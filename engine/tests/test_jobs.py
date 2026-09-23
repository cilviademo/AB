"""EXECUTE 1.2 gate: zero work on an unchanged re-run; a DECOMPILATION
stage_version bump re-runs only DECOMPILATION and later."""

import json

import pytest

from ab_engine import api
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs import runner
from ab_engine.jobs.model import STAGES, Job, StageRecord
from ab_engine.jobs.runner import StageContext, StageImpl, StageSkipped, register_stage
from ab_engine.jobs.store import ObjectStore


@pytest.fixture
def pipeline(ws, monkeypatch):
    """Nine counting stages; each records that it ran."""
    monkeypatch.setattr(runner, "_REGISTRY", {})
    runs: dict[str, int] = {s: 0 for s in STAGES}

    def make(stage):
        def run(ctx: StageContext):
            runs[stage] += 1
            ctx.output(f"{stage}.txt")
            (ctx.project_dir / f"{stage}.txt").write_text("x")
            ctx.metrics["n"] = runs[stage]
            ctx.completeness = "FAST_SCAN_COMPLETE" if stage == "STATIC_COMPLETE" else "NOT_APPLICABLE"
        return run

    for i, s in enumerate(STAGES):
        register_stage(StageImpl(s, version=1, run=make(s), config_keys=("deep_scan",) if s == "STATIC_COMPLETE" else ()))
    conn = jobs_db.connect(ws.db_path)
    job = Job("job1", "Fixture", "a" * 64, "OWNED", "2026-01-01T00:00:00+00:00", "/x/Fixture.vst3", str(ws.projects / "fixture"))
    jobs_db.upsert_job(conn, job)
    return conn, job, runs


def test_unchanged_rerun_does_zero_work(ws, pipeline):
    conn, job, runs = pipeline
    job, outcomes = runner.run_job(ws, conn, job)
    assert all(o == "run" for o in outcomes.values()) and all(v == 1 for v in runs.values())
    job, outcomes = runner.run_job(ws, conn, job)
    assert all(o == "reuse" for o in outcomes.values())
    assert all(v == 1 for v in runs.values()), "a stage ran again with unchanged inputs"
    # stage.json written for every stage with the contract envelope
    doc = json.loads((ws.projects / "fixture" / "stages" / "STATIC_COMPLETE.json").read_text())
    assert doc["schema"] == "artifactbench.stage" and doc["data"]["status"] == "OK"
    assert doc["data"]["completeness"] == "FAST_SCAN_COMPLETE"


def test_stage_version_bump_reruns_only_downstream(ws, pipeline):
    conn, job, runs = pipeline
    job, _ = runner.run_job(ws, conn, job)
    impl = runner._REGISTRY["DECOMPILATION_COMPLETE"]
    runner._REGISTRY["DECOMPILATION_COMPLETE"] = StageImpl(impl.stage, version=2, run=impl.run)
    job, outcomes = runner.run_job(ws, conn, job)
    before = STAGES[: STAGES.index("DECOMPILATION_COMPLETE")]
    after = STAGES[STAGES.index("DECOMPILATION_COMPLETE"):]
    assert all(outcomes[s] == "reuse" for s in before)
    assert all(outcomes[s] == "run" for s in after)
    assert all(runs[s] == 1 for s in before) and all(runs[s] == 2 for s in after)


def test_config_hash_only_covers_declared_keys(ws, pipeline):
    conn, job, runs = pipeline
    job, _ = runner.run_job(ws, conn, job)
    job, outcomes = runner.run_job(ws, conn, job, options={"unrelated": True})
    assert all(o == "reuse" for o in outcomes.values())
    job, outcomes = runner.run_job(ws, conn, job, options={"deep_scan": True})
    assert outcomes["INGESTED"] == "reuse" and outcomes["STATIC_COMPLETE"] == "run"
    assert outcomes["EXPORT_COMPLETE"] == "run"  # downstream invalidated


def test_failure_marks_stage_and_skips_downstream(ws, pipeline, monkeypatch):
    conn, job, runs = pipeline

    def boom(ctx):
        raise runner.StageFailed("PLUGIN_CRASH", "vst3host exited with 3")

    runner._REGISTRY["RUNTIME_COMPLETE"] = StageImpl("RUNTIME_COMPLETE", 1, boom)
    job, outcomes = runner.run_job(ws, conn, job)
    assert outcomes["RUNTIME_COMPLETE"] == "failed"
    rec = job.stage("RUNTIME_COMPLETE")
    assert rec.status == "FAILED" and rec.errors[0]["code"] == "PLUGIN_CRASH" and rec.cache_key == ""
    assert job.stage("DECOMPILATION_COMPLETE").status == "SKIPPED"
    assert job.stage("STATIC_COMPLETE").status == "OK"  # earlier outputs stay valid


def test_skipped_stage_is_reported_not_faked(ws, pipeline):
    conn, job, runs = pipeline

    def skip(ctx):
        raise StageSkipped("ghidra not installed")

    runner._REGISTRY["DECOMPILATION_COMPLETE"] = StageImpl("DECOMPILATION_COMPLETE", 1, skip)
    job, outcomes = runner.run_job(ws, conn, job)
    rec = job.stage("DECOMPILATION_COMPLETE")
    assert rec.status == "SKIPPED" and rec.skip_reason == "ghidra not installed"
    assert outcomes["BEHAVIOR_COMPLETE"] == "run"  # a skip does not block later stages


def test_object_store_refcounts_and_materialize(ws, tmp_path):
    conn = jobs_db.connect(ws.db_path)
    store = ObjectStore(ws.objects, conn)
    sha = store.put_bytes(b"hello")
    assert store.put_bytes(b"hello") == sha and jobs_db.object_refs(conn, sha) == 2
    src = tmp_path / "f.bin"
    src.write_bytes(b"\x00" * 100000)
    sha2, size = store.put_file(src)
    assert size == 100000 and store.get_path(sha2).stat().st_size == 100000
    out = store.materialize({"02_recovered_assets/images/a.bin": sha, "x/y.bin": sha2}, tmp_path / "out")
    assert (tmp_path / "out" / "02_recovered_assets" / "images" / "a.bin").read_bytes() == b"hello"
    assert len(out) == 2
    with pytest.raises(ValueError):
        store.materialize({"../escape": sha}, tmp_path / "out")
    store.release(sha)
    assert store.has(sha)
    store.release(sha)
    assert not store.has(sha) and jobs_db.object_refs(conn, sha) is None


def test_rpc_job_methods(ws, pipeline):
    conn, job, runs = pipeline
    assert api.dispatch("job.list", {}, ws)["jobs"][0]["job_id"] == "job1"
    plan = api.dispatch("job.plan", {"job_id": "job1"}, ws)["plan"]
    assert plan[0] == {"stage": "INGESTED", "action": "run"}
    result = api.dispatch("job.run", {"job_id": "job1", "stages": ["INGESTED", "STATIC_COMPLETE"]}, ws)
    assert result["outcomes"] == {"INGESTED": "run", "STATIC_COMPLETE": "run"}
    with pytest.raises(api.ApiError):
        api.dispatch("job.run", {"job_id": "job1", "stages": ["NOPE"]}, ws)
    assert api.dispatch("job.delete", {"job_id": "job1"}, ws) == {"deleted": "job1"}
    assert api.dispatch("job.list", {}, ws)["jobs"] == []


def test_stage_record_roundtrip(ws):
    conn = jobs_db.connect(ws.db_path)
    job = Job("j", "n", "b" * 64, "THIRD_PARTY", "2026", "/p", "/d", [StageRecord("j", "INGESTED", "OK", cache_key="k")])
    jobs_db.upsert_job(conn, job)
    back = jobs_db.get_job(conn, "j")
    assert back.stages[0].cache_key == "k" and back.reconstruction_allowed is False
