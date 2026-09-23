"""Known-library cache (SPEC §8.5, §1.6; EXECUTE 3.4).

``knowledge/<state>/<sha8-of-tuple>.json`` entries keyed by *normalized fingerprint
tuples* (NORMALIZED_INSTRUCTION_HASH, CFG hash), never by name. Entry:
schema_version, tool_version, source_artifact_hashes[], compiler_fingerprint,
state (KNOWN_FRAMEWORK | KNOWN_THIRD_PARTY | KNOWN_SHARED_INTERNAL |
KNOWN_PLUGIN_SPECIFIC | UNKNOWN), function_fingerprints[], class_fingerprints[],
last_verification.

Matching: a function whose (normalized, cfg) tuple is in the cache inherits the
entry's state — *unless* any of its other fingerprints contradict the cached
one (constant signature, string-xref signature, vtable slot / RTTI class, callgraph
signature). A contradiction downgrades the match to UNKNOWN and flags the
function for re-analysis (SPEC §1.6: the cache never poisons). Deep work is
suppressed for KNOWN_FRAMEWORK / KNOWN_THIRD_PARTY; classifications are
reused for KNOWN_SHARED_INTERNAL.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATES = ("KNOWN_FRAMEWORK", "KNOWN_THIRD_PARTY", "KNOWN_SHARED_INTERNAL", "KNOWN_PLUGIN_SPECIFIC", "UNKNOWN")
SCHEMA_VERSION = 1


def tuple_key(fp: dict[str, Any]) -> str:
    n = fp.get("NORMALIZED_INSTRUCTION_HASH", "")
    c = (fp.get("CFG_SIGNATURE") or {}).get("hash", "")
    return hashlib.sha256(f"{n}|{c}".encode()).hexdigest()


class Knowledge:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.root / "knowledge.db"), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS functions (
                key TEXT PRIMARY KEY, state TEXT NOT NULL, normalized TEXT NOT NULL, cfg TEXT NOT NULL,
                constant_sig TEXT NOT NULL, string_sig TEXT NOT NULL, callgraph_sig TEXT NOT NULL,
                rtti TEXT, vtable_slot INTEGER, name TEXT, library TEXT, source_hashes TEXT NOT NULL,
                compiler TEXT, tool_version TEXT, last_verification TEXT NOT NULL, verifications INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_functions_state ON functions(state);
            CREATE TABLE IF NOT EXISTS resources (sha256 TEXT PRIMARY KEY, ext TEXT, size INTEGER, names TEXT, state TEXT, source_hashes TEXT);
            CREATE TABLE IF NOT EXISTS classes (name TEXT, state TEXT, slot_hashes TEXT, source_hash TEXT, PRIMARY KEY (name, source_hash));
        """)

    # -- seeding --------------------------------------------------------------
    def seed_functions(self, fps: list[dict[str, Any]], *, state: str, source_hash: str, library: str | None, compiler: str | None,
                       tool_version: str, only_names: set[str] | None = None, min_size: int = 32) -> int:
        if state not in STATES:
            raise ValueError(state)
        n = 0
        now = datetime.now(UTC).isoformat()
        for fp in fps:
            if int(fp.get("size", 0)) < min_size:
                continue
            if only_names is not None and fp.get("name") not in only_names and not any(fp.get("name", "").startswith(p) for p in only_names):
                continue
            key = tuple_key(fp)
            row = self.db.execute("SELECT * FROM functions WHERE key=?", (key,)).fetchone()
            const_sig = hashlib.sha256(json.dumps(fp.get("CONSTANT_SIGNATURE", []), sort_keys=True).encode()).hexdigest()
            if row:
                hashes = set(json.loads(row["source_hashes"])) | {source_hash}
                self.db.execute("UPDATE functions SET source_hashes=?, last_verification=?, verifications=verifications+1 WHERE key=?",
                                (json.dumps(sorted(hashes)), now, key))
            else:
                self.db.execute("INSERT INTO functions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                                (key, state, fp.get("NORMALIZED_INSTRUCTION_HASH", ""), (fp.get("CFG_SIGNATURE") or {}).get("hash", ""), const_sig,
                                 fp.get("STRING_XREF_SIGNATURE", ""), fp.get("CALLGRAPH_SIGNATURE", ""), fp.get("RTTI_XREF"), fp.get("VTABLE_SLOT", -1),
                                 fp.get("name"), library, json.dumps([source_hash]), compiler, tool_version, now))
            n += 1
        return n

    def seed_resources(self, resources: list[dict[str, Any]], *, state: str, source_hash: str) -> int:
        n = 0
        for r in resources:
            if not r.get("sha256"):
                continue
            row = self.db.execute("SELECT names, source_hashes FROM resources WHERE sha256=?", (r["sha256"],)).fetchone()
            names = set(json.loads(row["names"])) if row else set()
            if r.get("candidate_name"):
                names.add(r["candidate_name"])
            hashes = (set(json.loads(row["source_hashes"])) if row else set()) | {source_hash}
            self.db.execute("INSERT OR REPLACE INTO resources VALUES (?,?,?,?,?,?)", (r["sha256"], r.get("ext"), r.get("size"), json.dumps(sorted(names)), state, json.dumps(sorted(hashes))))
            n += 1
        return n

    # -- matching with the §1.6 contradiction check ------------------------------
    def match(self, fp: dict[str, Any]) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM functions WHERE key=?", (tuple_key(fp),)).fetchone()
        if row is None:
            return {"state": "UNKNOWN", "matched": False}
        const_sig = hashlib.sha256(json.dumps(fp.get("CONSTANT_SIGNATURE", []), sort_keys=True).encode()).hexdigest()
        contradictions = []
        if row["constant_sig"] != const_sig:
            contradictions.append("CONSTANT_SIGNATURE differs")
        if row["string_sig"] and fp.get("STRING_XREF_SIGNATURE") and row["string_sig"] != fp["STRING_XREF_SIGNATURE"]:
            contradictions.append("STRING_XREF_SIGNATURE differs")
        if row["callgraph_sig"] and fp.get("CALLGRAPH_SIGNATURE") and row["callgraph_sig"] != fp["CALLGRAPH_SIGNATURE"]:
            contradictions.append("CALLGRAPH_SIGNATURE differs")
        if row["rtti"] and fp.get("RTTI_XREF") and row["rtti"] != fp["RTTI_XREF"]:
            contradictions.append(f"RTTI class differs ({row['rtti']} vs {fp['RTTI_XREF']})")
        if row["vtable_slot"] is not None and row["vtable_slot"] >= 0 and fp.get("VTABLE_SLOT", -1) >= 0 and row["vtable_slot"] != fp["VTABLE_SLOT"]:
            contradictions.append("vtable slot differs")
        if contradictions:
            return {"state": "UNKNOWN", "matched": True, "downgraded_from": row["state"], "contradictions": contradictions, "reanalyse": True,
                    "cached_name": row["name"], "library": row["library"]}
        return {"state": row["state"], "matched": True, "cached_name": row["name"], "library": row["library"], "verifications": row["verifications"],
                "suppress_deep_work": row["state"] in ("KNOWN_FRAMEWORK", "KNOWN_THIRD_PARTY")}

    def match_all(self, fps: list[dict[str, Any]]) -> dict[str, Any]:
        results = {fp["addr"]: self.match(fp) for fp in fps}
        counts: dict[str, int] = {}
        for r in results.values():
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        suppressed = sum(1 for r in results.values() if r.get("suppress_deep_work"))
        downgraded = sum(1 for r in results.values() if r.get("reanalyse"))
        return {"results": results, "counts": counts, "suppressed": suppressed, "downgraded": downgraded, "total": len(fps)}

    def stats(self) -> dict[str, Any]:
        rows = self.db.execute("SELECT state, COUNT(*) AS n FROM functions GROUP BY state").fetchall()
        res = self.db.execute("SELECT COUNT(*) AS n FROM resources").fetchone()["n"]
        return {"functions": {r["state"]: r["n"] for r in rows}, "resources": res, "root": str(self.root)}
