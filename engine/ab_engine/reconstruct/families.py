"""C++ code generation for the transfer-curve families fitted in ``ab_engine.behavior.fit``.

Every family here mirrors the numpy definition in ``fit.FAMILIES`` (or the polynomial / piecewise /
LUT fits) exactly, so a module generated from a fit reproduces the fitted curve to float precision.
The functions return the *body* of ``static float shape (float x)`` for the family's default
parameters; gain/drive modulation is applied by the caller around it (``y = g · shape (d · x)``).
Nothing here names a plugin, a vendor or a reference-corpus file (CLAUDE.md: clean room).
"""

from __future__ import annotations

from typing import Any

PARAMETRIC = {"hard_clip", "tanh", "tanh_normalized", "atan", "cubic", "rational", "rational_p2"}


def _f(v: float) -> str:
    s = repr(float(v))
    if "e" in s or "E" in s:
        return f"{float(v):.9g}f"
    if "." not in s:
        s += ".0"
    return s + "f"


def shape_body(family: str, params: dict[str, Any]) -> tuple[str, str]:
    """Return (helper declarations, expression in ``u``) where ``u`` is the (already drive-scaled)
    input for parametric families, or the raw input ``x`` for the fixed-shape families."""
    if family == "hard_clip":
        return "", "juce::jlimit (-1.0f, 1.0f, u)"
    if family == "tanh":
        return "", "std::tanh (u)"
    if family == "tanh_normalized":
        return "", "std::tanh (u) / std::tanh (drive)"
    if family == "atan":
        return "", "(2.0f / juce::MathConstants<float>::pi) * std::atan (u)"
    if family == "cubic":
        return "", "(std::abs (u) >= 1.0f ? (u < 0.0f ? -2.0f / 3.0f : 2.0f / 3.0f) : u - (u * u * u) / 3.0f)"
    if family == "rational":
        return "", "u / (1.0f + std::abs (u))"
    if family == "rational_p2":
        return "", "u / std::sqrt (1.0f + u * u)"
    if family.startswith("poly_odd_"):
        coef = params.get("coefficients", [])
        terms = " + ".join(f"{_f(c)} * {'x' if k == 0 else f'std::pow (x, {2 * k + 1})'}" for k, c in enumerate(coef)) or "x"
        return "", f"({terms})"
    if family == "piecewise_cubic_3":
        segs = params.get("segments", [])
        decl = "    static float seg (float x, const float* c) noexcept { return ((c[0] * x + c[1]) * x + c[2]) * x + c[3]; }\n"
        lines = []
        for i, s in enumerate(segs):
            c = ", ".join(_f(v) for v in s["coefficients"])
            hi = s.get("abs_x_to")
            cond = f"std::abs (x) < {_f(hi)}" if hi is not None else "true"
            lines.append(f"        {{ static const float c{i}[4] = {{ {c} }}; if ({cond}) return seg (x, c{i}); }}")
        decl += "    static float piecewise (float x) noexcept\n    {\n" + "\n".join(lines) + "\n        return x;\n    }\n"
        return decl, "piecewise (x)"
    if family == "lut_65":
        xs = ", ".join(_f(v) for v in params["x"])
        ys = ", ".join(_f(v) for v in params["y"])
        decl = (f"    static constexpr int lutSize = {len(params['x'])};\n"
                f"    static const float* lutX() noexcept {{ static const float v[] = {{ {xs} }}; return v; }}\n"
                f"    static const float* lutY() noexcept {{ static const float v[] = {{ {ys} }}; return v; }}\n"
                "    static float lut (float x) noexcept\n    {\n"
                "        const float* X = lutX(); const float* Y = lutY();\n"
                "        if (x <= X[0]) return Y[0];\n        if (x >= X[lutSize - 1]) return Y[lutSize - 1];\n"
                "        int i = 1; while (i < lutSize - 1 && X[i] < x) ++i;\n"
                "        const float t = (x - X[i - 1]) / (X[i] - X[i - 1]);\n        return Y[i - 1] + t * (Y[i] - Y[i - 1]);\n    }\n")
        return decl, "lut (x)"
    raise ValueError(f"unknown fit family {family!r}")


def describe(family: str) -> str:
    return {
        "hard_clip": "hard clip  y = g · clamp(d·x, −1, 1)",
        "tanh": "tanh  y = g · tanh(d·x)",
        "tanh_normalized": "normalised tanh  y = g · tanh(d·x) / tanh(d)",
        "atan": "arctangent  y = g · (2/π) · atan(d·x)",
        "cubic": "cubic soft clip  y = g · (u − u³/3), |u| ≥ 1 → ±2/3",
        "rational": "rational  y = g · u / (1 + |u|)",
        "rational_p2": "rational p=2  y = g · u / √(1 + u²)",
        "piecewise_cubic_3": "piecewise cubic (3 segments by |x|)",
        "lut_65": "65-point look-up table (shape captured, family unknown)",
    }.get(family, "odd polynomial" if family.startswith("poly_odd_") else family)


__all__ = ["shape_body", "describe", "PARAMETRIC"]
