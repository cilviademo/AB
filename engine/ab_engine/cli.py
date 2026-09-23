"""``ab-cli`` — every RPC method as a command (SPEC §2, §16).

    ab-cli doctor
    ab-cli call <method> '<json params>'
    ab-cli run --stage static <file>          (1.4)
    ab-cli diff-baseline                      (1.4)
    ab-cli export <job_id> --zip              (1.5)

Output is the JSON result envelope unless ``--text`` chooses the human report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ab_engine import __version__, api
from ab_engine.workspace import Workspace


def _ws(args: argparse.Namespace) -> Workspace:
    return Workspace.open(Path(args.workspace)) if args.workspace else Workspace.open()


def _print(result: dict, text_key: str | None, as_text: bool) -> None:
    if as_text and text_key and text_key in result:
        sys.stdout.write(str(result[text_key]) + "\n")
    else:
        sys.stdout.write(json.dumps({"ok": True, "data": result}, indent=2) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ab-cli", description="AB (Artifact Bench) engine CLI")
    p.add_argument("--version", action="version", version=f"ab-cli {__version__}")
    p.add_argument("--workspace", help="use this folder for projects and state (tests, portable mode)")
    p.add_argument("--text", action="store_true", help="human-readable report where available")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="shell, engine, disk, sandbox and tool status")
    c = sub.add_parser("call", help="invoke any RPC method")
    c.add_argument("method")
    c.add_argument("params", nargs="?", default="{}")
    sub.add_parser("methods", help="list RPC methods")

    # Stage commands register their own subparsers.
    api._load_stage_modules()
    for name, adder in _SUBCOMMANDS.items():
        adder(sub.add_parser(name, help=_HELP.get(name, "")))
    return p


_SUBCOMMANDS: dict = {}
_HELP: dict[str, str] = {}


def subcommand(name: str, help_text: str = ""):
    """Register a CLI subcommand: ``adder(parser)`` sets arguments and ``parser.set_defaults(func=...)``."""

    def deco(adder):
        _SUBCOMMANDS[name] = adder
        _HELP[name] = help_text
        return adder

    return deco


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ws = _ws(args)
    try:
        if args.command == "doctor":
            result = api.dispatch("doctor", {}, ws)
            _print(result, "report", args.text)
            return 0 if result["ok"] else 1
        if args.command == "methods":
            _print({"methods": sorted(api.HANDLERS)}, None, False)
            return 0
        if args.command == "call":
            with api.sink(lambda payload: sys.stderr.write(json.dumps(payload) + "\n")):
                result = api.dispatch(args.method, json.loads(args.params), ws)
            _print(result, None, False)
            return 0
        func = getattr(args, "func", None)
        if func is None:
            sys.stderr.write("unknown command\n")
            return 2
        with api.sink(lambda payload: sys.stderr.write(json.dumps(payload) + "\n")):
            return int(func(args, ws) or 0)
    except api.ApiError as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": exc.code, "detail": exc.detail}) + "\n")
        return 1


if __name__ == "__main__":
    # `python -m ab_engine.cli` loads this file as __main__, a second module object: subcommands registered by the API
    # modules attach to the real `ab_engine.cli`. Delegate there so both spellings see every subcommand (Windows bootstrap).
    from ab_engine.cli import main as _main  # noqa: PLC0415

    raise SystemExit(_main())
