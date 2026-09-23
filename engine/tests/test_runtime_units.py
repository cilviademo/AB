"""Correlation and identity logic without a host (the host integration test lives in test_runtime_host.py)."""

from ab_engine.runtime.correlate import correlate, diff_states, parse_state_text, representation, tiers
from ab_engine.runtime.identity import juce_codes_from_cid


def test_juce_codes_from_fuid_both_layouts():
    # inline (Linux/mac) layout: ABCDEF01 9182FAEB 'Mbnd' 'Abgt'
    inline = "ABCDEF019182FAEB" + "Mbnd".encode().hex().upper() + "Abgt".encode().hex().upper()
    r = juce_codes_from_cid(inline)
    assert r and r["manufacturer_code"] == "Mbnd" and r["plugin_code"] == "Abgt" and r["kind"] == "component" and r["layout"] == "inline"
    # COM (Windows) layout: data1 LE, data2/data3 LE
    com = "01EFCDAB" + "8291" + "EBFA" + "Mbnd".encode().hex().upper() + "Abgt".encode().hex().upper()
    r2 = juce_codes_from_cid(com)
    assert r2 and r2["manufacturer_code"] == "Mbnd" and r2["layout"] == "com"
    assert juce_codes_from_cid("00" * 16) is None
    assert juce_codes_from_cid("not hex") is None


def test_state_diff_and_representation():
    a = parse_state_text('<PARAMETERS waveShapers_0_1="0.25"><PARAM id="drive" value="4.0"/><PARAM id="bypass" value="0.0"/></PARAMETERS>')
    b = parse_state_text('<PARAMETERS waveShapers_0_1="0.25"><PARAM id="drive" value="20.0"/><PARAM id="bypass" value="0.0"/></PARAMETERS>')
    assert a["waveShapers_0_1"] == "0.25" and diff_states(a, b) == ["drive"]
    assert representation("20.0", 1.0, 20.0, 0) == "PLAIN"
    assert representation("1.0", 1.0, 20.0, 0) == "NORMALIZED"
    assert representation("1.0", 1.0, 1.0, 1) == "BOOLEAN"
    assert representation("2", 1.0, 2.0, 2) == "ENUM"
    assert representation("x", 1.0, None, 0) == "OTHER"


def test_correlate_relationships_and_decoy():
    keys = [{"name": "drive"}, {"name": "cutoff"}, {"name": "waveShapers_0_1", "key_kind_candidate": "INTERNAL_EFFECT_PROPERTY (indexed array element)"}, {"name": "uiScale"}]
    params = [{"param_id": 11, "title": "drive", "step_count": 0}, {"param_id": 12, "title": "Cutoff", "step_count": 0}, {"param_id": 13, "title": "Bypass", "step_count": 1}]
    diff = {"11": {"changed": ["drive"], "field_value": "20.0", "normalized": 1.0, "plain": 20.0},
            "12": {"changed": ["cutoff"], "field_value": "20000.0", "normalized": 1.0, "plain": 20000.0}}
    m = {r.get("title") or r["key"]: r for r in correlate(keys, params, diff)}
    assert m["drive"]["relationship"] == "SAME_ID" and m["drive"]["value_representation"] == "PLAIN"
    assert m["Cutoff"]["relationship"] == "MAPPED" and m["Cutoff"]["key"] == "cutoff"
    assert m["Bypass"]["relationship"] == "RUNTIME_ONLY"           # no field changed → not claimed
    assert m["waveShapers_0_1"]["relationship"] == "STATE_ONLY" and m["waveShapers_0_1"]["basis"].startswith("runtime")
    t = {r["key"]: r["tier"] for r in tiers(correlate(keys, params, diff), ui_hints={"uiScale"})}
    assert t["waveShapers_0_1"] == "STATE_SCHEMA_FIELD" and t["uiScale"] == "UI_ONLY_CONTROL" and t["drive"] == "VST3_EXPORTED_PARAMETER"
