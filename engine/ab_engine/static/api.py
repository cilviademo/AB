"""STATIC_COMPLETE stage (EXECUTE 1.4): drives the frozen Static Recovery v2 port.

Two ways a result arrives (DECISIONS D-005):

* **Node host** — `ab-cli`/CI: the engine spawns `node cli.mjs analyze` as an
  isolated worker over the job's stored inputs and reads the plan it wrote.
* **Worker host** — the GUI: the webview runs the engine in a Web Worker and
  posts the plan through `static.submit`; the stage consumes that.

Either way the stage then writes the v2 file set into the project folder,
puts every carved byte blob in the object store, records SPEC §6.4
instrumentation and the §1.10 completeness flag, and applies the §6.3
DEEP_SCAN auto-triggers (re-running with `--deep` when they fire).
"""

from __future__ import annotations

import base64
import json
import re
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from ab_engine import api
from ab_engine import tools as tools_mod
from ab_engine.contracts import write_json, check_envelope
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs import runner
from ab_engine.jobs.runner import BlockedDependency, StageContext, StageFailed, StageImpl, StageSkipped
from ab_engine.workers.run import run_worker
from ab_engine.workspace import Workspace

STAGE_VERSION = 3  # 3: v2 licensing wording canonicalized at install (ADDENDUM C2); 2: LIEF inventory + v2 cross-check + Itanium typeinfo candidates (ADDENDUM A1, D-021)
STATIC_TOOL = "static-recovery-v2"
#: The v2 contracts SPEC §6.1 says are preserved. Anything else the port writes is extra, never fewer.
V2_CONTRACTS = (
    "00_manifest/recovery_summary.json", "01_evidence/rtti/classes.json", "01_evidence/paths/build_path_evidence.json",
    "01_evidence/resources/index.json", "01_evidence/resources/binarydata_map.json", "03_architecture/serialized_keys.json",
    "03_architecture/classes.json", "03_architecture/parameters.json", "07_agent_handoff/reconstruction_index.json",
)
SUBMITTED = "static_submitted.json"


def _inputs_for_node(ctx: StageContext) -> list[dict[str, Any]]:
    out = []
    for i in jobs_db.get_inputs(ctx.conn, ctx.job.job_id):
        if i["kind"] in ("binary", "preset", "session", "source", "obj", "pdb"):
            if not ctx.store.has(i["sha256"]):
                ctx.warn("INPUT_MISSING", f"{i['path']} is no longer in the object store")
                continue
            fmt = "PE"
            if i["kind"] == "binary":
                with open(ctx.store.get_path(i["sha256"]), "rb") as fh:
                    head = fh.read(4)
                fmt = "ELF" if head == b"\x7fELF" else "Mach-O" if head[:2] in (b"\xcf\xfa", b"\xca\xfe", b"\xce\xfa") else "PE"
            out.append({"path": i["path"], "fs_path": str(ctx.store.get_path(i["sha256"])), "kind": i["kind"], "format": fmt})
    return out


def _run_node(ctx: StageContext, deep: bool) -> dict[str, Any]:
    node = tools_mod.find_node(ctx.ws)
    cli = tools_mod.find_static_engine_cli()
    if not node.present or not cli.present:
        raise BlockedDependency("static engine unavailable here: run from the AB app (worker) or install Node and build app/static-engine")
    work = Path(tempfile.mkdtemp(prefix="ab-static-", dir=ctx.ws.tmp))
    inputs = _inputs_for_node(ctx)
    if not any(i["kind"] == "binary" for i in inputs):
        raise StageFailed("NO_BINARY", "the job has no binary input in the object store")
    (work / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    argv = [node.path or "node", cli.path or "", "analyze", "--inputs", str(work / "inputs.json"), "--out", str(work / "out"),
            "--key", ctx.job.name] + (["--deep"] if deep else [])
    ctx.progress("deep scan" if deep else "static scan", deep=deep)
    res = run_worker("static-engine", argv, timeout=float(ctx.options.get("static_timeout_s", 1800)), log_dir=ctx.ws.logs / ctx.job.job_id,
                     cwd=work, keep_cwd=True, parse_json_stdout=True, env_extra={"NODE_OPTIONS": "--max-old-space-size=4096"})
    ctx.tool_versions["node"] = node.version or "node"
    ctx.tool_versions["static_engine"] = STATIC_TOOL
    if not res.ok or not isinstance(res.stdout_json, dict):
        tail = ""
        try:
            tail = Path(res.stderr_path or "").read_text(encoding="utf-8", errors="replace")[-600:]
        except OSError:
            pass
        shutil.rmtree(work, ignore_errors=True)
        raise StageFailed(res.error_code or "STATIC_FAILED", f"static engine exit {res.exit_code}: {tail.strip() or 'no output'}")
    result = json.loads((work / "out" / "static_result.json").read_text(encoding="utf-8"))
    result["_out_dir"] = str(work / "out")
    result["_work"] = str(work)
    result["_peak_rss_mb"] = res.peak_rss_mb
    return result


# ---- ADDENDUM C2 canonicalization of the frozen v2 bundle -------------------------------------------------------
# The Static Recovery v2 port is frozen (diff-baseline) and still labels licensing code PROTECTED_SUBSYSTEM and tells
# an agent not to reimplement it. AB's own layer translates that *before* anything current reads it: generated text
# (agent prompt, handoff, scaffolds) is rewritten, the Protected/ scaffold folder becomes Licensing/, and the v2
# reconstruction index gains original_role / canonical_role. Frozen evidence JSON (recovery.* contracts) stays verbatim.
V2_LICENSING_LABEL = "PROTECTED_SUBSYSTEM"
LICENSING_LABEL = "LICENSING_AND_ENTITLEMENT_SUBSYSTEM"
LICENSING_RULE = ("Licensing, activation, entitlement, registration, authentication and demo-state components are "
                  "LICENSING_AND_ENTITLEMENT_SUBSYSTEM: recover, reconstruct, transform and validate them under the same evidence/provenance "
                  "rules as DSP, state, UI and build code. Preserve recovered original behaviour where supported; any intentional behavioural "
                  "change is recorded as a transformation (TRANSFORMED_BREAKING when a check is replaced) and validated, never presented as "
                  "recovered source.")
_STALE_RULE = re.compile(r"Licensing code is PROTECTED_SUBSYSTEM[^\n]*")
_V2_TEXT_DIRS = ("07_agent_handoff", "04_reconstruction")
_V2_TEXT_FILES = ("README_RECOVERY.md",)
_V2_TEXT_EXT = (".md", ".h", ".cpp", ".txt", ".cmake")
_SCAFFOLD_PROTECTED = "04_reconstruction/Source/RecoveredScaffolds/Protected/"
_SCAFFOLD_LICENSING = "04_reconstruction/Source/RecoveredScaffolds/Licensing/"


def canonical_rel(rel: str) -> str:
    """Install path of a v2 bundle file inside an AB project."""
    if rel == "00_manifest/input_manifest.json":
        return "00_manifest/static_input_manifest.json"
    if rel.startswith(_SCAFFOLD_PROTECTED):
        return _SCAFFOLD_LICENSING + rel[len(_SCAFFOLD_PROTECTED):]
    return rel


def canonicalize_v2_text(text: str) -> tuple[str, int]:
    """Translate v2 licensing wording in generated text; returns (text, replacements)."""
    n = 0
    text, k = _STALE_RULE.subn(LICENSING_RULE, text)
    n += k
    text, k = re.subn(r"\bPROTECTED_SUBSYSTEM\b", LICENSING_LABEL, text)
    n += k
    text, k = re.subn(r"RecoveredScaffolds/Protected/", "RecoveredScaffolds/Licensing/", text)
    n += k
    return text, n


def canonicalize_v2(project_dir: Path, written: list[str]) -> dict[str, Any]:
    """Run after the v2 files are installed. Rewrites generated text, annotates the v2 reconstruction index and records
    every translated class in 01_evidence/rtti/role_canonicalization.json (original_role kept for provenance)."""
    rewritten: list[str] = []
    for rel in written:
        p = project_dir / rel
        if not p.is_file():
            continue
        if (rel.split("/")[0] in _V2_TEXT_DIRS or rel in _V2_TEXT_FILES) and p.suffix in _V2_TEXT_EXT:
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            new, n = canonicalize_v2_text(text)
            if n:
                p.write_text(new, encoding="utf-8")
                rewritten.append(rel)
    classes: list[dict[str, Any]] = []
    idx = project_dir / "07_agent_handoff" / "reconstruction_index.json"
    if idx.is_file():
        try:
            doc = json.loads(idx.read_text(encoding="utf-8"))
            entries = doc.get("data") if isinstance(doc, dict) else doc
            changed = False
            for e in entries or []:
                if isinstance(e, dict) and e.get("role") == V2_LICENSING_LABEL:
                    e["original_role"] = V2_LICENSING_LABEL      # provenance: what the frozen engine said
                    e["canonical_role"] = LICENSING_LABEL
                    e["role"] = LICENSING_LABEL                  # what every current reader sees
                    e["reconstruction"] = "eligible: recover / reconstruct / transform / validate like DSP (ADDENDUM C2)"
                    if isinstance(e.get("file"), str):
                        e["file"] = e["file"].replace("RecoveredScaffolds/Protected/", "RecoveredScaffolds/Licensing/")
                    classes.append({"class": e.get("symbol") or e.get("class") or e.get("name"), "original_role": V2_LICENSING_LABEL, "canonical_role": LICENSING_LABEL})
                    changed = True
            if changed:
                idx.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                rewritten.append("07_agent_handoff/reconstruction_index.json")
        except (OSError, ValueError):
            pass
    rtti = project_dir / "01_evidence" / "rtti" / "classes.json"
    if rtti.is_file():
        try:
            for c in (json.loads(rtti.read_text(encoding="utf-8")).get("data") or []):
                if isinstance(c, dict) and c.get("role") == V2_LICENSING_LABEL and not any(x["class"] == c.get("recovered_name") for x in classes):
                    classes.append({"class": c.get("recovered_name"), "original_role": V2_LICENSING_LABEL, "canonical_role": LICENSING_LABEL})
        except (OSError, ValueError):
            pass
    report = {"rule": LICENSING_RULE, "v2_label": V2_LICENSING_LABEL, "canonical_label": LICENSING_LABEL, "classes": classes, "rewritten_files": rewritten,
              "scaffold_dir": {"v2": "RecoveredScaffolds/Protected/", "canonical": "RecoveredScaffolds/Licensing/"},
              "note": "frozen v2 evidence JSON (recovery.* contracts) keeps its original labels; every current AB report, instruction and export uses the canonical one"}
    if classes or rewritten:
        write_json(project_dir / "01_evidence" / "rtti" / "role_canonicalization.json", "artifactbench.role_canonicalization", report)
        written.append("01_evidence/rtti/role_canonicalization.json")
    return report


def _install(ctx: StageContext, result: dict[str, Any], out_dir: Path | None, entries_b64: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Copy the plan into the project folder; carved bytes go through the object store."""
    counts = {"files": 0, "carved_objects": 0}
    written: list[str] = []

    def target(rel: str) -> str:
        # AB's ingest manifest (usage_context / source_availability, ADDENDUM C1) lives at 00_manifest/input_manifest.json;
        # the frozen v2 bundle writes a file of the same name — keep it beside, never over, the AB one.
        # Protected/ scaffolds land in Licensing/ (ADDENDUM C2; the original role is kept in role_canonicalization.json)
        return canonical_rel(rel)

    if out_dir is not None:
        for f in result.get("files", []):
            rel = f["path"]
            src = out_dir / rel
            rel = target(rel)
            f["path"] = rel
            dst = ctx.project_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if f.get("carved"):
                sha, _ = ctx.store.put_file(src)
                shutil.copyfile(ctx.store.get_path(sha), dst)
                counts["carved_objects"] += 1
                f["object"] = sha
            else:
                shutil.copyfile(src, dst)
            written.append(rel)
            counts["files"] += 1
    elif entries_b64 is not None:
        for e in entries_b64:
            rel = target(e["path"])
            dst = ctx.project_dir / rel
            if Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise StageFailed("BAD_PLAN", f"refusing plan path {rel}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if "json" in e:
                dst.write_text(json.dumps(e["json"], indent=2), encoding="utf-8")
            elif "text" in e:
                dst.write_text(e["text"], encoding="utf-8")
            else:
                data = base64.b64decode(e["bytes_b64"])
                if e.get("carved"):
                    ctx.store.put_bytes(data)
                    counts["carved_objects"] += 1
                dst.write_bytes(data)
            written.append(rel)
            counts["files"] += 1
    # Every v2 contract file must exist and carry the v2 envelope.
    for rel in V2_CONTRACTS:
        p = ctx.project_dir / rel
        if not p.is_file():
            raise StageFailed("CONTRACT_MISSING", f"static engine did not write {rel}")
        doc = json.loads(p.read_text(encoding="utf-8"))
        check_envelope(doc)
        if doc["schema_version"] != 2 or doc["tool"] != STATIC_TOOL:
            raise StageFailed("CONTRACT_MISMATCH", f"{rel} is not a Static Recovery v2 contract")
    # ADDENDUM C2: translate the frozen v2 licensing wording before anything current reads the project
    canon = canonicalize_v2(ctx.project_dir, written)
    counts["licensing_canonicalized"] = len(canon["classes"])
    counts["v2_text_rewritten"] = len(canon["rewritten_files"])
    for rel in written:
        ctx.output(rel)
    return counts


def _deep_triggers(result: dict[str, Any]) -> list[str]:
    """SPEC §6.3: when the fast scan must be followed by a deep pass."""
    reasons = []
    inst = result.get("instrumentation", {})
    trig = result.get("triggers", {})
    if inst.get("completeness") == "FAST_SCAN_EARLY_TERMINATED":
        reasons.append("fast scan reported EARLY_TERMINATED")
    names, carved = trig.get("binarydata_names_by_ext", {}), trig.get("carved_by_ext", {})
    for ext, n in names.items():
        if n > carved.get(ext, 0):
            reasons.append(f"BinaryData names for .{ext} ({n}) outnumber carved assets ({carved.get(ext, 0)})")
    missing = [k for k in trig.get("state_keys", []) if k not in trig.get("keys_in_documents", [])]
    if missing:
        reasons.append(f"{len(missing)} state key(s) not found in any carved document")
    return reasons


def stage_static(ctx: StageContext) -> None:
    submitted = ctx.project_dir / SUBMITTED
    forced_deep = bool(ctx.options.get("deep_scan"))
    if submitted.is_file() and not ctx.options.get("prefer_node"):
        doc = json.loads(submitted.read_text(encoding="utf-8"))
        result, out_dir, entries = doc["result"], None, doc["result"].get("entries")
        for e in entries or []:
            if "bytes_b64" not in e and "json" not in e and "text" not in e:
                raise StageFailed("BAD_PLAN", f"submitted entry {e.get('path')} has no content")
        source = "worker"
    else:
        result, entries = _run_node(ctx, forced_deep), None
        out_dir = Path(result["_out_dir"])
        source = "node"
    reasons = [] if result["instrumentation"].get("deep") else _deep_triggers(result)
    if reasons and source == "node":
        ctx.log.info("DEEP_SCAN triggered", reasons=reasons)
        for r in reasons:
            ctx.warn("DEEP_SCAN_TRIGGERED", r)
        shutil.rmtree(result["_work"], ignore_errors=True)
        result = _run_node(ctx, True)
        out_dir = Path(result["_out_dir"])
    elif reasons:
        for r in reasons:
            ctx.warn("DEEP_SCAN_RECOMMENDED", r + " (worker result; run the deep scan from the Bench or ab-cli)")
    counts = _install(ctx, result, out_dir, entries)
    if source == "node":
        # keep the slim group result for corpus mode; it is a v2-internal structure, not a contract
        grp = Path(result["_out_dir"]) / "static_group.json"
        if grp.is_file():
            shutil.copyfile(grp, ctx.project_dir / "static_group.json")
        shutil.rmtree(result["_work"], ignore_errors=True)
    inst = result["instrumentation"]
    ctx.completeness = inst["completeness"]
    ctx.metrics.update({
        "elapsed_ms": inst["elapsed_ms"], "bytes_processed": inst["bytes_processed"], "objects_found": inst["objects_found"],
        "peak_rss_mb": result.get("_peak_rss_mb") or inst.get("peak_rss_mb"), "stages_ms": inst["stages_ms"],
        "mb_per_s": round(inst["bytes_processed"] / 1048576 / max(0.001, inst["elapsed_ms"] / 1000), 2),
        "files": counts["files"], "carved_objects": counts["carved_objects"], "source": source, "deep": bool(inst.get("deep")),
    })
    (ctx.project_dir / "static_result.json").write_text(json.dumps({k: v for k, v in result.items() if not k.startswith("_") and k != "entries"}, indent=2), encoding="utf-8")
    ctx.input_hashes = sorted({i["sha256"] for i in jobs_db.get_inputs(ctx.conn, ctx.job.job_id)})
    _write_inventory(ctx)


def _write_inventory(ctx: StageContext) -> None:
    """LIEF inventory beside the frozen v2 binary record (ADDENDUM A1, DECISIONS D-021): every binary
    input gets an ``artifactbench.binary_inventory`` entry plus a cross-check of v2's ``pe`` object."""
    from ab_engine.inventory import lief_inventory as li  # noqa: PLC0415

    rows = []
    bdir = ctx.project_dir / "01_evidence" / "binary"
    for i in jobs_db.get_inputs(ctx.conn, ctx.job.job_id):
        if i["kind"] != "binary" or not ctx.store.has(i["sha256"]):
            continue
        src = ctx.store.get_path(i["sha256"])
        try:
            inv = li.inventory(src)
            inv["file"] = i["path"].replace("\\", "/").split("/")[-1]
            v2_file = bdir / (inv["file"] + ".json")
            check: dict[str, Any] = {"status": "NO_V2_RECORD"}
            if v2_file.is_file():
                v2 = json.loads(v2_file.read_text(encoding="utf-8")).get("data", {}).get("pe", {})
                mine = li.v2_pe_dict(src)
                diff = sorted(k for k in set(v2) | set(mine) if v2.get(k) != mine.get(k) and k != "error")
                check = {"status": "MATCH" if not diff else "MISMATCH", "differing_keys": diff}
            inv["v2_pe_crosscheck"] = check
            if check.get("status") == "MISMATCH":
                ctx.warn("INVENTORY_MISMATCH", f"{inv['file']}: LIEF and v2 parsePE disagree on {check['differing_keys']}")
        except Exception as exc:  # noqa: BLE001 — a parser failure is evidence, not a stage failure
            inv = {"file": i["path"], "sha256": i["sha256"], "status": "PARSE_ERROR", "detail": f"{exc.__class__.__name__}: {exc}"[:300]}
        rows.append(inv)
    if rows:
        write_json(bdir / "inventory.json", "artifactbench.binary_inventory", rows)
        ctx.output("01_evidence/binary/inventory.json")
        ctx.metrics["inventory"] = {r["file"]: r.get("v2_pe_crosscheck", {}).get("status", r.get("status")) for r in rows}
    # YARA candidate families (ADDENDUM A4): markers only, never lineage proof
    from ab_engine.lineage import rules as yara_rules  # noqa: PLC0415

    fam: list[dict[str, Any]] = []
    for r in rows:
        for i in jobs_db.get_inputs(ctx.conn, ctx.job.job_id):
            if i["kind"] == "binary" and i["sha256"] == r.get("sha256") and ctx.store.has(i["sha256"]):
                res = yara_rules.scan(ctx.store.get_path(i["sha256"]))
                fam.append({"file": r.get("file"), **res})
    if fam:
        write_json(ctx.project_dir / "01_evidence" / "lineage" / "family_candidates.json", "artifactbench.family_candidates", fam)
        ctx.output("01_evidence/lineage/family_candidates.json")
        ctx.metrics["family_candidates"] = {f["file"]: [c["rule"] for c in f.get("candidates", [])] if f.get("status") == "OK" else f.get("status") for f in fam}
    from ab_engine.knowledge import hooks as knowledge_hooks  # noqa: PLC0415

    knowledge_hooks.after_static(ctx, inventory=rows)
    # stripped ELF / Mach-O: Itanium typeinfo-name CANDIDATES (v2 keys on _ZTS symbols, which strip removes)
    from ab_engine.inventory import typeinfo  # noqa: PLC0415

    cands: list[dict[str, Any]] = []
    for r in rows:
        if r.get("format") in ("ELF", "Mach-O") and r.get("status") == "PARSED":
            for i in jobs_db.get_inputs(ctx.conn, ctx.job.job_id):
                if i["kind"] == "binary" and i["sha256"] == r.get("sha256") and ctx.store.has(i["sha256"]):
                    cands += typeinfo.scan(ctx.store.get_path(i["sha256"]))
    if cands:
        write_json(ctx.project_dir / "01_evidence" / "rtti" / "itanium_typeinfo_candidates.json", "artifactbench.rtti_candidates", cands)
        ctx.output("01_evidence/rtti/itanium_typeinfo_candidates.json")
        ctx.metrics["typeinfo_candidates"] = {"total": len(cands), "plugin_owned_candidates": sum(1 for c in cands if c["kind"] == "PLUGIN_OWNED_CANDIDATE")}


runner.register_stage(StageImpl("STATIC_COMPLETE", version=STAGE_VERSION, run=stage_static, tool_version=STATIC_TOOL,
                                config_keys=("attachments_hash", "deep_scan", "prefer_node"), contract=runner.CONTRACTS["STATIC_COMPLETE"]))


# --------------------------------------------------------------------------- #
# RPC: the GUI worker path and result access
# --------------------------------------------------------------------------- #

def h_static_submit(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    result = params.get("result")
    if not isinstance(result, dict) or "entries" not in result or "instrumentation" not in result:
        raise api.ApiError("bad_request", "result must be the worker's StaticRunResult with entries and instrumentation")
    Path(job.project_dir).mkdir(parents=True, exist_ok=True)
    (Path(job.project_dir) / SUBMITTED).write_text(json.dumps({"result": result}), encoding="utf-8")
    return {"accepted": True, "entries": len(result["entries"])}


def h_static_inputs(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """What the GUI worker needs: categorized inputs with object-store paths it may read."""
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    from ab_engine.jobs.store import ObjectStore  # noqa: PLC0415

    store = ObjectStore(ws.objects, conn)
    files = []
    for i in jobs_db.get_inputs(conn, job.job_id):
        if i["kind"] in ("binary", "preset", "session", "source", "obj", "pdb") and store.has(i["sha256"]):
            files.append({"path": i["path"], "name": i["path"].split("/")[-1], "kind": i["kind"], "size": i["size"],
                          "object_path": str(store.get_path(i["sha256"]))})
    return {"key": job.name, "files": files}


api.register("static.submit", h_static_submit)
api.register("static.inputs", h_static_inputs)


from ab_engine.cli import subcommand  # noqa: E402


@subcommand("static", "run the static stage headlessly on a job (ab-cli static <job_id> [--deep])")
def _cli_static(p):
    p.add_argument("job_id")
    p.add_argument("--deep", action="store_true")

    def run(args, ws):
        result = api.dispatch("job.run", {"job_id": args.job_id, "stages": ["INGESTED", "STATIC_COMPLETE"],
                                          "options": {"deep_scan": bool(args.deep), "prefer_node": True}}, ws)
        rec = next(s for s in result["stages"] if s["stage"] == "STATIC_COMPLETE")
        sys.stdout.write(json.dumps({"ok": rec["status"] == "OK", "status": rec["status"], "completeness": rec["completeness"],
                                     "metrics": rec["metrics"], "warnings": rec["warnings"], "errors": rec["errors"],
                                     "skip_reason": rec.get("skip_reason")}, indent=2) + "\n")
        return 0 if rec["status"] == "OK" else 1
    p.set_defaults(func=run)


__all__ = ["stage_static", "h_static_submit", "os"]
