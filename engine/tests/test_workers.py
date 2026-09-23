import sys

from ab_engine.workers.run import DEFAULT_ENV_ALLOWLIST, run_worker, sanitized_env


def test_env_is_sanitized(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = sanitized_env({"AB_X": "1"})
    assert "GITHUB_TOKEN" not in env
    assert env["PATH"] == "/usr/bin" and env["AB_X"] == "1"
    assert "PATH" in DEFAULT_ENV_ALLOWLIST


def test_worker_captures_exit_and_output(ws):
    r = run_worker("probe", [sys.executable, "-c", "import sys; print('{\"a\":1}'); sys.stderr.write('warn'); sys.exit(3)"],
                   timeout=20, log_dir=ws.logs, parse_json_stdout=True)
    assert r.exit_code == 3 and r.timed_out is False and r.stdout_json == {"a": 1}
    assert open(r.stderr_path).read() == "warn"
    assert r.error_code == "WORKER_FAILED"


def test_worker_timeout_kills_tree(ws):
    r = run_worker("vst3host", [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.5, log_dir=ws.logs)
    assert r.timed_out is True and r.error_code == "HOST_TIMEOUT" and r.elapsed_ms < 10000


def test_missing_program(ws):
    r = run_worker("ghidra", ["definitely-not-a-program-xyz"], timeout=5, log_dir=ws.logs)
    assert r.error_code == "WORKER_NOT_FOUND" and r.pid is None


def test_stdin_is_delivered(ws):
    r = run_worker("probe", [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
                   timeout=20, log_dir=ws.logs, stdin_text="hello")
    assert open(r.stdout_path).read().strip() == "HELLO"
