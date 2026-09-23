"""YARA candidate-family rules (EXECUTE_ADDENDUM_A §A4).

Rules live in ``lineage/rules/*.yar`` (repo root) and are compiled with yara-python. A match is
evidence that a *known family's markers* occur in the artifact — never proof of lineage. Every
hit is emitted as ``CANDIDATE_FAMILY`` with the matched strings/conditions listed; promotion to an
INFERRED family (class-set Jaccard) or a VERIFIED shared implementation (function/vtable
fingerprints) follows A2. ``AB.Framework.*`` and ``AB.ThirdParty.*`` hits are library markers, not
families. A missing yara-python leaves the scan ``UNAVAILABLE`` (never an empty "no family").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ab_engine import deps
from ab_engine import tools as tools_mod


def rules_dir() -> Path | None:
    root = tools_mod.repo_root()
    if root and (root / "lineage" / "rules").is_dir():
        return root / "lineage" / "rules"
    import sys  # noqa: PLC0415

    if getattr(sys, "frozen", False):
        p = Path(sys.executable).resolve().parent.parent / "lineage" / "rules"
        if p.is_dir():
            return p
    return None


def scan(path: Path, *, max_strings_per_rule: int = 24) -> dict[str, Any]:
    d = rules_dir()
    if d is None:
        return {"status": "UNAVAILABLE", "reason": "lineage/rules not found beside the engine", "candidates": []}
    if not deps.available("yara"):
        return {"status": "UNAVAILABLE", "reason": "yara-python not importable (docs/DEPENDENCIES.md)", "candidates": []}
    import yara  # noqa: PLC0415

    files = sorted(d.glob("*.yar"))
    if not files:
        return {"status": "UNAVAILABLE", "reason": "no .yar rules", "candidates": []}
    rules = yara.compile(filepaths={f.stem: str(f) for f in files})
    matches = rules.match(str(path), timeout=120)
    cands = []
    for m in matches:
        seen: dict[str, int] = {}
        for s in m.strings:
            ident = s.identifier
            seen[ident] = seen.get(ident, 0) + len(s.instances)
        kind = "FRAMEWORK" if m.rule.startswith("AB_Framework") else "THIRD_PARTY" if m.rule.startswith("AB_ThirdParty") else "FAMILY"
        cands.append({"rule": m.rule.replace("_", ".", 2) if m.rule.startswith("AB_") else m.rule, "namespace": m.namespace, "kind": kind,
                      "status": "CANDIDATE_FAMILY" if kind == "FAMILY" else "CANDIDATE_LIBRARY", "tags": list(m.tags), "meta": dict(m.meta),
                      "matched_strings": [{"id": k, "count": v} for k, v in sorted(seen.items())][:max_strings_per_rule], "distinct_markers": len(seen),
                      "basis": "YARA rule derived from corpus evidence (docs/CLAUDE_CODE_PROMPT §corpus priors); a marker match is never lineage proof"})
    cands.sort(key=lambda c: (-c["distinct_markers"], c["rule"]))
    return {"status": "OK", "rules": [f.name for f in files], "candidates": cands, "tool": f"yara-python {deps.check('yara').version}"}


__all__ = ["scan", "rules_dir"]
