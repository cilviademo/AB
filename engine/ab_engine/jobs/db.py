"""SQLite ``jobs.db`` (EXECUTE 1.2): jobs, stages, inputs, objects refcounts.

One file, WAL mode, every write in a short transaction. The database is state,
never evidence: evidence lives in the project folders and the object store.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ab_engine.jobs.model import Job, StageRecord

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, name TEXT NOT NULL, artifact_sha256 TEXT NOT NULL, ownership TEXT NOT NULL,
    created TEXT NOT NULL, primary_path TEXT NOT NULL, project_dir TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stages (
    job_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
    input_hashes TEXT NOT NULL, tool_versions TEXT NOT NULL, config_hash TEXT NOT NULL, stage_version INTEGER NOT NULL,
    started TEXT, ended TEXT, warnings TEXT NOT NULL, errors TEXT NOT NULL, outputs TEXT NOT NULL,
    completeness TEXT NOT NULL, metrics TEXT NOT NULL, skip_reason TEXT, cache_key TEXT NOT NULL,
    PRIMARY KEY (job_id, stage), FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS inputs (
    job_id TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
    kind TEXT NOT NULL, attached_to TEXT, PRIMARY KEY (job_id, path),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS objects (sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, refs INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_jobs_artifact ON jobs(artifact_sha256);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_DDL)
    # D-026 migration: the ownership column keeps its name (SQLite), holds the usage_context; source_availability is new
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "source_availability" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN source_availability TEXT NOT NULL DEFAULT 'SOURCE_UNKNOWN'")
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    elif int(row["value"]) > SCHEMA_VERSION:
        raise RuntimeError(f"jobs.db schema {row['value']} is newer than this engine ({SCHEMA_VERSION})")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# -- jobs ------------------------------------------------------------------- #

def upsert_job(conn: sqlite3.Connection, job: Job) -> None:
    with tx(conn):
        conn.execute(
            "INSERT OR REPLACE INTO jobs (job_id, name, artifact_sha256, ownership, created, primary_path, project_dir, source_availability) VALUES (?,?,?,?,?,?,?,?)",
            (job.job_id, job.name, job.artifact_sha256, job.usage_context, job.created, job.primary, job.project_dir, job.source_availability),
        )
        for s in job.stages:
            _put_stage(conn, s)


def _put_stage(conn: sqlite3.Connection, s: StageRecord) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO stages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (s.job_id, s.stage, s.status, json.dumps(s.input_hashes), json.dumps(s.tool_versions), s.config_hash,
         s.stage_version, s.started, s.ended, json.dumps(s.warnings), json.dumps(s.errors), json.dumps(s.outputs),
         s.completeness, json.dumps(s.metrics), s.skip_reason, s.cache_key),
    )


def put_stage(conn: sqlite3.Connection, s: StageRecord) -> None:
    with tx(conn):
        _put_stage(conn, s)


def _stage_from_row(r: sqlite3.Row) -> StageRecord:
    return StageRecord(
        job_id=r["job_id"], stage=r["stage"], status=r["status"], input_hashes=json.loads(r["input_hashes"]),
        tool_versions=json.loads(r["tool_versions"]), config_hash=r["config_hash"], stage_version=r["stage_version"],
        started=r["started"], ended=r["ended"], warnings=json.loads(r["warnings"]), errors=json.loads(r["errors"]),
        outputs=json.loads(r["outputs"]), completeness=r["completeness"], metrics=json.loads(r["metrics"]),
        skip_reason=r["skip_reason"], cache_key=r["cache_key"],
    )


def get_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    r = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if r is None:
        return None
    stages = [_stage_from_row(s) for s in conn.execute("SELECT * FROM stages WHERE job_id=?", (job_id,))]
    from ab_engine.jobs.model import STAGES  # noqa: PLC0415

    stages.sort(key=lambda s: STAGES.index(s.stage) if s.stage in STAGES else 99)
    return Job(r["job_id"], r["name"], r["artifact_sha256"], r["ownership"], r["created"], r["primary_path"],
               r["project_dir"], stages, source_availability=(r["source_availability"] if "source_availability" in r.keys() and r["source_availability"] else "SOURCE_UNKNOWN"))


def list_jobs(conn: sqlite3.Connection) -> list[Job]:
    ids = [r["job_id"] for r in conn.execute("SELECT job_id FROM jobs ORDER BY created DESC")]
    return [j for j in (get_job(conn, i) for i in ids) if j is not None]


def find_job_by_artifact(conn: sqlite3.Connection, sha256: str) -> Job | None:
    r = conn.execute("SELECT job_id FROM jobs WHERE artifact_sha256=? ORDER BY created DESC", (sha256,)).fetchone()
    return get_job(conn, r["job_id"]) if r else None


def delete_job(conn: sqlite3.Connection, job_id: str) -> None:
    with tx(conn):
        conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))


# -- inputs ----------------------------------------------------------------- #

def put_inputs(conn: sqlite3.Connection, job_id: str, inputs: list[dict[str, Any]]) -> None:
    with tx(conn):
        conn.execute("DELETE FROM inputs WHERE job_id=?", (job_id,))
        conn.executemany(
            "INSERT INTO inputs VALUES (?,?,?,?,?,?)",
            [(job_id, i["path"], int(i["size"]), i["sha256"], i["kind"], i.get("attached_to")) for i in inputs],
        )


def get_inputs(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT path, size, sha256, kind, attached_to FROM inputs WHERE job_id=? ORDER BY path", (job_id,))]


# -- objects (refcounts; bytes live in the store) ---------------------------- #

def object_ref(conn: sqlite3.Connection, sha256: str, size: int, delta: int = 1) -> int:
    with tx(conn):
        conn.execute("INSERT INTO objects(sha256, size, refs) VALUES (?,?,0) ON CONFLICT(sha256) DO NOTHING", (sha256, size))
        conn.execute("UPDATE objects SET refs = MAX(0, refs + ?) WHERE sha256=?", (delta, sha256))
        return int(conn.execute("SELECT refs FROM objects WHERE sha256=?", (sha256,)).fetchone()["refs"])


def object_refs(conn: sqlite3.Connection, sha256: str) -> int | None:
    r = conn.execute("SELECT refs FROM objects WHERE sha256=?", (sha256,)).fetchone()
    return int(r["refs"]) if r else None


def unreferenced_objects(conn: sqlite3.Connection) -> list[str]:
    return [r["sha256"] for r in conn.execute("SELECT sha256 FROM objects WHERE refs <= 0")]


def forget_object(conn: sqlite3.Connection, sha256: str) -> None:
    with tx(conn):
        conn.execute("DELETE FROM objects WHERE sha256=?", (sha256,))
