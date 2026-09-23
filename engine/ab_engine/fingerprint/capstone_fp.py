"""Function signature set before Ghidra (EXECUTE_ADDENDUM_A §A3), computed with Capstone from the
LIEF inventory of a PE / ELF / Mach-O image.

Per function (same field names as ``ghidra/Fingerprint.java`` so ``decompile.stability`` and the
knowledge cache match either source):

* ``RAW_BYTE_HASH``                 sha256 of the function bytes
* ``NORMALIZED_INSTRUCTION_HASH``   sha256 of the normalized instruction stream: mnemonic +
  operand shape; immediates that are addresses / relocations (image range, rip-relative
  displacements) masked; stack-frame displacements normalized; registers reduced to class+width
* ``TLSH``                          TLSH of the normalized stream (relatedness only; absent when
  py-tlsh is not installed or the stream is too short)
* ``CFG_SIGNATURE``                 basic-block count and an edge-shape hash
* ``CONSTANT_SIGNATURE``            sorted immediates and float32/float64 constants loaded
  rip-relative from read-only data
* ``STRING_XREF_SIGNATURE``         hash of the sorted printable strings referenced rip-relative
* ``CALLGRAPH_SIGNATURE``           hash of the sorted normalized hashes of direct callees (depth 1)

Function starts without symbols come from exports, direct call targets and prologue patterns; a
function spans to the next start (trimmed at trailing padding). This is deliberately a fast,
conservative pass: it exists so the knowledge cache can match *before* Ghidra runs and Ghidra is
scheduled only on the residual. Nothing here names a function.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from ab_engine import deps

PROLOGUES_X64 = (b"\xf3\x0f\x1e\xfa", b"\x55\x48\x89\xe5", b"\x55\x48\x8b\xec", b"\x48\x83\xec", b"\x48\x81\xec", b"\x41\x57", b"\x41\x56", b"\x41\x55", b"\x41\x54", b"\x53\x48\x83\xec", b"\x55\x53", b"\x55\x41\x57", b"\x55\x41\x56")
PROLOGUES_X86 = (b"\x55\x8b\xec", b"\x55\x89\xe5")


def _cs_for(arch: str, bits: int):
    import capstone as cs  # noqa: PLC0415

    if arch in ("x64", "X86_64", "AMD64", "x86"):
        md = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64 if bits == 64 else cs.CS_MODE_32)
    elif arch.upper().startswith("ARM64") or arch.upper() in ("AARCH64",):
        md = cs.Cs(cs.CS_ARCH_ARM64, cs.CS_MODE_ARM)
    else:
        raise ValueError(f"unsupported architecture {arch}")
    md.detail = True
    md.skipdata = True
    return md


def _load_image(path: Path) -> dict[str, Any]:
    """Text + read-only sections with their virtual addresses, plus exports and the image range."""
    import lief  # noqa: PLC0415

    lief.logging.disable()
    b = lief.parse(str(path))
    if b is None:
        raise ValueError("not a parseable binary")
    if isinstance(b, lief.MachO.FatBinary):
        b = b.at(0)
    fmt = str(b.format).rsplit(".", 1)[-1]
    base = int(getattr(b.optional_header, "imagebase", 0)) if fmt == "PE" else 0
    text, ro = [], []
    for s in b.sections:
        name = s.name.rstrip("\0")
        va = base + int(getattr(s, "virtual_address", 0))
        content = bytes(s.content)
        if not content:
            continue
        is_code = False
        if fmt == "PE":
            is_code = name in (".text",) or "CODE" in name.upper() or name.startswith(".text")
        elif fmt == "ELF":
            is_code = name in (".text", ".init", ".fini", ".plt", ".plt.sec") or name.startswith(".text.")
        else:
            is_code = name in ("__text", "__stubs")
        if is_code and name not in (".plt", ".plt.sec", "__stubs", ".init", ".fini"):
            text.append((name, va, content))
        elif not is_code:
            ro.append((name, va, content))
    if fmt == "PE":
        arch = {"I386": "x86", "AMD64": "x64", "ARM64": "ARM64"}.get(str(b.header.machine).rsplit(".", 1)[-1], "?")
        bits = 32 if arch == "x86" else 64
    elif fmt == "ELF":
        m = str(b.header.machine_type).rsplit(".", 1)[-1]
        arch = {"X86_64": "x64", "I386": "x86", "AARCH64": "ARM64"}.get(m, m)
        bits = 32 if arch == "x86" else 64
    else:
        m = str(b.header.cpu_type).rsplit(".", 1)[-1]
        arch = {"X86_64": "x64", "ARM64": "ARM64"}.get(m, m)
        bits = 64
    exports = {}
    for f in b.exported_functions:
        if f.address:
            exports[base + int(f.address)] = f.name
    syms = {}
    for f in getattr(b, "functions", []) or []:
        try:
            if f.address:
                syms.setdefault(base + int(f.address), f.name)
        except Exception:  # noqa: BLE001
            pass
    lo = min(va for _, va, _ in text) if text else 0
    hi = max(va + len(c) for _, va, c in text + ro) if (text or ro) else 0
    return {"format": fmt, "arch": arch, "bits": bits, "text": text, "ro": ro, "exports": exports, "symbols": syms, "image_lo": lo, "image_hi": hi, "base": base}


def _read_ro(img: dict[str, Any], addr: int, n: int) -> bytes | None:
    for _, va, content in img["ro"] + img["text"]:
        if va <= addr and addr + n <= va + len(content):
            off = addr - va
            return content[off:off + n]
    return None


def _string_at(img: dict[str, Any], addr: int) -> str | None:
    raw = _read_ro(img, addr, 256)
    if not raw:
        return None
    end = raw.find(b"\0")
    s = raw[:end if end >= 0 else 256]
    if len(s) >= 4 and all(32 <= c < 127 for c in s):
        return s.decode("ascii")
    return None


def discover_starts(img: dict[str, Any], md) -> list[int]:
    """Exports + direct call targets + prologue patterns, all inside the code sections.

    Symbols are deliberately NOT used as starts: the stripped artifact has none, and the signature
    set must be computed the same way on every build for cross-build matching (gate A3). Symbol
    names only annotate the functions they land on."""
    starts: set[int] = set(a for a in img["exports"])
    import capstone as cs  # noqa: PLC0415

    x86 = img["arch"] in ("x64", "x86")
    for _, va, content in img["text"]:
        starts.add(va)
        # prologue patterns after alignment padding
        for pat in (PROLOGUES_X64 if img["bits"] == 64 else PROLOGUES_X86) if x86 else ():
            i = content.find(pat)
            while i >= 0:
                if i == 0 or content[i - 1] in (0xC3, 0xCC, 0x90, 0x00) or (i >= 2 and content[i - 2:i] in (b"\x0f\x1f", b"\x66\x90")):
                    starts.add(va + i)
                i = content.find(pat, i + 1)
        # direct call targets (linear sweep; skipdata keeps going through data)
        for ins in md.disasm(content, va):
            if ins.id == 0:
                continue  # skipdata pseudo-instruction
            if x86 and ins.mnemonic == "call" and ins.operands and ins.operands[0].type == cs.x86.X86_OP_IMM:
                starts.add(int(ins.operands[0].imm))
            elif (not x86) and ins.mnemonic == "bl" and ins.operands and ins.operands[0].type == cs.arm64.ARM64_OP_IMM:
                starts.add(int(ins.operands[0].imm))
    lo_hi = [(va, va + len(c)) for _, va, c in img["text"]]
    return sorted(a for a in starts if any(lo <= a < hi for lo, hi in lo_hi))


def _norm_op_x86(ins, op, img, cs, consts: list[float | int], strings: list[str]) -> str:
    if op.type == cs.x86.X86_OP_REG:
        name = ins.reg_name(op.reg)
        cls = "X" if name.startswith("xmm") else "Y" if name.startswith("ymm") else "S" if name in ("rsp", "esp", "rbp", "ebp") else "R"
        return f"{cls}{op.size}"
    if op.type == cs.x86.X86_OP_IMM:
        v = int(op.imm)
        if img["image_lo"] <= v < img["image_hi"]:
            return "A"  # address-like immediate (relocated)
        if -0x10000 < v < 0x10000:
            consts.append(v)
            return f"I{v}"
        consts.append(v)
        return "I"
    if op.type == cs.x86.X86_OP_MEM:
        m = op.mem
        base = ins.reg_name(m.base) if m.base else ""
        if base == "rip":
            target = ins.address + ins.size + int(m.disp)
            s = _string_at(img, target)
            if s:
                strings.append(s)
            elif op.size in (4, 8) and ins.mnemonic.startswith(("movs", "adds", "muls", "subs", "divs", "comis", "ucomis", "cvts", "mulp", "addp", "subp", "movap", "movup")):
                raw = _read_ro(img, target, op.size)
                if raw:
                    try:
                        consts.append(round(struct.unpack("<f" if op.size == 4 else "<d", raw)[0], 9))
                    except struct.error:
                        pass
            return f"M{op.size}[rip]"
        if base in ("rsp", "esp", "rbp", "ebp"):
            return f"M{op.size}[S]"
        idx = "+I" if m.index else ""
        return f"M{op.size}[R{idx}]" + (f"+{int(m.disp)}" if -0x1000 < int(m.disp) < 0x1000 and not m.index else "")
    return "?"


def fingerprint_function(img: dict[str, Any], md, start: int, end: int, tlsh_mod) -> dict[str, Any] | None:
    import capstone as cs  # noqa: PLC0415

    raw = _read_ro(img, start, end - start)
    if raw is None or len(raw) < 4:
        return None
    # trim trailing padding
    while raw and raw[-1] in (0xCC, 0x90, 0x00) and len(raw) > 4:
        raw = raw[:-1]
    x86 = img["arch"] in ("x64", "x86")
    norm: list[str] = []
    consts: list[float | int] = []
    strings: list[str] = []
    callees: list[int] = []
    leaders: set[int] = {start}
    edges: list[tuple[str, str]] = []
    insns = list(md.disasm(raw, start))
    if not insns:
        return None
    for ins in insns:
        if ins.id == 0:
            norm.append(".data")
            continue
        if x86:
            ops = ",".join(_norm_op_x86(ins, op, img, cs, consts, strings) for op in ins.operands)
            norm.append(f"{ins.mnemonic} {ops}")
            g = ins.groups
            if ins.mnemonic == "call" and ins.operands and ins.operands[0].type == cs.x86.X86_OP_IMM:
                callees.append(int(ins.operands[0].imm))
            if cs.CS_GRP_JUMP in g:
                nxt = ins.address + ins.size
                if ins.operands and ins.operands[0].type == cs.x86.X86_OP_IMM:
                    tgt = int(ins.operands[0].imm)
                    if start <= tgt < end:
                        leaders.add(tgt)
                        edges.append(("b", "fwd" if tgt > ins.address else "back"))
                leaders.add(nxt)
                edges.append(("j", "cond" if ins.mnemonic != "jmp" else "uncond"))
            elif cs.CS_GRP_RET in g:
                edges.append(("ret", ""))
        else:
            norm.append(f"{ins.mnemonic} {len(ins.operands)}")
            if ins.mnemonic == "bl" and ins.operands and ins.operands[0].type == cs.arm64.ARM64_OP_IMM:
                callees.append(int(ins.operands[0].imm))
            if ins.mnemonic.startswith(("b", "cb", "tb")) and ins.operands and ins.operands[-1].type == cs.arm64.ARM64_OP_IMM:
                tgt = int(ins.operands[-1].imm)
                if start <= tgt < end:
                    leaders.add(tgt)
                edges.append(("j", "cond" if ins.mnemonic != "b" else "uncond"))
            elif ins.mnemonic == "ret":
                edges.append(("ret", ""))
    stream = "\n".join(norm).encode()
    blocks = len([a for a in leaders if start <= a < end])
    cfg_hash = hashlib.sha256((f"{blocks}|" + ",".join(f"{k}:{v}" for k, v in edges)).encode()).hexdigest()
    consts_sorted = sorted({c for c in consts if isinstance(c, float) or abs(c) >= 2}, key=lambda v: (isinstance(v, float), v))
    fp: dict[str, Any] = {
        "addr": f"0x{start:x}", "size": len(raw), "instructions": len(insns), "name": img["symbols"].get(start) or img["exports"].get(start),
        "RAW_BYTE_HASH": hashlib.sha256(raw).hexdigest(),
        "NORMALIZED_INSTRUCTION_HASH": hashlib.sha256(stream).hexdigest(),
        "CFG_SIGNATURE": {"blocks": blocks, "edges": len(edges), "hash": cfg_hash},
        "CONSTANT_SIGNATURE": [c for c in consts_sorted][:64],
        "STRING_XREF_SIGNATURE": hashlib.sha256("\n".join(sorted(set(strings))).encode()).hexdigest() if strings else "",
        "string_refs": len(set(strings)), "float_consts": sum(1 for c in consts if isinstance(c, float)),
        "float_ops": sum(1 for n in norm if n.startswith(("adds", "subs", "muls", "divs", "sqrts", "maxs", "mins", "cvt", "addp", "mulp", "subp", "divp")) or "X" in n.split(" ", 1)[-1][:6]),
        "_callees": callees,
    }
    if tlsh_mod is not None and len(stream) >= 50:
        try:
            h = tlsh_mod.hash(stream)
            fp["TLSH"] = None if h in ("TNULL", "") else h
        except Exception:  # noqa: BLE001
            fp["TLSH"] = None
    return fp


def fingerprint_binary(path: Path, *, max_functions: int = 200000, progress=None) -> dict[str, Any]:
    if not deps.available("lief") or not deps.available("capstone"):
        return {"status": "UNAVAILABLE", "reason": "lief + capstone required (docs/DEPENDENCIES.md)", "functions": []}
    tlsh_mod = None
    if deps.available("tlsh"):
        import tlsh as tlsh_mod  # noqa: PLC0415
    img = _load_image(path)
    md = _cs_for(img["arch"], img["bits"])
    starts = discover_starts(img, md)
    if progress:
        progress(f"{len(starts)} function starts")
    bounds = []
    for i, s in enumerate(starts[:max_functions]):
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        sec_end = next((va + len(c) for _, va, c in img["text"] if va <= s < va + len(c)), s)
        end = min(nxt, sec_end) if nxt and nxt <= sec_end else sec_end
        bounds.append((s, end))
    fps = []
    for k, (s, e) in enumerate(bounds):
        if progress and k % 5000 == 0:
            progress(f"fingerprint {k}/{len(bounds)}")
        fp = fingerprint_function(img, md, s, e, tlsh_mod)
        if fp:
            fps.append(fp)
    by_addr = {int(f["addr"], 16): f["NORMALIZED_INSTRUCTION_HASH"] for f in fps}
    for f in fps:
        callees = sorted({by_addr.get(c, "external") for c in f.pop("_callees")})
        f["CALLGRAPH_SIGNATURE"] = hashlib.sha256("\n".join(callees).encode()).hexdigest() if callees else ""
        f["callees"] = len(callees)
    return {"status": "OK", "tool": f"capstone {deps.check('capstone').version} + lief {deps.check('lief').version}", "format": img["format"], "arch": img["arch"],
            "functions": fps, "starts": len(starts), "basis": "exports ∪ symbols ∪ direct call targets ∪ prologue patterns; spans to the next start; TLSH " + ("on" if tlsh_mod else "unavailable")}


def write(path: Path, out: Path, **kw: Any) -> dict[str, Any]:
    from ab_engine.contracts import write_json  # noqa: PLC0415

    r = fingerprint_binary(path, **kw)
    write_json(out, "artifactbench.prefingerprints", r)
    return r


__all__ = ["fingerprint_binary", "discover_starts", "fingerprint_function", "write"]
