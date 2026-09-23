"""Where external tools live and whether they are present (SPEC §2, §3.1).

Detected, never required: every stage that needs a missing tool degrades to
``SKIPPED`` with a reason. Downloaded tools are verified against
``tools/manifest.json`` pinned SHA-256 (Phase 3.1); this module only *finds*.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ab_engine.workspace import Workspace


@dataclass(frozen=True)
class Tool:
    name: str
    path: str | None
    version: str | None
    detail: str

    @property
    def present(self) -> bool:
        return self.path is not None


def _version(argv: list[str], timeout: float = 8.0) -> str | None:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        text = [ln for ln in (out.stdout or out.stderr or "").strip().splitlines()
                if ln.strip() and not ln.startswith("Picked up ")]
        return text[0][:120] if text else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def repo_root() -> Path | None:
    """The source checkout, when running from one (development only)."""
    for start in (Path(__file__).resolve(), Path.cwd()):
        for d in [start, *start.parents]:
            if (d / "docs" / "SPEC.md").is_file() and (d / "engine").is_dir():
                return d
    return None


def bundled_bin_dir() -> Path | None:
    """``resources/bin`` beside a packaged engine (vst3host.exe ships there)."""
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().parent.parent / "bin"
        if candidate.is_dir():
            return candidate
    override = os.environ.get("AB_BIN")
    return Path(override) if override and Path(override).is_dir() else None


def find_vst3host(ws: Workspace) -> Tool:
    name = _exe("vst3host")
    candidates: list[Path] = []
    if os.environ.get("AB_VST3HOST"):
        candidates.append(Path(os.environ["AB_VST3HOST"]))
    if bundled_bin_dir():
        candidates.append(bundled_bin_dir() / name)  # type: ignore[operator]
    candidates.append(ws.tools / "vst3host" / name)
    root = repo_root()
    if root:
        for sub in ("build/Release", "build", "build/Debug"):
            candidates.append(root / "native" / "vst3host" / sub / name)
    for c in candidates:
        if c.is_file():
            return Tool("vst3host", str(c), _version([str(c), "--version"]), "isolated VST3 host")
    return Tool("vst3host", None, None, "not built; Phase 2 (native/vst3host)")


def find_validator(ws: Workspace) -> Tool:
    """Steinberg SDK validator built next to vst3host (AB_VST3VALIDATOR, bundled bin, dev build tree)."""
    root = repo_root()
    cands = [Path(os.environ["AB_VST3VALIDATOR"]) if os.environ.get("AB_VST3VALIDATOR") else None,
             (bundled_bin_dir() / _exe("validator")) if bundled_bin_dir() else None, ws.tools / "vst3host" / _exe("validator")]
    if root:
        for sub in ("build/bin/Release", "build/bin", "build/Release", "build"):
            cands.append(root / "native" / "vst3host" / sub / _exe("validator"))
    for c in cands:
        if c and c.is_file():
            return Tool("validator", str(c), "VST3 SDK 3.7.9 validator", "second validation source (RUNTIME stage)")
    return Tool("validator", None, None, "not built; native/vst3host/build_all.* builds it (target validator)")


def find_node(ws: Workspace) -> Tool:
    path = shutil.which("node")
    if path:
        return Tool("node", path, _version(["node", "--version"]), "runs the static engine headlessly (ab-cli/CI)")
    return Tool("node", None, None, "not on PATH; static stage runs in the GUI worker only")


def find_static_engine_cli() -> Tool:
    root = repo_root()
    candidates = []
    if root:
        candidates.append(root / "app" / "static-engine" / "dist" / "cli.mjs")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent.parent / "static-engine" / "cli.mjs")
    for c in candidates:
        if c.is_file():
            return Tool("static-engine", str(c), None, "Static Recovery v2 port (Node entry)")
    return Tool("static-engine", None, None, "not built; run `npm run build` in app/")


def find_jdk(ws: Workspace) -> Tool:
    bases = [Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else None, ws.tools / "jdk"]
    if (ws.tools / "jdk").is_dir():  # downloader layout: tools/jdk/<root_glob>/ (macOS: <root>/Contents/Home)
        for d in sorted((ws.tools / "jdk").glob("jdk-21*"), reverse=True):
            bases += [d, d / "Contents" / "Home"]
    for base in bases:
        if base and (base / "bin" / _exe("java")).is_file():
            exe = base / "bin" / _exe("java")
            return Tool("jdk", str(exe), _version([str(exe), "-version"]), "for Ghidra")
    path = shutil.which("java")
    if path:
        return Tool("jdk", path, _version(["java", "-version"]), "system Java")
    return Tool("jdk", None, None, "not installed; Phase 3 downloader (tools/manifest.json)")


def find_ghidra(ws: Workspace) -> Tool:
    roots = [ws.tools / "ghidra", ws.tools]  # downloader layout: tools/ghidra/ghidra_<ver>_PUBLIC/
    if os.environ.get("GHIDRA_INSTALL_DIR"):
        roots.insert(0, Path(os.environ["GHIDRA_INSTALL_DIR"]).parent)
    for root in roots:
        if not root.is_dir():
            continue
        for d in sorted(root.glob("ghidra_*"), reverse=True):
            headless = d / "support" / ("analyzeHeadless.bat" if sys.platform == "win32" else "analyzeHeadless")
            if headless.is_file():
                return Tool("ghidra", str(headless), d.name, "headless decompiler")
    return Tool("ghidra", None, None, "not installed; Phase 3 downloader")


def find_pluginval(ws: Workspace) -> Tool:
    for c in (ws.tools / "pluginval" / _exe("pluginval"), Path(shutil.which("pluginval") or "")):
        if c and c.is_file():
            return Tool("pluginval", str(c), _version([str(c), "--version"]), "plugin validator")
    return Tool("pluginval", None, None, "not installed; optional (Phase 4)")


def find_juce(ws: Workspace, override: str | None = None) -> Tool:
    """JUCE source tree for the build stage: option/env override, <workspace>/tools/JUCE, or the fixture's clone in a dev checkout."""
    root = repo_root()
    cands = [Path(override) if override else None, Path(os.environ["AB_JUCE_DIR"]) if os.environ.get("AB_JUCE_DIR") else None,
             ws.tools / "juce" / "JUCE", ws.tools / "juce", ws.tools / "JUCE", (root / "fixtures" / "groundtruth" / "third_party" / "JUCE") if root else None]
    for c in cands:
        if c and (c / "CMakeLists.txt").is_file():
            ver = None
            try:
                import re as _re  # noqa: PLC0415

                mm = _re.search(r"JUCE VERSION ([0-9.]+)", (c / "CMakeLists.txt").read_text(encoding="utf-8", errors="replace"))
                ver = mm.group(1) if mm else None
            except OSError:
                pass
            return Tool("juce", str(c), ver, "JUCE source tree (build stage)")
    return Tool("juce", None, None, "not found; set AB_JUCE_DIR or clone JUCE 8.0.9 to <workspace>/tools/JUCE")


def find_cmake() -> Tool:
    path = shutil.which("cmake")
    return Tool("cmake", path, _version(["cmake", "--version"]) if path else None,
                "build stage" if path else "not on PATH; build stage will SKIP")


def find_msvc() -> Tool:
    if sys.platform != "win32":
        cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        return Tool("compiler", cxx, _version([cxx, "--version"]) if cxx else None,
                    "non-Windows compiler (fixture/vst3host dev builds)" if cxx else "no C++ compiler")
    for var in ("VCINSTALLDIR", "VSINSTALLDIR"):
        if os.environ.get(var):
            return Tool("msvc", os.environ[var], None, "from environment")
    vswhere = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.is_file():
        found = _version([str(vswhere), "-latest", "-products", "*", "-requires",
                          "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"])
        if found:
            return Tool("msvc", found, None, "MSVC Build Tools")
    return Tool("msvc", None, None, "MSVC Build Tools not found; build stage will SKIP")


def all_tools(ws: Workspace) -> list[Tool]:
    return [find_node(ws), find_static_engine_cli(), find_vst3host(ws), find_jdk(ws), find_ghidra(ws),
            find_pluginval(ws), find_cmake(), find_msvc(), find_juce(ws), find_validator(ws)]
