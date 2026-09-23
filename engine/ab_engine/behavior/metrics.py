"""Measurements over rendered audio (SPEC §11): peak, RMS, latency (measured vs reported), tail,
frequency/phase response (from the log sweep), harmonics/THD (from the 1 kHz sine), aliasing energy
(from the two-tone), transfer curve (from the ramp)."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    data = Path(path).read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    p = 12
    fmt = None
    pcm = b""
    while p + 8 <= len(data):
        tag, size = data[p:p + 4], struct.unpack("<I", data[p + 4:p + 8])[0]
        body = data[p + 8:p + 8 + size]
        if tag == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif tag == b"data":
            pcm = body
        p += 8 + size + (size & 1)
    assert fmt is not None
    code, ch, sr, _, _, bits = fmt
    if code == 3 and bits == 32:
        arr = np.frombuffer(pcm, dtype="<f4")
    elif code == 1 and bits == 16:
        arr = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    else:
        raise ValueError(f"unsupported wav format {code}/{bits}")
    return arr.reshape(-1, ch).T.astype(np.float32), sr


def basic(y: np.ndarray) -> dict[str, float]:
    return {"peak": float(np.max(np.abs(y))) if y.size else 0.0, "rms": float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) if y.size else 0.0,
            "dc": float(np.mean(y)) if y.size else 0.0, "non_finite": bool(np.any(~np.isfinite(y)))}


def latency_from_impulse(y: np.ndarray, thresh: float = 1e-5) -> int:
    idx = np.flatnonzero(np.abs(y) > thresh)
    return int(idx[0]) if idx.size else -1


def tail_samples(y: np.ndarray, input_len: int, floor_db: float = -100.0) -> int:
    thr = 10 ** (floor_db / 20)
    idx = np.flatnonzero(np.abs(y) > thr)
    return int(max(0, idx[-1] - input_len + 1)) if idx.size else 0


def harmonics(y: np.ndarray, sr: float, f0: float = 1000.0, n_harm: int = 10) -> dict[str, Any]:
    n = len(y)
    if n < 1024:
        return {"thd": None, "harmonics_db": []}
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(y.astype(np.float64) * win)) / (n / 2)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    def mag(f):
        k = int(round(f * n / sr))
        lo, hi = max(0, k - 2), min(len(spec), k + 3)
        return float(np.max(spec[lo:hi])) if hi > lo else 0.0
    fund = mag(f0)
    harms = [mag(f0 * h) for h in range(2, n_harm + 1) if f0 * h < sr / 2]
    thd = float(np.sqrt(sum(h * h for h in harms)) / fund) if fund > 0 else None
    return {"fundamental": fund, "thd": thd, "thd_db": (20 * np.log10(thd) if thd and thd > 0 else None),
            "harmonics_db": [round(20 * np.log10(h / fund), 2) if fund > 0 and h > 0 else None for h in harms], "bin_hz": float(freqs[1])}


def response(x: np.ndarray, y: np.ndarray, sr: float, bands: int = 64) -> dict[str, Any]:
    """Magnitude/phase response by dividing output and input spectra of the log sweep in log-spaced bands."""
    n = min(len(x), len(y))
    if n < 4096:
        return {"bands": []}
    X = np.fft.rfft(x[:n].astype(np.float64) * np.hanning(n))
    Y = np.fft.rfft(y[:n].astype(np.float64) * np.hanning(n))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    edges = np.geomspace(20.0, min(20000.0, sr / 2 * 0.98), bands + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=False):
        m = (freqs >= lo) & (freqs < hi) & (np.abs(X) > 1e-9)
        if not np.any(m):
            continue
        H = Y[m] / X[m]
        out.append({"hz": float(np.sqrt(lo * hi)), "mag_db": float(20 * np.log10(np.mean(np.abs(H)) + 1e-12)), "phase_deg": float(np.degrees(np.angle(np.mean(H))))})
    return {"bands": out}


def aliasing(y: np.ndarray, sr: float) -> dict[str, Any]:
    """Two-tone 19/20 kHz: energy outside the tones and their expected IMD products vs in-band."""
    n = len(y)
    if n < 4096:
        return {"aliasing_ratio_db": None}
    spec = np.abs(np.fft.rfft(y.astype(np.float64) * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    tone = np.zeros_like(spec, dtype=bool)
    for f in (19000.0, 20000.0, 1000.0, 18000.0, 21000.0, 17000.0, 22000.0):
        tone |= np.abs(freqs - f) < 60
    total = float(np.sum(spec ** 2))
    tones = float(np.sum(spec[tone] ** 2))
    other = total - tones
    return {"aliasing_ratio_db": float(10 * np.log10((other + 1e-18) / (tones + 1e-18))), "tone_energy": tones, "other_energy": other}


def transfer_curve(x: np.ndarray, y: np.ndarray, latency: int, points: int = 1024, lead_in: int | None = None) -> list[list[float]]:
    """(x, y) pairs from the measured half of the ramp probe (after the settle lead-in), latency-compensated."""
    from ab_engine.behavior.probes import ramp_lead_in  # noqa: PLC0415

    lat = max(0, latency)
    lead = ramp_lead_in(len(x)) if lead_in is None else lead_in
    n = min(len(x), len(y) - lat)
    if n <= lead:
        return []
    step = max(1, (n - lead) // points)
    return [[float(x[i]), float(y[i + lat])] for i in range(lead, n, step)]
