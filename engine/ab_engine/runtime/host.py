"""Python side of vst3host (SPEC §7): one isolated process per command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ab_engine import tools as tools_mod
from ab_engine.workers.run import WorkerResult, run_worker
from ab_engine.workspace import Workspace


class HostError(Exception):
    def __init__(self, code: str, detail: str, result: WorkerResult | None = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.result = code, detail, result


EXIT_CODES = {2: "LOAD_FAILURE", 3: "PLUGIN_CRASH", 4: "HOST_TIMEOUT", 5: "BAD_REQUEST"}


class Vst3Host:
    def __init__(self, ws: Workspace, log_dir: Path, *, timeout: float = 60.0) -> None:
        self.ws = ws
        self.log_dir = log_dir
        self.timeout = timeout
        tool = tools_mod.find_vst3host(ws)
        self.path = tool.path
        self.version = tool.version

    @property
    def available(self) -> bool:
        return bool(self.path)

    def call(self, command: str, plugin: Path, **fields: Any) -> dict[str, Any]:
        if not self.path:
            raise HostError("HOST_UNAVAILABLE", "vst3host is not built (native/vst3host)")
        request = {"command": command, "plugin": str(plugin), "timeout_s": self.timeout, **fields}
        res = run_worker("vst3host", [self.path, "--timeout", str(self.timeout)], timeout=self.timeout + 5, log_dir=self.log_dir,
                         stdin_text=json.dumps(request), parse_json_stdout=True)
        if res.timed_out:
            raise HostError("HOST_TIMEOUT", f"vst3host {command} exceeded {self.timeout} s", res)
        body = res.stdout_json if isinstance(res.stdout_json, dict) else None
        if res.exit_code != 0 or body is None or not body.get("ok"):
            code = (body or {}).get("error") or res.error_code or EXIT_CODES.get(res.exit_code or -1, "WORKER_FAILED")
            detail = (body or {}).get("detail") or _tail(res.stderr_path) or f"exit {res.exit_code}"
            raise HostError(code, f"vst3host {command}: {detail}", res)
        body["_worker"] = res.as_dict()
        return body


def _tail(path: str | None, n: int = 400) -> str:
    try:
        return Path(path or "").read_text(encoding="utf-8", errors="replace")[-n:].strip()
    except OSError:
        return ""
