"""BEHAVIOR_COMPLETE stage — the PROBE rail entry (EXECUTE 4.1, SPEC §11).

Renders deterministic probes through the ORIGINAL plugin with vst3host:
* every probe at the base rate/block (48 kHz, 256)
* impulse + 1 kHz sine at 44.1/48/96 kHz × block sizes 32…1024 (latency/tail/response stability)
* the amplitude ramp with each exported parameter varied alone at 0, .25, .5, .75, 1
  (transfer curves per parameter position; fitted by family, chosen by residual)
Audio goes to the object store and is materialised under 05_reference_behavior/original_renders/;
metrics to measurements.json; fits to transfer_curves/*.json. One parameter varies at a time
from the verified default; every render records the exact request so it can be replayed on the
rebuild by the differential harness (Phase 4.3).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from ab_engine import TOOL, api
from ab_engine.behavior import fit as fit_mod
from ab_engine.behavior import metrics as m
from ab_engine.behavior import probes
from ab_engine.contracts import write_json
from ab_engine.jobs import runner
from ab_engine.jobs.runner import StageContext, StageFailed, StageImpl, StageSkipped
from ab_engine.runtime.api import _loadable, _primary_plugin
from ab_engine.runtime.host import HostError, Vst3Host
from ab_engine.workspace import Workspace

STAGE_VERSION = 2  # 2: ramp probe settle lead-in (D-017), sweep ramps 2 s
BASE_SR, BASE_BLOCK = 48000.0, 256
POSITIONS = (0.0, 0.25, 0.5, 0.75, 1.0)


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")).get("data") if p.is_file() else None


def render_plan(params: list[dict[str, Any]], *, quick: bool) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for probe in probes.PROBES:
        plan.append({"id": f"{probe}_48k_256", "probe": probe, "sr": BASE_SR, "block": BASE_BLOCK, "params": {}, "frames": 2 * int(BASE_SR)})
    for probe in ("impulse", "sine1k"):
        for sr in probes.RATES:
            for block in (probes.BLOCKS if not quick else (32, 256, 1024)):
                if sr == BASE_SR and block == BASE_BLOCK:
                    continue
                plan.append({"id": f"{probe}_{int(sr)}_{block}", "probe": probe, "sr": sr, "block": block, "params": {}, "frames": int(sr)})
    for p in params:
        if p.get("is_readonly") or p.get("is_bypass"):
            continue
        for pos in (POSITIONS if not quick else (0.0, 1.0)):
            plan.append({"id": f"ramp_{p['title'].replace(' ', '_')}_{pos}", "probe": "ramp", "sr": BASE_SR, "block": BASE_BLOCK,
                         "params": {str(p["param_id"]): pos}, "frames": 2 * int(BASE_SR), "sweep": {"param_id": p["param_id"], "title": p["title"], "normalized": pos}})
    return plan


def stage_behavior(ctx: StageContext) -> None:
    host = Vst3Host(ctx.ws, ctx.ws.logs / ctx.job.job_id, timeout=float(ctx.options.get("host_timeout_s", 120)))
    if not host.available:
        raise StageSkipped("vst3host not built: run native/vst3host/build_all.{sh,ps1}")
    plugin = _loadable(_primary_plugin(ctx))
    params = _load(ctx.project_dir / "01_evidence" / "vst3" / "runtime_parameters.json") or []
    quick = bool(ctx.options.get("quick_probes", False))
    plan = render_plan(params, quick=quick)
    ref = ctx.project_dir / "05_reference_behavior"
    renders = ref / "original_renders"
    (ref / "probes").mkdir(parents=True, exist_ok=True)
    renders.mkdir(parents=True, exist_ok=True)
    (ref / "transfer_curves").mkdir(parents=True, exist_ok=True)
    (ref / "spectra").mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failures = 0
    tmp = ctx.ws.tmp / f"render-{ctx.job.job_id}"
    tmp.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(plan):
        ctx.check_cancel()
        ctx.progress(f"render {i + 1}/{len(plan)} {item['id']}")
        wav = tmp / f"{item['id']}.wav"
        try:
            r = host.call("render", plugin, probe=item["probe"], sample_rate=item["sr"], block_size=item["block"], frames=item["frames"], params=item["params"], out=str(wav))
        except HostError as exc:
            failures += 1
            ctx.warn(exc.code, f"{item['id']}: {exc.detail[:200]}")
            results.append({**item, "ok": False, "error": exc.code})
            continue
        d = r["data"]
        y, sr = m.read_wav(wav)
        sha, _ = ctx.store.put_file(wav)
        shutil.copyfile(wav, renders / f"{item['id']}.wav")
        ch0 = y[0] if y.shape[0] else y.reshape(-1)
        x = probes.make(item["probe"], item["frames"], item["sr"])
        row: dict[str, Any] = {**item, "ok": True, "wav": f"05_reference_behavior/original_renders/{item['id']}.wav", "object": sha, "channels": int(y.shape[0]),
                               "latency_reported": d.get("latency_reported"), "latency_measured": d.get("latency_measured"), "tail_last_sample": d.get("tail_last_sample"),
                               **m.basic(ch0)}
        if item["probe"] == "impulse":
            row["latency_measured_py"] = m.latency_from_impulse(ch0)
            row["tail_samples"] = m.tail_samples(ch0, 1)
        if item["probe"] == "sine1k":
            row["harmonics"] = m.harmonics(ch0, item["sr"])
        if item["probe"] == "log_sweep":
            resp = m.response(x, ch0, item["sr"])
            (ref / "spectra" / f"{item['id']}.json").write_text(json.dumps(resp), encoding="utf-8")
            row["response_bands"] = len(resp["bands"])
        if item["probe"] == "two_tone":
            row["aliasing"] = m.aliasing(ch0, item["sr"])
        if item["probe"] == "ramp":
            lat = int(d.get("latency_reported") or 0)
            curve = m.transfer_curve(x, ch0, lat, points=1024)
            fits = fit_mod.fit_all(curve)
            name = item["id"]
            write_json(ref / "transfer_curves" / f"{name}.json", "artifactbench.transfer_curve",
                       {"probe": item, "latency_used": lat, "curve": curve, "fit": {k: v for k, v in fits.items() if k != "fits"},
                        "fits": [{k: v for k, v in f.items() if k != "params" or f["family"] != "lut_65"} for f in fits["fits"][:8]]})
            row["fit_family"] = fits.get("chosen")
            row["fit_rmse"] = fits.get("chosen_rmse")
            row["transfer_curve_points"] = len(curve)
        results.append(row)
        wav.unlink(missing_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    ok = [r for r in results if r["ok"]]
    write_json(ref / "measurements.json", "artifactbench.measurements",
               {"plugin": str(plugin), "renders": results, "probe_set": list(probes.PROBES), "rates": list(probes.RATES), "blocks": list(probes.BLOCKS),
                "one_parameter_at_a_time": True, "quick": quick, "evidence": "VERIFIED_RUNTIME (original plugin, deterministic probes)"})
    (ref / "probes" / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    for rel in ("05_reference_behavior/measurements.json", "05_reference_behavior/probes/plan.json"):
        ctx.output(rel)
    ctx.output("05_reference_behavior/original_renders/")
    lat = {r["latency_reported"] for r in ok if r["probe"] == "impulse"}
    ctx.metrics.update({"renders": len(ok), "failed": failures, "latency_values": sorted(x for x in lat if x is not None),
                        "fits": {r["id"]: r.get("fit_family") for r in ok if r["probe"] == "ramp"}})
    if failures and not ok:
        raise StageFailed("RENDER_FAILED", "every render failed; see warnings")
    ctx.completeness = "NOT_APPLICABLE"


runner.register_stage(StageImpl("BEHAVIOR_COMPLETE", version=STAGE_VERSION, run=stage_behavior, tool_version=TOOL,
                                config_keys=("quick_probes", "host_timeout_s")))

for _s in ("measurements", "transfer_curve"):
    pass

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("fit", "fit a transfer curve JSON ([[x,y],…]) against the candidate families")
def _cli_fit(p):
    p.add_argument("curve")

    def run(args, ws):
        r = fit_mod.fit_all(json.loads(Path(args.curve).read_text(encoding="utf-8")))
        sys.stdout.write(json.dumps({k: v for k, v in r.items() if k != "fits"} | {"top": [{k: v for k, v in f.items() if k != "params"} for f in r["fits"][:5]]}, indent=2) + "\n")
        return 0
    p.set_defaults(func=run)


__all__ = ["stage_behavior", "render_plan", "Workspace", "api"]
