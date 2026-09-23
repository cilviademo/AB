"""Intake classification and grouping — the rules of Static Recovery v2's
``ingest()`` / ``pluginKeyOf()`` / ``attach()`` carried over unchanged, plus
``.map`` (brief) and archives.

Nothing here executes anything found in a dropped folder (SPEC §15).
"""

from __future__ import annotations

import re
from pathlib import Path

BINARY_EXT = re.compile(r"\.(vst3|vst|component|dll|dylib)$", re.I)
BUNDLE_KEY = re.compile(r"([^\\/]+\.(vst3|vst|component|dll|dylib))(?=[\\/]|$)", re.I)
SRC_RX = re.compile(r"\.(cpp|cc|cxx|c|h|hpp|hh|mm|m|jucer|cmake|txt|json|md|xml|svg|png|jpg|ttf|otf)$", re.I)
SRC_STRICT = re.compile(r"\.(cpp|h|hpp|jucer|mm)$", re.I)
SRC_PATH_HINT = re.compile(r"(source|src|juce|include|resources|assets|cmake|\.jucer)", re.I)
PRESET_RX = re.compile(r"\.(vstpreset|fxp|fxb|aupreset|rpp|als|flp|cpr|logicx|ptx|song|bwproject|xml|json|txt)$", re.I)
PRESET_ONLY = re.compile(r"\.(vstpreset|fxp|fxb|aupreset)$", re.I)
SESSION_ONLY = re.compile(r"\.(rpp|als|flp|cpr|logicx|ptx|song|bwproject)$", re.I)
OBJ_RX = re.compile(r"\.(obj|o|ilk|pch)$", re.I)
ASSET_RX = re.compile(r"\.(png|jpg|jpeg|svg|ttf|otf|wav|aiff|aif)$", re.I)
SKIP_DIRS = re.compile(r"(^|[\\/])(node_modules|\.git|JUCE[\\/]modules|build[\\/]_deps)[\\/]", re.I)
ARCHIVE_RX = re.compile(r"\.zip$", re.I)

MIN_BINARY_SIZE = 32 * 1024
MAX_PRESET_SIZE = 200 * 1024 * 1024


def magic_kind(head: bytes) -> str | None:
    if head[:2] == b"MZ":
        return "PE"
    if head[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
        return "Mach-O"
    if head[:4] == b"\x7fELF":
        return "ELF"
    return None


def classify(path: str, size: int, head: bytes) -> tuple[str, str | None]:
    """Return ``(kind, binary_format)``; kind ∈ binary|pdb|map|obj|source|preset|session|asset|archive|other|skip."""
    if SKIP_DIRS.search(path):
        return "skip", None
    low = path.lower()
    name = low.split("/")[-1].split("\\")[-1]
    fmt = magic_kind(head)
    if name.endswith(".pdb"):
        return "pdb", None
    if name.endswith(".map"):
        return "map", None
    if fmt and size > MIN_BINARY_SIZE:
        return "binary", fmt
    if OBJ_RX.search(name):
        return "obj", None
    if ARCHIVE_RX.search(name):
        return "archive", None
    if (SRC_RX.search(name) and SRC_PATH_HINT.search(low)) or SRC_STRICT.search(name):
        return "source", None
    if PRESET_ONLY.search(name) and size < MAX_PRESET_SIZE:
        return "preset", None
    if SESSION_ONLY.search(name) and size < MAX_PRESET_SIZE:
        return "session", None
    if PRESET_RX.search(name) and size < MAX_PRESET_SIZE:
        return "preset", None
    if ASSET_RX.search(name):
        return "asset", None
    return "other", None


def bundle_key(path: str) -> str:
    """v2 ``pluginKeyOf``: the path segment ending in a plugin extension, else the file name."""
    m = BUNDLE_KEY.search(path)
    return m.group(1) if m else re.split(r"[\\/]", path)[-1]


def attaches(path: str, key: str, single_group: bool) -> bool:
    """v2 ``attach``: everything attaches when there is one plugin; else by name prefix."""
    return single_group or re.sub(r"\.[^.]+$", "", key) in path


def safe_folder(s: str) -> str:
    s = BINARY_EXT.sub("", s)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:60]
    return s or "plugin"
