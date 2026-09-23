#!/usr/bin/env python3
"""Generate the AB icon set (PNG + ICO) with no image library.

The mark is a bench: a wide top rail over two legs, white on the product's
#0A0A0A. Run from the repo root: ``python scripts/make_icons.py``.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

BG = (0x0A, 0x0A, 0x0A, 255)
FG = (0xF2, 0xF2, 0xF2, 255)
FG2 = (0x9D, 0x9D, 0x9D, 255)


def render(size: int) -> bytes:
    px = [[BG] * size for _ in range(size)]
    m = size / 32.0
    def rect(x0, y0, x1, y1, c):
        for y in range(max(0, int(y0 * m)), min(size, int(y1 * m))):
            for x in range(max(0, int(x0 * m)), min(size, int(x1 * m))):
                px[y][x] = c
    rect(4, 9, 28, 13, FG)       # top rail
    rect(7, 13, 10, 25, FG2)     # left leg
    rect(22, 13, 25, 25, FG2)    # right leg
    rect(4, 25, 28, 26.5, FG)    # base line
    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in px)
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(pngs: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(pngs))
    entries, data, off = b"", b"", 6 + 16 * len(pngs)
    for size, png in pngs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), off)
        data += png
        off += len(png)
    return head + entries + data


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "app/src-tauri/icons")
    out.mkdir(parents=True, exist_ok=True)
    for name, size in (("32x32.png", 32), ("64x64.png", 64), ("128x128.png", 128), ("128x128@2x.png", 256),
                       ("icon.png", 512), ("Square30x30Logo.png", 30), ("Square44x44Logo.png", 44),
                       ("Square71x71Logo.png", 71), ("Square89x89Logo.png", 89), ("Square107x107Logo.png", 107),
                       ("Square142x142Logo.png", 142), ("Square150x150Logo.png", 150), ("Square284x284Logo.png", 284),
                       ("Square310x310Logo.png", 310), ("StoreLogo.png", 50)):
        (out / name).write_bytes(render(size))
    (out / "icon.ico").write_bytes(ico([(256, render(256)), (48, render(48)), (32, render(32)), (16, render(16))]))
    print(f"wrote icons to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
