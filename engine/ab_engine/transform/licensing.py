"""Licensing / entitlement subsystem checks (ADDENDUM C2).

Two things this module knows how to say, and nothing more:

* ``licensing_symbols`` — which recovered classes / functions belong to
  ``LICENSING_AND_ENTITLEMENT_SUBSYSTEM`` (role from the decompiler stage; the frozen v2 label
  ``PROTECTED_SUBSYSTEM`` is an alias), and which state keys look like licence state.
* ``detect_bypass`` — whether a source file replaces a licensing check with a constant
  (``return true;``, ``licensed = true;`` …). Such an edit is a *transformation* with status
  ``TRANSFORMED_BREAKING`` when the evidence body of the same function branches; when no evidence
  body exists it is ``LICENSE_REQUIRES_MANUAL_REVIEW``. It is never labelled recovery, and it is
  never applied by AB itself.

Validation states (SPEC §12 / C2): ``LICENSE_BEHAVIOR_MATCHED`` · ``LICENSE_STATE_COMPATIBLE`` ·
``LICENSE_MIGRATION_VALIDATED`` · ``LICENSE_TRANSFORMED`` · ``LICENSE_REQUIRES_MANUAL_REVIEW``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

LICENSING_ROLE = "LICENSING_AND_ENTITLEMENT_SUBSYSTEM"
ROLE_ALIASES = ("LICENSING_AND_ENTITLEMENT_SUBSYSTEM", "PROTECTED_SUBSYSTEM")
LICENSE_STATES = ("LICENSE_BEHAVIOR_MATCHED", "LICENSE_STATE_COMPATIBLE", "LICENSE_MIGRATION_VALIDATED", "LICENSE_TRANSFORMED", "LICENSE_REQUIRES_MANUAL_REVIEW")
#: state keys / identifiers that look like licence state (a hint for grouping, never a classification by itself)
LICENSE_TOKENS = re.compile(r"(?i)(licen[cs]e|serial|activat|entitle|unlock|trial|demo|registr|hwid|machine[_ ]?id)")
#: the function names a bypass edit typically targets
CHECK_TOKENS = re.compile(r"(?i)(isLicensed|checkSerial|validate|verify|isValid|isActivated|isDemo|isTrial|hasLicen[cs]e|checkLicen[cs]e|licensed)")

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_CONST_RETURN = re.compile(r"^\s*return\s+(true|false|1|0)\s*;\s*$")
_FORCED_FLAG = re.compile(r"^\s*(?:this->)?(\w*(?:licen[cs]ed|valid|activated|unlocked|registered)\w*)\s*=\s*(true|1)\s*;\s*(?:return\s+(?:true|1|\1)\s*;\s*)?$", re.I)
_BRANCH = re.compile(r"\b(if|switch|while|for)\b|\?")


def is_licensing_role(role: str | None) -> bool:
    return (role or "") in ROLE_ALIASES


def looks_like_license_state(key: str) -> bool:
    return bool(LICENSE_TOKENS.search(key or ""))


def function_bodies(text: str) -> dict[str, str]:
    """``{qualified_or_leaf_name: body}`` for every brace-delimited function definition in a C/C++ text
    (a small tokenizer, enough for generated / decompiled code; templates and macros are not parsed)."""
    src = _COMMENT.sub("", text)
    out: dict[str, str] = {}
    for m in re.finditer(r"([A-Za-z_][\w:<>~]*)\s*\([^;{}]*\)\s*(?:const|noexcept|override|final|\s)*\s*\{", src):
        name = m.group(1)
        if name in ("if", "for", "while", "switch", "catch", "return", "sizeof"):
            continue
        depth, i = 0, m.end() - 1
        start = i
        while i < len(src):
            c = src[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = src[start + 1:i]
        out[name] = body
        out.setdefault(name.split("::")[-1], body)
    return out


def _is_constant(body: str) -> str | None:
    stmts = [s.strip() for s in body.strip().split(";") if s.strip()]
    flat = "\n".join(s + ";" for s in stmts)
    if _CONST_RETURN.match(flat):
        return "CONSTANT_RETURN"
    if _FORCED_FLAG.match(flat):
        return "FORCED_FLAG"
    return None


def detect_bypass(transformed_text: str, *, symbols: list[str] | None = None, evidence_text: str | None = None) -> list[dict[str, Any]]:
    """Find licensing functions in ``transformed_text`` whose body is a constant. ``symbols`` narrows the
    functions looked at (recovered licensing symbols); without it every function whose name carries a
    check token is examined. ``evidence_text`` (the decompiled / recovered original) decides the status:
    the original branches → ``TRANSFORMED_BREAKING``; the original is constant too → no finding (the
    reconstruction matches the original); no evidence body → ``LICENSE_REQUIRES_MANUAL_REVIEW``."""
    bodies = function_bodies(transformed_text)
    ev = function_bodies(evidence_text) if evidence_text else {}
    wanted = {s.split("::")[-1] for s in (symbols or [])}
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, body in bodies.items():
        leaf = name.split("::")[-1]
        if leaf in seen:
            continue
        if wanted and leaf not in wanted and name not in set(symbols or []):
            continue
        if not wanted and not CHECK_TOKENS.search(leaf):
            continue
        kind = _is_constant(body)
        if not kind:
            continue
        seen.add(leaf)
        orig = ev.get(name) or ev.get(leaf)
        if orig is None:
            status, reason = "LICENSE_REQUIRES_MANUAL_REVIEW", "no evidence body for this function: cannot tell a faithful stub from a bypass"
        elif _is_constant(orig):
            continue   # the original returns a constant as well: this is recovery, not a bypass
        elif _BRANCH.search(orig):
            status, reason = "TRANSFORMED_BREAKING", "the evidence body branches on its inputs; the transformed body returns a constant"
        elif kind == "FORCED_FLAG":
            status, reason = "TRANSFORMED_BREAKING", "the transformed body forces the licence flag that the evidence body only reads"
        else:
            status, reason = "LICENSE_REQUIRES_MANUAL_REVIEW", "the evidence body returns state without branching; a constant may or may not be equivalent"
        findings.append({"symbol": name, "kind": kind, "status": status, "subsystem": LICENSING_ROLE, "reason": reason,
                         "labelled_as": "transformation (never recovery)", "body": body.strip()[:160]})
    return findings


def scan_tree(root: Path, *, symbols: list[str] | None, evidence_root: Path | None) -> list[dict[str, Any]]:
    """Run ``detect_bypass`` over every C++ file under ``root`` (Source/Active, transformed_source …)."""
    if not root.is_dir():
        return []
    ev_text = ""
    if evidence_root and evidence_root.is_dir():
        ev_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(evidence_root.rglob("*")) if p.suffix in (".c", ".cpp", ".h", ".hpp", ".cc"))
    out: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        if p.suffix not in (".c", ".cpp", ".h", ".hpp", ".cc"):
            continue
        for f in detect_bypass(p.read_text(encoding="utf-8", errors="replace"), symbols=symbols, evidence_text=ev_text or None):
            out.append({**f, "file": p.relative_to(root).as_posix()})
    return out


__all__ = ["LICENSING_ROLE", "LICENSE_STATES", "is_licensing_role", "looks_like_license_state", "function_bodies", "detect_bypass", "scan_tree"]
