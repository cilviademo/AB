"""Structured JSONL logs, one file per job and per worker (SPEC §16).

Nothing in the engine calls ``print()``: the stdio channel belongs to the RPC.
Records are ``{"ts", "level", "op", ...fields}``; secrets are scrubbed before
they reach disk so "Copy diagnostics" can ship the file as-is.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SECRET_RX = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[=:]\s*\S+|"
    r"\b(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"
)


def scrub(text: str) -> str:
    return _SECRET_RX.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=<redacted>"
                          if "=" in m.group(0) or ":" in m.group(0) else "<redacted>", text)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return scrub(repr(value))


class JobLog:
    """Append-only structured log. Never raises: it is a record, not the work."""

    def __init__(self, path: Path | None, *, echo_stderr: bool = False) -> None:
        self.path = path
        self._echo = echo_stderr
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def op(self, name: str, level: str = "info", **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(), "level": level, "op": name,
                  **{k: _jsonable(v) for k, v in fields.items()}}
        line = json.dumps(record)
        if self.path is not None:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass
        if self._echo:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()

    def info(self, message: str, **fields: Any) -> None:
        self.op("INFO", message=message, **fields)

    def warn(self, message: str, **fields: Any) -> None:
        self.op("WARN", level="warn", message=message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self.op("ERROR", level="error", message=message, **fields)
