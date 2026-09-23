"""ADDENDUM B4: universal artifact router — identify by magic + extension + context, capability registry,
UNKNOWN_ARTIFACT preserved, PDB GUID/age relationships, no merge on file-name similarity alone."""
from __future__ import annotations

import struct
from pathlib import Path

from ab_engine.ingest import router


def test_identify_by_magic_extension_and_context():
    assert router.identify("a/b/Plug.vst3/Contents/x86_64-win/Plug.vst3", 100000, b"MZ\x90\x00" + b"\0" * 60)["type"] == "PLUGIN_PE"
    assert router.identify("x.so", 100000, b"\x7fELF" + b"\0" * 60)["type"] == "PLUGIN_ELF"
    assert router.identify("knob.png", 790, b"\x89PNG\r\n\x1a\n" + b"\0" * 8)["type"] == "IMAGE_PNG"
    r = router.identify("weird.bin", 790, b"\x89PNG\r\n\x1a\n" + b"\0" * 8)
    assert r["type"] == "IMAGE_PNG" and r["evidence"][0].startswith("magic")                      # magic without extension
    assert router.identify("song.mid", 500, b"MThd" + b"\0" * 20)["type"] == "MIDI"
    assert router.identify("take.flac", 500, b"fLaC" + b"\0" * 20)["type"] == "AUDIO_FLAC"
    assert router.identify("Plug.pdb", 5000, b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0")["type"] == "PDB"
    assert router.identify("sess.rpp", 500, b"<REAPER_PROJECT 0.1")["type"] == "SESSION_RPP"
    assert router.identify("p.vstpreset", 500, b"VST3\x01\x00")["type"] == "VSTPRESET"
    assert router.identify("p.fxp", 500, b"CcnK\0\0")["type"] == "FXP_FXB"
    assert router.identify("Source/PluginProcessor.cpp", 500, b"#include <juce>")["type"] == "SOURCE_CPP"
    assert router.identify("Source/PluginProcessor.cpp", 500, b"#include <juce>")["confidence"] == 0.7   # source tree context raises confidence
    assert router.identify("x.aupreset", 500, b'<?xml version="1.0"?><plist>')["type"] == "AUPRESET"
    assert router.identify("CMakeLists.txt", 500, b"cmake_minimum_required")["type"] == "BUILD_SCRIPT"
    u = router.identify("mystery.dat", 500, b"\x00\x01\x02\x03")
    assert u["type"] == "UNKNOWN" and u["status"] == "UNKNOWN_ARTIFACT" and u["capabilities"] == ["preserve"]
    assert router.identify("notes.md", 10, b"# hi")["status"] == "PRESERVED_UNPARSED"                    # recognized, no parser: preserved
    # magic beats a lying extension, and says so
    r = router.identify("photo.txt", 500, b"\xff\xd8\xff\xe0" + b"\0" * 20)
    assert r["type"] == "IMAGE_JPEG" and any("disagree" in e for e in r["evidence"])


def test_registry_is_the_only_switch():
    assert set(router.REGISTRY) == set(router.KIND_OF)
    for t, entry in router.REGISTRY.items():
        assert "preserve" in entry["capabilities"] and set(entry["capabilities"]) <= set(router.CAPABILITIES), t
    # adding a type is one entry: the router routes it without any other change
    router.REGISTRY["TEST_TYPE"] = {"family": "asset", "capabilities": ["preserve"], "parser": None}
    router.KIND_OF["TEST_TYPE"] = "other"
    try:
        assert router.identify("x.unknownext", 1, b"")["type"] == "UNKNOWN"   # no detector wired: still unknown, never crashes
    finally:
        del router.REGISTRY["TEST_TYPE"]
        del router.KIND_OF["TEST_TYPE"]


def _msf7(guid: bytes, age: int, page: int = 512) -> bytes:
    """A minimal MSF 7.00 file: superblock (page 0), directory map (page 1), directory (page 2), stream 1 (page 3)."""
    info = struct.pack("<III", 20000404, 0x11223344, age) + guid + b"\0" * 8
    directory = struct.pack("<I", 2) + struct.pack("<II", 0, len(info)) + struct.pack("<I", 3)   # 2 streams: stream 0 empty, stream 1 on page 3
    sb = b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00" + struct.pack("<IIIIII", page, 0, 4, len(directory), 0, 1)
    pages = [sb.ljust(page, b"\0"), struct.pack("<I", 2).ljust(page, b"\0"), directory.ljust(page, b"\0"), info.ljust(page, b"\0")]
    return b"".join(pages)


def test_pdb_guid_age_and_relationships(tmp_path: Path):
    guid = bytes(range(16))
    (tmp_path / "Plug.pdb").write_bytes(_msf7(guid, 3))
    meta = router.pdb_guid_age(tmp_path / "Plug.pdb")
    assert meta and meta["age"] == 3 and meta["guid"] == "03020100-0504-0706-0809-0A0B0C0D0E0F".upper() and meta["streams"] == 2
    assert router.pdb_guid_age(tmp_path / "missing.pdb") is None
    (tmp_path / "bad.pdb").write_bytes(b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0" + b"\0" * 40)
    assert router.pdb_guid_age(tmp_path / "bad.pdb") is None
    # relationship engine on records (no LIEF needed): GUID/age match vs mismatch vs unverified; identical bytes; near-related candidates
    recs = [
        {"path": "Plug.vst3", "type": "PLUGIN_PE", "family": "compiled_plugin", "size": 1000, "sha256": "a" * 64, "codeview": {"guid": "03020100-0504-0706-0809-0A0B0C0D0E0F", "age": 3}},
        {"path": "Plug.pdb", "type": "PDB", "family": "debug_evidence", "size": 10, "sha256": "p" * 64, "pdb": {"guid": "03020100-0504-0706-0809-0A0B0C0D0E0F", "age": 3}},
        {"path": "Plug_old.vst3", "type": "PLUGIN_PE", "family": "compiled_plugin", "size": 900, "sha256": "b" * 64, "codeview": {"guid": "FFFFFFFF-0504-0706-0809-0A0B0C0D0E0F", "age": 1}},
        {"path": "copy/Plug.vst3", "type": "PLUGIN_PE", "family": "compiled_plugin", "size": 1000, "sha256": "a" * 64},
        {"path": "Other.pdb", "type": "PDB", "family": "debug_evidence", "size": 10, "sha256": "q" * 64},
        {"path": "Other.vst3", "type": "PLUGIN_PE", "family": "compiled_plugin", "size": 500, "sha256": "c" * 64},
    ]
    edges = router.relationships(recs)
    kinds = {(e["kind"], e["a"], e["b"]): e for e in edges}
    assert kinds[("IDENTICAL_BYTES", "Plug.vst3", "copy/Plug.vst3")]["confidence"] == 1.0
    assert kinds[("PDB_MATCHES_BINARY", "Plug.pdb", "Plug.vst3")]["confidence"] == 1.0
    assert kinds[("PDB_MISMATCH", "Plug.pdb", "Plug_old.vst3")]["confidence"] == 0.0
    assert kinds[("PDB_UNVERIFIED", "Other.pdb", "Other.vst3")]["confidence"] == 0.3            # same stem only: never merged on this
    near = kinds[("NEAR_RELATED_CANDIDATE", "Plug.vst3", "Plug_old.vst3")]
    assert near["confidence"] < 0.7 and "fingerprints decide" in near["basis"]
    assert ("NEAR_RELATED_CANDIDATE", "Plug.vst3", "Other.vst3") not in kinds                       # different names: no edge at all


def test_route_records_every_artifact_and_counts(tmp_path: Path):
    (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    (tmp_path / "mystery.bin").write_bytes(b"\x00\x01\x02")
    files = [{"path": "a.png", "size": 24, "sha256": "1" * 64, "fs_path": str(tmp_path / "a.png")}, {"path": "mystery.bin", "size": 3, "sha256": "2" * 64, "fs_path": str(tmp_path / "mystery.bin")}]
    r = router.route(files)
    assert r["counts"] == {"ROUTED": 1, "UNKNOWN_ARTIFACT": 1} and len(r["records"]) == 2 and r["records"][1]["kind"] == "other"
