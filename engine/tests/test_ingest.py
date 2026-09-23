"""EXECUTE 1.3 gate: 4 fixtures + 3 presets → 4 jobs with correct attachments and hashes; streamed hashing."""

import hashlib
import json
import tracemalloc

from ab_engine import api
from ab_engine.ingest.api import group, walk
from ab_engine.ingest.classify import classify
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs.store import sha256_file
from fixtures import fake_pe, make_zip, write_tree

PRESET = b'<?xml version="1.0"?><PARAMETERS><PARAM id="drive" value="0.5"/></PARAMETERS>'


def test_classify_rules():
    assert classify("Twin Panda FX.vst3/Contents/x86_64-win/Twin Panda FX.vst3", 100000, b"MZ\x90\x00")[0] == "binary"
    assert classify("small.dll", 1000, b"MZ\x90\x00")[0] == "other"          # < 32 KB is not a plugin binary
    assert classify("a/b/plugin.pdb", 10, b"Micr")[0] == "pdb"
    assert classify("x.map", 10, b"")[0] == "map"
    assert classify("Source/PluginProcessor.cpp", 10, b"")[0] == "source"
    assert classify("preset1.vstpreset", 10, b"")[0] == "preset"
    assert classify("session.RPP", 10, b"")[0] == "session"
    assert classify("build/_deps/juce/x.cpp", 10, b"")[0] == "skip"
    assert classify("node_modules/x/y.js", 10, b"")[0] == "skip"
    assert classify("art/knob.png", 10, b"\x89PNG")[0] == "asset"
    assert classify("stuff.zip", 10, b"PK")[0] == "archive"


def test_four_fixtures_three_presets_yield_four_jobs(ws, tmp_path):
    drop = tmp_path / "drop"
    names = ["Twin Panda FX", "Rhino Reverb", "Fox Echo Chorus", "TimeMachine"]
    spec = {}
    for i, n in enumerate(names):
        spec[f"{n}.vst3/Contents/x86_64-win/{n}.vst3"] = fake_pe(64 * 1024 + i * 4096)
    spec["Twin Panda FX presets/Init.vstpreset"] = PRESET
    spec["Twin Panda FX presets/Warm.vstpreset"] = PRESET + b" "
    spec["Rhino Reverb/Hall.vstpreset"] = PRESET + b"  "
    spec["symbols/TimeMachine.pdb"] = b"Microsoft C/C++ MSF 7.00"
    write_tree(drop, spec)

    result = api.dispatch("ingest.run", {"paths": [str(drop)], "ownership": "THIRD_PARTY"}, ws)
    assert len(result["jobs"]) == 4
    conn = jobs_db.connect(ws.db_path)
    by_name = {j["name"]: j for j in result["jobs"]}
    assert set(by_name) == {n.replace(" ", "_") for n in names}

    tp = jobs_db.get_inputs(conn, by_name["Twin_Panda_FX"]["job_id"])
    kinds = {i["path"]: i["kind"] for i in tp}
    assert sum(1 for k in kinds.values() if k == "preset") == 2
    assert sum(1 for k in kinds.values() if k == "pdb") == 1            # pdb attaches to every group
    rr = jobs_db.get_inputs(conn, by_name["Rhino_Reverb"]["job_id"])
    assert sum(1 for i in rr if i["kind"] == "preset") == 1
    fx = jobs_db.get_inputs(conn, by_name["Fox_Echo_Chorus"]["job_id"])
    assert sum(1 for i in fx if i["kind"] == "preset") == 0

    # hashes are real, streamed SHA-256 of the file bytes
    primary = next(i for i in tp if i["kind"] == "binary")
    expected = hashlib.sha256(spec["Twin Panda FX.vst3/Contents/x86_64-win/Twin Panda FX.vst3"]).hexdigest()
    assert primary["sha256"] == expected and by_name["Twin_Panda_FX"]["artifact_sha256"] == expected

    # manifests were written by the INGESTED stage with contract envelopes
    pd = by_name["Twin_Panda_FX"]["project_dir"]
    man = json.load(open(f"{pd}/00_manifest/input_manifest.json"))
    assert man["schema"] == "artifactbench.input_manifest" and man["data"]["mode"] == "THIRD_PARTY_ANALYSIS_ONLY"
    assert man["data"]["reconstruction_allowed"] is False
    assert sorted(man["data"]["attachments"]) == ["pdb", "preset"]
    assert json.load(open(f"{pd}/00_manifest/hashes.json"))["data"]["algorithm"] == "sha256"
    assert "engine" in json.load(open(f"{pd}/00_manifest/tool_versions.json"))["data"]
    assert by_name["Twin_Panda_FX"]["stages"][0]["status"] == "OK"


def test_single_plugin_attaches_everything_and_reingest_is_idempotent(ws, tmp_path):
    drop = tmp_path / "drop"
    write_tree(drop, {"MyPlug.vst3": fake_pe(), "Other Name/x.vstpreset": PRESET, "Src/PluginProcessor.cpp": b"int x;"})
    r1 = api.dispatch("ingest.run", {"paths": [str(drop)], "ownership": "OWNED"}, ws)
    assert len(r1["jobs"]) == 1
    conn = jobs_db.connect(ws.db_path)
    kinds = sorted(i["kind"] for i in jobs_db.get_inputs(conn, r1["jobs"][0]["job_id"]))
    assert kinds == ["binary", "preset", "source"]
    r2 = api.dispatch("ingest.run", {"paths": [str(drop)], "ownership": "OWNED"}, ws)
    assert r2["jobs"][0]["job_id"] == r1["jobs"][0]["job_id"]
    assert r2["jobs"][0]["outcomes"] == {"INGESTED": "reuse"}   # nothing changed → zero work
    # a new preset changes the attachment set → INGESTED re-runs
    (drop / "New.vstpreset").write_bytes(PRESET + b"new")
    r3 = api.dispatch("ingest.run", {"paths": [str(drop)], "ownership": "OWNED"}, ws)
    assert r3["jobs"][0]["outcomes"] == {"INGESTED": "run"}


def test_archive_expansion_is_safe(ws, tmp_path):
    z = tmp_path / "old_build.zip"
    make_zip(z, {"Release/Plug.vst3": fake_pe(), "../escape.txt": b"x", "/abs.txt": b"y", "presets/a.vstpreset": PRESET})
    files, ignored = walk([str(z)], ws.cache)
    paths = {f["path"] for f in files}
    assert "old_build/Release/Plug.vst3" in paths and "old_build/presets/a.vstpreset" in paths
    assert not any("escape" in p or "abs.txt" in p for p in paths)
    assert not list(ws.cache.rglob("escape.txt"))


def test_nothing_usable(ws, tmp_path):
    (tmp_path / "notes.md").write_text("hi")
    r = api.dispatch("ingest.run", {"paths": [str(tmp_path / "notes.md")], "ownership": "OWNED"}, ws)
    assert r["jobs"] == [] and r["files"][0]["kind"] == "other"


def test_grouping_largest_binary_is_primary():
    files = [
        {"path": "P.vst3/Contents/x86_64-win/P.vst3", "size": 500, "kind": "binary"},
        {"path": "P.vst3/Contents/Resources/helper.dll", "size": 900, "kind": "binary"},
    ]
    g = group(files)
    # v2 rule: the bundle key is the FIRST path segment with a plugin extension, so a
    # helper DLL inside the bundle joins the group and the largest binary is primary.
    assert len(g) == 1
    assert g[0]["key"] == "P.vst3" and g[0]["primary"]["size"] == 900


def test_hashing_is_streamed(tmp_path):
    big = tmp_path / "big.bin"
    with open(big, "wb") as fh:
        for _ in range(64):
            fh.write(b"\x5a" * (1024 * 1024))
    tracemalloc.start()
    sha, size = sha256_file(big)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert size == 64 * 1024 * 1024
    assert peak < 16 * 1024 * 1024, f"hashing held {peak / 1e6:.1f} MB of a 64 MB file in memory"
