"""Ingest (EXECUTE 1.3): files, folders, zips → grouped, hashed, attached jobs.

* walks folders (skipping v2's noise dirs), expands archives safely into the
  state cache (no traversal, no symlinks, size cap), never executes anything
* classifies every file with the v2 rules (``classify.py``)
* groups binaries by bundle, largest binary per group is the primary
* attaches presets/sessions/sources/objs by path prefix; .pdb/.map to every group
* streamed SHA-256 for everything; duplicates by hash
* records usage_context / source_availability (ADDENDUM C1); writes ``00_manifest/{input_manifest,
  hashes, tool_versions}.json`` from the INGESTED stage so they are cached
  and invalidated like every other stage output
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ab_engine import TOOL, __version__, api
from ab_engine import tools as tools_mod
from ab_engine.contracts import write_json
from ab_engine.ingest.classify import attaches, bundle_key, classify, safe_folder
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs import runner
from ab_engine.jobs.model import SOURCE_AVAILABILITIES, USAGE_CONTEXTS, Job, StageRecord, normalize_context
from ab_engine.jobs.runner import StageContext, StageFailed, StageImpl
from ab_engine.jobs.store import ObjectStore, sha256_file
from ab_engine.workspace import Workspace

MAX_ARCHIVE_MEMBER = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_TOTAL = 8 * 1024 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Walking and archives
# --------------------------------------------------------------------------- #

def _extract_archive(zip_path: Path, cache: Path, sha: str) -> Path | None:
    """Extract once per content hash. Refuses traversal, absolute names and symlinks."""
    dest = cache / "archives" / sha
    if (dest / ".complete").is_file():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                name = info.filename
                if info.is_dir() or "__MACOSX/" in name or name.endswith(".DS_Store"):
                    continue
                p = Path(name)
                if p.is_absolute() or ".." in p.parts or name.startswith(("/", "\\")):
                    continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000:  # symlink
                    continue
                if info.file_size > MAX_ARCHIVE_MEMBER:
                    continue
                total += info.file_size
                if total > MAX_ARCHIVE_TOTAL:
                    break
                target = dest / p
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    while True:
                        block = src.read(4 * 1024 * 1024)
                        if not block:
                            break
                        out.write(block)
    except (zipfile.BadZipFile, OSError):
        return None
    (dest / ".complete").write_text("ok", encoding="utf-8")
    return dest


def walk(paths: list[str], cache: Path) -> tuple[list[dict[str, Any]], int]:
    """Every regular file under the dropped paths, with archives expanded. Returns (files, ignored)."""
    files: list[dict[str, Any]] = []
    ignored = 0
    seen: set[str] = set()

    def add_file(fs_path: Path, logical: str) -> None:
        nonlocal ignored
        try:
            if fs_path.is_symlink() or not fs_path.is_file():
                return
            size = fs_path.stat().st_size
            with open(fs_path, "rb") as fh:
                head = fh.read(8)
        except OSError:
            ignored += 1
            return
        kind, fmt = classify(logical, size, head)
        if kind == "skip":
            ignored += 1
            return
        if kind == "archive":
            sha, _ = sha256_file(fs_path)
            root = _extract_archive(fs_path, cache, sha)
            if root is None:
                ignored += 1
                return
            base = logical[:-4] if logical.lower().endswith(".zip") else logical
            for inner in sorted(root.rglob("*")):
                if inner.is_file() and inner.name != ".complete":
                    add_file(inner, base + "/" + inner.relative_to(root).as_posix())
            return
        key = str(fs_path.resolve())
        if key in seen:
            return
        seen.add(key)
        files.append({"fs_path": str(fs_path), "path": logical, "size": size, "kind": kind, "format": fmt})

    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for root, dirs, names in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".git") and d != "node_modules")
                for n in sorted(names):
                    fp = Path(root) / n
                    add_file(fp, (p.name + "/" + fp.relative_to(p).as_posix()))
        else:
            add_file(p, p.name)
    return files, ignored


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #

def group(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """v2 ``analyzeAll`` grouping: binaries by bundle key, largest primary, attachments by prefix."""
    bins = [f for f in files if f["kind"] == "binary"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for b in bins:
        groups.setdefault(bundle_key(b["path"]), []).append(b)
    single = len(groups) == 1
    out = []
    for key, members in groups.items():
        members.sort(key=lambda f: -f["size"])
        attached = {"pdb": [], "map": [], "obj": [], "source": [], "preset": [], "session": [], "asset": [], "other": []}
        for f in files:
            k = f["kind"]
            if k == "binary":
                continue
            if k in ("pdb", "map") or attaches(f["path"], key, single):
                attached.setdefault(k, []).append(f)
        out.append({"key": key, "binaries": members, "primary": members[0], "attachments": attached})
    return out


# --------------------------------------------------------------------------- #
# The INGESTED stage: manifests from the stored inputs
# --------------------------------------------------------------------------- #

def _tool_versions(ws: Workspace) -> dict[str, Any]:
    se = tools_mod.find_static_engine_cli()
    return {
        "engine": TOOL,
        "static_engine": "static-recovery-v2" if se.present else None,
        # names and versions only: absolute tool paths would leak the machine into the bundle (the export scanner caught this)
        "tools": [{"name": t.name, "present": t.present, "version": t.version} for t in tools_mod.all_tools(ws)],
    }


def stage_ingested(ctx: StageContext) -> None:
    conn, job = ctx.conn, ctx.job
    inputs = jobs_db.get_inputs(conn, job.job_id)
    if not inputs:
        raise StageFailed("NO_INPUTS", "the job has no recorded inputs")
    primary = next((i for i in inputs if i["path"] == job.primary), None) or next(i for i in inputs if i["kind"] == "binary")
    meta = json.loads((ctx.project_dir / "ingest.json").read_text(encoding="utf-8")) if (ctx.project_dir / "ingest.json").is_file() else {}
    attachments: dict[str, list[str]] = {}
    for i in inputs:
        if i["kind"] != "binary":
            attachments.setdefault(i["kind"], []).append(i["path"])
    by_hash: dict[str, list[str]] = {}
    for i in inputs:
        by_hash.setdefault(i["sha256"], []).append(i["path"])
    dupes = [v for v in by_hash.values() if len(v) > 1]

    manifest = {
        "job_id": job.job_id, "name": job.name,
        # ADDENDUM C1: interpretation metadata only — no stage reads it to decide what runs (D-026)
        "usage_context": job.usage_context, "source_availability": job.source_availability, "interpretation": job.interpretation,
        **({"legacy_ownership": meta["legacy_ownership"]} if meta.get("legacy_ownership") else {}),
        "primary": {"path": primary["path"], "size": primary["size"], "sha256": primary["sha256"], "kind": "binary",
                    "format_hint": meta.get("format", "unknown")},
        # ADDENDUM A5: every dropped item is identified (magic + extension + LIEF for binaries) and kept; types AB has no
        # parser for are stored in the object store and listed as PRESERVED_UNPARSED — never silently dropped
        "inputs": [{"path": i["path"], "size": i["size"], "sha256": i["sha256"], "kind": i["kind"],
                    "status": "PRESERVED_UNPARSED" if i["kind"] in ("other", "obj") else "IDENTIFIED"} for i in inputs],
        "attachments": attachments, "preserved_unparsed": [i["path"] for i in inputs if i["kind"] in ("other", "obj")],
        "ignored": int(meta.get("ignored", 0)), "ignored_note": "skip-dir contents (node_modules, .git, JUCE/modules, build/_deps) and unreadable files; everything else is stored",
        "duplicates": dupes,
        "bundle_key": meta.get("bundle_key", ""), "source_roots": meta.get("source_roots", []),
    }
    write_json(ctx.project_dir / "00_manifest" / "input_manifest.json", "artifactbench.input_manifest", manifest)
    write_json(ctx.project_dir / "00_manifest" / "hashes.json", "artifactbench.hashes",
               {"algorithm": "sha256", "files": [{"path": i["path"], "sha256": i["sha256"], "size": i["size"]} for i in inputs]})
    write_json(ctx.project_dir / "00_manifest" / "tool_versions.json", "artifactbench.tool_versions", _tool_versions(ctx.ws))
    for rel in ("00_manifest/input_manifest.json", "00_manifest/hashes.json", "00_manifest/tool_versions.json"):
        ctx.output(rel)
    ctx.input_hashes = sorted({i["sha256"] for i in inputs})
    ctx.metrics.update({"inputs": len(inputs), "bytes": sum(i["size"] for i in inputs), "duplicates": len(dupes)})
    ctx.completeness = "NOT_APPLICABLE"


runner.register_stage(StageImpl("INGESTED", version=1, run=stage_ingested, config_keys=("attachments_hash",)))


# --------------------------------------------------------------------------- #
# ingest.run
# --------------------------------------------------------------------------- #

def h_ingest_run(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    paths = params.get("paths")
    if not isinstance(paths, list) or not paths:
        raise api.ApiError("bad_request", "paths must be a non-empty list")
    try:
        usage_context, source_availability = normalize_context(params.get("usage_context"), params.get("source_availability"), params.get("ownership"))
    except ValueError as exc:
        raise api.ApiError("bad_request", str(exc)) from exc
    legacy_ownership = str(params.get("ownership") or "").upper() or None
    if os.environ.get("AB_SAFE_MODE") == "1":
        raise api.ApiError("safe_mode", "AB is in Safe Mode and will not write files")
    for raw in paths:
        if not Path(raw).exists():
            raise api.ApiError("not_found", f"{raw} does not exist")

    api.progress("INGEST", "running", "walking and hashing")
    files, ignored = walk([str(p) for p in paths], ws.cache)
    conn = jobs_db.connect(ws.db_path)
    store = ObjectStore(ws.objects, conn)

    # Hash everything once (streamed); the object store dedups by content.
    for f in files:
        f["sha256"], _ = store.put_file(Path(f["fs_path"]))

    groups = group(files)
    if not groups:
        # Everything stored is released again: nothing to attach it to.
        for f in files:
            store.release(f["sha256"])
        return {"jobs": [], "files": _public(files), "duplicates": _dupes(files), "ignored": ignored}

    jobs_out = []
    for g in groups:
        primary = g["primary"]
        job = jobs_db.find_job_by_artifact(conn, primary["sha256"])
        created = datetime.now(UTC).isoformat()
        if job is None:
            name = str(params.get("name") or safe_folder(g["key"]))
            job_id = "ab-" + primary["sha256"][:12]
            project_dir = ws.projects / f"{safe_folder(name)}-{primary['sha256'][:8]}"
            job = Job(job_id, name, primary["sha256"], usage_context, created, primary["path"], str(project_dir),
                      [StageRecord(job_id, "INGESTED")], source_availability=source_availability)
        else:
            if (job.usage_context, job.source_availability) != (usage_context, source_availability) and (params.get("usage_context") or params.get("source_availability") or params.get("ownership")):
                job.usage_context, job.source_availability = usage_context, source_availability   # the tags at the latest drop win; recorded in the manifest
        project_dir = Path(job.project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)

        previous = {i["path"]: i for i in jobs_db.get_inputs(conn, job.job_id)}
        inputs: dict[str, dict[str, Any]] = dict(previous)
        for b in g["binaries"]:
            inputs[b["path"]] = {"path": b["path"], "size": b["size"], "sha256": b["sha256"], "kind": "binary", "attached_to": g["key"]}
        for kind, members in g["attachments"].items():
            for f in members:
                inputs[f["path"]] = {"path": f["path"], "size": f["size"], "sha256": f["sha256"], "kind": kind, "attached_to": g["key"]}
        jobs_db.upsert_job(conn, job)
        jobs_db.put_inputs(conn, job.job_id, list(inputs.values()))
        (project_dir / "ingest.json").write_text(json.dumps({**({"legacy_ownership": legacy_ownership} if legacy_ownership else {}), 
            "format": primary.get("format"), "bundle_key": g["key"], "ignored": ignored,
            "source_roots": sorted({str(Path(p).resolve()) for p in paths if Path(p).is_dir()}),
        }, indent=2), encoding="utf-8")

        # A different attachment set is a different static input: it lands in the config hash.
        attachments_hash = _attachments_hash(list(inputs.values()))
        job, outcomes = runner.run_job(ws, conn, job, options={"attachments_hash": attachments_hash}, only=["INGESTED"])
        d = job.as_dict()
        d["outcomes"] = outcomes
        d["attachments_hash"] = attachments_hash
        jobs_out.append(d)

    return {"jobs": jobs_out, "files": _public(files), "duplicates": _dupes(files), "ignored": ignored}


def _attachments_hash(inputs: list[dict[str, Any]]) -> str:
    import hashlib  # noqa: PLC0415

    h = hashlib.sha256()
    for i in sorted(inputs, key=lambda x: x["path"]):
        if i["kind"] != "binary":
            h.update(f"{i['kind']}:{i['sha256']}\n".encode())
    return h.hexdigest()[:16]


def _public(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"path": f["path"], "size": f["size"], "sha256": f.get("sha256"), "kind": f["kind"]} for f in files]


def _dupes(files: list[dict[str, Any]]) -> list[list[str]]:
    by: dict[str, list[str]] = {}
    for f in files:
        if f.get("sha256"):
            by.setdefault(f["sha256"], []).append(f["path"])
    return [v for v in by.values() if len(v) > 1]


api.register("ingest.run", h_ingest_run)


from ab_engine.cli import subcommand  # noqa: E402


@subcommand("ingest", "ingest files/folders/zips into recovery jobs (ab-cli ingest [--context USER_RECOVERY] [--source-availability SOURCE_UNKNOWN] <paths...>)")
def _cli_ingest(p):
    p.add_argument("paths", nargs="+")
    p.add_argument("--context", dest="usage_context", default=None, choices=USAGE_CONTEXTS, help="how reports interpret the results (ADDENDUM C1); default USER_RECOVERY")
    p.add_argument("--source-availability", dest="source_availability", default=None, choices=SOURCE_AVAILABILITIES, help="default SOURCE_UNKNOWN")
    p.add_argument("--ownership", default=None, choices=("OWNED", "AUTHORIZED", "THIRD_PARTY"), help="deprecated alias (D-026): OWNED/AUTHORIZED → USER_RECOVERY, THIRD_PARTY → BLACK_BOX_REFERENCE")
    p.add_argument("--name")

    def run(args, ws):
        result = api.dispatch("ingest.run", {"paths": args.paths, "usage_context": args.usage_context, "source_availability": args.source_availability,
                                             "ownership": args.ownership, "name": args.name}, ws)
        sys.stdout.write(json.dumps({"ok": True, "data": result}, indent=2) + "\n")
        return 0 if result["jobs"] else 1
    p.set_defaults(func=run)


__all__ = ["h_ingest_run", "walk", "group", "stage_ingested", "__version__"]
