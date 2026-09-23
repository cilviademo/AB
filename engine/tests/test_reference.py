"""ADDENDUM B6: reference library — typed entries with full provenance, explicit actions (never inferred from a
co-drop), "where did AB learn this?", fixture-source isolation, ground-truth dashboard as counts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ab_engine import api, cli
from ab_engine.contracts import read_json
from ab_engine.jobs.model import Job
from ab_engine.knowledge.db import KnowledgeDB
from ab_engine.reference import library

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"


def _variant(tmp_path: Path, tag: bytes) -> Path:
    """A byte-distinct copy of the synthetic PE (dedupe is by hash, so a second job needs different bytes)."""
    p = tmp_path / f"SynthPlug_{tag.decode()}.vst3"
    p.write_bytes(FIXTURE.read_bytes() + b"\0" * 16 + tag)
    return p


def _fp(i: int, name=None):
    norm = hashlib.sha256(f"norm{i}".encode()).hexdigest()
    return {"addr": f"0x{0x1000 + i * 0x40:x}", "size": 200, "name": name, "RAW_BYTE_HASH": hashlib.sha256(f"raw{i}".encode()).hexdigest(),
            "NORMALIZED_INSTRUCTION_HASH": norm, "CFG_SIGNATURE": {"blocks": 3, "hash": hashlib.sha256(f"cfg{i}".encode()).hexdigest()},
            "CONSTANT_SIGNATURE": [1.5, 3], "STRING_XREF_SIGNATURE": "", "CALLGRAPH_SIGNATURE": hashlib.sha256(f"cg{i}".encode()).hexdigest(), "TLSH": None}


def test_entries_are_typed_by_context_with_provenance_and_explicit_actions(ws, tmp_path: Path):
    a = api.dispatch("ingest.run", {"paths": [str(FIXTURE)], "name": "Mine"}, ws)["jobs"][0]
    b = api.dispatch("ingest.run", {"paths": [str(_variant(tmp_path, b"fx"))], "name": "Fixture", "usage_context": "KNOWN_SOURCE_FIXTURE", "source_availability": "KNOWN_SOURCE_GROUND_TRUTH"}, ws)["jobs"][0]
    for j in (a, b):
        api.dispatch("job.run", {"job_id": j["job_id"], "stages": ["INGESTED"]}, ws)
    lib = api.dispatch("reference.list", {}, ws)
    by_id = {e["id"]: e for e in lib["entries"]}
    ea, eb = by_id[a["job_id"]], by_id[b["job_id"]]
    assert ea["entry_type"] == "USER_ARTIFACT" and eb["entry_type"] == "KNOWN_SOURCE_FIXTURE"
    for e in (ea, eb):                                   # every entry answers origin / source / licence / hash / version / evidence / date / relationships
        for k in ("origin", "source_artifact", "license", "hash", "analysis_version", "evidence_state", "verification_date", "relationships", "knowledge_learned"):
            assert k in e, k
        assert e["evidence_state"].get("INGESTED") == "OK" and e["verification_date"]
    assert ea["license"]["class"] == "USER_OWNED_OR_UNSTATED"
    assert eb["fixture"]["fixture_id"] is None and "truth.json" in eb["fixture"]["note"]   # declared, not proven: no manifest names this hash
    # actions are explicit and typed; nothing was applied by dropping two plugins next to each other
    assert {x["id"] for x in ea["actions"]} == {"COMPARE_AGAINST_REFERENCE", "ADD_AS_FIXTURE", "USE_AS_BLACK_BOX_REFERENCE"}
    assert {x["id"] for x in eb["actions"]} == {"VALIDATE_RECOVERY_AGAINST_SOURCE", "COMPARE_AGAINST_REFERENCE"}
    assert api.dispatch("job.get", {"job_id": a["job_id"]}, ws)["usage_context"] == "USER_RECOVERY"
    # the clean-room DSP reference package: typed, licensed, hashed, CANDIDATE only
    dsp = [e for e in lib["entries"] if e["entry_type"] == "DSP_REFERENCE"]
    assert len(dsp) == 33 and all(e["license"]["text"] == "MIT License" and len(e["hash"] or "") == 64 and e["evidence_state"] == "CANDIDATE" and e["actions"] == [] for e in dsp)
    assert lib["counts"]["USER_ARTIFACT"] == 1 and lib["counts"]["KNOWN_SOURCE_FIXTURE"] == 1 and lib["counts"]["DSP_REFERENCE"] == 33
    assert lib["isolation"]["ok"] and lib["isolation"]["checked_projects"] == 0     # nothing reconstructed yet: nothing to leak
    # reports on disk, contract-validated
    doc = read_json(Path(lib["written"]["json"]), expect="artifactbench.reference_library")
    assert doc["data"]["counts"] == lib["counts"]
    md = Path(lib["written"]["markdown"]).read_text(encoding="utf-8")
    assert "| DSP_REFERENCE | 33 |" in md and "Fixture-source isolation: **OK**" in md


def test_set_context_is_explicit_recorded_and_interpretation_only(ws):
    a = api.dispatch("ingest.run", {"paths": [str(FIXTURE)], "name": "Mine"}, ws)["jobs"][0]
    api.dispatch("job.run", {"job_id": a["job_id"], "stages": ["INGESTED"]}, ws)
    with pytest.raises(api.ApiError):
        api.dispatch("reference.set_context", {"job_id": a["job_id"]}, ws)          # no silent default: the action names its target
    r = api.dispatch("reference.set_context", {"job_id": a["job_id"], "usage_context": "BLACK_BOX_REFERENCE"}, ws)
    assert r["before"]["usage_context"] == "USER_RECOVERY" and r["after"]["usage_context"] == "BLACK_BOX_REFERENCE" and r["entry_type"] == "BLACK_BOX_REFERENCE"
    job = api.dispatch("job.get", {"job_id": a["job_id"]}, ws)
    assert job["usage_context"] == "BLACK_BOX_REFERENCE" and job["stages"][0]["status"] == "OK"     # stage outputs untouched
    man = read_json(Path(a["project_dir"]) / "00_manifest" / "input_manifest.json", expect="artifactbench.input_manifest")["data"]
    assert man["usage_context"] == "BLACK_BOX_REFERENCE" and man["context_history"][-1]["from"]["usage_context"] == "USER_RECOVERY" and man["context_history"][-1]["by"] == "reference.set_context"
    lib = api.dispatch("reference.list", {"write": False}, ws)
    e = next(x for x in lib["entries"] if x["id"] == a["job_id"])
    assert e["entry_type"] == "BLACK_BOX_REFERENCE" and e["actions"] == []                  # alone on the bench: nothing to compare against
    # re-typing never loses the job's inputs (an INSERT OR REPLACE upsert once cascaded them away) — the pipeline still runs
    from ab_engine.jobs import db as jobs_db
    assert [i["kind"] for i in jobs_db.get_inputs(jobs_db.connect(ws.db_path), a["job_id"])] == ["binary"]
    assert api.dispatch("job.run", {"job_id": a["job_id"], "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)["stages"][1]["status"] == "OK"


def test_provenance_answers_where_ab_learned_this(tmp_path: Path):
    db = KnowledgeDB(tmp_path / "k")
    db.record_artifact("a" * 64, kind="binary", size=10, ownership="USER_RECOVERY", name="Mine")
    db.record_artifact("f" * 64, kind="binary", size=10, ownership="KNOWN_SOURCE_FIXTURE", name="ABGroundTruth")
    fps = [_fp(i, name="juce::Thing" if i % 2 else None) for i in range(4)]
    db.record_functions("a" * 64, fps[:2], source="test", tool_version="t", evidence_version="e", kind_of=lambda fp: "KNOWN_FRAMEWORK" if (fp.get("name") or "").startswith("juce::") else None)
    db.record_functions("f" * 64, fps[2:], source="test", tool_version="t", evidence_version="e", kind_of=lambda fp: "KNOWN_FRAMEWORK" if (fp.get("name") or "").startswith("juce::") else None)
    db.close() if hasattr(db, "close") else None
    import sqlite3
    conn = sqlite3.connect(str(next((tmp_path / "k").glob("*.db"))))
    conn.row_factory = sqlite3.Row
    r = library.provenance(conn, "juce::Thing")
    assert len(r["hits"]) == 2 and all(h["entity_type"] == "function" and h["kind"] == "KNOWN_FRAMEWORK" for h in r["hits"])
    origins = {(a["name"], a["entry_type"]) for h in r["hits"] for a in h["learned_from"]}
    assert origins == {("Mine", "USER_ARTIFACT"), ("ABGroundTruth", "KNOWN_SOURCE_FIXTURE")}
    assert r["fixture_derived"] == 1 and all(h["occurrences"] and h["last_verified"] and h["tool_version"] == "t" for h in r["hits"])
    assert library.provenance(conn, "nothing-like-this")["hits"] == [] and library.provenance(None, "x")["hits"] == []
    fw = library.framework_entries(conn)
    e = next(x for x in fw if x["id"] == "fw:KNOWN_FRAMEWORK")
    assert e["functions"] == 2 and {a["usage_context"] for a in e["source_artifact"]} == {"USER_RECOVERY", "KNOWN_SOURCE_FIXTURE"} and e["license"]["class"] == "THIRD_PARTY_SIGNATURES"


def _job(tmp_path: Path, jid: str, ctx: str) -> Job:
    pd = tmp_path / jid
    (pd / "04_reconstruction" / "Source").mkdir(parents=True)
    return Job(jid, jid, hashlib.sha256(jid.encode()).hexdigest(), ctx, "2026-01-01T00:00:00Z", "x.vst3", str(pd))


def test_fixture_source_never_enters_a_user_recovery(tmp_path: Path):
    fx = tmp_path / "fixture" / "Source"
    fx.mkdir(parents=True)
    (fx / "Secret.h").write_text("// fixture source: a hand-written class that must never be copied into a user's recovery\nstruct S { float f (float x) { return x; } };\n", encoding="utf-8")
    (fx / "tiny.h").write_text("#pragma once\n", encoding="utf-8")                 # trivially small: not source evidence
    user = _job(tmp_path, "user", "USER_RECOVERY")
    fixture_job = _job(tmp_path, "fixt", "KNOWN_SOURCE_FIXTURE")
    for j in (user, fixture_job):
        (Path(j.project_dir) / "04_reconstruction" / "Source" / "Gen.h").write_text("// generated by AB from evidence — plenty of bytes so it is not trivially small\nstruct G {};\n", encoding="utf-8")
    ok = library.fixture_source_isolation([user, fixture_job], fixture_source_dirs=[fx])
    assert ok["ok"] and ok["checked_projects"] == 1 and ok["fixture_files"] == 1
    (Path(user.project_dir) / "04_reconstruction" / "Source" / "Copied.h").write_bytes((fx / "Secret.h").read_bytes())
    bad = library.fixture_source_isolation([user, fixture_job], fixture_source_dirs=[fx])
    assert not bad["ok"] and bad["violations"][0]["job_id"] == "user" and bad["violations"][0]["file"].endswith("Copied.h")
    (Path(fixture_job.project_dir) / "04_reconstruction" / "Source" / "Own.h").write_bytes((fx / "Secret.h").read_bytes())   # the fixture's own project may hold its source
    assert len(library.fixture_source_isolation([user, fixture_job], fixture_source_dirs=[fx])["violations"]) == 1


def test_dashboard_is_counts_not_a_percentage():
    rep = {"metrics": {"parameters": {"expected": 8, "found": 8}, "state_fields_mapped": {"expected": 8, "correct": 7}, "rtti_classes_recovered": {"expected": 35, "recovered": 31},
                       "process_block_path": {"processBlock": True, "prepareToPlay": True, "state_functions": False, "basis": "symbol"}, "resources": {"expected": 12, "valid_exact": 12},
                       "waveshaper_differential": {"worst_rmse": 6.8e-05, "classification": "BEHAVIORALLY_EQUIVALENT"}},
           "gates": [{"ok": True}, {"ok": False}, {"ok": None}], "false_positives": [1], "false_negatives": []}
    d = library.dashboard(rep)
    assert d["parameter_recall"] == {"n": 8, "of": 8} and d["state_mapping"] == {"n": 7, "of": 8} and d["classes"] == {"n": 31, "of": 35}
    assert d["dsp_entry_points"] == {"n": 2, "of": 3} and d["resources"] == {"n": 12, "of": 12} and d["false_positives"] == 1 and d["behavioral_rmse"] == 6.8e-05
    assert d["gates"] == {"ok": 1, "failed": 1, "pending": 1} and library.dashboard(None) is None


def test_cli_reference_and_dashboard(ws, capsys):
    a = api.dispatch("ingest.run", {"paths": [str(FIXTURE)], "name": "Mine"}, ws)["jobs"][0]
    api.dispatch("job.run", {"job_id": a["job_id"], "stages": ["INGESTED"]}, ws)
    assert cli.main(["--workspace", str(ws.home), "--text", "reference"]) == 0
    out = capsys.readouterr().out
    assert "# REFERENCE_LIBRARY" in out and "USER_ARTIFACT | 1" in out
    assert cli.main(["--workspace", str(ws.home), "--text", "reference", "--dashboard", a["job_id"]]) == 1      # no ground-truth report: says so, never invents counts
    assert "no ground-truth report" in capsys.readouterr().out
    assert cli.main(["--workspace", str(ws.home), "reference", "--provenance", "anything"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["hits"] == []
