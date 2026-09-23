"""ADDENDUM A6 (Git checkpoints) and A4 (YARA candidate families)."""
from __future__ import annotations

from pathlib import Path

import pytest

from ab_engine import checkpoint, deps
from ab_engine.lineage import rules

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"


@pytest.mark.skipif(not checkpoint.available(), reason="git")
def test_checkpoint_sequence_and_clean_status(tmp_path):
    p = tmp_path / "proj"
    assert checkpoint.init(p)["status"] == "OK" and (p / ".gitignore").is_file()
    (p / "00_manifest").mkdir()
    (p / "00_manifest" / "input_manifest.json").write_text("{}")
    r = checkpoint.commit(p, "INGESTED", job_id="ab-1")
    assert r["status"] == "COMMITTED" and r["message"] == "ingest: add recovered artifacts"
    assert checkpoint.commit(p, "INGESTED")["status"] == "NOTHING_TO_COMMIT"
    (p / "01_evidence").mkdir()
    (p / "01_evidence" / "x.json").write_text("{}")
    (p / "05_reference_behavior" / "original_renders").mkdir(parents=True)
    (p / "05_reference_behavior" / "original_renders" / "big.wav").write_bytes(b"\0" * 1024)  # ignored
    checkpoint.commit(p, "RUNTIME_COMPLETE")
    (p / "04_reconstruction").mkdir()
    (p / "04_reconstruction" / "Waveshaper.h").write_text("// x")
    checkpoint.commit(p, "RECONSTRUCTION_COMPLETE", metrics={"modules_detail": [{"name": "Waveshaper"}]})
    (p / "06_validation").mkdir()
    (p / "06_validation" / "differential_results.json").write_text("{}")
    checkpoint.commit(p, "VALIDATION_COMPLETE", metrics={"modules": {"Waveshaper": "BEHAVIORALLY_EQUIVALENT"}, "waveshaper_rmse": "6.85e-05"})
    subjects = [c["subject"] for c in checkpoint.log(p)]
    assert subjects[0] == "validation: Waveshaper matched original (BEHAVIORALLY_EQUIVALENT, rmse=6.85e-05)"
    assert "reconstruction: implement Waveshaper" in subjects and "recovery: import verified runtime metadata" in subjects
    assert checkpoint.status_clean(p)
    assert checkpoint._git(p, "ls-files").stdout.count("big.wav") == 0


@pytest.mark.skipif(not deps.available("yara"), reason="yara-python")
def test_yara_rules_emit_candidates_only():
    r = rules.scan(FIXTURE)
    assert r["status"] == "OK" and {"families.yar", "thirdparty.yar", "framework.yar"} <= set(r["rules"])
    names = {c["rule"] for c in r["candidates"]}
    assert "AB.Framework.JUCE" in names
    assert all(c["status"] in ("CANDIDATE_FAMILY", "CANDIDATE_LIBRARY") for c in r["candidates"])
    assert all(c["distinct_markers"] >= 1 and c["matched_strings"] for c in r["candidates"])
    assert not any(c["rule"].startswith("AB.Family.") for c in r["candidates"])  # the synthetic fixture belongs to no corpus generation
