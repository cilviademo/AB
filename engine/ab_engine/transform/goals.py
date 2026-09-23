"""Recovery goals and preservation switches (ADDENDUM C3).

The owner selects a goal after evidence recovery; per-subsystem switches say what must survive the
transformation. ``PRESERVE ORIGINAL`` (the default) produces no transformation node at all: Source/Active
is the recovered implementation. Everything else is recorded in the transformation graph, never merged into
recovery, and validated against the surviving artifact.

Goals AB can carry out today are listed in ``AVAILABLE``; the others are accepted, recorded and reported
``NOT_AVAILABLE`` with the reason (interface + honest status, never a faked result — AB_BRIEF).
"""

from __future__ import annotations

from typing import Any

GOALS = ("PRESERVE_ORIGINAL", "MODERNIZE", "MIGRATE", "REFACTOR", "PORT", "REBUILD")
GOAL_ALIASES = {"PRESERVE ORIGINAL": "PRESERVE_ORIGINAL", "PRESERVE": "PRESERVE_ORIGINAL", "ORIGINAL": "PRESERVE_ORIGINAL"}
#: what each goal means for the generated source (a transformation node per subsystem it touches)
GOAL_TEXT = {
    "PRESERVE_ORIGINAL": "reproduce the recovered implementation; no transformation nodes",
    "MODERNIZE": "same behaviour, current JUCE/C++ idioms: block-processing DSP modules (juce::dsp ProcessorBase shape), cached parameter handles, noexcept/[[nodiscard]], canonical names",
    "REFACTOR": "same behaviour and APIs, source reorganised into per-subsystem modules with canonical names",
    "MIGRATE": "state / preset / licence-data schema migration with compatibility maps",
    "PORT": "another framework or platform target",
    "REBUILD": "new product identity on the recovered behaviour",
}
#: goals with a generator in this version; the rest are interface-only (recorded NOT_AVAILABLE)
AVAILABLE = ("PRESERVE_ORIGINAL", "MODERNIZE", "REFACTOR")
NOT_AVAILABLE_REASON = {
    "MIGRATE": "state / preset / licence-data migration generators are not implemented yet; the naming layer already proposes LEGACY_STATE_KEY → TRANSFORMED_STATE_KEY rows (identifier_map.json) and nothing is applied",
    "PORT": "no second framework target is generated yet (iPlug2 fixture pending, BLOCKERS B-008)",
    "REBUILD": "new-identity builds need the FIDELITY/TRANSFORMED identity split of SPEC §10 wired to the goal; SURROGATE identity is what the build uses today",
}
#: per-subsystem preservation switches: YES / NO / OPTIONAL (defaults per ADDENDUM C3's example)
SWITCHES = {"preserve_dsp_behavior": "YES", "preserve_preset_compatibility": "YES", "preserve_legacy_license_format": "OPTIONAL", "replace_activation_backend": "NO",
            "preserve_parameter_ids": "YES", "preserve_state_keys": "YES", "preserve_identity": "YES"}
STATUS = ("RECOVERED_EXACT", "RECONSTRUCTED", "MODERNIZED_EQUIVALENT", "TRANSFORMED_COMPATIBLE", "TRANSFORMED_WITH_MIGRATION", "TRANSFORMED_BREAKING", "UNRECOVERABLE", "NOT_AVAILABLE", "PENDING_VALIDATION")
BEHAVIOURS = ("ORIGINAL_BEHAVIOR", "RECOVERED_BEHAVIOR", "TRANSFORMED_BEHAVIOR")


def normalize_goal(value: Any) -> str:
    g = str(value or "PRESERVE_ORIGINAL").strip().upper().replace("-", "_")
    g = GOAL_ALIASES.get(g, g)
    if g not in GOALS:
        raise ValueError(f"recovery goal must be one of {GOALS} (got {value!r})")
    return g


def switches_from_options(options: dict[str, Any]) -> dict[str, str]:
    """``--option preserve_dsp_behavior=NO`` style overrides; unknown values are rejected, unknown keys ignored."""
    out = dict(SWITCHES)
    for k in SWITCHES:
        if k in options:
            v = str(options[k]).strip().upper()
            v = {"1": "YES", "TRUE": "YES", "0": "NO", "FALSE": "NO"}.get(v, v)
            if v not in ("YES", "NO", "OPTIONAL"):
                raise ValueError(f"{k} must be YES, NO or OPTIONAL")
            out[k] = v
    return out


def plan(goal: str, switches: dict[str, str]) -> dict[str, Any]:
    """What this goal will do, in one structure the graph, the generator and the UI all read."""
    goal = normalize_goal(goal)
    transformed = goal != "PRESERVE_ORIGINAL"
    return {"goal": goal, "goal_text": GOAL_TEXT[goal], "switches": switches, "transformed": transformed,
            "available": goal in AVAILABLE, "not_available_reason": NOT_AVAILABLE_REASON.get(goal),
            "active_variant": "TRANSFORMED" if (transformed and goal in AVAILABLE) else "RECOVERED",
            "naming_default": "CANONICALIZE_NAMES" if transformed else "PRESERVE_ORIGINAL_NAMES"}


__all__ = ["GOALS", "GOAL_TEXT", "AVAILABLE", "SWITCHES", "STATUS", "BEHAVIOURS", "normalize_goal", "switches_from_options", "plan"]
