"""ADDENDUM B6 — reference library RPC + CLI.

* ``reference.list``        — every entry typed with provenance, explicit actions, fixture-source isolation
* ``reference.provenance``  — "where did AB learn this?" for a function / class / vtable layout / implementation
* ``reference.dashboard``   — ground-truth counts for one job (from its GROUND_TRUTH_REPORT.json; never re-runs)
* ``reference.set_context`` — Add as Fixture / Use as Black-Box Reference: explicit, recorded, interpretation only
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ab_engine import api
from ab_engine.jobs import db as jobs_db
from ab_engine.reference import library
from ab_engine.workspace import Workspace


def _kconn(ws: Workspace) -> sqlite3.Connection | None:
    p = ws.knowledge / "knowledge.db"
    if not p.is_file():
        return None
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def _write_reports(ws: Workspace, lib: dict[str, Any]) -> dict[str, str]:
    out = ws.home / "Reference"
    out.mkdir(parents=True, exist_ok=True)
    (out / "REFERENCE_LIBRARY.md").write_text(library.to_markdown(lib), encoding="utf-8")
    from ab_engine.contracts import write_json  # noqa: PLC0415

    write_json(out / "reference_library.json", "artifactbench.reference_library", lib)
    return {"markdown": str(out / "REFERENCE_LIBRARY.md"), "json": str(out / "reference_library.json")}


def h_reference_list(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    jobs = jobs_db.list_jobs(conn)
    k = _kconn(ws)
    try:
        lib = library.build(jobs, kconn=k)
    finally:
        if k is not None:
            k.close()
    if params.get("write", True):
        lib["written"] = _write_reports(ws, lib)
    return lib


def h_reference_provenance(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    k = _kconn(ws)
    try:
        return library.provenance(k, str(params.get("query", "")), limit=int(params.get("limit", 20)))
    finally:
        if k is not None:
            k.close()


def h_reference_dashboard(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    p = Path(job.project_dir) / "06_validation" / "GROUND_TRUTH_REPORT.json"
    rep = library._load(p) if p.is_file() else None
    d = library.dashboard(rep)
    return {"job_id": job.job_id, "dashboard": d, "source": "06_validation/GROUND_TRUTH_REPORT.json" if d else None,
            "note": None if d else "no ground-truth report yet: run groundtruth.compare (Validate Recovery Against Source)"}


def h_reference_set_context(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    if not (params.get("usage_context") or params.get("source_availability")):
        raise api.ApiError("bad_request", "usage_context and/or source_availability required — the action is explicit, never inferred")
    return library.set_context(conn, job, params.get("usage_context"), params.get("source_availability"))


for _n, _h in {"reference.list": h_reference_list, "reference.provenance": h_reference_provenance, "reference.dashboard": h_reference_dashboard, "reference.set_context": h_reference_set_context}.items():
    api.register(_n, _h)


from ab_engine.cli import subcommand  # noqa: E402


def _emit(r: dict[str, Any]) -> None:
    import sys  # noqa: PLC0415

    sys.stdout.write(json.dumps({"ok": True, "data": r}, indent=2, default=str) + "\n")


@subcommand("reference", "reference library (ADDENDUM B6): typed entries with provenance; --provenance asks where AB learned something")
def _cli_reference(p):
    p.add_argument("--provenance", metavar="QUERY", help="function fingerprint id / name, class, vtable layout or implementation")
    p.add_argument("--dashboard", metavar="JOB", help="ground-truth counts for one job")
    p.add_argument("--set-context", nargs=2, metavar=("JOB", "CONTEXT"), help="explicit re-typing: USER_RECOVERY | KNOWN_SOURCE_FIXTURE | BLACK_BOX_REFERENCE | SOURCE_AVAILABLE_REFERENCE")
    p.add_argument("--source-availability", default=None)

    def run(args, ws):
        text = bool(getattr(args, "text", False))
        if args.provenance:
            r = api.dispatch("reference.provenance", {"query": args.provenance}, ws)
            if text:
                for h in r["hits"]:
                    src = ", ".join(f"{a['name'] or a['sha256'][:12]} ({a['entry_type']})" for a in h["learned_from"]) or "—"
                    print(f"{h['entity_type']:15} {h.get('name') or h['entity_id']}  state {h.get('state')}  learned from: {src}  verified {h.get('last_verified')}")
                print(f"{len(r['hits'])} hit(s), {r.get('fixture_derived', 0)} fixture-derived")
                return 0
            _emit(r); return 0
        if args.dashboard:
            r = api.dispatch("reference.dashboard", {"job_id": args.dashboard}, ws)
            if text:
                d = r["dashboard"]
                if not d:
                    print(r["note"]); return 1
                for k, v in d.items():
                    print(f"{k:32} {v['n']}/{v['of']}" if isinstance(v, dict) and 'of' in v else f"{k:32} {v}")
                return 0
            _emit(r); return 0
        if args.set_context:
            r = api.dispatch("reference.set_context", {"job_id": args.set_context[0], "usage_context": args.set_context[1], "source_availability": args.source_availability}, ws)
            if text:
                print(f"{r['job_id']}: {r['before']} → {r['after']} ({r['entry_type']})"); return 0
            _emit(r); return 0
        r = api.dispatch("reference.list", {}, ws)
        if text:
            print(library.to_markdown(r)); return 0 if r["isolation"]["ok"] else 1
        _emit(r); return 0

    p.set_defaults(func=run)
