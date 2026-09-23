"""Known-source validation (ADDENDUM B5): the evaluator side of a KNOWN_SOURCE_FIXTURE job.

The recovery side only ever saw the binary; here the evaluator holds ``truth.json`` (generated from the
fixture's source) and scores the recovery with metrics that are **never collapsed into one percentage**:
identity accuracy · parameter recall / precision · state-field recall · class recall · class-ownership
precision · DSP-classification precision · resource recall · source-filename recovery · function-match
precision / recall · behavioural error. Every failed gate is classified
``PARSER | CLASSIFICATION | CORRELATION | DECOMPILER | RUNTIME | BEHAVIOR | RECONSTRUCTION | BUILD | VALIDATION | UI``
so systemic errors are fixed before any single fixture is tuned. No fixture facts live in recovery logic —
they come from the fixture manifest and truth.json only (benchmark integrity, checked here too).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FAILURE_CLASS = {
    "RTTI classes": "PARSER", "resources": "PARSER", "BinaryData names": "PARSER", "serialized keys": "PARSER", "illegal paths": "PARSER", "state fields found": "PARSER",
    "no static key promoted": "CLASSIFICATION", "identity": "RUNTIME", "parameters": "RUNTIME", "state fields mapped": "CORRELATION",
    "processBlock": "DECOMPILER", "DSP candidates": "CLASSIFICATION", "fingerprints stable": "DECOMPILER", "waveshaper family": "RECONSTRUCTION",
    "build green": "BUILD", "pluginval": "VALIDATION", "BEHAVIORALLY_EQUIVALENT": "BEHAVIOR", "CROSS_LOAD": "VALIDATION",
}


def _classify_failure(name: str) -> str:
    for key, cls in FAILURE_CLASS.items():
        if key.lower() in name.lower():
            return cls
    return "VALIDATION"


def _ratio(n: int, d: int) -> float | None:
    return None if d == 0 else round(n / d, 4)


def metrics_from_report(report: dict[str, Any], truth: dict[str, Any], *, project_dir: Path | None = None) -> dict[str, Any]:
    m = report.get("metrics", {})
    gates = report.get("gates", [])
    out: dict[str, Any] = {"fixture": truth.get("product"), "never_collapsed": True}
    # identity
    ident = m.get("identity") or {}
    out["identity_accuracy"] = {"vendor": ident.get("vendor_ok"), "product": ident.get("product_ok"), "evidence": ident.get("evidence"), "measured": bool(ident)}
    # parameters: recall = expected found; precision = recovered rows that are real exported parameters (no static key promoted)
    p = m.get("parameters") or {}
    promoted = (m.get("static_keys_promoted_to_parameters") or {})
    n_promoted = promoted.get("promoted", promoted.get("count", 0)) if isinstance(promoted, dict) else 0
    out["parameter_recall"] = {"found": p.get("found"), "expected": p.get("expected"), "ratio": _ratio(int(p.get("found") or 0), int(p.get("expected") or 0)), "defaults_ok": p.get("defaults_ok"), "steps_ok": p.get("steps_ok"), "units_ok": p.get("units_ok")}
    out["parameter_precision"] = {"recovered": p.get("found"), "false_parameters": n_promoted, "ratio": _ratio(int(p.get("found") or 0), int(p.get("found") or 0) + int(n_promoted or 0))}
    # state fields
    sf = m.get("state_fields_found") or {}
    sm = m.get("state_fields_mapped") or {}
    out["state_field_recall"] = {"found": sf.get("found"), "expected": sf.get("expected"), "ratio": _ratio(int(sf.get("found") or 0), int(sf.get("expected") or 0)), "mapped_correct": sm.get("correct"), "decoy_from_runtime": sm.get("decoy_classified_from_runtime")}
    # classes
    rc = m.get("rtti_classes_recovered") or {}
    oa = m.get("ownership_accuracy") or {}
    out["class_recall"] = {"recovered": rc.get("recovered"), "expected": rc.get("expected"), "ratio": rc.get("ratio"), "by_source": rc.get("by_source")}
    out["class_ownership_precision"] = {"expected_owned_classified_owned": oa.get("expected_owned_classified_owned"), "of": oa.get("of"), "framework_misclassified_as_owned": oa.get("framework_misclassified_as_owned"),
                                        "ratio": _ratio(int(oa.get("expected_owned_classified_owned") or 0), int(oa.get("of") or 0))}
    # DSP classification
    dr = m.get("dsp_role_candidates") or {}
    di = m.get("dsp_function_identification") or {}
    out["dsp_classification_precision"] = {"class_roles_matched": dr.get("matched"), "of": dr.get("expected"), "ratio": _ratio(int(dr.get("matched") or 0), int(dr.get("expected") or 0)),
                                           "top5": di.get("top5"), "waveshaper_in_top5": di.get("waveshaper_in_top5"), "filter_in_top5": di.get("filter_in_top5"), "via": [k for k in ("via_knowledge", "via_inlining") if di.get(k)]}
    # resources
    rs = m.get("resources") or {}
    bd = m.get("binarydata_names_present") or {}
    out["resource_recall"] = {"valid_exact": rs.get("valid_exact"), "expected": rs.get("expected"), "ratio": _ratio(int(rs.get("valid_exact") or 0), int(rs.get("expected") or 0)), "binarydata_names": bd.get("seen")}
    # source filenames: PROJECT_SOURCE paths recovered from the binary vs the fixture's source files
    src_expected = sorted({c.split("::")[-1] for c in truth.get("classes", [])})
    found_files: list[str] = []
    if project_dir is not None:
        try:
            bp = json.loads((project_dir / "01_evidence" / "paths" / "build_path_evidence.json").read_text(encoding="utf-8")).get("data")
            rows = bp if isinstance(bp, list) else (bp or {}).get("paths", []) if isinstance(bp, dict) else []
            found_files = sorted({str(r.get("path") or r).replace("\\", "/").split("/")[-1] for r in rows if (isinstance(r, dict) and str(r.get("classification", r.get("class", ""))).startswith("PROJECT_SOURCE")) or isinstance(r, str)})
        except (OSError, ValueError):
            found_files = []
    stems = {f.rsplit(".", 1)[0] for f in found_files}
    out["source_filename_recovery"] = {"recovered_files": found_files[:50], "expected_class_stems": src_expected, "stems_matched": sorted(s for s in src_expected if s in stems),
                                       "ratio": _ratio(sum(1 for s in src_expected if s in stems), len(src_expected)), "note": "a stripped release build carries no source paths: 0 is the honest result there"}
    # functions: seeds located vs truth entry points; inlined attribution counts as located with basis
    pb = m.get("process_block_path") or {}
    expected_fns = ["processBlock", "prepareToPlay", "getStateInformation", "setStateInformation"]
    located = [f for f in expected_fns if (pb.get(f) if f in pb else pb.get("state_functions"))]
    out["function_match"] = {"located": located, "expected": expected_fns, "recall": _ratio(len(located), len(expected_fns)), "basis": pb.get("basis"),
                             "precision_note": "seeds are one address per entry point; a wrong address would fail the behavioural gates rather than this count"}
    # behaviour
    wd = m.get("waveshaper_differential") or {}
    out["behavioral_error"] = {"module": wd.get("module"), "classification": wd.get("classification"), "worst_rmse": wd.get("worst_rmse"), "worst_spectrum_diff_db": wd.get("worst_spectrum_diff_db"),
                               "overall": (m.get("behavioral") or {}).get("Plugin") if isinstance(m.get("behavioral"), dict) else None, "cross_load": m.get("cross_load")}
    # failures by class
    failed = [g for g in gates if g.get("ok") is False]
    out["failures"] = [{"gate": g["name"], "phase": g.get("phase"), "class": _classify_failure(g["name"]), "detail": g.get("detail")} for g in failed]
    out["failure_classes"] = {}
    for f in out["failures"]:
        out["failure_classes"][f["class"]] = out["failure_classes"].get(f["class"], 0) + 1
    out["gates"] = {"pass": sum(1 for g in gates if g.get("ok") is True), "fail": len(failed), "pending": sum(1 for g in gates if g.get("ok") is None)}
    return out


def integrity(job_context: dict[str, Any], manifest: dict[str, Any] | None, fixture_source_dir: Path | None) -> dict[str, Any]:
    """Benchmark integrity: the recovery side must not have seen the fixture source."""
    inputs = (manifest or {}).get("inputs", [])
    leaked = []
    if fixture_source_dir is not None:
        src_names = {p.name for p in fixture_source_dir.rglob("*") if p.is_file()}
        leaked = [i["path"] for i in inputs if i.get("kind") == "source" and i["path"].replace("\\", "/").split("/")[-1] in src_names]
    return {"usage_context": job_context.get("usage_context"), "source_availability": job_context.get("source_availability"),
            "context_declared_known_source": job_context.get("usage_context") == "KNOWN_SOURCE_FIXTURE",
            "fixture_source_in_recovery_inputs": leaked, "ok": not leaked,
            "rule": "source is withheld from every recovery stage and read only by this evaluator (ADDENDUM B5 / C1)"}


def to_markdown(ks: dict[str, Any], integ: dict[str, Any], manifest: dict[str, Any] | None) -> str:
    def r(v):
        return "n/a" if v is None else (f"{v:.0%}" if isinstance(v, float) and v <= 1 else str(v))

    lines = [f"# KNOWN_SOURCE_VALIDATION_REPORT — {ks.get('fixture')}", "",
             f"Fixture manifest: {(manifest or {}).get('fixture_id', 'n/a')} · licence {(manifest or {}).get('license_class', 'UNKNOWN')} ({(manifest or {}).get('license', 'n/a')}) · build {(manifest or {}).get('build_configuration', 'n/a')} · compiler {(manifest or {}).get('compiler', 'n/a')}",
             f"Benchmark integrity: context `{integ.get('usage_context')}` / `{integ.get('source_availability')}` · fixture source in recovery inputs: {integ.get('fixture_source_in_recovery_inputs') or 'none'} → {'OK' if integ.get('ok') else 'VIOLATED'}", "",
             "Metrics are reported separately, never as one percentage (ADDENDUM B5).", "",
             "| metric | value | detail |", "|---|---|---|",
             f"| identity accuracy | vendor {ks['identity_accuracy']['vendor']} · product {ks['identity_accuracy']['product']} | {ks['identity_accuracy']['evidence']} |",
             f"| parameter recall | {r(ks['parameter_recall']['ratio'])} | {ks['parameter_recall']['found']}/{ks['parameter_recall']['expected']}; defaults {ks['parameter_recall']['defaults_ok']}, steps {ks['parameter_recall']['steps_ok']}, units {ks['parameter_recall']['units_ok']} |",
             f"| parameter precision | {r(ks['parameter_precision']['ratio'])} | false parameters (static keys promoted): {ks['parameter_precision']['false_parameters']} |",
             f"| state-field recall | {r(ks['state_field_recall']['ratio'])} | {ks['state_field_recall']['found']}/{ks['state_field_recall']['expected']}; mapped correct {ks['state_field_recall']['mapped_correct']}; decoy from runtime {ks['state_field_recall']['decoy_from_runtime']} |",
             f"| class recall | {r(ks['class_recall']['ratio'])} | {ks['class_recall']['recovered']}/{ks['class_recall']['expected']} by source {ks['class_recall']['by_source']} |",
             f"| class-ownership precision | {r(ks['class_ownership_precision']['ratio'])} | framework misclassified as owned: {ks['class_ownership_precision']['framework_misclassified_as_owned']} |",
             f"| DSP-classification precision | {r(ks['dsp_classification_precision']['ratio'])} | top-5 {ks['dsp_classification_precision']['top5']} via {ks['dsp_classification_precision']['via'] or 'symbols/structure'} |",
             f"| resource recall | {r(ks['resource_recall']['ratio'])} | {ks['resource_recall']['valid_exact']}/{ks['resource_recall']['expected']} VALID_EXACT; BinaryData names {ks['resource_recall']['binarydata_names']} |",
             f"| source-filename recovery | {r(ks['source_filename_recovery']['ratio'])} | {ks['source_filename_recovery']['stems_matched']} of {ks['source_filename_recovery']['expected_class_stems']} ({ks['source_filename_recovery']['note']}) |",
             f"| function match (entry points) | recall {r(ks['function_match']['recall'])} | {ks['function_match']['located']} — basis: {ks['function_match']['basis']} |",
             f"| behavioural error | {ks['behavioral_error']['classification']} | worst RMSE {ks['behavioral_error']['worst_rmse']}, Δspectrum {ks['behavioral_error']['worst_spectrum_diff_db']} dB; overall {ks['behavioral_error']['overall']}; cross-load {ks['behavioral_error']['cross_load']} |",
             "", f"Gates: {ks['gates']['pass']} pass · {ks['gates']['fail']} fail · {ks['gates']['pending']} pending", ""]
    if ks["failures"]:
        lines += ["## Failures by class (fix systemic classes before tuning a fixture)", ""] + [f"- **{f['class']}** — {f['gate']} (phase {f['phase']}): {f['detail']}" for f in ks["failures"]] + [""]
    return "\n".join(lines)


def load_fixture_manifest(truth_path: Path) -> dict[str, Any] | None:
    p = truth_path.parent / "fixture.json"
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc.get("data", doc)
    except (OSError, ValueError):
        return None


__all__ = ["metrics_from_report", "integrity", "to_markdown", "load_fixture_manifest", "FAILURE_CLASS"]
