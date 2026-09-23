"""``ab-cli doctor`` — shell, engine, disk, sandbox and tool status (SPEC §16).

Verdicts follow Prosody's four-state model: PASS recedes, WARNING and FAIL are
read, UNAVAILABLE is honest about what this machine cannot answer.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

from ab_engine import TOOL, __version__
from ab_engine import tools as tools_mod
from ab_engine.workspace import Workspace


def _row(name: str, verdict: str, detail: str) -> dict:
    return {"name": name, "verdict": verdict, "detail": detail}


def run(ws: Workspace) -> dict:
    rows: list[dict] = []
    rows.append(_row("engine", "PASS", f"{TOOL} · Python {platform.python_version()} · {'frozen' if getattr(sys, 'frozen', False) else 'source checkout'}"))
    rows.append(_row("platform", "PASS" if sys.platform == "win32" else "WARNING",
                     f"{platform.system()} {platform.release()} ({platform.machine()})"
                     + ("" if sys.platform == "win32" else " — Windows-only stages (MSVC build, WER dumps) unavailable here")))

    # -- disk --------------------------------------------------------------
    try:
        usage = shutil.disk_usage(ws.state)
        free_gb = usage.free / 1e9
        rows.append(_row("disk", "PASS" if free_gb > 5 else "WARNING" if free_gb > 1 else "FAIL",
                         f"{free_gb:.1f} GB free at {ws.state}"))
    except OSError as exc:
        rows.append(_row("disk", "FAIL", str(exc)))

    # -- workspace ---------------------------------------------------------
    for label, path in (("projects", ws.projects), ("state", ws.state), ("objects", ws.objects), ("logs", ws.logs)):
        rows.append(_row(f"folder:{label}", "PASS" if path.is_dir() and os.access(path, os.W_OK) else "FAIL", str(path)))

    # -- sandbox: can we create and remove a temp working dir? -------------
    try:
        d = tempfile.mkdtemp(prefix="ab-doctor-", dir=ws.tmp)
        Path(d, "probe").write_text("ok", encoding="utf-8")
        shutil.rmtree(d)
        rows.append(_row("sandbox", "PASS", f"temp working dirs under {ws.tmp}"))
    except OSError as exc:
        rows.append(_row("sandbox", "FAIL", str(exc)))

    # -- tools -------------------------------------------------------------
    for t in tools_mod.all_tools(ws):
        if t.present:
            rows.append(_row(f"tool:{t.name}", "PASS", f"{t.path}" + (f" · {t.version}" if t.version else "")))
        else:
            optional = t.name in ("pluginval", "msvc", "compiler", "ghidra", "jdk", "vst3host", "node", "static-engine")
            rows.append(_row(f"tool:{t.name}", "UNAVAILABLE" if optional else "FAIL", t.detail))

    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("PASS", "WARNING", "UNAVAILABLE", "FAIL")}
    return {
        "ok": counts["FAIL"] == 0,
        "rows": rows,
        "counts": counts,
        "workspace": {"home": str(ws.home), "state": str(ws.state), "version": __version__},
    }


def report(result: dict) -> str:
    """Plain-text rendering with the user's profile path replaced by ~."""
    home = str(Path.home())
    lines = [f"AB doctor — {result['workspace']['version']}"]
    for r in result["rows"]:
        lines.append(f"{r['verdict']:<12} {r['name']:<22} {r['detail'].replace(home, '~')}")
    c = result["counts"]
    lines.append(f"{c['PASS']} pass · {c['WARNING']} warning · {c['UNAVAILABLE']} unavailable · {c['FAIL']} fail")
    return "\n".join(lines)
