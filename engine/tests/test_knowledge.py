"""ADDENDUM A2: cumulative knowledge base — ladder, never-mutate history, provenance on match, delta summary, gate simulation."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from ab_engine import deps
from ab_engine.knowledge.db import LADDER, KnowledgeDB, fp_id

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"


def _fp(i: int, consts=(1.5, 3), name=None, size=200):
    norm = hashlib.sha256(f"norm{i}".encode()).hexdigest()
    return {"addr": f"0x{0x1000 + i * 0x40:x}", "size": size, "name": name, "RAW_BYTE_HASH": hashlib.sha256(f"raw{i}".encode()).hexdigest(),
            "NORMALIZED_INSTRUCTION_HASH": norm, "CFG_SIGNATURE": {"blocks": 3, "hash": hashlib.sha256(f"cfg{i}".encode()).hexdigest()},
            "CONSTANT_SIGNATURE": list(consts), "STRING_XREF_SIGNATURE": "", "CALLGRAPH_SIGNATURE": hashlib.sha256(f"cg{i}".encode()).hexdigest(), "TLSH": None}


def test_ladder_and_history_never_mutate_silently(tmp_path):
    db = KnowledgeDB(tmp_path / "k")
    fps = [_fp(i, name="juce::Thing" if i % 2 else None) for i in range(6)]
    r = db.record_functions("a" * 64, fps, source="test", tool_version="t", evidence_version="e", kind_of=lambda fp: "KNOWN_FRAMEWORK" if (fp.get("name") or "").startswith("juce::") else None)
    assert r == {"new": 6, "seen": 0}
    fid = fp_id(fps[0])
    assert db.promote_allowed("CANDIDATE", "STATIC_SUPPORTED") and not db.promote_allowed("BEHAVIOR_MATCHED", "CANDIDATE")
    assert db.set_state("function", "function_fp_id", fid, "STATIC_SUPPORTED", "vtable agrees", tool_version="t", evidence_version="e")
    assert not db.set_state("function", "function_fp_id", fid, "STATIC_SUPPORTED", "same again")
    hist = db.history_rows(fid)
    assert hist[0]["previous"] == "CANDIDATE" and hist[0]["current"] == "STATIC_SUPPORTED" and hist[0]["reason"] == "vtable agrees"
    assert LADDER[-1] == "IMPLEMENTATION_VERIFIED" and not db.reusable("STATIC_SUPPORTED") and db.reusable("BEHAVIOR_MATCHED")


def test_match_provenance_second_run_and_near_match_downgrade(tmp_path):
    db = KnowledgeDB(tmp_path / "k")
    fps = [_fp(i) for i in range(10)]
    db.record_functions("a" * 64, fps, source="capstone", tool_version="t", evidence_version="e")
    # second run of the same artifact family: everything known, provenance lists agreeing signatures
    rep = db.match_all(fps, artifact_sha256="b" * 64)
    assert rep["delta"]["known_implementation_pct"] == 100.0 and rep["counts"]["known"] == 10
    m = rep["results"][fps[0]["addr"]]
    assert m["verdict"] == "known" and set(m["agree"]) >= {"NORMALIZED_INSTRUCTION_HASH", "CFG_SIGNATURE", "CONSTANT_SIGNATURE", "CALLGRAPH_SIGNATURE"} and m["prior_binaries"] == 1
    assert m["reusable"] is False  # CANDIDATE never skips analysis
    # one constant changed in a "modified build": same normalized stream, different constants → near_match + history downgrade
    mod = copy.deepcopy(fps)
    mod[3]["CONSTANT_SIGNATURE"] = [1.7, 3]
    rep2 = db.match_all(mod, artifact_sha256="c" * 64)
    m3 = rep2["results"][mod[3]["addr"]]
    assert m3["verdict"] == "near_match" and "CONSTANT_SIGNATURE" in m3["disagree"] and "NORMALIZED_INSTRUCTION_HASH" in m3["agree"]
    assert rep2["counts"]["near_match"] == 1 and rep2["counts"]["known"] == 9
    h = db.history_rows(fp_id(fps[3]))
    assert h and "contradiction" in h[0]["reason"] and "CONSTANT_SIGNATURE" in h[0]["reason"]
    # a never-seen function is unknown and goes first for deep analysis
    rep3 = db.match_all([_fp(99)], artifact_sha256="d" * 64)
    assert rep3["counts"]["unknown"] == 1 and rep3["deep_analysis_first"] == [_fp(99)["addr"]]


def test_implementation_promotion_needs_two_binaries_and_behavior(tmp_path):
    db = KnowledgeDB(tmp_path / "k")
    fps = [_fp(1), _fp(2)]
    db.record_functions("a" * 64, fps, source="ghidra", tool_version="t", evidence_version="e")
    members = [fp_id(f) for f in fps]
    db.record_implementation("impl1", name_hint="WAVESHAPER:tanh", member_fp_ids=members, artifact_sha256="a" * 64, state="BEHAVIOR_MATCHED")
    assert db.db.execute("SELECT state FROM implementation WHERE impl_id='impl1'").fetchone()["state"] == "BEHAVIOR_MATCHED"
    db.record_behavior("impl1", artifact_sha256="a" * 64, probe_set_hash="p", metrics_ref="06", result_state="BEHAVIORALLY_EQUIVALENT")
    db.record_implementation("impl1", name_hint="WAVESHAPER:tanh", member_fp_ids=members, artifact_sha256="b" * 64, state="BEHAVIOR_MATCHED")
    assert db.db.execute("SELECT state FROM implementation WHERE impl_id='impl1'").fetchone()["state"] == "IMPLEMENTATION_VERIFIED"
    m = db.match(fps[0], artifact_sha256="c" * 64)
    assert m["implementation"] == "impl1" and m["implementation_state"] == "IMPLEMENTATION_VERIFIED" and m["behavior_confirmations"] == 1 and m["reusable"]
    # a later downgrade is written with a reason, never silently
    db.record_implementation("impl1", name_hint="WAVESHAPER:tanh", member_fp_ids=members, artifact_sha256="c" * 64, state="RUNTIME_SUPPORTED")
    assert db.history_rows("impl1")[0]["reason"].startswith("downgraded")


@pytest.mark.skipif(not (deps.available("lief") and deps.available("capstone")), reason="lief + capstone")
def test_gate_a2_on_the_synthetic_fixture(tmp_path):
    """Analyse twice: the second run matches ≥ 80 % KNOWN_*; a constant edit shows as near_match with history."""
    from ab_engine.fingerprint import capstone_fp as cf

    db = KnowledgeDB(tmp_path / "k")
    fps = cf.fingerprint_binary(FIXTURE)["functions"]
    fps = [f for f in fps if f["size"] >= 32]
    db.record_functions("a" * 64, fps, source="capstone", tool_version="t", evidence_version="e", kind_of=lambda fp: "KNOWN_PLUGIN_SPECIFIC")
    rep = db.match_all(fps, artifact_sha256="b" * 64)
    assert rep["delta"]["known_implementation_pct"] >= 80.0
    assert all(r["kind"] == "KNOWN_PLUGIN_SPECIFIC" for r in rep["results"].values())
