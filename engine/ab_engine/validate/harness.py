"""Differential harness (SPEC §11, EXECUTE 4.3): original vs rebuild on identical probes and state.

Every render recorded by the behaviour stage (probe, sample rate, block size, frames, parameter
settings) is replayed on the rebuild through vst3host; the original's audio comes back from the
object store by hash. Per render: sample-level error after each plugin's *reported* latency is
compensated, RMSE, max error, spectral difference (1/3-octave magnitude bands to 20 kHz, on bands
where the original carries energy above −80 dBFS), latency delta, tail delta. Classification per
render and per module uses ``behavior.fit.classify`` (BIT_EXACT … FAILED); a module's class is the
worst of its renders. Modules are assigned by what a probe exercises: the amplitude ramps validate
the waveshaper (and the gain laws), the log sweep the frequency response (filter), impulse/sine grids
the latency/tail/rate stability, noise and two-tone the aliasing/oversampling behaviour.

State cross-load (CROSS_LOAD_VALIDATED): the original's component state is loaded into the rebuild
and read back, and vice-versa; every VST3_EXPORTED_PARAMETER must survive both directions.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from ab_engine.behavior import fit as fit_mod

ORDER = ("BIT_EXACT", "NUMERICALLY_EQUIVALENT", "BEHAVIORALLY_EQUIVALENT", "PERCEPTUALLY_CLOSE", "FAILED")


def worst(classes: list[str]) -> str:
    return max(classes, key=ORDER.index) if classes else "NOT_VALIDATED"


def third_octave_bands(sr: float, n: int) -> list[tuple[float, float]]:
    bands = []
    f = 25.0
    while f < min(20000.0, sr / 2):
        bands.append((f / 2 ** (1 / 6), f * 2 ** (1 / 6)))
        f *= 2 ** (1 / 3)
    return bands


def spectrum_db(a: np.ndarray, sr: float) -> np.ndarray:
    n = len(a)
    if n < 64:
        return np.array([])
    win = np.hanning(n)
    mag = np.abs(np.fft.rfft(a * win)) / max(1.0, np.sum(win) / 2)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    out = []
    for lo, hi in third_octave_bands(sr, n):
        m = (freqs >= lo) & (freqs < hi)
        p = float(np.sum(mag[m] ** 2)) if np.any(m) else 0.0
        out.append(10 * np.log10(p + 1e-30))
    return np.asarray(out)


def _metrics(a: np.ndarray, b: np.ndarray, sr: float) -> dict[str, Any]:
    err = b - a
    rmse = float(np.sqrt(np.mean(err ** 2)))
    max_err = float(np.max(np.abs(err)))
    sa, sb = spectrum_db(a, sr), spectrum_db(b, sr)
    spec = None
    if len(sa) and len(sb):
        peak = float(max(np.max(np.abs(a)), 1e-9))
        keep = sa > 20 * np.log10(peak) - 80.0
        spec = float(np.max(np.abs(sa[keep] - sb[keep]))) if np.any(keep) else 0.0
    corr = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else (1.0 if max_err == 0 else 0.0)
    return {"rmse": rmse, "max_error": max_err, "spectrum_diff_db": spec, "correlation": corr, "samples": int(len(a))}


def compare_renders(orig: np.ndarray, reb: np.ndarray, sr: float, lat_orig: int, lat_reb: int, *, window: tuple[int, int] | None = None) -> dict[str, Any]:
    """Compare channel-0 audio after compensating each plugin's reported latency.

    Signals hotter than unity are scaled to the original's peak before the error is taken, so the
    absolute thresholds (RMSE ≤ 1e-4 …) mean the same thing at +24 dB as at 0 dB. With ``window``
    (start, end) — the ramp probe's measurement half — the classification is taken on that window
    and the excluded lead-in is reported separately (settle transients, e.g. parameter smoothing)."""
    lo, lr = max(0, int(lat_orig or 0)), max(0, int(lat_reb or 0))
    n = min(len(orig) - lo, len(reb) - lr)
    if n <= 0:
        return {"classification": "FAILED", "reason": "no overlapping samples after latency compensation", "rmse": None, "max_error": None}
    a, b = orig[lo:lo + n].astype(np.float64), reb[lr:lr + n].astype(np.float64)
    peak = float(max(np.max(np.abs(a)), 1e-9))
    scale = 1.0 / peak if peak > 1.0 else 1.0
    a, b = a * scale, b * scale
    full = _metrics(a, b, sr)
    out: dict[str, Any] = {"latency_delta": lr - lo, "peak_original": peak, "level_scale": scale, "samples_compared": int(n), "full": full}
    if window is not None:
        s0, s1 = max(0, window[0]), min(n, window[1])
        if s1 - s0 >= 64:
            win = _metrics(a[s0:s1], b[s0:s1], sr)
            lead = _metrics(a[:s0], b[:s0], sr) if s0 >= 64 else None
            out.update({"window": [s0, s1], "measured": win, "lead_in": lead})
            cls = fit_mod.classify(win["rmse"], win["max_error"], win["spectrum_diff_db"], lr - lo, peak=1.0)
            out.update({"classification": cls, "rmse": win["rmse"], "max_error": win["max_error"], "spectrum_diff_db": win["spectrum_diff_db"], "correlation": win["correlation"],
                        "rmse_full": full["rmse"], "lead_in_rmse": lead["rmse"] if lead else None,
                        "basis": "measurement window (after the ramp's settle lead-in); lead-in error reported separately"})
            return out
    cls = fit_mod.classify(full["rmse"], full["max_error"], full["spectrum_diff_db"], lr - lo, peak=1.0)
    out.update({"classification": cls, "rmse": full["rmse"], "max_error": full["max_error"], "spectrum_diff_db": full["spectrum_diff_db"], "correlation": full["correlation"],
                "rmse_full": full["rmse"], "basis": "full render"})
    return out


def module_of(item: dict[str, Any], laws: dict[str, str]) -> list[str]:
    """Which reconstructed modules a render exercises (by probe and swept parameter)."""
    probe = item.get("probe")
    sweep = (item.get("sweep") or {}).get("title")
    key = None
    for k, title in laws.get("_titles", {}).items():
        if title == sweep:
            key = k
    mods = ["Plugin"]
    if probe == "ramp":
        law = laws.get(key, "") if key else "default"
        if law == "unmodeled":
            mods.append(f"Unmodeled:{key}")
        elif key is None:
            mods.append("Waveshaper")  # the module proof: the fitted shaper at the verified default setting
        else:
            mods.append("WaveshaperSweeps")  # one parameter moved at a time (law "none" sweeps check that no effect holds in the rebuild too)
            mods.append(f"Law:{key}")
    elif probe == "log_sweep":
        mods.append("FrequencyResponse")
    elif probe in ("impulse", "sine1k"):
        mods.append("LatencyAndRateStability")
    elif probe in ("white", "pink", "two_tone", "sine_amp_sweep"):
        mods.append("AliasingAndNoise")
    elif probe in ("silence", "dc"):
        mods.append("SilenceAndDC")
    return mods


PARAM_RX = re.compile(r"<PARAM\s+id=\"([^\"]+)\"\s+value=\"([^\"]*)\"")


def parse_params(xml_text: str | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in PARAM_RX.findall(xml_text or ""):
        try:
            out[k] = float(v)
        except ValueError:
            pass
    return out


def cross_load_verdict(a_to_b: dict[str, float], a_orig: dict[str, float], b_to_a: dict[str, float], b_orig: dict[str, float], keys: list[str]) -> dict[str, Any]:
    def diff(src: dict[str, float], dst: dict[str, float]) -> list[dict[str, Any]]:
        bad = []
        for k in keys:
            if k not in src:
                continue
            if k not in dst:
                bad.append({"key": k, "issue": "missing after load"})
            elif abs(src[k] - dst[k]) > 1e-4 * max(1.0, abs(src[k])):
                bad.append({"key": k, "issue": "value changed", "from": src[k], "to": dst[k]})
        return bad
    d1, d2 = diff(a_orig, a_to_b), diff(b_orig, b_to_a)
    return {"classification": "CROSS_LOAD_VALIDATED" if not d1 and not d2 else "FAILED",
            "original_to_rebuild": {"ok": not d1, "mismatches": d1, "checked": [k for k in keys if k in a_orig]},
            "rebuild_to_original": {"ok": not d2, "mismatches": d2, "checked": [k for k in keys if k in b_orig]}}


__all__ = ["compare_renders", "module_of", "worst", "parse_params", "cross_load_verdict", "spectrum_db", "ORDER"]
