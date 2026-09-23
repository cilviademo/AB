"""Method table shared by the stdio RPC server and ``ab-cli``.

Every method is ``handler(params: dict, ws: Workspace) -> dict``. Handlers never
write to stdout themselves; they call :func:`emit` for progress lines and
return the result payload. The server wraps results in
``{"id", "ok", "data"}`` envelopes; the CLI prints them.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from ab_engine import __version__, doctor
from ab_engine.workspace import Workspace

Handler = Callable[[dict[str, Any], Workspace], dict[str, Any]]


class ApiError(Exception):
    """A failure the UI can act on: ``code`` is stable, ``detail`` is human."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _stdout_sink(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


_sink: Callable[[dict[str, Any]], None] = _stdout_sink


@contextmanager
def sink(target: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    global _sink
    previous = _sink
    _sink = target
    try:
        yield
    finally:
        _sink = previous


def emit(payload: dict[str, Any]) -> None:
    _sink(payload)


def progress(stage: str, status: str, detail: str = "", **extra: Any) -> None:
    emit({"event": "progress", "stage": stage, "status": status, "detail": detail, **extra})


# --------------------------------------------------------------------------- #
# Handlers (1.1). Later phases register theirs via ``register``.
# --------------------------------------------------------------------------- #

def h_ping(params: dict, ws: Workspace) -> dict:
    return {"version": __version__}


def h_doctor(params: dict, ws: Workspace) -> dict:
    result = doctor.run(ws)
    result["report"] = doctor.report(result)
    return result


def h_environment(params: dict, ws: Workspace) -> dict:
    import platform  # noqa: PLC0415

    from ab_engine import tools as tools_mod  # noqa: PLC0415

    return {
        "version": __version__,
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "home": str(ws.home),
        "state": str(ws.state),
        "tools": [t.__dict__ | {"present": t.present} for t in tools_mod.all_tools(ws)],
    }


def h_settings_get(params: dict, ws: Workspace) -> dict:
    return ws.load_settings()


def h_settings_set(params: dict, ws: Workspace) -> dict:
    patch = params.get("settings")
    if not isinstance(patch, dict):
        raise ApiError("bad_request", "settings must be an object")
    return ws.save_settings(patch)


HANDLERS: dict[str, Handler] = {
    "ping": h_ping,
    "doctor": h_doctor,
    "environment": h_environment,
    "settings.get": h_settings_get,
    "settings.set": h_settings_set,
}


def register(name: str, handler: Handler) -> None:
    HANDLERS[name] = handler


def dispatch(method: str, params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    handler = HANDLERS.get(method)
    if handler is None:
        raise ApiError("unknown_method", f"no such method: {method}")
    return handler(params, ws)


def _load_stage_modules() -> None:
    """Import stage packages so they register their methods. Missing ones are fine."""
    import importlib  # noqa: PLC0415

    for mod in ("ab_engine.jobs.api", "ab_engine.ingest.api", "ab_engine.static.api", "ab_engine.static.baseline",
                "ab_engine.bundle.api",
                "ab_engine.bundle.api", "ab_engine.groundtruth.api", "ab_engine.runtime.api",
                "ab_engine.fingerprint.api", "ab_engine.lineage.api", "ab_engine.behavior.api",
                "ab_engine.reconstruct.api"):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as exc:
            if exc.name and not exc.name.startswith("ab_engine"):
                raise
