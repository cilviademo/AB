"""Lineage and corpus mode (SPEC §9, EXECUTE 3.4) and the knowledge cache RPC.

* ``lineage.report`` — LINEAGE_REPORT.md per plugin: INFERRED_CODEBASE_FAMILY from
  class-name-set Jaccard (v2 CLASS_NAME_GRAPH_CLUSTER, connected components ≥ 0.5,
  kept and labelled INFERRED) plus average-link and medoid similarity; shared
  resources by hash; state-schema overlap; and, when fingerprints exist,
  SHARED_IMPLEMENTATION_* matches per function. SYMBOL_LINEAGE_FINGERPRINT
  (recurring uncommon spellings) recorded as supporting evidence only.
* ``corpus.run`` — the frozen v2 corpus layer over every job that has a
  static_group.json (Node host), written to ``<home>/Corpus/``.
* ``knowledge.*`` — seed / match / stats for the known-library cache.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from ab_engine import api
from ab_engine import tools as tools_mod
from ab_engine.jobs import db as jobs_db
from ab_engine.lineage.knowledge import STATES, Knowledge
from ab_engine.workers.run import run_worker
from ab_engine.workspace import Workspace

TYPO_HINTS = ("DisotrtionEffect", "ParametericEQ")


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")).get("data") if p.is_file() else None


def _owned_set(pd: Path) -> set[str]:
    return {c["recovered_name"] for c in (_load(pd / "01_evidence" / "rtti" / "classes.json") or []) if c.get("kind") == "PLUGIN_OWNED_CANDIDATE"}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def families(keys: list[str], sets: dict[str, set[str]], threshold: float = 0.5) -> dict[str, Any]:
    pairs = [(a, b, round(jaccard(sets[a], sets[b]), 3)) for i, a in enumerate(keys) for b in keys[i + 1:]]
    parent = {k: k for k in keys}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, j in pairs:
        if j >= threshold:
            parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    fams = []
    for members in groups.values():
        # average-link and medoid: the member with the highest mean similarity to the others
        sims = {m: [j for a, b, j in pairs if m in (a, b) and (a in members and b in members)] for m in members}
        avg = {m: (sum(v) / len(v) if v else 1.0) for m, v in sims.items()}
        medoid = max(members, key=lambda m: avg[m])
        fams.append({"members": sorted(members), "size": len(members), "average_link": round(sum(avg.values()) / len(avg), 3), "medoid": medoid,
                     "status": "INFERRED_CODEBASE_FAMILY", "basis": "class-name-set Jaccard ≥ 0.5 connected components (name evidence only)"})
    fams.sort(key=lambda f: -f["size"])
    return {"pairs": sorted(pairs, key=lambda p: -p[2]), "families": fams, "threshold": threshold}


def h_lineage_report(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    jobs = jobs_db.list_jobs(conn)
    target = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if target is None:
        raise api.ApiError("not_found", "no such job")
    sets = {j.job_id: _owned_set(Path(j.project_dir)) for j in jobs}
    keys = [j.job_id for j in jobs if sets[j.job_id]]
    fam = families(keys, sets) if len(keys) > 1 else {"pairs": [], "families": [], "threshold": 0.5}
    names = {j.job_id: j.name for j in jobs}
    my = sets.get(target.job_id, set())
    mine = next((f for f in fam["families"] if target.job_id in f["members"]), None)
    # shared resources by hash
    res_by_job = {}
    for j in jobs:
        res_by_job[j.job_id] = {r["sha256"] for r in (_load(Path(j.project_dir) / "01_evidence" / "resources" / "index.json") or []) if r.get("sha256")}
    shared_res = {}
    for j in jobs:
        if j.job_id == target.job_id:
            continue
        common = res_by_job.get(target.job_id, set()) & res_by_job.get(j.job_id, set())
        if common:
            shared_res[names[j.job_id]] = len(common)
    # state-schema overlap
    keys_by_job = {j.job_id: {k["name"] for k in (_load(Path(j.project_dir) / "03_architecture" / "serialized_keys.json") or [])} for j in jobs}
    schema_overlap = {names[j.job_id]: round(jaccard(keys_by_job[target.job_id], keys_by_job[j.job_id]), 3) for j in jobs if j.job_id != target.job_id and keys_by_job[j.job_id]}
    # implementation matches from the knowledge cache
    fps = (_load(Path(target.project_dir) / "01_evidence" / "decompiler" / "fingerprints.json") or {}).get("functions", [])
    kn = Knowledge(ws.knowledge)
    km = kn.match_all(fps) if fps else None
    typos = sorted(c for c in my if any(t.lower() in c.lower() for t in TYPO_HINTS))
    unique = sorted(c for c in my if all(c not in sets[k] for k in keys if k != target.job_id))
    lines = [f"# LINEAGE_REPORT — {target.name}", "",
             f"Family: {'INFERRED_CODEBASE_FAMILY of ' + str(mine['size']) + ' (medoid ' + names[mine['medoid']] + ', average link ' + str(mine['average_link']) + ')' if mine and mine['size'] > 1 else 'no family inferred (single plugin or no shared owned class names)'}",
             "Family membership is INFERRED from class-name-set similarity until implementation fingerprints reinforce it (SPEC §1.4).", "",
             "## Verified shared implementation matches (function fingerprints, knowledge cache)",
             *([f"- {km['counts']}: {km['suppressed']} functions suppressed as known framework/third-party, {km['downgraded']} cache matches downgraded on contradiction"] if km else ["- no fingerprints yet (decompiler stage not run)"]),
             "", "## Near matches (class-name Jaccard, top 5)",
             *([f"- {names[p[0]] if p[1] == target.job_id else names[p[1]]}: {p[2]}" for p in fam["pairs"] if target.job_id in p[:2]][:5] or ["- none"]),
             "", "## Shared resources (identical SHA-256)", *([f"- {k}: {v}" for k, v in shared_res.items()] or ["- none"]),
             "", "## State-schema overlap (serialized key Jaccard)", *([f"- {k}: {v}" for k, v in sorted(schema_overlap.items(), key=lambda kv: -kv[1])[:10]] or ["- none"]),
             "", f"## Unique owned class names ({len(unique)}) — where deep analysis should focus", *[f"- {c}" for c in unique[:60]],
             "", "## SYMBOL_LINEAGE_FINGERPRINT (supporting evidence only)", *([f"- {c}" for c in typos] or ["- none"]),
             "", "## Deep-analysis priority list", "- see 01_evidence/decompiler/dsp_candidates.md (priority = reachability × plugin-specific × parameter refs × DSP evidence × not known)"]
    report = "\n".join(lines) + "\n"
    (Path(target.project_dir) / "LINEAGE_REPORT.md").write_text(report, encoding="utf-8")
    return {"report": report, "families": fam["families"], "pairs": fam["pairs"][:50], "knowledge": {k: v for k, v in (km or {}).items() if k != "results"}, "unique_owned": unique}


def h_corpus_run(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    groups = [Path(j.project_dir) / "static_group.json" for j in jobs_db.list_jobs(conn) if (Path(j.project_dir) / "static_group.json").is_file()]
    if len(groups) < 2:
        raise api.ApiError("not_enough", "corpus mode needs two or more jobs analysed by the Node static host (static_group.json)")
    node, cli = tools_mod.find_node(ws), tools_mod.find_static_engine_cli()
    if not node.present or not cli.present:
        raise api.ApiError("unavailable", "corpus mode needs Node and the built static engine")
    out = ws.home / "Corpus"
    res = run_worker("static-engine", [node.path or "node", cli.path or "", "corpus", "--groups", ",".join(str(g) for g in groups), "--out", str(out)],
                     timeout=600, log_dir=ws.logs / "corpus", parse_json_stdout=True)
    if not res.ok:
        raise api.ApiError("CORPUS_FAILED", f"static engine corpus exit {res.exit_code}")
    return {"out_dir": str(out), "plugins": len(groups), "report": (out / "corpus" / "CORPUS_REPORT.md").read_text(encoding="utf-8") if (out / "corpus" / "CORPUS_REPORT.md").is_file() else ""}


def h_knowledge_seed(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """Seed from a job's fingerprints. state defaults: framework/third-party only (EXECUTE 3.4)."""
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    state = str(params.get("state", "KNOWN_FRAMEWORK"))
    if state not in STATES:
        raise api.ApiError("bad_request", f"state must be one of {STATES}")
    prefixes = set(params.get("name_prefixes") or (["juce::", "_ZN4juce", "juce"] if state == "KNOWN_FRAMEWORK" else []))
    fps = (_load(Path(job.project_dir) / "01_evidence" / "decompiler" / "fingerprints.json") or {}).get("functions", [])
    kn = Knowledge(ws.knowledge)
    n = kn.seed_functions(fps, state=state, source_hash=job.artifact_sha256, library=params.get("library"), compiler=None, tool_version="ghidra/Fingerprint.java",
                          only_names=prefixes or None)
    r = kn.seed_resources(_load(Path(job.project_dir) / "01_evidence" / "resources" / "index.json") or [], state=state, source_hash=job.artifact_sha256)
    return {"seeded_functions": n, "seeded_resources": r, "stats": kn.stats()}


def h_knowledge_match(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    fps = (_load(Path(job.project_dir) / "01_evidence" / "decompiler" / "fingerprints.json") or {}).get("functions", [])
    r = Knowledge(ws.knowledge).match_all(fps)
    keep = {k: v for k, v in r["results"].items() if v.get("matched")}
    r["results"] = dict(list(keep.items())[:2000])
    return r


def h_knowledge_stats(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    return Knowledge(ws.knowledge).stats()


for _n, _h in {"lineage.report": h_lineage_report, "corpus.run": h_corpus_run, "knowledge.seed": h_knowledge_seed, "knowledge.match": h_knowledge_match, "knowledge.stats": h_knowledge_stats}.items():
    api.register(_n, _h)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("lineage", "write LINEAGE_REPORT.md for a job")
def _cli_lineage(p):
    p.add_argument("job_id")

    def run(args, ws):
        sys.stdout.write(api.dispatch("lineage.report", {"job_id": args.job_id}, ws)["report"])
        return 0
    p.set_defaults(func=run)


@subcommand("knowledge", "known-library cache: ab-cli knowledge stats | seed <job_id> [--state S] | match <job_id>")
def _cli_knowledge(p):
    p.add_argument("action", choices=["stats", "seed", "match"])
    p.add_argument("job_id", nargs="?")
    p.add_argument("--state", default="KNOWN_FRAMEWORK", choices=STATES)
    p.add_argument("--prefix", action="append", dest="prefixes")

    def run(args, ws):
        if args.action == "stats":
            r = api.dispatch("knowledge.stats", {}, ws)
        elif args.action == "seed":
            r = api.dispatch("knowledge.seed", {"job_id": args.job_id, "state": args.state, "name_prefixes": args.prefixes}, ws)
        else:
            r = api.dispatch("knowledge.match", {"job_id": args.job_id}, ws)
            r = {k: v for k, v in r.items() if k != "results"}
        sys.stdout.write(json.dumps({"ok": True, "data": r}, indent=2) + "\n")
        return 0
    p.set_defaults(func=run)


__all__ = ["h_lineage_report", "families", "re", "tempfile"]
