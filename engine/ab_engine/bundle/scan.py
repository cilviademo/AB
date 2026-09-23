"""Export scanners (EXECUTE 1.5 gate, SPEC §14 GIT_READY, §15).

* Windows-invalid paths: reserved characters, reserved device names, trailing
  dot/space, over-long paths, case-collisions, non-portable characters.
* Secrets: API keys/tokens, private keys, credentials in URLs, and absolute
  user paths (``C:\\Users\\<name>``, ``/home/<name>``, ``/Users/<name>``) that
  would leak the machine into the bundle.

Both walk the exported tree; text files are scanned by content, binaries by
name only. Findings are rows with file, line and a redacted excerpt.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
INVALID_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
MAX_PATH = 240  # leave room for a checkout prefix under the 260 default

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b")),
    ("generic_assignment", re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+=]{12,}")),
    ("url_credentials", re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]+@")),
    ("juce_serial_literal", re.compile(r"(?i)\b(serial|licen[cs]e)[_-]?(key|number)\b\s*[:=]\s*['\"][A-Z0-9-]{12,}['\"]")),
]
USER_PATH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("windows_user_path", re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s\"'<>|]+")),
    ("unix_home_path", re.compile(r"(?<![\w/])/(?:home|Users)/[^/\s\"'<>|]+")),
]
TEXT_EXT = {".json", ".md", ".txt", ".cpp", ".h", ".hpp", ".cmake", ".xml", ".yml", ".yaml", ".toml", ".ini", ".cfg",
            ".py", ".ts", ".js", ".ps1", ".sh", ".gitignore", ".csv", ".log", ".svg", ".html"}
#: Evidence paths are recorded on purpose: build_path_evidence.json and the raw string dump
#: *contain* the original developer's paths — that is the evidence. They are not the bundle leaking ours.
EVIDENCE_EXEMPT = ("01_evidence/paths/", "01_evidence/strings/", "01_evidence/binary/")


def scan_paths(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen_lower: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        for part in rel.split("/"):
            stem = part.split(".")[0].upper()
            if INVALID_CHARS.search(part):
                findings.append({"kind": "invalid_char", "path": rel, "detail": f"segment {part!r} has a Windows-reserved character"})
            elif stem in RESERVED_NAMES:
                findings.append({"kind": "reserved_name", "path": rel, "detail": f"segment {part!r} is a reserved device name"})
            elif part != part.rstrip(". "):
                findings.append({"kind": "trailing_dot_space", "path": rel, "detail": f"segment {part!r} ends with a dot or space"})
            elif any(ord(c) > 0x7e for c in part):
                findings.append({"kind": "non_ascii", "path": rel, "detail": f"segment {part!r} is not portable ASCII"})
        if len(rel) > MAX_PATH:
            findings.append({"kind": "too_long", "path": rel, "detail": f"{len(rel)} characters (> {MAX_PATH})"})
        low = rel.lower()
        if low in seen_lower and seen_lower[low] != rel:
            findings.append({"kind": "case_collision", "path": rel, "detail": f"collides with {seen_lower[low]} on a case-insensitive filesystem"})
        seen_lower.setdefault(low, rel)
    return findings


def _redact(s: str) -> str:
    return s[:6] + "…" + s[-3:] if len(s) > 12 else "…"


def scan_secrets(root: Path, *, max_bytes: int = 8 * 1024 * 1024) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if p.suffix.lower() not in TEXT_EXT and p.name not in ("CMakeLists.txt", ".gitignore"):
            continue
        if p.stat().st_size > max_bytes:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        exempt = rel.startswith(EVIDENCE_EXEMPT)
        for lineno, line in enumerate(text.splitlines(), 1):
            for kind, rx in SECRET_PATTERNS:
                m = rx.search(line)
                if m:
                    findings.append({"kind": kind, "path": rel, "line": lineno, "excerpt": _redact(m.group(0))})
            if not exempt:
                for kind, rx in USER_PATH_PATTERNS:
                    m = rx.search(line)
                    if m:
                        findings.append({"kind": kind, "path": rel, "line": lineno, "excerpt": _redact(m.group(0))})
    return findings
