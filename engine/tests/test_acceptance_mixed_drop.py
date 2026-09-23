"""ADDENDUM B8 acceptance test 2 — mixed drop: one folder with a VST3, a PDB, presets, an RPP session, a WAV, a PNG,
an XML, a source fragment, a ZIP and an unknown file. Everything is inventoried and routed, relationships are
created, unknowns are preserved, nothing is lost, no crash, and the project exports."""
from __future__ import annotations

import json
import shutil
import struct
import zipfile
from pathlib import Path

from ab_engine import api
from ab_engine.ingest import router
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "SynthPlug.vst3"   # the synthetic PE


def _msf7(guid: bytes, age: int, page: int = 512) -> bytes:
    info = struct.pack("<III", 20000404, 0x11223344, age) + guid + b"\0" * 8
    directory = struct.pack("<I", 2) + struct.pack("<II", 0, len(info)) + struct.pack("<I", 3)
    sb = b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00" + struct.pack("<IIIIII", page, 0, 4, len(directory), 0, 1)
    return b"".join(x.ljust(page, b"\0") for x in (sb, struct.pack("<I", 2), directory, info))


def _wav(frames: int = 8) -> bytes:
    data = b"\0\0" * frames
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data


def test_mixed_drop_is_inventoried_routed_related_preserved_and_exported(ws, tmp_path: Path):
    drop = tmp_path / "MixedDrop"
    (drop / "SynthPlug.vst3" / "Contents" / "x86_64-win").mkdir(parents=True)
    shutil.copyfile(FIXTURE, drop / "SynthPlug.vst3" / "Contents" / "x86_64-win" / "SynthPlug.vst3")
    (drop / "SynthPlug.pdb").write_bytes(_msf7(bytes(range(16)), 2))
    (drop / "presets").mkdir()
    (drop / "presets" / "Init.vstpreset").write_bytes(b"VST3\x01\x00\x00\x00" + b"\0" * 32)
    (drop / "presets" / "Warm.xml").write_text('<?xml version="1.0"?><PARAMETERS><PARAM id="drive" value="0.5"/></PARAMETERS>', encoding="utf-8")
    (drop / "session.rpp").write_text("<REAPER_PROJECT 0.1 \"6.0\"\n  <TRACK\n  >\n>\n", encoding="utf-8")
    (drop / "render.wav").write_bytes(_wav())
    (drop / "knob.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 24)
    (drop / "Source").mkdir()
    (drop / "Source" / "Shaper.h").write_text("struct Shaper { float process(float x); };\n", encoding="utf-8")
    with zipfile.ZipFile(drop / "old_builds.zip", "w") as zf:
        zf.writestr("notes.txt", "old build notes")
        zf.writestr("../evil.txt", "traversal must be refused")
    (drop / "mystery.dat").write_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07" * 8)

    r = api.dispatch("ingest.run", {"paths": [str(drop)], "name": "MixedDrop"}, ws)
    assert r["jobs"], "a plugin binary in the drop must yield a job"
    job_id = r["jobs"][0]["job_id"]
    api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    pd = Path(r["jobs"][0]["project_dir"])
    man = json.loads((pd / "00_manifest" / "input_manifest.json").read_text(encoding="utf-8"))["data"]
    routes = json.loads((pd / "00_manifest" / "artifact_routes.json").read_text(encoding="utf-8"))["data"]
    by_path = {i["path"].split("/")[-1]: i for i in man["inputs"]}
    # every dropped item is present, nothing lost (the traversal member of the zip is refused, its safe member kept)
    for name in ("SynthPlug.vst3", "SynthPlug.pdb", "Init.vstpreset", "Warm.xml", "session.rpp", "render.wav", "knob.png", "Shaper.h", "notes.txt", "mystery.dat"):
        assert name in by_path, name
    assert "evil.txt" not in by_path
    types = {i["path"].split("/")[-1]: i["artifact_type"] for i in man["inputs"]}
    assert types["SynthPlug.vst3"] == "PLUGIN_PE" and types["SynthPlug.pdb"] == "PDB" and types["Init.vstpreset"] == "VSTPRESET" and types["Warm.xml"] == "XML_STATE"
    assert types["session.rpp"] == "SESSION_RPP" and types["render.wav"] == "AUDIO_WAV" and types["knob.png"] == "IMAGE_PNG" and types["Shaper.h"] == "SOURCE_CPP"
    assert types["mystery.dat"] == "UNKNOWN" and by_path["mystery.dat"]["status"] == "UNKNOWN_ARTIFACT" and "mystery.dat" in " ".join(man["preserved_unparsed"])
    assert by_path["session.rpp"]["status"] == "IDENTIFIED" and by_path["SynthPlug.pdb"]["status"] == "IDENTIFIED"
    # the unknown file is a full record: hash, size, name, mime, magic evidence
    unk = next(x for x in routes["records"] if x["path"].endswith("mystery.dat"))
    assert unk["sha256"] and unk["size"] == 64 and unk["mime"] == "application/octet-stream" and unk["capabilities"] == ["preserve"]
    # relationships: the PDB is not blindly attached to the binary (the synthetic PE has no CodeView record) — same-stem only, low confidence
    rel = [e for e in man["relationships"] if e["kind"].startswith("PDB")]
    assert rel and rel[0]["kind"] == "PDB_UNVERIFIED" and rel[0]["confidence"] <= 0.3
    # idempotence: the same drop again adds nothing and changes nothing
    r2 = api.dispatch("ingest.run", {"paths": [str(drop)], "name": "MixedDrop"}, ws)
    assert r2["jobs"][0]["job_id"] == job_id
    man2 = json.loads((pd / "00_manifest" / "input_manifest.json").read_text(encoding="utf-8"))["data"]
    assert sorted(i["sha256"] for i in man2["inputs"]) == sorted(i["sha256"] for i in man["inputs"])
    # per-file drops yield the same object set as the folder drop (dedupe by hash)
    ws2_root = tmp_path / "ws2"
    from ab_engine.workspace import Workspace
    ws2 = Workspace.open(ws2_root)
    paths = [str(p) for p in sorted(drop.rglob("*")) if p.is_file()]
    r3 = api.dispatch("ingest.run", {"paths": paths, "name": "MixedDrop"}, ws2)
    api.dispatch("job.run", {"job_id": r3["jobs"][0]["job_id"], "stages": ["INGESTED"]}, ws2)
    man3 = json.loads((Path(r3["jobs"][0]["project_dir"]) / "00_manifest" / "input_manifest.json").read_text(encoding="utf-8"))["data"]
    assert sorted(i["sha256"] for i in man3["inputs"]) == sorted(i["sha256"] for i in man["inputs"])
    # export works and keeps the unknown artifact record
    e = api.dispatch("bundle.export", {"job_id": job_id, "zip": True}, ws)
    out = Path(e["out_dir"])
    assert (out / "evidence" / "00_manifest" / "artifact_routes.json").is_file() and (out / "CONTEXT.md").is_file() and e["path_findings"] == []
    assert router.REGISTRY["UNKNOWN"]["capabilities"] == ["preserve"]
