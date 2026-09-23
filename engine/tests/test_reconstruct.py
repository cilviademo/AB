"""Phase 4 unit tests: fit-family code generation, evidence model laws, generator output, harness classification."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from ab_engine.behavior import fit as fit_mod
from ab_engine.contracts import write_json
from ab_engine.reconstruct import families, generate, model
from ab_engine.validate import harness


def test_family_expressions_cover_every_fit_family():
    for fam in list(fit_mod.FAMILIES) + ["poly_odd_3", "poly_odd_5", "piecewise_cubic_3", "lut_65"]:
        params = {"gain": 1.0, "drive": 2.0}
        if fam.startswith("poly"):
            params = {"coefficients": [1.0, -0.1, 0.01][: (int(fam[-1]) + 1) // 2]}
        if fam == "piecewise_cubic_3":
            params = {"segments": [{"abs_x_from": 0, "abs_x_to": 1.0, "coefficients": [0, 0, 1, 0]}, {"abs_x_from": 1.0, "abs_x_to": None, "coefficients": [0, 0, 0.5, 0.5]}]}
        if fam == "lut_65":
            params = {"x": [float(v) for v in np.linspace(-1, 1, 65)], "y": [float(np.tanh(v)) for v in np.linspace(-1, 1, 65)]}
        decl, expr = families.shape_body(fam, params)
        assert expr and ("u" in expr or "x" in expr)
        assert families.describe(fam)


def test_juce_param_id_matches_hashcode_rule():
    assert model.juce_param_id("inputGain") == 1706566249
    assert model.juce_param_id("bypass") == 773352680


def _write_curve(tc: Path, name: str, x: np.ndarray, y: np.ndarray, sweep: dict | None):
    write_json(tc / f"{name}.json", "artifactbench.transfer_curve",
               {"probe": {"id": name, "probe": "ramp", "sr": 48000.0, "block": 256, "params": {}, "frames": 96000, **({"sweep": sweep} if sweep else {})},
                "latency_used": 0, "curve": [[float(a), float(b)] for a, b in zip(x, y)]})


def _synthetic_project(tmp_path: Path) -> Path:
    """A project whose ORIGINAL is y = post·tanh(pre·drive·x)/tanh(drive): gain params in dB, drive proportional, a bypass switch."""
    p = tmp_path / "proj"
    for d in ("01_evidence/vst3", "03_architecture", "05_reference_behavior/transfer_curves", "01_evidence/rtti", "02_recovered_assets/images", "04_reconstruction", "07_agent_handoff"):
        (p / d).mkdir(parents=True)
    def samples(strings):
        return [{"normalized": n, "plain": n, "round_trip_normalized": n, "string": s} for n, s in zip((0, 0.25, 0.5, 0.75, 1), strings)]
    params = [
        {"param_id": model.juce_param_id("gainIn"), "title": "Gain In", "index": 0, "step_count": 0, "default_normalized": 0.5, "units": "dB", "samples": samples(["-12.0", "-6.0", "0.0", "6.0", "12.0"]), "is_bypass": False, "is_list": False, "can_automate": True, "is_readonly": False, "is_hidden": False, "flags": 1, "unit_id": 0, "evidence": "VERIFIED_RUNTIME"},
        {"param_id": model.juce_param_id("amount"), "title": "Amount", "index": 1, "step_count": 0, "default_normalized": 0.25, "units": "", "samples": samples(["1.0", "2.0", "3.0", "4.0", "5.0"]), "is_bypass": False, "is_list": False, "can_automate": True, "is_readonly": False, "is_hidden": False, "flags": 1, "unit_id": 0, "evidence": "VERIFIED_RUNTIME"},
        {"param_id": model.juce_param_id("kill"), "title": "Kill", "index": 2, "step_count": 1, "default_normalized": 0.0, "units": "", "samples": samples(["Off", "Off", "On", "On", "On"]), "is_bypass": False, "is_list": False, "can_automate": True, "is_readonly": False, "is_hidden": False, "flags": 1, "unit_id": 0, "evidence": "VERIFIED_RUNTIME"},
        {"param_id": 12345, "title": "Bypass", "index": 3, "step_count": 1, "default_normalized": 0.0, "units": "", "samples": samples(["Off", "Off", "On", "On", "On"]), "is_bypass": True, "is_list": False, "can_automate": True, "is_readonly": False, "is_hidden": False, "flags": 1, "unit_id": 0, "evidence": "VERIFIED_RUNTIME"},
    ]
    write_json(p / "01_evidence/vst3/runtime_parameters.json", "artifactbench.runtime_parameters", params)
    tiers = [{"param_id": params[0]["param_id"], "title": "Gain In", "key": "gainIn", "relationship": "MAPPED", "value_representation": "PLAIN", "tier": "VST3_EXPORTED_PARAMETER"},
             {"param_id": params[1]["param_id"], "title": "Amount", "key": "amount", "relationship": "MAPPED", "value_representation": "PLAIN", "tier": "VST3_EXPORTED_PARAMETER"},
             {"param_id": params[2]["param_id"], "title": "Kill", "key": "kill", "relationship": "MAPPED", "value_representation": "BOOLEAN", "tier": "VST3_EXPORTED_PARAMETER"}]
    write_json(p / "03_architecture/parameters.json", "artifactbench.parameters", {"tiers": tiers, "runtime_parameters": params, "note": "test"})
    write_json(p / "01_evidence/vst3/state_baseline.json", "artifactbench.state",
               {"component_state_text": '<?xml version="1.0"?> <STATE extra="0.5"><PARAM id="gainIn" value="0.0"/><PARAM id="amount" value="2.0"/><PARAM id="kill" value="0.0"/></STATE>', "component_state_b64": "x", "evidence": "VERIFIED_RUNTIME"})
    write_json(p / "03_architecture/identity.json", "artifactbench.identity", {"vendor": "Test Co", "product": "Shaper Test", "processor_fuid": "00", "manufacturer_code": "Tstc", "plugin_code": "Shpr", "evidence": "VERIFIED_RUNTIME",
                                                                                "codes_status": "VERIFIED_RUNTIME", "latency_samples": 2, "tail_samples": 0, "buses": {"input_audio": [{"channel_count": 2}], "output_audio": [{"channel_count": 2}]}, "editor": {"width": 300, "height": 200}})
    write_json(p / "01_evidence/rtti/classes.json", "recovery.classes", [{"recovered_name": "test::Shaper", "kind": "PLUGIN_OWNED_CANDIDATE", "role": "WAVESHAPER", "role_status": "CANDIDATE", "safe_name": "Shaper", "name_status": "VERIFIED_RTTI_NAME"},
                                                                          {"recovered_name": "test::Lic", "kind": "PLUGIN_OWNED_CANDIDATE", "role": "PROTECTED_SUBSYSTEM", "role_status": "CANDIDATE", "safe_name": "Lic", "name_status": "VERIFIED_RTTI_NAME"}])
    (p / "02_recovered_assets/images/png_000.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    x = np.linspace(-4, 4, 1024)
    d0, post0 = 2.0, 0.8
    f = lambda pre, d, post: post * np.tanh(pre * d * x) / np.tanh(d)  # noqa: E731
    tc = p / "05_reference_behavior/transfer_curves"
    _write_curve(tc, "ramp_48k_256", x, f(1, d0, post0), None)
    for pos, db in zip((0, 0.25, 0.5, 0.75, 1), (-12, -6, 0, 6, 12)):
        _write_curve(tc, f"ramp_Gain_In_{pos}", x, f(10 ** (db / 20), d0, post0), {"param_id": params[0]["param_id"], "title": "Gain In", "normalized": pos})
    for pos, plain in zip((0, 0.25, 0.5, 0.75, 1), (1, 2, 3, 4, 5)):
        _write_curve(tc, f"ramp_Amount_{pos}", x, f(1, plain, post0), {"param_id": params[1]["param_id"], "title": "Amount", "normalized": pos})
    _write_curve(tc, "ramp_Kill_0.0", x, f(1, d0, post0), {"param_id": params[2]["param_id"], "title": "Kill", "normalized": 0.0})
    _write_curve(tc, "ramp_Kill_1.0", x, x.copy(), {"param_id": params[2]["param_id"], "title": "Kill", "normalized": 1.0})
    return p


def test_model_recovers_laws_and_gates(tmp_path):
    p = _synthetic_project(tmp_path)
    m = model.build(p, build_kind="FIDELITY")
    assert m["build_kind"] == "FIDELITY"
    ws = m["modules"][0]
    assert ws["family"] == "tanh_normalized" and ws["active"] and ws["rmse"] < 1e-6
    laws = {mo["key"]: (mo["law"], mo["knob"]) for mo in ws["modulation"]}
    assert laws["gainIn"] == ("db", "pre")
    assert laws["amount"] == ("proportional", "drive")
    assert laws["kill"][0] == "passthrough"
    keys = {q["key"] for q in m["parameters"] if q.get("generate")}
    assert keys == {"gainIn", "amount", "kill"}  # the wrapper bypass is not regenerated
    assert m["state"]["root_tag"] == "STATE" and m["state"]["state_only"][0]["key"] == "extra"
    assert [c["name"] for c in m["scaffolds"]] == ["test::Shaper", "test::Lic"] or {c["name"] for c in m["scaffolds"]} >= {"test::Lic"}


def test_fidelity_refused_without_verified_identity(tmp_path):
    p = _synthetic_project(tmp_path)
    ident = json.loads((p / "03_architecture/identity.json").read_text())
    ident["data"]["evidence"] = "INFERRED"
    (p / "03_architecture/identity.json").write_text(json.dumps(ident))
    m = model.build(p, build_kind="FIDELITY")
    assert m["build_kind"] == "SURROGATE" and "fidelity_refused" in m["identity"]


def test_generate_writes_active_only_for_validated_modules(tmp_path):
    p = _synthetic_project(tmp_path)
    m = model.build(p)
    out = generate.generate(p, m)
    rec = p / "04_reconstruction"
    assert (rec / "Source/Active/DSP/Waveshaper.h").is_file() and (rec / "recovered_source/Waveshaper.h").is_file()
    src = (rec / "Source/Active/DSP/Waveshaper.h").read_text()
    assert "std::tanh (u) / std::tanh (drive)" in src
    assert 'decibelsToGain (apvts.getRawParameterValue ("gainIn")->load() - 0.0f)' in src
    assert 'getRawParameterValue ("amount")->load() / 2.0f' in src
    assert 'getRawParameterValue ("kill")->load() >= 0.5f) passthrough = true' in src
    layout = (rec / "Source/Active/Parameters.h").read_text()
    assert 'juce::ParameterID { "gainIn", 1 }' in layout and 'withLabel ("dB")' in layout and 'AudioParameterBool> (juce::ParameterID { "kill", 1 }' in layout
    cmake = (rec / "CMakeLists.txt").read_text()
    assert "AB_BUILD_KIND" in cmake and "Source/Active/PluginProcessor.cpp" in cmake and "RecoveredScaffolds" not in re.sub(r"#.*", "", cmake)
    assert "Resources/png_000.png" in cmake
    ws_entry = next(e for e in out["index"] if e.get("role") == "WAVESHAPER")
    assert ws_entry["compiled"] and ws_entry["status"] == "BEHAVIOR_MATCHED" and ws_entry["validation"].startswith("PENDING")
    lic = next(e for e in out["index"] if e["symbol"] == "test::Lic")
    assert lic["compiled"] is False and lic["subsystem"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" and "TRANSFORMED_BREAKING" in lic["promotion"]   # v2 PROTECTED_SUBSYSTEM input → aliased
    # a weak fit stays out of Active
    m["modules"][0]["active"] = False
    out2 = generate.generate(p, m)
    proc = (rec / "Source/Active/PluginProcessor.h").read_text()
    assert "did not reach BEHAVIORALLY_EQUIVALENT" in proc and next(e for e in out2["index"] if e.get("role") == "WAVESHAPER")["compiled"] is False


def test_harness_classification_and_cross_load():
    sr = 48000.0
    x = np.linspace(-1, 1, 8192).astype(np.float32)
    y = np.tanh(3 * x)
    same = harness.compare_renders(y, y.copy(), sr, 0, 0)
    assert same["classification"] == "BIT_EXACT"
    shifted = harness.compare_renders(np.concatenate([np.zeros(3, np.float32), y]), y, sr, 3, 0)
    assert shifted["classification"] in ("BIT_EXACT", "NUMERICALLY_EQUIVALENT") and shifted["latency_delta"] == -3
    close = harness.compare_renders(y, (y * np.float32(1.00005)).astype(np.float32), sr, 0, 0)
    assert close["classification"] == "BEHAVIORALLY_EQUIVALENT"
    bad = harness.compare_renders(y, 0.5 * y, sr, 0, 0)
    assert bad["classification"] == "FAILED"
    assert harness.worst(["BIT_EXACT", "PERCEPTUALLY_CLOSE", "BEHAVIORALLY_EQUIVALENT"]) == "PERCEPTUALLY_CLOSE"
    a = harness.parse_params('<S><PARAM id="a" value="1.0"/><PARAM id="b" value="2.5"/></S>')
    v = harness.cross_load_verdict(a, a, {"a": 1.0, "b": 2.5}, {"a": 1.0, "b": 2.5}, ["a", "b"])
    assert v["classification"] == "CROSS_LOAD_VALIDATED"
    v2 = harness.cross_load_verdict({"a": 1.0}, a, a, a, ["a", "b"])
    assert v2["classification"] == "FAILED" and v2["original_to_rebuild"]["mismatches"][0]["key"] == "b"


def test_module_assignment_by_probe():
    laws = {"_titles": {"gainIn": "Gain In", "cut": "Cut"}, "gainIn": "db", "cut": "unmodeled"}
    assert "Waveshaper" in harness.module_of({"probe": "ramp"}, laws)
    assert "Law:gainIn" in harness.module_of({"probe": "ramp", "sweep": {"title": "Gain In"}}, laws)
    assert "Unmodeled:cut" in harness.module_of({"probe": "ramp", "sweep": {"title": "Cut"}}, laws)
    assert "FrequencyResponse" in harness.module_of({"probe": "log_sweep"}, laws)


def test_surrogate_codes_are_stable_and_four_chars():
    a, b = generate.surrogate_codes("Some Plugin")
    assert a == "AbSr" and len(b) == 4 and (a, b) == generate.surrogate_codes("Some Plugin")


def test_stripped_build_scaffolds_decompiler_only_classes(tmp_path):
    """D-025 / C2 on a stripped binary: the static v2 RTTI list is empty and every class comes from the decompiler's
    structural pass (03_architecture/classes.json). They are owned candidates and get scaffolds — the licensing stub
    included — instead of silently vanishing from the reconstruction."""
    p = _synthetic_project(tmp_path)
    write_json(p / "01_evidence/rtti/classes.json", "recovery.classes", [])
    write_json(p / "03_architecture/classes.json", "artifactbench.classes_verified", [
        {"recovered_name": "abgt::LicenseStub", "kind": "PLUGIN_OWNED_CANDIDATE", "role": "LICENSING_AND_ENTITLEMENT_SUBSYSTEM", "role_status": "CANDIDATE", "role_basis": ["name tokens"], "name_status": "VERIFIED_RTTI", "vtables": [], "methods": [], "bases": []},
        {"recovered_name": "abgt::TanhShaper", "kind": "PLUGIN_OWNED_CANDIDATE", "role": "WAVESHAPER", "role_status": "CANDIDATE", "role_basis": ["name tokens"], "name_status": "VERIFIED_RTTI", "vtables": [], "methods": [], "bases": []},
        {"recovered_name": "juce::AudioProcessor", "kind": "FRAMEWORK", "role": "FRAMEWORK", "role_status": "VERIFIED", "name_status": "VERIFIED_RTTI", "vtables": [], "methods": [], "bases": []},
    ])
    classes = model.owned_classes(p)
    assert {c["name"] for c in classes} == {"abgt::LicenseStub", "abgt::TanhShaper"}          # framework rows never become scaffolds
    m = model.build(p)
    out = generate.generate(p, m)
    lic = next(e for e in out["index"] if e["symbol"] == "abgt::LicenseStub")
    assert lic["subsystem"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" and lic["compiled"] is False and "TRANSFORMED_BREAKING" in lic["promotion"]
    assert (p / "04_reconstruction" / "Source" / "RecoveredScaffolds" / "Licensing").is_dir()
