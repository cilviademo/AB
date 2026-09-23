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
from ab_engine.jobs.runner import StageContext, StageImpl, StageSkipped
from ab_engine.reconstruct import generate as gen
from ab_engine.reconstruct import model as model_mod
from ab_engine.workspace import Workspace

STAGE_VERSION = 1


def reconstruct(project: Path, *, build_kind: str = "SURROGATE") -> dict[str, Any]:
    m = model_mod.build(project, build_kind=build_kind)
    out = gen.generate(project, m)
    write_json(project / "07_agent_handoff" / "reconstruction_index.json", "artifactbench.reconstruction_index", out["index"])
    write_json(project / "04_reconstruction" / "reconstruction_model.json", "artifactbench.reconstruction_model",
               {k: v for k, v in m.items() if k != "dsp_functions"} | {"target": out["target"], "resources": out["resources"]})
    md = ["# 04_reconstruction", "", f"Target `{out['target']}` · build kind **{m['build_kind']}** · identity {m['identity'].get('codes_status')}", ""]
    if m["identity"].get("fidelity_refused"):
        md.append(f"> FIDELITY refused: {m['identity']['fidelity_refused']}")
    md += ["", "| symbol | file | status | compiled | rmse |", "|---|---|---|---|---|"]
    for e in out["index"]:
        rmse = "" if e.get("rmse") is None else f"{e['rmse']:.2e}"
        md.append(f"| `{e['symbol']}` | {e['file']} | {e['status']} | {'yes' if e.get('compiled') else 'no'} | {rmse} |")
    md += ["", "Only `Source/Active` is compiled. `human_source/` is the concise idiomatic form of every fitted module; `evidence_source/` is decompiler pseudo-C; `Source/RecoveredScaffolds/` is never built.", ""]
    (project / "04_reconstruction" / "RECONSTRUCTION.md").write_text("\n".join(md), encoding="utf-8")
    out["written"] += ["07_agent_handoff/reconstruction_index.json", "04_reconstruction/reconstruction_model.json", "04_reconstruction/RECONSTRUCTION.md"]
    out["model"] = m
    return out


def stage_reconstruct(ctx: StageContext) -> None:
    if not (ctx.project_dir / "01_evidence" / "vst3" / "runtime_parameters.json").is_file():
        raise StageSkipped("runtime evidence missing (RUNTIME_COMPLETE did not run): the parameter layout gate needs VST3_EXPORTED_PARAMETER rows")
    kind = str(ctx.options.get("build_kind", "SURROGATE")).upper()
    ctx.progress("deriving reconstruction model")
    out = reconstruct(ctx.project_dir, build_kind=kind)
    m = out["model"]
    for rel in out["written"]:
        ctx.output(rel)
    if m["identity"].get("fidelity_refused"):
        ctx.warn("FIDELITY_REFUSED", m["identity"]["fidelity_refused"])
    if not (ctx.project_dir / "05_reference_behavior" / "transfer_curves" / "ramp_48k_256.json").is_file():
        ctx.warn("NO_BEHAVIOR", "BEHAVIOR_COMPLETE did not run: no module could be fitted; Active is a verified shell only")
    for ws in m["modules"]:
        if not ws["active"]:
            ctx.warn("MODULE_NOT_ACTIVE", f"{ws['name']}: fit RMSE {ws['rmse']:.2e} > {model_mod.ACTIVE_RMSE:g}; kept in human_source only")
    ctx.metrics.update(out["summary"] | {"modules_detail": [{"name": ws["name"], "family": ws["family"], "rmse": ws["rmse"], "active": ws["active"],
                                                             "laws": {mo["key"]: mo["law"] for mo in ws["modulation"]}} for ws in m["modules"]]})
    ctx.completeness = "NOT_APPLICABLE"


runner.register_stage(StageImpl("RECONSTRUCTION_COMPLETE", version=STAGE_VERSION, run=stage_reconstruct, tool_version=TOOL, config_keys=("build_kind",)))


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
