"""Local Git checkpoints for the reconstructed project (EXECUTE_ADDENDUM_A §A6).

Each recovery project folder is a local Git repository initialised at ingest; the engine commits
at stage boundaries with fixed prefixes:

    ingest: add recovered artifacts
    recovery: import verified runtime metadata
    recovery: add RTTI and callgraph evidence
    reconstruction: implement <module>
    validation: <module> matched original (<state>, rmse=<x>)
    build: validated VST3 reconstruction
    export: repo-ready bundle

Transient analysis events are not committed. Large binaries (the original module copy, renders,
rebuilt bundles, build trees) are ignored and referenced through ``00_manifest/hashes.json`` and
the object store; the commit carries the evidence, architecture, sources and reports. GitHub push
is never automatic (BLOCKERS B-006). A missing ``git`` records ``GIT_UNAVAILABLE`` and never fails
a stage.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

GITIGNORE = """# AB project checkpoints: evidence objects are referenced by hash (00_manifest/hashes.json), large binaries stay out
runtime/
04_reconstruction/build/
04_reconstruction/JUCE/
05_reference_behavior/original_renders/
06_validation/rebuild_renders/
*.wav
*.vst3/
*.so
*.dll
*.dylib
*.pdb
build/
"""

PREFIX = {
    "INGESTED": "ingest: add recovered artifacts",
    "STATIC_COMPLETE": "recovery: add static evidence (Static Recovery v2, inventory, candidate families)",
    "RUNTIME_COMPLETE": "recovery: import verified runtime metadata",
    "DECOMPILATION_COMPLETE": "recovery: add RTTI and callgraph evidence",
    "BEHAVIOR_COMPLETE": "recovery: add reference behaviour measurements",
    "RECONSTRUCTION_COMPLETE": "reconstruction: implement {modules}",
    "BUILD_COMPLETE": "build: validated VST3 reconstruction",
    "VALIDATION_COMPLETE": "validation: {module} matched original ({state}, rmse={rmse})",
    "EXPORT_COMPLETE": "export: repo-ready bundle",
    "HANDOFF": "validation: agent handoff regenerated (HANDOFF, TODO, UNRECOVERABLE)",
}


def _git(project: Path, *args: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "LANG")}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "AB Artifact Bench", "GIT_AUTHOR_EMAIL": "ab@localhost",
                "GIT_COMMITTER_NAME": "AB Artifact Bench", "GIT_COMMITTER_EMAIL": "ab@localhost"})
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, timeout=timeout, env=env, check=False)


def available() -> bool:
    return shutil.which("git") is not None


def init(project: Path) -> dict[str, Any]:
    if not available():
        return {"status": "GIT_UNAVAILABLE"}
    project.mkdir(parents=True, exist_ok=True)
    if not (project / ".git").is_dir():
        r = _git(project, "init", "-q", "-b", "main")
        if r.returncode != 0:
            r = _git(project, "init", "-q")
            if r.returncode != 0:
                return {"status": "GIT_INIT_FAILED", "detail": r.stderr.strip()[:300]}
    gi = project / ".gitignore"
    if not gi.is_file():
        gi.write_text(GITIGNORE, encoding="utf-8")
    return {"status": "OK", "repo": str(project)}


def message_for(stage: str, metrics: dict[str, Any] | None) -> str:
    m = metrics or {}
    tpl = PREFIX.get(stage, f"recovery: {stage.lower()}")
    if stage == "RECONSTRUCTION_COMPLETE":
        mods = ", ".join(x.get("name", "?") for x in m.get("modules_detail", [])) or "shell only"
        return tpl.format(modules=mods)
    if stage == "VALIDATION_COMPLETE":
        mods = m.get("modules") or {}
        module = "Waveshaper" if "Waveshaper" in mods else (next(iter(mods), "plugin"))
        return tpl.format(module=module, state=mods.get(module, m.get("overall", "NOT_VALIDATED")), rmse=m.get("waveshaper_rmse", "n/a"))
    return tpl


def commit(project: Path, stage: str, *, metrics: dict[str, Any] | None = None, job_id: str = "") -> dict[str, Any]:
    """Commit the project state for a completed stage. Nothing to commit is not an error."""
    if not available():
        return {"status": "GIT_UNAVAILABLE"}
    if not (project / ".git").is_dir():
        r = init(project)
        if r["status"] != "OK":
            return r
    add = _git(project, "add", "-A")
    if add.returncode != 0:
        return {"status": "GIT_ADD_FAILED", "detail": add.stderr.strip()[:300]}
    if _git(project, "diff", "--cached", "--quiet").returncode == 0:
        return {"status": "NOTHING_TO_COMMIT", "stage": stage}
    msg = message_for(stage, metrics)
    body = f"{msg}\n\nstage: {stage}\njob: {job_id}\n"
    r = _git(project, "commit", "-q", "-m", body)
    if r.returncode != 0:
        return {"status": "GIT_COMMIT_FAILED", "detail": (r.stderr or r.stdout).strip()[:300]}
    head = _git(project, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"status": "COMMITTED", "stage": stage, "commit": head, "message": msg}


def log(project: Path, limit: int = 50) -> list[dict[str, str]]:
    if not available() or not (project / ".git").is_dir():
        return []
    r = _git(project, "log", f"-{limit}", "--pretty=format:%h%x1f%s")
    out = []
    for line in r.stdout.splitlines():
        if "\x1f" in line:
            h, s = line.split("\x1f", 1)
            out.append({"commit": h, "subject": s})
    return out


def status_clean(project: Path) -> bool:
    if not available() or not (project / ".git").is_dir():
        return False
    return _git(project, "status", "--porcelain").stdout.strip() == ""


__all__ = ["init", "commit", "log", "status_clean", "message_for", "available"]
