#!/usr/bin/env python3
"""Deterministic synthetic plugin binary for engine tests (DECISIONS D-007).

TEST DATA, NEVER EVIDENCE. ``SynthPlug.vst3`` is a well-formed PE32+ image with
a ``.rdata`` section that carries exactly what Static Recovery v2 looks for:

* exports ``GetPluginFactory`` (→ format VST3), MSVC linker 14.0, timestamp
* MSVC RTTI type-descriptor strings for plugin-owned, JUCE, third-party and
  OS classes (plus one false positive)
* an embedded APVTS preset XML with 3 keys (one indexed → STATE_FIELD_CANDIDATE)
* a valid PNG (IHDR/IDAT/IEND), a valid 4-table TrueType font with a Windows
  ``name`` table ("Synth Sans"), a RIFF/WAVE with JUNK+bext before fmt (the BWF
  case), a headerless layout XML document, and a truncated PNG (INVALID)
* JUCE BinaryData names (``knob_png``, ``SynthSans_ttf``, ``bg_png``), a JUCE
  version string, project/framework/CRT/build-machine paths, an RSDS .pdb
  reference, licence strings, and π / 44100 / 1/√2 constants in .rdata

Everything is written in a fixed order with fixed bytes, so its SHA-256 is
stable across machines: the static baseline in ``fixtures/static_v2/synthetic``
diffs against it. Usage: ``python fixtures/synthetic/make_fixture.py [out.vst3]``.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def png(w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + bytes([(x * 7 + y * 3) & 0xFF for x in range(w) for _ in range(4)]) for y in range(h))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ttf(full_name: str) -> bytes:
    """Minimal sfnt: head, hhea, maxp, name tables; the name table is real."""
    def name_table() -> bytes:
        recs = []
        strings = b""
        for nid, text in ((1, full_name.split(" ")[0]), (4, full_name)):
            enc = text.encode("utf-16-be")
            recs.append(struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(enc), len(strings)))
            strings += enc
        count = len(recs)
        return struct.pack(">HHH", 0, count, 6 + 12 * count) + b"".join(recs) + strings
    # v2 only accepts fonts whose table extents exceed 1 KB, so carry a glyf table of real size
    tables = {b"head": bytes(54), b"hhea": bytes(36), b"maxp": bytes(6), b"name": name_table(), b"glyf": bytes(range(256)) * 8}
    n = len(tables)
    out = struct.pack(">IHHHH", 0x00010000, n, 64, 2, 0)
    offset = 12 + 16 * n
    dir_entries, blobs = b"", b""
    for tag in sorted(tables):
        data = tables[tag]
        padded = data + b"\0" * ((4 - len(data) % 4) % 4)
        dir_entries += tag + struct.pack(">III", 0, offset + len(blobs), len(data))
        blobs += padded
    return out + dir_entries + blobs


def bwf_wav(seconds: float = 0.05, sr: int = 48000) -> bytes:
    n = int(seconds * sr)
    data = b"".join(struct.pack("<h", int(8000 * ((i % 97) - 48) / 48)) for i in range(n))
    junk = b"JUNK" + struct.pack("<I", 28) + bytes(28)
    bext = b"bext" + struct.pack("<I", 602) + b"Synth IR".ljust(602, b"\0")
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
    body = b"WAVE" + junk + bext + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


PRESET_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n<PARAMETERS><PARAM id="drive" value="0.75"/>'
    b'<PARAM id="oversample" value="1.0"/><PARAM id="waveShapers_4_2" value="0.25"/>'
    b'<PARAM id="drive" value="0.5"/></PARAMETERS>'
)

LAYOUT_XML = (
    b'<layout version="2"><knob id="drive" x="10" y="20" w="60" h="60" param="drive"/>'
    b'<slider id="cutoff" x="90" y="20" w="60" h="60"/><button id="oversample" x="170" y="20"/>'
    + b'<label text="pad"/>' * 12 + b"</layout>"
)

STRINGS = [
    b".?AVSynthClipper@synth@@", b".?AVSynthFilter@synth@@", b".?AVSynthPlugAudioProcessor@@",
    b".?AVSynthLookAndFeel@@", b".?AVSerialScreen@@", b".?AVSlider@juce@@", b".?AVAudioProcessor@juce@@",
    b".?AVSoundTouch@soundtouch@@", b".?AVbasic_string@std@@", b".?AVIUnknown@@", b".?AVab@@",
    b"JUCE v7.0.5", b"JucePlugin_Name", b"JucePlugin_Manufacturer",
    b"C:\\dev\\SynthPlug\\Source\\PluginProcessor.cpp", b"C:\\dev\\SynthPlug\\Source\\DSP\\Clipper.h",
    b"C:\\JUCE\\modules\\juce_dsp\\juce_dsp.h", b"D:\\a\\1\\s\\build\\x64\\Release\\junk.obj",
    b"C:\\Program Files (x86)\\Windows Kits\\10\\Include\\ucrt\\corecrt_internal_strtox.h",
    b"knob_png", b"SynthSans_ttf", b"bg_png", b"isLicensed", b"serial_number_background", b"rSavedState",
    b"oversampl", b"tanh", b"lookahead", b"GetPluginFactory", b"AudioProcessorValueTreeState",
]


def build() -> bytes:
    e_lfanew = 0x80
    opt_size = 240
    sec_raw = 0x400
    rdata = bytearray()

    def put(b: bytes, align: int = 16) -> int:
        while len(rdata) % align:
            rdata.append(0)
        off = len(rdata)
        rdata.extend(b)
        rdata.append(0)
        return off

    # export directory at .rdata+0x100
    rdata.extend(bytes(0x100))
    exports = (b"GetPluginFactory", b"InitDll", b"ExitDll")
    rdata_va = 0x1000
    exp_base = len(rdata)
    rdata.extend(bytes(40))
    names_rva = rdata_va + exp_base + 40
    rdata.extend(bytes(4 * len(exports)))
    str_off = []
    for name in exports:
        str_off.append(len(rdata))
        rdata.extend(name + b"\0")
    struct.pack_into("<I", rdata, exp_base + 24, len(exports))
    struct.pack_into("<I", rdata, exp_base + 32, names_rva)
    for i, so in enumerate(str_off):
        struct.pack_into("<I", rdata, exp_base + 40 + 4 * i, rdata_va + so)

    for s in STRINGS:
        put(s)
    # UTF-16 strings too (v2 scans both)
    put("MSVC 14.0 x64".encode("utf-16-le"))
    # RSDS debug record: "RSDS" + 16-byte guid + 4-byte age + path
    put(b"RSDS" + bytes(range(16)) + struct.pack("<I", 1) + b"C:\\dev\\SynthPlug\\build\\SynthPlug.pdb")
    # constants at 4-byte alignment
    put(struct.pack("<d", 3.141592653589793) + struct.pack("<f", 44100.0) + struct.pack("<f", 0.70710678) + struct.pack("<d", 2 * 3.141592653589793), 8)
    # resources
    put(PRESET_XML)
    put(LAYOUT_XML)
    put(png(16, 16))
    put(png(8, 64))                       # tall → SPRITE_SHEET_CANDIDATE (h ≥ 4w)
    put(png(24, 24)[:60])                 # truncated → no IEND → not carved / INVALID
    put(ttf("Synth Sans"))
    put(bwf_wav())
    put(b"\x00\x01\x00\x00" + b"\xff" * 40)   # fake TrueType signature in code → must be rejected
    put(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x01" * 300 + b"\xff\xd9")   # JFIF-marked but tiny (<96 bytes? no: >96) heuristic jpg
    while len(rdata) % 0x200:
        rdata.append(0)
    rdata_size = len(rdata)

    # deterministic pseudo-code section so the image is > 32 KB (v2 binary threshold)
    text = bytearray()
    x = 0x12345678
    for _ in range(48 * 1024):
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
        text.append((x >> 16) & 0xFF)
    text_size = len(text)
    text_va = 0x1000
    rdata_va = 0x1000 + ((text_size + 0xFFF) & ~0xFFF)
    # patch the export directory RVAs for the new .rdata VA
    struct.pack_into("<I", rdata, exp_base + 32, rdata_va + exp_base + 40)
    for i, so in enumerate(str_off):
        struct.pack_into("<I", rdata, exp_base + 40 + 4 * i, rdata_va + so)
    rdata_raw = sec_raw + text_size

    img = bytearray(sec_raw) + text + rdata
    img[0:2] = b"MZ"
    struct.pack_into("<I", img, 0x3C, e_lfanew)
    img[e_lfanew:e_lfanew + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", img, e_lfanew + 4, 0x8664, 2, 1720000000, 0, 0, opt_size, 0x2022)
    opt = e_lfanew + 24
    struct.pack_into("<H", img, opt, 0x20B)
    img[opt + 2], img[opt + 3] = 14, 0
    struct.pack_into("<II", img, opt + 112, rdata_va + exp_base, 0x200)
    sec = opt + opt_size
    img[sec:sec + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", img, sec + 8, text_size, text_va, text_size, sec_raw)
    sec2 = sec + 40
    img[sec2:sec2 + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", img, sec2 + 8, rdata_size, rdata_va, rdata_size, rdata_raw)
    return bytes(img)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("SynthPlug.vst3"))
    data = build()
    out.write_bytes(data)
    import hashlib  # noqa: PLC0415

    print(f"{out} {len(data)} bytes sha256={hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
