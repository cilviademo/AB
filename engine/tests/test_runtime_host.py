"""vst3host integration (needs the built host and the Linux fixture build) and the always-on fuzz check:
20 malformed/hostile inputs must fail with exit codes 2–5 and never take the engine down."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ab_engine import api
from ab_engine.runtime.host import HostError, Vst3Host
from ab_engine.workers.run import run_worker

ROOT = Path(__file__).resolve().parents[2]
HOST = Path(os.environ.get("AB_VST3HOST") or ROOT / "native" / "vst3host" / "build" / "vst3host")
FIXTURE = ROOT / "fixtures" / "groundtruth" / "out" / "stripped" / "ABGroundTruth.vst3"
CLI = ROOT / "app" / "static-engine" / "dist" / "cli.mjs"
needs_host = pytest.mark.skipif(not HOST.is_file(), reason="vst3host not built")
needs_fixture = pytest.mark.skipif(not (HOST.is_file() and FIXTURE.exists()), reason="needs vst3host + built ground-truth fixture")


@pytest.fixture(autouse=True)
def _host_env(monkeypatch):
    if HOST.is_file():
        monkeypatch.setenv("AB_VST3HOST", str(HOST))


HOSTILE = [
    "", "garbage", "[]", "42", "{}", '{"command": "factory"}', '{"plugin": "/x"}',
    '{"command": "explode", "plugin": "/x"}', '{"command": "factory", "plugin": "/nonexistent/thing.vst3"}',
    '{"command": "factory", "plugin": "' + "A" * 4096 + '"}', '{"command": "factory", "plugin": 12}',
    '{"command": "render", "plugin": "/nonexistent", "probe": "nope"}', '{"command": "state", "plugin": "", "params": {"x": "y"}}',
    '{"command": "factory", "plugin": "/dev/null"}', '{"command": "factory", "plugin": "/etc/passwd"}',
    '{"command": "parameters", "plugin": "/tmp"}', '{"command": "factory", "plugin": "\\u0000"}',
    '{"command": "factory", "plugin": "/x", "timeout_s": -1}', '{"command": ["factory"], "plugin": "/x"}',
    '{"command": "factory", "plugin": "/x", "class_index": 99999999999}',
]


@needs_host
def test_fuzz_twenty_hostile_inputs_fail_cleanly(ws):
    assert len(HOSTILE) == 20
    for text in HOSTILE:
        res = run_worker("vst3host", [str(HOST), "--timeout", "10"], timeout=30, log_dir=ws.logs, stdin_text=text, parse_json_stdout=True)
        assert res.exit_code in (2, 3, 4, 5), (text[:60], res.exit_code, res.error_code)
        assert not res.timed_out or res.exit_code == 4
        assert isinstance(res.stdout_json, dict) and res.stdout_json.get("ok") is False, text[:60]


@needs_fixture
def test_host_commands_on_fixture(ws):
    host = Vst3Host(ws, ws.logs)
    f = host.call("factory", FIXTURE)["data"]
    assert f["vendor"] == "Multibanded" and any(c["name"] == "ABGroundTruth" for c in f["classes"])
    p = host.call("parameters", FIXTURE)["data"]
    titles = {x["title"] for x in p}
    assert {"Bypass", "Mode", "Input Gain", "Cutoff", "Drive", "Oversample", "Output Gain"} <= titles
    cutoff = next(x for x in p if x["title"] == "Cutoff")
    assert cutoff["units"] == "Hz" and cutoff["step_count"] == 0 and any(s["string"] == "20.0000000" for s in cutoff["samples"])
    i = host.call("info", FIXTURE)["data"]
    assert i["latency_samples"] > 0 and i["editor"]["width"] == 520     # oversampling on by default → FIR latency
    s = host.call("state", FIXTURE)["data"]
    assert 'waveShapers_0_1="0.25"' in s["component_state_text"]
    r = host.call("render", FIXTURE, probe="ramp", frames=4096, out=str(ws.tmp / "ramp.wav"))["data"]
    assert (ws.tmp / "ramp.wav").stat().st_size > 4096 * 4 and len(r["transfer_curve"]) > 100 and r["non_finite"] is False
    with pytest.raises(HostError) as ei:
        host.call("render", FIXTURE, probe="nope")
    assert ei.value.code == "BAD_REQUEST"


@needs_fixture
@pytest.mark.skipif(not (shutil.which("node") and CLI.is_file()), reason="needs static engine")
def test_full_pipeline_meets_phase2_gates(ws, tmp_path):
    job_id = api.dispatch("ingest.run", {"paths": [str(FIXTURE)], "ownership": "OWNED"}, ws)["jobs"][0]["job_id"]
    result = api.dispatch("job.run", {"job_id": job_id, "stop_after": "RUNTIME_COMPLETE", "options": {"prefer_node": True}}, ws)
    for st in ("INGESTED", "STATIC_COMPLETE", "RUNTIME_COMPLETE"):
        rec = next(s for s in result["stages"] if s["stage"] == st)
        assert rec["status"] == "OK", (st, rec["errors"])
    r = api.dispatch("groundtruth.compare", {"job_id": job_id, "phase": 2}, ws)
    failed = [g for g in r["gates"] if g["phase"] <= 2 and g["ok"] is False]
    assert not failed, failed
    assert r["metrics"]["identity"]["vendor_ok"] and r["metrics"]["parameters"]["found"] == 7
    ident = json.loads((Path(result["project_dir"]) / "03_architecture" / "identity.json").read_text())["data"]
    assert ident["manufacturer_code"] == "Mbnd" and ident["plugin_code"] == "Abgt" and ident["codes_status"].startswith("VERIFIED_RUNTIME")
    assert (Path(result["project_dir"]) / "04_reconstruction" / "identity.cmake").is_file()
