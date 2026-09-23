"""ADDENDUM B7: robustness and portability — adversarial inputs never execute or crash, paths stay portable, a fresh
machine gets AVAILABLE | MISSING | WRONG_VERSION | UNSUPPORTED with guidance, schemas migrate N → N+1 without
discarding evidence, exports round-trip, checkpoints are quiet."""
from __future__ import annotations

import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from ab_engine import api, checkpoint, deps, doctor
from ab_engine.bundle.api import tree_digest
from ab_engine.contracts import ContractError, read_json
from ab_engine.ingest import router
from ab_engine.jobs import db as jobs_db
from ab_engine.knowledge.db import SCHEMA_VERSION as KDB_VERSION, KnowledgeDB
from ab_engine.workspace import Workspace

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"


# ------------------------------------------------------------------ fuzz / adversarial parsers (no execution)
def test_adversarial_drop_is_inventoried_and_never_crashes(ws, tmp_path: Path):
    drop = tmp_path / "Adversarial Drop ünïcödé"
    (drop / "Malformed.vst3" / "Contents" / "x86_64-win").mkdir(parents=True)
    (drop / "Malformed.vst3" / "Contents" / "x86_64-win" / "Malformed.vst3").write_bytes(b"MZ" + b"\xff" * 4000)          # PE header, garbage body
    (drop / "Truncated.vst3").write_bytes(FIXTURE.read_bytes()[:200])                                                       # cut mid-header
    (drop / "broken.xml").write_text("<PARAMETERS><PARAM id='a' value='1'>", encoding="utf-8")                              # unclosed
    (drop / "corrupt.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"IHDR" + b"\xff" * 40)                                        # bad chunk walk
    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("deep/notes.txt", "nested")
    with zipfile.ZipFile(drop / "outer.zip", "w") as zf:
        zf.write(inner, "inner.zip")
        zf.writestr("../escape.txt", "traversal")
        zf.writestr("/abs.txt", "absolute")
    (drop / "a").mkdir(); (drop / "b").mkdir()
    (drop / "a" / "same.txt").write_text("one", encoding="utf-8"); (drop / "b" / "same.txt").write_text("two", encoding="utf-8")   # duplicate names, different bytes
    long_dir = drop / ("L" * 120) / ("M" * 120)
    long_dir.mkdir(parents=True)
    (long_dir / "deep file with spaces.txt").write_text("long", encoding="utf-8")
    for reserved in ("CON.txt", "aux.png", "NUL", "com1.wav", "trailing.", "dot..dot"):
        try:
            (drop / reserved).write_bytes(b"x")
        except OSError:
            pass                                                                                                             # Windows refuses these names itself
    (drop / "nothing.bin").write_bytes(b"")
    (drop / "Good Plugin.vst3").write_bytes(FIXTURE.read_bytes())                                                           # one real binary among the junk
    r = api.dispatch("ingest.run", {"paths": [str(drop)], "name": "Adversarial"}, ws)
    assert len(r["jobs"]) == 1, "the real binary yields the job; garbage never becomes a plugin"
    job = api.dispatch("job.run", {"job_id": r["jobs"][0]["job_id"], "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    statuses = {s["stage"]: s["status"] for s in job["stages"]}
    assert statuses["INGESTED"] == "OK" and statuses.get("STATIC_COMPLETE") in ("OK", "FAILED", "SKIPPED", "BLOCKED")        # never an exception, never a false green
    man = json.loads((Path(r["jobs"][0]["project_dir"]) / "00_manifest" / "input_manifest.json").read_text(encoding="utf-8"))["data"]
    names = {i["path"].split("/")[-1] for i in man["inputs"]}
    for n in ("Good Plugin.vst3", "Malformed.vst3", "Truncated.vst3", "broken.xml", "corrupt.png", "same.txt", "deep file with spaces.txt", "nothing.bin", "notes.txt"):
        assert n in names, n
    assert "escape.txt" not in names and "abs.txt" not in names                                                             # refused, not extracted
    assert all(i["status"] in ("IDENTIFIED", "PRESERVED_UNPARSED", "UNKNOWN_ARTIFACT") for i in man["inputs"])
    assert sum(1 for i in man["inputs"] if i["path"].endswith("same.txt")) == 2                                              # both kept: different bytes
    # the export of an adversarial project is still portable: no illegal path leaves
    e = api.dispatch("bundle.export", {"job_id": r["jobs"][0]["job_id"], "zip": False}, ws)
    assert isinstance(e["path_findings"], list)


def test_router_never_raises_on_garbage():
    for head in (b"", b"\x00", b"MZ", b"\x7fELF\xff", b"PK\x03\x04" + b"\xff" * 8, b"\x89PNG\r\n\x1a\n", b"<?xml", b"RIFF\x00\x00\x00\x00WAVE", b"\xff" * 64):
        for name in ("x", "x.vst3", "x.png", "x.xml", "x.zip", "CON", "a b/ü.dat", "x" * 300):
            r = router.identify(name, len(head), head)
            assert r["type"] in router.REGISTRY and r["status"] in ("ROUTED", "IDENTIFIED", "PRESERVED_UNPARSED", "UNKNOWN_ARTIFACT")


# ------------------------------------------------------------------ path portability
def test_export_from_unicode_spaced_paths_has_no_findings_and_no_machine_roots(tmp_path: Path):
    home = tmp_path / "Wörk Space ✓" / "AB"
    ws = Workspace.open(home)
    drop = tmp_path / "Plüg ins" / "My Plugin (v2).vst3"
    drop.parent.mkdir(parents=True)
    drop.write_bytes(FIXTURE.read_bytes())
    r = api.dispatch("ingest.run", {"paths": [str(drop)], "name": "My Plugin (v2)"}, ws)
    api.dispatch("job.run", {"job_id": r["jobs"][0]["job_id"], "stages": ["INGESTED"]}, ws)
    e = api.dispatch("bundle.export", {"job_id": r["jobs"][0]["job_id"], "zip": True}, ws)
    assert e["path_findings"] == [] and e["secret_findings"] == []
    out = Path(e["out_dir"])
    assert out.name == "My_Plugin_v2_RECOVERED" and Path(e["zip_path"]).is_file()
    text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in out.rglob("*.json"))
    assert str(tmp_path) not in text and "Wörk Space" not in text                                                            # this machine's roots never leave


# ------------------------------------------------------------------ fresh machine
def test_fresh_machine_dependency_statuses_and_guidance(ws, monkeypatch):
    d = deps.check("numpy")
    assert d.status == "AVAILABLE" and d.guidance == ""
    monkeypatch.setattr(deps.importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError("no")))
    m = deps.check("lief")
    assert m.status == "MISSING" and "pip install" in m.guidance and "lief==1.0.0" in m.guidance
    monkeypatch.undo()
    monkeypatch.setattr(deps.md, "version", lambda dist: "0.0.1")
    w = deps.check("capstone")
    assert w.status == "WRONG_VERSION" and "capstone==5.0.9" in w.guidance
    monkeypatch.undo()
    rep = doctor.run(ws)
    assert set(rep["dependency_status"]) == {"AVAILABLE", "MISSING", "WRONG_VERSION", "UNSUPPORTED"}
    assert all(("status" in r) == (r["name"].startswith(("dep:", "tool:", "engine"))) for r in rep["rows"])
    for s in rep["setup"]:
        assert s["status"] in ("MISSING", "WRONG_VERSION", "UNSUPPORTED") and s["guidance"]
    # an old interpreter is UNSUPPORTED with guidance, and a tool probe that raises becomes a row — never a crash
    monkeypatch.setattr(sys, "version_info", (3, 9, 0, "final", 0))
    assert next(r for r in doctor.run(ws)["rows"] if r["name"] == "engine")["status"] == "UNSUPPORTED"
    monkeypatch.undo()
    monkeypatch.setattr(doctor.tools_mod, "all_tools", lambda ws: (_ for _ in ()).throw(RuntimeError("boom")))
    rep2 = doctor.run(ws)
    assert any(r["name"] == "tool:probe" and r["status"] == "MISSING" for r in rep2["rows"])
    txt = doctor.report(rep2)
    assert "MISSING" in txt


# ------------------------------------------------------------------ migrations: N → N+1, old evidence never discarded
def test_jobs_db_migrates_old_schema_and_refuses_newer(tmp_path: Path):
    old = tmp_path / "jobs.db"
    c = sqlite3.connect(str(old))
    c.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_version', '1');
        CREATE TABLE jobs (job_id TEXT PRIMARY KEY, name TEXT NOT NULL, artifact_sha256 TEXT NOT NULL, ownership TEXT NOT NULL, created TEXT NOT NULL, primary_path TEXT NOT NULL, project_dir TEXT NOT NULL);
        INSERT INTO jobs VALUES ('ab-old', 'Old', 'a', 'OWNED', '2026-01-01', 'p', '/x');
        CREATE TABLE stages (job_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL, input_hashes TEXT NOT NULL, tool_versions TEXT NOT NULL, config_hash TEXT NOT NULL, stage_version INTEGER NOT NULL, started TEXT, ended TEXT, warnings TEXT NOT NULL, errors TEXT NOT NULL, outputs TEXT NOT NULL, completeness TEXT NOT NULL, metrics TEXT NOT NULL, skip_reason TEXT, cache_key TEXT NOT NULL, PRIMARY KEY (job_id, stage));
        CREATE TABLE inputs (job_id TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, kind TEXT NOT NULL, attached_to TEXT);
        CREATE TABLE objects (sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, refs INTEGER NOT NULL DEFAULT 0);
    """)
    c.commit(); c.close()
    conn = jobs_db.connect(old)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert "source_availability" in cols
    j = jobs_db.get_job(conn, "ab-old")
    assert j is not None and j.name == "Old" and j.usage_context == "USER_RECOVERY" and j.source_availability == "SOURCE_UNKNOWN"   # legacy OWNED read through the alias, row kept
    conn.close()
    newer = tmp_path / "newer.db"
    c = sqlite3.connect(str(newer))
    c.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL); INSERT INTO meta VALUES ('schema_version', '99');")
    c.commit(); c.close()
    with pytest.raises(RuntimeError):
        jobs_db.connect(newer)


def test_knowledge_db_migrates_and_refuses_newer(tmp_path: Path):
    root = tmp_path / "k"
    root.mkdir()
    c = sqlite3.connect(str(root / "knowledge.db"))
    c.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES ('schema_version', '1');
        CREATE TABLE implementation (impl_id TEXT PRIMARY KEY, name_hint TEXT, member_fp_ids TEXT, family_id TEXT, state TEXT, behavior_ref TEXT, first_seen TEXT, last_verified TEXT, source_hashes TEXT);
        INSERT INTO implementation VALUES ('i1', 'Old', '[]', 'f', 'BEHAVIOR_MATCHED', NULL, 't0', 't0', '["a"]');
    """)
    c.commit(); c.close()
    db = KnowledgeDB(root)
    row = db.db.execute("SELECT * FROM implementation WHERE impl_id='i1'").fetchone()
    assert row["tier"] == "RECOVERED_IMPLEMENTATION_KNOWLEDGE" and row["state"] == "BEHAVIOR_MATCHED"                       # migrated in place, nothing discarded
    assert db.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(KDB_VERSION)
    db.db.close()
    root2 = tmp_path / "k2"
    root2.mkdir()
    c = sqlite3.connect(str(root2 / "knowledge.db"))
    c.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES ('schema_version', '99');")
    c.commit(); c.close()
    with pytest.raises(RuntimeError):
        KnowledgeDB(root2)


def test_contract_major_version_is_never_reinterpreted(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"schema": "artifactbench.hashes", "schema_version": 2, "tool": "t", "generated": "now", "data": {}}), encoding="utf-8")
    with pytest.raises(ContractError):
        read_json(p)


# ------------------------------------------------------------------ export round-trip
def test_export_round_trip_restores_identical_state(ws, tmp_path: Path):
    r = api.dispatch("ingest.run", {"paths": [str(FIXTURE)], "name": "SynthPlug"}, ws)["jobs"][0]
    before = api.dispatch("job.run", {"job_id": r["job_id"], "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    e = api.dispatch("bundle.export", {"job_id": r["job_id"], "zip": True}, ws)
    assert (Path(e["out_dir"]) / "evidence" / "00_manifest" / "stages.json").is_file()
    ws2 = Workspace.open(tmp_path / "second machine")
    imp = api.dispatch("bundle.import", {"path": e["zip_path"]}, ws2)
    assert imp["job_id"] == r["job_id"] and imp["evidence_identical"] and imp["stage_records_found"] and imp["missing_evidence_dirs"] == []
    after = api.dispatch("job.get", {"job_id": r["job_id"]}, ws2)
    for k in ("job_id", "name", "artifact_sha256", "usage_context", "source_availability", "created", "primary"):
        assert after[k] == before[k], k
    assert [(s["stage"], s["status"], s["cache_key"], s["stage_version"]) for s in after["stages"]] == [(s["stage"], s["status"], s["cache_key"], s["stage_version"]) for s in before["stages"] if s["stage"] != "EXPORT_COMPLETE"]
    # the evidence tree is byte-identical on both machines
    d1 = tree_digest(Path(before["project_dir"]), skip=("ingest.json",))
    d2 = tree_digest(Path(after["project_dir"]), skip=("ingest.json",))
    ev1 = {k: v for k, v in d1.items() if k.split("/")[0] in ("00_manifest", "01_evidence", "02_recovered_assets", "03_architecture", "05_reference_behavior")}
    assert ev1 and all(d2.get(k) == v for k, v in ev1.items())
    # re-exporting from the imported project yields the same evidence again; a second import is refused unless replace
    e2 = api.dispatch("bundle.export", {"job_id": r["job_id"], "zip": False}, ws2)
    skip = ("00_manifest/export_report.json", "knowledge_used.json", "00_manifest/stages.json")
    assert tree_digest(Path(e["out_dir"]) / "evidence", skip=skip) == tree_digest(Path(e2["out_dir"]) / "evidence", skip=skip)
    with pytest.raises(api.ApiError):
        api.dispatch("bundle.import", {"path": e["out_dir"]}, ws2)
    assert api.dispatch("bundle.import", {"path": e["out_dir"], "replace": True}, ws2)["evidence_identical"]
    with pytest.raises(api.ApiError):
        api.dispatch("bundle.import", {"path": str(tmp_path)}, ws2)                                                           # not an export: says so


# ------------------------------------------------------------------ checkpoints: every stage has a message, no noise commits
@pytest.mark.skipif(not checkpoint.available(), reason="git")
def test_checkpoints_cover_every_stage_without_noise(tmp_path: Path):
    for stage in ("INGESTED", "STATIC_COMPLETE", "RUNTIME_COMPLETE", "DECOMPILATION_COMPLETE", "RECONSTRUCTION_COMPLETE", "VALIDATION_COMPLETE"):
        assert stage in checkpoint.PREFIX
    p = tmp_path / "proj"
    checkpoint.init(p)
    (p / "00_manifest").mkdir(); (p / "00_manifest" / "m.json").write_text("{}")
    assert checkpoint.commit(p, "INGESTED")["status"] == "COMMITTED"
    for stage in ("STATIC_COMPLETE", "RUNTIME_COMPLETE", "DECOMPILATION_COMPLETE"):
        assert checkpoint.commit(p, stage)["status"] == "NOTHING_TO_COMMIT"                                                  # nothing changed → no commit
    (p / "01_evidence").mkdir(); (p / "01_evidence" / "e.json").write_text("{}")
    assert checkpoint.commit(p, "STATIC_COMPLETE")["message"].startswith("recovery: add static evidence")
    (p / "01_evidence" / "rtti.json").write_text("{}")
    assert checkpoint.commit(p, "DECOMPILATION_COMPLETE")["message"] == "recovery: add RTTI and callgraph evidence"
    assert len(checkpoint.log(p)) == 3 and checkpoint.status_clean(p)
