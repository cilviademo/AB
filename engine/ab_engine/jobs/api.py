"""RPC methods and CLI twins for jobs (EXECUTE 1.2)."""

from __future__ import annotations

import json
import sys

from ab_engine import api
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs import runner
from ab_engine.jobs.model import STAGES
from ab_engine.workspace import Workspace


def _job(ws: Workspace, job_id: str):
    conn = jobs_db.connect(ws.db_path)
    job = jobs_db.get_job(conn, job_id)
    if job is None:
        raise api.ApiError("not_found", f"no job {job_id}")
    return conn, job


def h_job_list(params, ws: Workspace):
    conn = jobs_db.connect(ws.db_path)
    return {"jobs": [j.as_dict() for j in jobs_db.list_jobs(conn)]}


def h_job_get(params, ws: Workspace):
    _, job = _job(ws, str(params.get("job_id", "")))
    return job.as_dict()


def h_job_run(params, ws: Workspace):
    conn, job = _job(ws, str(params.get("job_id", "")))
    stages = params.get("stages")
    if stages is not None and not (isinstance(stages, list) and all(s in STAGES for s in stages)):
        raise api.ApiError("bad_request", f"stages must be a list of {', '.join(STAGES)}")
    options = params.get("options") or {}
    if not isinstance(options, dict):
        raise api.ApiError("bad_request", "options must be an object")
    job, outcomes = runner.run_job(ws, conn, job, options=options, only=stages, stop_after=params.get("stop_after"))
    d = job.as_dict()
    d["outcomes"] = outcomes
    return d


def h_job_plan(params, ws: Workspace):
    _, job = _job(ws, str(params.get("job_id", "")))
    return {"plan": [{"stage": s, "action": a} for s, a in runner.plan(job, params.get("options") or {}, params.get("stages"))]}


def h_job_cancel(params, ws: Workspace):
    return {"cancelled": runner.cancel(str(params.get("job_id", "")))}


def h_job_delete(params, ws: Workspace):
    conn, job = _job(ws, str(params.get("job_id", "")))
    from ab_engine.jobs.store import ObjectStore  # noqa: PLC0415

    store = ObjectStore(ws.objects, conn)
    for i in jobs_db.get_inputs(conn, job.job_id):
        if store.has(i["sha256"]):
            store.release(i["sha256"])
    jobs_db.delete_job(conn, job.job_id)
    return {"deleted": job.job_id}


for _name, _h in {
    "job.list": h_job_list, "job.get": h_job_get, "job.run": h_job_run, "job.plan": h_job_plan,
    "job.cancel": h_job_cancel, "job.delete": h_job_delete,
}.items():
    api.register(_name, _h)


# -- CLI twins ---------------------------------------------------------------- #

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("jobs", "list recovery jobs")
def _cli_jobs(p):
    def run(args, ws):
        for j in jobs_db.list_jobs(jobs_db.connect(ws.db_path)):
            done = ",".join(s.stage.replace("_COMPLETE", "") for s in j.stages if s.status == "OK")
            sys.stdout.write(f"{j.job_id}  {j.ownership:<11} {j.artifact_sha256[:12]}  {j.name}  [{done or 'INGESTED?'}]\n")
        return 0
    p.set_defaults(func=run)


@subcommand("run", "run stages of a job (ab-cli run <job_id> [--stage STAGE ...])")
def _cli_run(p):
    p.add_argument("job_id")
    p.add_argument("--stage", action="append", dest="stages", choices=STAGES, help="run only these stages")
    p.add_argument("--stop-after", choices=STAGES)
    p.add_argument("--option", action="append", default=[], help="key=value stage option")
    p.add_argument("--plan", action="store_true", help="show what would run and why")

    def run(args, ws):
        options = {}
        for kv in args.option:
            k, _, v = kv.partition("=")
            try:
                options[k] = json.loads(v)
            except ValueError:
                options[k] = v
        params = {"job_id": args.job_id, "stages": args.stages, "options": options, "stop_after": args.stop_after}
        result = api.dispatch("job.plan" if args.plan else "job.run", params, ws)
        sys.stdout.write(json.dumps({"ok": True, "data": result}, indent=2) + "\n")
        if not args.plan and any(s["status"] == "FAILED" for s in result["stages"]):
            return 1
        return 0
    p.set_defaults(func=run)
