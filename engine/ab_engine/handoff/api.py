"""RPC + CLI for the agent handoff writers, and the export hook (EXECUTE Phase 5)."""

from __future__ import annotations

import json
import sys
from typing import Any

from ab_engine import api
from ab_engine.handoff import writer
from ab_engine.jobs import db as jobs_db
from ab_engine.workspace import Workspace


def h_handoff_write(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    written = writer.write_all(job)
    return {"written": written, "tasks": writer.next_tasks(writer.gather(job))}


api.register("handoff.write", h_handoff_write)


def h_loop_run(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """One turn of the whole-project loop (EXECUTE Phase 5): reconstruct → build → compare → handoff.

    Re-derives 04_reconstruction from the current evidence, rebuilds, replays every probe, then
    regenerates the handoff so the next target (locate error → patch) is named with its evidence.
    Nothing is patched automatically: the loop reports, a person or agent edits recovered_source/.
    """
    from ab_engine.jobs import runner  # noqa: PLC0415

    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, str(params.get("job_id", "")))
    if job is None:
        raise api.ApiError("not_found", "no such job")
    options = dict(params.get("options") or {})
    stages = ["RECONSTRUCTION_COMPLETE", "BUILD_COMPLETE", "VALIDATION_COMPLETE"]
    job, outcomes = runner.run_job(ws, conn, job, options=options, only=stages)
    written = writer.write_all(job)
    ev = writer.gather(job)
    if not options.get("no_checkpoint"):
        # ADDENDUM A6: the regenerated handoff belongs to the validation boundary — leave the project clean
        from pathlib import Path  # noqa: PLC0415

        from ab_engine import checkpoint  # noqa: PLC0415

        try:
            checkpoint.commit(Path(job.project_dir), "HANDOFF", metrics={"overall": (ev["diff"] or {}).get("overall")}, job_id=job.job_id)
        except Exception:  # noqa: BLE001 — a checkpoint problem never fails the loop
            pass
    diff = ev["diff"] or {}
    return {"stages": {s: {"status": (job.stage(s).status if job.stage(s) else "PENDING"), "outcome": outcomes.get(s)} for s in stages},
            "overall": diff.get("overall"), "cross_load": diff.get("cross_load"),
            "modules": [{"module": m["module"], "classification": m["classification"], "worst_rmse": m.get("worst_rmse"), "failing": m.get("failing", [])[:5]} for m in diff.get("modules", [])],
            "next": writer.next_tasks(ev)[:5], "written": written}


api.register("loop.run", h_loop_run)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("loop", "one whole-project loop turn: reconstruct → build → compare → handoff (ab-cli loop <job_id> [--option k=v])")
def _cli_loop(p):
    p.add_argument("job_id")
    p.add_argument("--option", action="append", default=[], help="stage option key=value")

    def run(args, ws):
        options = {}
        for kv in args.option:
            k, _, v = kv.partition("=")
            try:
                options[k] = json.loads(v)
            except ValueError:
                options[k] = v
        r = api.dispatch("loop.run", {"job_id": args.job_id, "options": options}, ws)
        if args.text:
            for st, o in r["stages"].items():
                sys.stdout.write(f"{st:<24} {o['status']} ({o['outcome']})\n")
            sys.stdout.write(f"overall {r['overall']} · cross-load {r['cross_load']}\n")
            for m in r["modules"]:
                sys.stdout.write(f"  {m['module']:<24} {m['classification']}\n")
            for i, t in enumerate(r["next"], 1):
                sys.stdout.write(f"next {i}: {t['task']}\n")
        else:
            sys.stdout.write(json.dumps({"ok": True, "data": r}, indent=2) + "\n")
        return 0 if all(o["status"] == "OK" for o in r["stages"].values()) else 1
    p.set_defaults(func=run)


@subcommand("handoff", "regenerate 07_agent_handoff/{HANDOFF,TODO,agent_prompt,UNRECOVERABLE}.md from all evidence")
def _cli(p):
    p.add_argument("job_id")

    def run(args, ws):
        r = api.dispatch("handoff.write", {"job_id": args.job_id}, ws)
        if args.text:
            for i, t in enumerate(r["tasks"], 1):
                sys.stdout.write(f"{i}. [{t['priority']}] {t['task']}\n")
        else:
            sys.stdout.write(json.dumps({"ok": True, "data": r}, indent=2) + "\n")
        return 0
    p.set_defaults(func=run)
