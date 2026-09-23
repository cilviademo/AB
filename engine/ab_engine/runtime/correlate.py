"""Correlation (EXECUTE 2.2): static serialized keys × runtime parameters → state_runtime_map.

Relationships: SAME_ID (a serialized key equals a runtime parameter's id/title),
MAPPED (the state-differential harness located the field a parameter writes),
STATE_ONLY, RUNTIME_ONLY, UNKNOWN. ``value_representation`` is resolved by the
harness only: change one parameter, diff the serialized state, find the changed
field, compare its value form with the normalized and plain values.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

PARAM_RX = re.compile(r'<PARAM\s+id="([^"]+)"\s+value="([^"]+)"|<PARAM\s+value="([^"]+)"\s+id="([^"]+)"')


def parse_state_text(text: str | None) -> dict[str, str]:
    """All ``id → value`` pairs in a JUCE APVTS XML state, plus root attributes (state-only fields)."""
    out: dict[str, str] = {}
    if not text:
        return out
    for m in PARAM_RX.finditer(text):
        out[m.group(1) or m.group(4)] = m.group(2) or m.group(3)
    try:
        root = ET.fromstring(text)
        for k, v in root.attrib.items():
            out.setdefault(k, v)
    except ET.ParseError:
        pass
    return out


def diff_states(a: dict[str, str], b: dict[str, str]) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def _close(x: float, y: float, tol: float = 1e-4) -> bool:
    return abs(x - y) <= tol * max(1.0, abs(x), abs(y))


def representation(field_value: str, normalized: float, plain: float | None, step_count: int) -> str:
    try:
        v = float(field_value)
    except ValueError:
        return "OTHER"
    if step_count == 1 and v in (0.0, 1.0):
        return "BOOLEAN"
    if step_count > 1 and float(v).is_integer() and 0 <= v <= step_count:
        return "ENUM"
    if plain is not None and _close(v, plain):
        return "PLAIN"
    if _close(v, normalized):
        return "NORMALIZED"
    return "OTHER"


def correlate(serialized_keys: list[dict[str, Any]], runtime_params: list[dict[str, Any]],
              differential: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """``differential``: ``{param_id_str: {"changed": [field, ...], "field_value": str, "normalized": float, "plain": float|None}}``."""
    keys = {k["name"] for k in serialized_keys}
    by_title = {p.get("title"): p for p in runtime_params}
    out: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for p in runtime_params:
        pid = str(p.get("param_id"))
        title = p.get("title")
        rec: dict[str, Any] = {"param_id": p.get("param_id"), "title": title, "key": None, "relationship": "RUNTIME_ONLY",
                               "value_representation": "UNKNOWN", "basis": "runtime", "tier": "VST3_EXPORTED_PARAMETER"}
        d = (differential or {}).get(pid)
        if d and d.get("changed"):
            field = d["changed"][0] if len(d["changed"]) == 1 else next((c for c in d["changed"] if c == title or c in keys), d["changed"][0])
            rec.update({"key": field, "relationship": "SAME_ID" if field == title else "MAPPED",
                        "value_representation": representation(str(d.get("field_value", "")), float(d.get("normalized", 0.0)), d.get("plain"), int(p.get("step_count", 0))),
                        "changed_fields": d["changed"], "basis": "state-differential"})
            consumed.add(field)
        elif title in keys:
            rec.update({"key": title, "relationship": "SAME_ID", "basis": "title matches a serialized key (representation UNKNOWN until differential)"})
            consumed.add(title)
        out.append(rec)
    for k in serialized_keys:
        if k["name"] in consumed:
            continue
        tier = "STATE_SCHEMA_FIELD"
        basis = "static key, no runtime parameter changed it"
        if differential is not None:
            basis = "runtime: no exported parameter changes this field"
        out.append({"param_id": None, "title": None, "key": k["name"], "relationship": "STATE_ONLY", "value_representation": "UNKNOWN",
                    "basis": basis, "tier": tier, "static_hint": k.get("key_kind_candidate")})
    return out


def tiers(state_runtime_map: list[dict[str, Any]], ui_hints: set[str] | None = None) -> list[dict[str, Any]]:
    """03_architecture/parameters.json rows with the final tier vocabulary (SPEC §7)."""
    rows = []
    for m in state_runtime_map:
        tier = m["tier"]
        if m["relationship"] == "STATE_ONLY" and ui_hints and m["key"] in ui_hints:
            tier = "UI_ONLY_CONTROL"
        if m["relationship"] == "UNKNOWN":
            tier = "UNKNOWN_PROPERTY"
        rows.append({**m, "tier": tier})
    return rows
