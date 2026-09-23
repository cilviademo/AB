"""EXECUTE 1.5 gate: path and secret scanners run on every export and pass on the fixtures."""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from ab_engine import api
from ab_engine.bundle.scan import scan_paths, scan_secrets, scrub_machine_paths

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"
CLI = ROOT / "app" / "static-engine" / "dist" / "cli.mjs"
needs_node = pytest.mark.skipif(not (shutil.which("node") and CLI.is_file()), reason="needs node + built static engine")


def test_path_scanner_finds_windows_illegal_names(tmp_path):
    for rel in ("ok/file.txt", "bad/CON.cpp", "bad/what?.h", "bad/trailing. ", "bad/über.png", "case/A.txt", "case/a.txt"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    kinds = {f["kind"] for f in scan_paths(tmp_path)}
    assert {"reserved_name", "invalid_char", "trailing_dot_space", "non_ascii", "case_collision"} <= kinds
    assert not [f for f in scan_paths(tmp_path) if f["path"] == "ok/file.txt"]


def test_secret_scanner(tmp_path):
    (tmp_path / "04_reconstruction").mkdir()
    (tmp_path / "04_reconstruction" / "a.cpp").write_text('const char* k = "AKIAABCDEFGHIJKLMNOP";\n// path C:\\Users\\marc\\dev\\x\nstd::string t = "ghp_abcdefghijklmnopqrstuvwxyz0123";\n')
    (tmp_path / "01_evidence" / "paths").mkdir(parents=True)
    (tmp_path / "01_evidence" / "paths" / "build_path_evidence.json").write_text('{"data":[{"path":"C:\\\\Users\\\\dev\\\\Source\\\\x.cpp"}]}')
    f = scan_secrets(tmp_path)
    kinds = sorted(x["kind"] for x in f)
    assert "aws_access_key" in kinds and "github_token" in kinds and "windows_user_path" in kinds
    assert all(x["path"].startswith("04_") for x in f), "evidence paths are exempt from the machine-path rule"
    assert all("AKIAABCDEFGHIJKLMNOP" not in x["excerpt"] for x in f), "excerpts are redacted"


@needs_node
def test_export_runs_scanners_and_git_ready(ws, tmp_path):
    drop = tmp_path / "drop" / "SynthPlug.vst3" / "Contents" / "x86_64-win"
    drop.mkdir(parents=True)
    shutil.copyfile(FIXTURE, drop / "SynthPlug.vst3")
    job_id = api.dispatch("ingest.run", {"paths": [str(tmp_path / "drop")], "ownership": "OWNED"}, ws)["jobs"][0]["job_id"]
    api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    tree = api.dispatch("bundle.tree", {"job_id": job_id}, ws)["entries"]
    paths = {e["path"] for e in tree}
    assert "01_evidence/rtti/classes.json" in paths
    assert next(e for e in tree if e["path"] == "01_evidence/rtti/classes.json")["schema"] == "recovery.classes v2"
    read = api.dispatch("bundle.read", {"job_id": job_id, "path": "03_architecture/serialized_keys.json"}, ws)
    assert read["schema"] == "recovery.serialized_keys v2" and '"drive"' in read["text"]
    with pytest.raises(api.ApiError):
        api.dispatch("bundle.read", {"job_id": job_id, "path": "../../etc/passwd"}, ws)
    cells = {c["key"]: c for c in api.dispatch("bundle.scorecard", {"job_id": job_id}, ws)["cells"]}
    assert cells["Original source"]["value"] == "0 %" and cells["Original source"]["evidence"] == "UNRECOVERABLE"
    assert cells["Runtime parameters"]["value"] == "UNVERIFIED"
    assert cells["State schema"]["value"].startswith("3 keys (1 STATE_FIELD_CANDIDATE)")
    assert cells["Resources"]["value"].startswith("6 / 7 VALID_EXACT")

    r = api.dispatch("bundle.export", {"job_id": job_id, "zip": True}, ws)
    out = Path(r["out_dir"])
    assert out.name.endswith("_RECOVERED") and (out / "UNRECOVERABLE.md").is_file() and (out / "CMakeLists.txt").is_file()
    assert (out / "Source" / "Active").is_dir() and (out / "HANDOFF.md").is_file() and (out / "reconstruction_index.json").is_file()
    assert (out / "evidence" / "02_recovered_assets" / "fonts" / "ttf_000.ttf").is_file() and (out / "evidence" / "01_evidence" / "rtti" / "classes.json").is_file()
    assert r["path_findings"] == [] and r["secret_findings"] == []
    checks = {c["name"]: c for c in r["git_ready"]["checks"]}
    assert checks["legal filenames"]["ok"] and checks["no secrets"]["ok"] and checks["no machine paths"]["ok"]
    assert checks["configure/build passed"]["ok"] is None  # pending, never shown as passed
    assert r["git_ready"]["ok"] is True
    with zipfile.ZipFile(r["zip_path"]) as zf:
        assert any(n.endswith("/UNRECOVERABLE.md") for n in zf.namelist())
    report = json.loads((out / "evidence" / "00_manifest" / "export_report.json").read_text())
    assert report["schema"] == "artifactbench.export_report" and report["data"]["layout"].startswith("A7")


@needs_node
def test_context_changes_wording_never_capability(ws, tmp_path):
    """Gate C1: every usage_context runs the same stages with the same outputs; only the interpretation
    text differs, and a black-box reference export still carries its (binary-derived) reconstruction."""
    from ab_engine.workspace import Workspace  # noqa: PLC0415

    runs = {}
    for ctx, extra in (("USER_RECOVERY", {}), ("BLACK_BOX_REFERENCE", {"source_availability": "SOURCE_UNAVAILABLE"}), ("KNOWN_SOURCE_FIXTURE", {"source_availability": "KNOWN_SOURCE_GROUND_TRUTH"}),
                       ("legacy", {"ownership": "THIRD_PARTY"})):
        ws = Workspace.open(tmp_path / ctx / "ws")          # one workspace per context: identical bytes dedupe into one job otherwise
        drop = tmp_path / ctx / "drop"
        drop.mkdir(parents=True)
        shutil.copyfile(FIXTURE, drop / "Vendor.vst3")
        params = {"paths": [str(drop)], "name": "Vendor"}
        params.update({"usage_context": ctx} if ctx != "legacy" else {})
        params.update(extra)
        job_id = api.dispatch("ingest.run", params, ws)["jobs"][0]["job_id"]
        job = api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
        r = api.dispatch("bundle.export", {"job_id": job_id, "zip": False}, ws)
        out = Path(r["out_dir"])
        man = json.loads((out / "evidence" / "00_manifest" / "input_manifest.json").read_text(encoding="utf-8"))["data"]
        runs[ctx] = {"stages": [(s["stage"], s["status"]) for s in job["job"]["stages"]] if isinstance(job, dict) and "job" in job else None,
                     "files": sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file() and p.name != "CONTEXT.md" and "00_manifest" not in p.parts),
                     "manifest": man, "context_md": (out / "CONTEXT.md").read_text(encoding="utf-8"), "has_recon": (out / "CMakeLists.txt").is_file()}
    files = {tuple(v["files"]) for v in runs.values()}
    assert len(files) == 1, "the exported file set must not depend on the context"
    assert all(v["has_recon"] for v in runs.values())
    assert runs["BLACK_BOX_REFERENCE"]["manifest"]["usage_context"] == "BLACK_BOX_REFERENCE" and "binary-derived" in runs["BLACK_BOX_REFERENCE"]["context_md"]
    assert runs["KNOWN_SOURCE_FIXTURE"]["manifest"]["source_availability"] == "KNOWN_SOURCE_GROUND_TRUTH" and "known source" in runs["KNOWN_SOURCE_FIXTURE"]["context_md"]
    assert runs["legacy"]["manifest"]["usage_context"] == "BLACK_BOX_REFERENCE" and runs["legacy"]["manifest"]["legacy_ownership"] == "THIRD_PARTY"
    assert runs["USER_RECOVERY"]["manifest"]["source_availability"] == "SOURCE_UNKNOWN"


def test_export_scrubs_this_machines_paths(tmp_path):
    """The build machine's workspace, tools, home and temp roots never leave with an export; the original
    developer's paths under 01_evidence/paths stay (they are evidence)."""
    out = tmp_path / "X_RECOVERED"
    (out / "validation").mkdir(parents=True)
    (out / "evidence" / "01_evidence" / "paths").mkdir(parents=True)
    ws_root = str(tmp_path / "ws")
    (out / "validation" / "build_report.json").write_text('{"juce_dir": "/home/someone/JUCE", "log": "' + ws_root + '/logs/b.log", "win": "C:\\\\Users\\\\someone\\\\AppData\\\\Local\\\\AB\\\\tools"}', encoding="utf-8")
    (out / "evidence" / "01_evidence" / "paths" / "build_path_evidence.json").write_text('{"path": "C:\\\\Users\\\\dev\\\\plugin\\\\Source\\\\x.cpp"}', encoding="utf-8")
    before = scan_secrets(out)
    assert {f["kind"] for f in before} >= {"unix_home_path", "temp_path", "windows_user_path"}
    rows = scrub_machine_paths(out, [(ws_root, "<WORKSPACE>"), ("/home/someone", "<HOME>"), ("C:\\Users\\someone\\AppData\\Local\\AB\\tools", "<TOOLS>")])
    assert rows == [{"path": "validation/build_report.json", "replacements": 3}]
    text = (out / "validation" / "build_report.json").read_text(encoding="utf-8")
    assert '"<HOME>/JUCE"' in text and '"<WORKSPACE>/logs/b.log"' in text and '"<TOOLS>"' in text
    assert scan_secrets(out) == []
    assert "dev" in (out / "evidence" / "01_evidence" / "paths" / "build_path_evidence.json").read_text(encoding="utf-8")   # evidence untouched
