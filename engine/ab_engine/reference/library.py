"""ADDENDUM B6 — reference library and knowledge hardening.

Entries are typed ``USER_ARTIFACT | KNOWN_SOURCE_FIXTURE | BLACK_BOX_REFERENCE | FRAMEWORK_REFERENCE |
DSP_REFERENCE``. Every entry records origin, source artifact, licence (when external), hash, analysis
version, evidence state, verification date and relationships, so the user can always answer
"where did AB learn this?" (:func:`provenance`). External fixture source stays isolated from user
recoveries (:func:`fixture_source_isolation`). Actions are explicit: intent is never assumed from
co-dropping two plugins (:func:`actions_for`).

The type of a job entry follows its ``usage_context`` (ADDENDUM C1) — interpretation only; no stage
reads it to decide what runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from ab_engine.jobs import db as jobs_db
from ab_engine.jobs.model import Job, normalize_context

ENTRY_TYPES = ("USER_ARTIFACT", "KNOWN_SOURCE_FIXTURE", "BLACK_BOX_REFERENCE", "FRAMEWORK_REFERENCE", "DSP_REFERENCE")
CONTEXT_TO_TYPE = {
    "USER_RECOVERY": "USER_ARTIFACT",
    "UNKNOWN_CONTEXT": "USER_ARTIFACT",
    "KNOWN_SOURCE_FIXTURE": "KNOWN_SOURCE_FIXTURE",
    "SOURCE_AVAILABLE_REFERENCE": "KNOWN_SOURCE_FIXTURE",
    "BLACK_BOX_REFERENCE": "BLACK_BOX_REFERENCE",
}
FRAMEWORK_KINDS = ("KNOWN_FRAMEWORK", "KNOWN_THIRD_PARTY", "KNOWN_SHARED_INTERNAL")
ACTIONS = {
    "COMPARE_AGAINST_REFERENCE": {"label": "Compare Against Reference", "rpc": "lineage.report", "needs": "another entry with a recovery project"},
    "ADD_AS_FIXTURE": {"label": "Add as Fixture", "rpc": "reference.set_context", "needs": "usage_context KNOWN_SOURCE_FIXTURE and the fixture's source"},
    "USE_AS_BLACK_BOX_REFERENCE": {"label": "Use as Black-Box Reference", "rpc": "reference.set_context", "needs": "usage_context BLACK_BOX_REFERENCE"},
    "VALIDATE_RECOVERY_AGAINST_SOURCE": {"label": "Validate Recovery Against Source", "rpc": "groundtruth.compare", "needs": "truth.json generated from the fixture source"},
}
RULE = "intent is never inferred from a co-drop: every reference action is explicit; entries record origin, source artifact, licence, hash, analysis version, evidence state, verification date and relationships (ADDENDUM B6)"


# ---------------------------------------------------------------- helpers
def _load(p: Path) -> Any:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("data", d) if isinstance(d, dict) else d
    except (OSError, ValueError):
        return None


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def reference_package_dir() -> Path:
    override = os.environ.get("AB_REFERENCE_DIR")
    return Path(override) if override else repo_root() / "reference" / "music_reference_corpus_21"


def fixture_dirs() -> list[Path]:
    override = os.environ.get("AB_FIXTURE_DIRS")
    if override:
        return [Path(x) for x in override.split(os.pathsep) if x]
    fx = repo_root() / "fixtures"
    return [p for p in (fx / "groundtruth", fx / "groundtruth_unseen", fx / "groundtruth_iplug2") if p.is_dir()]


def load_fixture_manifests(dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    out = []
    for d in dirs if dirs is not None else fixture_dirs():
        m = _load(d / "fixture.json")
        if isinstance(m, dict):
            out.append({**m, "_dir": str(d)})
    return out


def _fixture_for(sha256: str, manifests: list[dict[str, Any]]) -> dict[str, Any] | None:
    for m in manifests:
        hashes = m.get("binary_sha256") or {}
        variants = hashes.values() if isinstance(hashes, dict) else [hashes]
        if sha256 in variants:
            return m
    return None


# ---------------------------------------------------------------- job entries
def _knowledge_learned(conn: sqlite3.Connection | None, sha256: str) -> dict[str, int]:
    if conn is None:
        return {}
    like = f'%"{sha256}"%'
    try:
        return {
            "functions": int(conn.execute("SELECT count(*) FROM function_occurrence WHERE artifact_sha256=?", (sha256,)).fetchone()[0]),
            "classes": int(conn.execute("SELECT count(*) FROM class WHERE source_hashes LIKE ?", (like,)).fetchone()[0]),
            "vtable_layouts": int(conn.execute("SELECT count(*) FROM vtable_layout WHERE source_hashes LIKE ?", (like,)).fetchone()[0]),
            "implementations": int(conn.execute("SELECT count(*) FROM implementation WHERE source_hashes LIKE ?", (like,)).fetchone()[0]),
            "behaviours": int(conn.execute("SELECT count(*) FROM behavior WHERE artifact_sha256=?", (sha256,)).fetchone()[0]),
        }
    except sqlite3.Error:
        return {}


def job_entry(job: Job, *, manifests: list[dict[str, Any]] | None = None, kconn: sqlite3.Connection | None = None) -> dict[str, Any]:
    pd = Path(job.project_dir)
    manifests = manifests if manifests is not None else load_fixture_manifests()
    entry_type = CONTEXT_TO_TYPE.get(job.usage_context, "USER_ARTIFACT")
    stages = {s.stage: s.status for s in job.stages}
    ended = [s.ended for s in job.stages if s.ended and s.status == "OK"]
    tools: dict[str, str] = {}
    for s in job.stages:
        tools.update(s.tool_versions or {})
    manifest = _load(pd / "00_manifest" / "input_manifest.json") or {}
    rels = manifest.get("relationships") or []
    fx = _fixture_for(job.artifact_sha256, manifests)
    entry: dict[str, Any] = {
        "entry_type": entry_type, "id": job.job_id, "name": job.name, "usage_context": job.usage_context, "source_availability": job.source_availability,
        "origin": "ingested by the user" if entry_type == "USER_ARTIFACT" else f"ingested as {job.usage_context}",
        "source_artifact": {"sha256": job.artifact_sha256, "path": job.primary, "inputs": len(manifest.get("inputs") or [])},
        "hash": job.artifact_sha256, "license": None, "analysis_version": tools, "evidence_state": stages,
        "verification_date": max(ended) if ended else None, "created": job.created,
        "relationships": [{"kind": r.get("kind"), "a": r.get("a"), "b": r.get("b"), "confidence": r.get("confidence")} for r in rels[:50]],
        "knowledge_learned": _knowledge_learned(kconn, job.artifact_sha256),
        "project_dir": job.project_dir,
    }
    if entry_type == "USER_ARTIFACT":
        entry["license"] = {"class": "USER_OWNED_OR_UNSTATED", "text": "the user's own artifact; no external licence recorded"}
    if fx is not None:
        entry["fixture"] = {"fixture_id": fx.get("fixture_id"), "source_type": fx.get("source_type"), "source_repository": fx.get("source_repository"),
                            "source_commit": fx.get("source_commit"), "build_configuration": fx.get("build_configuration"), "compiler": fx.get("compiler"),
                            "variant": next((k for k, v in (fx.get("binary_sha256") or {}).items() if v == job.artifact_sha256), None),
                            "algorithms": fx.get("algorithms") or fx.get("dsp") or [], "source_dir": str(Path(fx["_dir"]) / "Source")}
        entry["license"] = {"class": fx.get("license_class"), "text": fx.get("license")}
    elif entry_type == "KNOWN_SOURCE_FIXTURE":
        entry["fixture"] = {"fixture_id": None, "note": "declared a known-source fixture; no fixture manifest names this binary hash — Validate Recovery Against Source needs truth.json from its source"}
    ks = _load(pd / "06_validation" / "known_source_metrics.json")
    gt = _load(pd / "06_validation" / "GROUND_TRUTH_REPORT.json")
    diff = _load(pd / "06_validation" / "differential_results.json")
    entry["verification"] = {
        "known_source": None if not ks else {"integrity_ok": (ks.get("integrity") or {}).get("ok"), "failure_classes": ks.get("failure_classes")},
        "ground_truth": None if not gt else {"gates_ok": sum(1 for g in gt.get("gates", []) if g.get("ok") is True), "gates": len(gt.get("gates", [])), "false_positives": len(gt.get("false_positives") or []), "false_negatives": len(gt.get("false_negatives") or [])},
        "behavioral": None if not diff else {m.get("module"): m.get("classification") for m in diff.get("modules", [])},
    }
    return entry


# ---------------------------------------------------------------- reference package (DSP_REFERENCE)
def dsp_reference_entries(pkg: Path | None = None) -> list[dict[str, Any]]:
    pkg = pkg or reference_package_dir()
    manifest = _load(pkg / "catalog" / "reference_manifest.json") or {}
    comps = _load(pkg / "catalog" / "reference_components.json") or []
    symbols = _load(pkg / "catalog" / "observed_symbols.json") or []
    if not comps:
        return []
    lic_file = pkg / "LICENSE"
    lic_text = lic_file.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip() if lic_file.is_file() else None
    by_comp: dict[str, int] = {}
    for s in symbols:
        c = s.get("reference_component")
        if c:
            by_comp[c] = by_comp.get(c, 0) + 1
    out = []
    for c in comps:
        f = pkg / "include" / "musicref" / str(c.get("file") or "")
        out.append({
            "entry_type": "DSP_REFERENCE", "id": f"dsp:{c.get('component')}", "name": c.get("component"), "purpose": c.get("purpose"),
            "origin": f"clean-room reference package {manifest.get('package', pkg.name)} v{manifest.get('version', '?')} — {manifest.get('code_provenance', '')}".strip(),
            "source_artifact": {"path": str(f.relative_to(pkg)) if f.is_file() else c.get("file"), "package": str(pkg)},
            "hash": _sha(f) if f.is_file() else None, "license": {"class": "EXTERNAL", "text": lic_text},
            "analysis_version": {"package": manifest.get("version")}, "evidence_state": "CANDIDATE",
            "verification_date": None, "relationships": [{"kind": "OBSERVED_SYMBOL_HYPOTHESIS", "count": by_comp.get(c.get("component"), 0)}],
            "rule": "candidate code and vocabulary only; a mapping is never proof that a vendor class used it (REFERENCE_NOTICE.md)",
        })
    return out


# ---------------------------------------------------------------- knowledge (FRAMEWORK_REFERENCE, shared implementations)
def framework_entries(kconn: sqlite3.Connection | None) -> list[dict[str, Any]]:
    if kconn is None:
        return []
    out = []
    try:
        for kind in FRAMEWORK_KINDS:
            rows = kconn.execute("SELECT state, count(*) AS c, min(first_seen) AS fs, max(last_verified) AS lv FROM function WHERE kind=? GROUP BY state", (kind,)).fetchall()
            if not rows:
                continue
            arts = kconn.execute("SELECT DISTINCT a.sha256, a.name, a.ownership FROM function_occurrence o JOIN function f ON f.function_fp_id=o.function_fp_id "
                                 "JOIN artifact a ON a.sha256=o.artifact_sha256 WHERE f.kind=? LIMIT 50", (kind,)).fetchall()
            total = sum(int(r["c"]) for r in rows)
            out.append({
                "entry_type": "FRAMEWORK_REFERENCE", "id": f"fw:{kind}", "name": kind, "origin": "function fingerprints learned from analysed artifacts (keyed by fingerprint, never by name)",
                "source_artifact": [{"sha256": a["sha256"], "name": a["name"], "usage_context": a["ownership"]} for a in arts],
                "hash": None, "license": {"class": "THIRD_PARTY_SIGNATURES", "text": "signatures only; no third-party source is stored"},
                "analysis_version": {}, "evidence_state": {r["state"]: int(r["c"]) for r in rows}, "functions": total,
                "verification_date": max((r["lv"] for r in rows if r["lv"]), default=None), "first_seen": min((r["fs"] for r in rows if r["fs"]), default=None),
                "relationships": [{"kind": "LEARNED_FROM", "count": len(arts)}],
            })
        impls = kconn.execute("SELECT impl_id, name_hint, state, tier, family_id, first_seen, last_verified, source_hashes, behavior_ref FROM implementation").fetchall()
        for r in impls:
            hashes = json.loads(r["source_hashes"] or "[]")
            arts = [dict(a) for a in kconn.execute(f"SELECT sha256, name, ownership FROM artifact WHERE sha256 IN ({','.join('?' * len(hashes))})", hashes).fetchall()] if hashes else []
            out.append({
                "entry_type": "FRAMEWORK_REFERENCE", "kind": "SHARED_IMPLEMENTATION", "id": f"impl:{r['impl_id']}", "name": r["name_hint"] or r["impl_id"],
                "origin": f"implementation learned from {len(hashes)} artifact(s) — tier {r['tier']}",
                "source_artifact": [{"sha256": a["sha256"], "name": a["name"], "usage_context": a["ownership"]} for a in arts],
                "hash": r["impl_id"], "license": None, "analysis_version": {}, "evidence_state": r["state"], "tier": r["tier"], "family": r["family_id"],
                "verification_date": r["last_verified"], "first_seen": r["first_seen"], "behavior_ref": r["behavior_ref"],
                "relationships": [{"kind": "LEARNED_FROM", "count": len(hashes)}],
            })
    except sqlite3.Error:
        return out
    return out


# ---------------------------------------------------------------- provenance: "where did AB learn this?"
def provenance(kconn: sqlite3.Connection | None, query: str, *, limit: int = 20) -> dict[str, Any]:
    q = (query or "").strip()
    hits: list[dict[str, Any]] = []
    if not q or kconn is None:
        return {"query": q, "hits": hits, "rule": RULE}
    like = f"%{q}%"

    def artifacts(hashes: list[str]) -> list[dict[str, Any]]:
        if not hashes:
            return []
        rows = kconn.execute(f"SELECT sha256, name, ownership, first_seen FROM artifact WHERE sha256 IN ({','.join('?' * len(hashes))})", hashes).fetchall()
        return [{"sha256": r["sha256"], "name": r["name"], "usage_context": r["ownership"], "entry_type": CONTEXT_TO_TYPE.get(r["ownership"] or "", "USER_ARTIFACT"), "first_seen": r["first_seen"]} for r in rows]

    def history(entity_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in kconn.execute("SELECT previous, current, changed_at, reason, tool_version, evidence_version FROM classification_history WHERE entity_id=? ORDER BY id DESC LIMIT 20", (entity_id,)).fetchall()]

    try:
        for r in kconn.execute("SELECT * FROM function WHERE function_fp_id=? OR name_hint LIKE ? LIMIT ?", (q, like, limit)).fetchall():
            occ = kconn.execute("SELECT artifact_sha256, address, source FROM function_occurrence WHERE function_fp_id=?", (r["function_fp_id"],)).fetchall()
            hits.append({"entity_type": "function", "entity_id": r["function_fp_id"], "name": r["name_hint"], "kind": r["kind"], "state": r["state"], "role": r["role"],
                         "first_seen": r["first_seen"], "last_verified": r["last_verified"], "verifications": r["verifications"], "tool_version": r["tool_version"], "evidence_version": r["evidence_version"],
                         "learned_from": artifacts(sorted({o["artifact_sha256"] for o in occ})), "occurrences": [{"sha256": o["artifact_sha256"], "address": o["address"], "source": o["source"]} for o in occ],
                         "history": history(r["function_fp_id"])})
        for r in kconn.execute("SELECT * FROM class WHERE class_id=? OR rtti_name LIKE ? LIMIT ?", (q, like, limit)).fetchall():
            hashes = json.loads(r["source_hashes"] or "[]")
            hits.append({"entity_type": "class", "entity_id": r["class_id"], "name": r["rtti_name"], "kind": r["kind"], "state": r["state"], "first_seen": r["first_seen"], "last_verified": r["last_verified"],
                         "learned_from": artifacts(hashes), "history": history(r["class_id"])})
        for r in kconn.execute("SELECT * FROM vtable_layout WHERE layout_id=? OR rtti_name LIKE ? LIMIT ?", (q, like, limit)).fetchall():
            hashes = json.loads(r["source_hashes"] or "[]")
            hits.append({"entity_type": "vtable_layout", "entity_id": r["layout_id"], "name": r["rtti_name"], "slot_count": r["slot_count"], "state": r["state"], "first_seen": r["first_seen"], "last_verified": r["last_verified"],
                         "verifications": r["verifications"], "tool_version": r["tool_version"], "evidence_version": r["evidence_version"], "learned_from": artifacts(hashes), "history": history(r["layout_id"])})
        for r in kconn.execute("SELECT * FROM implementation WHERE impl_id=? OR name_hint LIKE ? LIMIT ?", (q, like, limit)).fetchall():
            hashes = json.loads(r["source_hashes"] or "[]")
            hits.append({"entity_type": "implementation", "entity_id": r["impl_id"], "name": r["name_hint"], "state": r["state"], "tier": r["tier"], "family": r["family_id"], "behavior_ref": r["behavior_ref"],
                         "first_seen": r["first_seen"], "last_verified": r["last_verified"], "learned_from": artifacts(hashes), "history": history(r["impl_id"])})
    except sqlite3.Error as e:
        return {"query": q, "hits": hits, "error": str(e), "rule": RULE}
    fixture_derived = [h for h in hits if any(a["entry_type"] != "USER_ARTIFACT" for a in h["learned_from"])]
    return {"query": q, "hits": hits[:limit], "fixture_derived": len(fixture_derived), "rule": RULE}


# ---------------------------------------------------------------- isolation: fixture source never enters a user recovery
def fixture_source_isolation(jobs: list[Job], *, fixture_source_dirs: list[Path] | None = None, manifests: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    dirs = fixture_source_dirs if fixture_source_dirs is not None else [Path(m["_dir"]) / "Source" for m in (manifests if manifests is not None else load_fixture_manifests())]
    fixture_hashes: dict[str, str] = {}
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.rglob("*")):
                if f.is_file() and f.stat().st_size > 64:      # trivially small files (empty headers, blank lines) are not source
                    fixture_hashes.setdefault(_sha(f), str(f))
    violations = []
    checked = 0
    for j in jobs:
        if CONTEXT_TO_TYPE.get(j.usage_context, "USER_ARTIFACT") not in ("USER_ARTIFACT", "BLACK_BOX_REFERENCE"):
            continue
        rec = Path(j.project_dir) / "04_reconstruction"
        if not rec.is_dir():
            continue
        checked += 1
        for f in rec.rglob("*"):
            if f.is_file() and not any(part in ("build", "third_party") for part in f.relative_to(rec).parts):
                h = _sha(f)
                if h in fixture_hashes:
                    violations.append({"job_id": j.job_id, "file": str(f.relative_to(Path(j.project_dir))), "matches_fixture_file": fixture_hashes[h], "sha256": h})
    return {"ok": not violations, "checked_projects": checked, "fixture_files": len(fixture_hashes), "violations": violations,
            "rule": "external fixture source stays isolated from user recoveries: a user or black-box project never contains a byte-identical fixture source file"}


# ---------------------------------------------------------------- explicit actions
def actions_for(entry: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    t = entry.get("entry_type")
    others = [e for e in entries if e.get("project_dir") and e.get("id") != entry.get("id")]
    ids: list[str] = []
    if t == "USER_ARTIFACT":
        ids = (["COMPARE_AGAINST_REFERENCE"] if others else []) + ["ADD_AS_FIXTURE", "USE_AS_BLACK_BOX_REFERENCE"]
    elif t == "KNOWN_SOURCE_FIXTURE":
        ids = ["VALIDATE_RECOVERY_AGAINST_SOURCE"] + (["COMPARE_AGAINST_REFERENCE"] if others else [])
    elif t == "BLACK_BOX_REFERENCE":
        ids = ["COMPARE_AGAINST_REFERENCE"] if others else []
    return [{"id": i, **ACTIONS[i], "job_id": entry.get("id")} for i in ids]


# ---------------------------------------------------------------- ground-truth dashboard (counts, never one percentage)
def dashboard(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    m = report.get("metrics") or {}

    def nn(d: dict[str, Any] | None, num: str, den: str) -> dict[str, Any] | None:
        return None if not d else {"n": d.get(num), "of": d.get(den)}

    pb = m.get("process_block_path") or {}
    entry_points = None if not pb else {"n": sum(1 for k, v in pb.items() if k != "basis" and v), "of": sum(1 for k in pb if k != "basis")}
    idx_impls = [e for e in (m.get("implementations") or [])]
    wd = m.get("waveshaper_differential") or {}
    return {
        "parameter_recall": nn(m.get("parameters"), "found", "expected"),
        "state_mapping": nn(m.get("state_fields_mapped"), "correct", "expected"),
        "classes": nn(m.get("rtti_classes_recovered"), "recovered", "expected"),
        "dsp_entry_points": entry_points,
        "resources": nn(m.get("resources"), "valid_exact", "expected"),
        "implementation_matches_verified": len([i for i in idx_impls if str(i.get("state", "")) in ("BEHAVIOR_MATCHED", "IMPLEMENTATION_VERIFIED")]),
        "false_positives": len(report.get("false_positives") or []),
        "false_negatives": len(report.get("false_negatives") or []),
        "behavioral_rmse": wd.get("worst_rmse"),
        "behavioral_classification": wd.get("classification"),
        "gates": {"ok": sum(1 for g in report.get("gates", []) if g.get("ok") is True), "failed": sum(1 for g in report.get("gates", []) if g.get("ok") is False), "pending": sum(1 for g in report.get("gates", []) if g.get("ok") is None)},
        "rule": "counts, not one percentage",
    }


# ---------------------------------------------------------------- context change (Add as Fixture / Use as Black-Box Reference)
def set_context(conn: sqlite3.Connection, job: Job, usage_context: str | None, source_availability: str | None) -> dict[str, Any]:
    """Explicit, recorded re-typing of an entry. Interpretation only (C1): no stage output changes; the manifest keeps the history."""
    from ab_engine.contracts import write_json  # noqa: PLC0415

    new_ctx, new_src = normalize_context(usage_context or job.usage_context, source_availability or job.source_availability, None)
    before = job.context
    job.usage_context, job.source_availability = new_ctx, new_src
    jobs_db.upsert_job(conn, job)   # upsert_job owns its transaction
    from ab_engine.contracts import ContractError  # noqa: PLC0415

    mp = Path(job.project_dir) / "00_manifest" / "input_manifest.json"
    manifest = _load(mp)
    entry = {"from": before, "to": job.context, "at": _now(), "by": "reference.set_context"}
    recorded_in = None
    if isinstance(manifest, dict):
        hist = list(manifest.get("context_history") or []) + [entry]
        manifest.update({"usage_context": job.usage_context, "source_availability": job.source_availability, "interpretation": job.interpretation, "context_history": hist})
        manifest.setdefault("job_id", job.job_id)
        manifest.setdefault("name", job.name)
        try:
            write_json(mp, "artifactbench.input_manifest", manifest)
            recorded_in = "00_manifest/input_manifest.json"
        except ContractError:
            manifest = None       # a manifest from before the current contract: never rewritten into an invalid file
    if recorded_in is None:
        # the change is still recorded next to the manifest (older projects); the job row is authoritative either way
        side = mp.parent / "context_history.json"
        prev = _load(side) or {}
        write_json(side, "artifactbench.context_history", {"job_id": job.job_id, **job.context, "history": list(prev.get("history") or []) + [entry]})
        recorded_in = "00_manifest/context_history.json"
    return {"job_id": job.job_id, "before": before, "after": job.context, "entry_type": CONTEXT_TO_TYPE.get(job.usage_context, "USER_ARTIFACT"), "recorded_in": recorded_in}


def _now() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- the library
def build(jobs: list[Job], *, kconn: sqlite3.Connection | None, manifests: list[dict[str, Any]] | None = None, pkg: Path | None = None) -> dict[str, Any]:
    manifests = manifests if manifests is not None else load_fixture_manifests()
    entries = [job_entry(j, manifests=manifests, kconn=kconn) for j in jobs]
    entries += framework_entries(kconn)
    entries += dsp_reference_entries(pkg)
    for e in entries:
        e["actions"] = actions_for(e, entries)
    counts = {t: sum(1 for e in entries if e["entry_type"] == t) for t in ENTRY_TYPES}
    return {"entries": entries, "counts": counts, "types": list(ENTRY_TYPES), "isolation": fixture_source_isolation(jobs, manifests=manifests), "fixture_manifests": [{k: v for k, v in m.items() if k not in ("_dir",)} for m in manifests], "rule": RULE}


def to_markdown(lib: dict[str, Any]) -> str:
    lines = ["# REFERENCE_LIBRARY", "", lib["rule"], "", "| type | count |", "|---|---|"]
    lines += [f"| {t} | {n} |" for t, n in lib["counts"].items()]
    iso = lib["isolation"]
    lines += ["", f"Fixture-source isolation: **{'OK' if iso['ok'] else 'VIOLATED'}** — {iso['checked_projects']} user/black-box project(s) checked against {iso['fixture_files']} fixture source file(s)."]
    for v in iso["violations"]:
        lines.append(f"- {v['job_id']}: `{v['file']}` is byte-identical to `{v['matches_fixture_file']}`")
    lines += ["", "| entry | type | origin | licence | evidence | verified |", "|---|---|---|---|---|---|"]
    for e in lib["entries"]:
        lic = e.get("license") or {}
        ev = e.get("evidence_state")
        ev_s = ev if isinstance(ev, str) else (", ".join(f"{k}={v}" for k, v in (ev or {}).items())[:80] or "—")
        lines.append(f"| {e.get('name')} | {e['entry_type']} | {str(e.get('origin', ''))[:70]} | {lic.get('class') or '—'} | {ev_s} | {e.get('verification_date') or '—'} |")
    return "\n".join(lines) + "\n"


__all__ = ["ENTRY_TYPES", "CONTEXT_TO_TYPE", "ACTIONS", "RULE", "job_entry", "dsp_reference_entries", "framework_entries", "provenance", "fixture_source_isolation", "actions_for", "dashboard", "set_context", "build", "to_markdown", "load_fixture_manifests", "reference_package_dir", "fixture_dirs"]
