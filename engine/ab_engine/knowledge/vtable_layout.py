"""Knowledge-learned vtable layouts (ADDENDUM A2 applied to SPEC §8.4 seeds).

A stripped build has no ``processBlock`` symbol, but its Itanium RTTI survives: ``ExportRTTI``
recovers every class's primary vtable structurally (typeinfo-name string → typeinfo object →
vtable). What a stripped build cannot say is *which slot is which method*. A symbol build of any
plugin on the same framework can: its vtables carry named slots, and those names are the same for
every class derived from the same framework base (``juce::AudioProcessor`` slot 10 is
``processBlock(float)`` for every JUCE 8 plugin).

So the knowledge base learns, from symbol builds only, ``rtti_name → [slot → (method leaf name,
fingerprint ids of the function seen in that slot)]``. On a stripped build a layout is applied to a
class only when the *fingerprints* corroborate it: the framework functions left un-overridden in the
class's own vtable (and in the base's own vtable when the binary carries it) must match the
fingerprints the layout recorded. A name match alone is never enough (CLAUDE.md: cache keyed by
fingerprints, never by name); a contradiction is recorded and the layout is not applied.

The seeds this produces are ``INFERRED`` / ``CANDIDATE``: ``seed_basis`` says so, and the
ground-truth gate reports the basis next to the result.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from ab_engine.knowledge.db import KnowledgeDB, fp_id

PURE_VIRTUAL = ("__cxa_pure_virtual", "_purecall")
GHIDRA_DEFAULT = re.compile(r"^(FUN_|thunk_FUN_|LAB_|SUB_|EXT_|Unwind_)")
SEED_KEYS = ("processBlock", "prepareToPlay", "releaseResources", "getStateInformation", "setStateInformation", "createEditor")
FRAMEWORK_PREFIXES = ("juce::", "Steinberg::", "std::", "__cxxabiv1::", "__gnu_cxx::")
MIN_SLOTS = 4            # a layout needs at least this many slots to mean anything
MIN_COMPARABLE = 4       # ... and at least this many fingerprint-comparable slots before it is applied
MIN_CONFIDENCE = 0.5     # fraction of comparable slots whose fingerprints match


def leaf(name: str) -> str:
    return name.split("::")[-1]


def _hexint(a: str) -> int:
    return int(str(a), 16)


def learn_rows(classes: list[dict[str, Any]], fp_by_addr: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Layouts a symbol build teaches: primary vtable of every class with ≥ MIN_SLOTS slots where at
    least half the slots carry a real (non-Ghidra-default) name."""
    rows: list[dict[str, Any]] = []
    for c in classes:
        name = c.get("name") or c.get("recovered_name")
        slots_list = c.get("vtable_slots") or []
        names_list = c.get("vtable_slot_names") or []
        if not name or not slots_list:
            continue
        slots = slots_list[0]
        names = names_list[0] if names_list else [""] * len(slots)
        if len(slots) < MIN_SLOTS or len(names) != len(slots):
            continue
        real = [n for n in names if n and not GHIDRA_DEFAULT.match(n)]
        if len(real) * 2 < len(slots):
            continue
        entries = []
        for i, (a, n) in enumerate(zip(slots, names)):
            n = n or ""
            pure = any(p in n for p in PURE_VIRTUAL)
            fp = fp_by_addr.get(a)
            owner = n.rsplit("::", 1)[0] if "::" in n else ""
            entries.append({"slot": i, "name": "" if pure or not n or GHIDRA_DEFAULT.match(leaf(n)) else leaf(n), "pure": pure,
                            "owner": "" if pure else owner, "own": (not pure) and owner == name,   # the class's own implementation sits here
                            "fps": [fp_id(fp)] if (fp and not pure and a not in ("0x0", "0")) else []})
        rows.append({"rtti_name": name, "slot_count": len(slots), "slots": entries, "_slots": slots, "_bases": list(c.get("bases") or [])})
    # A base whose own vtable was not walked (abstract classes, or a framework class the image never
    # instantiates) is still described by its derived classes: every slot a derived class does not own
    # belongs to a base, and the Itanium ABI appends a class's new virtuals after its base's slots. So a
    # derived class D with declared base B teaches a layout for B up to the last base-owned slot: base-owned
    # slots keep their fingerprints (B's default implementations), D-owned slots lend their name only.
    have = {r["rtti_name"] for r in rows}
    synthesized: list[dict[str, Any]] = []
    for r in rows:
        for b in r["_bases"]:
            if b in have or b.startswith("std::"):
                continue
            base_owned = [e["slot"] for e in r["slots"] if e["pure"] or (e["owner"] and e["owner"] != r["rtti_name"])]
            if len(base_owned) < MIN_SLOTS:
                continue
            count = max(base_owned) + 1
            ents = []
            for e in r["slots"][:count]:
                mine = e["own"]
                ents.append({"slot": e["slot"], "name": e["name"], "pure": e["pure"], "owner": "" if mine else e["owner"], "own": (not mine) and bool(e["owner"]),
                             "fps": [] if mine else list(e["fps"]), **({"name_from": r["rtti_name"]} if mine and e["name"] else {})})
            synthesized.append({"rtti_name": b, "slot_count": count, "slots": ents, "_slots": r["_slots"][:count], "_bases": [], "synthesized_from": r["rtti_name"]})
    rows.extend(synthesized)
    # A base's pure-virtual slots carry no name of their own (they point at __cxa_pure_virtual); the classes
    # deriving from it name them, and the Itanium ABI keeps a slot's meaning down the hierarchy. Fill a base's
    # blank slot names from its derived classes: declared bases, or bases inferred from shared slot functions
    # (>= half of the base's non-pure slots hold the very same function in the derived table).
    by_name = {r["rtti_name"]: r for r in rows}
    for r in rows:
        derived_of = set(r["_bases"])
        for b in rows:
            if b is r or b["slot_count"] > r["slot_count"] or b["rtti_name"] in derived_of:
                continue
            shared = sum(1 for e, a in zip(b["slots"], b["_slots"]) if not e["pure"] and r["_slots"][e["slot"]] == a)
            nonpure = sum(1 for e in b["slots"] if not e["pure"])
            if nonpure and shared * 2 >= nonpure:
                derived_of.add(b["rtti_name"])
        for bn in derived_of:
            b = by_name.get(bn)
            if not b or b["slot_count"] > r["slot_count"]:
                continue
            for e in b["slots"]:
                d = r["slots"][e["slot"]]
                if not e["name"] and d["name"]:
                    e["name"] = d["name"]
                    e["name_from"] = r["rtti_name"]
    for r in rows:
        r.pop("_slots", None)
        r.pop("_bases", None)
    return rows


def _transitive_bases(name: str, by_name: dict[str, dict[str, Any]]) -> list[str]:
    out: list[str] = []
    q = deque(by_name.get(name, {}).get("bases", []) or [])
    while q:
        b = q.popleft()
        if b in out or b == name:
            continue
        out.append(b)
        q.extend(by_name.get(b, {}).get("bases", []) or [])
    return out


def apply(db: KnowledgeDB, classes: list[dict[str, Any]], fp_by_addr: dict[str, dict[str, Any]], *, artifact_sha256: str = "",
          tool_version: str = "", evidence_version: str = "") -> dict[str, Any]:
    """Seed the framework entry points of a stripped build from learned layouts.

    Returns ``{"seeds": {key: addr}, "seed_basis": str, "classes": [per-class report], "layouts_considered": n}``.
    ``seeds`` is empty when nothing is fingerprint-confirmed."""
    by_name = {(c.get("name") or c.get("recovered_name")): c for c in classes if (c.get("name") or c.get("recovered_name"))}
    reports: list[dict[str, Any]] = []
    considered = 0

    def fp_of(addr: str | None) -> str | None:
        fp = fp_by_addr.get(addr) if addr else None
        return fp_id(fp) if fp else None

    for name, c in by_name.items():
        own_list = c.get("vtable_slots") or []
        if not own_list or len(own_list[0]) < MIN_SLOTS:
            continue
        own = own_list[0]
        cands = [name] + _transitive_bases(name, by_name)
        layouts = db.layouts_for(cands)
        if not layouts:
            continue
        best: dict[str, Any] | None = None
        tried = []
        for lay in layouts:
            considered += 1
            if lay["slot_count"] > len(own):
                tried.append({"layout": lay["layout_id"], "rtti_name": lay["rtti_name"], "state": "SLOT_COUNT_EXCEEDS_TABLE", "confidence": None})
                continue
            base_slots = (by_name.get(lay["rtti_name"], {}).get("vtable_slots") or [[]])[0] if lay["rtti_name"] != name else []
            matches = comparable = 0
            for e in lay["slots"]:
                i = e["slot"]
                if e.get("pure") or not e.get("fps"):
                    continue
                cand = {f for f in (fp_of(own[i]), fp_of(base_slots[i]) if i < len(base_slots) else None) if f}
                if not cand:
                    continue
                comparable += 1
                if cand & set(e["fps"]):
                    matches += 1
            conf = (matches / comparable) if comparable else None
            if comparable >= MIN_COMPARABLE and conf is not None and conf >= MIN_CONFIDENCE:
                state = "FINGERPRINT_CONFIRMED"
            elif comparable == 0:
                state = "NAME_ONLY_NOT_APPLIED"
            else:
                state = "CONTRADICTED"
                db.history("vtable_layout", lay["layout_id"], lay.get("state"), lay.get("state") or "",
                           f"not applied to {name} in {artifact_sha256[:12]}: {matches}/{comparable} slot fingerprints match (name matched, fingerprints did not)",
                           tool_version=tool_version, evidence_version=evidence_version)
            t = {"layout": lay["layout_id"], "rtti_name": lay["rtti_name"], "slot_count": lay["slot_count"], "state": state, "confidence": conf,
                 "matches": matches, "comparable": comparable, "learned_from": len(lay.get("source_hashes") or []), "verifications": lay.get("verifications")}
            tried.append(t)
            if state == "FINGERPRINT_CONFIRMED" and (best is None or (conf, lay["slot_count"]) > (best["confidence"], best["slot_count"])):
                best = dict(t, slots=lay["slots"], base_slots=base_slots)
        rep: dict[str, Any] = {"class": name, "slots": len(own), "bases": cands[1:], "layouts": tried, "applied": None, "methods": {}}
        if best:
            methods: dict[str, dict[str, Any]] = {}
            for e in best["slots"]:
                i = e["slot"]
                if not e.get("name") or i >= len(own):
                    continue
                base_slots = best["base_slots"]
                same_as_base = i < len(base_slots) and base_slots[i] == own[i]
                own_fp = fp_of(own[i])
                if best["rtti_name"] == name:
                    overridden = bool(e.get("own"))          # the class's own layout: the symbol build said whose implementation sits here
                else:
                    overridden = (not same_as_base) and (own_fp is None or own_fp not in set(e.get("fps") or []))
                m = {"slot": i, "addr": own[i], "overridden": overridden, "evidence": "INFERRED"}
                # first overridden slot wins a name; an un-overridden one only if nothing overridden carries it
                prev = methods.get(e["name"])
                if prev is None or (overridden and not prev["overridden"]):
                    methods[e["name"]] = m
            rep["applied"] = {k: best[k] for k in ("layout", "rtti_name", "slot_count", "confidence", "matches", "comparable", "learned_from")}
            rep["methods"] = methods
        reports.append(rep)

    # choose the plugin's own processor: a non-framework class with confirmed layout and the most overridden seed slots
    def score(r: dict[str, Any]) -> tuple[int, int, int]:
        fw = 1 if r["class"].startswith(FRAMEWORK_PREFIXES) else 0
        over = sum(1 for k in SEED_KEYS if r["methods"].get(k, {}).get("overridden"))
        return (-fw, over, len(r["methods"]))

    applied = sorted((r for r in reports if r["applied"]), key=score, reverse=True)
    seeds: dict[str, str] = {}
    seed_detail: dict[str, Any] = {}
    chosen = None
    for r in applied:
        pb = r["methods"].get("processBlock")
        if pb and pb["overridden"]:
            chosen = r
            break
    if chosen:
        for k in SEED_KEYS:
            m = chosen["methods"].get(k)
            if m and m["overridden"]:
                seeds[k] = m["addr"]
                seed_detail[k] = {"slot": m["slot"], "class": chosen["class"], "evidence": "INFERRED"}
    basis = ("knowledge vtable layout (%s from %d symbol build(s), %d/%d slot fingerprints match) — CANDIDATE"
             % (chosen["applied"]["rtti_name"], chosen["applied"]["learned_from"], chosen["applied"]["matches"], chosen["applied"]["comparable"])) if chosen else "none"
    return {"seeds": seeds, "seed_detail": seed_detail, "seed_basis": basis, "chosen_class": chosen["class"] if chosen else None,
            "ambiguous": [r["class"] for r in applied if r is not chosen and r["methods"].get("processBlock", {}).get("overridden") and not r["class"].startswith(FRAMEWORK_PREFIXES)],
            "classes": reports, "layouts_considered": considered}


def distances(functions: list[dict[str, Any]], seed: str) -> dict[str, int]:
    """BFS ``dist_from_processBlock`` over the callgraph's callee lists (mirrors ExportCallgraph)."""
    callees = {f["addr"]: f.get("callees", []) for f in functions}
    dist = {seed: 0}
    q = deque([seed])
    while q:
        a = q.popleft()
        for c in callees.get(a, []):
            if c not in dist and c in callees:
                dist[c] = dist[a] + 1
                q.append(c)
    return dist


__all__ = ["learn_rows", "apply", "distances", "SEED_KEYS", "MIN_CONFIDENCE", "MIN_COMPARABLE"]
