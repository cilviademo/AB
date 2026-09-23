"""Isolated worker execution (SPEC §4, §15; EXECUTE 1.1).

The one way the engine runs anything external: ``vst3host``, Ghidra, CMake,
pluginval, Node (static engine CLI). Guarantees, per run:

* hard timeout (a watchdog kills the whole process tree)
* temporary working directory that is removed afterwards unless kept
* sanitized environment: only an allow-list of variables reaches the child,
  no tokens or keys, no network proxy variables unless explicitly allowed
* stdout and stderr captured to files (never into memory unbounded)
* exit code, timeout flag, crash state and elapsed time recorded
* on Windows the child runs inside a Job Object with kill-on-close, so an
  orphaned plugin thread dies with its worker (``vst3host`` needs this)

The engine never loads a plugin itself. This module runs *processes*.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

#: Environment variables a worker may inherit. Everything else is dropped.
DEFAULT_ENV_ALLOWLIST = (
    "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "PATHEXT", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "USERPROFILE",
    "LOCALAPPDATA", "APPDATA", "HOME", "LANG", "LC_ALL", "TZ", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "JAVA_HOME", "GHIDRA_INSTALL_DIR", "MAXMEM",
    "VST3_SDK_DIR", "CMAKE_GENERATOR", "VCINSTALLDIR", "VSINSTALLDIR", "LD_LIBRARY_PATH",
    "DISPLAY", "XDG_RUNTIME_DIR",
)

#: Stable error codes the UI shows (AB_BRIEF "Error handling").
CRASH_CODES = {
    "vst3host": "PLUGIN_CRASH",
    "ghidra": "GHIDRA_FAILED",
    "cmake": "BUILD_FAILED",
    "msbuild": "BUILD_FAILED",
    "pluginval": "VALIDATION_FAILED",
}


@dataclass
class WorkerResult:
    kind: str
    pid: int | None
    exit_code: int | None
    stdout_path: str | None
    stderr_path: str | None
    timed_out: bool
    crash_dump: str | None
    elapsed_ms: int
    peak_rss_mb: float | None = None
    error_code: str | None = None
    stdout_json: object = None

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def sanitized_env(extra: dict[str, str] | None = None, allow: tuple[str, ...] = DEFAULT_ENV_ALLOWLIST) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in {a.upper() for a in allow}}
    if extra:
        env.update(extra)
    return env


def _win_job_object():
    """Create a kill-on-close Job Object (Windows only). Returns a handle or None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                        "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        return job
    except Exception:  # noqa: BLE001 - best effort; the watchdog still kills the child
        return None


def _assign_job(job, pid: int) -> None:
    if job is None or sys.platform != "win32":
        return
    try:
        import ctypes  # noqa: PLC0415

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1F0FFF, False, pid)
        if handle:
            kernel32.AssignProcessToJobObject(job, handle)
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
        else:
            import signal  # noqa: PLC0415

            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass


def _find_crash_dump(kind: str, pid: int | None, started_at: float) -> str | None:
    """WER local dumps (SPEC §16) land under %LOCALAPPDATA%\\CrashDumps."""
    if sys.platform != "win32" or pid is None:
        return None
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    dumps = Path(local) / "CrashDumps"
    if not dumps.is_dir():
        return None
    for dmp in sorted(dumps.glob("*.dmp"), key=lambda p: p.stat().st_mtime, reverse=True):
        if dmp.stat().st_mtime >= started_at - 1 and f".{pid}." in dmp.name:
            return str(dmp)
    return None


def run_worker(
    kind: str,
    argv: list[str],
    *,
    timeout: float,
    log_dir: Path,
    stdin_text: str | None = None,
    env_extra: dict[str, str] | None = None,
    env_allowlist: tuple[str, ...] = DEFAULT_ENV_ALLOWLIST,
    cwd: Path | None = None,
    keep_cwd: bool = False,
    parse_json_stdout: bool = False,
) -> WorkerResult:
    """Run ``argv`` isolated and return a :class:`WorkerResult`. Never raises for child failure."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stdout_path = log_dir / f"{kind}-{stamp}-{os.getpid()}.stdout"
    stderr_path = log_dir / f"{kind}-{stamp}-{os.getpid()}.stderr"

    program = argv[0]
    if not (Path(program).is_file() or shutil.which(program)):
        return WorkerResult(kind, None, None, None, None, False, None, 0, None, "WORKER_NOT_FOUND")

    temp_cwd = None
    if cwd is None:
        temp_cwd = Path(tempfile.mkdtemp(prefix=f"ab-{kind}-"))
        cwd = temp_cwd

    creation = 0
    if sys.platform == "win32":
        creation = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    job = _win_job_object()
    started = time.monotonic()
    started_wall = time.time()
    timed_out = False
    pid: int | None = None
    exit_code: int | None = None
    peak_rss = None

    with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
        try:
            proc = subprocess.Popen(
                argv, cwd=str(cwd), env=sanitized_env(env_extra, env_allowlist),
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=out, stderr=err, creationflags=creation,
                start_new_session=(sys.platform != "win32"),
            )
        except OSError as exc:
            err.write(str(exc).encode())
            return WorkerResult(kind, None, None, str(stdout_path), str(stderr_path), False, None,
                                int((time.monotonic() - started) * 1000), None, "WORKER_FAILED")
        pid = proc.pid
        _assign_job(job, pid)
        try:
            proc.communicate(input=stdin_text.encode("utf-8") if stdin_text is not None else None, timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            exit_code = proc.returncode
        if sys.platform != "win32":
            try:
                import resource  # noqa: PLC0415

                peak_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0
            except Exception:  # noqa: BLE001
                peak_rss = None

    elapsed_ms = int((time.monotonic() - started) * 1000)
    crash_dump = None
    error_code: str | None = None
    if timed_out:
        error_code = "HOST_TIMEOUT" if kind == "vst3host" else "WORKER_FAILED"
    elif exit_code != 0:
        crash_dump = _find_crash_dump(kind, pid, started_wall)
        # Negative codes (signals) and Windows fault codes are crashes; documented
        # non-zero codes (vst3host 2..5) are reported as-is by the caller.
        if exit_code is None or exit_code < 0 or (exit_code & 0xC0000000) == 0xC0000000:
            error_code = CRASH_CODES.get(kind, "WORKER_FAILED")
        else:
            error_code = CRASH_CODES.get(kind, "WORKER_FAILED") if kind != "vst3host" else None

    stdout_json = None
    if parse_json_stdout and not timed_out:
        try:
            text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
            stdout_json = json.loads(text) if text else None
        except ValueError:
            stdout_json = None

    if temp_cwd is not None and not keep_cwd:
        shutil.rmtree(temp_cwd, ignore_errors=True)

    return WorkerResult(kind, pid, exit_code, str(stdout_path), str(stderr_path), timed_out,
                        crash_dump, elapsed_ms, peak_rss, error_code, stdout_json)
