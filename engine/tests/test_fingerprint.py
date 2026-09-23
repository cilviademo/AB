"""ADDENDUM A3: Capstone signature set — deterministic, symbol-independent, relocation-insensitive."""
from __future__ import annotations

from pathlib import Path

import pytest

from ab_engine import deps
from ab_engine.decompile import stability
from ab_engine.fingerprint import capstone_fp as cf

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "SynthPlug.vst3"
needs = pytest.mark.skipif(not (deps.available("lief") and deps.available("capstone")), reason="lief + capstone")


@needs
def test_signature_set_is_deterministic_and_symbol_free(tmp_path):
    r1 = cf.fingerprint_binary(FIXTURE)
    r2 = cf.fingerprint_binary(FIXTURE)
    assert r1["status"] == "OK" and r1["arch"] == "x64" and r1["functions"]
    assert stability.compare(r1["functions"], r2["functions"], min_size=1)["match_ratio"] == 1.0
    f = r1["functions"][0]
    for k in ("RAW_BYTE_HASH", "NORMALIZED_INSTRUCTION_HASH", "CFG_SIGNATURE", "CONSTANT_SIGNATURE", "STRING_XREF_SIGNATURE", "CALLGRAPH_SIGNATURE"):
        assert k in f
    # a relocated copy (every rip-relative displacement shifted) keeps its normalized hash
    out = cf.write(FIXTURE, tmp_path / "fp.json")
    assert (tmp_path / "fp.json").is_file() and out["status"] == "OK"


@needs
def test_normalization_masks_addresses_but_keeps_small_immediates():
    import capstone as cs

    md = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64)
    md.detail = True
    img = {"image_lo": 0x400000, "image_hi": 0x500000, "ro": [], "text": [], "arch": "x64"}
    consts: list = []
    strings: list = []
    # mov eax, 5 ; mov rdi, 0x401000 ; add xmm0, [rip+0x10]
    code = b"\xb8\x05\x00\x00\x00" + b"\x48\xc7\xc7\x00\x10\x40\x00" + b"\xf3\x0f\x58\x05\x10\x00\x00\x00"
    ops = []
    for ins in md.disasm(code, 0x401000):
        ops.append(",".join(cf._norm_op_x86(ins, op, img, cs, consts, strings) for op in ins.operands))
    assert ops[0] == "R4,I5" and ops[1] == "R8,A" and ops[2] == "X16,M4[rip]"
    assert 5 in consts
