"""Steinberg VST3 SDK validator as a second validation source (EXECUTE_ADDENDUM_A §A1).

The validator is the SDK's own sample host (MIT), built next to vst3host from the pinned SDK.
It runs in an isolated worker; its text report is parsed into ``artifactbench.validator_report``:
tests passed/failed, the failing test names, and the exit code. Missing validator → NOT_RUN with
the build hint, never a fabricated pass.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ab_engine import tools as tools_mod
from ab_engine.workers.run import run_worker
from ab_engine.workspace import Workspace

RESULT_RX = re.compile(r"Result:\s*(\d+)\s+tests? passed,\s*(\d+)\s+tests? failed")
TEST_RX = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")


def parse(text: str) -> dict[str, Any]:
    passed = failed = None
    m = RESULT_RX.search(text)
    if m:
        passed, failed = int(m.group(1)), int(m.group(2))
    current = None
    failing: list[str] = []
    tests: list[dict[str, str]] = []
    for line in text.splitlines():
        s = line.strip()
        mt = TEST_RX.match(s)
        if mt and mt.group("name") not in ("Succeeded", "Failed", "XFailed"):
            current = mt.group("name")
            continue
        if s in ("[Succeeded]", "[Failed]", "[XFailed]") and current:
            tests.append({"name": current, "result": s.strip("[]")})
            if s == "[Failed]":
                failing.append(current)
            current = None
    return {"passed": passed, "failed": failed, "tests": tests, "failing": failing}


def run(ws: Workspace, log_dir: Path, plugin: Path, *, timeout: float = 300.0) -> dict[str, Any]:
    tool = tools_mod.find_validator(ws)
    if not tool.path:
        return {"status": "NOT_RUN", "reason": "SDK validator not built: native/vst3host/build_all.{sh,ps1} builds it next to vst3host (target `validator`)", "tool": "validator"}
    res = run_worker("validator", [tool.path, str(plugin)], timeout=timeout, log_dir=log_dir)
    text = ""
    try:
        text = Path(res.stdout_path or "").read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    parsed = parse(text)
    status = "TIMEOUT" if res.timed_out else ("PASSED" if res.ok and parsed["failed"] == 0 else "FAILED" if parsed["failed"] is not None else ("CRASHED" if res.exit_code not in (0, 1) else "FAILED"))
    return {"status": status, "tool": "validator", "tool_version": tool.version, "exit_code": res.exit_code, "elapsed_ms": res.elapsed_ms, "log": res.stdout_path, **parsed,
            "basis": "Steinberg VST3 SDK validator (sample host), isolated worker"}


__all__ = ["run", "parse"]
