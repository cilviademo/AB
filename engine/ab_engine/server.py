"""Line-delimited JSON RPC over stdio (EXECUTE 1.1).

    -> {"id": 1, "method": "ping"}
    <- {"id": 1, "ok": true, "data": {"version": "0.1.0"}}
    -> {"id": 7, "method": "job.run", "params": {...}}
    <- {"id": 7, "event": "progress", "stage": "STATIC", "status": "running", "detail": "..."}
    <- {"id": 7, "ok": true, "data": {...}}

Why stdio and not localhost HTTP: no port to collide, no firewall prompt on
first launch, and the process dies with its parent. The loop never raises: a
malformed line, an unknown method or a handler exception all produce a
response envelope, because a silent engine looks identical to a hung one.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, TextIO

from ab_engine import __version__, api
from ab_engine.workspace import Workspace

PING = "ping"
SHUTDOWN = "shutdown"


class Session:
    def __init__(self, stdin: TextIO | None = None, stdout: TextIO | None = None,
                 workspace: Workspace | None = None) -> None:
        self._in = stdin if stdin is not None else sys.stdin
        self._out = stdout if stdout is not None else sys.stdout
        self._workspace = workspace
        self._current_id: Any = None

    def write(self, payload: dict[str, Any]) -> None:
        line = dict(payload)
        if self._current_id is not None and "id" not in line:
            line["id"] = self._current_id
        self._out.write(json.dumps(line) + "\n")
        self._out.flush()

    def workspace(self, params: dict[str, Any]) -> Workspace:
        override = params.get("workspace")
        if override:
            return Workspace.open(Path(str(override)))
        if self._workspace is None:
            self._workspace = Workspace.open()
        return self._workspace

    def handle(self, line: str) -> bool:
        text = line.strip()
        if not text:
            return True
        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            self.write({"ok": False, "error": "bad_request", "detail": str(exc)})
            return True
        if not isinstance(request, dict):
            self.write({"ok": False, "error": "bad_request", "detail": "a request must be a JSON object"})
            return True

        self._current_id = request.get("id")
        method = str(request.get("method", ""))
        params = request.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        try:
            if method == PING:
                self.write({"ok": True, "data": {"version": __version__}})
                return True
            if method == SHUTDOWN:
                self.write({"ok": True, "data": {}})
                return False
            if not method:
                self.write({"ok": False, "error": "bad_request", "detail": "no method given"})
                return True
            with api.sink(self.write):
                data = api.dispatch(method, params, self.workspace(params))
            self.write({"ok": True, "data": data})
        except api.ApiError as exc:
            self.write({"ok": False, "error": exc.code, "detail": exc.detail})
        except Exception as exc:  # noqa: BLE001 - the loop must never die
            self.write({"ok": False, "error": "internal", "detail": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc(limit=6)})
        finally:
            self._current_id = None
        return True

    def serve(self) -> int:
        api._load_stage_modules()
        for line in self._in:
            if not self.handle(line):
                break
        return 0


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None,
          workspace: Workspace | None = None) -> int:
    return Session(stdin, stdout, workspace).serve()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] in ("--version", "-V"):
        sys.stdout.write(__version__ + "\n")
        return 0
    if argv and not argv[0].startswith("-"):
        # One-shot diagnostic mode:  ab-engine doctor '{}'
        from ab_engine.cli import main as cli_main  # noqa: PLC0415

        return cli_main(argv)
    return serve()
