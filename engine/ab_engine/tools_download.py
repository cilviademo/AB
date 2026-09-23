"""First-run tool downloader (EXECUTE 3.1, SPEC §15).

* pinned SHA-256 from ``tools/manifest.json`` — an entry without a real hash is
  refused (``PIN_ME``), never downloaded "and trusted"
* resumable (HTTP Range), verified before extraction, extracted into
  ``%LOCALAPPDATA%\\AB\\tools\\<name>``; a ``.complete`` marker with the hash
* offline mode: any network failure returns ``SKIPPED`` with a reason; stages
  that need the tool degrade to SKIPPED
* zip members are checked for traversal; nothing is executed
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from ab_engine import api
from ab_engine import tools as tools_mod
from ab_engine.workspace import Workspace


def manifest_path() -> Path | None:
    root = tools_mod.repo_root()
    if root and (root / "tools" / "manifest.json").is_file():
        return root / "tools" / "manifest.json"
    if getattr(sys, "frozen", False):
        p = Path(sys.executable).resolve().parent.parent / "tools" / "manifest.json"
        if p.is_file():
            return p
    return None


def load_manifest() -> dict[str, Any]:
    p = manifest_path()
    if p is None:
        raise api.ApiError("not_found", "tools/manifest.json not found")
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("schema") != "artifactbench.tool_manifest" or int(doc.get("schema_version", 0)) != 1:
        raise api.ApiError("contract", "unsupported tools/manifest.json schema")
    return doc


def _platform() -> str:
    return "win32" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else "linux"


def entry_for(name: str, doc: dict[str, Any]) -> dict[str, Any]:
    t = doc["tools"].get(name)
    if t is None:
        raise api.ApiError("not_found", f"no tool {name} in the manifest")
    if "platforms" in t and isinstance(t["platforms"], dict):
        p = t["platforms"].get(_platform())
        if p is None:
            raise api.ApiError("unsupported", f"{name}: no download for {_platform()}")
        return {**{k: v for k, v in t.items() if k != "platforms"}, **p}
    return t


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _download(url: str, dest: Path, expected_size: int | None, progress) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = dest.stat().st_size if dest.is_file() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "AB-tool-downloader", **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "ab" if have else "wb") as out:
        if have and resp.status != 206:
            out.seek(0); out.truncate(); have = 0
        total = expected_size or (have + int(resp.headers.get("Content-Length") or 0))
        got = have
        while True:
            block = resp.read(4 * 1024 * 1024)
            if not block:
                break
            out.write(block); got += len(block)
            progress(got, total)


def _safe_extract(archive: Path, kind: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                p = Path(info.filename)
                if p.is_absolute() or ".." in p.parts:
                    raise api.ApiError("unsafe_archive", f"{archive.name}: member {info.filename} escapes the target")
            zf.extractall(dest)
            # zip loses the executable bit; restore for known launchers
            for p in dest.rglob("*"):
                if p.is_file() and (p.suffix in ("", ".sh") and p.parent.name in ("support", "bin", "MacOS") or p.name.startswith("pluginval")):
                    p.chmod(0o755)
    else:
        with tarfile.open(archive) as tf:
            safe = []
            for m in tf.getmembers():
                p = Path(m.name)
                if p.is_absolute() or ".." in p.parts:
                    raise api.ApiError("unsafe_archive", f"{archive.name}: member {m.name} escapes the target")
                if m.issym() or m.islnk():
                    continue  # links are skipped, never followed (JDK tarballs carry a few convenience links)
                safe.append(m)
            tf.extractall(dest, members=safe)


def install(ws: Workspace, name: str, progress=lambda got, total: None) -> dict[str, Any]:
    doc = load_manifest()
    e = entry_for(name, doc)
    sha = str(e.get("sha256", ""))
    if not sha or sha == "PIN_ME" or len(sha) != 64:
        return {"tool": name, "state": "SKIPPED", "reason": f"{name}: no pinned sha256 in tools/manifest.json (owner must pin it; see BLOCKERS B-007)"}
    target = ws.tools / name
    marker = target / ".complete"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == sha:
        return {"tool": name, "state": "PRESENT", "path": str(target)}
    archive = ws.tools / "downloads" / f"{name}-{e['version']}.{ 'zip' if e['extract'] == 'zip' else 'tar.gz'}"
    try:
        if not (archive.is_file() and sha256_file(archive) == sha):
            _download(e["url"], archive, e.get("size"), progress)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return {"tool": name, "state": "SKIPPED", "reason": f"offline or blocked: {exc}"}
    actual = sha256_file(archive)
    if actual != sha:
        archive.unlink(missing_ok=True)
        return {"tool": name, "state": "FAILED", "reason": f"sha256 mismatch: manifest {sha[:12]}… got {actual[:12]}… (download discarded)"}
    if target.exists():
        shutil.rmtree(target)
    _safe_extract(archive, e["extract"], target)
    marker.write_text(sha + "\n", encoding="utf-8")
    return {"tool": name, "state": "INSTALLED", "path": str(target), "sha256": sha}


def h_tools_install(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    names = params.get("tools") or ["ghidra", "jdk", "pluginval", "juce"]
    results = []
    for n in names:
        api.progress("TOOLS", "running", f"{n}: checking")
        results.append(install(ws, n, lambda got, total, n=n: api.progress("TOOLS", "running", f"{n}: {got // 1048576} / {(total or 0) // 1048576} MB")))
    return {"results": results}


def h_tools_status(params: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    doc = load_manifest()
    out = []
    for n in doc["tools"]:
        try:
            e = entry_for(n, doc)
            pinned = str(e.get("sha256", "")) not in ("", "PIN_ME")
        except api.ApiError:
            pinned = False
        marker = ws.tools / n / ".complete"
        out.append({"tool": n, "pinned": pinned, "installed": marker.is_file(), "path": str(ws.tools / n)})
    return {"tools": out, "manifest": str(manifest_path())}


api.register("tools.install", h_tools_install)
api.register("tools.status", h_tools_status)

from ab_engine.cli import subcommand  # noqa: E402


@subcommand("tools", "manage first-run tools: ab-cli tools status | install [name ...] | hash <file>")
def _cli_tools(p):
    p.add_argument("action", choices=["status", "install", "hash"])
    p.add_argument("names", nargs="*")

    def run(args, ws):
        if args.action == "hash":
            for f in args.names:
                sys.stdout.write(f"{sha256_file(Path(f))}  {f}\n")
            return 0
        r = api.dispatch("tools.status" if args.action == "status" else "tools.install", {"tools": args.names or None}, ws)
        sys.stdout.write(json.dumps({"ok": True, "data": r}, indent=2) + "\n")
        return 0
    p.set_defaults(func=run)
