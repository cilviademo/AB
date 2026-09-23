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


MIN_PYTHON = (3, 11)
#: ADDENDUM B7 fresh-machine guidance: what to do when a tool is MISSING (never a crash, never a silent skip)
TOOL_GUIDANCE = {
    "ghidra": "ab-cli tools install (Ghidra 11.3.2, pinned SHA-256) — needed for DECOMPILE; other stages run without it",
    "jdk": "ab-cli tools install (Temurin JDK 21) — needed by Ghidra",
    "pluginval": "ab-cli tools install (pluginval 1.0.4) — needed for the BUILD validation gate",
    "juce": "ab-cli tools install (JUCE 8.0.9) or set AB_JUCE_DIR — needed for BUILD",
    "validator": "ab-cli tools install (VST3 SDK validator) — optional second validation",
    "vst3host": "build native/vst3host (cmake -S native/vst3host -B native/vst3host/build && cmake --build native/vst3host/build) or set AB_VST3HOST — needed for RUNTIME/PROBE",
    "node": "install Node.js 20+ — needed for the frozen Static Recovery v2 engine (STATIC)",
    "static-engine": "cd app && npm ci && npm run build — builds static-engine/dist for STATIC",
    "cmake": "install CMake 3.22+ — needed for BUILD",
    "msvc": "install Visual Studio 2022 Build Tools (Desktop C++) — needed for the Windows BUILD",
    "compiler": "install a C++17 compiler (MSVC / g++ 11+ / clang 14+) — needed for BUILD",
}


def _row(name: str, verdict: str, detail: str, *, status: str | None = None, guidance: str = "") -> dict:
    row = {"name": name, "verdict": verdict, "detail": detail}
    if status is not None:
        row["status"] = status
        row["guidance"] = guidance
    return row


def run(ws: Workspace) -> dict:
    rows: list[dict] = []
    py_ok = sys.version_info[:2] >= MIN_PYTHON
    rows.append(_row("engine", "PASS" if py_ok else "FAIL", f"{TOOL} · Python {platform.python_version()} · {'frozen' if getattr(sys, 'frozen', False) else 'source checkout'}",
                     status="AVAILABLE" if py_ok else "UNSUPPORTED", guidance="" if py_ok else f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required; install it and reinstall the engine (pip install -e engine[dev])"))
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

    # -- python dependencies (ADDENDUM A1: version, licence, pinned hash) ------------
    from ab_engine import deps  # noqa: PLC0415

    try:
        rows.extend(deps.doctor_rows())
    except Exception as exc:  # noqa: BLE001 — a broken dependency probe is a row, never a crash
        rows.append(_row("dep:probe", "FAIL", f"dependency probe raised {type(exc).__name__}: {exc}"[:200], status="MISSING", guidance="reinstall the engine: pip install -e engine[dev]"))
    # -- tools (ADDENDUM B7: AVAILABLE | MISSING with setup guidance; a probe that raises is a row) ----------
    try:
        found = tools_mod.all_tools(ws)
    except Exception as exc:  # noqa: BLE001
        found = []
        rows.append(_row("tool:probe", "FAIL", f"tool probe raised {type(exc).__name__}: {exc}"[:200], status="MISSING", guidance="run `ab-cli doctor` again after checking the tools folder; report the message above"))
    for t in found:
        if t.present:
            rows.append(_row(f"tool:{t.name}", "PASS", f"{t.path}" + (f" · {t.version}" if t.version else ""), status="AVAILABLE"))
        else:
            optional = t.name in ("pluginval", "msvc", "compiler", "ghidra", "jdk", "vst3host", "node", "static-engine", "juce", "validator")
            rows.append(_row(f"tool:{t.name}", "UNAVAILABLE" if optional else "FAIL", t.detail, status="MISSING", guidance=TOOL_GUIDANCE.get(t.name, "see docs/DEVELOPMENT.md")))

    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("PASS", "WARNING", "UNAVAILABLE", "FAIL")}
    statuses = {v: sum(1 for r in rows if r.get("status") == v) for v in ("AVAILABLE", "MISSING", "WRONG_VERSION", "UNSUPPORTED")}
    return {
        "ok": counts["FAIL"] == 0,
        "rows": rows,
        "counts": counts,
        "dependency_status": statuses,
        "setup": [{"name": r["name"], "status": r["status"], "guidance": r["guidance"]} for r in rows if r.get("status") in ("MISSING", "WRONG_VERSION", "UNSUPPORTED")],
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
    for s in result.get("setup", []):
        lines.append(f"  {s['status']:<14} {s['name']:<20} {s['guidance']}")
    return "\n".join(lines)
