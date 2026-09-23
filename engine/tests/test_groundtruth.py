"""GROUND_TRUTH_REPORT gate logic on a fabricated bundle (the real stripped build is scored in CI / studio PC)."""

import hashlib
import json
from pathlib import Path

from ab_engine import api
from ab_engine.contracts import envelope, read_json
from ab_engine.groundtruth.compare import compare, default_truth_path
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs.model import Job, StageRecord

ROOT = Path(__file__).resolve().parents[2]


def _truth():
    return read_json(default_truth_path(), expect="artifactbench.ground_truth")["data"]


def _bundle(pd: Path, truth: dict, *, drop_class: str | None = None, promote_key: bool = False):
    def w(rel, schema, data):
        p = pd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(envelope(schema, data, version=2)), encoding="utf-8")
    roles = {"TptLowpass": "FILTER", "TanhShaper": "WAVESHAPER", "LicenseStub": "UNKNOWN"}
    classes = [{"recovered_name": c, "kind": "PLUGIN_OWNED_CANDIDATE", "role": roles.get(c.split("::")[-1]), "name_status": "VERIFIED_RTTI_NAME"} for c in truth["classes"] if c != drop_class]
    classes.append({"recovered_name": "juce::Slider", "kind": "FRAMEWORK", "role": None})
    w("01_evidence/rtti/classes.json", "recovery.classes", classes)
    keys = [{"name": f["id"], "runtime_parameter_status": "VERIFIED" if (promote_key and f["id"] == "drive") else "UNVERIFIED"} for f in truth["state_fields"]]
    w("03_architecture/serialized_keys.json", "recovery.serialized_keys", keys)
    res = [{"name": f"r_{i}", "ext": r["file"].split(".")[-1], "status": "VALID_EXACT", "sha256": r["sha256"]} for i, r in enumerate(truth["resources"])]
    w("01_evidence/resources/index.json", "recovery.index", res)
    w("01_evidence/resources/binarydata_map.json", "recovery.binarydata_map", [{"binarydata_name": r["binarydata_name"], "carved": None, "mapping_status": "UNRESOLVED"} for r in truth["resources"]])


def test_truth_json_is_generated_and_consistent():
    truth = _truth()
    assert [p["id"] for p in truth["parameters"]] == ["bypass", "mode", "inputGain", "cutoff", "drive", "oversample", "outputGain"]
    assert {f["id"]: f["tier"] for f in truth["state_fields"]}["waveShapers_0_1"] == "STATE_SCHEMA_FIELD"
    for r in truth["resources"]:
        assert r["sha256"] == hashlib.sha256((ROOT / "fixtures/groundtruth" / r["file"]).read_bytes()).hexdigest()


def test_phase1_gates_pass_on_a_complete_static_bundle(ws, tmp_path):
    truth = _truth()
    pd = tmp_path / "proj"
    _bundle(pd, truth)
    job = Job("gt", "ABGroundTruth", "c" * 64, "OWNED", "2026", "/x", str(pd), [StageRecord("gt", "STATIC_COMPLETE", "OK")])
    r = compare(job, truth, phase=1)
    p1 = [g for g in r["gates"] if g["phase"] == 1]
    assert all(g["ok"] for g in p1), p1
    assert r["ok_for_phase"] is True and r["false_negatives"] == [] and r["false_positives"] == []
    assert r["metrics"]["dsp_role_candidates"]["matched"] == 2
    assert r["metrics"]["identity"] is None                                  # runtime not run → null, not zero
    assert all(g["ok"] is None for g in r["gates"] if g["phase"] == 2)      # pending, never false


def test_false_negatives_and_promotion_are_caught(ws, tmp_path):
    truth = _truth()
    pd = tmp_path / "proj"
    _bundle(pd, truth, drop_class="abgt::TanhShaper", promote_key=True)
    job = Job("gt", "ABGroundTruth", "c" * 64, "OWNED", "2026", "/x", str(pd))
    r = compare(job, truth, phase=1)
    assert {"kind": "rtti_class", "item": "abgt::TanhShaper"} in r["false_negatives"]
    assert {"kind": "static_key_promoted", "item": "drive"} in r["false_positives"]
    assert r["ok_for_phase"] is False


def test_rpc_writes_report(ws, tmp_path):
    truth = _truth()
    pd = tmp_path / "proj"
    _bundle(pd, truth)
    conn = jobs_db.connect(ws.db_path)
    jobs_db.upsert_job(conn, Job("gt", "ABGroundTruth", "c" * 64, "OWNED", "2026", "/x", str(pd)))
    r = api.dispatch("groundtruth.compare", {"job_id": "gt", "phase": 1}, ws)
    assert r["ok_for_phase"] is True
    doc = read_json(pd / "06_validation" / "GROUND_TRUTH_REPORT.json", expect="artifactbench.ground_truth_report")
    assert doc["data"]["metrics"]["rtti_classes_recovered"]["ratio"] == 1.0


def test_known_source_metrics_are_separate_and_failures_classified(tmp_path):
    from ab_engine.groundtruth import known_source as ks

    report = {"metrics": {"identity": {"vendor_ok": True, "product_ok": True, "evidence": "VERIFIED_RUNTIME"},
                          "parameters": {"expected": 7, "found": 7, "defaults_ok": 7, "steps_ok": 7, "units_ok": 7},
                          "static_keys_promoted_to_parameters": {"promoted": 0}, "state_fields_found": {"expected": 11, "found": 9},
                          "state_fields_mapped": {"expected": 11, "correct": 9, "decoy_classified_from_runtime": True},
                          "rtti_classes_recovered": {"expected": 5, "recovered": 5, "ratio": 1.0, "by_source": {"ghidra_VERIFIED_RTTI": 5}},
                          "ownership_accuracy": {"expected_owned_classified_owned": 5, "of": 5, "framework_misclassified_as_owned": 0},
                          "dsp_role_candidates": {"expected": 2, "matched": 2}, "dsp_function_identification": {"top5": ["x ⊃ abgt::TanhShaper (inlined)"], "waveshaper_in_top5": True, "filter_in_top5": False, "via_inlining": True},
                          "resources": {"expected": 3, "valid_exact": 3}, "binarydata_names_present": {"seen": ["knob_png"]},
                          "process_block_path": {"processBlock": True, "prepareToPlay": True, "state_functions": True, "basis": "knowledge vtable layout"},
                          "waveshaper_differential": {"module": "Waveshaper", "classification": "BEHAVIORALLY_EQUIVALENT", "worst_rmse": 6.8e-5, "worst_spectrum_diff_db": 0.0002}, "cross_load": "CROSS_LOAD_VALIDATED"},
              "gates": [{"phase": 2, "name": "all state fields found (static ∪ runtime)", "ok": False, "detail": "9/11"}, {"phase": 3, "name": "waveshaper and filter in top-5 DSP candidates", "ok": False, "detail": "x"},
                        {"phase": 4, "name": "waveshaper BEHAVIORALLY_EQUIVALENT", "ok": True, "detail": "y"}, {"phase": 3, "name": "fingerprints stable", "ok": None, "detail": "pending"}]}
    truth = {"product": "ABGroundTruth", "classes": ["abgt::TptLowpass", "abgt::TanhShaper", "ABGroundTruthAudioProcessor"]}
    m = ks.metrics_from_report(report, truth, project_dir=tmp_path)
    assert m["never_collapsed"] and m["parameter_recall"]["ratio"] == 1.0 and m["parameter_precision"]["ratio"] == 1.0
    assert m["state_field_recall"]["ratio"] == round(9 / 11, 4) and m["class_recall"]["ratio"] == 1.0 and m["class_ownership_precision"]["ratio"] == 1.0
    assert m["dsp_classification_precision"]["via"] == ["via_inlining"] and m["source_filename_recovery"]["ratio"] == 0.0
    assert m["function_match"]["recall"] == 1.0 and m["behavioral_error"]["classification"] == "BEHAVIORALLY_EQUIVALENT"
    assert m["failure_classes"] == {"PARSER": 1, "CLASSIFICATION": 1} and m["gates"] == {"pass": 1, "fail": 2, "pending": 1}
    integ = ks.integrity({"usage_context": "KNOWN_SOURCE_FIXTURE", "source_availability": "KNOWN_SOURCE_GROUND_TRUTH"},
                         {"inputs": [{"path": "drop/Plug.vst3", "kind": "binary"}, {"path": "drop/Dsp.h", "kind": "source"}]}, Path(__file__).resolve().parents[2] / "fixtures" / "groundtruth" / "Source")
    assert integ["ok"] is False and integ["fixture_source_in_recovery_inputs"] == ["drop/Dsp.h"]     # the fixture's own source leaked into recovery
    md = ks.to_markdown(m, integ, {"fixture_id": "abgt-juce-1", "license_class": "PROPRIETARY", "license": "repo", "build_configuration": "Release", "compiler": "g++"})
    assert "never as one percentage" in md and "VIOLATED" in md and "**PARSER**" in md
