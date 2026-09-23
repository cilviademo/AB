"""RECONSTRUCTION_COMPLETE stage — the RECONSTRUCT rail entry (EXECUTE 4.2, SPEC §10).

Derives the evidence model (parameters, state, fitted modules, scaffolds, identity) and writes
04_reconstruction/{human_source,evidence_source,Source/Active,CMakeLists.txt} plus
07_agent_handoff/reconstruction_index.json. Gates are enforced in ``reconstruct.model``:
only a module at ≥ BEHAVIORALLY_EQUIVALENT reaches Source/Active; FIDELITY identity only
with a VERIFIED_RUNTIME factory identity.

Options: ``build_kind`` (SURROGATE | FIDELITY; FIDELITY falls back to SURROGATE without a
verified identity and the fallback is recorded).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ab_engine import TOOL, api
from ab_engine.contracts import write_json
from ab_engine.jobs import runner
from ab_engine.jobs.runner import StageContext, StageFailed, StageImpl, StageSkipped
from ab_engine.reconstruct import generate as gen
from ab_engine.reconstruct import model as model_mod
from ab_engine.workspace import Workspace

STAGE_VERSION = 5  # 4–5: decompiler-only classes (stripped builds) are indexed and get evidence-only scaffold headers; 3: transformed process() binds input block by const reference (MODERNIZE build fix); 2: recovery goal, recovered_source/transformed_source, transformation graph, identifier map (ADDENDUM C3)


def reconstruct(project: Path, *, build_kind: str = "SURROGATE", goal: str = "PRESERVE_ORIGINAL", switches: dict[str, str] | None = None,
                naming: str | None = None, naming_terms: list[str] | None = None) -> dict[str, Any]:
    from ab_engine.naming import api as naming_api  # noqa: PLC0415
    from ab_engine.transform import goals as goals_mod  # noqa: PLC0415
    from ab_engine.transform import graph as graph_mod  # noqa: PLC0415

    plan = goals_mod.plan(goal, switches or dict(goals_mod.SWITCHES))
    m = model_mod.build(project, build_kind=build_kind)
    # naming layer first (the generator reads canonical names); default mode follows the goal (naming directive §5)
    imap = naming_api.build_for_project(project, mode=(naming or plan["naming_default"]).upper(), terms=naming_terms or [])
    out = gen.generate(project, m, plan=plan, imap=imap)
    lic_entries = [e for e in out["index"] if e.get("role") in ("LICENSING_AND_ENTITLEMENT_SUBSYSTEM", "PROTECTED_SUBSYSTEM")]
    graph = graph_mod.build(m, plan, imap, licensing_entries=lic_entries)
    write_json(project / "04_reconstruction" / "transformation_graph.json", "artifactbench.transformation_graph", graph)
    out["plan"], out["graph"], out["imap"] = plan, graph, imap
    write_json(project / "07_agent_handoff" / "reconstruction_index.json", "artifactbench.reconstruction_index", out["index"])
    write_json(project / "04_reconstruction" / "reconstruction_model.json", "artifactbench.reconstruction_model",
               {k: v for k, v in m.items() if k != "dsp_functions"} | {"target": out["target"], "resources": out["resources"]})
    md = ["# 04_reconstruction", "", f"Target `{out['target']}` · build kind **{m['build_kind']}** · identity {m['identity'].get('codes_status')} · recovery goal **{plan['goal']}** (Source/Active = {plan['active_variant']} variant"
          + (f"; goal not available: {plan['not_available_reason']}" if plan.get("not_available_reason") else "") + ")", ""]
    if m["identity"].get("fidelity_refused"):
        md.append(f"> FIDELITY refused: {m['identity']['fidelity_refused']}")
    md += ["", "| symbol | file | status | compiled | rmse |", "|---|---|---|---|---|"]
    for e in out["index"]:
        rmse = "" if e.get("rmse") is None else f"{e['rmse']:.2e}"
        md.append(f"| `{e['symbol']}` | {e['file']} | {e['status']} | {'yes' if e.get('compiled') else 'no'} | {rmse} |")
    md += ["", "Only `Source/Active` is compiled. `recovered_source/` is the closest semantic reconstruction of the original (every fitted module); `transformed_source/` the goal's modernized / migrated implementation; `evidence_source/` is decompiler pseudo-C; `Source/RecoveredScaffolds/` is never built.", ""]
    (project / "04_reconstruction" / "RECONSTRUCTION.md").write_text("\n".join(md), encoding="utf-8")
    out["written"] += ["07_agent_handoff/reconstruction_index.json", "04_reconstruction/reconstruction_model.json", "04_reconstruction/RECONSTRUCTION.md",
                       "04_reconstruction/transformation_graph.json", "04_reconstruction/identifier_map.json", "04_reconstruction/IDENTIFIER_MAP.md"]
    out["model"] = m
    return out


def stage_reconstruct(ctx: StageContext) -> None:
    if not (ctx.project_dir / "01_evidence" / "vst3" / "runtime_parameters.json").is_file():
        raise StageSkipped("runtime evidence missing (RUNTIME_COMPLETE did not run): the parameter layout gate needs VST3_EXPORTED_PARAMETER rows")
    kind = str(ctx.options.get("build_kind", "SURROGATE")).upper()
    from ab_engine.transform import goals as goals_mod  # noqa: PLC0415

    try:
        goal = goals_mod.normalize_goal(ctx.options.get("goal", "PRESERVE_ORIGINAL"))
        switches = goals_mod.switches_from_options(ctx.options)
    except ValueError as exc:
        raise StageFailed("BAD_OPTION", str(exc)) from exc
    ctx.progress(f"deriving reconstruction model (goal {goal})")
    out = reconstruct(ctx.project_dir, build_kind=kind, goal=goal, switches=switches, naming=(str(ctx.options["naming"]).upper() if ctx.options.get("naming") else None),
                      naming_terms=[t for t in str(ctx.options.get("naming_terms", "")).split(",") if t.strip()])
    m = out["model"]
    if out["plan"].get("not_available_reason"):
        ctx.warn("GOAL_NOT_AVAILABLE", f"{goal}: {out['plan']['not_available_reason']} — Source/Active stays the recovered implementation")
    for rel in out["written"]:
        ctx.output(rel)
    if m["identity"].get("fidelity_refused"):
        ctx.warn("FIDELITY_REFUSED", m["identity"]["fidelity_refused"])
    if not (ctx.project_dir / "05_reference_behavior" / "transfer_curves" / "ramp_48k_256.json").is_file():
        ctx.warn("NO_BEHAVIOR", "BEHAVIOR_COMPLETE did not run: no module could be fitted; Active is a verified shell only")
    for ws in m["modules"]:
        if not ws["active"]:
            ctx.warn("MODULE_NOT_ACTIVE", f"{ws['name']}: fit RMSE {ws['rmse']:.2e} > {model_mod.ACTIVE_RMSE:g}; kept in human_source only")
    imap = out["imap"]
    ctx.metrics.update(out["summary"] | {"modules_detail": [{"name": ws["name"], "family": ws["family"], "rmse": ws["rmse"], "active": ws["active"],
                                                             "laws": {mo["key"]: mo["law"] for mo in ws["modulation"]}} for ws in m["modules"]],
                                         "naming": {"mode": imap["mode"], "identifiers": len(imap["identifiers"]), "renamed": sum(1 for r in imap["identifiers"] if r["active"] != r["original"].split("::")[-1]), "terms": imap["terms"]},
                                         "transformation": {"goal": goal, "active_variant": out["plan"]["active_variant"], "available": out["plan"]["available"], "nodes": out["graph"]["transformation_nodes"], "switches": switches}})
    ctx.completeness = "NOT_APPLICABLE"


runner.register_stage(StageImpl("RECONSTRUCTION_COMPLETE", version=STAGE_VERSION, run=stage_reconstruct, tool_version=TOOL, config_keys=("build_kind", "naming", "naming_terms", "goal", *sorted(__import__("ab_engine.transform.goals", fromlist=["SWITCHES"]).SWITCHES)), contract=runner.CONTRACTS["RECONSTRUCTION_COMPLETE"]))


def h_reconstruct(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    out = reconstruct(Path(str(params["project_dir"])), build_kind=str(params.get("build_kind", "SURROGATE")).upper())
    return {"summary": out["summary"], "written": out["written"], "index": out["index"]}


api.register("reconstruct.run", h_reconstruct)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("reconstruct", "generate 04_reconstruction from a project folder's evidence (no job needed)")
def _cli(p):
    p.add_argument("project_dir")
    p.add_argument("--build-kind", default="SURROGATE", choices=("SURROGATE", "FIDELITY"))

    def run(args, ws):
        r = api.dispatch("reconstruct.run", {"project_dir": args.project_dir, "build_kind": args.build_kind}, ws)
        sys.stdout.write(json.dumps({"ok": True, "data": {"summary": r["summary"], "written": r["written"]}}, indent=2) + "\n")
        return 0
    p.set_defaults(func=run)


__all__ = ["reconstruct", "stage_reconstruct"]
