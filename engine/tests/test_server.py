import io
import json

from ab_engine import __version__
from ab_engine.server import Session


def _run(lines: list[str], ws) -> list[dict]:
    out = io.StringIO()
    Session(io.StringIO("\n".join(lines) + "\n"), out, ws).serve()
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_ping_and_shutdown(ws):
    replies = _run(['{"id": 1, "method": "ping"}', '{"id": 2, "method": "shutdown"}', '{"id": 3, "method": "ping"}'], ws)
    assert replies[0] == {"id": 1, "ok": True, "data": {"version": __version__}}
    assert replies[1] == {"id": 2, "ok": True, "data": {}}
    assert len(replies) == 2  # nothing after shutdown


def test_malformed_and_unknown_never_kill_the_loop(ws):
    replies = _run(["not json", "[1,2]", '{"id": 5, "method": "nope"}', '{"id": 6, "method": "ping"}'], ws)
    assert replies[0]["error"] == "bad_request"
    assert replies[1]["error"] == "bad_request"
    assert replies[2] == {"id": 5, "ok": False, "error": "unknown_method", "detail": "no such method: nope"}
    assert replies[3]["ok"] is True


def test_settings_round_trip(ws):
    replies = _run(['{"id": 1, "method": "settings.set", "params": {"settings": {"a": 1}}}',
                    '{"id": 2, "method": "settings.get"}'], ws)
    assert replies[1]["data"] == {"a": 1}


def test_doctor_runs_and_reports(ws):
    replies = _run(['{"id": 1, "method": "doctor"}'], ws)
    data = replies[0]["data"]
    names = {r["name"] for r in data["rows"]}
    assert {"engine", "disk", "sandbox", "tool:node", "tool:vst3host", "tool:ghidra"} <= names
    assert all(r["verdict"] in ("PASS", "WARNING", "UNAVAILABLE", "FAIL") for r in data["rows"])
    assert "AB doctor" in data["report"]
