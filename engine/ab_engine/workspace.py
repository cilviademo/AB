"""Where AB reads and writes on this machine.

Two roots, decided by the desktop shell and handed down through the
environment so exactly one place knows the policy (mirrors Prosody):

* ``AB_HOME``  — the user's recovery projects (``Documents\\AB`` or, when
  Documents is cloud-synced, ``<profile>\\AB``)
* ``AB_STATE`` — machine-local state: ``jobs.db``, ``objects/``, ``knowledge/``,
  ``logs/``, ``tools/`` (``%LOCALAPPDATA%\\AB``)

Portable mode collapses both into ``Data\\`` beside the executable.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "AB"
ENV_HOME = "AB_HOME"
ENV_STATE = "AB_STATE"


def _home() -> Path:
    profile = os.environ.get("USERPROFILE") if sys.platform == "win32" else None
    return Path(profile) if profile else Path.home()


def documents_dir() -> Path:
    override = os.environ.get("AB_DOCUMENTS")
    if override:
        return Path(override)
    if sys.platform == "win32":
        try:
            import winreg  # noqa: PLC0415

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "Personal")
            expanded = Path(os.path.expandvars(str(value)))
            if expanded.is_dir():
                return expanded
        except OSError:
            pass
    return _home() / "Documents"


def is_cloud_synced(path: Path) -> bool:
    """A sync client locks files it uploads; recovery bundles are large."""
    lower = str(path).lower()
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.environ.get(var, "")
        if root and lower.startswith(root.lower()):
            return True
    return any(p.startswith("onedrive") or p == "dropbox" for p in lower.replace("\\", "/").split("/"))


def local_app_data() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) if local else _home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share")


def default_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override)
    documents = documents_dir()
    return (_home() / APP_NAME) if is_cloud_synced(documents) else (documents / APP_NAME)


def default_state() -> Path:
    override = os.environ.get(ENV_STATE)
    if override:
        return Path(override)
    return local_app_data() / APP_NAME


@dataclass(frozen=True)
class Workspace:
    """The application's folders. Created on demand, never scattered."""

    home: Path
    state: Path

    @classmethod
    def open(cls, home: Path | None = None, state: Path | None = None) -> Workspace:
        if home is not None and state is None:
            resolved_home, resolved_state = Path(home), Path(home)
        else:
            resolved_home = Path(home) if home else default_home()
            resolved_state = Path(state) if state else default_state()
        ws = cls(resolved_home, resolved_state)
        ws.ensure()
        return ws

    # -- folders ---------------------------------------------------------- #
    @property
    def projects(self) -> Path:
        return self.home / "Projects"

    @property
    def exports(self) -> Path:
        return self.home / "Exports"

    @property
    def db_path(self) -> Path:
        return self.state / "jobs.db"

    @property
    def objects(self) -> Path:
        return self.state / "objects"

    @property
    def knowledge(self) -> Path:
        return self.state / "knowledge"

    @property
    def logs(self) -> Path:
        return self.state / "logs"

    @property
    def tools(self) -> Path:
        return self.state / "tools"

    @property
    def cache(self) -> Path:
        return self.state / "cache"

    @property
    def tmp(self) -> Path:
        return self.state / "tmp"

    @property
    def settings_path(self) -> Path:
        return self.state / "settings.json"

    def ensure(self) -> None:
        for d in (self.projects, self.exports, self.objects, self.knowledge, self.logs,
                  self.tools, self.cache, self.tmp):
            d.mkdir(parents=True, exist_ok=True)

    # -- settings --------------------------------------------------------- #
    def load_settings(self) -> dict:
        import json  # noqa: PLC0415

        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self, patch: dict) -> dict:
        import json  # noqa: PLC0415

        merged = {**self.load_settings(), **patch}
        self.settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        return merged
