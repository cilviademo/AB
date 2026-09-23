"""Agent handoff writers (EXECUTE Phase 5, SPEC §14 Export): HANDOFF.md, TODO.md, agent_prompt.md,
UNRECOVERABLE.md under 07_agent_handoff/, regenerated from *all* evidence present in the project
folder at export time (the frozen static stage writes a first, static-only version).

Everything stated is read from the evidence files and carries its status; nothing is asserted that
no stage measured. A fresh session must be able to make a correct DSP change guided by
reconstruction_index.json + these files without re-running analysis (Phase 5 gate).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ab_engine.decompile import roles as roles_mod
from ab_engine.jobs.model import Job

EQ = ("BIT_EXACT", "NUMERICALLY_EQUIVALENT", "BEHAVIORALLY_EQUIVALENT")


def _load(pd: Path, rel: str) -> Any:
    p = pd / rel
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("data")
    except (OSError, ValueError):
        return None


def gather(job: Job) -> dict[str, Any]:
    pd = Path(job.project_dir)
    summary = _load(pd, "00_manifest/recovery_summary.json") or {}
    ident = _load(pd, "03_architecture/identity.json") or {}
    params = _load(pd, "01_evidence/vst3/runtime_parameters.json") or []
    arch = _load(pd, "03_architecture/parameters.json") or {}
    tiers = arch.get("tiers", []) if isinstance(arch, dict) else []
    classes = _load(pd, "01_evidence/rtti/classes.json") or []
    verified = _load(pd, "01_evidence/rtti/classes_verified.json") or []
    resources = _load(pd, "01_evidence/resources/index.json") or []
    bd_res = _load(pd, "03_architecture/binarydata_resolved.json") or {}
    signal = _load(pd, "03_architecture/signal_flow.json")
    dsp = _load(pd, "01_evidence/decompiler/dsp_candidates.json") or []
    recon = _load(pd, "07_agent_handoff/reconstruction_index.json") or []
    model = _load(pd, "04_reconstruction/reconstruction_model.json") or {}
    meas = _load(pd, "05_reference_behavior/measurements.json")
    diff = _load(pd, "06_validation/differential_results.json")
    build = _load(pd, "06_validation/build_report.json")
    pv = _load(pd, "06_validation/pluginval.json")
    cross = _load(pd, "06_validation/cross_load.json")
    gt = _load(pd, "06_validation/GROUND_TRUTH_REPORT.json")
    stages = {s.stage: s.status for s in job.stages}
    return {"pd": pd, "summary": summary, "ident": ident, "params": params, "tiers": tiers, "classes": classes, "verified": verified, "resources": resources,
            "bd_res": bd_res, "signal": signal, "dsp": dsp, "recon": recon, "model": model, "meas": meas, "diff": diff, "build": build, "pv": pv, "cross": cross,
            "gt": gt, "stages": stages}


def next_tasks(ev: dict[str, Any]) -> list[dict[str, str]]:
    """Ordered by confidence and payoff: what a fresh session should do next."""
    tasks: list[dict[str, str]] = []
    st = ev["stages"]
    if st.get("RUNTIME_COMPLETE") != "OK":
        tasks.append({"task": "Run the RUNTIME stage (vst3host) to turn XML keys into VST3_EXPORTED_PARAMETER rows and verify identity", "evidence": "01_evidence/vst3/ is empty", "priority": "1"})
    if st.get("DECOMPILATION_COMPLETE") != "OK":
        tasks.append({"task": "Run the DECOMPILE stage (Ghidra headless; Settings → Tools) to verify vtables, seed the processBlock callgraph and rank DSP functions", "evidence": "no 01_evidence/decompiler/", "priority": "2"})
    if st.get("BEHAVIOR_COMPLETE") != "OK":
        tasks.append({"task": "Run the PROBE stage so transfer curves and response measurements exist for fitting", "evidence": "no 05_reference_behavior/", "priority": "2"})
    diff, model = ev["diff"], ev["model"]
    mods = {m["module"]: m for m in (diff or {}).get("modules", [])}
    if model:
        for ws in model.get("modules", []):
            for mo in ws.get("modulation", []):
                if mo["law"] == "unmodeled":
                    tasks.append({"task": f"Parameter `{mo['key']}` is not a static transfer effect ({mo['basis'][:120]}): model it as its own module (filter/modulation) from the log-sweep response and the FILTER-role class, then re-run BUILD + COMPARE",
                                  "evidence": f"reconstruction_model.json modulation[{mo['key']}]; 05_reference_behavior/spectra/", "priority": "3"})
    for name, m in mods.items():
        if name in ("Plugin", "WaveshaperSweeps") or name.startswith(("Law:", "Unmodeled:")):
            continue
        if m["classification"] not in EQ:
            tasks.append({"task": f"Module `{name}` is {m['classification']} on {m['renders']} render(s) (worst RMSE {m['worst_rmse']:.2e}" + (f", Δspectrum {m['worst_spectrum_diff_db']:.2f} dB" if m.get("worst_spectrum_diff_db") is not None else "") + f"): failing {', '.join(m['failing'][:4])}",
                          "evidence": "06_validation/differential_results.json", "priority": "3"})
    sw = mods.get("WaveshaperSweeps")
    if sw and sw["classification"] not in EQ:
        tasks.append({"task": f"Parameter sweeps reach {sw['classification']} (worst RMSE {sw['worst_rmse']:.2e}); the lead-in error (parameter smoothing) and any fractional-sample latency of the original are not modelled — add smoothing / a fractional delay only with measured evidence",
                      "evidence": "06_validation/differential_results.json modules[WaveshaperSweeps], per-render lead_in_rmse", "priority": "4"})
    for e in ev["recon"]:
        role = roles_mod.canonical_role(e.get("role"))   # the frozen v2 index may still say PROTECTED_SUBSYSTEM (ADDENDUM C2 alias)
        if e.get("status") == "SCAFFOLD_ONLY" and role not in ("GUI", "UNKNOWN", "STATE"):
            tasks.append({"task": f"Scaffold `{e['symbol']}` (role {role}, {e.get('structure_status', 'UNKNOWN')}): port from evidence_source/ + fit against probes; promote to Source/Active only at BEHAVIOR_MATCHED",
                          "evidence": e.get("file", ""), "priority": "5"})
    if ev["build"] and ev["build"].get("build_kind") == "SURROGATE" and ev["ident"].get("evidence") == "VERIFIED_RUNTIME":
        tasks.append({"task": "Identity is VERIFIED_RUNTIME: configure with -DAB_BUILD_KIND=FIDELITY for a session-compatible build once modules are equivalent", "evidence": "04_reconstruction/identity.cmake", "priority": "6"})
    if not tasks:
        tasks.append({"task": "Every measured module is equivalent; extend probes to parameter pairs and longer material before claiming more", "evidence": "06_validation/", "priority": "6"})
    return tasks


def handoff_md(job: Job, ev: dict[str, Any]) -> str:
    s, ident, st = ev["summary"], ev["ident"], ev["stages"]
    product = ident.get("product") or job.name
    vendor = ident.get("vendor") or "vendor UNVERIFIED"
    lines = [f"# Handoff: {product}", "",
             f"**Binary:** `{job.primary}` · sha256 `{job.artifact_sha256[:16]}…` · JUCE {s.get('juce') or '?'}" + (" · PDB present" if s.get('pdbFound') else " · no PDB"),
             f"**Identity:** {vendor} · codes {ident.get('manufacturer_code') or '?'}/{ident.get('plugin_code') or '?'} — {ident.get('codes_status') or ident.get('evidence') or 'UNVERIFIED'}",
             "**Stages:** " + " · ".join(f"{k.replace('_COMPLETE', '').replace('INGESTED', 'INGEST')} {v}" for k, v in st.items()), ""]
    # verified
    lines += ["## Verified"]
    if ev["params"]:
        exported = [t for t in ev["tiers"] if t.get("tier") == "VST3_EXPORTED_PARAMETER"]
        mapped = sum(1 for t in exported if t.get("key"))
        wrapper = sum(1 for p in ev["params"] if p.get("is_bypass") and not any(t.get("param_id") == p.get("param_id") and t.get("key") for t in exported))
        lines.append(f"- {len(ev['params'])} VST3 exported parameters (IEditController); {mapped} mapped to serialized state keys by the state-differential harness" + (f"; {wrapper} wrapper-provided (bypass)" if wrapper else ""))
    else:
        lines.append(f"- {len(_load(ev['pd'], '03_architecture/serialized_keys.json') or [])} serialized keys (XML) — exported parameters UNVERIFIED until the runtime stage")
    if ev["ident"].get("evidence") == "VERIFIED_RUNTIME":
        lines.append(f"- factory identity, buses ({len((ident.get('buses') or {}).get('input_audio', []))} in / {len((ident.get('buses') or {}).get('output_audio', []))} out), latency {ident.get('latency_samples')} samples, editor {(ident.get('editor') or {}).get('width')}×{(ident.get('editor') or {}).get('height')}")
    owned = [c for c in ev["classes"] if c.get("kind") == "PLUGIN_OWNED_CANDIDATE"]
    vt = sum(1 for c in ev["verified"] if c.get("structure_status") == "VERIFIED_VTABLE")
    lines.append(f"- {len(owned)} plugin-owned class names (RTTI)" + (f"; {vt} classes with vtables located by Ghidra" if ev["verified"] else "; vtables need the decompiler stage"))
    valid = sum(1 for r in ev["resources"] if r.get("status") == "VALID_EXACT")
    ren = len((ev["bd_res"] or {}).get("renames") or {})
    lines.append(f"- {valid} / {len(ev['resources'])} embedded resources VALID_EXACT" + (f"; {ren} BinaryData names resolved by content" if ren else ""))
    if ev["cross"]:
        lines.append(f"- state compatibility: {ev['cross'].get('classification')} (original ⇄ rebuild)")
    if ev["diff"]:
        for m in ev["diff"].get("modules", []):
            if m["module"] in ("Waveshaper",) and m["classification"] in EQ:
                lines.append(f"- module `{m['module']}` {m['classification']} on the ramp probe (RMSE {m['worst_rmse']:.2e}, Δspectrum {m['worst_spectrum_diff_db']:.3f} dB)")
    # inferred
    lines += ["", "## Inferred"]
    if ev["model"]:
        for ws in ev["model"].get("modules", []):
            laws = ", ".join(f"{mo['key']}={mo['law']}" for mo in ws.get("modulation", []) if mo["law"] not in ("none",))
            lines.append(f"- `{ws['name']}`: family {ws['family']} chosen by residual (RMSE {ws['rmse']:.2e}); parameter laws measured one at a time ({laws}); their combination is INFERRED (separable)")
    if ev["signal"]:
        lines.append(f"- signal flow: {len(ev['signal'].get('nodes', []))} processBlock-reachable DSP nodes ({ev['signal'].get('seed_basis')})")
    lines.append("- class roles from name tokens (CANDIDATE) until the callgraph confirms them" if not ev["dsp"] else f"- {len(ev['dsp'])} ranked DSP function candidates (priority = reachability × plugin-specific × parameter refs × DSP evidence)")
    # generated
    lines += ["", "## Generated / scaffold-only"]
    active = [e for e in ev["recon"] if e.get("compiled")]
    scaff = [e for e in ev["recon"] if e.get("status") == "SCAFFOLD_ONLY"]
    lines.append(f"- Source/Active: {', '.join('`' + e['symbol'] + '`' for e in active) or 'nothing compiled'}")
    lines.append(f"- Source/RecoveredScaffolds ({len(scaff)}): {', '.join('`' + e['symbol'] + '`' for e in scaff[:8])}{' …' if len(scaff) > 8 else ''} — never compiled")
    lines.append("- UI: generic parameter editor sized like the original; the original layout/paint code is not recoverable")
    # validation
    lines += ["", "## Build and validation"]
    if ev["build"]:
        lines.append(f"- build: {ev['build'].get('build_kind')} {ev['build'].get('status')}" + (f" · pluginval {ev['pv'].get('status')} (strictness {ev['pv'].get('strictness')})" if ev["pv"] else ""))
    else:
        lines.append("- build: not run (BUILD stage needs CMake + compiler + JUCE; Settings → Tools)")
    if ev["diff"]:
        lines.append(f"- differential harness: overall {ev['diff'].get('overall')} over {len(ev['diff'].get('renders', []))} renders; per module: " + "; ".join(f"{m['module']} {m['classification']}" for m in ev["diff"].get("modules", []) if not m["module"].startswith("Law:")))
    else:
        lines.append("- differential harness: not run")
    if ev["gt"]:
        gates = ev["gt"].get("gates", [])
        lines.append(f"- ground truth (fixture only): {sum(1 for g in gates if g['ok'] is True)} pass / {sum(1 for g in gates if g['ok'] is False)} fail / {sum(1 for g in gates if g['ok'] is None)} pending")
    # how to build
    lines += ["", "## How to build", "In the exported `<Plugin>_RECOVERED/` folder (inside the app's project it is `04_reconstruction/`):", "```", "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DJUCE_DIR=<path to JUCE 8.0.9> -DAB_BUILD_KIND=SURROGATE",
              "cmake --build build --config Release", "```",
              "FIDELITY (original identity, session-compatible) needs `identity.cmake` with VERIFIED_RUNTIME codes: " + ("present" if (ev["pd"] / "04_reconstruction" / "identity.cmake").is_file() else "absent — run the RUNTIME stage first") + ".",
              "After any DSP change: rebuild, then re-run COMPARE (`ab-cli run <job> --stage BUILD_COMPLETE --stage VALIDATION_COMPLETE`) and read 06_validation/VALIDATION.md.", ""]
    imap = _load(ev["pd"], "04_reconstruction/identifier_map.json") or {}
    renamed = [r for r in imap.get("identifiers", []) if r.get("active") != r.get("original", "").split("::")[-1]]
    lines += ["## Names", f"Naming mode `{imap.get('mode', 'PRESERVE_ORIGINAL_NAMES')}`; the full reversible map is `04_reconstruction/IDENTIFIER_MAP.md` (search either name space: `ab-cli naming-search <job> <name>`)."]
    if renamed:
        lines += ["Renamed in the reconstruction (a presentation/source-maintenance transformation; identity, fingerprints, addresses, callgraph, behaviour and validation state are untouched):"]
        lines += [f"- recovered symbol `{r['original']}` ({r.get('evidence_status')}, {r.get('original_address') or 'no address'}) → `{r['active']}` — reason: {r['reason']}" for r in renamed[:40]]
        if len(renamed) > 40:
            lines.append(f"- … {len(renamed) - 40} more in IDENTIFIER_MAP.md")
    else:
        lines += ["No identifier was renamed: original names are used everywhere."]
    lines += ["", "## Next best tasks (in order)"]
    for i, t in enumerate(next_tasks(ev), 1):
        lines.append(f"{i}. {t['task']}  \n   evidence: {t['evidence']}")
    lines += ["", "Unrecoverable items are listed in UNRECOVERABLE.md — recreate them, do not search for them.", ""]
    return "\n".join(lines)


def todo_md(ev: dict[str, Any]) -> str:
    lines = ["# TODO — ordered by confidence and payoff", "", "| # | priority | task | evidence |", "|---|---|---|---|"]
    for i, t in enumerate(next_tasks(ev), 1):
        lines.append(f"| {i} | {t['priority']} | {t['task']} | {t['evidence']} |")
    lines += ["", "Module TODOs carried in reconstruction_index.json:", ""]
    for e in ev["recon"]:
        for td in e.get("todos", [])[:6]:
            lines.append(f"- `{e['symbol']}`: {td}")
    return "\n".join(lines) + "\n"


def agent_prompt(job: Job, ev: dict[str, Any]) -> str:
    product = ev["ident"].get("product") or job.name
    ws_mod = next((e for e in ev["recon"] if e.get("role") == "WAVESHAPER"), None)
    return f"""You are continuing an evidence-first reconstruction of {product} from its compiled binary (AB — Artifact Bench bundle).

Start here:
1. 07_agent_handoff/reconstruction_index.json — every symbol with status, file, evidence, addresses, validation and todos. Work TODOs in confidence order (TODO.md).
2. 04_reconstruction/RECONSTRUCTION.md and 06_validation/VALIDATION.md — what is compiled, what passed, what failed and on which renders.
3. {'04_reconstruction/recovered_source/Waveshaper.h — the fitted module (' + str(ws_mod.get('validation')) + ' at the default; sweeps ' + str(ws_mod.get('validation_sweeps')) + ')' if ws_mod else '04_reconstruction/recovered_source/ — fitted modules (none yet)'}.

Rules:
- Treat 01_evidence/ as immutable. Never edit it.
- Never promote a CANDIDATE or INFERRED item to VERIFIED without new evidence (runtime introspection, RTTI export, behavioural test).
- Any algorithmic operation not present in static or behavioural evidence must be marked INFERRED in code comments and in reconstruction_index.json.
- Only Source/Active is compiled. Promote a scaffold only when it is BEHAVIOR_MATCHED at ≥ BEHAVIORALLY_EQUIVALENT on the differential harness.
- Keep 04_reconstruction buildable at every commit (SURROGATE identity until FIDELITY is justified by VERIFIED_RUNTIME identity).
- After changing any DSP: rebuild, re-run the COMPARE stage, and record the per-module result in reconstruction_index.json (validation, rmse, failing renders).
- Licensing / activation / entitlement code is LICENSING_AND_ENTITLEMENT_SUBSYSTEM: recover, reconstruct and validate it like DSP (licence states original vs rebuild). Replacing a check with a constant is a TRANSFORMED_BREAKING transformation: record it in the transformation graph, never label it recovery.
- Do not search for what UNRECOVERABLE.md lists; recreate it.

Measured state of this bundle: {'; '.join(f"{k.replace('_COMPLETE', '')} {v}" for k, v in ev['stages'].items())}.
"""


def unrecoverable_md(ev: dict[str, Any], has_pdb: bool) -> str:
    lines = ["# Unrecoverable from a stripped optimised binary", "", "Recreate these; do not keep searching for them.", "",
             "- original source comments", "- original whitespace/formatting", "- original local variable names"]
    if not has_pdb:
        lines.append("- original function/member names (no .pdb; RTTI class names and exported symbols are the exception)")
    lines += ["- dead source removed by the compiler/linker", "- excluded #if branches and unused files", "- template abstractions optimised away",
              "- Git history", "- original CMake/Projucer formatting", "- UI layout and paint code (only assets survive; the editor size is measured)"]
    if ev["model"]:
        for ws in ev["model"].get("modules", []):
            for mo in ws.get("modulation", []):
                if mo["law"] == "table":
                    lines.append(f"- the exact mapping law of `{mo['key']}` between measured positions (a table is interpolated; INFERRED)")
    lines += ["", "Unmodelled but measurable (not unrecoverable — needs work, see TODO.md): parameter smoothing times, fractional-sample latency of oversampling filters, per-parameter effects flagged `unmodeled`.", ""]
    return "\n".join(lines)


def write_all(job: Job) -> list[str]:
    ev = gather(job)
    out = ev["pd"] / "07_agent_handoff"
    out.mkdir(parents=True, exist_ok=True)
    manifest = _load(ev["pd"], "00_manifest/input_manifest.json") or {}
    has_pdb = any(i.get("kind") == "pdb" for i in manifest.get("inputs", []))
    written = []
    for name, text in (("HANDOFF.md", handoff_md(job, ev)), ("TODO.md", todo_md(ev)), ("agent_prompt.md", agent_prompt(job, ev)), ("UNRECOVERABLE.md", unrecoverable_md(ev, has_pdb))):
        (out / name).write_text(text, encoding="utf-8")
        written.append(f"07_agent_handoff/{name}")
    return written


__all__ = ["write_all", "gather", "next_tasks"]
