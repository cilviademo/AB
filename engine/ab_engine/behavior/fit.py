"""Nonlinear transfer-curve fitting (SPEC §11): candidate families fitted to the (x, y) transfer
curve measured from the amplitude ramp; the model is chosen by residual, never by name.

Families: hard clip, tanh, atan, cubic soft clip, polynomial (odd, degree 3/5/7/9), piecewise
polynomial (3 segments), rational saturation x/(1+|x|^p)^(1/p), LUT (interpolated, used as the
ceiling: it always fits, so it only wins when nothing parametric comes within its residual).
Each fit reports RMSE, max error, correlation and the parameters; the winner is the lowest RMSE
parametric model within 1.25× of the LUT floor, else LUT (meaning: shape captured, family unknown).
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np


def _stats(y: np.ndarray, yh: np.ndarray) -> dict[str, float]:
    err = yh - y
    corr = float(np.corrcoef(y, yh)[0, 1]) if np.std(y) > 0 and np.std(yh) > 0 else 0.0
    return {"rmse": float(np.sqrt(np.mean(err ** 2))), "max_error": float(np.max(np.abs(err))), "correlation": corr}


def _best_gain(y: np.ndarray, base: np.ndarray) -> float:
    """Closed-form least-squares gain for y ≈ gain · base."""
    den = float(np.dot(base, base))
    return float(np.dot(base, y) / den) if den > 0 else 1.0


def _rmse_at(x: np.ndarray, y: np.ndarray, f, d: float) -> tuple[float, float]:
    base = f(x, d, 1.0)
    g = _best_gain(y, base)
    return float(np.sqrt(np.mean((g * base - y) ** 2))), g


def _grid(x: np.ndarray, y: np.ndarray, f: Callable[[np.ndarray, float, float], np.ndarray], gains: np.ndarray, drives: np.ndarray) -> tuple[dict[str, float], float]:
    """Scan drive; the gain is solved exactly for each drive (the 'gains' grid is kept for API symmetry)."""
    best, bp = None, (1.0, 1.0)
    for d in drives:
        r, g = _rmse_at(x, y, f, float(d))
        if best is None or r < best:
            best, bp = r, (g, float(d))
    return {"gain": bp[0], "drive": bp[1]}, best  # type: ignore[return-value]


def _refine(x: np.ndarray, y: np.ndarray, f, p: dict[str, float], iters: int = 60) -> dict[str, float]:
    """Golden-section search on drive around the grid optimum; gain solved in closed form."""
    d = p["drive"]
    lo, hi = max(1e-3, d / 1.6), d * 1.6
    phi = (np.sqrt(5) - 1) / 2
    a, b = hi - phi * (hi - lo), lo + phi * (hi - lo)
    fa, fb = _rmse_at(x, y, f, a)[0], _rmse_at(x, y, f, b)[0]
    for _ in range(iters):
        if fa < fb:
            hi, b, fb = b, a, fa
            a = hi - phi * (hi - lo); fa = _rmse_at(x, y, f, a)[0]
        else:
            lo, a, fa = a, b, fb
            b = lo + phi * (hi - lo); fb = _rmse_at(x, y, f, b)[0]
    d = a if fa < fb else b
    return {"gain": _rmse_at(x, y, f, d)[1], "drive": float(d)}


FAMILIES: dict[str, Callable[[np.ndarray, float, float], np.ndarray]] = {
    "hard_clip": lambda x, d, _: np.clip(x * d, -1.0, 1.0),
    "tanh": lambda x, d, _: np.tanh(x * d),
    "tanh_normalized": lambda x, d, _: np.tanh(x * d) / np.tanh(d),
    "atan": lambda x, d, _: (2.0 / np.pi) * np.arctan(x * d),
    "cubic": lambda x, d, _: np.where(np.abs(x * d) >= 1.0, np.sign(x * d) * (2.0 / 3.0), x * d - (x * d) ** 3 / 3.0),
    "rational": lambda x, d, _: (x * d) / (1.0 + np.abs(x * d)),
    "rational_p2": lambda x, d, _: (x * d) / np.sqrt(1.0 + (x * d) ** 2),
}


def fit_all(curve: list[list[float]]) -> dict[str, Any]:
    pts = np.asarray(curve, dtype=np.float64)
    if pts.ndim != 2 or len(pts) < 16:
        return {"fits": [], "chosen": None, "note": "not enough transfer-curve points"}
    x, y = pts[:, 0], pts[:, 1]
    order = np.argsort(x)
    x, y = x[order], y[order]
    fits: list[dict[str, Any]] = []
    gains = np.geomspace(0.05, 20.0, 40)
    drives = np.geomspace(0.05, 40.0, 40)
    for name, f in FAMILIES.items():
        p, _ = _grid(x, y, f, gains, drives)
        p = _refine(x, y, f, p)
        yh = p["gain"] * f(x, p["drive"], 1.0)
        fits.append({"family": name, "params": p, **_stats(y, yh)})
    for deg in (3, 5, 7, 9):
        # odd polynomial through the origin
        A = np.stack([x ** k for k in range(1, deg + 1, 2)], axis=1)
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        yh = A @ coef
        fits.append({"family": f"poly_odd_{deg}", "params": {"coefficients": [float(c) for c in coef]}, **_stats(y, yh)})
    # piecewise (3 segments split at the 33/66 percentiles of |x|)
    edges = np.quantile(np.abs(x), [0.33, 0.66])
    yh = np.empty_like(y)
    segs = []
    for lo, hi in ((0, edges[0]), (edges[0], edges[1]), (edges[1], np.inf)):
        m = (np.abs(x) >= lo) & (np.abs(x) < hi)
        if np.sum(m) >= 4:
            c = np.polyfit(x[m], y[m], 3)
            yh[m] = np.polyval(c, x[m])
            segs.append({"abs_x_from": float(lo), "abs_x_to": float(hi) if np.isfinite(hi) else None, "coefficients": [float(v) for v in c]})
        else:
            yh[m] = y[m]
    fits.append({"family": "piecewise_cubic_3", "params": {"segments": segs}, **_stats(y, yh)})
    # LUT floor: 65-point interpolation
    lut_x = np.linspace(x.min(), x.max(), 65)
    lut_y = np.interp(lut_x, x, y)
    yh = np.interp(x, lut_x, lut_y)
    lut = {"family": "lut_65", "params": {"x": [float(v) for v in lut_x], "y": [float(v) for v in lut_y]}, **_stats(y, yh)}
    fits.append(lut)
    parametric = sorted((f for f in fits if f["family"] != "lut_65"), key=lambda f: f["rmse"])
    chosen = parametric[0] if parametric and parametric[0]["rmse"] <= max(1.25 * lut["rmse"], 1e-6) else lut
    return {"fits": sorted(fits, key=lambda f: f["rmse"]), "chosen": chosen["family"], "chosen_rmse": chosen["rmse"], "lut_floor_rmse": lut["rmse"],
            "basis": "lowest residual; LUT wins only when no parametric family comes within 1.25× of the LUT floor (shape captured, family unknown)"}


def classify(rmse: float, max_err: float, spectrum_db: float | None, latency_delta: int, *, peak: float = 1.0) -> str:
    """Differential classification (SPEC §1, EXECUTE 4.3 thresholds)."""
    if max_err == 0.0:
        return "BIT_EXACT"
    if rmse <= 1e-6 * max(1.0, peak) and max_err <= 1e-5 * max(1.0, peak):
        return "NUMERICALLY_EQUIVALENT"
    if rmse <= 1e-4 and (spectrum_db is None or spectrum_db <= 0.1) and latency_delta == 0:
        return "BEHAVIORALLY_EQUIVALENT"
    if rmse <= 1e-2 and (spectrum_db is None or spectrum_db <= 1.0):
        return "PERCEPTUALLY_CLOSE"
    return "FAILED"
