"""BinaryData resolution (SPEC §8.4, EXECUTE 3.3).

Ghidra's ExportDecompiled hashed every (size, pointer) resource it found in the
getNamedResource switch straight out of program memory. A carved asset with
the same SHA-256 *is* that resource; when a name string sits at the same
position in namedResourceList as the switch case (JUCE emits both tables in
declaration order inside the same TU), the name is assigned VERIFIED.
Otherwise the bytes are proven but the name is not; that is recorded as
VERIFIED_BYTES_NAME_UNRESOLVED — never guessed by declaration order alone.
"""

from __future__ import annotations

import hashlib
from typing import Any

JUCE_HASH_MOD = 2**32


def juce_name_hash(name: str) -> int:
    """JUCE BinaryData::getNamedResource: `hash = 31 * hash + c` over the name (int, wrapping)."""
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


def resolve(resolution: dict[str, Any], carved: list[dict[str, Any]], static_names: list[str]) -> list[dict[str, Any]]:
    """Return binarydata_map rows: {binarydata_name, carved, mapping_status, sha256, size, pointer, basis}."""
    names = list(resolution.get("names", [])) or list(static_names)
    resources = resolution.get("resources", [])
    by_sha = {c.get("sha256"): c for c in carved if c.get("sha256")}
    rows: list[dict[str, Any]] = []
    used_names: set[str] = set()
    # 0. named by a surviving symbol (BinaryData::<name> + <name>Size): the strongest evidence, no positional claim needed
    named = [r for r in resources if r.get("name")]
    for r in named:
        c = by_sha.get(r.get("sha256"))
        if c is not None:
            rows.append({"binarydata_name": r["name"], "carved": c["name"], "sha256": r["sha256"], "size": r["size"], "pointer": r["pointer"],
                         "mapping_status": "VERIFIED (symbol BinaryData::name + nameSize; bytes sha256 match)",
                         "basis": ["sha256 of the bytes at the named symbol equals the carved asset", r.get("basis", "symbol")]})
        else:
            rows.append({"binarydata_name": r["name"], "carved": None, "sha256": r["sha256"], "size": r["size"], "pointer": r["pointer"],
                         "mapping_status": "RESOURCE_NOT_CARVED (bytes located at the named symbol but no carved asset has this hash — DEEP_SCAN or non-carvable type)", "basis": [r.get("basis", "symbol")]})
        used_names.add(r["name"])
    resources = [r for r in resources if not r.get("name")]
    names = [n for n in names if n not in used_names]
    # 1. bytes proven by hash; name by exact position when the two tables have the same length
    positional_ok = len(names) == len(resources) and len(names) > 0
    for i, r in enumerate(resources):
        c = by_sha.get(r.get("sha256"))
        name = names[i] if positional_ok else None
        if c is not None and name is not None:
            rows.append({"binarydata_name": name, "carved": c["name"], "sha256": r["sha256"], "size": r["size"], "pointer": r["pointer"],
                         "mapping_status": "VERIFIED (getNamedResource bytes sha256 match; name by matching table position)",
                         "basis": ["sha256 of the resource bytes read from program memory equals the carved asset", "namedResourceList and getNamedResource cases have equal length; position i ↔ i"]})
            used_names.add(name)
        elif c is not None:
            rows.append({"binarydata_name": None, "carved": c["name"], "sha256": r["sha256"], "size": r["size"], "pointer": r["pointer"],
                         "mapping_status": "VERIFIED_BYTES_NAME_UNRESOLVED (bytes proven; name table length differs, no positional claim)", "basis": ["sha256 match"]})
        else:
            rows.append({"binarydata_name": name, "carved": None, "sha256": r["sha256"], "size": r["size"], "pointer": r["pointer"],
                         "mapping_status": "RESOURCE_NOT_CARVED (bytes located in the binary but no carved asset has this hash — DEEP_SCAN or non-carvable type)", "basis": ["getNamedResource"]})
            if name:
                used_names.add(name)
    for n in names:
        if n not in used_names:
            rows.append({"binarydata_name": n, "carved": None, "mapping_status": "UNRESOLVED (no getNamedResource case matched this name)", "basis": []})
    return rows


def apply_to_index(index: list[dict[str, Any]], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Set candidate_name/mapping_status on carved entries with VERIFIED mappings. Returns (index, renames)."""
    renames: dict[str, str] = {}
    by_name = {r["carved"]: r for r in rows if r.get("carved") and r["mapping_status"].startswith("VERIFIED (")}
    for entry in index:
        r = by_name.get(entry.get("name"))
        if not r:
            continue
        original = r["binarydata_name"]
        filename = original.rsplit("_", 1)[0] + "." + original.rsplit("_", 1)[1] if "_" in original else original
        entry["candidate_name"] = filename
        entry["mapping_status"] = r["mapping_status"]
        entry["mapping_basis"] = r["basis"]
        renames[entry["name"]] = filename
    return index, renames


def sha_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
