"""VALIDATION_COMPLETE stage — the COMPARE rail entry (EXECUTE 4.3, SPEC §11).

Replays every recorded original render on the rebuilt plugin (vst3host, isolated), compares
audio per render and per module (``validate.harness``), cross-loads state both ways, and writes

  06_validation/differential_results.json   artifactbench.differential_results
  06_validation/cross_load.json             artifactbench.cross_load
  06_validation/VALIDATION.md               human summary
  06_validation/rebuild_renders/            only the renders that are not ≥ BEHAVIORALLY_EQUIVALENT (inspection)

and updates the ``validation`` / ``classification`` fields of 07_agent_handoff/reconstruction_index.json.
Modules are never promoted here: promotion is a reconstruction-stage decision on fit evidence; this
stage records what the rebuild actually does, including FAILED with the failing renders.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from ab_engine import TOOL, api
from ab_engine.behavior import metrics as m
from ab_engine.behavior import probes
from ab_engine.contracts import write_json
from ab_engine.jobs import runner
from ab_engine.jobs.runner import StageContext, StageFailed, StageImpl, StageSkipped
from ab_engine.runtime.api import _loadable, _primary_plugin
from ab_engine.runtime.host import HostError, Vst3Host
from ab_engine.validate import harness
from ab_engine.workspace import Workspace

STAGE_VERSION = 3  # 3: windowed ramp comparison, unity-peak scaling, module split (default vs sweeps)


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")).get("data") if p.is_file() else None


def rebuild_bundle(project: Path) -> Path | None:
    rep = _load(project / "06_validation" / "build_report.json") or {}
    inst = rep.get("installed")
    if inst and (project / inst).exists():
        return project / inst
    return None


def stage_validate(ctx: StageContext) -> None:
    host = Vst3Host(ctx.ws, ctx.ws.logs / ctx.job.job_id, timeout=float(ctx.options.get("host_timeout_s", 120)))
    if not host.available:
        raise StageSkipped("vst3host not built: run native/vst3host/build_all.{sh,ps1}")
    reb = rebuild_bundle(ctx.project_dir)
    if reb is None:
        raise StageSkipped("no rebuilt plugin (BUILD_COMPLETE did not produce a bundle)")
    meas = _load(ctx.project_dir / "05_reference_behavior" / "measurements.json")
    if not meas:
        raise StageSkipped("no reference measurements (BEHAVIOR_COMPLETE did not run)")
    orig = _loadable(_primary_plugin(ctx))
    reb = _loadable(reb)
    model = _load(ctx.project_dir / "04_reconstruction" / "reconstruction_model.json") or {}
    laws: dict[str, Any] = {"_titles": {}}
    for ws in model.get("modules", []):
        for mo in ws.get("modulation", []):
            laws[mo["key"]] = mo["law"]
            laws["_titles"][mo["key"]] = mo["title"]
    val = ctx.project_dir / "06_validation"
    keep_dir = val / "rebuild_renders"
    keep_dir.mkdir(parents=True, exist_ok=True)
    tmp = ctx.ws.tmp / f"validate-{ctx.job.job_id}"
    tmp.mkdir(parents=True, exist_ok=True)
    renders: list[dict[str, Any]] = []
    per_module: dict[str, list[str]] = {}
    per_module_rows: dict[str, list[str]] = {}
    items = [r for r in meas.get("renders", []) if r.get("ok") and r.get("object") and ctx.store.has(r["object"])]
    for i, item in enumerate(items):
        ctx.check_cancel()
        ctx.progress(f"replay {i + 1}/{len(items)} {item['id']}")
        wav = tmp / f"{item['id']}.wav"
        row: dict[str, Any] = {"id": item["id"], "probe": item["probe"], "sr": item["sr"], "block": item["block"], "params": item.get("params", {}), "sweep": item.get("sweep")}
        try:
            r = host.call("render", reb, probe=item["probe"], sample_rate=item["sr"], block_size=item["block"], frames=item["frames"], params=item.get("params", {}), out=str(wav))
        except HostError as exc:
            row.update({"classification": "FAILED", "error": exc.code, "detail": exc.detail[:300]})
            renders.append(row)
            for mod in harness.module_of(item, laws):
                per_module.setdefault(mod, []).append("FAILED")
                per_module_rows.setdefault(mod, []).append(item["id"])
            continue
        yo, sro = m.read_wav(ctx.store.get_path(item["object"]))
        yr, srr = m.read_wav(wav)
        window = (probes.ramp_lead_in(int(item["frames"])), int(item["frames"])) if item["probe"] == "ramp" else None
        cmp = harness.compare_renders(yo[0] if yo.shape[0] else yo.reshape(-1), yr[0] if yr.shape[0] else yr.reshape(-1), float(item["sr"]),
                                      int(item.get("latency_reported") or 0), int(r["data"].get("latency_reported") or 0), window=window)
        cmp["tail_delta"] = (r["data"].get("tail_last_sample") or 0) - (item.get("tail_last_sample") or 0)
        cmp["channels"] = [int(yo.shape[0]), int(yr.shape[0])]
        sha, _ = ctx.store.put_file(wav)
        row.update(cmp | {"object": sha, "original_object": item["object"]})
        if harness.ORDER.index(cmp["classification"]) > harness.ORDER.index("BEHAVIORALLY_EQUIVALENT"):
            shutil.copyfile(wav, keep_dir / f"{item['id']}.wav")
            row["kept"] = f"06_validation/rebuild_renders/{item['id']}.wav"
        wav.unlink(missing_ok=True)
        renders.append(row)
        for mod in harness.module_of(item, laws):
            per_module.setdefault(mod, []).append(cmp["classification"])
            per_module_rows.setdefault(mod, []).append(item["id"])
    shutil.rmtree(tmp, ignore_errors=True)

    by_id = {r["id"]: r for r in renders}
    modules = []
    for name, classes in per_module.items():
        ids = per_module_rows[name]
        rows = [by_id[i] for i in ids]
        rm = [r["rmse"] for r in rows if r.get("rmse") is not None]
        sp = [r["spectrum_diff_db"] for r in rows if r.get("spectrum_diff_db") is not None]
        role = {"Waveshaper": "WAVESHAPER", "WaveshaperSweeps": "WAVESHAPER_LAWS", "FrequencyResponse": "FILTER", "LatencyAndRateStability": "RUNTIME", "AliasingAndNoise": "OVERSAMPLER", "Plugin": "AUDIO_LOOP", "SilenceAndDC": "RUNTIME"}.get(name.split(":")[0], "PARAMETER_UPDATE" if name.startswith("Law:") else "UNKNOWN")
        li = [r.get("lead_in_rmse") for r in rows if r.get("lead_in_rmse") is not None]
        modules.append({"module": name, "role": role, "classification": harness.worst(classes), "renders": len(rows),
                        "worst_rmse": max(rm) if rm else None, "worst_spectrum_diff_db": max(sp) if sp else None,
                        "latency_delta": sorted({r.get("latency_delta") for r in rows if r.get("latency_delta") is not None}),
                        "worst_lead_in_rmse": max(li) if li else None, "worst_rmse_full": max((r["rmse_full"] for r in rows if r.get("rmse_full") is not None), default=None),
                        "failing": [r["id"] for r in rows if harness.ORDER.index(r["classification"]) > harness.ORDER.index("BEHAVIORALLY_EQUIVALENT")][:20],
                        "basis": "worst render classification; sample error after reported-latency compensation, spectral diff on 1/3-octave bands to 20 kHz"})
    modules.sort(key=lambda x: (x["module"] != "Waveshaper", x["module"]))

    # ---- state cross-load ------------------------------------------------------------------
    cross: dict[str, Any] = {"classification": "NOT_VALIDATED", "reason": "state baseline missing"}
    base = _load(ctx.project_dir / "01_evidence" / "vst3" / "state_baseline.json") or {}
    keys = [mo["key"] for ws in model.get("modules", []) for mo in ws.get("modulation", [])] or [p["key"] for p in model.get("parameters", []) if p.get("generate")]
    keys = [p["key"] for p in model.get("parameters", []) if p.get("generate")] or keys
    if base.get("component_state_b64"):
        try:
            rs = host.call("state", reb)["data"]
            a_orig = harness.parse_params(base.get("component_state_text"))
            b_orig = harness.parse_params(rs.get("component_state_text"))
            a_to_b = harness.parse_params(host.call("state", reb, component_state_b64=base["component_state_b64"])["data"].get("component_state_text"))
            b_to_a = harness.parse_params(host.call("state", orig, component_state_b64=rs["component_state_b64"])["data"].get("component_state_text"))
            cross = harness.cross_load_verdict(a_to_b, a_orig, b_to_a, b_orig, keys) | {"state_size": [base.get("component_state_size"), rs.get("component_state_size")]}
        except HostError as exc:
            cross = {"classification": "FAILED", "reason": f"{exc.code}: {exc.detail[:300]}"}
    write_json(val / "cross_load.json", "artifactbench.cross_load", cross)

    overall = harness.worst([x["classification"] for x in modules]) if modules else "NOT_VALIDATED"
    write_json(val / "differential_results.json", "artifactbench.differential_results",
               {"original": str(orig), "rebuild": str(reb), "renders": renders, "modules": modules, "overall": overall, "cross_load": cross["classification"],
                "thresholds": {"BEHAVIORALLY_EQUIVALENT": "RMSE ≤ 1e-4, spectrum ≤ 0.1 dB to 20 kHz, latency delta 0", "PERCEPTUALLY_CLOSE": "RMSE ≤ 1e-2, spectrum ≤ 1 dB",
                               "level": "signals hotter than unity are scaled to the original's peak", "ramp": "classified on the measurement window after the settle lead-in (D-017); lead-in error reported per render"}})
    for rel in ("06_validation/differential_results.json", "06_validation/cross_load.json"):
        ctx.output(rel)

    # ---- update the reconstruction index ----------------------------------------------------
    idx_path = ctx.project_dir / "07_agent_handoff" / "reconstruction_index.json"
    idx = _load(idx_path)
    if isinstance(idx, list):
        mod_by = {x["module"]: x for x in modules}
        for e in idx:
            if e.get("role") == "WAVESHAPER" and "Waveshaper" in mod_by:
                w = mod_by["Waveshaper"]
                e["validation"] = w["classification"]
                sw = mod_by.get("WaveshaperSweeps")
                e["validation_detail"] = {"default": {"renders": w["renders"], "worst_rmse": w["worst_rmse"], "worst_spectrum_diff_db": w["worst_spectrum_diff_db"], "failing": w["failing"]},
                                          "sweeps": None if sw is None else {"classification": sw["classification"], "renders": sw["renders"], "worst_rmse": sw["worst_rmse"], "worst_lead_in_rmse": sw.get("worst_lead_in_rmse"), "failing": sw["failing"]},
                                          "laws": {x["module"][4:]: x["classification"] for x in modules if x["module"].startswith("Law:")}}
                e["validation_sweeps"] = None if sw is None else sw["classification"]
                if sw is not None and harness.ORDER.index(sw["classification"]) > harness.ORDER.index("BEHAVIORALLY_EQUIVALENT"):
                    e.setdefault("todos", []).append(f"parameter sweeps reach {sw['classification']} (worst RMSE {sw['worst_rmse']:.1e} on {', '.join(sw['failing'][:4])}); lead-in error {sw.get('worst_lead_in_rmse')}: the original's parameter smoothing and any fractional-sample latency are not modelled")
            if e.get("symbol", "").endswith("AudioProcessor") and e.get("compiled"):
                e["validation"] = overall
                e["state_compatibility"] = cross["classification"]
        from ab_engine.knowledge import hooks as knowledge_hooks  # noqa: PLC0415

        knowledge_hooks.after_validation(ctx, modules=modules, index=idx, measurements_hash=hashlib.sha256(json.dumps(meas.get("probe_set")).encode()).hexdigest()[:16])
        write_json(idx_path, "artifactbench.reconstruction_index", idx)
        ctx.output("07_agent_handoff/reconstruction_index.json")

    md = ["# 06_validation — differential harness", "", f"Original `{orig.name}` vs rebuild `{reb.name}` on {len(renders)} identical renders.", "",
          f"**Overall: {overall}** · state cross-load: **{cross['classification']}**", "", "| module | role | class | renders | worst RMSE | worst Δspectrum dB | worst lead-in RMSE | failing |", "|---|---|---|---|---|---|---|---|"]
    for x in modules:
        rm_s = "" if x["worst_rmse"] is None else f"{x['worst_rmse']:.2e}"
        sp_s = "" if x["worst_spectrum_diff_db"] is None else f"{x['worst_spectrum_diff_db']:.2f}"
        li_s = "" if x["worst_lead_in_rmse"] is None else f"{x['worst_lead_in_rmse']:.2e}"
        md.append(f"| {x['module']} | {x['role']} | {x['classification']} | {x['renders']} | {rm_s} | {sp_s} | {li_s} | {', '.join(x['failing'][:6])} |")
    md += ["", "Renders that are not ≥ BEHAVIORALLY_EQUIVALENT are kept under rebuild_renders/ for inspection; every render's rebuild audio is in the object store.", ""]
    (val / "VALIDATION.md").write_text("\n".join(md), encoding="utf-8")
    ctx.output("06_validation/VALIDATION.md")
    ws_mod = next((x for x in modules if x["module"] == "Waveshaper"), None)
    ctx.metrics.update({"renders": len(renders), "overall": overall, "cross_load": cross["classification"],
                        "modules": {x["module"]: x["classification"] for x in modules},
                        "waveshaper_rmse": (f"{ws_mod['worst_rmse']:.2e}" if ws_mod and ws_mod.get("worst_rmse") is not None else "n/a")})
    if not renders:
        raise StageFailed("VALIDATION_FAILED", "no render could be replayed on the rebuild")
    ctx.completeness = "NOT_APPLICABLE"


runner.register_stage(StageImpl("VALIDATION_COMPLETE", version=STAGE_VERSION, run=stage_validate, tool_version=TOOL, config_keys=("host_timeout_s",)))


def h_compare(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """Compare two WAV files (original, rebuild) at a sample rate with reported latencies — used by tests and the CLI."""
    yo, sro = m.read_wav(Path(str(params["a"])))
    yr, srr = m.read_wav(Path(str(params["b"])))
    return harness.compare_renders(yo[0], yr[0], float(params.get("sr", sro)), int(params.get("latency_a", 0)), int(params.get("latency_b", 0)))


api.register("validate.compare", h_compare)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("compare-wav", "differential comparison of two renders (original, rebuild)")
def _cli(p):
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--latency-a", type=int, default=0)
    p.add_argument("--latency-b", type=int, default=0)

    def run(args, ws):
        r = api.dispatch("validate.compare", {"a": args.a, "b": args.b, "latency_a": args.latency_a, "latency_b": args.latency_b}, ws)
        sys.stdout.write(json.dumps({"ok": True, "data": r}, indent=2) + "\n")
        return 0
    p.set_defaults(func=run)


__all__ = ["stage_validate", "rebuild_bundle"]
