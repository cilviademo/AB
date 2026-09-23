"""Deterministic probe signals (SPEC §11) — bit-for-bit the same as native/vst3host/src/probes.h
and reference/…/ProbeSignals.h, in float32 arithmetic, so the Python side can regenerate the
exact input the host fed the plugin without keeping input WAVs around."""

from __future__ import annotations

import numpy as np

PROBES = ("silence", "impulse", "dc", "ramp", "sine1k", "sine_amp_sweep", "log_sweep", "white", "pink", "two_tone")
RATES = (44100.0, 48000.0, 96000.0)
BLOCKS = (32, 64, 128, 256, 512, 1024)


def _xorshift(n: int, seed: int = 0x12345678) -> np.ndarray:
    out = np.empty(n, dtype=np.float32)
    s = np.uint32(seed if seed else 1)
    for i in range(n):
        s ^= np.uint32((int(s) << 13) & 0xFFFFFFFF)
        s ^= np.uint32(int(s) >> 17)
        s ^= np.uint32((int(s) << 5) & 0xFFFFFFFF)
        out[i] = (np.float32(int(s)) / np.float32(0xFFFFFFFF)) * np.float32(2.0) - np.float32(1.0)
    return out


def ramp_lead_in(n: int) -> int:
    """Samples of settle lead-in at the head of the ramp probe (mirrors abprobes::rampLeadIn)."""
    return n // 2


def make(name: str, n: int, sr: float) -> np.ndarray:
    i = np.arange(n, dtype=np.float64)
    if name == "silence":
        return np.zeros(n, dtype=np.float32)
    if name == "impulse":
        x = np.zeros(n, dtype=np.float32)
        if n:
            x[0] = 1.0
        return x
    if name == "dc":
        return np.full(n, 0.5, dtype=np.float32)
    if name == "ramp":
        # settle lead-in (0 → lo over the first half; DECISIONS D-017) then the measured lo → hi sweep
        lo, hi = np.float32(-4.0), np.float32(4.0)
        lead = ramp_lead_in(n)
        main = n - lead
        x = np.empty(n, dtype=np.float32)
        x[:lead] = (lo * (np.arange(lead, dtype=np.float32) / np.float32(lead - 1))) if lead > 1 else np.float32(0.0)
        x[lead:] = (lo + (hi - lo) * (np.arange(main, dtype=np.float32) / np.float32(main - 1))) if main > 1 else lo
        return x
    if name == "sine1k":
        return (np.float32(0.5) * np.sin(2 * np.pi * 1000.0 * i / sr).astype(np.float32)).astype(np.float32)
    if name == "sine_amp_sweep":
        t = i / (n - 1) if n > 1 else np.zeros(n)
        amp = (0.001 * np.power(2.0 / 0.001, t)).astype(np.float32)
        return (amp * np.sin(2 * np.pi * 1000.0 * i / sr).astype(np.float32)).astype(np.float32)
    if name == "log_sweep":
        f0, f1 = 20.0, 20000.0
        T = n / sr
        K = T / np.log(f1 / f0)
        L = 2 * np.pi * f0 * K
        t = i / sr
        return (np.float32(0.5) * np.sin(L * (np.exp(t / K) - 1)).astype(np.float32)).astype(np.float32)
    if name == "white":
        return (np.float32(0.25) * _xorshift(n)).astype(np.float32)
    if name == "pink":
        w = _xorshift(n)
        out = np.empty(n, dtype=np.float32)
        b0 = b1 = b2 = np.float32(0)
        for k in range(n):
            x = w[k]
            b0 = np.float32(0.99765) * b0 + x * np.float32(0.0990460)
            b1 = np.float32(0.96300) * b1 + x * np.float32(0.2965164)
            b2 = np.float32(0.57000) * b2 + x * np.float32(1.0526913)
            out[k] = np.float32(0.25) * np.float32(0.25) * (b0 + b1 + b2 + x * np.float32(0.1848))
        return out
    if name == "two_tone":
        return (np.float32(0.25) * (np.sin(2 * np.pi * 19000.0 * i / sr) + np.sin(2 * np.pi * 20000.0 * i / sr)).astype(np.float32)).astype(np.float32)
    raise ValueError(f"unknown probe {name}")
