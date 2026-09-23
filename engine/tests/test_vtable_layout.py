"""Knowledge-learned vtable layouts: symbol builds teach slot → method names, stripped builds are seeded
only when the slot fingerprints corroborate the layout (never on the name alone)."""
from __future__ import annotations

import hashlib

from ab_engine.knowledge.db import KnowledgeDB, fp_id
from ab_engine.knowledge import vtable_layout as vl


def _fp(tag: str, addr: str):
    return {"addr": addr, "size": 100, "name": None, "NORMALIZED_INSTRUCTION_HASH": hashlib.sha256(f"norm{tag}".encode()).hexdigest(),
            "CFG_SIGNATURE": {"blocks": 2, "hash": hashlib.sha256(f"cfg{tag}".encode()).hexdigest()}, "CONSTANT_SIGNATURE": [], "STRING_XREF_SIGNATURE": ""}


BASE_NAMES = ["~AP", "~AP", "getName", "prepareToPlay", "releaseResources", "processBlock", "processBlock", "getTailLengthSeconds",
              "createEditor", "hasEditor", "getStateInformation", "setStateInformation"]
PURE = {"prepareToPlay", "releaseResources", "createEditor", "hasEditor", "getStateInformation", "setStateInformation", "getName"}


def _symbol_build():
    """A symbol build: base juce::AudioProcessor (pure slots point at __cxa_pure_virtual) and a plugin class
    overriding some slots. Fingerprints are stable framework functions for the un-overridden slots."""
    fps = {}
    base_slots, base_names = [], []
    for i, n in enumerate(BASE_NAMES):
        if n in PURE:
            base_slots.append("0xdead0"); base_names.append("__cxa_pure_virtual")
        else:
            a = f"0x{0x5000 + i * 0x20:x}"
            base_slots.append(a); base_names.append(n); fps[a] = _fp(f"fw{i}", a)
    plugin_slots, plugin_names = [], []
    for i, n in enumerate(BASE_NAMES):
        if n in PURE or (n == "processBlock" and i == 5):   # plugin overrides pure slots + processBlock(float)
            a = f"0x{0x9000 + i * 0x20:x}"
            plugin_slots.append(a); plugin_names.append(n); fps[a] = _fp(f"pl{i}", a)
        else:
            plugin_slots.append(base_slots[i]); plugin_names.append(base_names[i])
    classes = [{"name": "juce::AudioProcessor", "vtable_slots": [base_slots], "vtable_slot_names": [base_names], "bases": []},
               {"name": "MyPlugin", "vtable_slots": [plugin_slots], "vtable_slot_names": [plugin_names], "bases": ["juce::AudioProcessor"]}]
    return classes, fps


def _stripped_build(*, other_framework: bool = False):
    """The same framework, a different plugin, no names. Function addresses differ; framework fingerprints
    are the same unless ``other_framework`` (a different JUCE version: nothing matches)."""
    fps = {}
    base_slots = []
    for i, n in enumerate(BASE_NAMES):
        if n in PURE:
            base_slots.append("0xbeef0")
        else:
            a = f"0x{0x7000 + i * 0x20:x}"
            base_slots.append(a); fps[a] = _fp(f"{'v9' if other_framework else 'fw'}{i}", a)
    plugin_slots = []
    for i, n in enumerate(BASE_NAMES):
        if n in PURE or (n == "processBlock" and i == 5):
            a = f"0x{0xa000 + i * 0x20:x}"
            plugin_slots.append(a); fps[a] = _fp(f"other{i}", a)
        else:
            plugin_slots.append(base_slots[i])
    classes = [{"name": "juce::AudioProcessor", "vtable_slots": [base_slots], "vtable_slot_names": [[""] * len(base_slots)], "bases": [], "rtti_kind": "ITANIUM_RTTI_STRUCTURAL"},
               {"name": "OtherPlugin", "vtable_slots": [plugin_slots], "vtable_slot_names": [[""] * len(plugin_slots)], "bases": ["juce::AudioProcessor"], "rtti_kind": "ITANIUM_RTTI_STRUCTURAL"}]
    return classes, fps


def test_learn_rows_only_from_named_tables():
    classes, fps = _symbol_build()
    rows = vl.learn_rows(classes, fps)
    assert {r["rtti_name"] for r in rows} == {"juce::AudioProcessor", "MyPlugin"}
    ap = next(r for r in rows if r["rtti_name"] == "juce::AudioProcessor")
    assert ap["slot_count"] == len(BASE_NAMES)
    # pure slots have no name of their own; the derived class that overrides them lends it (ABI: same slot, same method)
    assert [e["name"] for e in ap["slots"]][3:6] == ["prepareToPlay", "releaseResources", "processBlock"]
    assert ap["slots"][3]["pure"] and ap["slots"][3]["name_from"] == "MyPlugin" and "name_from" not in ap["slots"][5]
    assert [e["name"] for e in vl.learn_rows([classes[0]], fps)[0]["slots"]][3:5] == ["", ""]   # no derived class: stays blank
    assert all(e["fps"] for e in ap["slots"] if not e["pure"])
    # a stripped build (Ghidra default names / blanks) teaches nothing
    stripped, sfps = _stripped_build()
    assert vl.learn_rows(stripped, sfps) == []


def test_apply_needs_fingerprints_not_names(tmp_path):
    db = KnowledgeDB(tmp_path)
    classes, fps = _symbol_build()
    n = db.record_vtable_layouts("a" * 64, vl.learn_rows(classes, fps), tool_version="t", evidence_version="e")
    assert n == 2 and db.stats()["vtable_layouts"] == 2
    # same framework, stripped: confirmed, processBlock = the overridden slot 5, prepareToPlay slot 3 ...
    stripped, sfps = _stripped_build()
    r = vl.apply(db, stripped, sfps, artifact_sha256="b" * 64)
    assert r["chosen_class"] == "OtherPlugin"
    assert r["seeds"]["processBlock"] == stripped[1]["vtable_slots"][0][5]
    assert r["seeds"]["prepareToPlay"] == stripped[1]["vtable_slots"][0][3]
    assert r["seeds"]["getStateInformation"] == stripped[1]["vtable_slots"][0][10]
    assert "CANDIDATE" in r["seed_basis"]
    rep = next(c for c in r["classes"] if c["class"] == "OtherPlugin")
    assert rep["applied"]["rtti_name"] == "juce::AudioProcessor" and rep["applied"]["confidence"] == 1.0
    assert rep["methods"]["processBlock"]["overridden"] and rep["methods"]["processBlock"]["evidence"] == "INFERRED"
    # a different framework build: every name matches, no fingerprint does -> CONTRADICTED, no seeds, history row
    other, ofps = _stripped_build(other_framework=True)
    r2 = vl.apply(db, other, ofps, artifact_sha256="c" * 64)
    assert r2["seeds"] == {} and r2["chosen_class"] is None
    states = {t["state"] for c in r2["classes"] for t in c["layouts"]}
    assert "CONTRADICTED" in states and "FINGERPRINT_CONFIRMED" not in states
    assert any(h["entity_type"] == "vtable_layout" and "fingerprints did not" in h["reason"] for h in db.history_rows())
    # no fingerprints at all for the slots -> NAME_ONLY_NOT_APPLIED
    r3 = vl.apply(db, other, {}, artifact_sha256="d" * 64)
    assert r3["seeds"] == {} and {t["state"] for c in r3["classes"] for t in c["layouts"]} == {"NAME_ONLY_NOT_APPLIED"}


def test_second_symbol_build_never_overwrites_a_slot_name_silently(tmp_path):
    db = KnowledgeDB(tmp_path)
    classes, fps = _symbol_build()
    rows = vl.learn_rows(classes, fps)
    db.record_vtable_layouts("a" * 64, rows)
    rows2 = [dict(r, slots=[dict(e, name=("somethingElse" if e["slot"] == 5 else e["name"])) for e in r["slots"]]) for r in rows if r["rtti_name"] == "juce::AudioProcessor"]
    db.record_vtable_layouts("e" * 64, rows2)
    lay = db.layouts_for(["juce::AudioProcessor"])[0]
    assert lay["slots"][5]["name"] == "" and lay["verifications"] == 2 and len(lay["source_hashes"]) == 2
    assert any(h["entity_type"] == "vtable_layout" and "slot 5" in h["reason"] for h in db.history_rows())


def test_distances_bfs():
    fns = [{"addr": "0x1", "callees": ["0x2", "0x3"]}, {"addr": "0x2", "callees": ["0x4"]}, {"addr": "0x3", "callees": []}, {"addr": "0x4", "callees": ["0x1"]}, {"addr": "0x9", "callees": []}]
    d = vl.distances(fns, "0x1")
    assert d == {"0x1": 0, "0x2": 1, "0x3": 1, "0x4": 2}


def test_fp_id_is_never_a_name():
    a = _fp("x", "0x1"); b = dict(_fp("x", "0x2"), name="processBlock")
    assert fp_id(a) == fp_id(b)
