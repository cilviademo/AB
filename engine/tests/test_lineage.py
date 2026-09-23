"""Knowledge cache contradiction rule (SPEC §1.6) and family inference (SPEC §9)."""

from ab_engine.lineage.api import families
from ab_engine.lineage.knowledge import Knowledge


def _fp(addr, norm, cfg, consts, strs="s", rtti=None, slot=-1, name="f", size=100):
    return {"addr": addr, "name": name, "size": size, "NORMALIZED_INSTRUCTION_HASH": norm, "CFG_SIGNATURE": {"blocks": 3, "hash": cfg},
            "CONSTANT_SIGNATURE": consts, "STRING_XREF_SIGNATURE": strs, "CALLGRAPH_SIGNATURE": "cg", "RTTI_XREF": rtti, "VTABLE_SLOT": slot, "RAW_BYTE_HASH": "raw" + addr}


def test_cache_matches_by_fingerprint_and_downgrades_on_contradiction(tmp_path):
    kn = Knowledge(tmp_path / "k")
    juce = [_fp("0x1", "n1", "c1", ["0.5"], name="juce::Slider::paint"), _fp("0x2", "n2", "c2", ["3.14159"], name="juce::dsp::Oversampling::process")]
    assert kn.seed_functions(juce, state="KNOWN_FRAMEWORK", source_hash="a" * 64, library="JUCE", compiler=None, tool_version="t", only_names={"juce::"}) == 2
    # same implementation at another address, different raw hash → match, deep work suppressed
    m = kn.match(_fp("0x999", "n2", "c2", ["3.14159"], name="FUN_00000999"))
    assert m["state"] == "KNOWN_FRAMEWORK" and m["suppress_deep_work"] and m["cached_name"].startswith("juce::dsp")
    # one DSP constant changed → contradiction → UNKNOWN + re-analyse (the Phase 3 exit gate)
    d = kn.match(_fp("0x999", "n2", "c2", ["2.71828"], name="FUN_00000999"))
    assert d["state"] == "UNKNOWN" and d["reanalyse"] and "CONSTANT_SIGNATURE" in d["contradictions"][0] and d["downgraded_from"] == "KNOWN_FRAMEWORK"
    # never by name
    assert kn.match(_fp("0x5", "other", "x", [], name="juce::Slider::paint"))["matched"] is False
    r = kn.match_all(juce + [_fp("0x7", "n9", "c9", [])])
    assert r["counts"] == {"KNOWN_FRAMEWORK": 2, "UNKNOWN": 1} and r["suppressed"] == 2
    assert kn.stats()["functions"]["KNOWN_FRAMEWORK"] == 2


def test_families_are_inferred_with_medoid():
    sets = {"a": {"X", "Y", "Z", "W"}, "b": {"X", "Y", "Z", "Q"}, "c": {"X", "Y", "Z", "W", "V"}, "d": {"Alone"}}
    f = families(["a", "b", "c", "d"], sets)
    fam = next(x for x in f["families"] if x["size"] == 3)
    assert set(fam["members"]) == {"a", "b", "c"} and fam["status"] == "INFERRED_CODEBASE_FAMILY" and fam["medoid"] in ("a", "c")
    assert any(x["members"] == ["d"] for x in f["families"])
