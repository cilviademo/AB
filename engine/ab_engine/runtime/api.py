"""RUNTIME_COMPLETE stage (EXECUTE 2.1–2.3).

1. vst3host: factory · parameters · units · buses · info · state → 01_evidence/vst3/*.json
2. state-differential harness: baseline state, one parameter changed at a time
   (to 0.0 and 1.0, or the far end from its default), diff the serialized state,
   locate the field → state_runtime_map.json with relationships and representations
3. 03_architecture/{serialized_properties,state_runtime_map,parameters,identity}.json;
   04_reconstruction/identity.cmake for the FIDELITY build

Third-party jobs run steps 1–3 too (architecture documentation), but never
touch 04_reconstruction (SPEC §15).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ab_engine import TOOL, api
from ab_engine.contracts import write_json
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs import runner
from ab_engine.jobs.runner import StageContext, StageFailed, StageImpl, StageSkipped
from ab_engine.runtime.correlate import correlate, diff_states, parse_state_text, tiers
from ab_engine.runtime.host import HostError, Vst3Host
from ab_engine.runtime.identity import identity_from_runtime
from ab_engine.workspace import Workspace

STAGE_VERSION = 2  # 2: SDK validator report (ADDENDUM A1)


def _primary_plugin(ctx: StageContext) -> Path:
    for i in jobs_db.get_inputs(ctx.conn, ctx.job.job_id):
        if i["kind"] == "binary" and i["path"] == ctx.job.primary and ctx.store.has(i["sha256"]):
            return _materialize_bundle(ctx, i)
    raise StageFailed("NO_BINARY", "primary binary is not in the object store")


def _materialize_bundle(ctx: StageContext, inp: dict[str, Any]) -> Path:
    """vst3host needs a loadable module. A bare `.so`/`.dll`/`.vst3` file from the store is
    written under a bundle-shaped folder so the SDK's module loader accepts it on every platform."""
    logical = inp["path"]
    bundle_dir = ctx.project_dir / "runtime" / "module"
    parts = logical.replace("\\", "/").split("/")
    # keep the path from the `.vst3` folder down when present (Contents/x86_64-win/… etc.)
    idx = next((k for k, p in enumerate(parts) if p.lower().endswith(".vst3") and k != len(parts) - 1), None)
    rel = "/".join(parts[idx:]) if idx is not None else parts[-1]
    target = bundle_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    src = ctx.store.get_path(inp["sha256"])
    if not target.is_file() or target.stat().st_size != src.stat().st_size:
        import shutil  # noqa: PLC0415

        shutil.copyfile(src, target)
        if sys.platform != "win32":
            target.chmod(0o755)
    # for a bare file inside a bundle folder, load the bundle root; else the file
    root = bundle_dir / parts[idx] if idx is not None else target
    return root


def _loadable(root: Path) -> Path:
    """The SDK loads a `.vst3` folder bundle; on Linux a bare .so needs to sit under <bundle>/Contents/<arch>-linux/."""
    if root.is_dir():
        return root
    if sys.platform.startswith("linux") and root.suffix in (".so", ".vst3") and root.is_file():
        import platform  # noqa: PLC0415
        import shutil  # noqa: PLC0415

        arch = platform.machine()
        bundle = root.parent / (root.stem + ".vst3")
        dest = bundle / "Contents" / f"{arch}-linux" / (root.stem + ".so")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file():
            shutil.copyfile(root, dest)
        return bundle
    return root


def stage_runtime(ctx: StageContext) -> None:
    host = Vst3Host(ctx.ws, ctx.ws.logs / ctx.job.job_id, timeout=float(ctx.options.get("host_timeout_s", 60)))
    if not host.available:
        raise StageSkipped("vst3host not built: run native/vst3host/build_all.{sh,ps1}")
    ctx.tool_versions["vst3host"] = host.version or "vst3host"
    plugin = _loadable(_primary_plugin(ctx))
    ev = ctx.project_dir / "01_evidence" / "vst3"
    sr, block = float(ctx.options.get("sample_rate", 48000)), int(ctx.options.get("block_size", 256))

    def call(cmd: str, **kw: Any) -> dict[str, Any]:
        ctx.check_cancel()
        ctx.progress(cmd)
        try:
            return host.call(cmd, plugin, sample_rate=sr, block_size=block, **kw)
        except HostError as exc:
            raise StageFailed(exc.code, exc.detail) from exc

    factory = call("factory")
    write_json(ev / "factory.json", "artifactbench.factory", factory["data"] | {"host": factory.get("host"), "sdk": factory.get("sdk")})
    params = call("parameters")
    write_json(ev / "runtime_parameters.json", "artifactbench.runtime_parameters", params["data"])
    units = call("units")
    write_json(ev / "units.json", "artifactbench.units", units["data"])
    buses = call("buses")
    write_json(ev / "buses.json", "artifactbench.buses", buses["data"])
    info = call("info")
    write_json(ev / "info.json", "artifactbench.info", info["data"])
    baseline = call("state")
    write_json(ev / "state_baseline.json", "artifactbench.state", baseline["data"])
    for rel in ("factory", "runtime_parameters", "units", "buses", "info", "state_baseline"):
        ctx.output(f"01_evidence/vst3/{rel}.json")
    class_info = params.get("class")
    # second validation source: the SDK's own validator (ADDENDUM A1); NOT_RUN when not built, never faked
    from ab_engine.runtime import validator as sdk_validator  # noqa: PLC0415

    ctx.progress("sdk validator")
    vrep = sdk_validator.run(ctx.ws, ctx.ws.logs / ctx.job.job_id, plugin, timeout=float(ctx.options.get("validator_timeout_s", 300)))
    write_json(ev / "validator.json", "artifactbench.validator_report", vrep)
    ctx.output("01_evidence/vst3/validator.json")
    if vrep["status"] == "NOT_RUN":
        ctx.warn("VALIDATOR_NOT_RUN", vrep.get("reason", ""))
    elif vrep["status"] != "PASSED":
        ctx.warn("VALIDATOR_" + vrep["status"], f"{vrep.get('failed')} failed: {', '.join(vrep.get('failing', [])[:5])}")
    ctx.metrics["sdk_validator"] = {"status": vrep["status"], "passed": vrep.get("passed"), "failed": vrep.get("failed")}

    # ---- state-differential harness --------------------------------------
    base_fields = parse_state_text(baseline["data"].get("component_state_text"))
    differential: dict[str, dict[str, Any]] = {}
    runs: list[dict[str, Any]] = []
    for p in params["data"]:
        if p.get("is_readonly"):
            continue
        pid = str(p["param_id"])
        default = float(p.get("default_normalized", 0.0))
        for target in ([1.0, 0.0] if default < 0.5 else [0.0, 1.0]):
            if abs(target - default) < 1e-9:
                continue
            probe = call("setparam", params={pid: target})
            fields = parse_state_text(probe["data"].get("component_state_text"))
            changed = diff_states(base_fields, fields)
            sample = next((s for s in p.get("samples", []) if abs(float(s.get("normalized", -1)) - target) < 1e-9), {})
            plain = _plain_of(sample)
            runs.append({"param_id": p["param_id"], "title": p.get("title"), "normalized": target, "changed": changed,
                         "field_value": fields.get(changed[0]) if len(changed) >= 1 else None, "plain": plain,
                         "state_changed_bytes": probe["data"].get("component_state_size") != baseline["data"].get("component_state_size")
                         or probe["data"].get("component_state_b64") != baseline["data"].get("component_state_b64")})
            if changed and pid not in differential:
                differential[pid] = {"changed": changed, "field_value": fields.get(changed[0]), "normalized": target, "plain": plain}
            if changed:
                break
    write_json(ev / "state_differential.json", "artifactbench.state_differential", {"baseline_fields": base_fields, "runs": runs, "sample_rate": sr, "block_size": block})
    ctx.output("01_evidence/vst3/state_differential.json")

    # ---- correlation -------------------------------------------------------
    keys_doc = ctx.project_dir / "03_architecture" / "serialized_keys.json"
    serialized_keys = json.loads(keys_doc.read_text(encoding="utf-8")).get("data", []) if keys_doc.is_file() else []
    static_names = {k["name"] for k in serialized_keys}
    # fields the runtime state carries that the static scan never saw are serialized properties too
    for name, value in base_fields.items():
        if name not in static_names:
            serialized_keys.append({"name": name, "serialized_key_status": "VERIFIED_RUNTIME_STATE", "runtime_parameter_status": "UNVERIFIED",
                                    "key_kind_candidate": "INTERNAL_EFFECT_PROPERTY (indexed array element)" if __import__("re").search(r"_\d+(_\d+)*$", name) else "XML_PARAMETER_KEY",
                                    "observed_serialized_values": [value], "value_representation": "UNKNOWN", "source": "vst3host getState"})
    write_json(ctx.project_dir / "03_architecture" / "serialized_properties.json", "artifactbench.serialized_properties", serialized_keys)
    srmap = correlate(serialized_keys, params["data"], differential)
    ui_hints = {k["name"] for k in serialized_keys if k["name"].lower().startswith(("ui", "gui", "editor", "window", "scale", "zoom"))}
    write_json(ctx.project_dir / "03_architecture" / "state_runtime_map.json", "artifactbench.state_runtime_map", srmap)
    write_json(ctx.project_dir / "03_architecture" / "parameters.json", "artifactbench.parameters",
               {"tiers": tiers(srmap, ui_hints), "runtime_parameters": params["data"], "note": "VST3_EXPORTED_PARAMETER rows come from vst3host (IEditController); STATE_SCHEMA_FIELD rows were never exported; representation is resolved by the state-differential harness"})
    for rel in ("serialized_properties", "state_runtime_map", "parameters"):
        ctx.output(f"03_architecture/{rel}.json")

    # ---- identity (2.3) ------------------------------------------------------
    ident = identity_from_runtime(factory["data"], class_info)
    ident["buses"] = buses["data"]
    ident["latency_samples"] = info["data"].get("latency_samples")
    ident["tail_samples"] = info["data"].get("tail_samples")
    ident["editor"] = info["data"].get("editor")
    ident["programs"] = units["data"].get("program_lists")
    write_json(ctx.project_dir / "03_architecture" / "identity.json", "artifactbench.identity", ident)
    ctx.output("03_architecture/identity.json")
    _write_identity_cmake(ctx, ident)   # every job (D-026: no ownership gate)

    mapped = sum(1 for m in srmap if m["relationship"] in ("SAME_ID", "MAPPED") and m["value_representation"] != "UNKNOWN")
    ctx.metrics.update({"parameters": len(params["data"]), "state_fields": len(serialized_keys), "mapped": mapped,
                        "differential_runs": len(runs), "identity_codes": ident["codes_status"],
                        "latency_samples": info["data"].get("latency_samples")})
    if mapped < len(params["data"]):
        ctx.warn("STATE_MAPPING_INCOMPLETE", f"{len(params['data']) - mapped} exported parameter(s) did not produce a locatable state field")
    from ab_engine.knowledge import hooks as knowledge_hooks  # noqa: PLC0415

    knowledge_hooks.after_runtime(ctx)
    ctx.completeness = "NOT_APPLICABLE"


def _plain_of(sample: dict[str, Any]) -> float | None:
    """The plain value behind a normalized one. The controller's display string is authoritative
    when it is numeric (JUCE's normalizedParamToPlain returns the normalized value for float
    parameters); otherwise fall back to normalizedParamToPlain."""
    text = sample.get("string")
    if isinstance(text, str):
        try:
            return float(text.strip().split()[0])
        except (ValueError, IndexError):
            pass
    return sample.get("plain")


def _write_identity_cmake(ctx: StageContext, ident: dict[str, Any]) -> None:
    recon = ctx.project_dir / "04_reconstruction"
    recon.mkdir(parents=True, exist_ok=True)
    codes_ok = ident["codes_status"].startswith("VERIFIED")
    lines = ["# GENERATED by the runtime stage from 03_architecture/identity.json (VERIFIED_RUNTIME).",
             "# FIDELITY mode uses these; SURROGATE mode ignores them (RECOVERY_SURROGATE_BUILD=ON).",
             f'set(RECOVERED_COMPANY "{ident.get("vendor") or ""}")',
             f'set(RECOVERED_PRODUCT "{ident.get("product") or ""}")',
             f'set(RECOVERED_MANUFACTURER_CODE "{ident["manufacturer_code"] if codes_ok else ""}")',
             f'set(RECOVERED_PLUGIN_CODE "{ident["plugin_code"] if codes_ok else ""}")',
             f'set(RECOVERED_PROCESSOR_FUID "{ident.get("processor_fuid") or ""}")',
             f'set(RECOVERED_VERSION "{ident.get("version") or ""}")',
             f'# codes: {ident["codes_status"]}' + (f' — {ident["codes_derivation"]}' if ident.get("codes_derivation") else " (non-JUCE FUID: codes stay empty; FIDELITY needs them from the owner)")]
    (recon / "identity.cmake").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmake = recon / "CMakeLists.txt"
    if cmake.is_file():
        text = cmake.read_text(encoding="utf-8")
        marker = "include(${CMAKE_CURRENT_SOURCE_DIR}/identity.cmake OPTIONAL)"
        if marker not in text:
            text = text.replace('set(RECOVERED_COMPANY "")           # UNVERIFIED', marker + '\nif(NOT DEFINED RECOVERED_COMPANY)\n  set(RECOVERED_COMPANY "")\nendif()', 1)
            text = text.replace('set(RECOVERED_MANUFACTURER_CODE "") # UNVERIFIED', 'if(NOT DEFINED RECOVERED_MANUFACTURER_CODE)\n  set(RECOVERED_MANUFACTURER_CODE "")\nendif()', 1)
            text = text.replace('set(RECOVERED_PLUGIN_CODE "")       # UNVERIFIED', 'if(NOT DEFINED RECOVERED_PLUGIN_CODE)\n  set(RECOVERED_PLUGIN_CODE "")\nendif()', 1)
            cmake.write_text(text, encoding="utf-8")
    ctx.output("04_reconstruction/identity.cmake")


runner.register_stage(StageImpl("RUNTIME_COMPLETE", version=STAGE_VERSION, run=stage_runtime, tool_version=TOOL,
                                config_keys=("sample_rate", "block_size", "host_timeout_s")))


def h_runtime_call(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """Diagnostic: one vst3host command on a path (never inside the GUI process)."""
    host = Vst3Host(ws, ws.logs / "runtime", timeout=float(params.get("timeout_s", 60)))
    if not host.available:
        raise api.ApiError("HOST_UNAVAILABLE", "vst3host is not built")
    try:
        return host.call(str(params.get("command", "factory")), Path(str(params.get("plugin", ""))),
                         **{k: v for k, v in params.items() if k not in ("command", "plugin", "timeout_s")})
    except HostError as exc:
        raise api.ApiError(exc.code, exc.detail) from exc


api.register("runtime.call", h_runtime_call)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("host", "call vst3host directly (ab-cli host <command> <plugin> [--json '{...}'])")
def _cli_host(p):
    p.add_argument("command")
    p.add_argument("plugin")
    p.add_argument("--json", default="{}")

    def run(args, ws):
        extra = json.loads(args.json)
        r = api.dispatch("runtime.call", {"command": args.command, "plugin": args.plugin, **extra}, ws)
        r.pop("_worker", None)
        sys.stdout.write(json.dumps(r, indent=2) + "\n")
        return 0
    p.set_defaults(func=run)
