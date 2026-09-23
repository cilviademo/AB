"""Stage hooks into the cumulative knowledge base (ADDENDUM A2 / A8).

Every hook is best-effort: knowledge recording never fails a stage (a warning is recorded
instead), and nothing recorded here is ever reused without the provenance ``match`` returns.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ab_engine import TOOL
from ab_engine.contracts import write_json
from ab_engine.jobs.runner import StageContext
from ab_engine.knowledge.db import KnowledgeDB, fp_id

FRAMEWORK_PREFIXES = ("juce::", "_ZN4juce", "Steinberg::", "_ZN9Steinberg", "std::", "_ZNSt", "_ZSt", "__gnu_cxx", "_ZN9__gnu_cxx")
THIRD_PARTY_PREFIXES = ("OT::", "AAT::", "CFF::", "hb_", "_ZN2OT", "_ZN3AAT", "_ZN3CFF", "vorbis", "ogg_", "png_", "FLAC__", "_ZN9soundtouch", "chowdsp::")


def _db(ctx: StageContext) -> KnowledgeDB:
    return KnowledgeDB(ctx.ws.knowledge)


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")).get("data") if p.is_file() else None


def kind_from_name(name: str | None) -> str | None:
    if not name:
        return None
    if name.startswith(FRAMEWORK_PREFIXES):
        return "KNOWN_FRAMEWORK"
    if name.startswith(THIRD_PARTY_PREFIXES):
        return "KNOWN_THIRD_PARTY"
    return None


def _safe(ctx: StageContext, what: str, fn) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — knowledge is cumulative, never blocking
        ctx.warn("KNOWLEDGE_HOOK", f"{what}: {exc.__class__.__name__}: {exc}"[:300])
        return None


def after_static(ctx: StageContext, *, inventory: list[dict[str, Any]] | None = None) -> None:
    def go():
        db = _db(ctx)
        db.record_artifact(ctx.job.artifact_sha256, kind="binary", size=int((inventory or [{}])[0].get("size", 0)), ownership=ctx.job.usage_context, name=ctx.job.name)
        res = _load(ctx.project_dir / "01_evidence" / "resources" / "index.json") or []
        n = db.record_resources(ctx.job.artifact_sha256, res)
        ctx.metrics["knowledge"] = {"resources_recorded": n}
    _safe(ctx, "after_static", go)


def after_runtime(ctx: StageContext) -> None:
    def go():
        db = _db(ctx)
        ident = _load(ctx.project_dir / "03_architecture" / "identity.json") or {}
        db.record_identity(ctx.job.artifact_sha256, ident)
        params = _load(ctx.project_dir / "01_evidence" / "vst3" / "runtime_parameters.json") or []
        tiers = (_load(ctx.project_dir / "03_architecture" / "parameters.json") or {}).get("tiers", [])
        n = db.record_parameters(ctx.job.artifact_sha256, params, tiers)
        ctx.metrics["knowledge"] = {"parameters_recorded": n, "identity": ident.get("evidence")}
    _safe(ctx, "after_runtime", go)


def match_prefingerprints(ctx: StageContext, pre: dict[str, Any]) -> dict[str, Any] | None:
    """Before Ghidra: match the Capstone signature set against everything known and write the delta
    summary. Returns the match report (used to decide what Ghidra must still look at)."""
    def go():
        db = _db(ctx)
        fps = pre.get("functions", [])
        rep = db.match_all(fps, artifact_sha256=ctx.job.artifact_sha256)
        out = {"delta": rep["delta"], "counts": rep["counts"], "kinds": rep["kinds"], "reusable": rep["reusable"], "suppressed_deep_work": rep["suppressed_deep_work"],
               "deep_analysis_first": rep["deep_analysis_first"][:200],
               "matches": {a: {k: v for k, v in r.items() if k in ("verdict", "state", "kind", "agree", "disagree", "tlsh_distance", "prior_binaries", "behavior_confirmations", "implementation", "implementation_state", "reusable", "fp_id", "name_hint", "role")} for a, r in rep["results"].items() if r.get("matched")},
               "basis": "Capstone signature set matched by fingerprint tuple (normalized hash + CFG); near_match = CFG+constants or normalized stream with a contradiction; names are never a reason"}
        write_json(ctx.project_dir / "01_evidence" / "decompiler" / "knowledge_match.json", "artifactbench.knowledge_match", out)
        ctx.output("01_evidence/decompiler/knowledge_match.json")
        ctx.metrics["knowledge_delta"] = rep["delta"]
        return rep
    return _safe(ctx, "match_prefingerprints", go)


def after_decompile(ctx: StageContext, *, pre: dict[str, Any], ghidra_fps: list[dict[str, Any]], classes: list[dict[str, Any]], roles: list[dict[str, Any]], stage_version: int) -> None:
    def go():
        db = _db(ctx)
        role_by = {r["addr"]: r for r in roles}
        pre_fns = pre.get("functions", [])

        def kind_pre(fp):
            return kind_from_name(fp.get("name"))

        def kind_gh(fp):
            r = role_by.get(fp.get("addr"), {})
            if r.get("noise_kind") == "FRAMEWORK_PLUMBING" or (r.get("role") == "FRAMEWORK"):
                return "KNOWN_FRAMEWORK"
            return kind_from_name(fp.get("name")) or (None if r.get("noise") else ("KNOWN_PLUGIN_SPECIFIC" if r.get("role") in ("WAVESHAPER", "FILTER", "AUDIO_LOOP", "PARAMETER_UPDATE", "STATE", "GAIN", "LICENSING_AND_ENTITLEMENT_SUBSYSTEM") else None))

        a = db.record_functions(ctx.job.artifact_sha256, pre_fns, source="capstone", tool_version=pre.get("tool", "capstone"), evidence_version=f"decompile-stage-v{stage_version}", kind_of=kind_pre)
        b = db.record_functions(ctx.job.artifact_sha256, ghidra_fps, source="ghidra", tool_version="ghidra/Fingerprint.java", evidence_version=f"decompile-stage-v{stage_version}",
                                kind_of=kind_gh, role_of=lambda fp: role_by.get(fp.get("addr"), {}).get("role"))
        c = db.record_classes(ctx.job.artifact_sha256, classes)
        db.record_run(f"{ctx.job.job_id}:DECOMPILATION_COMPLETE:{hashlib.sha256(json.dumps(ctx.tool_versions, sort_keys=True).encode()).hexdigest()[:8]}", ctx.job.artifact_sha256, "DECOMPILATION_COMPLETE",
                      tool_versions=ctx.tool_versions, stage_version=stage_version, config_hash="", started="", ended="", status="OK")
        ctx.metrics["knowledge"] = {"capstone": a, "ghidra": b, "classes": c}
    _safe(ctx, "after_decompile", go)


def match_ghidra_names(ctx: StageContext, ghidra_fps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Exact (``known``) knowledge matches for the Ghidra fingerprints, by address: the name hint and role a
    symbol build recorded for the same fingerprint. Names obtained this way are ``INFERRED`` (fingerprint
    identity, not a symbol) and are labelled so wherever they surface."""
    out: dict[str, dict[str, Any]] = {}

    def go():
        db = _db(ctx)
        for fp in ghidra_fps:
            if int(fp.get("size", 0)) < 32:
                continue
            r = db.match(fp, artifact_sha256=ctx.job.artifact_sha256)
            if r.get("verdict") == "known" and r.get("name_hint") and not str(r["name_hint"]).startswith(("FUN_", "thunk_FUN_")):
                out[fp["addr"]] = {"name": r["name_hint"], "role": r.get("role"), "kind": r.get("kind"), "state": r.get("state"), "prior_binaries": r.get("prior_binaries"), "evidence": "INFERRED", "basis": "knowledge fingerprint match (normalized instruction hash + CFG)"}
    _safe(ctx, "match_ghidra_names", go)
    return out


def learn_vtable_layouts(ctx: StageContext, *, classes: list[dict[str, Any]], ghidra_fps: list[dict[str, Any]], stage_version: int) -> int:
    """Symbol builds teach slot → method-name layouts (see ``knowledge.vtable_layout``). Called only when
    the callgraph seed came from a symbol, i.e. the build carries names worth learning."""
    from ab_engine.knowledge import vtable_layout  # noqa: PLC0415

    out = {"n": 0}

    def go():
        db = _db(ctx)
        rows = vtable_layout.learn_rows(classes, {f["addr"]: f for f in ghidra_fps})
        out["n"] = db.record_vtable_layouts(ctx.job.artifact_sha256, rows, tool_version="ghidra/ExportRTTI.java", evidence_version=f"decompile-stage-v{stage_version}")
    _safe(ctx, "learn_vtable_layouts", go)
    return out["n"]


def seed_from_vtable_layouts(ctx: StageContext, *, classes: list[dict[str, Any]], ghidra_fps: list[dict[str, Any]], stage_version: int) -> dict[str, Any]:
    """Stripped builds: apply learned layouts to the structurally recovered vtables. Returns the report from
    ``vtable_layout.apply`` (empty seeds when nothing is fingerprint-confirmed)."""
    from ab_engine.knowledge import vtable_layout  # noqa: PLC0415

    out: dict[str, Any] = {"seeds": {}, "seed_detail": {}, "seed_basis": "none", "classes": [], "layouts_considered": 0, "chosen_class": None, "ambiguous": []}

    def go():
        db = _db(ctx)
        out.update(vtable_layout.apply(db, classes, {f["addr"]: f for f in ghidra_fps}, artifact_sha256=ctx.job.artifact_sha256,
                                       tool_version="ghidra/ExportRTTI.java", evidence_version=f"decompile-stage-v{stage_version}"))
    _safe(ctx, "seed_from_vtable_layouts", go)
    return out


def after_validation(ctx: StageContext, *, modules: list[dict[str, Any]], index: list[dict[str, Any]], measurements_hash: str) -> None:
    """A BEHAVIOR_MATCHED module becomes an ``implementation`` row (with its member function fingerprints
    from the signal-flow / role evidence when present), a ``behavior`` row and a ``reconstruction`` row."""
    def go():
        db = _db(ctx)
        roles = _load(ctx.project_dir / "01_evidence" / "decompiler" / "roles.json") or []
        fps = (_load(ctx.project_dir / "01_evidence" / "decompiler" / "fingerprints.json") or {}).get("functions", [])
        fp_by_addr = {f["addr"]: f for f in fps}
        mod_by = {m["module"]: m for m in modules}
        n = 0
        for e in index:
            if not e.get("role") or e.get("role") not in ("WAVESHAPER", "FILTER", "GAIN", "OVERSAMPLER", "DELAY", "REVERB", "COMPRESSOR", "LIMITER"):
                continue
            m = mod_by.get(e.get("symbol", "").split("::")[-1]) or mod_by.get("Waveshaper" if e["role"] == "WAVESHAPER" else "")
            if m is None:
                continue
            members = [fp_id(fp_by_addr[r["addr"]]) for r in roles if r.get("role") == e["role"] and r["addr"] in fp_by_addr and not r.get("noise")][:32]
            impl_id = hashlib.sha256((e["role"] + "|" + "|".join(sorted(members)) + "|" + (e.get("family") or "")).encode()).hexdigest()[:24]
            cls = m["classification"]
            state = "BEHAVIOR_MATCHED" if cls in ("BIT_EXACT", "NUMERICALLY_EQUIVALENT", "BEHAVIORALLY_EQUIVALENT") else ("RUNTIME_SUPPORTED" if cls == "PERCEPTUALLY_CLOSE" else "STATIC_SUPPORTED")
            bid = db.record_behavior(impl_id, artifact_sha256=ctx.job.artifact_sha256, probe_set_hash=measurements_hash, metrics_ref="06_validation/differential_results.json", result_state=cls)
            db.record_implementation(impl_id, name_hint=f"{e['role']}:{e.get('family') or e['symbol']}", member_fp_ids=members, artifact_sha256=ctx.job.artifact_sha256, state=state, behavior_ref=bid,
                                     tool_version=TOOL, evidence_version="validation-stage")
            db.record_reconstruction(impl_id, evidence_source_ref="04_reconstruction/evidence_source", human_source_ref=e.get("file"), validation_state=cls, rmse=e.get("rmse"))
            e["knowledge"] = {"implementation": impl_id, "state": state, "members": len(members), "behavior": bid}
            n += 1
        ctx.metrics["knowledge"] = {"implementations": n}
    _safe(ctx, "after_validation", go)


def refresh_from_evidence(ws, job) -> dict[str, Any]:
    """Re-record a job's stored decompiler evidence (fingerprints, roles, classes, vtable layouts) into the
    knowledge base without re-running Ghidra — e.g. after a symbol build was analysed *after* the stripped one
    so its names can replace decompiler labels (name hints never regress)."""
    from ab_engine.knowledge import vtable_layout  # noqa: PLC0415

    pd = Path(job.project_dir)
    db = KnowledgeDB(ws.knowledge)
    fps = (_load(pd / "01_evidence" / "decompiler" / "fingerprints.json") or {}).get("functions", [])
    roles = _load(pd / "01_evidence" / "decompiler" / "roles.json") or []
    classes = _load(pd / "01_evidence" / "rtti" / "classes_verified.json") or []
    cg = _load(pd / "01_evidence" / "callgraphs" / "callgraph.json") or {}
    from ab_engine.decompile.api import _fill_sizes  # noqa: PLC0415

    _fill_sizes(fps, cg)
    role_by = {r["addr"]: r for r in roles}
    b = db.record_functions(job.artifact_sha256, fps, source="ghidra", tool_version="ghidra/Fingerprint.java", evidence_version="knowledge-refresh",
                            kind_of=lambda fp: kind_from_name(fp.get("name")) or ("KNOWN_PLUGIN_SPECIFIC" if role_by.get(fp.get("addr"), {}).get("role") in ("WAVESHAPER", "FILTER", "AUDIO_LOOP", "PARAMETER_UPDATE", "STATE", "GAIN", "LICENSING_AND_ENTITLEMENT_SUBSYSTEM") and not role_by.get(fp.get("addr"), {}).get("noise") else None),
                            role_of=lambda fp: role_by.get(fp.get("addr"), {}).get("role"))
    c = db.record_classes(job.artifact_sha256, classes)
    n_layouts = 0
    if (cg.get("seeds") or {}).get("processBlock") and not cg.get("seed_detail"):
        n_layouts = db.record_vtable_layouts(job.artifact_sha256, vtable_layout.learn_rows(classes, {f["addr"]: f for f in fps}), tool_version="ghidra/ExportRTTI.java", evidence_version="knowledge-refresh")
    return {"functions": b, "classes": c, "vtable_layouts": n_layouts, "job_id": job.job_id}


def knowledge_used(ctx: StageContext) -> dict[str, Any]:
    """Rows this job relied on (for evidence/knowledge_used.json at export, A7): every match that was
    reusable or suppressed deep work, with its provenance, plus the ladder states of the
    implementations the reconstruction touched."""
    km = _load(ctx.project_dir / "01_evidence" / "decompiler" / "knowledge_match.json") or {}
    idx = _load(ctx.project_dir / "07_agent_handoff" / "reconstruction_index.json") or []
    used = [{"addr": a, **r} for a, r in (km.get("matches") or {}).items() if r.get("reusable") or (r.get("verdict") == "known" and r.get("kind") in ("KNOWN_FRAMEWORK", "KNOWN_THIRD_PARTY"))]
    impls = [e.get("knowledge") for e in idx if isinstance(e, dict) and e.get("knowledge")]
    return {"delta": km.get("delta"), "skipped_deep_analysis": used[:2000], "skipped_count": len(used), "implementations": impls,
            "rule": "only BEHAVIOR_MATCHED / IMPLEMENTATION_VERIFIED implementations are reused; KNOWN_FRAMEWORK / KNOWN_THIRD_PARTY matches suppress deep work; CANDIDATE / STATIC_SUPPORTED only prioritise"}


__all__ = ["after_static", "after_runtime", "match_prefingerprints", "after_decompile", "match_ghidra_names", "learn_vtable_layouts", "seed_from_vtable_layouts", "after_validation", "refresh_from_evidence", "knowledge_used", "kind_from_name"]
