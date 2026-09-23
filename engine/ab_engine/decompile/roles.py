"""Function role scoring (SPEC §8.2) over the callgraph + fingerprint features exported by Ghidra.

Inputs per function: dist_from_processBlock, float_ops, simd_ops, loops, sample_rate_refs,
constant_refs / CONSTANT_SIGNATURE, libm_calls, string_refs, param/state references (from the
runtime map when parameter ids appear as immediates), RTTI class + vtable slot, and the static
name-token role of its class (CANDIDATE). Output: role, role_status
(CANDIDATE | VERIFIED_CALLGRAPH), role_basis[], priority (§8.6).
"""

from __future__ import annotations

import math
import re
from typing import Any

ROLES = ("AUDIO_LOOP", "GAIN", "WAVESHAPER", "FILTER", "FILTER_COEFFICIENT", "OVERSAMPLER", "COMPRESSOR", "LIMITER", "GATE",
         "DELAY", "REVERB", "CONVOLUTION", "PITCH_TIME", "MODULATION", "METER", "PARAMETER_UPDATE", "STATE", "GUI", "RESOURCE",
         "FRAMEWORK", "RUNTIME", "LICENSING_AND_ENTITLEMENT_SUBSYSTEM", "UNKNOWN")
#: ADDENDUM C2: licensing / activation / entitlement code is a normal subsystem. The frozen static engine still
#: emits PROTECTED_SUBSYSTEM; it is an alias of LICENSING_AND_ENTITLEMENT_SUBSYSTEM everywhere AB writes.
LICENSING_ROLE = "LICENSING_AND_ENTITLEMENT_SUBSYSTEM"
ROLE_ALIASES = {"PROTECTED_SUBSYSTEM": LICENSING_ROLE}


def canonical_role(role: str | None) -> str | None:
    return ROLE_ALIASES.get(role or "", role)

#: v2 static (name-token) roles → final vocabulary (DECISIONS D-010)
STATIC_TO_FINAL = {"DELAY_REVERB": "DELAY", "ENVELOPE": "COMPRESSOR", "STATE_CONTROL": "STATE", "GUI": "GUI", "WAVESHAPER": "WAVESHAPER",
                   "FILTER": "FILTER", "OVERSAMPLER": "OVERSAMPLER", "LIMITER": "LIMITER", "COMPRESSOR": "COMPRESSOR", "GATE": "GATE",
                   "METER": "METER", "PROTECTED_SUBSYSTEM": "LICENSING_AND_ENTITLEMENT_SUBSYSTEM", "UNKNOWN": "UNKNOWN"}

DSP_ROLES = {"AUDIO_LOOP", "GAIN", "WAVESHAPER", "FILTER", "FILTER_COEFFICIENT", "OVERSAMPLER", "COMPRESSOR", "LIMITER", "GATE",
             "DELAY", "REVERB", "CONVOLUTION", "PITCH_TIME", "MODULATION"}

KNOWN_CONSTANTS = {"pi": 3.141592653589793, "2pi": 6.283185307179586, "sqrt2": 1.4142135623730951, "inv_sqrt2": 0.7071067811865476,
                   "ln10_20": 0.11512925464970229, "20_ln10": 8.685889638065037}


def _tokens(name: str) -> str:
    n = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    n = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", n)
    return " " + re.sub(r"[:_()<>,*&]+", " ", n).lower() + " "


def _const_hits(constants: list[Any]) -> dict[str, int]:
    hits: dict[str, int] = {}
    for c in constants:
        try:
            v = float(c)
        except (TypeError, ValueError):
            continue
        for k, ref in KNOWN_CONSTANTS.items():
            if ref and abs(v - ref) <= abs(ref) * 1e-4:
                hits[k] = hits.get(k, 0) + 1
        if v in (44100.0, 48000.0, 88200.0, 96000.0, 192000.0):
            hits["sample_rate"] = hits.get("sample_rate", 0) + 1
    return hits


def score(fn: dict[str, Any], fp: dict[str, Any] | None, *, class_static_role: str | None, is_owned: bool,
          param_refs: int, noise: bool, wrapper: bool, demangled: str) -> dict[str, Any]:
    dist = int(fn.get("dist_from_processBlock", -1))
    basis: list[str] = []
    if noise:
        role = "RUNTIME" if (fn.get("name") or "").startswith(("_", "__")) or "FUN_" not in str(fn.get("name")) and "CRT" in str(demangled) else "FRAMEWORK"
        return {"role": role, "role_status": "CANDIDATE", "role_basis": ["noise suppression"], "priority": 0.0, "dist": dist}
    fo, so, loops = int(fn.get("float_ops", 0)), int(fn.get("simd_ops", 0)), int(fn.get("loops", 0))
    libm, sr, cr, strs = int(fn.get("libm_calls", 0)), int(fn.get("sample_rate_refs", 0)), int(fn.get("constant_refs", 0)), int(fn.get("string_refs", 0))
    consts = _const_hits((fp or {}).get("CONSTANT_SIGNATURE", []) + list(fn.get("constants", [])))
    tokens = _tokens(demangled)
    dsp_density = (fo + 2 * so) / max(8.0, float(fn.get("size", 0)) / 4.0)

    role = "UNKNOWN"
    if strs > 6 and fo == 0:
        role, _ = ("GUI", basis.append("many string refs, no float work")) if re.search(r" (paint|resized|button|slider|label|component|colour|font|draw) ", tokens) else ("STATE", basis.append("string refs, no float work"))
    elif re.search(r" (licen\w*|serial|activat\w*|unlock|trial|hwid) ", tokens):
        role = LICENSING_ROLE; basis.append("licence / activation tokens")
    elif re.search(r" (get state|set state|state information|value tree|xml|preset) ", tokens):
        role = "STATE"; basis.append("state tokens")
    elif fo + so > 0 and loops > 0 and dist >= 0:
        if libm > 0 and re.search(r" (tanh|atan|clip\w*|satur\w*|shaper|drive|distort\w*|fold) ", tokens) or (libm > 0 and dist <= 3 and "sample_rate" not in consts):
            role = "WAVESHAPER"; basis.append("libm + nonlinear tokens" if re.search(r" (tanh|atan|clip|satur|shaper|drive) ", tokens) else "libm inside a processing loop near processBlock")
        elif ("pi" in consts or "2pi" in consts or "sample_rate" in consts or sr > 0) and libm > 0:
            role = "FILTER_COEFFICIENT"; basis.append("π / sample-rate constants with libm (tan/exp)")
        elif re.search(r" (filter|lpf|hpf|svf|tpt|biquad|ladder|shelf|eq) ", tokens) or ("inv_sqrt2" in consts and loops):
            role = "FILTER"; basis.append("filter tokens or Butterworth Q")
        elif re.search(r" (oversampl\w*|resampl\w*|upsamp\w*|downsamp\w*|halfband|polyphase) ", tokens):
            role = "OVERSAMPLER"; basis.append("oversampling tokens")
        elif re.search(r" (compress\w*|envelope|follower|attack|release) ", tokens):
            role = "COMPRESSOR"; basis.append("dynamics tokens")
        elif re.search(r" (limit\w*|ceiling|lookahead) ", tokens):
            role = "LIMITER"; basis.append("limiter tokens")
        elif re.search(r" (delay|echo) ", tokens):
            role = "DELAY"; basis.append("delay tokens")
        elif re.search(r" (reverb|comb|allpass) ", tokens):
            role = "REVERB"; basis.append("reverb tokens")
        elif re.search(r" (convol\w*|fft|impulse) ", tokens):
            role = "CONVOLUTION"; basis.append("convolution tokens")
        elif re.search(r" (pitch|stretch|tuner|transpos\w*) ", tokens):
            role = "PITCH_TIME"; basis.append("pitch/time tokens")
        elif re.search(r" (lfo|chorus|phaser|flanger|tremolo|wow|flutter|modulat\w*) ", tokens):
            role = "MODULATION"; basis.append("modulation tokens")
        elif re.search(r" (meter|rms|peak|lufs|vu) ", tokens):
            role = "METER"; basis.append("meter tokens")
        elif re.search(r" (gain|volume|decibel|db) ", tokens) or ("ln10_20" in consts or "20_ln10" in consts):
            role = "GAIN"; basis.append("gain tokens or dB constants")
        elif dist == 0:
            role = "AUDIO_LOOP"; basis.append("processBlock itself")
        elif dsp_density > 0.15 and loops > 0:
            role = "AUDIO_LOOP"; basis.append(f"float density {dsp_density:.2f} in a loop, {dist} calls from processBlock")
    elif fo + so > 0 and dist >= 0 and param_refs > 0:
        role = "PARAMETER_UPDATE"; basis.append("parameter ids referenced, float work, no loop")
    elif param_refs > 0:
        role = "PARAMETER_UPDATE"; basis.append("parameter ids referenced")
    elif class_static_role and class_static_role != "UNKNOWN":
        role = STATIC_TO_FINAL.get(class_static_role, "UNKNOWN"); basis.append(f"class name tokens ({class_static_role})")
    elif re.search(r" (juce|steinberg|vst) ", tokens):
        role = "FRAMEWORK"; basis.append("framework namespace")

    if wrapper:
        basis.append("forward-only wrapper (collapsed in human output)")
    if class_static_role and STATIC_TO_FINAL.get(class_static_role) == role and role != "UNKNOWN":
        basis.append("agrees with the static class role")
    # VERIFIED_CALLGRAPH: reachable from a symbol-seeded processBlock with DSP evidence; otherwise CANDIDATE
    status = "VERIFIED_CALLGRAPH" if (dist >= 0 and fn.get("seed_basis") == "symbol" and role in DSP_ROLES) else "CANDIDATE"
    # §8.6 priority = processBlock-reachable × plugin-specific × has verified parameter/state relationship × DSP evidence × not known
    reach = 1.0 / (1.0 + max(dist, 0)) if dist >= 0 else 0.05
    priority = reach * (1.0 if is_owned else 0.3) * (1.0 + 0.5 * min(param_refs, 4)) * (0.2 + min(1.0, dsp_density + 0.1 * libm + 0.1 * len(consts)))
    if role in DSP_ROLES:
        priority *= 1.5
    if noise or wrapper:
        priority *= 0.1
    return {"role": role, "role_status": status, "role_basis": basis or ["no distinguishing evidence"], "priority": round(priority, 4),
            "dist": dist, "dsp_density": round(dsp_density, 3), "constants": consts}
