import pytest
import numpy as np

from ab_engine.behavior import probes
from ab_engine.behavior.fit import classify, fit_all
from ab_engine.behavior.metrics import harmonics, latency_from_impulse, transfer_curve


def test_probes_are_deterministic_and_named():
    for name in probes.PROBES:
        a, b = probes.make(name, 2048, 48000.0), probes.make(name, 2048, 48000.0)
        assert a.dtype == np.float32 and np.array_equal(a, b)
    w = probes.make("white", 8, 48000.0)
    # xorshift32 seed 0x12345678 first output, as the C++ host computes it
    s = 0x12345678
    s ^= (s << 13) & 0xFFFFFFFF; s ^= s >> 17; s ^= (s << 5) & 0xFFFFFFFF
    expected = np.float32(0.25) * ((np.float32(s) / np.float32(0xFFFFFFFF)) * np.float32(2) - np.float32(1))
    assert w[0] == expected
    r = probes.make("ramp", 8, 48000.0).tolist()
    assert r[:4] == pytest.approx([0.0, -4.0 / 3, -8.0 / 3, -4.0], abs=1e-6)  # settle lead-in (D-017)
    assert r[4:] == pytest.approx([-4.0, -4.0 / 3, 4.0 / 3, 4.0], abs=1e-6)  # measured sweep


def test_fit_picks_tanh_by_residual_not_name():
    x = np.linspace(-4, 4, 800)
    y = 0.8 * np.tanh(2.5 * x) / np.tanh(2.5)
    r = fit_all(np.stack([x, y], axis=1).tolist())
    assert r["chosen"] in ("tanh_normalized", "tanh"), r["chosen"]
    top = r["fits"][0]
    assert top["rmse"] < 1e-3 and abs(top["params"]["drive"] - 2.5) < 0.2
    # hard clip data must not be called tanh
    y2 = np.clip(1.5 * x, -1, 1)
    r2 = fit_all(np.stack([x, y2], axis=1).tolist())
    assert r2["chosen"] == "hard_clip"


def test_classification_thresholds():
    assert classify(0.0, 0.0, 0.0, 0) == "BIT_EXACT"
    assert classify(1e-7, 5e-6, 0.0, 0) == "NUMERICALLY_EQUIVALENT"
    assert classify(5e-5, 1e-3, 0.05, 0) == "BEHAVIORALLY_EQUIVALENT"
    assert classify(5e-5, 1e-3, 0.5, 0) == "PERCEPTUALLY_CLOSE"
    assert classify(0.2, 0.9, 6.0, 0) == "FAILED"


def test_metrics_helpers():
    sr = 48000.0
    x = probes.make("sine1k", 48000, sr)
    y = np.tanh(3 * x).astype(np.float32)
    h = harmonics(y, sr)
    assert h["thd"] is not None and h["thd"] > 0.05
    imp = np.zeros(1000, dtype=np.float32); imp[7] = 0.5
    assert latency_from_impulse(imp) == 7
    tc = transfer_curve(probes.make("ramp", 4096, sr), np.tanh(probes.make("ramp", 4096, sr)), 0)
    assert len(tc) > 500 and abs(tc[0][0] + 4.0) < 1e-6


def test_render_plan_varies_one_parameter_at_a_time():
    from ab_engine.behavior.api import render_plan
    params = [{"param_id": 1, "title": "Drive"}, {"param_id": 2, "title": "Bypass", "is_bypass": True}, {"param_id": 3, "title": "RO", "is_readonly": True}]
    plan = render_plan(params, quick=False)
    ids = [p["id"] for p in plan]
    assert "ramp_48k_256" in ids and "impulse_96000_32" in ids and "sine1k_44100_1024" in ids
    sweeps = [p for p in plan if p.get("sweep")]
    assert {s["sweep"]["title"] for s in sweeps} == {"Drive"}           # bypass and read-only are not swept
    assert all(len(s["params"]) == 1 for s in sweeps) and len(sweeps) == 5
    assert len(render_plan(params, quick=True)) < len(plan)
