"""Stage pipeline with the SPEC §5 cache rule.

A stage is reused (zero work) when its cache key
``sha256(artifact) + tool_version + stage_version + config_hash`` matches the
stored OK record. Running a stage invalidates only the stages after it.
Every stage record is written before the run (RUNNING) and after (OK / FAILED
/ SKIPPED) both to ``jobs.db`` and to ``<project>/stages/<stage>.json``
(``artifactbench.stage``), so a partial output is never left unmarked.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ab_engine import TOOL, api
from ab_engine.contracts import write_json
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs.model import RAIL, STAGES, Job, StageRecord, cache_key, config_hash, downstream, stage_index
from ab_engine.jobs.store import ObjectStore
from ab_engine.obs.log import JobLog
from ab_engine.workspace import Workspace


class StageSkipped(Exception):
    """Raised by a stage that cannot run here (missing tool, third-party mode…)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StageFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class StageContext:
    ws: Workspace
    job: Job
    project_dir: Path
    store: ObjectStore
    conn: Any
    log: JobLog
    options: dict[str, Any]
    cancel: threading.Event
    warnings: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    completeness: str = "NOT_APPLICABLE"
    input_hashes: list[str] = field(default_factory=list)
    tool_versions: dict[str, str] = field(default_factory=dict)

    def progress(self, detail: str, **extra: Any) -> None:
        api.progress(self._rail, "running", detail, **extra)

    def warn(self, code: str, message: str) -> None:
        self.warnings.append({"code": code, "message": message})
        self.log.warn(message, code=code)

    def output(self, rel: str) -> None:
        if rel not in self.outputs:
            self.outputs.append(rel)

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise StageFailed("CANCELLED", "cancelled by the user")

    _rail: str = ""


@dataclass
class StageImpl:
    """One stage implementation registered with the runner."""

    stage: str
    version: int
    run: Callable[[StageContext], None]
    tool_version: str = TOOL
    #: option keys this stage's config hash depends on (others do not invalidate it)
    config_keys: tuple[str, ...] = ()


_REGISTRY: dict[str, StageImpl] = {}
_CANCEL: dict[str, threading.Event] = {}


def register_stage(impl: StageImpl) -> None:
    _REGISTRY[impl.stage] = impl


def registered() -> dict[str, StageImpl]:
    return dict(_REGISTRY)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_stage_file(project_dir: Path, rec: StageRecord) -> None:
    write_json(project_dir / "stages" / f"{rec.stage}.json", "artifactbench.stage", rec.contract_data())


def _config_for(impl: StageImpl, options: dict[str, Any]) -> dict[str, Any]:
    return {k: options[k] for k in impl.config_keys if k in options}


def plan(job: Job, options: dict[str, Any], only: list[str] | None = None) -> list[tuple[str, str]]:
    """What ``run_job`` would do: ``[(stage, 'reuse' | 'run' | 'unregistered')]``."""
    out: list[tuple[str, str]] = []
    for stage in STAGES:
        if only and stage not in only:
            continue
        impl = _REGISTRY.get(stage)
        if impl is None:
            out.append((stage, "unregistered"))
            continue
        key = cache_key(job.artifact_sha256, impl.tool_version, impl.version, config_hash(_config_for(impl, options)))
        rec = job.stage(stage)
        out.append((stage, "reuse" if rec and rec.status == "OK" and rec.cache_key == key else "run"))
    return out


def cancel(job_id: str) -> bool:
    ev = _CANCEL.get(job_id)
    if ev is None:
        return False
    ev.set()
    return True


def run_job(ws: Workspace, conn: Any, job: Job, *, options: dict[str, Any] | None = None,
            only: list[str] | None = None, stop_after: str | None = None) -> tuple[Job, dict[str, str]]:
    """Run every registered stage in order, honouring the cache. Returns the job and ``{stage: outcome}``."""
    options = dict(options or {})
    project_dir = Path(job.project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    store = ObjectStore(ws.objects, conn)
    log = JobLog(ws.logs / job.job_id / "job.jsonl")
    cancel_ev = _CANCEL.setdefault(job.job_id, threading.Event())
    cancel_ev.clear()
    outcomes: dict[str, str] = {}
    failed_upstream: str | None = None

    for stage in STAGES:
        if only and stage not in only:
            continue
        impl = _REGISTRY.get(stage)
        if impl is None:
            continue
        rail = RAIL[stage]
        rec = job.stage(stage) or StageRecord(job.job_id, stage)
        cfg = _config_for(impl, options)
        key = cache_key(job.artifact_sha256, impl.tool_version, impl.version, config_hash(cfg))

        if failed_upstream is not None:
            rec.status, rec.skip_reason = "SKIPPED", f"upstream stage {failed_upstream} did not complete"
            rec.cache_key = ""
            _store(conn, job, rec, project_dir)
            api.progress(rail, "skipped", rec.skip_reason)
            outcomes[stage] = "skipped"
            continue

        if rec.status == "OK" and rec.cache_key == key:
            outcomes[stage] = "reuse"
            log.op("STAGE_REUSE", stage=stage, cache_key=key)
            api.progress(rail, "ok", "reused (inputs, tool, stage version and config unchanged)")
            continue

        # Running this stage invalidates everything after it, nothing before (SPEC §5).
        for later in downstream(stage):
            later_rec = job.stage(later)
            if later_rec and later_rec.status != "PENDING":
                later_rec.status, later_rec.cache_key, later_rec.ended = "PENDING", "", None
                later_rec.skip_reason = None
                _store(conn, job, later_rec, project_dir)

        rec = StageRecord(job.job_id, stage, status="RUNNING", started=_now(), config_hash=config_hash(cfg),
                          stage_version=impl.version, cache_key=key, tool_versions={"engine": impl.tool_version})
        _store(conn, job, rec, project_dir)
        api.progress(rail, "running", "starting")
        log.op("STAGE_START", stage=stage, cache_key=key, config=cfg)
        ctx = StageContext(ws=ws, job=job, project_dir=project_dir, store=store, conn=conn, log=log,
                           options=options, cancel=cancel_ev, tool_versions={"engine": impl.tool_version})
        ctx._rail = rail
        t0 = time.monotonic()
        try:
            impl.run(ctx)
            rec.status = "OK"
            outcomes[stage] = "run"
            api.progress(rail, "ok", f"{int((time.monotonic() - t0) * 1000)} ms · {ctx.completeness}")
        except StageSkipped as exc:
            rec.status, rec.skip_reason, rec.cache_key = "SKIPPED", exc.reason, ""
            outcomes[stage] = "skipped"
            api.progress(rail, "skipped", exc.reason)
        except StageFailed as exc:
            rec.status, rec.cache_key = "FAILED", ""
            rec.errors.append({"code": exc.code, "message": exc.message})
            outcomes[stage] = "failed"
            failed_upstream = stage
            log.error(exc.message, code=exc.code, stage=stage)
            api.progress(rail, "failed", f"{exc.code}: {exc.message}")
        except Exception as exc:  # noqa: BLE001 - a stage bug fails its stage only
            rec.status, rec.cache_key = "FAILED", ""
            rec.errors.append({"code": "STAGE_EXCEPTION", "message": f"{type(exc).__name__}: {exc}"})
            outcomes[stage] = "failed"
            failed_upstream = stage
            log.error(str(exc), code="STAGE_EXCEPTION", stage=stage, trace=traceback.format_exc(limit=8))
            api.progress(rail, "failed", f"STAGE_EXCEPTION: {exc}")
        finally:
            rec.ended = _now()
            rec.warnings, rec.outputs, rec.metrics = ctx.warnings, ctx.outputs, dict(ctx.metrics)
            rec.metrics.setdefault("elapsed_ms", int((time.monotonic() - t0) * 1000))
            rec.completeness = ctx.completeness
            rec.input_hashes = ctx.input_hashes or [job.artifact_sha256]
            rec.tool_versions = ctx.tool_versions
            _store(conn, job, rec, project_dir)
            log.op("STAGE_END", stage=stage, status=rec.status, elapsed_ms=rec.metrics.get("elapsed_ms"))
        if stop_after == stage:
            break

    refreshed = jobs_db.get_job(conn, job.job_id) or job
    return refreshed, outcomes


def _store(conn: Any, job: Job, rec: StageRecord, project_dir: Path) -> None:
    existing = job.stage(rec.stage)
    if existing is None:
        job.stages.append(rec)
        job.stages.sort(key=lambda s: stage_index(s.stage))
    elif existing is not rec:
        job.stages[job.stages.index(existing)] = rec
    jobs_db.put_stage(conn, rec)
    _write_stage_file(project_dir, rec)
