"""Itanium typeinfo-name candidates from a stripped ELF/Mach-O (AB evidence, not v2).

The frozen v2 static engine keys Itanium RTTI on ``_ZTS…`` *symbol* names, which a real stripped
build no longer carries. The typeinfo *name strings* ("N4abgt10TanhShaperE") stay in .rodata as
long as RTTI is on, so they are recovered here by grammar and demangled with the same rule v2
uses (``demangleItaniumType``). Without a typeinfo object or vtable to tie them to, every row is
``CANDIDATE`` (name_status ``CANDIDATE_TYPEINFO_STRING``); the decompiler stage promotes to
VERIFIED_RTTI / VERIFIED_VTABLE when Ghidra locates the objects.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ab_engine import deps

TYPE_RX = re.compile(rb"(?<![A-Za-z0-9_])(N(?:\d+[A-Za-z_]\w*)+E|\d+[A-Za-z_]\w*)(?![A-Za-z0-9_])")


def demangle_itanium_type(s: str) -> str | None:
    """Port of v2 ``demangleItaniumType`` (nested-name grammar only; templates are left raw)."""
    i = 4 if s.startswith("_ZTS") else 0
    nested = False
    if i < len(s) and s[i] == "N":
        nested = True
        i += 1
    parts: list[str] = []
    while i < len(s):
        m = re.match(r"\d+", s[i:])
        if not m:
            break
        ln = int(m.group(0))
        i += len(m.group(0))
        part = s[i:i + ln]
        if len(part) != ln:
            return None
        parts.append(part)
        i += ln
        if not nested:
            break
    if nested and (i >= len(s) or s[i] != "E"):
        return None
    return "::".join(parts) if parts else None


def _well_formed(token: bytes) -> bool:
    """Every length prefix must consume exactly its identifier; the whole token must be consumed."""
    s = token.decode("ascii", "replace")
    nested = s.startswith("N")
    i = 1 if nested else 0
    n = 0
    while i < len(s):
        m = re.match(r"\d+", s[i:])
        if not m:
            break
        ln = int(m.group(0))
        i += len(m.group(0))
        ident = s[i:i + ln]
        if len(ident) != ln or not re.fullmatch(r"[A-Za-z_]\w*", ident):
            return False
        i += ln
        n += 1
        if not nested:
            return i == len(s) and n == 1
    return nested and i == len(s) - 1 and s[-1] == "E" and n >= 1


def scan(path: Path, *, sections: tuple[str, ...] = (".rodata", ".data.rel.ro", "__const", "__cstring")) -> list[dict[str, Any]]:
    if not deps.available("lief"):
        return []
    import lief  # noqa: PLC0415

    lief.logging.disable()
    b = lief.parse(str(path))
    if b is None:
        return []
    if isinstance(b, lief.MachO.FatBinary):
        b = b.at(0)
    fmt = str(b.format).rsplit(".", 1)[-1]
    if fmt not in ("ELF", "MACHO"):
        return []
    seen: dict[str, dict[str, Any]] = {}
    for s in b.sections:
        if s.name.rstrip("\0") not in sections:
            continue
        data = bytes(s.content)
        base = int(getattr(s, "virtual_address", 0))
        for m in TYPE_RX.finditer(data):
            tok = m.group(1)
            if len(tok) < 3 or len(tok) > 400 or not _well_formed(tok):
                continue
            # a typeinfo name string is NUL-terminated and starts at a NUL / section boundary
            st, en = m.start(1), m.end(1)
            if (st > 0 and data[st - 1] != 0) or (en < len(data) and data[en] != 0):
                continue
            name = demangle_itanium_type(tok.decode("ascii"))
            if not name or name in seen:
                continue
            if "::" not in name and len(name) < 3:
                continue  # two-letter unscoped types are overwhelmingly template noise (same floor as D-013)
            seen[name] = {"recovered_name": name, "mangled": tok.decode("ascii"), "kind": "UNCLASSIFIED",
                          "name_status": "CANDIDATE_TYPEINFO_STRING", "structure_status": "UNKNOWN", "evidence": "CANDIDATE",
                          "source": f"{s.name.rstrip(chr(0))} @ 0x{base + st:x} (Itanium typeinfo-name grammar; no symbol, no typeinfo object tied)",
                          "namespace_top": name.split("::")[0] if "::" in name else None}
    rows = list(seen.values())
    # simple ownership hint, mirroring the v2 vocabulary without inventing: framework namespaces are named as such
    for r in rows:
        top = r["namespace_top"] or r["recovered_name"]
        if top in ("juce", "std", "__gnu_cxx", "Steinberg", "__cxxabiv1", "OT", "AAT", "CFF", "hb", "boost"):
            r["kind"] = "FRAMEWORK_OR_THIRD_PARTY_CANDIDATE"
        elif top.startswith(("juce", "Steinberg")):
            r["kind"] = "FRAMEWORK_OR_THIRD_PARTY_CANDIDATE"
        else:
            r["kind"] = "PLUGIN_OWNED_CANDIDATE"
    return rows


__all__ = ["scan", "demangle_itanium_type"]
