"""BUILD_COMPLETE stage — the BUILD rail entry (EXECUTE 4.3, SPEC §10).

Configures and builds ``04_reconstruction`` with CMake in an isolated worker (sanitized env,
watchdog, stdout/stderr captured under logs/<job>/), then runs pluginval at strictness ≥ 5 on
the produced VST3 when pluginval is installed. Nothing is faked: a missing CMake, compiler,
JUCE or pluginval is reported as SKIPPED / NOT_RUN with setup instructions.

Outputs
  06_validation/build_report.json      artifactbench.build_report
  06_validation/pluginval.json         artifactbench.pluginval_report
  04_reconstruction/build/<bundle>.vst3  the rebuilt plugin (git-ignored); binary also in the object store

Options: build_kind (SURROGATE|FIDELITY), juce_dir, cmake_generator, build_timeout_s,
         pluginval_strictness (default 5), skip_pluginval
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from ab_engine import TOOL, api
from ab_engine import tools as tools_mod
from ab_engine.contracts import write_json
from ab_engine.jobs import runner
from ab_engine.jobs.runner import BlockedDependency, StageContext, StageFailed, StageImpl, StageSkipped
from ab_engine.workers.run import DEFAULT_ENV_ALLOWLIST, run_worker
from ab_engine.workspace import Workspace

STAGE_VERSION = 1
BUILD_ENV = DEFAULT_ENV_ALLOWLIST + ("INCLUDE", "LIB", "LIBPATH", "CC", "CXX", "CMAKE_PREFIX_PATH", "CMAKE_BUILD_PARALLEL_LEVEL", "PKG_CONFIG_PATH",
                                     "VCToolsInstallDir", "VCToolsRedistDir", "WindowsSdkDir", "WindowsSDKVersion", "UniversalCRTSdkDir", "UCRTVersion", "VSCMD_VER")


def _tail(path: str | None, n: int = 3000) -> str:
    try:
        return Path(path or "").read_text(encoding="utf-8", errors="replace")[-n:]
    except OSError:
        return ""


def _errors(text: str, limit: int = 12) -> list[str]:
    out = []
    for line in text.splitlines():
        low = line.lower()
        if ("error" in low and ("error:" in low or "error c" in low or "error lnk" in low or "cmake error" in low)) or "fatal error" in low:
            out.append(line.strip()[:400])
            if len(out) >= limit:
                break
    return out


def find_bundle(build_dir: Path) -> Path | None:
    cands = [p for p in build_dir.rglob("*.vst3") if p.is_dir() and (p / "Contents").is_dir()]
    if not cands:
        cands = [p for p in build_dir.rglob("*.vst3") if p.is_file()]
    return sorted(cands, key=lambda p: len(str(p)))[0] if cands else None


def bundle_binary(bundle: Path) -> Path | None:
    if bundle.is_file():
        return bundle
    for p in bundle.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".vst3", ".so", ".dll", ".dylib") and "Contents" in p.parts:
            return p
    return None


def build_project(ws: Workspace, log_dir: Path, rec: Path, build_dir: Path, *, juce_dir: Path, build_kind: str, generator: str | None,
                  timeout: float, jobs: int) -> dict[str, Any]:
    cmake = tools_mod.find_cmake()
    if not cmake.path:
        raise BlockedDependency("CMake not on PATH: install CMake ≥ 3.22 (winget install Kitware.CMake) — the build stage cannot run without it")
    cfg = [cmake.path, "-S", str(rec), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release", f"-DJUCE_DIR={juce_dir}", f"-DAB_BUILD_KIND={build_kind}"]
    if generator:
        cfg += ["-G", generator]
    elif sys.platform != "win32" and shutil.which("ninja"):
        cfg += ["-G", "Ninja"]
    build_dir.mkdir(parents=True, exist_ok=True)
    r1 = run_worker("cmake-configure", cfg, timeout=min(timeout, 900.0), log_dir=log_dir, env_allowlist=BUILD_ENV, cwd=build_dir, keep_cwd=True)
    report: dict[str, Any] = {"build_kind": build_kind, "juce_dir": str(juce_dir), "generator": generator or ("Ninja" if "-G" in cfg else "default"),
                              "configure": {"ok": r1.ok, "exit_code": r1.exit_code, "elapsed_ms": r1.elapsed_ms, "timed_out": r1.timed_out,
                                            "errors": _errors(_tail(r1.stderr_path, 20000) + _tail(r1.stdout_path, 20000)), "log": r1.stderr_path}}
    if not r1.ok:
        report["status"] = "CONFIGURE_FAILED"
        return report
    r2 = run_worker("cmake-build", [cmake.path, "--build", str(build_dir), "--config", "Release", "--parallel", str(jobs)], timeout=timeout, log_dir=log_dir,
                    env_allowlist=BUILD_ENV, cwd=build_dir, keep_cwd=True)
    text = _tail(r2.stderr_path, 60000) + _tail(r2.stdout_path, 60000)
    report["build"] = {"ok": r2.ok, "exit_code": r2.exit_code, "elapsed_ms": r2.elapsed_ms, "timed_out": r2.timed_out, "errors": _errors(text),
                       "warnings": sum(1 for line in text.splitlines() if "warning" in line.lower()), "log": r2.stderr_path}
    bundle = find_bundle(build_dir) if r2.ok else None
    report["status"] = "BUILT" if (r2.ok and bundle) else ("BUILD_TIMEOUT" if r2.timed_out else "BUILD_FAILED")
    report["bundle"] = str(bundle) if bundle else None
    return report


def run_pluginval(ws: Workspace, log_dir: Path, bundle: Path, *, strictness: int, timeout: float) -> dict[str, Any]:
    pv = tools_mod.find_pluginval(ws)
    if not pv.path:
        return {"status": "NOT_RUN", "reason": "pluginval not installed: Settings → Tools → install (pinned in tools/manifest.json) or put pluginval on PATH", "strictness": strictness}
    out_dir = log_dir / "pluginval"
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [pv.path, "--strictness-level", str(max(5, strictness)), "--skip-gui-tests", "--timeout-ms", str(int(timeout * 1000)), "--output-dir", str(out_dir),
            "--validate", str(bundle)]
    r = run_worker("pluginval", argv, timeout=timeout + 30, log_dir=log_dir, env_allowlist=BUILD_ENV)
    text = _tail(r.stdout_path, 40000) + _tail(r.stderr_path, 10000)
    failed = [line.strip()[:300] for line in text.splitlines() if line.strip().startswith("!!! Test") or "FAILED" in line]
    return {"status": "PASSED" if r.ok else ("TIMEOUT" if r.timed_out else "FAILED"), "exit_code": r.exit_code, "elapsed_ms": r.elapsed_ms,
            "strictness": max(5, strictness), "version": pv.version, "failures": failed[:20], "log": r.stdout_path,
            "tests_run": sum(1 for line in text.splitlines() if line.strip().startswith("Starting test")), "gui_tests": "skipped (headless worker)"}


def stage_build(ctx: StageContext) -> None:
    rec = ctx.project_dir / "04_reconstruction"
    if not (rec / "CMakeLists.txt").is_file() or not (rec / "Source" / "Active" / "PluginProcessor.cpp").is_file():
        raise StageSkipped("04_reconstruction has no Active sources yet (RECONSTRUCTION_COMPLETE did not run)")
    juce = tools_mod.find_juce(ctx.ws, ctx.options.get("juce_dir"))
    if not juce.path:
        raise BlockedDependency("JUCE not found: set the juce_dir option / AB_JUCE_DIR, or clone JUCE 8.0.9 into <workspace>/tools/JUCE")
    compiler = tools_mod.find_msvc()
    if not compiler.path:
        raise BlockedDependency("no C++ compiler: install Visual Studio Build Tools (C++ workload) — see scripts/setup-windows.ps1")
    ctx.tool_versions.update({"cmake": tools_mod.find_cmake().version or "cmake", "juce": juce.version or "juce", "compiler": (compiler.version or compiler.name)[:60]})
    kind = str(ctx.options.get("build_kind", "SURROGATE")).upper()
    build_dir = ctx.ws.tmp / f"build-{ctx.job.job_id}"
    log_dir = ctx.ws.logs / ctx.job.job_id
    ctx.progress(f"cmake configure + build ({kind})", juce=juce.path)
    report = build_project(ctx.ws, log_dir, rec, build_dir, juce_dir=Path(juce.path), build_kind=kind, generator=ctx.options.get("cmake_generator"),
                           timeout=float(ctx.options.get("build_timeout_s", 3600)), jobs=int(ctx.options.get("build_jobs", max(1, (os.cpu_count() or 2) - 1))))
    val = ctx.project_dir / "06_validation"
    val.mkdir(parents=True, exist_ok=True)
    installed = None
    if report.get("bundle"):
        bundle = Path(report["bundle"])
        dest = rec / "build" / bundle.name
        if dest.exists():
            shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle, dest) if bundle.is_dir() else shutil.copyfile(bundle, dest)
        installed = dest
        binary = bundle_binary(dest)
        if binary:
            sha, size = ctx.store.put_file(binary)
            report["binary"] = {"path": f"04_reconstruction/build/{binary.relative_to(rec / 'build').as_posix()}", "sha256": sha, "size": size}
        report["installed"] = f"04_reconstruction/build/{dest.name}"
        ctx.output(report["installed"])
    write_json(val / "build_report.json", "artifactbench.build_report", report)
    ctx.output("06_validation/build_report.json")
    if report["status"] != "BUILT":
        errs = (report.get("build") or report.get("configure") or {}).get("errors", [])
        raise StageFailed("BUILD_FAILED", f"{report['status']}: " + ("; ".join(errs[:3]) or "see build log"))
    if ctx.options.get("skip_pluginval"):
        pv = {"status": "NOT_RUN", "reason": "skip_pluginval option set"}
    else:
        ctx.progress("pluginval")
        pv = run_pluginval(ctx.ws, log_dir, installed, strictness=int(ctx.options.get("pluginval_strictness", 5)), timeout=float(ctx.options.get("pluginval_timeout_s", 600)))
    write_json(val / "pluginval.json", "artifactbench.pluginval_report", pv)
    ctx.output("06_validation/pluginval.json")
    if pv["status"] == "NOT_RUN":
        ctx.warn("PLUGINVAL_NOT_RUN", pv.get("reason", ""))
    elif pv["status"] != "PASSED":
        ctx.warn("PLUGINVAL_FAILED", "; ".join(pv.get("failures", [])[:3]) or pv["status"])
    ctx.metrics.update({"status": report["status"], "build_kind": kind, "configure_ms": report["configure"]["elapsed_ms"], "build_ms": report.get("build", {}).get("elapsed_ms"),
                        "warnings": report.get("build", {}).get("warnings"), "pluginval": pv["status"], "bundle": report.get("installed")})
    ctx.completeness = "NOT_APPLICABLE"


runner.register_stage(StageImpl("BUILD_COMPLETE", version=STAGE_VERSION, run=stage_build, tool_version=TOOL,
                                config_keys=("build_kind", "juce_dir", "cmake_generator", "pluginval_strictness", "skip_pluginval"), contract=runner.CONTRACTS["BUILD_COMPLETE"]))


def h_build(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    rec = Path(str(params["project_dir"])) / "04_reconstruction"
    juce = tools_mod.find_juce(ws, params.get("juce_dir"))
    if not juce.path:
        raise api.ApiError("juce_missing", "JUCE not found (juce_dir / AB_JUCE_DIR / <workspace>/tools/JUCE)")
    build_dir = ws.tmp / ("build-" + rec.parent.name)
    return build_project(ws, ws.logs / "adhoc", rec, build_dir, juce_dir=Path(juce.path), build_kind=str(params.get("build_kind", "SURROGATE")).upper(),
                         generator=params.get("cmake_generator"), timeout=float(params.get("build_timeout_s", 3600)), jobs=int(params.get("build_jobs", 2)))


api.register("build.run", h_build)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("build", "configure + build 04_reconstruction of a project folder (no job needed)")
def _cli(p):
    p.add_argument("project_dir")
    p.add_argument("--build-kind", default="SURROGATE", choices=("SURROGATE", "FIDELITY"))
    p.add_argument("--juce-dir")

    def run(args, ws):
        r = api.dispatch("build.run", {"project_dir": args.project_dir, "build_kind": args.build_kind, "juce_dir": args.juce_dir}, ws)
        sys.stdout.write(json.dumps({"ok": r["status"] == "BUILT", "data": r}, indent=2) + "\n")
        return 0 if r["status"] == "BUILT" else 1
    p.set_defaults(func=run)


__all__ = ["stage_build", "build_project", "run_pluginval", "find_bundle"]
