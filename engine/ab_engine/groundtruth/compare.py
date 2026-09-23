"""GROUND_TRUTH_REPORT.json (SPEC §12, EXECUTE 1.6): score a recovery bundle against truth.json.

Metrics: identity; param IDs/types/defaults/units; state fields mapped; RTTI
classes; ownership accuracy; processBlock path; DSP-function identification;
resource recovery; fingerprint stability across builds; false positives;
false negatives. Each phase's exit gate is a named row with its threshold, so
CI can fail on exactly the phase it is in. Metrics whose stage has not run are
reported as ``null`` with the stage that produces them — never as zero.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ab_engine import api
from ab_engine import tools as tools_mod
from ab_engine.contracts import read_json, write_json
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs.model import Job
from ab_engine.workspace import Workspace

FRAMEWORK_PREFIXES = ("juce::", "std::", "Steinberg::", "I")


def default_truth_path() -> Path | None:
    root = tools_mod.repo_root()
    return (root / "fixtures" / "groundtruth" / "truth.json") if root else None


def _load(pd: Path, rel: str) -> Any:
    p = pd / rel
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc.get("data", doc)
    except (ValueError, OSError):
        return None


def _norm_class(name: str) -> str:
    return name.split("::")[-1]


def compare(job: Job, truth: dict[str, Any], *, phase: int = 1) -> dict[str, Any]:
    pd = Path(job.project_dir)
    metrics: dict[str, Any] = {}
    fps: list[dict[str, Any]] = []
    fns: list[dict[str, Any]] = []

    # ---- static: RTTI classes ------------------------------------------------
    classes = _load(pd, "01_evidence/rtti/classes.json") or []
    recovered = {c["recovered_name"]: c for c in classes}
    expected = truth["classes"]
    hit = [c for c in expected if c in recovered or _norm_class(c) in {_norm_class(r) for r in recovered}]
    # a stripped ELF/Mach-O has no _ZTS symbols: typeinfo-name CANDIDATES (static, AB) and Ghidra-verified classes count too, labelled by source
    cand_rows = _load(pd, "01_evidence/rtti/itanium_typeinfo_candidates.json") or []
    ghidra_rows = _load(pd, "01_evidence/rtti/classes_verified.json") or []
    cand_names = {c["recovered_name"] for c in cand_rows}
    ghidra_names = {c["name"] for c in ghidra_rows}
    hit_cand = [c for c in expected if c not in hit and (c in cand_names or _norm_class(c) in {_norm_class(r) for r in cand_names})]
    hit_ghidra = [c for c in expected if c not in hit and c not in hit_cand and (c in ghidra_names or _norm_class(c) in {_norm_class(r) for r in ghidra_names})]
    total_hit = len(hit) + len(hit_cand) + len(hit_ghidra)
    metrics["rtti_classes_recovered"] = {"expected": len(expected), "recovered": total_hit, "ratio": round(total_hit / max(1, len(expected)), 3),
                                         "by_source": {"static_v2_VERIFIED_RTTI_NAME": len(hit), "typeinfo_string_CANDIDATE": len(hit_cand), "ghidra_VERIFIED_RTTI": len(hit_ghidra)}}
    hit = hit + hit_cand + hit_ghidra
    for c in expected:
        if c not in hit:
            fns.append({"kind": "rtti_class", "item": c})
    # ownership accuracy: expected classes must be PLUGIN_OWNED_CANDIDATE; juce/std must not be
    owned_ok = sum(1 for c in hit for r in recovered.values() if _norm_class(r["recovered_name"]) == _norm_class(c) and r["kind"] == "PLUGIN_OWNED_CANDIDATE")
    wrong_owned = [r["recovered_name"] for r in recovered.values() if r["kind"] == "PLUGIN_OWNED_CANDIDATE" and r["recovered_name"].startswith(("juce::", "std::", "Steinberg::"))]
    metrics["ownership_accuracy"] = {"expected_owned_classified_owned": owned_ok, "of": len(hit), "framework_misclassified_as_owned": len(wrong_owned)}
    for r in wrong_owned:
        fps.append({"kind": "ownership", "item": r})
    # DSP role identification (static, name-based CANDIDATE)
    roles = {_norm_class(r["recovered_name"]): r.get("role") for r in recovered.values()}
    dsp_expect = {"TptLowpass": "FILTER", "TanhShaper": "WAVESHAPER"}
    role_hits = sum(1 for k, v in dsp_expect.items() if roles.get(k) == v)
    metrics["dsp_role_candidates"] = {"expected": len(dsp_expect), "matched": role_hits, "basis": "name tokens (CANDIDATE)"}
    lic = roles.get("LicenseStub")
    # ADDENDUM C2: the licensing stub is classified LICENSING_AND_ENTITLEMENT_SUBSYSTEM (v2 still says PROTECTED_SUBSYSTEM: alias)
    lic_truth = truth.get("licensing") or {}
    metrics["licensing_subsystem_classified"] = {"class": lic_truth.get("class", "abgt::LicenseStub"), "role": lic, "classified": lic in ("LICENSING_AND_ENTITLEMENT_SUBSYSTEM", "PROTECTED_SUBSYSTEM")}

    # ---- static: serialized keys and state fields ---------------------------
    # The frozen v2 extractor reads <PARAM id= value=> entries; JUCE stores non-parameter
    # ValueTree properties as root attributes, which the runtime state (serialized_properties.json)
    # exposes. So: static gate = the <PARAM> keys; all fields = static ∪ runtime.
    keys = {k["name"]: k for k in (_load(pd, "03_architecture/serialized_keys.json") or [])}
    props = {k["name"]: k for k in (_load(pd, "03_architecture/serialized_properties.json") or [])}
    truth_fields = {f["id"]: f for f in truth["state_fields"]}
    param_fields = [k for k, f in truth_fields.items() if f["tier"] == "VST3_EXPORTED_PARAMETER"]
    found_keys = [k for k in param_fields if k in keys]
    metrics["serialized_keys_found"] = {"expected": len(param_fields), "found": len(found_keys), "ratio": round(len(found_keys) / max(1, len(param_fields)), 3),
                                        "note": "<PARAM> entries of the embedded APVTS XML (Init.xml is BinaryData in the fixture)"}
    all_found = [k for k in truth_fields if k in keys or k in props]
    metrics["state_fields_found"] = {"expected": len(truth_fields), "found": len(all_found), "source": "static keys ∪ runtime serialized_properties"} if props else None
    for k in param_fields:
        if k not in keys:
            fns.append({"kind": "serialized_key", "item": k})
    if props:
        for k in truth_fields:
            if k not in keys and k not in props:
                fns.append({"kind": "state_field", "item": k})
    # a static key must never be promoted to a parameter
    promoted = [k for k, v in keys.items() if v.get("runtime_parameter_status") not in (None, "UNVERIFIED")]
    for k in promoted:
        fps.append({"kind": "static_key_promoted", "item": k})
    metrics["static_keys_promoted_to_parameters"] = len(promoted)

    # ---- static: resources ---------------------------------------------------
    resources = _load(pd, "01_evidence/resources/index.json") or []
    by_sha = {r.get("sha256"): r for r in resources}
    res_hits = []
    for t in truth["resources"]:
        r = by_sha.get(t["sha256"])
        res_hits.append({"name": t["binarydata_name"], "carved": bool(r), "status": r.get("status") if r else None, "mapped_name": r.get("candidate_name") if r else None})
        if not r:
            fns.append({"kind": "resource", "item": t["binarydata_name"]})
    valid = sum(1 for h in res_hits if h["status"] == "VALID_EXACT")
    metrics["resources"] = {"expected": len(truth["resources"]), "carved": sum(1 for h in res_hits if h["carved"]), "valid_exact": valid, "detail": res_hits}
    bd = _load(pd, "01_evidence/resources/binarydata_map.json") or []
    names_seen = {m["binarydata_name"] for m in bd}
    metrics["binarydata_names_present"] = {"expected": [t["binarydata_name"] for t in truth["resources"]], "seen": sorted(names_seen & {t["binarydata_name"] for t in truth["resources"]})}
    invalid = [r["name"] for r in resources if r.get("status") in ("INVALID", "CARVED_PARTIAL")]
    for r in invalid:
        fps.append({"kind": "resource_carve", "item": r})

    # ---- illegal paths in the bundle -----------------------------------------
    from ab_engine.bundle.scan import scan_paths  # noqa: PLC0415

    illegal = scan_paths(pd) if pd.is_dir() else []
    metrics["illegal_paths"] = len(illegal)

    # ---- runtime (Phase 2) ---------------------------------------------------
    factory = _load(pd, "01_evidence/vst3/factory.json")
    rparams = _load(pd, "01_evidence/vst3/runtime_parameters.json")
    srmap = _load(pd, "03_architecture/state_runtime_map.json")
    if factory:
        classes_rt = factory.get("classes", [])
        metrics["identity"] = {"vendor_ok": factory.get("vendor") == truth["company"], "product_ok": any(c.get("name") == truth["product"] for c in classes_rt),
                               "vendor": factory.get("vendor"), "classes": [c.get("name") for c in classes_rt], "evidence": "VERIFIED_RUNTIME"}
    else:
        metrics["identity"] = None
    if rparams is not None:
        by_id = {}
        for p in rparams:
            # JUCE VST3 wrapper titles are the parameter names; ids are hashed. Match by title; the
            # wrapper's own bypass parameter (kIsBypass) must not shadow a plugin parameter of the same title.
            if p.get("title") in by_id and p.get("is_bypass"):
                continue
            by_id[p.get("title")] = p
        rows = []
        for t in truth["parameters"]:
            p = by_id.get(t["name"])
            row = {"id": t["id"], "found": bool(p)}
            if p:
                row["default_ok"] = t["default_normalized"] is None or abs(float(p.get("default_normalized", -1)) - float(t["default_normalized"])) < 1e-6
                row["step_count_ok"] = int(p.get("step_count", -1)) == int(t["step_count"])
                row["units_ok"] = (p.get("units") or "") == (t.get("units") or "")
                row["type_ok"] = (t["type"] == "bool") == (int(p.get("step_count", 0)) == 1) if t["type"] != "choice" else int(p.get("step_count", 0)) == len(t["choices"]) - 1
            rows.append(row)
        metrics["parameters"] = {"expected": len(truth["parameters"]), "found": sum(1 for r in rows if r["found"]),
                                 "defaults_ok": sum(1 for r in rows if r.get("default_ok")), "steps_ok": sum(1 for r in rows if r.get("step_count_ok")),
                                 "units_ok": sum(1 for r in rows if r.get("units_ok")), "types_ok": sum(1 for r in rows if r.get("type_ok")), "detail": rows}
        extra = [p.get("title") for p in rparams if p.get("title") not in {t["name"] for t in truth["parameters"]} and not p.get("is_bypass")]
        metrics["wrapper_bypass_parameter"] = any(p.get("is_bypass") for p in rparams)
        for e in extra:
            fps.append({"kind": "runtime_parameter", "item": e})
    else:
        metrics["parameters"] = None
    if srmap is not None:
        rel = {m["key"]: m for m in srmap}
        exp_map = {f["id"]: f["tier"] for f in truth["state_fields"]}
        ok = 0
        for k, tier in exp_map.items():
            m = rel.get(k)
            if not m:
                continue
            if tier == "VST3_EXPORTED_PARAMETER" and m.get("relationship") in ("SAME_ID", "MAPPED") and m.get("value_representation") not in (None, "UNKNOWN"):
                ok += 1
            elif tier != "VST3_EXPORTED_PARAMETER" and m.get("relationship") == "STATE_ONLY":
                ok += 1
        decoy = rel.get("waveShapers_0_1", {})
        metrics["state_fields_mapped"] = {"expected": len(exp_map), "correct": ok, "decoy_classified_from_runtime": decoy.get("relationship") == "STATE_ONLY" and str(decoy.get("basis", "")).startswith("runtime")}
    else:
        metrics["state_fields_mapped"] = None

    # ---- decompiler (Phase 3) ------------------------------------------------
    verified = _load(pd, "01_evidence/rtti/classes_verified.json")
    callgraph = _load(pd, "01_evidence/callgraphs/callgraph.json")
    fingerprints = _load(pd, "01_evidence/decompiler/fingerprints.json")
    dsp_candidates = _load(pd, "01_evidence/decompiler/dsp_candidates.json")
    if callgraph:
        seeds = callgraph.get("seeds", {})
        metrics["process_block_path"] = {"processBlock": bool(seeds.get("processBlock")), "prepareToPlay": bool(seeds.get("prepareToPlay")),
                                         "state_functions": bool(seeds.get("getStateInformation") and seeds.get("setStateInformation")),
                                         "basis": "symbol" if (seeds.get("processBlock") and not callgraph.get("seed_detail")) else callgraph.get("seed_basis")}
    else:
        metrics["process_block_path"] = None
    if dsp_candidates:
        top5 = [(c.get("class") or c.get("name") or "") + ((" ≈ " + c["knowledge_name"] + " (knowledge)") if c.get("knowledge_name") else "") + ((" ⊃ " + ", ".join(c["inlined_classes"]) + " (inlined, INFERRED)") if c.get("inlined_classes") else "") for c in dsp_candidates[:5]]
        metrics["dsp_function_identification"] = {"top5": top5, "waveshaper_in_top5": any("TanhShaper" in str(x) for x in top5), "filter_in_top5": any("TptLowpass" in str(x) for x in top5),
                                                  "via_knowledge": any(c.get("knowledge_name") for c in dsp_candidates[:5]), "via_inlining": any(c.get("inlined_classes") for c in dsp_candidates[:5])}
    else:
        metrics["dsp_function_identification"] = None
    metrics["rtti_verified"] = {"classes": len(verified)} if verified else None
    fs = _load(pd, "06_validation/fingerprint_stability.json")
    metrics["fingerprint_stability"] = None if not fs else {k: v for k, v in fs.items() if k != "matches"}
    metrics["fingerprints"] = {"functions": len(fingerprints)} if fingerprints else None

    # ---- behaviour (Phase 4) -------------------------------------------------
    diff = _load(pd, "06_validation/differential_results.json")
    metrics["behavioral"] = None if not diff else {m.get("module"): m.get("classification") for m in diff.get("modules", [])}
    ws_mod = next((m for m in (diff or {}).get("modules", []) if m.get("role") == "WAVESHAPER"), None)
    metrics["waveshaper_differential"] = None if ws_mod is None else {"module": ws_mod.get("module"), "classification": ws_mod.get("classification"), "worst_rmse": ws_mod.get("worst_rmse"),
                                                                       "worst_spectrum_diff_db": ws_mod.get("worst_spectrum_diff_db"), "renders": ws_mod.get("renders"), "failing": ws_mod.get("failing")}
    build = _load(pd, "06_validation/build_report.json")
    pv = _load(pd, "06_validation/pluginval.json")
    metrics["build"] = None if not build else {"status": build.get("status"), "kind": build.get("build_kind"), "errors": (build.get("build") or {}).get("errors", [])[:3]}
    metrics["pluginval"] = None if not pv else {"status": pv.get("status"), "strictness": pv.get("strictness"), "failures": pv.get("failures", [])[:3]}
    cross = _load(pd, "06_validation/cross_load.json")
    metrics["cross_load"] = None if not cross else cross.get("classification")
    ridx = _load(pd, "07_agent_handoff/reconstruction_index.json")
    fam = next((e for e in (ridx or []) if isinstance(e, dict) and e.get("role") == "WAVESHAPER"), None)
    metrics["waveshaper_fit"] = None if fam is None else {"family": fam.get("family"), "rmse": fam.get("rmse"), "compiled": fam.get("compiled"), "expected_family": "tanh_normalized"}

    # ---- gates per phase (EXECUTE) --------------------------------------------
    gates = [
        {"phase": 1, "name": "RTTI classes ≥ 95 % recovered", "ok": metrics["rtti_classes_recovered"]["ratio"] >= 0.95, "detail": json.dumps(metrics["rtti_classes_recovered"])},
        {"phase": 1, "name": "resources 100 % VALID_EXACT", "ok": valid == len(truth["resources"]), "detail": f"{valid}/{len(truth['resources'])}"},
        {"phase": 1, "name": "BinaryData names present", "ok": len(metrics["binarydata_names_present"]["seen"]) == len(truth["resources"]), "detail": json.dumps(metrics["binarydata_names_present"]["seen"])},
        {"phase": 1, "name": "serialized keys found", "ok": len(found_keys) == len(param_fields), "detail": f"{len(found_keys)}/{len(param_fields)} <PARAM> keys"},
        {"phase": 2, "name": "all state fields found (static ∪ runtime)", "ok": None if metrics["state_fields_found"] is None else metrics["state_fields_found"]["found"] == metrics["state_fields_found"]["expected"], "detail": "runtime stage not run" if metrics["state_fields_found"] is None else json.dumps(metrics["state_fields_found"])},
        {"phase": 1, "name": "0 illegal paths", "ok": not illegal, "detail": str(len(illegal))},
        {"phase": 1, "name": "no static key promoted to parameter", "ok": not promoted, "detail": str(len(promoted))},
        {"phase": 2, "name": "identity VERIFIED_RUNTIME", "ok": None if metrics["identity"] is None else (metrics["identity"]["vendor_ok"] and metrics["identity"]["product_ok"]), "detail": "runtime stage not run" if metrics["identity"] is None else json.dumps(metrics["identity"])},
        {"phase": 2, "name": "100 % parameters (ids, titles, steps, defaults, units)", "ok": None if metrics["parameters"] is None else all(metrics["parameters"][k] == metrics["parameters"]["expected"] for k in ("found", "defaults_ok", "steps_ok", "units_ok", "types_ok")), "detail": "runtime stage not run" if metrics["parameters"] is None else json.dumps({k: v for k, v in metrics["parameters"].items() if k != "detail"})},
        {"phase": 2, "name": "100 % state fields mapped; decoy classified from runtime", "ok": None if metrics["state_fields_mapped"] is None else (metrics["state_fields_mapped"]["correct"] == metrics["state_fields_mapped"]["expected"] and metrics["state_fields_mapped"]["decoy_classified_from_runtime"]), "detail": "correlation not run" if metrics["state_fields_mapped"] is None else json.dumps(metrics["state_fields_mapped"])},
        {"phase": 3, "name": "processBlock, prepareToPlay, state functions located", "ok": None if metrics["process_block_path"] is None else all(v for k, v in metrics["process_block_path"].items() if k != "basis"), "detail": "decompiler stage not run" if metrics["process_block_path"] is None else json.dumps(metrics["process_block_path"])},
        {"phase": 3, "name": "waveshaper and filter in top-5 DSP candidates", "ok": None if metrics["dsp_function_identification"] is None else (metrics["dsp_function_identification"]["waveshaper_in_top5"] and metrics["dsp_function_identification"]["filter_in_top5"]), "detail": "decompiler stage not run" if metrics["dsp_function_identification"] is None else json.dumps(metrics["dsp_function_identification"]["top5"])},
        {"phase": 3, "name": "fingerprints stable across Release+PDB and stripped", "ok": None if metrics["fingerprint_stability"] is None else bool(metrics["fingerprint_stability"].get("ok")), "detail": "needs the three builds" if metrics["fingerprint_stability"] is None else json.dumps(metrics["fingerprint_stability"])},
        {"phase": 4, "name": "waveshaper family recovered (tanh_normalized) and compiled into Active", "ok": None if metrics["waveshaper_fit"] is None else (metrics["waveshaper_fit"]["family"] in ("tanh_normalized", "tanh") and bool(metrics["waveshaper_fit"]["compiled"])), "detail": "reconstruction not run" if metrics["waveshaper_fit"] is None else json.dumps(metrics["waveshaper_fit"])},
        {"phase": 4, "name": "SURROGATE build green", "ok": None if metrics["build"] is None else metrics["build"]["status"] == "BUILT", "detail": "build stage not run" if metrics["build"] is None else json.dumps(metrics["build"])},
        {"phase": 4, "name": "pluginval strictness ≥ 5 green", "ok": None if metrics["pluginval"] is None or metrics["pluginval"]["status"] == "NOT_RUN" else metrics["pluginval"]["status"] == "PASSED", "detail": "pluginval not run" if metrics["pluginval"] is None else json.dumps(metrics["pluginval"])},
        {"phase": 4, "name": "waveshaper BEHAVIORALLY_EQUIVALENT (differential, ramp probes: RMSE ≤ 1e-4, spectrum ≤ 0.1 dB)", "ok": None if metrics["waveshaper_differential"] is None else metrics["waveshaper_differential"]["classification"] in ("BIT_EXACT", "NUMERICALLY_EQUIVALENT", "BEHAVIORALLY_EQUIVALENT"), "detail": "differential harness not run" if metrics["waveshaper_differential"] is None else json.dumps(metrics["waveshaper_differential"])},
        {"phase": 4, "name": "state CROSS_LOAD_VALIDATED both ways", "ok": None if metrics["cross_load"] is None else metrics["cross_load"] == "CROSS_LOAD_VALIDATED", "detail": "differential harness not run" if metrics["cross_load"] is None else str(metrics["cross_load"])},
    ]
    current = [g for g in gates if g["phase"] <= phase]
    return {
        "job_id": job.job_id, "truth_spec_sha256": truth.get("spec_sha256", ""), "phase_thresholds": phase,
        "metrics": metrics, "gates": gates, "false_positives": fps, "false_negatives": fns,
        "ok_for_phase": all(g["ok"] is True for g in current),
        "pending": [g["name"] for g in current if g["ok"] is None],
    }


def h_ground_truth(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    truth_path = Path(params["truth"]) if params.get("truth") else default_truth_path()
    if truth_path is None or not truth_path.is_file():
        raise api.ApiError("not_found", "truth.json not found; run fixtures/groundtruth/gen.py or pass truth=")
    truth = read_json(truth_path, expect="artifactbench.ground_truth")["data"]
    report = compare(job, truth, phase=int(params.get("phase", 1)))
    write_json(Path(job.project_dir) / "06_validation" / "GROUND_TRUTH_REPORT.json", "artifactbench.ground_truth_report", report)
    # ADDENDUM B5: the known-source validation report — separate metrics, failure classes, benchmark integrity
    from ab_engine.groundtruth import known_source as ks_mod  # noqa: PLC0415

    pd = Path(job.project_dir)
    manifest = _load(pd, "00_manifest/input_manifest.json") or {}
    fx = ks_mod.load_fixture_manifest(truth_path)
    ks = ks_mod.metrics_from_report(report, truth, project_dir=pd)
    src_dir = truth_path.parent / "Source"
    integ = ks_mod.integrity(job.context, manifest, src_dir if src_dir.is_dir() else None)
    ks["integrity"] = integ
    ks["fixture_manifest"] = fx
    write_json(pd / "06_validation" / "known_source_metrics.json", "artifactbench.known_source_metrics", ks)
    (pd / "06_validation" / "KNOWN_SOURCE_VALIDATION_REPORT.md").write_text(ks_mod.to_markdown(ks, integ, fx), encoding="utf-8")
    report["known_source"] = {"metrics": "06_validation/known_source_metrics.json", "report": "06_validation/KNOWN_SOURCE_VALIDATION_REPORT.md", "integrity_ok": integ["ok"], "failure_classes": ks["failure_classes"]}
    # ADDENDUM A6/B7: the evaluator's reports are checkpointed like every other project artefact (no dirty tree after a run)
    try:
        from ab_engine import checkpoint  # noqa: PLC0415

        if (pd / ".git").is_dir():
            report["checkpoint"] = checkpoint.commit(pd, "GROUND_TRUTH", job_id=job.job_id)
    except Exception as exc:  # noqa: BLE001 — a checkpoint problem never fails the evaluation
        report["checkpoint"] = {"status": "GIT_ERROR", "detail": f"{type(exc).__name__}: {exc}"[:200]}
    return report


api.register("groundtruth.compare", h_ground_truth)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("ground-truth", "score a job against fixtures/groundtruth/truth.json → GROUND_TRUTH_REPORT.json")
def _cli_gt(p):
    p.add_argument("job_id")
    p.add_argument("--truth")
    p.add_argument("--phase", type=int, default=1)
    p.add_argument("--allow-pending", action="store_true", help="exit 0 when no gate FAILS even if some are still PENDING (a tool stage did not run)")

    def run(args, ws):
        r = api.dispatch("groundtruth.compare", {"job_id": args.job_id, "truth": args.truth, "phase": args.phase}, ws)
        if args.allow_pending:
            r["ok_for_phase"] = all(g["ok"] is not False for g in r["gates"] if g["phase"] <= args.phase)
        if args.text:
            for g in r["gates"]:
                mark = "PASS" if g["ok"] else "PENDING" if g["ok"] is None else "FAIL"
                sys.stdout.write(f"P{g['phase']} {mark:<8} {g['name']}: {g['detail']}\n")
            sys.stdout.write(f"false positives: {len(r['false_positives'])} · false negatives: {len(r['false_negatives'])} · phase {r['phase_thresholds']} {'OK' if r['ok_for_phase'] else 'NOT OK'}\n")
        else:
            sys.stdout.write(json.dumps({"ok": r["ok_for_phase"], "data": r}, indent=2) + "\n")
        return 0 if r["ok_for_phase"] else 1
    p.set_defaults(func=run)
