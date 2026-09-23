"""Binary inventory with LIEF (EXECUTE_ADDENDUM_A §A1).

Two outputs from one parse:

* ``v2_pe_dict(path)`` — exactly the ``pe`` object the frozen Static Recovery v2 ``parsePE``
  writes (machine, timestamp, linker, sectionNames, rdata, exports ≤ 64, format), so the
  mapping test can prove LIEF reads the same facts. v2 stays the writer of ``01_evidence/binary/
  <name>.json`` (DECISIONS D-021); this is the cross-check and the base for everything new.
* ``inventory(path)`` — ``artifactbench.binary_inventory`` v1: format, arch, entry, sections,
  imports, exports (all), symbol counts, debug link (PDB / build-id / UUID), rich-header
  compiler hints, dependencies, whether symbols were stripped.

Every value is read from the file; nothing is guessed. A missing LIEF leaves the inventory
``UNAVAILABLE`` with the install hint, never a fabricated inventory.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ab_engine import deps

MACHINE_V2 = {"I386": "x86", "AMD64": "x64", "ARM64": "ARM64"}


def _lief():
    if not deps.available("lief"):
        return None
    import lief  # noqa: PLC0415

    lief.logging.disable()
    return lief


def _enum_name(v: Any) -> str:
    s = str(v)
    return s.rsplit(".", 1)[-1] if "." in s else s


def _format_from_exports(names: list[str]) -> str:
    if "GetPluginFactory" in names:
        return "VST3"
    if "VSTPluginMain" in names:
        return "VST2"
    if "clap_entry" in names:
        return "CLAP"
    return "unknown"


def _v2_exports_raw(data: bytes) -> list[str]:
    """v2 ``parsePE``'s export walk on raw bytes: export directory → name-pointer table, first 64, table order.
    LIEF refuses some hand-made or odd PE layouts that v2 still reads; the v2 definition is the raw walk."""
    import struct  # noqa: PLC0415

    try:
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if struct.unpack_from("<I", data, pe)[0] != 0x4550:
            return []
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        pe32p = struct.unpack_from("<H", data, opt)[0] == 0x20B
        dd = opt + (112 if pe32p else 96)
        exp_rva = struct.unpack_from("<I", data, dd)[0]
        secs = []
        so = opt + opt_size
        for i in range(nsec):
            s0 = so + i * 40
            vsz, va, rsz, raw = struct.unpack_from("<IIII", data, s0 + 8)
            secs.append((va, vsz, raw, rsz))

        def rva2off(rva: int) -> int:
            for va, vsz, raw, rsz in secs:
                if va <= rva < va + max(vsz, rsz):
                    return rva - va + raw
            return -1

        names: list[str] = []
        if exp_rva:
            e = rva2off(exp_rva)
            if e > 0:
                n_names = struct.unpack_from("<I", data, e + 24)[0]
                no = rva2off(struct.unpack_from("<I", data, e + 32)[0])
                for i in range(min(n_names, 64)):
                    so_ = rva2off(struct.unpack_from("<I", data, no + i * 4)[0])
                    if so_ < 0:
                        continue
                    j = so_
                    out = bytearray()
                    while j < so_ + 128 and j < len(data) and data[j]:
                        out.append(data[j])
                        j += 1
                    names.append(out.decode("latin-1"))
        return names
    except (struct.error, IndexError):
        return []


def v2_pe_dict(path: Path) -> dict[str, Any]:
    """The frozen v2 ``parsePE`` result: machine/timestamp/linker/sections from LIEF, exports by the
    v2 raw walk (LIEF cross-checks them when it parses the table). ``{}`` for non-PE files (as v2)."""
    lief = _lief()
    if lief is None:
        return {}
    b = lief.PE.parse(str(path))
    if b is None:
        return {}
    o: dict[str, Any] = {}
    o["machine"] = MACHINE_V2.get(_enum_name(b.header.machine), "?")
    o["timestamp"] = datetime.fromtimestamp(int(b.header.time_date_stamps), UTC).isoformat().replace("T", " ")[:16]
    o["linker"] = f"{b.optional_header.major_linker_version}.{b.optional_header.minor_linker_version}"
    secs = [(s.name.rstrip("\0"), int(s.virtual_address), int(s.virtual_size), int(s.pointerto_raw_data), int(s.sizeof_raw_data)) for s in b.sections]
    o["sectionNames"] = " ".join(n for n, *_ in secs)
    rd = next((s for s in secs if s[0] == ".rdata"), None)
    if rd:
        o["rdata"] = [rd[3], rd[3] + rd[4]]
    o["exports"] = _v2_exports_raw(Path(path).read_bytes())
    o["format"] = _format_from_exports(o["exports"])
    return o


def inventory(path: Path) -> dict[str, Any]:
    p = Path(path)
    data = p.read_bytes()
    out: dict[str, Any] = {"file": p.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "tool": "lief", "status": "UNAVAILABLE"}
    lief = _lief()
    if lief is None:
        out["detail"] = "LIEF not importable: pip install lief==1.0.0 (docs/DEPENDENCIES.md)"
        return out
    out["tool_version"] = deps.check("lief").version
    b = lief.parse(str(p))
    if b is None:
        out.update({"status": "UNPARSED", "format": "unknown", "detail": "not a PE/ELF/Mach-O file LIEF can parse"})
        return out
    if isinstance(b, lief.MachO.FatBinary):
        out["fat_slices"] = len(b)
        b = b.at(0)
    out["status"] = "PARSED"
    fmt = _enum_name(b.format)
    out["format"] = {"PE": "PE", "ELF": "ELF", "MACHO": "Mach-O"}.get(fmt, fmt)
    out["entrypoint"] = f"0x{int(b.entrypoint):x}" if getattr(b, "entrypoint", None) is not None else None
    sections = []
    for s in b.sections:
        sections.append({"name": s.name.rstrip("\0"), "va": int(getattr(s, "virtual_address", 0)), "vsize": int(getattr(s, "virtual_size", getattr(s, "size", 0))),
                         "offset": int(getattr(s, "offset", getattr(s, "pointerto_raw_data", 0))), "size": int(getattr(s, "size", getattr(s, "sizeof_raw_data", 0))),
                         "entropy": round(float(s.entropy), 3) if hasattr(s, "entropy") else None})
    out["sections"] = sections
    exports = sorted({f.name for f in b.exported_functions if f.name})
    imports = sorted({f.name for f in b.imported_functions if f.name})
    out["exports"] = exports[:2000]
    out["export_count"] = len(exports)
    out["imports"] = imports[:2000]
    out["import_count"] = len(imports)
    out["libraries"] = sorted(str(x) for x in getattr(b, "libraries", []) or [])
    out["plugin_format"] = _format_from_exports(exports)
    out["debug"] = {}
    if fmt == "PE":
        h = b.header
        out["arch"] = MACHINE_V2.get(_enum_name(h.machine), _enum_name(h.machine))
        out["timestamp"] = datetime.fromtimestamp(int(h.time_date_stamps), UTC).isoformat()
        out["linker"] = f"{b.optional_header.major_linker_version}.{b.optional_header.minor_linker_version}"
        out["subsystem"] = _enum_name(b.optional_header.subsystem)
        try:
            for d in b.debug:
                cv = getattr(d, "code_view", None) or (d if _enum_name(d.type) == "CODEVIEW" else None)
                fn = getattr(cv, "filename", None)
                if fn:
                    out["debug"] = {"kind": "CODEVIEW_RSDS", "pdb": fn, "age": int(getattr(cv, "age", 0)), "guid": str(getattr(cv, "guid", ""))}
        except Exception:  # noqa: BLE001 — debug directory variants
            pass
        try:
            rh = b.rich_header if b.has_rich_header else None
            out["rich_header"] = [{"id": e.id, "build_id": e.build_id, "count": e.count} for e in rh.entries][:64] if rh else []
        except Exception:  # noqa: BLE001
            out["rich_header"] = []
        out["stripped"] = not any(s["name"] == ".debug$S" for s in sections) and not out["debug"]
    elif fmt == "ELF":
        out["arch"] = _enum_name(b.header.machine_type)
        out["symtab_symbols"] = len(list(b.symtab_symbols)) if hasattr(b, "symtab_symbols") else len(list(getattr(b, "static_symbols", [])))
        out["dynamic_symbols"] = len(list(b.dynamic_symbols))
        out["stripped"] = out["symtab_symbols"] == 0
        for n in b.notes:
            if "BUILD_ID" in _enum_name(getattr(n, "type", "")):
                try:
                    out["debug"] = {"kind": "GNU_BUILD_ID", "build_id": bytes(n.description).hex()}
                except Exception:  # noqa: BLE001
                    pass
        out["has_debug_sections"] = any(s["name"].startswith(".debug") for s in sections)
    else:
        out["arch"] = _enum_name(b.header.cpu_type)
        out["stripped"] = len(list(b.symbols)) < 16
        try:
            out["debug"] = {"kind": "LC_UUID", "uuid": str(b.uuid.uuid)} if b.has_uuid else {}
        except Exception:  # noqa: BLE001
            pass
    return out


__all__ = ["inventory", "v2_pe_dict"]
