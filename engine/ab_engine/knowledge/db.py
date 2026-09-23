"""Cumulative, content-addressed, versioned knowledge base (EXECUTE_ADDENDUM_A §A2).

``<state>/knowledge/knowledge.db`` (SQLite) with the A2 tables; bytes live in the object store by
hash. Three rules the code enforces:

1. **Never mutate a classification in place.** ``set_state`` writes the new value *and* a
   ``classification_history`` row (previous, current, changed_at, tool_version, evidence_version,
   reason). Rows keep ``first_seen`` / ``last_verified``.
2. **Promotion ladder** CANDIDATE → STATIC_SUPPORTED → RUNTIME_SUPPORTED → BEHAVIOR_MATCHED →
   IMPLEMENTATION_VERIFIED. Only BEHAVIOR_MATCHED / IMPLEMENTATION_VERIFIED may be reused to skip
   analysis; CANDIDATE / STATIC_SUPPORTED may only prioritize. ``reusable()`` is the single gate.
3. **Provenance on every reuse decision.** ``match`` returns, per function, which signatures
   agreed (norm hash, CFG, constants, strings, callgraph, TLSH distance), in how many prior
   binaries the fingerprint occurred and how many behaviour confirmations its implementation has.
   A name is never a reason.

Library classification (KNOWN_FRAMEWORK / KNOWN_THIRD_PARTY / KNOWN_SHARED_INTERNAL /
KNOWN_PLUGIN_SPECIFIC / UNKNOWN) lives on the ``function`` row as ``kind``; the ladder state lives
in ``state``. A contradiction (same norm hash, different constants / strings / callgraph / RTTI)
downgrades the match to ``near_match`` and appends the reason to the history.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LADDER = ("CANDIDATE", "STATIC_SUPPORTED", "RUNTIME_SUPPORTED", "BEHAVIOR_MATCHED", "IMPLEMENTATION_VERIFIED")
KINDS = ("KNOWN_FRAMEWORK", "KNOWN_THIRD_PARTY", "KNOWN_SHARED_INTERNAL", "KNOWN_PLUGIN_SPECIFIC", "UNKNOWN")
REUSABLE = ("BEHAVIOR_MATCHED", "IMPLEMENTATION_VERIFIED")
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS artifact (sha256 TEXT PRIMARY KEY, kind TEXT, size INTEGER, first_seen TEXT, last_seen TEXT, ownership TEXT, compiler_fingerprint TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS analysis_run (run_id TEXT PRIMARY KEY, artifact_sha256 TEXT, stage TEXT, tool_versions TEXT, stage_version INTEGER, config_hash TEXT, started TEXT, ended TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS plugin_identity (artifact_sha256 TEXT PRIMARY KEY, vendor TEXT, product TEXT, version TEXT, processor_fuid TEXT, controller_fuid TEXT, status TEXT, first_seen TEXT, last_verified TEXT);
CREATE TABLE IF NOT EXISTS class (class_id TEXT PRIMARY KEY, rtti_name TEXT, vtable_fingerprint TEXT, ctor_fp TEXT, dtor_fp TEXT, kind TEXT, state TEXT, first_seen TEXT, last_verified TEXT, source_hashes TEXT);
CREATE TABLE IF NOT EXISTS vtable (class_id TEXT, slot INTEGER, function_fp TEXT, PRIMARY KEY (class_id, slot));
CREATE TABLE IF NOT EXISTS function (function_fp_id TEXT PRIMARY KEY, raw_sha256 TEXT, norm_sha256 TEXT, tlsh TEXT, cfg_sig TEXT, callgraph_sig TEXT, const_sig TEXT, strxref_sig TEXT, length INTEGER, role TEXT, role_status TEXT, kind TEXT, state TEXT, name_hint TEXT, first_seen TEXT, last_verified TEXT, tool_version TEXT, evidence_version TEXT, verifications INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_function_norm ON function(norm_sha256);
CREATE INDEX IF NOT EXISTS idx_function_cfg ON function(cfg_sig);
CREATE TABLE IF NOT EXISTS function_occurrence (function_fp_id TEXT, artifact_sha256 TEXT, address TEXT, source TEXT, PRIMARY KEY (function_fp_id, artifact_sha256, address));
CREATE TABLE IF NOT EXISTS implementation (impl_id TEXT PRIMARY KEY, name_hint TEXT, member_fp_ids TEXT, family_id TEXT, state TEXT, behavior_ref TEXT, first_seen TEXT, last_verified TEXT, source_hashes TEXT, tier TEXT DEFAULT 'RECOVERED_IMPLEMENTATION_KNOWLEDGE');
CREATE TABLE IF NOT EXISTS family (family_id TEXT PRIMARY KEY, label TEXT, method TEXT, state TEXT, first_seen TEXT);
CREATE TABLE IF NOT EXISTS resource (sha256 TEXT PRIMARY KEY, ext TEXT, dims TEXT, binarydata_name TEXT, mapping_status TEXT, first_seen TEXT, source_hashes TEXT);
CREATE TABLE IF NOT EXISTS parameter (artifact_sha256 TEXT, param_id INTEGER, title TEXT, units TEXT, step_count INTEGER, default_norm REAL, flags INTEGER, tier TEXT, PRIMARY KEY (artifact_sha256, param_id));
CREATE TABLE IF NOT EXISTS state_field (artifact_sha256 TEXT, key TEXT, representation TEXT, mapped_param_id INTEGER, relation TEXT, PRIMARY KEY (artifact_sha256, key));
CREATE TABLE IF NOT EXISTS behavior (behavior_id TEXT PRIMARY KEY, impl_id TEXT, probe_set_hash TEXT, metrics_ref TEXT, result_state TEXT, artifact_sha256 TEXT, recorded TEXT);
CREATE TABLE IF NOT EXISTS reconstruction (impl_id TEXT PRIMARY KEY, evidence_source_ref TEXT, human_source_ref TEXT, validation_state TEXT, rmse REAL, recorded TEXT);
CREATE TABLE IF NOT EXISTS vtable_layout (layout_id TEXT PRIMARY KEY, rtti_name TEXT, slot_count INTEGER, slots TEXT, state TEXT, first_seen TEXT, last_verified TEXT, source_hashes TEXT, verifications INTEGER DEFAULT 1, tool_version TEXT, evidence_version TEXT);
CREATE TABLE IF NOT EXISTS classification_history (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT, entity_id TEXT, previous TEXT, current TEXT, changed_at TEXT, tool_version TEXT, evidence_version TEXT, reason TEXT);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def fp_id(fp: dict[str, Any]) -> str:
    """Identity of a function fingerprint: normalized instruction hash + CFG hash (never a name)."""
    return hashlib.sha256(f"{fp.get('NORMALIZED_INSTRUCTION_HASH', '')}|{(fp.get('CFG_SIGNATURE') or {}).get('hash', '')}".encode()).hexdigest()


def const_sig(fp: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(fp.get("CONSTANT_SIGNATURE", []), sort_keys=True, default=str).encode()).hexdigest()


def _tlsh_diff(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    try:
        import tlsh  # noqa: PLC0415

        return int(tlsh.diff(a, b))
    except Exception:  # noqa: BLE001
        return None


class KnowledgeDB:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.root / "knowledge.db"), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        found = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if found is not None and int(found["value"]) > SCHEMA_VERSION:   # never reinterpret a newer schema (ADDENDUM B7 migration rule)
            self.db.close()
            raise RuntimeError(f"knowledge.db schema {found['value']} is newer than this engine ({SCHEMA_VERSION}); refusing to reinterpret")
        if found is not None and int(found["value"]) < SCHEMA_VERSION:   # older database: migrate in place, keep every row
            self.db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
        # ADDENDUM C3 tiers on databases created before them (old evidence never discarded)
        if "tier" not in {r[1] for r in self.db.execute("PRAGMA table_info(implementation)")}:
            self.db.execute("ALTER TABLE implementation ADD COLUMN tier TEXT DEFAULT 'RECOVERED_IMPLEMENTATION_KNOWLEDGE'")

    # ---- history / states ----------------------------------------------------------------
    def history(self, entity_type: str, entity_id: str, previous: str | None, current: str, reason: str, *, tool_version: str = "", evidence_version: str = "") -> None:
        self.db.execute("INSERT INTO classification_history (entity_type, entity_id, previous, current, changed_at, tool_version, evidence_version, reason) VALUES (?,?,?,?,?,?,?,?)",
                        (entity_type, entity_id, previous, current, _now(), tool_version, evidence_version, reason))

    def set_state(self, table: str, key_col: str, key: str, new_state: str, reason: str, *, tool_version: str = "", evidence_version: str = "") -> bool:
        """Change ``state`` with a history row; never silently. Returns True when something changed."""
        row = self.db.execute(f"SELECT state FROM {table} WHERE {key_col}=?", (key,)).fetchone()
        if row is None:
            return False
        if row["state"] == new_state:
            return False
        self.db.execute(f"UPDATE {table} SET state=?, last_verified=? WHERE {key_col}=?", (new_state, _now(), key))
        self.history(table, key, row["state"], new_state, reason, tool_version=tool_version, evidence_version=evidence_version)
        return True

    @staticmethod
    def reusable(state: str | None) -> bool:
        return state in REUSABLE

    @staticmethod
    def promote_allowed(current: str, target: str) -> bool:
        return target in LADDER and (current not in LADDER or LADDER.index(target) >= LADDER.index(current))

    # ---- artifacts / runs / identity ----------------------------------------------------------
    def record_artifact(self, sha256: str, *, kind: str, size: int, ownership: str, name: str, compiler_fingerprint: str | None = None) -> None:
        """``ownership`` carries the usage_context since D-026 (column name kept for existing databases)."""
        row = self.db.execute("SELECT sha256 FROM artifact WHERE sha256=?", (sha256,)).fetchone()
        if row:
            self.db.execute("UPDATE artifact SET last_seen=?, name=COALESCE(name, ?) WHERE sha256=?", (_now(), name, sha256))
        else:
            self.db.execute("INSERT INTO artifact VALUES (?,?,?,?,?,?,?,?)", (sha256, kind, size, _now(), _now(), ownership, compiler_fingerprint, name))

    def record_run(self, run_id: str, artifact_sha256: str, stage: str, *, tool_versions: dict[str, str], stage_version: int, config_hash: str, started: str, ended: str, status: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO analysis_run VALUES (?,?,?,?,?,?,?,?,?)",
                        (run_id, artifact_sha256, stage, json.dumps(tool_versions, sort_keys=True), stage_version, config_hash, started, ended, status))

    def record_identity(self, artifact_sha256: str, ident: dict[str, Any]) -> None:
        prev = self.db.execute("SELECT status FROM plugin_identity WHERE artifact_sha256=?", (artifact_sha256,)).fetchone()
        status = ident.get("evidence") or "UNVERIFIED"
        self.db.execute("INSERT OR REPLACE INTO plugin_identity VALUES (?,?,?,?,?,?,?,COALESCE((SELECT first_seen FROM plugin_identity WHERE artifact_sha256=?),?),?)",
                        (artifact_sha256, ident.get("vendor"), ident.get("product"), ident.get("version"), ident.get("processor_fuid"), ident.get("controller_fuid"), status, artifact_sha256, _now(), _now()))
        if prev and prev["status"] != status:
            self.history("plugin_identity", artifact_sha256, prev["status"], status, "identity re-verified by the runtime stage")

    def record_parameters(self, artifact_sha256: str, params: list[dict[str, Any]], tiers: list[dict[str, Any]]) -> int:
        n = 0
        tier_of = {int(t["param_id"]): t.get("tier") for t in tiers if t.get("param_id") is not None}
        for p in params:
            self.db.execute("INSERT OR REPLACE INTO parameter VALUES (?,?,?,?,?,?,?,?)",
                            (artifact_sha256, int(p["param_id"]), p.get("title"), p.get("units"), int(p.get("step_count") or 0), float(p.get("default_normalized") or 0.0), int(p.get("flags") or 0), tier_of.get(int(p["param_id"]), "VST3_EXPORTED_PARAMETER")))
            n += 1
        for t in tiers:
            if t.get("key"):
                self.db.execute("INSERT OR REPLACE INTO state_field VALUES (?,?,?,?,?)", (artifact_sha256, t["key"], t.get("value_representation", "UNKNOWN"), t.get("param_id"), t.get("relationship")))
        return n

    def record_resources(self, artifact_sha256: str, rows: list[dict[str, Any]]) -> int:
        n = 0
        for r in rows:
            if not r.get("sha256"):
                continue
            prev = self.db.execute("SELECT source_hashes, binarydata_name FROM resource WHERE sha256=?", (r["sha256"],)).fetchone()
            hashes = set(json.loads(prev["source_hashes"])) if prev else set()
            hashes.add(artifact_sha256)
            self.db.execute("INSERT OR REPLACE INTO resource VALUES (?,?,?,?,?,COALESCE((SELECT first_seen FROM resource WHERE sha256=?),?),?)",
                            (r["sha256"], r.get("ext"), json.dumps(r.get("dims")) if r.get("dims") else None, r.get("candidate_name") or (prev["binarydata_name"] if prev else None),
                             r.get("mapping_status") or r.get("status"), r["sha256"], _now(), json.dumps(sorted(hashes))))
            n += 1
        return n

    # ---- functions --------------------------------------------------------------------------
    def record_functions(self, artifact_sha256: str, fps: list[dict[str, Any]], *, source: str, tool_version: str, evidence_version: str,
                         kind_of=None, role_of=None, min_size: int = 32) -> dict[str, int]:
        """Insert/refresh function rows and occurrences. New rows start at CANDIDATE with the kind the
        caller derives from evidence (framework namespace, cache, …); nothing is guessed here."""
        new = seen = 0
        now = _now()
        for fp in fps:
            if int(fp.get("size", 0)) < min_size or not fp.get("NORMALIZED_INSTRUCTION_HASH"):
                continue
            fid = fp_id(fp)
            row = self.db.execute("SELECT function_fp_id, kind, state FROM function WHERE function_fp_id=?", (fid,)).fetchone()
            kind = (kind_of(fp) if kind_of else None) or "UNKNOWN"
            role = (role_of(fp) if role_of else None)
            if row:
                # a real name always beats a decompiler label, whatever order the builds were analysed in
                self.db.execute("UPDATE function SET last_verified=?, verifications=verifications+1, "
                                "name_hint=CASE WHEN (name_hint IS NULL OR name_hint LIKE 'FUN_%' OR name_hint LIKE 'thunk_FUN_%' OR name_hint LIKE 'switchD_%') AND ? IS NOT NULL AND ? NOT LIKE 'FUN_%' AND ? NOT LIKE 'thunk_FUN_%' THEN ? ELSE name_hint END, "
                                "role=COALESCE(?, role) WHERE function_fp_id=?", (now, fp.get("name"), fp.get("name"), fp.get("name"), fp.get("name"), role, fid))
                if row["kind"] == "UNKNOWN" and kind != "UNKNOWN":
                    self.db.execute("UPDATE function SET kind=? WHERE function_fp_id=?", (kind, fid))
                    self.history("function.kind", fid, "UNKNOWN", kind, f"kind learned from {source} in {artifact_sha256[:12]}", tool_version=tool_version, evidence_version=evidence_version)
                seen += 1
            else:
                self.db.execute("INSERT INTO function VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                                (fid, fp.get("RAW_BYTE_HASH"), fp.get("NORMALIZED_INSTRUCTION_HASH"), fp.get("TLSH"), (fp.get("CFG_SIGNATURE") or {}).get("hash", ""),
                                 fp.get("CALLGRAPH_SIGNATURE", ""), const_sig(fp), fp.get("STRING_XREF_SIGNATURE", ""), int(fp.get("size", 0)), role, "CANDIDATE" if role else None,
                                 kind, "CANDIDATE", fp.get("name"), now, now, tool_version, evidence_version))
                new += 1
            self.db.execute("INSERT OR IGNORE INTO function_occurrence VALUES (?,?,?,?)", (fid, artifact_sha256, fp.get("addr"), source))
        return {"new": new, "seen": seen}

    def record_classes(self, artifact_sha256: str, classes: list[dict[str, Any]]) -> int:
        n = 0
        for c in classes:
            name = c.get("name") or c.get("recovered_name")
            if not name:
                continue
            vt = hashlib.sha256(json.dumps({"slots": c.get("slot_counts"), "methods": c.get("methods", [])[:64]}, sort_keys=True).encode()).hexdigest()
            cid = hashlib.sha256(f"{name}|{vt}".encode()).hexdigest()
            prev = self.db.execute("SELECT source_hashes FROM class WHERE class_id=?", (cid,)).fetchone()
            hashes = set(json.loads(prev["source_hashes"])) if prev else set()
            hashes.add(artifact_sha256)
            state = "STATIC_SUPPORTED" if c.get("structure_status") == "VERIFIED_VTABLE" else "CANDIDATE"
            self.db.execute("INSERT OR REPLACE INTO class VALUES (?,?,?,?,?,?,?,COALESCE((SELECT first_seen FROM class WHERE class_id=?),?),?,?)",
                            (cid, name, vt, None, None, c.get("kind"), state, cid, _now(), _now(), json.dumps(sorted(hashes))))
            for i, m in enumerate(c.get("methods", [])[:256]):
                self.db.execute("INSERT OR REPLACE INTO vtable VALUES (?,?,?)", (cid, i, str(m)))
            n += 1
        return n

    # ---- vtable layouts (slot -> method name), learned from symbol builds only ------------------
    def record_vtable_layouts(self, artifact_sha256: str, rows: list[dict[str, Any]], *, tool_version: str = "", evidence_version: str = "") -> int:
        """``rows`` come from :func:`ab_engine.knowledge.vtable_layout.learn_rows`. A layout is keyed by the
        RTTI name and slot count; every slot carries the method's leaf name and the fingerprint ids observed
        for the function in that slot. A second symbol build that names a slot differently blanks that
        slot's name with a history row (never silently overwritten); fingerprints accumulate (max 8)."""
        n = 0
        for r in rows:
            lid = hashlib.sha256(f"{r['rtti_name']}|{r['slot_count']}".encode()).hexdigest()[:32]
            prev = self.db.execute("SELECT slots, source_hashes, verifications FROM vtable_layout WHERE layout_id=?", (lid,)).fetchone()
            slots = [dict(e) for e in r["slots"]]
            hashes = {artifact_sha256}
            ver = 1
            if prev:
                old = {e["slot"]: e for e in json.loads(prev["slots"])}
                hashes |= set(json.loads(prev["source_hashes"]))
                ver = int(prev["verifications"]) + (0 if artifact_sha256 in set(json.loads(prev["source_hashes"])) else 1)
                for e in slots:
                    o = old.get(e["slot"])
                    if not o:
                        continue
                    if o.get("name") and e.get("name") and o["name"] != e["name"]:
                        self.history("vtable_layout", lid, o["name"], "", f"slot {e['slot']} named {o['name']!r} before and {e['name']!r} in {artifact_sha256[:12]}: name blanked",
                                     tool_version=tool_version, evidence_version=evidence_version)
                        e["name"] = ""
                    elif not e.get("name"):
                        e["name"] = o.get("name", "")
                    fps = list(dict.fromkeys(list(o.get("fps", [])) + list(e.get("fps", []))))
                    e["fps"] = fps[:8]
            self.db.execute("INSERT OR REPLACE INTO vtable_layout VALUES (?,?,?,?,?,COALESCE((SELECT first_seen FROM vtable_layout WHERE layout_id=?),?),?,?,?,?,?)",
                            (lid, r["rtti_name"], int(r["slot_count"]), json.dumps(slots), "STATIC_SUPPORTED", lid, _now(), _now(), json.dumps(sorted(hashes)), ver, tool_version, evidence_version))
            n += 1
        return n

    def layouts_for(self, rtti_names: list[str]) -> list[dict[str, Any]]:
        if not rtti_names:
            return []
        q = ",".join("?" * len(rtti_names))
        rows = self.db.execute(f"SELECT * FROM vtable_layout WHERE rtti_name IN ({q})", tuple(rtti_names)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["slots"] = json.loads(d["slots"])
            d["source_hashes"] = json.loads(d["source_hashes"])
            out.append(d)
        return out

    # ---- matching with provenance ----------------------------------------------------------
    def match(self, fp: dict[str, Any], *, artifact_sha256: str | None = None) -> dict[str, Any]:
        fid = fp_id(fp)
        row = self.db.execute("SELECT * FROM function WHERE function_fp_id=?", (fid,)).fetchone()
        exact = row is not None
        if not exact:
            # near match: same CFG shape + constants, or same normalized stream with a different CFG hash
            cand = self.db.execute("SELECT * FROM function WHERE norm_sha256=? OR (cfg_sig=? AND const_sig=?) LIMIT 8",
                                   (fp.get("NORMALIZED_INSTRUCTION_HASH", ""), (fp.get("CFG_SIGNATURE") or {}).get("hash", ""), const_sig(fp))).fetchall()
            row = cand[0] if cand else None
        if row is None:
            return {"state": "UNKNOWN", "matched": False, "verdict": "unknown", "fp_id": fid}
        agree, disagree = [], []
        for label, mine, theirs in (("NORMALIZED_INSTRUCTION_HASH", fp.get("NORMALIZED_INSTRUCTION_HASH", ""), row["norm_sha256"]),
                                    ("CFG_SIGNATURE", (fp.get("CFG_SIGNATURE") or {}).get("hash", ""), row["cfg_sig"]),
                                    ("CONSTANT_SIGNATURE", const_sig(fp), row["const_sig"]),
                                    ("STRING_XREF_SIGNATURE", fp.get("STRING_XREF_SIGNATURE", ""), row["strxref_sig"]),
                                    ("CALLGRAPH_SIGNATURE", fp.get("CALLGRAPH_SIGNATURE", ""), row["callgraph_sig"])):
            if not mine or not theirs:
                continue
            (agree if mine == theirs else disagree).append(label)
        tl = _tlsh_diff(fp.get("TLSH"), row["tlsh"])
        prior = self.db.execute("SELECT COUNT(DISTINCT artifact_sha256) AS n FROM function_occurrence WHERE function_fp_id=? AND artifact_sha256<>?", (row["function_fp_id"], artifact_sha256 or "")).fetchone()["n"]
        impl = self.db.execute("SELECT impl_id, state FROM implementation WHERE member_fp_ids LIKE ?", (f"%{row['function_fp_id']}%",)).fetchone()
        confirmations = self.db.execute("SELECT COUNT(*) AS n FROM behavior WHERE impl_id=? AND result_state IN ('BIT_EXACT','NUMERICALLY_EQUIVALENT','BEHAVIORALLY_EQUIVALENT')", (impl["impl_id"],)).fetchone()["n"] if impl else 0
        contradiction = bool(exact and disagree)
        verdict = "near_match" if (not exact or contradiction) else "known"
        state = row["state"]
        if contradiction:
            self.history("function", row["function_fp_id"], state, "CANDIDATE", f"contradiction in {artifact_sha256[:12] if artifact_sha256 else 'new artifact'}: {', '.join(disagree)} differ for an identical normalized stream")
            self.db.execute("UPDATE function SET state='CANDIDATE', last_verified=? WHERE function_fp_id=? AND state<>'CANDIDATE'", (_now(), row["function_fp_id"]))
        return {"state": "CANDIDATE" if contradiction else state, "kind": row["kind"], "matched": True, "verdict": verdict, "fp_id": row["function_fp_id"],
                "agree": agree, "disagree": disagree, "tlsh_distance": tl, "prior_binaries": prior, "behavior_confirmations": confirmations,
                "implementation": impl["impl_id"] if impl else None, "implementation_state": impl["state"] if impl else None,
                "reusable": self.reusable(impl["state"] if impl else None) and not contradiction and verdict == "known",
                "name_hint": row["name_hint"], "role": row["role"]}

    def match_all(self, fps: list[dict[str, Any]], *, artifact_sha256: str | None = None, reachable: set[str] | None = None) -> dict[str, Any]:
        results: dict[str, dict[str, Any]] = {}
        counts = {"known": 0, "near_match": 0, "unknown": 0}
        by_bytes = {"known": 0, "near_match": 0, "unknown": 0}
        kinds: dict[str, int] = {}
        for fp in fps:
            if int(fp.get("size", 0)) < 32:
                continue
            r = self.match(fp, artifact_sha256=artifact_sha256)
            results[fp["addr"]] = r
            counts[r["verdict"]] += 1
            by_bytes[r["verdict"]] += int(fp.get("size", 0))
            k = r.get("kind") or "UNKNOWN"
            kinds[k] = kinds.get(k, 0) + 1
        total = max(1, sum(counts.values()))
        tb = max(1, sum(by_bytes.values()))
        delta = {"known_implementation_pct": round(100 * counts["known"] / total, 1), "near_match_pct": round(100 * counts["near_match"] / total, 1), "unknown_pct": round(100 * counts["unknown"] / total, 1),
                 "by_bytes": {k: round(100 * v / tb, 1) for k, v in by_bytes.items()}, "functions": total}
        if reachable:
            rc = {"known": 0, "near_match": 0, "unknown": 0}
            for a in reachable:
                if a in results:
                    rc[results[a]["verdict"]] += 1
            rt = max(1, sum(rc.values()))
            delta["processBlock_reachable"] = {k: round(100 * v / rt, 1) for k, v in rc.items()} | {"functions": rt}
        reusable = sum(1 for r in results.values() if r.get("reusable"))
        suppress = sum(1 for r in results.values() if r["verdict"] == "known" and r.get("kind") in ("KNOWN_FRAMEWORK", "KNOWN_THIRD_PARTY"))
        return {"results": results, "counts": counts, "kinds": kinds, "delta": delta, "reusable": reusable, "suppressed_deep_work": suppress,
                "deep_analysis_first": [a for a, r in results.items() if r["verdict"] == "unknown"][:500]}

    # ---- implementations / behaviour / reconstruction (promotion) ------------------------------
    def record_implementation(self, impl_id: str, *, name_hint: str, member_fp_ids: list[str], artifact_sha256: str, state: str, behavior_ref: str | None = None,
                              tool_version: str = "", evidence_version: str = "", tier: str = "RECOVERED_IMPLEMENTATION_KNOWLEDGE") -> None:
        prev = self.db.execute("SELECT state, source_hashes FROM implementation WHERE impl_id=?", (impl_id,)).fetchone()
        hashes = set(json.loads(prev["source_hashes"])) if prev else set()
        hashes.add(artifact_sha256)
        if prev is None:
            self.db.execute("INSERT INTO implementation (impl_id, name_hint, member_fp_ids, family_id, state, behavior_ref, first_seen, last_verified, source_hashes, tier) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (impl_id, name_hint, json.dumps(member_fp_ids), None, state, behavior_ref, _now(), _now(), json.dumps(sorted(hashes)), tier))
            self.history("implementation", impl_id, None, state, f"first recorded from {artifact_sha256[:12]}", tool_version=tool_version, evidence_version=evidence_version)
        else:
            self.db.execute("UPDATE implementation SET member_fp_ids=?, behavior_ref=COALESCE(?, behavior_ref), last_verified=?, source_hashes=? WHERE impl_id=?",
                            (json.dumps(member_fp_ids), behavior_ref, _now(), json.dumps(sorted(hashes)), impl_id))
            if self.promote_allowed(prev["state"], state) and prev["state"] != state:
                self.set_state("implementation", "impl_id", impl_id, state, f"promoted by evidence from {artifact_sha256[:12]}", tool_version=tool_version, evidence_version=evidence_version)
            elif prev["state"] != state:
                self.set_state("implementation", "impl_id", impl_id, state, f"downgraded by evidence from {artifact_sha256[:12]}", tool_version=tool_version, evidence_version=evidence_version)
        # IMPLEMENTATION_VERIFIED needs ≥ 2 binaries AND at least one behaviour confirmation — and only when
        # this run's own evidence is at least BEHAVIOR_MATCHED (a downgrade is never undone by bookkeeping)
        if len(hashes) >= 2 and state in REUSABLE:
            conf = self.db.execute("SELECT COUNT(*) AS n FROM behavior WHERE impl_id=? AND result_state IN ('BIT_EXACT','NUMERICALLY_EQUIVALENT','BEHAVIORALLY_EQUIVALENT')", (impl_id,)).fetchone()["n"]
            if conf >= 1:
                self.set_state("implementation", "impl_id", impl_id, "IMPLEMENTATION_VERIFIED", f"signatures agree across {len(hashes)} binaries and {conf} behaviour confirmation(s)", tool_version=tool_version, evidence_version=evidence_version)

    def record_behavior(self, impl_id: str, *, artifact_sha256: str, probe_set_hash: str, metrics_ref: str, result_state: str) -> str:
        bid = hashlib.sha256(f"{impl_id}|{artifact_sha256}|{probe_set_hash}".encode()).hexdigest()[:24]
        self.db.execute("INSERT OR REPLACE INTO behavior VALUES (?,?,?,?,?,?,?)", (bid, impl_id, probe_set_hash, metrics_ref, result_state, artifact_sha256, _now()))
        return bid

    def record_reconstruction(self, impl_id: str, *, evidence_source_ref: str | None, human_source_ref: str | None, validation_state: str, rmse: float | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO reconstruction VALUES (?,?,?,?,?,?)", (impl_id, evidence_source_ref, human_source_ref, validation_state, rmse, _now()))

    # ---- reporting ---------------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        q = lambda sql: self.db.execute(sql).fetchall()  # noqa: E731
        return {"schema_version": SCHEMA_VERSION, "root": str(self.root),
                "artifacts": q("SELECT COUNT(*) AS n FROM artifact")[0]["n"], "runs": q("SELECT COUNT(*) AS n FROM analysis_run")[0]["n"],
                "functions": {r["kind"]: r["n"] for r in q("SELECT kind, COUNT(*) AS n FROM function GROUP BY kind")},
                "function_states": {r["state"]: r["n"] for r in q("SELECT state, COUNT(*) AS n FROM function GROUP BY state")},
                "classes": q("SELECT COUNT(*) AS n FROM class")[0]["n"], "resources": q("SELECT COUNT(*) AS n FROM resource")[0]["n"],
                "implementations": {r["state"]: r["n"] for r in q("SELECT state, COUNT(*) AS n FROM implementation GROUP BY state")},
                "behaviors": q("SELECT COUNT(*) AS n FROM behavior")[0]["n"], "vtable_layouts": q("SELECT COUNT(*) AS n FROM vtable_layout")[0]["n"],
                "history_rows": q("SELECT COUNT(*) AS n FROM classification_history")[0]["n"]}

    def history_rows(self, entity_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if entity_id:
            rows = self.db.execute("SELECT * FROM classification_history WHERE entity_id=? ORDER BY id DESC LIMIT ?", (entity_id, limit)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM classification_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


__all__ = ["KnowledgeDB", "LADDER", "KINDS", "REUSABLE", "fp_id", "const_sig"]
