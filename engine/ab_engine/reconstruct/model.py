"""Reconstruction model: what the evidence supports generating, and at which status (SPEC §10).

Everything the generator writes is derived here from files in the project folder, each item
carrying the evidence status it earned:

* parameters   — VST3_EXPORTED_PARAMETER rows (VERIFIED_RUNTIME) joined with the state map;
                 ranges from the 5-point plain/display samples; JUCE paramID hash check.
* state        — root tag + state-only attributes from the runtime state baseline.
* modules      — the waveshaper model fitted from the amplitude-ramp transfer curves:
                 family chosen by residual at the verified default, per-parameter modulation laws
                 (dB gain law when the samples prove it, else a measured table), bypass detection.
                 Status BEHAVIOR_MATCHED only at measured points; separable combination INFERRED.
* scaffolds    — plugin-owned classes with DSP roles that no validated module covers.
* identity     — FIDELITY only when the runtime identity is VERIFIED_RUNTIME (else SURROGATE).

Thresholds: a module is eligible for ``Source/Active`` only when its default-position fit is at
least BEHAVIORALLY_EQUIVALENT (RMSE ≤ 1e-4), the gate SPEC §10 sets for scaffold → Active.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from ab_engine.behavior import fit as fit_mod
from ab_engine.decompile import roles as roles_mod
from ab_engine.reconstruct.families import PARAMETRIC

ACTIVE_RMSE = 1e-4  # BEHAVIORALLY_EQUIVALENT threshold (fit.classify)


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")).get("data") if p.is_file() else None


def juce_param_id(key: str) -> int:
    """juce::String::hashCode() & 0x7fffffff — the VST3 ParamID JUCE derives from a paramID string."""
    h = 0
    for ch in key:
        h = (31 * h + ord(ch)) & 0xFFFFFFFF
    if h >= 2 ** 31:
        h -= 2 ** 32
    return h & 0x7FFFFFFF


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    m = re.match(r"\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", str(s))
    return float(m.group(1)) if m else None


def _skew_from_samples(lo: float, hi: float, samples: list[tuple[float, float]]) -> tuple[float, str]:
    """NormalisableRange skew from (normalized, plain) samples: plain = lo + (hi−lo)·n^(1/skew)."""
    span = hi - lo
    if span == 0:
        return 1.0, "degenerate range"
    mids = [(n, p) for n, p in samples if 0.0 < n < 1.0 and lo < p < hi]
    if not mids:
        return 1.0, "linear assumed (no interior samples)"
    ests = []
    for n, p in mids:
        frac = (p - lo) / span
        if 0 < frac < 1:
            ests.append(math.log(n) / math.log(frac))
    if not ests:
        return 1.0, "linear assumed"
    skew = float(np.median(ests))
    if abs(skew - 1.0) < 0.02:
        skew = 1.0
    # verify the law against every interior sample (within 1 % of span)
    worst = max(abs((lo + span * n ** (1.0 / skew)) - p) / span for n, p in mids)
    return skew, ("VERIFIED_RUNTIME (5-point sample fits skew law within 1 %)" if worst <= 0.01 else f"INFERRED (skew law misfits by {worst * 100:.1f} % of span; JUCE symmetric/centre skew or custom mapping possible)")


def parameters(project: Path) -> list[dict[str, Any]]:
    arch = _load(project / "03_architecture" / "parameters.json") or {}
    tiers = arch.get("tiers", []) if isinstance(arch, dict) else []
    runtime = {int(p["param_id"]): p for p in (_load(project / "01_evidence" / "vst3" / "runtime_parameters.json") or [])}
    key_of = {int(t["param_id"]): t for t in tiers if t.get("param_id") is not None}
    out: list[dict[str, Any]] = []
    for pid, p in sorted(runtime.items(), key=lambda kv: kv[1].get("index", 0)):
        t = key_of.get(pid, {})
        key = t.get("key")
        if not key:
            if p.get("is_bypass"):
                out.append({"param_id": pid, "title": p.get("title"), "kind": "wrapper_bypass", "generate": False,
                            "evidence": "RUNTIME_ONLY", "note": "JUCE VST3 wrapper bypass parameter (DECISIONS D-015); the rebuild's wrapper adds it again"})
                continue
            key = f"param_{pid}"
            id_status = "GENERATED (no state key correlated; ParameterID hash cannot reproduce this id)"
        else:
            id_status = "VERIFIED_RUNTIME (juce::ParameterID hash reproduces the VST3 id)" if juce_param_id(key) == pid else f"INFERRED (state key {key!r}; hash {juce_param_id(key)} ≠ runtime id {pid}: legacy/custom id scheme)"
        samples = [(float(s["normalized"]), s.get("string")) for s in p.get("samples", [])]
        rep = t.get("value_representation", "UNKNOWN")
        step = int(p.get("step_count") or 0)
        row: dict[str, Any] = {"param_id": pid, "key": key, "title": p.get("title") or key, "units": p.get("units") or "", "id_status": id_status,
                               "default_normalized": float(p.get("default_normalized") or 0.0), "evidence": "VERIFIED_RUNTIME", "generate": True,
                               "is_bypass": bool(p.get("is_bypass")), "can_automate": bool(p.get("can_automate", True)), "representation": rep}
        if step == 1 or rep == "BOOLEAN":
            row.update({"kind": "bool", "default": row["default_normalized"] >= 0.5})
        elif step >= 2 or rep == "ENUM" or p.get("is_list"):
            choices = []
            for k in range(step + 1):
                n = k / step
                s = min(samples, key=lambda sv: abs(sv[0] - n)) if samples else (n, None)
                exact = abs(s[0] - n) < 1e-6
                choices.append({"name": (s[1] if exact and s[1] else f"Choice {k}"), "status": "VERIFIED_RUNTIME" if exact and s[1] else "GENERATED (display string not sampled at this step)"})
            row.update({"kind": "choice", "choices": choices, "default": int(round(row["default_normalized"] * step)), "step_count": step})
        else:
            plain = [(n, _num(s)) for n, s in samples if _num(s) is not None]
            lo = next((v for n, v in plain if n == 0.0), None)
            hi = next((v for n, v in plain if n == 1.0), None)
            if lo is None or hi is None:
                row.update({"kind": "float", "min": 0.0, "max": 1.0, "skew": 1.0, "range_status": "GENERATED (display strings not numeric; normalized 0..1 kept)", "default": row["default_normalized"]})
            else:
                skew, basis = _skew_from_samples(lo, hi, plain)
                d = lo + (hi - lo) * (row["default_normalized"] ** (1.0 / skew))
                row.update({"kind": "float", "min": lo, "max": hi, "skew": skew, "range_status": basis, "default": d,
                            "plain_samples": plain})
        out.append(row)
    return out


def state_model(project: Path, params: list[dict[str, Any]]) -> dict[str, Any]:
    base = _load(project / "01_evidence" / "vst3" / "state_baseline.json") or {}
    text = base.get("component_state_text") or ""
    m = re.search(r"<([A-Za-z_][\w.-]*)((?:\s+[\w.:-]+=\"[^\"]*\")*)\s*>", text)
    root = m.group(1) if m else "PARAMETERS"
    attrs = dict(re.findall(r"([\w.:-]+)=\"([^\"]*)\"", m.group(2))) if m else {}
    keys = {p.get("key") for p in params}
    extra = {k: v for k, v in attrs.items() if k not in keys}
    return {"root_tag": root, "root_status": "VERIFIED_RUNTIME (component state XML)" if m else "GENERATED (default APVTS tag; no runtime state)",
            "state_only": [{"key": k, "observed": v, "tier": "STATE_SCHEMA_FIELD", "representation": "UNKNOWN", "evidence": "VERIFIED_RUNTIME (present in serialized state; never exported)"} for k, v in extra.items()],
            "format": "juce::copyXmlToBinary (APVTS ValueTree XML)" if text.lstrip().startswith("<?xml") or text.startswith("<") else "UNKNOWN"}


# ---------------------------------------------------------------------------------------------
# waveshaper model from ramp transfer curves

def _curve(p: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    d = _load(p)
    if not d or not d.get("curve"):
        return None
    pts = np.asarray(d["curve"], dtype=np.float64)
    o = np.argsort(pts[:, 0])
    return pts[o, 0], pts[o, 1], d


def _fit_gd(x: np.ndarray, y: np.ndarray, f) -> dict[str, float]:
    p, _ = fit_mod._grid(x, y, f, np.geomspace(0.05, 20.0, 40), np.geomspace(0.05, 40.0, 40))
    p = fit_mod._refine(x, y, f, p)
    yh = p["gain"] * f(x, p["drive"], 1.0)
    return {**p, **fit_mod._stats(y, yh)}


def _identity_rmse(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - x) ** 2)))


def _norm_factor(family: str, drive: float) -> float:
    """Intrinsic normalisation of a family at a given drive (1.0 for families without one)."""
    return float(np.tanh(drive)) if family == "tanh_normalized" else 1.0


def _linear(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    a, b = np.polyfit(x, y, 1)
    return {"slope": float(a), "offset": float(b), "rmse": float(np.sqrt(np.mean((a * x + b - y) ** 2)))}


#: tie-break among fits with (numerically) equal residual: simplest, least-coupled family first
PREFERENCE = ("tanh", "hard_clip", "atan", "rational", "rational_p2", "cubic", "tanh_normalized", "poly_odd_3", "poly_odd_5", "poly_odd_7", "poly_odd_9", "piecewise_cubic_3", "lut_65")


def _knob(family: str, d0: float, gr: float, dr: float) -> tuple[str, float, dict[str, float]]:
    """Which knob a measured (gain_ratio, drive_ratio) pair moves: post gain, pre gain or drive.

    y = post · F(drive · pre · x) / norm(drive). A pre-gain change k leaves norm alone, so the fitted
    (gain, drive) become (g0·norm(d0·k)/norm(d0), d0·k); a drive change r gives (g0, d0·r); a post
    change gives (g·r, d0). Returns (best knob, factor, per-knob relative error) — the caller picks
    one knob per parameter that explains every sampled position."""
    if abs(dr - 1) <= 5e-3:
        return ("post", gr, {"post": 0.0}) if abs(gr - 1) > 5e-3 else ("none", 1.0, {"none": 0.0})
    pre_gr = _norm_factor(family, d0 * dr) / _norm_factor(family, d0)
    errs = {"pre": abs(gr / pre_gr - 1), "drive": abs(gr - 1)}
    best = min(errs, key=errs.get)
    return (best if errs[best] <= 0.02 else "table"), dr, errs


LAW_SCORE = {"db": 3, "proportional": 3, "passthrough": 3, "passthrough_off": 3, "none": 2, "discrete": 2, "table": 0, "unmodeled": -1}


def _modulation(family: str, chosen: dict[str, Any], x0: np.ndarray, y0: np.ndarray, tc: Path, params: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float, float]:
    if family in PARAMETRIC:
        shape = fit_mod.FAMILIES[family]
        g0, d0 = float(chosen["params"]["gain"]), float(chosen["params"]["drive"])
    else:
        xr = float(np.max(np.abs(x0)))
        shape = lambda x, d, _: np.interp(np.clip(x * d, -xr, xr), x0, y0)  # noqa: E731
        g0, d0 = 1.0, 1.0
    modulation: list[dict[str, Any]] = []
    for p in params:
        if not p.get("generate") or p.get("kind") == "wrapper_bypass":
            continue
        pts = []
        for f in sorted(tc.glob(f"ramp_{p['title'].replace(' ', '_')}_*.json")):
            c = _curve(f)
            if c is None:
                continue
            x, y, d = c
            pos = float(d["probe"].get("sweep", {}).get("normalized", f.stem.rsplit("_", 1)[-1]))
            gd = _fit_gd(x, y, shape)
            gr, dr = gd["gain"] / g0, gd["drive"] / d0
            knob, factor, errs = _knob(family, d0, gr, dr)
            lin = _linear(x, y)
            rms_y = float(np.sqrt(np.mean(y ** 2))) or 1.0
            pts.append({"normalized": pos, "gain_ratio": gr, "drive_ratio": dr, "knob": knob, "factor": factor, "rmse": gd["rmse"], "rmse_rel": gd["rmse"] / rms_y,
                        "max_error": gd["max_error"], "linear": lin, "knob_errors": errs, "file": f"05_reference_behavior/transfer_curves/{f.name}"})
        if not pts:
            continue
        pts.sort(key=lambda r: r["normalized"])
        kind = p.get("kind")
        # discrete parameters: one point per legal value (bool: off/on; choice: index k ↔ k/step)
        if kind == "bool":
            pts = [min(pts, key=lambda r: abs(r["normalized"] - v)) for v in (0.0, 1.0)]
            for r, v in zip(pts, (0, 1)):
                r["value"] = v
        elif kind == "choice":
            step = int(p.get("step_count", 1))
            sel = []
            for k in range(step + 1):
                r = dict(min(pts, key=lambda r: abs(r["normalized"] - k / step)))
                r["value"] = k
                r["sampled_exactly"] = abs(r["normalized"] - k / step) < 1e-6
                sel.append(r)
            pts = sel
        for r in pts:
            r["passthrough"] = abs(r["linear"]["slope"] - 1) <= 1e-3 and r["linear"]["rmse"] <= ACTIVE_RMSE
            r["is_linear"] = r["linear"]["rmse"] <= max(ACTIVE_RMSE, 0.5 * r["rmse"]) and r["linear"]["rmse"] < r["rmse"]
            r["best_rmse"] = min(r["rmse"], r["linear"]["rmse"]) if r["is_linear"] else r["rmse"]
        # one knob per parameter: the first of (pre, drive, post) compatible with every non-linear, non-null point
        moving = [r for r in pts if not r.get("is_linear") and r["knob"] != "none"]
        for cand in ("pre", "drive", "post"):
            if moving and all(r["knob_errors"].get(cand, 1.0) <= 0.02 for r in moving):
                for r in moving:
                    r["knob"] = cand
                break
        knobs = {r["knob"] for r in pts if not r.get("is_linear")}
        worst = max(r["best_rmse"] / max(r["gain_ratio"], 1.0) for r in pts)  # error referred to the default output level
        law, basis, knob = "table", "measured (pre, drive, post) factors at each sampled position; linear interpolation between positions is INFERRED", "table"
        if worst > 1e-2:
            law, basis = "unmodeled", f"the amplitude-ramp response is not a static transfer curve at some positions (worst RMSE {worst:.2e}); time-dependent (filter/modulation) effect — not modelled by the shaper"
        elif all(r["knob"] == "none" and not r["is_linear"] for r in pts):
            law, basis = "none", "no measurable effect on the amplitude-ramp transfer curve (all ratios within 0.5 %)"
        elif kind == "bool" and pts[1]["passthrough"] and not pts[0]["passthrough"]:
            law, basis = "passthrough", f"output equals input when on (slope {pts[1]['linear']['slope']:.5f}, RMSE {pts[1]['linear']['rmse']:.1e}; offset {pts[1]['linear']['offset']:.2e} = ramp slope × latency mismatch)"
        elif kind == "bool" and pts[0]["passthrough"] and not pts[1]["passthrough"]:
            law, basis = "passthrough_off", "output equals input when off"
        elif kind in ("bool", "choice"):
            law, basis = "discrete", "one measured setting per legal value: linear slope where the response is linear, else a (pre, drive, post) factor"
        elif kind == "float" and knobs <= {"pre", "post", "drive", "none"} and len(knobs - {"none"}) == 1:
            knob = next(iter(knobs - {"none"}))
            plain = dict(p.get("plain_samples") or [])
            dflt = float(p["default"])
            if p.get("units", "").lower() == "db" and plain:
                exp = {r["normalized"]: 10 ** ((plain.get(r["normalized"], dflt) - dflt) / 20.0) for r in pts}
                err = max(abs(r["factor"] / exp[r["normalized"]] - 1) for r in pts)
                if err <= 0.02:
                    law, basis = "db", f"{knob} factor = 10^((dB − default dB)/20) at every sampled position (max deviation {err * 100:.2f} %)"
            if law == "table" and plain and dflt != 0:
                exp = {r["normalized"]: plain.get(r["normalized"], dflt) / dflt for r in pts}
                err = max(abs(r["factor"] / exp[r["normalized"]] - 1) for r in pts)
                if err <= 0.02:
                    law, basis = "proportional", f"{knob} factor = plain value / default plain value at every sampled position (max deviation {err * 100:.2f} %)"
        if law == "table" and kind == "float":
            knob = "table"
        modulation.append({"key": p["key"], "param_id": p["param_id"], "title": p["title"], "kind": kind, "law": law, "knob": knob, "basis": basis, "points": pts,
                           "status": "BEHAVIOR_MATCHED" if worst <= ACTIVE_RMSE else ("PERCEPTUALLY_CLOSE" if worst <= 1e-2 else "INFERRED"), "worst_rmse_ref": worst})
    return modulation, g0, d0


def waveshaper_model(project: Path, params: list[dict[str, Any]]) -> dict[str, Any] | None:
    tc = project / "05_reference_behavior" / "transfer_curves"
    base = _curve(tc / "ramp_48k_256.json")
    if base is None:
        return None
    x0, y0, doc = base
    fits = fit_mod.fit_all([[float(a), float(b)] for a, b in zip(x0, y0)])
    best = fits["chosen_rmse"]
    tied = [f for f in fits["fits"] if f["family"] != "lut_65" and f["rmse"] <= best * 1.001 + 1e-12]  # within 0.1 % of the best residual or [next(f for f in fits["fits"] if f["family"] == fits["chosen"])]
    scored = []
    for cand in sorted(tied, key=lambda f: PREFERENCE.index(f["family"]) if f["family"] in PREFERENCE else 99):
        mod, g0, d0 = _modulation(cand["family"], cand, x0, y0, tc, params)
        scored.append((sum(LAW_SCORE.get(m["law"], 0) for m in mod), cand, mod, g0, d0))
    score, chosen, modulation, g0, d0 = max(scored, key=lambda t: t[0])  # first (simplest) wins ties: max keeps the first maximum
    family = chosen["family"]
    rmse0 = float(chosen["rmse"])
    family_note = f"{len(tied)} families tie at the residual; {family} chosen because its parameter laws are simplest (score {score})" if len(tied) > 1 else "lowest residual"
    return {"name": "Waveshaper", "role": "WAVESHAPER", "family": family, "family_basis": fits.get("basis") + "; " + family_note, "params": chosen["params"],
            "pre": 1.0, "drive": d0, "post": g0, "rmse": rmse0, "max_error": float(chosen["max_error"]), "correlation": float(chosen["correlation"]),
            "lut_floor_rmse": fits.get("lut_floor_rmse"), "status": "BEHAVIOR_MATCHED" if rmse0 <= 1e-2 else "INFERRED",
            "classification_at_default": fit_mod.classify(rmse0, float(chosen["max_error"]), None, 0),
            "active": rmse0 <= ACTIVE_RMSE, "modulation": modulation, "curve_points": int(len(x0)), "x_range": [float(x0.min()), float(x0.max())],
            "latency_used": doc.get("latency_used"), "reference": "05_reference_behavior/transfer_curves/ramp_48k_256.json",
            "candidates": [{"family": f["family"], "rmse": f["rmse"]} for f in fits["fits"][:6]]}


def owned_classes(project: Path) -> list[dict[str, Any]]:
    rows = _load(project / "01_evidence" / "rtti" / "classes.json") or []
    verified: dict[str, dict[str, Any]] = {}
    p3 = project / "03_architecture" / "classes.json"
    if p3.is_file():
        doc = json.loads(p3.read_text(encoding="utf-8"))
        if doc.get("schema") == "artifactbench.classes_verified":  # written by DECOMPILATION_COMPLETE; the v2 static file has another shape
            verified = {c.get("recovered_name"): c for c in doc.get("data", [])}
    out = []
    for c in rows:
        c = {**c, **{k: v for k, v in verified.get(c.get("recovered_name"), {}).items() if k in ("name_status", "structure_status", "vtables", "methods", "bases", "base_status")}}
        if c.get("kind") != "PLUGIN_OWNED_CANDIDATE":
            continue
        role = c.get("role") or "UNKNOWN"
        role = roles_mod.STATIC_TO_FINAL.get(role, role)
        out.append({"name": c.get("recovered_name"), "safe": c.get("safe_name") or re.sub(r"[^A-Za-z0-9_]", "_", str(c.get("recovered_name"))), "role": role,
                    "role_status": c.get("role_status", "UNKNOWN"), "name_status": c.get("name_status"), "structure_status": c.get("structure_status", "UNKNOWN"),
                    "vtables": c.get("vtables", []), "methods": c.get("methods", []), "bases": c.get("bases", []) or ([c["inferred_base"]] if c.get("inferred_base") else [])})
    return out


def dsp_functions(project: Path) -> list[dict[str, Any]]:
    return _load(project / "01_evidence" / "decompiler" / "dsp_candidates.json") or []


def identity(project: Path) -> dict[str, Any]:
    ident = _load(project / "03_architecture" / "identity.json") or {}
    verified = ident.get("evidence") == "VERIFIED_RUNTIME" and ident.get("manufacturer_code") and ident.get("plugin_code")
    return {"verified": bool(verified), "vendor": ident.get("vendor") or "", "product": ident.get("product") or "", "manufacturer_code": ident.get("manufacturer_code"),
            "plugin_code": ident.get("plugin_code"), "codes_status": ident.get("codes_status", "UNVERIFIED"), "processor_fuid": ident.get("processor_fuid"),
            "latency_samples": ident.get("latency_samples"), "tail_samples": ident.get("tail_samples"), "buses": ident.get("buses"), "editor": ident.get("editor")}


def build(project: Path, *, build_kind: str = "SURROGATE") -> dict[str, Any]:
    params = parameters(project)
    ident = identity(project)
    if build_kind == "FIDELITY" and not ident["verified"]:
        build_kind = "SURROGATE"
        ident["fidelity_refused"] = "FIDELITY requires a VERIFIED_RUNTIME factory identity (SPEC §10)"
    ws = waveshaper_model(project, params)
    classes = owned_classes(project)
    covered = {c["name"] for c in classes if c["role"] == "WAVESHAPER"} if ws and ws["active"] else set()
    scaffolds = [c for c in classes if c["role"] in roles_mod.DSP_ROLES | {roles_mod.LICENSING_ROLE, "UNKNOWN", "GUI", "STATE"} and c["name"] not in covered]
    return {"build_kind": build_kind, "identity": ident, "parameters": params, "state": state_model(project, params), "modules": [ws] if ws else [],
            "scaffolds": scaffolds, "dsp_functions": dsp_functions(project)[:50], "covers": sorted(covered)}


__all__ = ["build", "parameters", "waveshaper_model", "state_model", "identity", "juce_param_id", "ACTIVE_RMSE"]
