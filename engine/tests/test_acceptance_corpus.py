"""ADDENDUM B8 acceptance test 3 — corpus: several families dropped together → independent provenance, no
contamination, dedupe, lineage, cache reuse, reference matching, corpus report."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ab_engine import api, deps, tools
from ab_engine.jobs import db as jobs_db
from ab_engine.reference import library

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"


def _variant(base: bytes, renames: dict[bytes, bytes]) -> bytes:
    """Same-length byte renames of the embedded MSVC RTTI descriptors: a different plugin with the same (or a
    different) owned class-name set. Lengths are equal so every offset in the image stays valid."""
    out = base
    for a, b in renames.items():
        assert len(a) == len(b) and a in out, a
        out = out.replace(a, b)
    return out


def _needs_node():
    return not (tools.find_node(None).present if hasattr(tools, "find_node") else True)


@pytest.mark.skipif(not (ROOT / "app" / "static-engine" / "dist" / "cli.mjs").is_file(), reason="static engine not built")
def test_corpus_drop_keeps_provenance_independent_and_reports_lineage(ws, tmp_path: Path):
    base = FIXTURE.read_bytes()
    a = base                                                                                                   # Synth family, plugin A
    b = _variant(base, {b".?AVSynthPlugAudioProcessor@@": b".?AVRhinoPlugAudioProcessor@@"})                    # same DSP classes, another product → same family
    c = _variant(base, {b".?AVSynthClipper@synth@@": b".?AVCamelClipper@camel@@", b".?AVSynthFilter@synth@@": b".?AVCamelFilter@camel@@",
                        b".?AVSynthPlugAudioProcessor@@": b".?AVCamelPlugAudioProcessor@@", b".?AVSynthLookAndFeel@@": b".?AVCamelLookAndFeel@@"})   # another family
    drop = tmp_path / "corpus"
    for name, data in (("Synth Plug", a), ("Rhino Plug", b), ("Camel Strip", c), ("Synth Plug (copy)", a)):
        p = drop / f"{name}.vst3" / "Contents" / "x86_64-win" / f"{name}.vst3"
        p.parent.mkdir(parents=True)
        p.write_bytes(data)
    r = api.dispatch("ingest.run", {"paths": [str(drop)]}, ws)
    jobs = list({j["job_id"]: j for j in r["jobs"]}.values())
    assert len(jobs) == 3, "the byte-identical copy is deduped by hash, never a fourth plugin"
    assert len({j["artifact_sha256"] for j in r["jobs"]}) == 3
    by = {j["name"].split("_")[0]: j for j in jobs}
    assert set(by) == {"Synth", "Rhino", "Camel"}
    for j in jobs:
        api.dispatch("job.run", {"job_id": j["job_id"], "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    # independent provenance: three project folders, three manifests naming only their own primary; evidence never crosses
    dirs = {Path(j["project_dir"]) for j in jobs}
    assert len(dirs) == 3
    for j in jobs:
        man = json.loads((Path(j["project_dir"]) / "00_manifest" / "input_manifest.json").read_text(encoding="utf-8"))["data"]
        assert man["primary"]["sha256"] == j["artifact_sha256"]
        assert all(i["sha256"] == j["artifact_sha256"] for i in man["inputs"] if i["kind"] == "binary")
    classes = {}
    for k, j in by.items():
        rows = json.loads((Path(j["project_dir"]) / "01_evidence" / "rtti" / "classes.json").read_text(encoding="utf-8"))["data"]
        classes[k] = {c["recovered_name"] for c in rows if c.get("kind") == "PLUGIN_OWNED_CANDIDATE"}
    assert "synth::SynthClipper" in classes["Synth"] and "synth::SynthClipper" in classes["Rhino"] and "camel::CamelClipper" in classes["Camel"]
    assert "camel::CamelClipper" not in classes["Synth"] and "synth::SynthClipper" not in classes["Camel"]      # no contamination
    # lineage: Synth and Rhino share their DSP class names → one INFERRED family; Camel stands alone
    rep = api.dispatch("lineage.report", {"job_id": by["Synth"]["job_id"]}, ws)
    fam = next(f for f in rep["families"] if by["Synth"]["job_id"] in f["members"])
    assert set(fam["members"]) == {by["Synth"]["job_id"], by["Rhino"]["job_id"]} and by["Camel"]["job_id"] not in fam["members"]
    assert "INFERRED" in json.dumps(rep["families"]) and "SHARED_IMPLEMENTATION_VERIFIED" not in rep["report"]     # a name is never enough
    # cache reuse: the same stages again do zero work
    before = {s["stage"]: s["ended"] for s in api.dispatch("job.get", {"job_id": by["Synth"]["job_id"]}, ws)["stages"]}
    again = api.dispatch("job.run", {"job_id": by["Synth"]["job_id"], "stages": ["INGESTED", "STATIC_COMPLETE"], "options": {"prefer_node": True}}, ws)
    assert {s["stage"]: s["ended"] for s in again["stages"] if s["stage"] in before} == before
    # reference matching: every plugin is its own USER_ARTIFACT entry; the clean-room DSP references are listed beside them, never merged in
    lib = api.dispatch("reference.list", {"write": False}, ws)
    mine = [e for e in lib["entries"] if e["entry_type"] == "USER_ARTIFACT"]
    assert len(mine) == 3 and len({e["hash"] for e in mine}) == 3 and lib["counts"]["DSP_REFERENCE"] == 33
    assert lib["isolation"]["ok"]
    # corpus report (frozen v2 corpus layer) over the three
    try:
        corpus = api.dispatch("corpus.run", {}, ws)
    except api.ApiError as e:
        pytest.skip(f"corpus layer unavailable here: {e}")
    assert corpus["plugins"] == 3 and "CORPUS" in corpus["report"].upper()
    conn = jobs_db.connect(ws.db_path)
    assert len(jobs_db.list_jobs(conn)) == 3
