"""ADDENDUM A1: LIEF inventory beside v2, v2 pe cross-check, SDK validator parser, dependency registry."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ab_engine import api, deps
from ab_engine.inventory import lief_inventory as li
from ab_engine.runtime import validator

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"
CLI = ROOT / "app" / "static-engine" / "dist" / "cli.mjs"
needs_node = pytest.mark.skipif(not (shutil.which("node") and CLI.is_file()), reason="needs node + built static engine")
needs_lief = pytest.mark.skipif(not deps.available("lief"), reason="lief not installed")


def test_dependency_registry_reports_pins():
    rows = deps.doctor_rows()
    names = {r["name"] for r in rows}
    assert {"dep:lief", "dep:capstone", "dep:yara", "dep:tlsh", "dep:numpy", "dep:jsonschema"} <= names
    for r in rows:
        assert r["verdict"] in ("PASS", "WARNING", "UNAVAILABLE") and "pinned" in r["detail"]


@needs_lief
def test_inventory_reads_the_synthetic_pe():
    inv = li.inventory(FIXTURE)
    assert inv["status"] == "PARSED" and inv["format"] == "PE" and inv["arch"] == "x64" and inv["linker"] == "14.0"
    assert [s["name"] for s in inv["sections"]] == [".text", ".rdata"]
    v2 = li.v2_pe_dict(FIXTURE)
    assert v2["machine"] == "x64" and v2["sectionNames"] == ".text .rdata" and v2["rdata"][0] == inv["sections"][1]["offset"] and v2["exports"] == ["GetPluginFactory", "InitDll", "ExitDll"] and v2["format"] == "VST3"
    assert li.v2_pe_dict(ROOT / "README.md") == {}  # non-PE → {} like v2


@needs_node
@needs_lief
def test_static_stage_cross_checks_v2_pe_with_lief(ws, tmp_path):
    drop = tmp_path / "drop" / "SynthPlug.vst3" / "Contents" / "x86_64-win"
    drop.mkdir(parents=True)
    shutil.copyfile(FIXTURE, drop / "SynthPlug.vst3")
    job_id = api.dispatch("ingest.run", {"paths": [str(tmp_path / "drop")], "ownership": "OWNED"}, ws)["jobs"][0]["job_id"]
    result = api.dispatch("job.run", {"job_id": job_id, "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    rec = next(s for s in result["stages"] if s["stage"] == "STATIC_COMPLETE")
    assert rec["status"] == "OK"
    assert rec["metrics"]["inventory"] == {"SynthPlug.vst3": "MATCH"}, rec["metrics"].get("inventory")
    assert "01_evidence/binary/inventory.json" in rec["outputs"]


def test_validator_parser_reads_sdk_report():
    text = "[Scan Editor Classes]\nInfo: x\n[Succeeded]\n\n[Bus Consistency]\n[Failed]\n\n-------\nResult: 46 tests passed, 1 tests failed\n"
    r = validator.parse(text)
    assert r["passed"] == 46 and r["failed"] == 1 and r["failing"] == ["Bus Consistency"]
    assert [t["result"] for t in r["tests"]] == ["Succeeded", "Failed"]
