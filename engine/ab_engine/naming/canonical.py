"""Naming canonicalization / identifier transformation (docs/NAMING_CANONICALIZATION.md).

Names are evidence, metadata and transformable identifiers — never immutable architecture and never a
capability gate. This module produces the reversible ``identifier_map`` for a project:

    {original, kind, original_address, source, evidence_status, category, semantic, active, reason}

* ``original`` is what the artifact says (RTTI / symbol / runtime / resource table). It is kept forever and
  is what the knowledge base, lineage and search keep matching on.
* ``semantic`` is a neutral descriptive name — only when the role is actually supported (callgraph /
  behaviour); otherwise ``RecoveredClass_NNNN`` (never invented meaning).
* ``active`` is the name the reconstructed / transformed source uses under the chosen mode:
  ``PRESERVE_ORIGINAL_NAMES`` (evidence default) · ``CANONICALIZE_NAMES`` (transformed-source default) ·
  ``CUSTOM_RENAME_MAP`` (owner-supplied ``original → active``; unmapped names canonicalize).

Never renamed by this layer: runtime parameter ids, serialized state keys, plugin identity (FUID, codes,
manufacturer). Those get *proposals* (``transformed_display_name``, ``LEGACY_STATE_KEY → TRANSFORMED_STATE_KEY``
with ``migration_status: PROPOSED``) that a FIDELITY build ignores and a TRANSFORMED build applies only through an
explicit compatibility map (SPEC §10, naming directive §8–9, §13).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

MODES = ("PRESERVE_ORIGINAL_NAMES", "CANONICALIZE_NAMES", "CUSTOM_RENAME_MAP")
CATEGORIES = ("VENDOR_REFERENCE", "PRODUCT_NAME", "MODEL_NUMBER", "LEGACY_PROJECT_NAME", "DEPRECATED_BRANDING", "TEMPORARY_DEV_NAME",
              "MISSPELLING", "MACHINE_USERNAME", "ABSOLUTE_BUILD_PATH", "GENERATED_MANGLED", "WINDOWS_ILLEGAL", "NONE")
#: neutral names per supported role (naming directive §7); a role that is only CANDIDATE gets no semantic name
ROLE_BASE = {"WAVESHAPER": "Saturation", "FILTER": "Filter", "FILTER_COEFFICIENT": "FilterCoefficients", "COMPRESSOR": "Compressor", "LIMITER": "Limiter",
             "GATE": "Gate", "DELAY": "Delay", "REVERB": "Reverb", "CONVOLUTION": "Convolution", "PITCH_TIME": "PitchShifter", "MODULATION": "Modulation",
             "METER": "Meter", "GAIN": "GainStage", "OVERSAMPLER": "Oversampler", "AUDIO_LOOP": "Processor", "PARAMETER_UPDATE": "ParameterUpdate",
             "STATE": "StateModel", "GUI": "Editor", "RESOURCE": "Resources", "LICENSING_AND_ENTITLEMENT_SUBSYSTEM": "Licensing", "PROTECTED_SUBSYSTEM": "Licensing"}
SUPPORTED_ROLE_STATUS = ("VERIFIED_CALLGRAPH", "BEHAVIOR_MATCHED", "VERIFIED", "BEHAVIORALLY_EQUIVALENT", "NUMERICALLY_EQUIVALENT", "BIT_EXACT")
#: abbreviations expanded when a vendor prefix is stripped (`SSLComp` → `Comp` → `Compressor`)
ABBREVIATIONS = {"comp": "Compressor", "compressor": "Compressor", "eq": "EQ", "hp": "HighPass", "hpf": "HighPassFilter", "lp": "LowPass", "lpf": "LowPassFilter",
                 "lim": "Limiter", "sat": "Saturation", "dist": "Distortion", "osc": "Oscillator", "env": "Envelope", "mod": "Modulation", "rev": "Reverb",
                 "dly": "Delay", "proc": "Processor", "fx": "Effect", "ui": "Editor", "gui": "Editor", "strip": "Strip", "chan": "Channel", "channel": "Channel",
                 "bus": "Bus", "drive": "Drive", "input": "Input", "output": "Output", "in": "Input", "out": "Output"}
#: architecture words that disambiguate collisions (naming directive §14)
ARCH_TOKENS = ("Bus", "Channel", "Parallel", "Input", "Output", "Master", "Side", "Mid", "Stereo", "Mono", "Pre", "Post")
_FRAMEWORK = ("juce::", "std::", "Steinberg::", "__cxxabiv1::", "__gnu_cxx::", "iplug::", "igraphics::")
_MANGLED = re.compile(r"^(_Z|\?)")
#: decompiler-generated labels are not names at all: never mapped, never renamed
_GENERATED = re.compile(r"^(switchD_|caseD_|FUN_|LAB_|DAT_|PTR_|thunk_|SUB_|EXT_|entry$|_init$|_fini$|frame_dummy|register_tm_clones|deregister_tm_clones|__do_global|Unwind_)")


def is_generated_label(name: str) -> bool:
    return bool(_GENERATED.match(leaf(name)) or _GENERATED.match(name))
_MODEL = re.compile(r"((?<![A-Za-z])[A-Z]{1,3}\d{2,4}[A-Z]?|\d{3,4}[A-Z]{0,2})(?![A-Za-z0-9])")   # LA2A, 1176, DBX160, 33609
_WIN_RESERVED = re.compile(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$")
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')


def split_camel(name: str) -> list[str]:
    """`SSL_ChannelStripProcessor` → [SSL, Channel, Strip, Processor]; keeps all-caps runs together."""
    parts: list[str] = []
    for chunk in re.split(r"[_\s\-]+", name):
        for m in re.finditer(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+|[A-Z]+", chunk):
            parts.append(m.group(0))
    return [p for p in parts if p]


def leaf(name: str) -> str:
    return name.split("::")[-1]


def infer_vendor_terms(names: list[str], *, declared: list[str] | None = None, min_count: int = 3) -> dict[str, str]:
    """Terms worth neutralizing, each with its category. Declared terms (identity vendor/product, the owner's
    list) are ``VENDOR_REFERENCE`` / ``PRODUCT_NAME``; an all-caps prefix shared by ≥ ``min_count`` plugin
    identifiers (`SSL` in SSLComp, SSL_EQ, SSLBusComp) is a ``VENDOR_REFERENCE`` *candidate* — a naming clue,
    never a claim about the algorithm (directive §19)."""
    terms: dict[str, str] = {}
    for t in declared or []:
        t = (t or "").strip()
        if len(t) >= 2:
            terms[t] = terms.get(t, "VENDOR_REFERENCE")
    counts: dict[str, int] = {}
    for n in names:
        if n.startswith(_FRAMEWORK) or is_generated_label(n):
            continue
        parts = split_camel(leaf(n))
        # an all-caps prefix followed by a CamelCase word: SSL|Comp, SSL|Channel — not DT|OR-style fragments
        if len(parts) > 1 and parts[0].isupper() and 2 <= len(parts[0]) <= 5 and parts[1][:1].isupper() and parts[1][1:].islower() and len(parts[1]) >= 2:
            counts[parts[0]] = counts.get(parts[0], 0) + 1
    for pfx, c in counts.items():
        if c >= min_count and pfx not in terms:
            terms[pfx] = "VENDOR_REFERENCE"
    return terms


def categorize(name: str, terms: dict[str, str]) -> str:
    n = leaf(name)
    if _MANGLED.match(n):
        return "GENERATED_MANGLED"
    if _WIN_RESERVED.match(n) or _ILLEGAL.search(n):
        return "WINDOWS_ILLEGAL"
    parts = split_camel(n)
    for t, cat in sorted(terms.items(), key=lambda kv: -len(kv[0])):
        if t in parts or n.lower().startswith(t.lower()) or t.lower() in n.lower():
            return cat
    if _MODEL.search(n):
        return "MODEL_NUMBER"
    return "NONE"


def strip_terms(name: str, terms: dict[str, str]) -> str:
    """Remove vendor/product/model terms from a name: whole parts (`SSL`), multi-part terms as a contiguous
    run of parts (`ABGroundTruth` = AB·Ground·Truth), and model numbers."""
    parts = split_camel(leaf(name))
    lowered = {t.lower() for t in terms}
    runs = [[q.lower() for q in split_camel(t)] for t in terms if len(split_camel(t)) > 1]
    kept: list[str] = []
    i = 0
    while i < len(parts):
        hit = next((r for r in runs if [q.lower() for q in parts[i:i + len(r)]] == r), None)
        if hit:
            i += len(hit)
            continue
        p = parts[i]
        if p.lower() not in lowered and not _MODEL.fullmatch(p):
            kept.append(p)
        i += 1
    if not kept:
        return ""
    return "".join(ABBREVIATIONS.get(p.lower(), p[:1].upper() + p[1:]) for p in kept)


def placeholder(kind: str, original: str) -> str:
    """Stable, meaningless name for an unsupported role: RecoveredClass_0042 (from the original's hash)."""
    n = int(hashlib.sha256(original.encode()).hexdigest()[:4], 16) % 10000
    base = {"class": "RecoveredClass", "function": "RecoveredFunction", "resource": "resource", "file": "file"}.get(kind, "Recovered")
    return f"{base}_{n:04d}"


def semantic_name(item: dict[str, Any], terms: dict[str, str]) -> tuple[str, str]:
    """(semantic name, basis). Role-supported → descriptive; else the original with vendor terms stripped when
    something meaningful remains (a name clue, kept as CANDIDATE), else a placeholder."""
    original = str(item.get("original") or "")
    role = str(item.get("role") or "")
    supported = str(item.get("role_status") or "") in SUPPORTED_ROLE_STATUS or bool(item.get("validated"))
    stripped = strip_terms(original, terms)
    if supported and role in ROLE_BASE:
        base = ROLE_BASE[role]
        arch = [p for p in split_camel(leaf(original)) if p in ARCH_TOKENS]
        name = "".join(arch[:2]) + base if arch and not base.startswith(tuple(arch)) else base
        return name, f"role {role} ({item.get('role_status') or 'validated'})" + (f" + architecture tokens {arch}" if arch else "")
    if stripped and stripped.lower() != leaf(original).lower() and len(stripped) >= 2:
        return stripped, "original with vendor/product/model terms removed (role not confirmed: no semantic claim)"
    if role in ROLE_BASE and stripped:
        return stripped, "original kept (role CANDIDATE only)"
    if stripped:
        return stripped, "original kept"
    return placeholder(str(item.get("kind") or "class"), original), "nothing meaningful survives the vendor terms; placeholder (directive §7)"


def resolve_collisions(rows: list[dict[str, Any]]) -> None:
    """Two originals must never collapse into one active name (directive §14). The member whose role is
    supported (or the first by original name) keeps the base name; the others get an architecture token from
    their own original (Bus, Channel, …) or a numeric suffix."""
    by_active: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_active.setdefault(r["active"], []).append(r)
    used: set[str] = set(by_active)
    for active, group in by_active.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda r: (str(r.get("role_status") or "") not in SUPPORTED_ROLE_STATUS and not r.get("validated"), r["original"]))
        keeper = group[0]
        for r in group[1:]:
            arch = [p for p in split_camel(leaf(r["original"])) if p in ARCH_TOKENS]
            cand = ("".join(arch[:2]) + active) if arch else active
            if cand in used or cand == active:
                i = 2
                while f"{active}_{i}" in used:
                    i += 1
                cand = f"{active}_{i}"
            r["active"] = cand
            r["collision"] = {"with": [keeper["original"]], "resolved_by": "numeric suffix" if cand.startswith(active + "_") else "architecture token"}
            used.add(cand)



def sanitize_filename(name: str) -> str:
    out = _ILLEGAL.sub("_", name).rstrip(". ")
    if _WIN_RESERVED.match(out.split(".")[0]):
        out = "_" + out
    return out[:120] if len(out) > 120 else out


def build_map(*, classes: list[dict[str, Any]], functions: list[dict[str, Any]] | None = None, parameters: list[dict[str, Any]] | None = None,
              state_keys: list[dict[str, Any]] | None = None, resources: list[dict[str, Any]] | None = None, mode: str = "PRESERVE_ORIGINAL_NAMES",
              custom: dict[str, str] | None = None, declared_terms: list[str] | None = None) -> dict[str, Any]:
    """The identifier map. ``classes``/``functions`` rows: {original, address?, source?, evidence_status?, role?, role_status?, validated?}.
    ``parameters``: {runtime_param_id, display_name}; ``state_keys``: {key}; ``resources``: {binarydata_name, sha256, filename?}."""
    if mode not in MODES:
        raise ValueError(f"naming mode must be one of {MODES}")
    custom = dict(custom or {})
    names = [c["original"] for c in classes] + [f["original"] for f in (functions or [])]
    terms = infer_vendor_terms(names, declared=declared_terms)
    rows: list[dict[str, Any]] = []
    for kind, items in (("class", classes), ("function", functions or [])):
        for it in items:
            original = str(it["original"])
            if original.startswith(_FRAMEWORK) or is_generated_label(original):
                continue
            item = dict(it, kind=kind, original=original)
            sem, basis = semantic_name(item, terms)
            cat = categorize(original, terms)
            if mode == "PRESERVE_ORIGINAL_NAMES":
                active, reason = leaf(original), "PRESERVE_ORIGINAL_NAMES"
            elif mode == "CUSTOM_RENAME_MAP" and (original in custom or leaf(original) in custom):
                active, reason = custom.get(original) or custom[leaf(original)], "CUSTOM_RENAME_MAP (owner-supplied)"
            elif cat == "NONE":
                active, reason = leaf(original), "no vendor/product/model reference: name kept"
            else:
                active, reason = sem, "USER_OR_POLICY_CANONICALIZATION"
            rows.append({"original": original, "kind": kind, "original_address": it.get("address"), "source": it.get("source"),
                         "evidence_status": it.get("evidence_status") or ("VERIFIED_ORIGINAL_NAME" if it.get("source") in ("MSVC_RTTI", "ITANIUM_RTTI", "ITANIUM_RTTI_STRUCTURAL", "SYMBOL", "RUNTIME") else "CANDIDATE_ORIGINAL_NAME"),
                         "role": it.get("role"), "role_status": it.get("role_status"), "category": cat, "semantic": sem, "semantic_basis": basis,
                         "active": sanitize_filename(active) if kind != "function" else active, "reason": reason,
                         "identity_unchanged": ["class identity", "function fingerprint", "binary address", "callgraph", "behavioural evidence", "parameter mapping", "validation state"]})
    if mode != "PRESERVE_ORIGINAL_NAMES":
        resolve_collisions(rows)
    # parameters: ids never renamed; display names get a proposal
    params = []
    for p in parameters or []:
        disp = str(p.get("display_name") or "")
        params.append({"runtime_param_id": p.get("runtime_param_id"), "original_display_name": disp, "transformed_display_name": (strip_terms(disp, terms) if mode != "PRESERVE_ORIGINAL_NAMES" and categorize(disp, terms) != "NONE" else disp) or disp,
                       "id_policy": "runtime_param_id preserved (automation, presets, sessions, state restoration); a new id only through an explicit compatibility map in a TRANSFORMED build"})
    # state keys: migration proposals, never applied here
    states = []
    for sk in state_keys or []:
        key = str(sk.get("key") or "")
        cat = categorize(key, terms)
        new = strip_terms(key, terms) if cat != "NONE" and mode != "PRESERVE_ORIGINAL_NAMES" else key
        states.append({"legacy": key, "new": new or key, "category": cat, "migration_status": "NOT_NEEDED" if new == key or not new else "PROPOSED",
                       "rule": "old presets/sessions stay loadable: the legacy key is read and migrated by the state layer only when compatibility is requested (directive §9)"})
    # resources: proposed portable file names with provenance
    res = []
    for r in resources or []:
        bd = str(r.get("binarydata_name") or "")
        fn = str(r.get("filename") or bd)
        ext = ("." + fn.rsplit(".", 1)[-1]) if "." in fn else ""
        stem = fn[: -len(ext)] if ext else fn
        new_stem = strip_terms(stem, terms) if mode != "PRESERVE_ORIGINAL_NAMES" and categorize(stem, terms) != "NONE" else stem
        res.append({"original_binarydata_name": bd, "original_filename": fn, "sha256": r.get("sha256"), "new_filename": sanitize_filename((new_stem or stem) + ext),
                    "category": categorize(stem, terms)})
    return {"mode": mode, "terms": terms, "identifiers": rows, "parameters": params, "state_keys": states, "resources": res,
            "reversible": True, "rule": "renames are presentation / source-maintenance transformations; every row carries the original and its evidence (docs/NAMING_CANONICALIZATION.md)"}


def search(imap: dict[str, Any], query: str) -> list[dict[str, Any]]:
    """Both name spaces (directive §16): a query matches original, semantic or active."""
    q = query.lower().strip()
    if not q:
        return []
    hits = [r for r in imap.get("identifiers", []) if q in str(r.get("original", "")).lower() or q in str(r.get("semantic", "")).lower() or q in str(r.get("active", "")).lower()]
    for r in imap.get("resources", []):
        if q in str(r.get("original_binarydata_name", "")).lower() or q in str(r.get("new_filename", "")).lower():
            hits.append({"kind": "resource", **r})
    return hits


def to_markdown(imap: dict[str, Any], *, title: str = "IDENTIFIER_MAP") -> str:
    lines = [f"# {title} — original ⇄ semantic ⇄ active names", "",
             f"Mode: `{imap['mode']}`. Terms neutralized: " + (", ".join(f"`{t}` ({c})" for t, c in imap["terms"].items()) or "none") + ".",
             "Renames are reversible presentation/source-maintenance transformations; identity, fingerprints, addresses, callgraph, behavioural evidence, parameter mapping and validation state are untouched (docs/NAMING_CANONICALIZATION.md).", "",
             "| original (evidence) | kind | address | evidence | category | semantic | active | reason |", "|---|---|---|---|---|---|---|---|"]
    for r in imap["identifiers"]:
        lines.append(f"| `{r['original']}` | {r['kind']} | {r.get('original_address') or ''} | {r['evidence_status']} | {r['category']} | `{r['semantic']}` | `{r['active']}` | {r['reason']}" + (f" (collision with {', '.join(r['collision']['with'])}: {r['collision']['resolved_by']})" if r.get("collision") else "") + " |")
    if imap["parameters"]:
        lines += ["", "## Parameters (ids never renamed)", "", "| runtime_param_id | original display | transformed display |", "|---|---|---|"]
        lines += [f"| `{p['runtime_param_id']}` | {p['original_display_name']} | {p['transformed_display_name']} |" for p in imap["parameters"]]
    if imap["state_keys"]:
        lines += ["", "## State keys (migration proposals, never applied silently)", "", "| legacy | new | status |", "|---|---|---|"]
        lines += [f"| `{s['legacy']}` | `{s['new']}` | {s['migration_status']} |" for s in imap["state_keys"]]
    if imap["resources"]:
        lines += ["", "## Resources", "", "| BinaryData name | original file | sha256 | new file |", "|---|---|---|---|"]
        lines += [f"| `{r['original_binarydata_name']}` | {r['original_filename']} | {(r.get('sha256') or '')[:12]} | {r['new_filename']} |" for r in imap["resources"]]
    return "\n".join(lines) + "\n"


__all__ = ["MODES", "CATEGORIES", "is_generated_label", "build_map", "search", "to_markdown", "infer_vendor_terms", "categorize", "strip_terms", "semantic_name", "resolve_collisions", "sanitize_filename", "split_camel"]
