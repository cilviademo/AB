"""RPC + CLI for the identifier map (docs/NAMING_CANONICALIZATION.md §3, §5, §16, §20).

``naming.map``    build / rebuild ``04_reconstruction/identifier_map.json`` + ``IDENTIFIER_MAP.md`` for a job
``naming.search`` search original / semantic / active names
``ab-cli naming <job> [--mode …] [--term …] [--custom map.json]`` · ``ab-cli naming-search <job> <query>``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ab_engine import api
from ab_engine.contracts import write_json
from ab_engine.decompile import roles as roles_mod
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs.model import Job
from ab_engine.naming import canonical as nm
from ab_engine.workspace import Workspace


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")).get("data") if p.is_file() else None


def gather(project: Path) -> dict[str, Any]:
    """Every name the evidence recovered, with its address / source / evidence status / role."""
    classes = _load(project / "03_architecture" / "classes.json") or _load(project / "01_evidence" / "rtti" / "classes.json") or []
    roles = _load(project / "01_evidence" / "decompiler" / "roles.json") or []
    idx = _load(project / "07_agent_handoff" / "reconstruction_index.json") or []
    validated = {e.get("symbol") for e in idx if isinstance(e, dict) and e.get("validation") in ("BIT_EXACT", "NUMERICALLY_EQUIVALENT", "BEHAVIORALLY_EQUIVALENT")}
    idx_role = {e.get("symbol"): (e.get("role"), e.get("role_status")) for e in idx if isinstance(e, dict) and e.get("symbol") and e.get("role")}
    cls_rows = []
    for c in classes:
        if not isinstance(c, dict):
            continue
        name = c.get("recovered_name") or c.get("name")
        if not name:
            continue
        src = c.get("rtti_kind") or ("RTTI" if c.get("name_status") == "VERIFIED_RTTI" else "STATIC_STRING")
        cls_rows.append({"original": name, "address": (c.get("vtables") or [None])[0] or c.get("type_descriptor"), "source": src,
                         "evidence_status": "VERIFIED_ORIGINAL_NAME" if c.get("name_status") == "VERIFIED_RTTI" else "CANDIDATE_ORIGINAL_NAME",
                         "role": roles_mod.canonical_role(c.get("role") or idx_role.get(name, (None, None))[0]), "role_status": c.get("role_status") or idx_role.get(name, (None, None))[1], "validated": name in validated})
    seen = {r["original"] for r in cls_rows}
    for c in _load(project / "01_evidence" / "rtti" / "itanium_typeinfo_candidates.json") or []:   # stripped ELF (D-024)
        name = c.get("name") or c.get("recovered_name") if isinstance(c, dict) else None
        if name and name not in seen:
            cls_rows.append({"original": name, "address": c.get("offset") or c.get("address"), "source": "CANDIDATE_TYPEINFO_STRING", "evidence_status": "CANDIDATE_ORIGINAL_NAME",
                             "role": roles_mod.canonical_role(c.get("role")), "role_status": "CANDIDATE"})
            seen.add(name)
    fn_rows = []
    for r in roles:
        if not isinstance(r, dict) or r.get("noise") or not r.get("name") or str(r["name"]).startswith(("FUN_", "thunk_FUN_")):
            continue
        fn_rows.append({"original": r["name"], "address": r.get("addr"), "source": "SYMBOL" if not r.get("knowledge_name") else "KNOWLEDGE_MATCH",
                        "evidence_status": "VERIFIED_ORIGINAL_NAME" if not r.get("knowledge_name") else "INFERRED_NAME", "role": r.get("role"), "role_status": r.get("role_status")})
    params = [{"runtime_param_id": p.get("param_id"), "display_name": p.get("title")} for p in (_load(project / "01_evidence" / "vst3" / "runtime_parameters.json") or []) if isinstance(p, dict)]
    keys = _load(project / "03_architecture" / "serialized_keys.json") or {}
    key_list = keys.get("keys", keys) if isinstance(keys, dict) else keys
    state = [{"key": (k.get("key") or k.get("name") if isinstance(k, dict) else k)} for k in (key_list or []) if (k.get("key") or k.get("name") if isinstance(k, dict) else k)]
    bd = _load(project / "03_architecture" / "binarydata_resolved.json") or {}
    res = [{"binarydata_name": r.get("binarydata_name"), "filename": r.get("carved") or r.get("binarydata_name"), "sha256": r.get("sha256")} for r in (bd.get("rows", []) if isinstance(bd, dict) else []) if r.get("binarydata_name")]
    ident = _load(project / "03_architecture" / "identity.json") or {}
    declared = [x for x in (ident.get("vendor"), ident.get("product")) if x]
    return {"classes": cls_rows, "functions": fn_rows[:2000], "parameters": params, "state_keys": state, "resources": res, "declared": declared}


def build_for_project(project: Path, *, mode: str = "PRESERVE_ORIGINAL_NAMES", custom: dict[str, str] | None = None, terms: list[str] | None = None, write: bool = True) -> dict[str, Any]:
    g = gather(project)
    imap = nm.build_map(classes=g["classes"], functions=g["functions"], parameters=g["parameters"], state_keys=g["state_keys"], resources=g["resources"],
                        mode=mode, custom=custom, declared_terms=list(g["declared"]) + list(terms or []))
    if write:
        rec = project / "04_reconstruction"
        rec.mkdir(parents=True, exist_ok=True)
        write_json(rec / "identifier_map.json", "artifactbench.identifier_map", imap)
        (rec / "IDENTIFIER_MAP.md").write_text(nm.to_markdown(imap), encoding="utf-8")
    return imap


def _job(ws: Workspace, job_id: str) -> Job:
    job = jobs_db.get_job(jobs_db.connect(ws.db_path), job_id)
    if job is None:
        raise api.ApiError("not_found", "no such job")
    return job


def h_naming_map(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    job = _job(ws, str(params.get("job_id", "")))
    mode = str(params.get("mode") or "PRESERVE_ORIGINAL_NAMES").upper()
    if mode not in nm.MODES:
        raise api.ApiError("bad_request", f"mode must be one of {nm.MODES}")
    custom = params.get("custom") or {}
    if isinstance(custom, str) and custom:
        custom = json.loads(Path(custom).read_text(encoding="utf-8"))
    imap = build_for_project(Path(job.project_dir), mode=mode, custom=custom, terms=list(params.get("terms") or []))
    return {"mode": mode, "identifiers": len(imap["identifiers"]), "renamed": sum(1 for r in imap["identifiers"] if r["active"] != r["original"].split("::")[-1]),
            "terms": imap["terms"], "path": "04_reconstruction/identifier_map.json", "markdown": "04_reconstruction/IDENTIFIER_MAP.md"}


def h_naming_search(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    job = _job(ws, str(params.get("job_id", "")))
    imap = _load(Path(job.project_dir) / "04_reconstruction" / "identifier_map.json") or build_for_project(Path(job.project_dir), write=False)
    return {"query": params.get("query", ""), "hits": nm.search(imap, str(params.get("query", "")))[:200]}


api.register("naming.map", h_naming_map)
api.register("naming.search", h_naming_search)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("naming", "build the reversible identifier map (ab-cli naming <job> [--mode PRESERVE_ORIGINAL_NAMES|CANONICALIZE_NAMES|CUSTOM_RENAME_MAP] [--term SSL] [--custom map.json])")
def _cli_naming(p):
    p.add_argument("job_id")
    p.add_argument("--mode", default="PRESERVE_ORIGINAL_NAMES", choices=nm.MODES)
    p.add_argument("--term", action="append", default=[], help="a vendor/product/model term to neutralize (repeatable)")
    p.add_argument("--custom", default=None, help="JSON file {original: active} for CUSTOM_RENAME_MAP")

    def run(args, ws):
        r = api.dispatch("naming.map", {"job_id": args.job_id, "mode": args.mode, "terms": args.term, "custom": args.custom}, ws)
        sys.stdout.write(json.dumps({"ok": True, "data": r}, indent=2) + "\n")
        return 0
    p.set_defaults(func=run)


@subcommand("naming-search", "search original / semantic / active names (ab-cli naming-search <job> <query>)")
def _cli_search(p):
    p.add_argument("job_id")
    p.add_argument("query")

    def run(args, ws):
        r = api.dispatch("naming.search", {"job_id": args.job_id, "query": args.query}, ws)
        for h in r["hits"]:
            sys.stdout.write(f"{h.get('original') or h.get('original_binarydata_name')}  →  {h.get('active') or h.get('new_filename')}   [{h.get('kind')}, {h.get('evidence_status') or ''}]\n")
        return 0
    p.set_defaults(func=run)


__all__ = ["gather", "build_for_project", "h_naming_map", "h_naming_search"]
