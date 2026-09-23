"""Fingerprint stability across builds (EXECUTE 3.2 gate, SPEC §12 metric).

Two fingerprint sets (e.g. Release+PDB and Release-stripped of the same
source) are matched on NORMALIZED_INSTRUCTION_HASH and CFG_SIGNATURE.
RAW_BYTE_HASH is expected to differ (addresses/relocations), which is the
point of the normalized hash. Reported: matched functions, match ratio over
the smaller set, and — when symbol names exist on one side — the matched
names, so the ground-truth comparator can check that the waveshaper and the
filter matched by implementation, not by name.
"""

from __future__ import annotations

from typing import Any


def index(fps: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for f in fps:
        key = (f.get("NORMALIZED_INSTRUCTION_HASH", ""), (f.get("CFG_SIGNATURE") or {}).get("hash", ""))
        out.setdefault(key, []).append(f)
    return out


def compare(a: list[dict[str, Any]], b: list[dict[str, Any]], *, min_size: int = 32) -> dict[str, Any]:
    a = [f for f in a if int(f.get("size", 0)) >= min_size]
    b = [f for f in b if int(f.get("size", 0)) >= min_size]
    ia, ib = index(a), index(b)
    matched = []
    raw_same = 0
    for key, fa in ia.items():
        fb = ib.get(key)
        if not fb:
            continue
        for x in fa[: len(fb)]:
            y = fb[0]
            matched.append({"a": x.get("addr"), "b": y.get("addr"), "name_a": x.get("name"), "name_b": y.get("name"), "size": x.get("size"),
                            "raw_equal": x.get("RAW_BYTE_HASH") == y.get("RAW_BYTE_HASH")})
            raw_same += int(x.get("RAW_BYTE_HASH") == y.get("RAW_BYTE_HASH"))
    smaller = max(1, min(len(a), len(b)))
    ratio = len(matched) / smaller
    return {"functions_a": len(a), "functions_b": len(b), "matched": len(matched), "match_ratio": round(ratio, 4),
            "raw_hash_equal": raw_same, "ok": ratio >= 0.5, "matches": matched[:5000],
            "note": "matched on NORMALIZED_INSTRUCTION_HASH + CFG_SIGNATURE; raw hashes may differ by design"}
