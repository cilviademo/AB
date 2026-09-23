"""DECOMPILATION_COMPLETE stage (EXECUTE 3.2–3.3, SPEC §8).

Runs Ghidra headless (isolated worker, own user dir under the app data
folder, scripts only from ``ghidra/``) with ExportRTTI, ExportCallgraph,
Fingerprint and ExportDecompiled on the primary binary, then:

* installs the exports under ``01_evidence/{rtti,callgraphs,decompiler}``
* merges ``classes_verified.json`` into the static class list
  (``name_status: VERIFIED_RTTI``, ``structure_status: VERIFIED_VTABLE``)
* scores every function's role (§8.2) with the callgraph distance, marks
  ``CANDIDATE | VERIFIED_CALLGRAPH``, ranks DSP candidates by §8.6 priority
* resolves BinaryData names by content (§8.4) and renames carved assets
* writes ``03_architecture/signal_flow.json`` (processBlock-reachable DSP
  functions in call order) and ``07_agent_handoff/binary_symbol_map.json``
* records ``SCAN_INCOMPLETE`` when Ghidra stopped early (timeout/partial)

Ghidra missing → SKIPPED with the downloader hint; never faked.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from ab_engine import TOOL, api
from ab_engine import tools as tools_mod
from ab_engine.contracts import write_json
from ab_engine.decompile import binarydata as bd
from ab_engine.decompile import roles as roles_mod
from ab_engine.decompile import stability
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs import runner
from ab_engine.jobs.runner import StageContext, StageFailed, StageImpl, StageSkipped
from ab_engine.workers.run import run_worker
from ab_engine.workspace import Workspace

STAGE_VERSION = 6  # 6: name-token roles for structural classes, inlined-class inference; 5: Fingerprint.java sizes restored (were 0 → every Ghidra fingerprint was skipped by the knowledge base); 4: structural RTTI + vtable layouts; 3: Capstone (A3)
SCRIPTS = ("ExportRTTI.java", "ExportCallgraph.java", "Fingerprint.java", "ExportDecompiled.java")


def scripts_dir() -> Path | None:
    root = tools_mod.repo_root()
    if root and (root / "ghidra" / "ExportRTTI.java").is_file():
        return root / "ghidra"
    if getattr(sys, "frozen", False):
        p = Path(sys.executable).resolve().parent.parent / "ghidra"
        if (p / "ExportRTTI.java").is_file():
            return p
    return None


def _primary_file(ctx: StageContext) -> Path:
    for i in jobs_db.get_inputs(ctx.conn, ctx.job.job_id):
        if i["kind"] == "binary" and i["path"] == ctx.job.primary and ctx.store.has(i["sha256"]):
            return ctx.store.get_path(i["sha256"])
    raise StageFailed("NO_BINARY", "primary binary is not in the object store")


def run_ghidra(ws: Workspace, log_dir: Path, binary: Path, out: Path, *, timeout: float, max_functions: int, java_home: str | None,
               scripts: tuple[str, ...] = SCRIPTS) -> Any:
    ghidra = tools_mod.find_ghidra(ws)
    if not ghidra.present:
        raise StageSkipped("Ghidra not installed: Settings → Tools → install (pinned tools/manifest.json) or set GHIDRA_INSTALL_DIR")
    sdir = scripts_dir()
    if sdir is None:
        raise StageFailed("GHIDRA_FAILED", "ghidra/ scripts not found beside the engine")
    work = Path(tempfile.mkdtemp(prefix="ab-ghidra-", dir=ws.tmp))
    (work / "proj").mkdir()
    home = ws.state / "ghidra-home"  # Ghidra's user settings dir lives under the app data folder (SPEC §15)
    home.mkdir(parents=True, exist_ok=True)
    argv = [ghidra.path, str(work / "proj"), "ab", "-import", str(binary), "-scriptPath", str(sdir), "-max-cpu", "2"]
    for s in scripts:
        argv += ["-postScript", s, str(out)] + ([str(max_functions)] if s == "ExportDecompiled.java" else [])
    argv += ["-deleteProject"]
    env = {"MAXMEM": os.environ.get("MAXMEM", "4G"), "JAVA_TOOL_OPTIONS": "", "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home)}
    if java_home:
        env["JAVA_HOME"] = java_home
        env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + os.environ.get("PATH", "")
    out.mkdir(parents=True, exist_ok=True)
    return run_worker("ghidra", argv, timeout=timeout, log_dir=log_dir, cwd=work, env_extra=env)


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")).get("data") if p.is_file() else None


def _fill_sizes(fps: list[dict[str, Any]], callgraph: dict[str, Any]) -> int:
    """A fingerprint row without a size (a Fingerprint.java export bug shipped once) takes the callgraph's
    size for the same address — same evidence, one column."""
    sizes = {f.get("addr"): int(f.get("size", 0)) for f in callgraph.get("functions", []) if f.get("addr")}
    n = 0
    for fp in fps:
        if int(fp.get("size", 0) or 0) == 0 and sizes.get(fp.get("addr")):
            fp["size"] = sizes[fp["addr"]]
            n += 1
    return n


def stage_decompile(ctx: StageContext) -> None:
    jdk = tools_mod.find_jdk(ctx.ws)
    ghidra = tools_mod.find_ghidra(ctx.ws)
    if not ghidra.present:
        raise StageSkipped("Ghidra not installed: Settings → Tools → install (pinned tools/manifest.json) or set GHIDRA_INSTALL_DIR")
    if not jdk.present:
        raise StageSkipped("JDK 21 not found for Ghidra (tools/manifest.json jdk entry needs a pinned hash, BLOCKERS B-007)")
    ctx.tool_versions["ghidra"] = ghidra.version or "ghidra"
    ctx.tool_versions["jdk"] = (jdk.version or "jdk")[:60]
    binary = _primary_file(ctx)
    # ADDENDUM A3: the Capstone signature set is computed BEFORE Ghidra (seconds, symbol-free) so the
    # knowledge cache can match first; Ghidra then runs on the whole image but its results are joined
    # to these pre-fingerprints by address. (Scheduling Ghidra on the residual only lands with A2.)
    from ab_engine.fingerprint import capstone_fp  # noqa: PLC0415

    ctx.progress("capstone pre-fingerprints")
    pre = capstone_fp.fingerprint_binary(binary, progress=lambda d: ctx.progress(f"capstone: {d}"))
    pre_dir = ctx.project_dir / "01_evidence" / "decompiler"
    pre_dir.mkdir(parents=True, exist_ok=True)
    write_json(pre_dir / "prefingerprints.json", "artifactbench.prefingerprints", pre)
    ctx.output("01_evidence/decompiler/prefingerprints.json")
    ctx.metrics["prefingerprints"] = {"status": pre.get("status"), "functions": len(pre.get("functions", [])), "tlsh": sum(1 for f in pre.get("functions", []) if f.get("TLSH"))}
    from ab_engine.knowledge import hooks as knowledge_hooks  # noqa: PLC0415

    knowledge_hooks.match_prefingerprints(ctx, pre)
    out = Path(tempfile.mkdtemp(prefix="ab-ghidra-out-", dir=ctx.ws.tmp))
    ctx.progress("ghidra headless analysis", tool=ghidra.version)
    java_home = str(Path(jdk.path).parent.parent) if jdk.path and Path(jdk.path).name.startswith("java") else None
    res = run_ghidra(ctx.ws, ctx.ws.logs / ctx.job.job_id, binary, out, timeout=float(ctx.options.get("ghidra_timeout_s", 3600)),
                     max_functions=int(ctx.options.get("max_functions", 20000)), java_home=java_home)
    partial = res.timed_out
    produced = {n: (out / n).is_file() for n in ("rtti/classes_verified.json", "callgraphs/callgraph.json", "decompiler/fingerprints.json", "decompiler/functions.json")}
    if not res.ok and not any(produced.values()):
        tail = ""
        try:
            tail = Path(res.stderr_path or "").read_text(encoding="utf-8", errors="replace")[-800:]
        except OSError:
            pass
        raise StageFailed(res.error_code or "GHIDRA_FAILED", f"ghidra exit {res.exit_code}: {tail.strip()[-400:] or 'no stderr'}")
    if partial or not all(produced.values()):
        ctx.warn("SCAN_INCOMPLETE", f"ghidra {'timed out' if partial else 'did not write every export'}: {produced}")
    # install evidence
    ev = ctx.project_dir / "01_evidence"
    for sub in ("rtti", "callgraphs", "decompiler"):
        src = out / sub
        if not src.is_dir():
            continue
        dst = ev / sub
        for p in src.rglob("*"):
            if p.is_file():
                rel = p.relative_to(out)
                (ev / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, ev / rel)
                ctx.output(f"01_evidence/{rel.as_posix()}")
        del dst
    shutil.rmtree(out, ignore_errors=True)

    verified = _load(ev / "rtti" / "classes_verified.json") or []
    callgraph = _load(ev / "callgraphs" / "callgraph.json") or {"functions": [], "seeds": {}, "seed_basis": "none"}
    fps = (_load(ev / "decompiler" / "fingerprints.json") or {}).get("functions", [])
    _fill_sizes(fps, callgraph)
    funcs = _load(ev / "decompiler" / "functions.json") or []
    resolution = _load(ev / "decompiler" / "binarydata_resolution.json") or {}

    # ---- names the knowledge base can lend by fingerprint (INFERRED, never VERIFIED) ----
    kn = knowledge_hooks.match_ghidra_names(ctx, fps)
    ctx.metrics["knowledge_names"] = len(kn)

    # ---- vtable layouts: symbol builds teach, stripped builds are seeded (A2 knowledge, SPEC §8.4) ----
    seeds0 = callgraph.get("seeds", {})
    if seeds0.get("processBlock"):
        n_learned = knowledge_hooks.learn_vtable_layouts(ctx, classes=verified, ghidra_fps=fps, stage_version=STAGE_VERSION)
        ctx.metrics["vtable_layouts_learned"] = n_learned
    else:
        kl = knowledge_hooks.seed_from_vtable_layouts(ctx, classes=verified, ghidra_fps=fps, stage_version=STAGE_VERSION)
        write_json(ev / "callgraphs" / "seeds_knowledge.json", "artifactbench.seeds_knowledge", kl)
        ctx.output("01_evidence/callgraphs/seeds_knowledge.json")
        ctx.metrics["vtable_layout_seeds"] = {"seeds": sorted(kl["seeds"]), "chosen_class": kl.get("chosen_class"), "ambiguous": kl.get("ambiguous"), "layouts_considered": kl.get("layouts_considered")}
        if kl["seeds"]:
            # the learned seeds replace the density heuristic; distances are recomputed the same way ExportCallgraph does
            merged_seeds = {k: v for k, v in seeds0.items() if k != "processBlock_candidate"}
            merged_seeds.update(kl["seeds"])
            callgraph = dict(callgraph, seeds=merged_seeds, seed_basis=kl["seed_basis"], seed_detail=kl["seed_detail"],
                             previous_seed_basis=callgraph.get("seed_basis"), previous_processBlock_candidate=seeds0.get("processBlock_candidate"))
            from ab_engine.knowledge import vtable_layout as _vl  # noqa: PLC0415

            dist = _vl.distances(callgraph.get("functions", []), kl["seeds"]["processBlock"])
            callgraph["functions"] = [dict(f, dist_from_processBlock=dist.get(f["addr"], -1)) for f in callgraph.get("functions", [])]
            write_json(ev / "callgraphs" / "callgraph.json", "artifactbench.callgraph", callgraph)
            ctx.progress(f"processBlock seeded from a learned vtable layout ({kl['chosen_class']}); {len(dist)} functions reachable")

    # ---- classes: merge verified RTTI into the static list ---------------------
    static_classes = _load(ctx.project_dir / "01_evidence" / "rtti" / "classes.json") or []
    by_name = {c["name"]: c for c in verified}
    leaf = lambda n: n.split("::")[-1]  # noqa: E731
    by_leaf = {leaf(c["name"]): c for c in verified}
    merged = []
    for c in static_classes:
        v = by_name.get(c["recovered_name"]) or by_leaf.get(leaf(c["recovered_name"]))
        row = dict(c)
        if v:
            row.update({"name_status": "VERIFIED_RTTI", "structure_status": v.get("structure_status", "UNKNOWN"), "vtables": v.get("vtables", []),
                        "slot_counts": v.get("slot_counts", []), "bases": v.get("bases", []), "base_status": v.get("base_status", "UNKNOWN"),
                        "methods": v.get("methods", []), "ctor_dtor_candidates": v.get("ctor_dtor_candidates", [])})
        else:
            row.update({"structure_status": "UNKNOWN", "rtti_note": "name seen as a type-descriptor string; no vtable located by Ghidra"})
        merged.append(row)
    seen = {c["recovered_name"] for c in static_classes} | {leaf(c["recovered_name"]) for c in static_classes}
    for v in verified:
        if v["name"] not in seen and leaf(v["name"]) not in seen:
            fw = v["name"].startswith(("juce::", "std::", "Steinberg::", "__cxxabiv1::", "__gnu_cxx::"))
            role, role_status = roles_mod.role_from_name(v["name"]) if not fw else ("FRAMEWORK", "CANDIDATE")
            merged.append({"recovered_name": v["name"], "kind": "PLUGIN_OWNED_CANDIDATE" if not fw else "FRAMEWORK", "role": role, "role_status": role_status, "role_basis": ["name tokens"] if not fw else ["framework namespace"],
                           "name_status": "VERIFIED_RTTI", "structure_status": v.get("structure_status"), "vtables": v.get("vtables", []), "slot_counts": v.get("slot_counts", []),
                           "bases": v.get("bases", []), "base_status": v.get("base_status", "UNKNOWN"), "methods": v.get("methods", []), "source": "Ghidra RTTI (" + str(v.get("rtti_kind") or "analyzer") + ")"})
    write_json(ctx.project_dir / "03_architecture" / "classes.json", "artifactbench.classes_verified", merged)
    ctx.output("03_architecture/classes.json")

    # ---- roles + priority ----------------------------------------------------------
    static_roles = {c["recovered_name"]: c.get("role") for c in static_classes}
    static_roles.update({leaf(k): v for k, v in list(static_roles.items())})
    owned = {c["recovered_name"] for c in static_classes if c.get("kind") == "PLUGIN_OWNED_CANDIDATE"} | {leaf(c["recovered_name"]) for c in static_classes if c.get("kind") == "PLUGIN_OWNED_CANDIDATE"}
    fp_by = {f["addr"]: f for f in fps}
    fn_meta = {f["addr"]: f for f in funcs}
    param_ids = set()
    rp = _load(ctx.project_dir / "01_evidence" / "vst3" / "runtime_parameters.json") or []
    for p in rp:
        param_ids.add(int(p.get("param_id", -1)))
    scored = []
    for fn in callgraph.get("functions", []):
        meta = fn_meta.get(fn["addr"], {})
        fp = fp_by.get(fn["addr"])
        consts = set()
        for c in (fp or {}).get("CONSTANT_SIGNATURE", []):
            try:
                consts.add(int(float(c)))
            except (TypeError, ValueError):
                pass
        param_refs = len(consts & param_ids) if param_ids else 0
        cls = meta.get("class") or (fp or {}).get("RTTI_XREF") or ""
        fn = dict(fn)
        fn["seed_basis"] = "symbol" if (callgraph.get("seeds", {}).get("processBlock") and not callgraph.get("seed_detail")) else callgraph.get("seed_basis", "none")
        s = roles_mod.score(fn, fp, class_static_role=static_roles.get(cls) or static_roles.get(leaf(cls)), is_owned=(cls in owned or leaf(cls) in owned),
                            param_refs=param_refs, noise=bool(meta.get("noise")), wrapper=bool(meta.get("wrapper")), demangled=meta.get("demangled") or fn.get("name", ""))
        k = kn.get(fn["addr"])
        scored.append({"addr": fn["addr"], "name": meta.get("demangled") or fn.get("name"), "raw": fn.get("name"), "class": cls, "size": fn.get("size"),
                       "knowledge_name": (k or {}).get("name"), "knowledge_role": (k or {}).get("role"), "knowledge_basis": (k or {}).get("basis"),
                       "dist_from_processBlock": fn.get("dist_from_processBlock", -1), "noise": bool(meta.get("noise")), "noise_kind": meta.get("noise_kind"),
                       "wrapper": bool(meta.get("wrapper")), "param_refs": param_refs, "vtable_slot": (fp or {}).get("VTABLE_SLOT", -1), "file": meta.get("file"), **s})
    scored.sort(key=lambda r: -r["priority"])
    dsp = [r for r in scored if r["role"] in roles_mod.DSP_ROLES and not r["noise"]]
    # optimizer inlining (stripped -O2 builds): DSP-role classes with no surviving method body live inside processBlock
    seeds_now = callgraph.get("seeds", {})
    inlined = roles_mod.infer_inlined(merged, scored, seeds_now.get("processBlock") or seeds_now.get("processBlock_candidate"))
    for r in dsp:
        mine = [x for x in inlined if x["inlined_into"] == r["addr"]]
        if mine:
            r["inlined_classes"] = [x["class"] for x in mine]
            r["inlined_basis"] = mine[0]["basis"]
    if inlined:
        write_json(ev / "decompiler" / "inlined_classes.json", "artifactbench.inlined_classes", inlined)
        ctx.output("01_evidence/decompiler/inlined_classes.json")
    write_json(ev / "decompiler" / "roles.json", "artifactbench.decompiled_functions", scored)
    write_json(ev / "decompiler" / "dsp_candidates.json", "artifactbench.dsp_candidates", dsp[:200])
    def _dsp_row(i: int, r: dict[str, Any]) -> str:
        kn = f" ≈ `{r['knowledge_name']}` (knowledge, INFERRED)" if r.get("knowledge_name") else ""
        inl = " ⊃ inlined " + ", ".join(r["inlined_classes"]) + " (INFERRED)" if r.get("inlined_classes") else ""
        basis = "; ".join(r["role_basis"])
        return f"| {i + 1} | {r['priority']} | {r['role']} | {r['role_status']} | {r['dist']} | {r['class']} | `{r['name']}`{kn}{inl} @ {r['addr']} | {basis} |"

    (ev / "decompiler" / "dsp_candidates.md").write_text(
        "# DSP candidates — priority = reachability × plugin-specific × parameter/state refs × DSP evidence (SPEC §8.6)\n\n| # | priority | role | status | dist | class | function | basis |\n|---|---|---|---|---|---|---|---|\n"
        + "\n".join(_dsp_row(i, r) for i, r in enumerate(dsp[:100])) + "\n", encoding="utf-8")
    for rel in ("01_evidence/decompiler/roles.json", "01_evidence/decompiler/dsp_candidates.json", "01_evidence/decompiler/dsp_candidates.md"):
        ctx.output(rel)

    # ---- signal flow (processBlock-reachable DSP functions in callee order) -------
    by_addr = {r["addr"]: r for r in scored}
    seeds = callgraph.get("seeds", {})
    pb = seeds.get("processBlock") or seeds.get("processBlock_candidate")
    nodes, edges = [], []
    if pb and pb in by_addr:
        order: list[str] = []
        stack = [pb]
        seen_nodes: set[str] = set()
        cg = {f["addr"]: f for f in callgraph.get("functions", [])}
        while stack:
            a = stack.pop()
            if a in seen_nodes:
                continue
            seen_nodes.add(a)
            order.append(a)
            for c in reversed(cg.get(a, {}).get("callees", [])):
                if c in by_addr and not by_addr[c]["noise"]:
                    edges.append({"from": a, "to": c})
                    stack.append(c)
        nodes = [{"addr": a, "name": by_addr[a]["name"], "role": by_addr[a]["role"], "role_status": by_addr[a]["role_status"], "dist": by_addr[a]["dist"], "class": by_addr[a]["class"]}
                 for a in order if by_addr[a]["role"] in roles_mod.DSP_ROLES or a == pb]
    write_json(ctx.project_dir / "03_architecture" / "signal_flow.json", "artifactbench.signal_flow",
               {"seed": pb, "seed_basis": callgraph.get("seed_basis"), "seed_detail": callgraph.get("seed_detail") or {}, "evidence": "INFERRED" if pb else "UNKNOWN", "nodes": nodes, "edges": [e for e in edges if e["to"] in {n["addr"] for n in nodes}]})
    ctx.output("03_architecture/signal_flow.json")

    # ---- BinaryData resolution (3.3) -------------------------------------------------
    index_path = ctx.project_dir / "01_evidence" / "resources" / "index.json"
    index_doc = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else None
    carved = index_doc["data"] if index_doc else []
    static_map = _load(ctx.project_dir / "01_evidence" / "resources" / "binarydata_map.json") or []
    static_names = [m["binarydata_name"] for m in static_map]
    rows = bd.resolve(resolution, carved, static_names) if resolution else []
    verified_rows = [r for r in rows if r["mapping_status"].startswith("VERIFIED (")]
    renames: dict[str, str] = {}
    if index_doc:
        # 01_evidence is immutable (SPEC §1.7): the resolution is a new file; the resolved map lives in 03_architecture
        _, renames = bd.apply_to_index([dict(c) for c in carved], rows)
    write_json(ctx.project_dir / "03_architecture" / "binarydata_resolved.json", "artifactbench.binarydata_resolution",
               {"rows": rows, "renames": renames, "static_map": static_map, "note": "VERIFIED only by content (sha256 of bytes read from program memory); 02_recovered_assets renamed accordingly"})
    ctx.output("03_architecture/binarydata_resolved.json")
    for carved_name, filename in renames.items():
        for sub in ("images", "fonts", "xml", "impulses"):
            src = ctx.project_dir / "02_recovered_assets" / sub / carved_name
            if src.is_file():
                dst = src.with_name(filename)
                if not dst.exists():
                    shutil.copyfile(src, dst)
                    ctx.output(f"02_recovered_assets/{sub}/{filename}")

    # ---- binary_symbol_map (07) ------------------------------------------------------
    symbol_map = _load(ev / "decompiler" / "symbol_map.json") or []
    bsm = [{"addr": s["addr"], "raw": s["raw"], "inferred": s.get("inferred"), "final": s.get("final"), "status": s.get("status"),
            "role": by_addr.get(s["addr"], {}).get("role"), "class": by_addr.get(s["addr"], {}).get("class"), "file": by_addr.get(s["addr"], {}).get("file")} for s in symbol_map]
    write_json(ctx.project_dir / "07_agent_handoff" / "binary_symbol_map.json", "artifactbench.binary_symbol_map", bsm)
    ctx.output("07_agent_handoff/binary_symbol_map.json")

    # ---- fingerprint stability against a sibling build, when the owner dropped one -----
    sibling = ctx.options.get("sibling_fingerprints")
    if sibling and Path(sibling).is_file():
        other = (json.loads(Path(sibling).read_text(encoding="utf-8")).get("data") or {}).get("functions", [])
        write_json(ctx.project_dir / "06_validation" / "fingerprint_stability.json", "artifactbench.fingerprint_stability", stability.compare(fps, other))
        ctx.output("06_validation/fingerprint_stability.json")

    knowledge_hooks.after_decompile(ctx, pre=pre, ghidra_fps=fps, classes=verified, roles=scored, stage_version=STAGE_VERSION)
    n_verified = sum(1 for c in merged if c.get("name_status") == "VERIFIED_RTTI")
    ctx.metrics.update({"functions": len(scored), "classes_verified": n_verified, "dsp_candidates": len(dsp), "seed_basis": callgraph.get("seed_basis"),
                        "processBlock": bool(seeds.get("processBlock") or seeds.get("processBlock_candidate")), "binarydata_verified": len(verified_rows),
                        "fingerprints": len(fps), "ghidra_ms": res.elapsed_ms, "noise_hidden": sum(1 for r in scored if r["noise"])})
    ctx.completeness = "SCAN_INCOMPLETE" if partial else "NOT_APPLICABLE"


runner.register_stage(StageImpl("DECOMPILATION_COMPLETE", version=STAGE_VERSION, run=stage_decompile, tool_version=TOOL,
                                config_keys=("max_functions", "ghidra_timeout_s", "sibling_fingerprints")))


def h_fingerprint_stability(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """Compare two fingerprint sets; with ``job_id`` the report is written to that job's 06_validation/ (ground-truth gate)."""
    a = (json.loads(Path(str(params["a"])).read_text(encoding="utf-8")).get("data") or {}).get("functions", [])
    b = (json.loads(Path(str(params["b"])).read_text(encoding="utf-8")).get("data") or {}).get("functions", [])
    r = stability.compare(a, b)
    if params.get("job_id"):
        job = jobs_db.get_job(jobs_db.connect(ws.db_path), str(params["job_id"]))
        if job is None:
            raise api.ApiError("not_found", "no such job")
        out = Path(job.project_dir) / "06_validation" / "fingerprint_stability.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, "artifactbench.fingerprint_stability", r | {"a": str(params["a"]), "b": str(params["b"]), "matches": r["matches"][:200]})
        r["written"] = str(out)
    r["matches"] = r["matches"][:50]
    return r


api.register("decompile.stability", h_fingerprint_stability)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("fingerprint", "Capstone signature set of a binary before Ghidra (ADDENDUM A3): ab-cli fingerprint <binary> --out fp.json")
def _cli_fp(p):
    p.add_argument("binary")
    p.add_argument("--out", required=True)

    def run(args, ws):
        from ab_engine.fingerprint import capstone_fp  # noqa: PLC0415

        r = capstone_fp.write(Path(args.binary), Path(args.out))
        sys.stdout.write(json.dumps({"ok": r.get("status") == "OK", "data": {k: v for k, v in r.items() if k != "functions"} | {"functions": len(r.get("functions", []))}}, indent=2) + "\n")
        return 0 if r.get("status") == "OK" else 1
    p.set_defaults(func=run)


@subcommand("fingerprint-stability", "compare two fingerprints.json files (Release+PDB vs stripped)")
def _cli_stab(p):
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--job", help="also write 06_validation/fingerprint_stability.json into this job")

    def run(args, ws):
        r = api.dispatch("decompile.stability", {"a": args.a, "b": args.b, "job_id": args.job}, ws)
        sys.stdout.write(json.dumps({"ok": r["ok"], "data": {k: v for k, v in r.items() if k != "matches"}}, indent=2) + "\n")
        return 0 if r["ok"] else 1
    p.set_defaults(func=run)


__all__ = ["stage_decompile", "run_ghidra", "re"]
