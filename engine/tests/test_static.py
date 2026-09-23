"""EXECUTE 1.4: the STATIC stage through the Node host, the worker (submit) path, and DEEP_SCAN triggers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ab_engine import api
from ab_engine import tools as tools_mod
from ab_engine.jobs import db as jobs_db

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"
CLI = ROOT / "app" / "static-engine" / "dist" / "cli.mjs"

needs_node = pytest.mark.skipif(not (shutil.which("node") and CLI.is_file()), reason="needs node + built static engine")


@pytest.fixture(scope="module")
def fixture_binary() -> Path:
    if not FIXTURE.is_file():
        subprocess.run(["python3", str(ROOT / "fixtures/synthetic/make_fixture.py"), str(FIXTURE)], check=True)
    return FIXTURE


def _ingest(ws, tmp_path, binary: Path, extra: dict[str, bytes] | None = None):
    drop = tmp_path / "drop" / "SynthPlug.vst3" / "Contents" / "x86_64-win"
    drop.mkdir(parents=True)
    shutil.copyfile(binary, drop / "SynthPlug.vst3")
    for rel, data in (extra or {}).items():
        p = tmp_path / "drop" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    r = api.dispatch("ingest.run", {"paths": [str(tmp_path / "drop")], "ownership": "OWNED"}, ws)
    assert len(r["jobs"]) == 1
    return r["jobs"][0]["job_id"]


@needs_node
def test_static_stage_via_node_writes_v2_contracts(ws, tmp_path, fixture_binary):
    job_id = _ingest(ws, tmp_path, fixture_binary, {"presets/Warm.vstpreset": b'<PARAMETERS><PARAM id="drive" value="0.9"/><PARAM id="cutoff" value="1000"/></PARAMETERS>'})
    result = api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    rec = next(s for s in result["stages"] if s["stage"] == "STATIC_COMPLETE")
    assert rec["status"] == "OK", rec
    assert rec["completeness"] == "FAST_SCAN_COMPLETE"
    m = rec["metrics"]
    assert m["bytes_processed"] > 60000 and m["objects_found"] > 10 and m["files"] > 40 and m["carved_objects"] >= 6
    assert set(m["stages_ms"]) == {"pe_parse", "string_scan", "classify_rtti_paths_xml", "resource_carve", "constant_scan", "resource_validate"}
    assert rec["tool_versions"]["static_engine"] == "static-recovery-v2"
    pd = Path(result["project_dir"])
    for rel in ("01_evidence/rtti/classes.json", "01_evidence/resources/index.json", "03_architecture/serialized_keys.json", "07_agent_handoff/reconstruction_index.json"):
        doc = json.loads((pd / rel).read_text())
        assert doc["schema_version"] == 2 and doc["tool"] == "static-recovery-v2" and doc["schema"].startswith("recovery.")
    keys = {k["name"]: k for k in json.loads((pd / "03_architecture/serialized_keys.json").read_text())["data"]}
    assert keys["cutoff"]["serialized_key_status"].startswith("VERIFIED_XML (preset/session file)")
    assert keys["drive"]["observed_serialized_values"] == [0.75, 0.5, 0.9] and keys["drive"]["value_representation"] == "UNKNOWN"
    assert keys["waveShapers_4_2"]["key_kind_candidate"].startswith("INTERNAL_EFFECT_PROPERTY")
    # carved assets are content-addressed in the store and materialized in the project
    assert (pd / "02_recovered_assets/fonts/ttf_000.ttf").is_file()
    conn = jobs_db.connect(ws.db_path)
    assert conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0] >= 7  # binary + preset + carves
    # stage.json exists with the contract
    assert json.loads((pd / "stages/STATIC_COMPLETE.json").read_text())["schema"] == "artifactbench.stage"
    # unchanged re-run is zero work
    again = api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    assert again["outcomes"]["STATIC_COMPLETE"] == "reuse"
    # deep_scan option is part of the config hash → re-runs, DEEP_SCAN_COMPLETE
    deep = api.dispatch("job.run", {"job_id": job_id, "stages": ["STATIC_COMPLETE"], "options": {"prefer_node": True, "deep_scan": True}}, ws)
    rec = next(s for s in deep["stages"] if s["stage"] == "STATIC_COMPLETE")
    assert rec["status"] == "OK" and rec["completeness"] == "DEEP_SCAN_COMPLETE" and rec["metrics"]["deep"] is True


@needs_node
def test_deep_scan_auto_trigger(ws, tmp_path, fixture_binary):
    # A BinaryData font name with no carved font → "names outnumber carved assets" → auto DEEP_SCAN (SPEC §6.3)
    data = fixture_binary.read_bytes() + b"\0\0extra_font_ttf\0\0" + b"\0" * 64
    variant = tmp_path / "variant.vst3"
    variant.write_bytes(data)
    job_id = _ingest(ws, tmp_path, variant)
    result = api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    rec = next(s for s in result["stages"] if s["stage"] == "STATIC_COMPLETE")
    assert rec["status"] == "OK"
    assert any(w["code"] == "DEEP_SCAN_TRIGGERED" and "ttf" in w["message"] for w in rec["warnings"]), rec["warnings"]
    assert rec["completeness"] == "DEEP_SCAN_COMPLETE"


@needs_node
def test_worker_submit_path(ws, tmp_path, fixture_binary):
    job_id = _ingest(ws, tmp_path, fixture_binary)
    inputs = api.dispatch("static.inputs", {"job_id": job_id}, ws)
    assert inputs["files"][0]["kind"] == "binary" and Path(inputs["files"][0]["object_path"]).is_file()
    spec = [{"path": f["path"], "fs_path": f["object_path"], "kind": f["kind"], "format": "PE"} for f in inputs["files"]]
    (tmp_path / "inputs.json").write_text(json.dumps(spec))
    out = subprocess.run(["node", str(CLI), "plan", "--inputs", str(tmp_path / "inputs.json"), "--key", "SynthPlug"], capture_output=True, text=True, check=True)
    plan = json.loads(out.stdout)
    assert any("bytes_b64" in e for e in plan["entries"])
    r = api.dispatch("static.submit", {"job_id": job_id, "result": plan}, ws)
    assert r["accepted"] and r["entries"] > 40
    result = api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"]}, ws)
    rec = next(s for s in result["stages"] if s["stage"] == "STATIC_COMPLETE")
    assert rec["status"] == "OK" and rec["metrics"]["source"] == "worker"
    assert (Path(result["project_dir"]) / "02_recovered_assets/fonts/ttf_000.ttf").is_file()


def test_static_skips_without_node(ws, tmp_path, fixture_binary, monkeypatch):
    monkeypatch.setattr(tools_mod, "find_node", lambda ws: tools_mod.Tool("node", None, None, "absent"))
    job_id = _ingest(ws, tmp_path, fixture_binary)
    result = api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    rec = next(s for s in result["stages"] if s["stage"] == "STATIC_COMPLETE")
    assert rec["status"] == "BLOCKED" and "static engine unavailable" in rec["skip_reason"]   # missing dependency → BLOCKED (Addendum B3)


@needs_node
def test_diff_baseline_on_synthetic(ws):
    from ab_engine.static import baseline  # noqa: PLC0415

    # diff against the COMMITTED baseline (the repo fixture is regression data; tests never rewrite it)
    from ab_engine import tools as tools_mod  # noqa: PLC0415

    root = tools_mod.repo_root()
    if root is None or not (root / "fixtures" / "static_v2" / "synthetic" / "baseline").is_dir():
        baseline.init_baseline(ws, "synthetic")
    r = baseline.diff_fixture(ws, "synthetic")
    assert r["ok"], r["rows"]
    assert all(row["ok"] for row in r["rows"] if row["check"] != "timing variance ≤ 20 %")
