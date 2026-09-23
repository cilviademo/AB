"""ADDENDUM C3: recovery goal, transformation graph, recovered_source / transformed_source, statuses."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ab_engine.transform import goals, graph, modernize

WS = {"name": "Waveshaper", "role": "WAVESHAPER", "active": True, "family": "tanh_normalized", "params": {"k": 2.0}, "rmse": 6.8e-05, "max_error": 1e-4, "correlation": 0.9999,
      "classification_at_default": "BEHAVIORALLY_EQUIVALENT", "reference": "ramp_48k_256", "curve_points": 8192, "x_range": [-4, 4], "family_basis": "residual", "candidates": [],
      "drive": 1.0, "post": 0.5, "status": "BEHAVIOR_MATCHED",
      "modulation": [{"key": "inputGain", "law": "db", "knob": "pre", "status": "BEHAVIOR_MATCHED", "basis": "sweep", "worst_rmse_ref": 1e-5, "points": [], "title": "Input Gain"},
                     {"key": "mode", "law": "discrete", "knob": "drive", "status": "BEHAVIOR_MATCHED", "basis": "sweep", "worst_rmse_ref": 1e-5, "title": "Mode",
                      "points": [{"value": 0, "passthrough": False, "is_linear": True, "linear": {"slope": 0.5012, "rmse": 1e-5}, "knob": "drive", "factor": 1.0, "rmse": 1e-5, "normalized": 0.0},
                                 {"value": 2, "knob": "drive", "factor": 2.0, "rmse": 1e-5, "normalized": 1.0}]},
                     {"key": "cutoff", "law": "unmodeled", "knob": "pre", "status": "UNMODELED", "basis": "filter", "worst_rmse_ref": 0.02, "points": [], "title": "Cutoff"}]}
PARAMS = [{"key": "inputGain", "title": "Input Gain", "kind": "float", "min": -24.0, "max": 24.0, "skew": 1.0, "units": "dB", "default": 0.0, "generate": True, "id_status": "VERIFIED_RUNTIME", "range_status": "VERIFIED_RUNTIME", "default_status": "VERIFIED_RUNTIME", "note": ""},
          {"key": "mode", "title": "Mode", "kind": "choice", "choices": [{"name": "Clean", "status": "VERIFIED_RUNTIME"}, {"name": "Warm", "status": "VERIFIED_RUNTIME"}, {"name": "Hot", "status": "VERIFIED_RUNTIME"}], "default": 1, "generate": True, "id_status": "VERIFIED_RUNTIME", "range_status": "VERIFIED_RUNTIME", "default_status": "VERIFIED_RUNTIME", "note": ""},
          {"key": "cutoff", "title": "Cutoff", "kind": "float", "min": 20.0, "max": 20000.0, "skew": 0.3, "units": "Hz", "default": 1000.0, "generate": True, "id_status": "VERIFIED_RUNTIME", "range_status": "VERIFIED_RUNTIME", "default_status": "VERIFIED_RUNTIME", "note": ""}]
MODEL = {"build_kind": "SURROGATE", "identity": {"codes_status": "VERIFIED_RUNTIME (JUCE FUID derivation)", "product": "P"}, "parameters": PARAMS,
         "state": {"root_tag": "PARAMETERS", "state_only": [], "format": "xml", "root_status": "VERIFIED_RUNTIME"}, "modules": [WS], "scaffolds": [{"name": "abgt::Filt", "role": "FILTER", "structure_status": "VERIFIED_VTABLE", "vtables": ["0x1"]}], "dsp_functions": []}


def test_goals_and_switches():
    assert goals.normalize_goal("preserve original") == "PRESERVE_ORIGINAL" and goals.normalize_goal("modernize") == "MODERNIZE"
    with pytest.raises(ValueError):
        goals.normalize_goal("rewrite")
    sw = goals.switches_from_options({"preserve_dsp_behavior": "no", "replace_activation_backend": "1"})
    assert sw["preserve_dsp_behavior"] == "NO" and sw["replace_activation_backend"] == "YES" and sw["preserve_preset_compatibility"] == "YES"
    p = goals.plan("MIGRATE", sw)
    assert p["transformed"] and not p["available"] and p["active_variant"] == "RECOVERED" and "not implemented" in p["not_available_reason"]
    assert goals.plan("PRESERVE_ORIGINAL", sw)["naming_default"] == "PRESERVE_ORIGINAL_NAMES" and goals.plan("MODERNIZE", sw)["naming_default"] == "CANONICALIZE_NAMES"


def test_preserve_original_has_no_transformation_nodes_and_modernize_has():
    g0 = graph.build(MODEL, goals.plan("PRESERVE_ORIGINAL", dict(goals.SWITCHES)), None)
    assert g0["transformation_nodes"] == 0 and g0["active_variant"] == "RECOVERED"
    assert {s["subsystem"] for s in g0["subsystems"]} == {"DSP", "State", "Identity", "Scaffold"}
    g1 = graph.build(MODEL, goals.plan("MODERNIZE", dict(goals.SWITCHES)), None)
    assert g1["transformation_nodes"] == 2 and g1["active_variant"] == "TRANSFORMED"
    dsp = next(s for s in g1["subsystems"] if s["subsystem"] == "DSP")
    assert [n["node"] for n in dsp["nodes"]] == ["BINARY_EVIDENCE", "RECOVERED_IMPLEMENTATION", "SEMANTIC_RECONSTRUCTION", "TRANSFORMED_IMPLEMENTATION", "VALIDATION"]
    assert dsp["status"] == "PENDING_VALIDATION" and dsp["preserve"] == "YES"
    # validation fills the graph: equivalent → MODERNIZED_EQUIVALENT; a failed DSP with preserve YES → TRANSFORMED_BREAKING listed as a change
    ok = graph.update_with_validation(json.loads(json.dumps(g1)), variant="TRANSFORMED", modules=[{"module": "Waveshaper", "classification": "BEHAVIORALLY_EQUIVALENT", "worst_rmse": 7e-5}],
                                      cross={"classification": "CROSS_LOAD_VALIDATED"}, licensing=None, comparisons=[{"pair": "ORIGINAL↔TRANSFORMED", "renders": 79}])
    assert next(s for s in ok["subsystems"] if s["subsystem"] == "DSP")["status"] == "MODERNIZED_EQUIVALENT"
    assert next(s for s in ok["subsystems"] if s["subsystem"] == "State")["status"] == "TRANSFORMED_COMPATIBLE" and ok["intentional_behavioral_changes"] == []
    bad = graph.update_with_validation(json.loads(json.dumps(g1)), variant="TRANSFORMED", modules=[{"module": "Waveshaper", "classification": "FAILED", "worst_rmse": 0.3}],
                                       cross={"classification": "FAILED"}, licensing=None, comparisons=[])
    assert next(s for s in bad["subsystems"] if s["subsystem"] == "DSP")["status"] == "TRANSFORMED_BREAKING"
    assert bad["intentional_behavioral_changes"] and bad["intentional_behavioral_changes"][0]["status"] == "TRANSFORMED_BREAKING" and bad["intentional_behavioral_changes"][0]["intended"] is False
    # a licensing bypass in the transformed source lands in the graph as a listed change
    g2 = graph.build(MODEL, goals.plan("MODERNIZE", dict(goals.SWITCHES)), None, licensing_entries=[{"symbol": "abgt::LicenseStub", "file": "x", "status": "SCAFFOLD_ONLY", "compiled": False}])
    g2 = graph.update_with_validation(g2, variant="TRANSFORMED", modules=[], cross={}, comparisons=[],
                                      licensing={"entries": [{"symbol": "abgt::LicenseStub", "state": "LICENSE_REQUIRES_MANUAL_REVIEW", "reason": "r"}],
                                                 "bypass_findings": [{"symbol": "LicenseStub::checkSerial", "kind": "CONSTANT_RETURN", "status": "TRANSFORMED_BREAKING"}]})
    lic = next(s for s in g2["subsystems"] if s["subsystem"] == "Licensing")
    assert lic["status"] == "TRANSFORMED_BREAKING" and "never recovery" in lic["intentional_behavioral_changes"][0]["rule"]


def test_modernized_module_keeps_the_recovered_laws():
    src = modernize.saturation_source(WS, PARAMS)
    assert "class SaturationStage" in src and "namespace ab_transformed" in src
    assert "void prepare (const juce::AudioProcessorValueTreeState& apvts) noexcept" in src and "getRawParameterValue (\"inputGain\")" in src
    assert "decibelsToGain" in src and "linearSlope = 0.5012" in src and "drive *= 2.0f" in src        # the same laws
    assert "template <typename ProcessContext>" in src and "[[nodiscard]] float processSample" in src
    assert "cutoff" not in src.split("void update()")[1].split("isPassthrough")[0] or "unmodeled" in src   # an unmodeled law adds nothing


def test_generate_writes_both_trees_and_active_from_the_goal(tmp_path: Path):
    """On the synthetic project of test_reconstruct: PRESERVE_ORIGINAL keeps Active = recovered; MODERNIZE writes
    transformed_source/ and builds Active from it, while recovered_source/ stays."""
    from ab_engine.reconstruct import api as rapi
    from tests.test_reconstruct import _synthetic_project

    p = _synthetic_project(tmp_path)
    out = rapi.reconstruct(p, goal="PRESERVE_ORIGINAL")
    rec = p / "04_reconstruction"
    assert (rec / "recovered_source" / "Waveshaper.h").is_file() and (rec / "Source" / "Active" / "DSP" / "Waveshaper.h").is_file()
    assert not (rec / "transformed_source" / "DSP").exists() and "PRESERVE_ORIGINAL" in (rec / "transformed_source" / "README.md").read_text()
    assert out["summary"]["active_variant"] == "RECOVERED" and all(e.get("variant") != "TRANSFORMED" for e in out["index"])
    g0 = json.loads((rec / "transformation_graph.json").read_text())["data"]
    assert g0["transformation_nodes"] == 0 and (rec / "identifier_map.json").is_file() and json.loads((rec / "identifier_map.json").read_text())["data"]["mode"] == "PRESERVE_ORIGINAL_NAMES"
    out2 = rapi.reconstruct(p, goal="MODERNIZE")
    assert (rec / "transformed_source" / "DSP" / "Saturation.h").is_file() and (rec / "Source" / "Active" / "DSP" / "Saturation.h").is_file()
    assert (rec / "recovered_source" / "Waveshaper.h").is_file()                                       # the recovered tree is always kept
    proc = (rec / "Source" / "Active" / "PluginProcessor.cpp").read_text()
    assert "juce::dsp::ProcessContextReplacing<float>" in proc and "shaper.prepare (apvts)" in proc
    t = next(e for e in out2["index"] if e.get("variant") == "TRANSFORMED")
    assert t["symbol"] == "ab_transformed::SaturationStage" and t["recovered_symbol"] == "ab_rebuild::Waveshaper" and t["transformation_status"] == "PENDING_VALIDATION"
    r = next(e for e in out2["index"] if e.get("symbol") == "ab_rebuild::Waveshaper")
    assert r["compiled"] is False and r["file"].endswith("recovered_source/Waveshaper.h")
    g1 = json.loads((rec / "transformation_graph.json").read_text())["data"]
    assert g1["transformation_nodes"] >= 1 and g1["active_variant"] == "TRANSFORMED" and json.loads((rec / "identifier_map.json").read_text())["data"]["mode"] == "CANONICALIZE_NAMES"
    # a goal without a generator is recorded, never faked
    out3 = rapi.reconstruct(p, goal="MIGRATE")
    assert out3["plan"]["available"] is False and out3["summary"]["active_variant"] == "RECOVERED" and "not implemented" in out3["plan"]["not_available_reason"]
