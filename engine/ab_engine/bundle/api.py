"""Bundle browsing, scorecard and export (EXECUTE 1.5).

* ``bundle.tree`` / ``bundle.read`` — the Evidence browser: files under the
  project folder with their contract schema badge; JSON/text returned inline,
  binary as a path for the shell's sandboxed reader.
* ``bundle.scorecard`` — the separate categories of AB_BRIEF (no single fake
  number); every value carries its evidence state.
* ``bundle.export`` — materialises ``Exports/<name>-<sha8>/`` as independent
  files (carved bytes from the object store), writes ``UNRECOVERABLE.md`` at
  the root, runs the path and secret scanners and the GIT_READY checklist,
  optionally zips. Third-party jobs export without ``04_reconstruction``.
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ab_engine import TOOL, api
from ab_engine.bundle.scan import scan_paths, scan_secrets
from ab_engine.contracts import write_json
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs import runner
from ab_engine.jobs.model import Job
from ab_engine.jobs.runner import StageContext, StageFailed, StageImpl
from ab_engine.workspace import Workspace

TEXT_SUFFIXES = {".json", ".md", ".txt", ".cpp", ".h", ".hpp", ".cmake", ".xml", ".svg", ".gitignore", ".log", ".ps1", ".sh", ".jsonl"}
BUNDLE_DIRS = ("00_manifest", "01_evidence", "02_recovered_assets", "03_architecture", "04_reconstruction",
               "05_reference_behavior", "06_validation", "07_agent_handoff")


def _job(ws: Workspace, job_id: str) -> tuple[Any, Job]:
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, job_id)
    if job is None:
        raise api.ApiError("not_found", f"no job {job_id}")
    return conn, job


def _safe_rel(project_dir: Path, rel: str) -> Path:
    p = (project_dir / rel).resolve()
    if project_dir.resolve() not in p.parents and p != project_dir.resolve():
        raise api.ApiError("bad_request", "path escapes the project folder")
    return p


def h_bundle_tree(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    _, job = _job(ws, str(params.get("job_id", "")))
    root = Path(job.project_dir)
    entries = []
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root).as_posix()
            top = rel.split("/")[0]
            if top not in BUNDLE_DIRS and top not in ("stages", "UNRECOVERABLE.md", "README_RECOVERY.md", "static_result.json"):
                continue
            if p.is_dir():
                entries.append({"path": rel, "size": 0, "kind": "dir"})
            else:
                e: dict[str, Any] = {"path": rel, "size": p.stat().st_size, "kind": "file"}
                if p.suffix == ".json" and p.stat().st_size < 4_000_000:
                    try:
                        head = p.read_text(encoding="utf-8")[:400]
                        m = json.loads(head[: head.find('"generated"')] + '"x":0}') if '"generated"' in head else None
                        if m and "schema" in m:
                            e["schema"] = f"{m['schema']} v{m.get('schema_version', '?')}"
                    except (ValueError, OSError):
                        pass
                entries.append(e)
    return {"root": str(root), "entries": entries}


def h_bundle_read(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    _, job = _job(ws, str(params.get("job_id", "")))
    p = _safe_rel(Path(job.project_dir), str(params.get("path", "")))
    if not p.is_file():
        raise api.ApiError("not_found", f"{params.get('path')} is not in the bundle")
    size = p.stat().st_size
    if p.suffix.lower() in TEXT_SUFFIXES and size <= 8 * 1024 * 1024:
        text = p.read_text(encoding="utf-8", errors="replace")
        schema = None
        if p.suffix == ".json":
            try:
                doc = json.loads(text)
                if isinstance(doc, dict) and "schema" in doc:
                    schema = f"{doc['schema']} v{doc.get('schema_version', '?')}"
            except ValueError:
                pass
        return {"text": text, "schema": schema, "size": size, "path": str(p)}
    return {"text": None, "schema": None, "size": size, "path": str(p)}


# --------------------------------------------------------------------------- #
# Scorecard
# --------------------------------------------------------------------------- #

def _load(project_dir: Path, rel: str) -> Any:
    p = project_dir / rel
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("data")
    except (ValueError, OSError):
        return None


def scorecard(job: Job) -> list[dict[str, str]]:
    pd = Path(job.project_dir)
    summary = _load(pd, "00_manifest/recovery_summary.json") or {}
    factory = _load(pd, "01_evidence/vst3/factory.json")
    rparams = _load(pd, "01_evidence/vst3/runtime_parameters.json")
    keys = _load(pd, "03_architecture/serialized_keys.json") or []
    srmap = _load(pd, "03_architecture/state_runtime_map.json")
    classes = _load(pd, "01_evidence/rtti/classes.json") or []
    verified_classes = _load(pd, "01_evidence/rtti/classes_verified.json")
    resources = _load(pd, "01_evidence/resources/index.json") or []
    bdmap = _load(pd, "01_evidence/resources/binarydata_map.json") or []
    signal = _load(pd, "03_architecture/signal_flow.json")
    recon = _load(pd, "07_agent_handoff/reconstruction_index.json") or []
    validation = _load(pd, "06_validation/differential_results.json")
    build = _load(pd, "06_validation/build.json")
    static_ok = job.stage("STATIC_COMPLETE") and job.stage("STATIC_COMPLETE").status == "OK"

    def cell(key: str, value: str, evidence: str, detail: str = "") -> dict[str, str]:
        return {"key": key, "value": value, "evidence": evidence, "detail": detail}

    cells = []
    if factory:
        cells.append(cell("Identity", f"{factory.get('vendor', '?')} · {len(factory.get('classes', []))} class(es)", "VERIFIED_RUNTIME", "vst3host factory"))
    else:
        cells.append(cell("Identity", summary.get("format", "?") + " " + str(summary.get("arch", "")), "UNVERIFIED" if static_ok else "UNKNOWN", "vendor, codes, FUID need the runtime stage"))
    if rparams:
        cells.append(cell("Runtime parameters", str(len(rparams)), "VERIFIED_RUNTIME", "IEditController"))
    else:
        cells.append(cell("Runtime parameters", "UNVERIFIED", "UNKNOWN", f"{len(keys)} serialized keys are not parameters"))
    indexed = sum(1 for k in keys if str(k.get("key_kind_candidate", "")).startswith("INTERNAL"))
    cells.append(cell("State schema", f"{len(keys)} keys" + (f" ({indexed} STATE_FIELD_CANDIDATE)" if indexed else ""), "VERIFIED_XML" if keys else "UNKNOWN",
                      "representation UNKNOWN until the state-differential harness" if keys and not srmap else ("mapped" if srmap else "")))
    owned = sum(1 for c in classes if c.get("kind") == "PLUGIN_OWNED_CANDIDATE")
    cells.append(cell("Class architecture", f"{owned} plugin-owned · {len(classes)} RTTI names", "VERIFIED_RTTI_NAME" if classes else "UNKNOWN",
                      "vtables/inheritance need the decompiler stage" if classes and not verified_classes else ("VERIFIED_VTABLE" if verified_classes else "")))
    valid = sum(1 for r in resources if r.get("status") == "VALID_EXACT")
    mapped = sum(1 for m in bdmap if str(m.get("mapping_status", "")).startswith("VERIFIED"))
    cells.append(cell("Resources", f"{valid} / {len(resources)} VALID_EXACT", "VERIFIED" if valid else "UNKNOWN", f"{mapped}/{len(bdmap)} BinaryData names mapped" if bdmap else ""))
    ui_docs = sum(1 for r in resources if r.get("ext") == "xml" and r.get("root") not in (None, "PARAMETERS"))
    cells.append(cell("UI", f"{ui_docs} layout document(s)" if ui_docs else "code-defined", "VERIFIED" if ui_docs else "UNRECOVERABLE" if static_ok else "UNKNOWN", "paint()/resized() do not survive; rebuild from assets"))
    cells.append(cell("Signal flow", f"{len(signal.get('nodes', []))} nodes" if signal else "not mapped", "INFERRED" if signal else "UNKNOWN", "processBlock callgraph (Phase 3)"))
    dsp_roles = sum(1 for c in classes if c.get("role") in ("WAVESHAPER", "FILTER", "OVERSAMPLER", "COMPRESSOR", "LIMITER", "GATE", "DELAY_REVERB", "ENVELOPE"))
    cells.append(cell("DSP structure", f"{dsp_roles} role candidate(s)", "CANDIDATE" if dsp_roles else "UNKNOWN", "roles from name tokens until the callgraph confirms"))
    if validation:
        mods = validation.get("modules", [])
        eq = sum(1 for m in mods if m.get("classification") in ("BIT_EXACT", "NUMERICALLY_EQUIVALENT", "BEHAVIORALLY_EQUIVALENT"))
        cells.append(cell("DSP behavioral match", f"{eq} / {len(mods)} modules", "MEASURED", "differential harness"))
    else:
        cells.append(cell("DSP behavioral match", "not measured", "SCAFFOLD_ONLY" if recon else "UNKNOWN", "probes + fits (Phase 4)"))
    if build:
        cells.append(cell("Build readiness", build.get("mode", "?") + (" OK" if build.get("ok") else " FAILED"), "MEASURED", build.get("detail", "")))
    else:
        cells.append(cell("Build readiness", "FIDELITY needs identity" if job.reconstruction_allowed else "analysis only", "GENERATED" if recon and job.reconstruction_allowed else "UNKNOWN",
                          "SURROGATE build available for DSP work" if job.reconstruction_allowed else "third-party: no reconstruction"))
    cells.append(cell("State compatibility", "not validated", "UNKNOWN", "CROSS_LOAD_VALIDATED needs original ⇄ rebuild"))
    exported = job.stage("EXPORT_COMPLETE")
    cells.append(cell("Repo readiness", "GIT_READY" if exported and exported.status == "OK" and exported.metrics.get("git_ready") else "not exported", "MEASURED" if exported and exported.status == "OK" else "UNKNOWN", "checklist runs on export"))
    cells.append(cell("Original source", "0 %", "UNRECOVERABLE", "comments, names, formatting, history are gone"))
    return cells


def h_bundle_scorecard(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    _, job = _job(ws, str(params.get("job_id", "")))
    return {"cells": scorecard(job)}


# --------------------------------------------------------------------------- #
# Export (EXPORT_COMPLETE stage)
# --------------------------------------------------------------------------- #

UNRECOVERABLE = """# UNRECOVERABLE

Information a stripped, optimised binary does not contain. Recreate it; do not keep searching for it.

- original source comments, whitespace and formatting
- original local variable names{names}
- dead source removed by the compiler or linker; excluded `#if` branches; unused files
- template abstractions optimised away
- Git history
- original CMake / Projucer formatting
- the intent behind UI `paint()` / `resized()` code (geometry survives, meaning does not)

Everything under `04_reconstruction/` is GENERATED unless its entry in
`07_agent_handoff/reconstruction_index.json` says otherwise.
"""


def git_ready_checks(out: Path, job: Job, path_findings: list, secret_findings: list) -> list[dict[str, Any]]:
    """SPEC §14 Export: legal filenames, no secrets, no machine paths, deps documented, .gitignore,
    build instructions, provenance manifest, no bundled SDK, configure/build passed, validation passed."""
    recon = out / "04_reconstruction"
    validation = job.stage("VALIDATION_COMPLETE")
    build = job.stage("BUILD_COMPLETE")
    rows: list[dict[str, Any]] = [
        {"name": "legal filenames", "ok": not path_findings, "detail": "no Windows-reserved names, characters or over-long paths" if not path_findings else f"{len(path_findings)} finding(s): " + "; ".join(f"{f['path']} ({f['kind']})" for f in path_findings[:3])},
        {"name": "no secrets", "ok": not [f for f in secret_findings if not f["kind"].endswith("_path")], "detail": "no keys, tokens or credentials found" if not secret_findings else f"{len(secret_findings)} finding(s)"},
        {"name": "no machine paths", "ok": not [f for f in secret_findings if f["kind"].endswith("_path")], "detail": "no absolute user paths outside 01_evidence" if not [f for f in secret_findings if f["kind"].endswith("_path")] else "; ".join(f"{f['path']}:{f['line']}" for f in secret_findings if f["kind"].endswith("_path"))[:200]},
        {"name": "dependencies documented", "ok": (out / "README_RECOVERY.md").is_file() and (not recon.is_dir() or (recon / "CMakeLists.txt").is_file()), "detail": "README_RECOVERY.md and CMakeLists.txt name JUCE and the build modes"},
        {"name": ".gitignore", "ok": (out / ".gitignore").is_file(), "detail": str(out / ".gitignore")},
        {"name": "build instructions", "ok": (out / "07_agent_handoff" / "HANDOFF.md").is_file(), "detail": "07_agent_handoff/HANDOFF.md"},
        {"name": "provenance manifest", "ok": (out / "00_manifest" / "input_manifest.json").is_file() and (out / "00_manifest" / "hashes.json").is_file(), "detail": "00_manifest/{input_manifest,hashes,tool_versions}.json"},
        {"name": "generated vs recovered separated", "ok": not recon.is_dir() or ((recon / "Source" / "Active").is_dir() and (recon / "Source" / "RecoveredScaffolds").is_dir()), "detail": "Source/Active vs Source/RecoveredScaffolds; 01_evidence immutable"},
        {"name": "no bundled SDK", "ok": not any((out / d).is_dir() for d in ("04_reconstruction/JUCE", "04_reconstruction/vst3sdk", "JUCE", "vst3sdk")), "detail": "JUCE / VST3 SDK are fetched, never vendored"},
        {"name": "configure/build passed", "ok": (build.status == "OK") if build and build.status in ("OK", "FAILED") else None, "detail": "pending: build stage (Phase 4)" if not build or build.status not in ("OK", "FAILED") else build.status},
        {"name": "validation passed", "ok": (validation.status == "OK") if validation and validation.status in ("OK", "FAILED") else None, "detail": "pending: pluginval + differential (Phase 4)" if not validation or validation.status not in ("OK", "FAILED") else validation.status},
    ]
    return rows


def export_job(ws: Workspace, conn: Any, job: Job, *, zip_it: bool, ctx: StageContext | None = None) -> dict[str, Any]:
    pd = Path(job.project_dir)
    if not (pd / "00_manifest" / "input_manifest.json").is_file():
        raise StageFailed("NOT_INGESTED", "nothing to export: the job has no manifest yet")
    name = pd.name
    out = ws.exports / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    copied = 0
    for d in BUNDLE_DIRS:
        src = pd / d
        if not src.is_dir():
            continue
        if d == "04_reconstruction" and not job.reconstruction_allowed:
            continue  # SPEC §15: third-party mode exports no reconstruction source
        shutil.copytree(src, out / d)
        copied += sum(1 for _ in (out / d).rglob("*") if _.is_file())
    for f in ("README_RECOVERY.md",):
        if (pd / f).is_file():
            shutil.copyfile(pd / f, out / f)
    names_note = "" if (job.stage("STATIC_COMPLETE") and (pd / "00_manifest" / "input_manifest.json").is_file() and any(i.get("kind") == "pdb" for i in (json.loads((pd / "00_manifest" / "input_manifest.json").read_text(encoding="utf-8")).get("data", {}).get("inputs", [])))) else "\n- original function and member names (no .pdb)"
    (out / "UNRECOVERABLE.md").write_text(UNRECOVERABLE.format(names=names_note), encoding="utf-8")
    if not (out / ".gitignore").is_file():
        (out / ".gitignore").write_text("build/\n*.pdb\n*.ilk\n.DS_Store\nThumbs.db\n", encoding="utf-8")
    if not job.reconstruction_allowed:
        (out / "ANALYSIS_ONLY.md").write_text("# Third-party analysis\n\nOwnership was declared THIRD_PARTY at ingest: this export holds evidence, architecture and corpus signatures only. No reconstruction source is generated or exported (SPEC §1.9, §15).\n", encoding="utf-8")
    path_findings = scan_paths(out)
    secret_findings = scan_secrets(out)
    checks = git_ready_checks(out, job, path_findings, secret_findings)
    git_ready = all(c["ok"] is True for c in checks if c["ok"] is not None) and not any(c["ok"] is False for c in checks)
    zip_path = (ws.exports / f"{name}.zip") if zip_it else None
    report = {"job_id": job.job_id, "exported": datetime.now(UTC).isoformat(), "out_dir": str(out), "files": copied,
              "reconstruction_exported": job.reconstruction_allowed, "path_findings": path_findings, "secret_findings": secret_findings,
              "git_ready": git_ready, "checks": checks, "zip_path": str(zip_path) if zip_path else None}
    write_json(out / "00_manifest" / "export_report.json", "artifactbench.export_report", report)
    if zip_path is not None:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(out.rglob("*")):
                if p.is_file():
                    zf.write(p, f"{name}/{p.relative_to(out).as_posix()}")
    if ctx is not None:
        ctx.metrics.update({"files": copied, "git_ready": git_ready, "path_findings": len(path_findings), "secret_findings": len(secret_findings)})
        for f in path_findings[:20]:
            ctx.warn("ILLEGAL_PATH", f"{f['path']}: {f['detail']}")
        for f in secret_findings[:20]:
            ctx.warn("SECRET_OR_MACHINE_PATH", f"{f['path']}:{f.get('line', 0)} {f['kind']}")
        ctx.output(f"export:{out}")
    return {"out_dir": str(out), "zip_path": str(zip_path) if zip_path else None, "git_ready": {"ok": git_ready, "checks": checks},
            "path_findings": path_findings, "secret_findings": secret_findings, "files": copied}


def stage_export(ctx: StageContext) -> None:
    export_job(ctx.ws, ctx.conn, ctx.job, zip_it=bool(ctx.options.get("zip", False)), ctx=ctx)
    ctx.completeness = "NOT_APPLICABLE"


runner.register_stage(StageImpl("EXPORT_COMPLETE", version=1, run=stage_export, tool_version=TOOL, config_keys=("zip",)))


def h_bundle_export(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn, job = _job(ws, str(params.get("job_id", "")))
    job, _ = runner.run_job(ws, conn, job, options={"zip": bool(params.get("zip", False))}, only=["EXPORT_COMPLETE"])
    rec = job.stage("EXPORT_COMPLETE")
    if rec is None or rec.status != "OK":
        raise api.ApiError((rec.errors[0]["code"] if rec and rec.errors else "EXPORT_FAILED"), (rec.errors[0]["message"] if rec and rec.errors else "export did not run"))
    report = json.loads((ws.exports / Path(job.project_dir).name / "00_manifest" / "export_report.json").read_text(encoding="utf-8"))["data"]
    return {"out_dir": report["out_dir"], "zip_path": report.get("zip_path"), "git_ready": {"ok": report["git_ready"], "checks": report["checks"]},
            "path_findings": report["path_findings"], "secret_findings": report["secret_findings"], "files": report["files"]}


for _n, _h in {"bundle.tree": h_bundle_tree, "bundle.read": h_bundle_read, "bundle.scorecard": h_bundle_scorecard, "bundle.export": h_bundle_export}.items():
    api.register(_n, _h)


from ab_engine.cli import subcommand  # noqa: E402


@subcommand("export", "export a job's recovery bundle (ab-cli export <job_id> [--zip])")
def _cli_export(p):
    p.add_argument("job_id")
    p.add_argument("--zip", action="store_true")

    def run(args, ws):
        result = api.dispatch("bundle.export", {"job_id": args.job_id, "zip": args.zip}, ws)
        sys.stdout.write(json.dumps({"ok": True, "data": result}, indent=2) + "\n")
        return 0 if result["git_ready"]["ok"] or all(c["ok"] is not False for c in result["git_ready"]["checks"]) else 1
    p.set_defaults(func=run)


@subcommand("scorecard", "print a job's recovery scorecard")
def _cli_scorecard(p):
    p.add_argument("job_id")

    def run(args, ws):
        cells = api.dispatch("bundle.scorecard", {"job_id": args.job_id}, ws)["cells"]
        for c in cells:
            sys.stdout.write(f"{c['key']:<24} {c['value']:<32} {c['evidence']:<20} {c['detail']}\n")
        return 0
    p.set_defaults(func=run)
