"""Synthetic test inputs. Test data, never evidence."""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path


def fake_pe(size: int = 64 * 1024, machine: int = 0x8664, exports: tuple[str, ...] = ("GetPluginFactory",)) -> bytes:
    """A minimal but well-formed PE: DOS header, PE signature, one .rdata section
    holding an export directory with the given names. Enough for parsePE."""
    e_lfanew = 0x80
    nsec = 1
    opt_size = 240  # PE32+
    headers_end = e_lfanew + 4 + 20 + opt_size + 40 * nsec
    sec_raw = 0x400
    rdata_size = max(0x1000, size - sec_raw)
    img = bytearray(sec_raw + rdata_size)
    img[0:2] = b"MZ"
    img[0x3C:0x40] = struct.pack("<I", e_lfanew)
    img[e_lfanew:e_lfanew + 4] = b"PE\0\0"
    # COFF: machine, nsec, timestamp, symtab, nsyms, optsize, characteristics
    img[e_lfanew + 4:e_lfanew + 24] = struct.pack("<HHIIIHH", machine, nsec, 1720000000, 0, 0, opt_size, 0x2022)
    opt = e_lfanew + 24
    img[opt:opt + 2] = struct.pack("<H", 0x20B)
    img[opt + 2] = 14  # linker major
    img[opt + 3] = 0
    # data directory 0 (exports) at opt+112 for PE32+
    rdata_va = 0x1000
    exp_off = 0x100  # within .rdata
    img[opt + 112:opt + 120] = struct.pack("<II", rdata_va + exp_off, 0x200)
    sec = opt + opt_size
    img[sec:sec + 8] = b".rdata\0\0"
    img[sec + 8:sec + 24] = struct.pack("<IIII", rdata_size, rdata_va, rdata_size, sec_raw)
    assert headers_end <= sec_raw
    # export directory: names table at exp_off+40, strings after
    base = sec_raw + exp_off
    names_rva = rdata_va + exp_off + 40
    str_rva = names_rva + 4 * len(exports)
    img[base + 24:base + 28] = struct.pack("<I", len(exports))
    img[base + 32:base + 36] = struct.pack("<I", names_rva)
    cursor = str_rva
    for i, name in enumerate(exports):
        img[sec_raw + exp_off + 40 + 4 * i: sec_raw + exp_off + 44 + 4 * i] = struct.pack("<I", cursor)
        off = sec_raw + (cursor - rdata_va)
        img[off:off + len(name) + 1] = name.encode() + b"\0"
        cursor += len(name) + 1
    return bytes(img)


def write_tree(root: Path, spec: dict[str, bytes]) -> None:
    for rel, data in spec.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def make_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
