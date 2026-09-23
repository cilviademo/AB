import json

import pytest

from ab_engine.contracts import ContractError, envelope, read_json, validate, write_json


def test_envelope_families():
    assert envelope("recovery.binary", {})["schema_version"] == 2
    assert envelope("artifactbench.stage", {})["schema_version"] == 1
    with pytest.raises(ContractError):
        envelope("other.thing", {})


def test_unknown_major_is_rejected_not_reinterpreted():
    doc = envelope("artifactbench.doctor", {"ok": True, "rows": [], "counts": {}, "workspace": {}})
    doc["schema_version"] = 2
    with pytest.raises(ContractError, match="refusing to reinterpret"):
        validate(doc)


def test_payload_schema_enforced(tmp_path):
    with pytest.raises(ContractError):
        write_json(tmp_path / "x.json", "artifactbench.doctor", {"ok": "yes"})
    path = tmp_path / "ok.json"
    write_json(path, "artifactbench.doctor", {"ok": True, "rows": [], "counts": {}, "workspace": {}})
    doc = read_json(path, expect="artifactbench.doctor")
    assert doc["data"]["ok"] is True
    assert not (tmp_path / "ok.json.partial").exists()


def test_stage_schema_rejects_bad_status():
    doc = envelope("artifactbench.stage", {
        "job_id": "j", "stage": "STATIC_COMPLETE", "status": "DONE", "input_hashes": [], "tool_versions": {},
        "config_hash": "", "stage_version": 1, "started": None, "ended": None, "warnings": [], "errors": [],
        "outputs": [], "completeness": "NOT_APPLICABLE"})
    with pytest.raises(ContractError):
        validate(doc)
    doc["data"]["status"] = "OK"
    assert validate(doc) == "artifactbench.stage"
    json.dumps(doc)
