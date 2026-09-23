"""Identity from runtime facts (EXECUTE 2.3).

JUCE's VST3 wrapper derives its component/controller class IDs from the
plugin's manufacturer and plugin codes::

    component  = FUID (0xABCDEF01, 0x9182FAEB, JucePlugin_ManufacturerCode, JucePlugin_PluginCode)
    controller = FUID (0xABCDEF01, 0x1234ABCD, JucePlugin_ManufacturerCode, JucePlugin_PluginCode)

(``JUCE_VST3_CAN_REPLACE_VST2`` uses a different layout and is reported as such.)
So for a JUCE plugin the two four-character codes are literally present in the
FUID the factory reports: they are read, not guessed, and the derivation is
recorded next to them. Non-JUCE plugins keep ``UNKNOWN`` codes.
FUID byte order differs between COM (Windows) and the other platforms; both
layouts are tried and the one that reproduces the JUCE magic words wins.
"""

from __future__ import annotations

import struct
from typing import Any

JUCE_MAGIC_1 = 0xABCDEF01
JUCE_COMPONENT_MAGIC = 0x9182FAEB
JUCE_CONTROLLER_MAGIC = 0x1234ABCD


def _four_ints(raw: bytes, layout: str) -> tuple[int, int, int, int]:
    if layout == "com":  # Windows: data1 LE u32, data2 LE u16, data3 LE u16, data4 8 bytes big-endian-ish
        d1, d2, d3 = struct.unpack("<IHH", raw[:8])
        l1 = d1
        l2 = (d2 << 16) | d3
        l3 = struct.unpack(">I", raw[8:12])[0]
        l4 = struct.unpack(">I", raw[12:16])[0]
        return l1, l2, l3, l4
    return struct.unpack(">IIII", raw)


def _code(v: int) -> str:
    b = v.to_bytes(4, "big")
    return b.decode("latin1")


def juce_codes_from_cid(cid_hex: str) -> dict[str, Any] | None:
    """Return {manufacturer_code, plugin_code, kind, layout} when the FUID is JUCE-derived."""
    try:
        raw = bytes.fromhex(cid_hex.strip())
    except ValueError:
        return None
    if len(raw) != 16:
        return None
    for layout in ("com", "inline"):
        l1, l2, l3, l4 = _four_ints(raw, layout)
        if l1 != JUCE_MAGIC_1:
            continue
        kind = "component" if l2 == JUCE_COMPONENT_MAGIC else "controller" if l2 == JUCE_CONTROLLER_MAGIC else None
        if kind is None:
            continue
        m, p = _code(l3), _code(l4)
        if all(0x20 <= ord(c) < 0x7F for c in m + p):
            return {"manufacturer_code": m, "plugin_code": p, "kind": kind, "layout": layout,
                    "derivation": f"FUID(0x{l1:08X}, 0x{l2:08X}, '{m}', '{p}') — JUCE VST3 wrapper class-id rule"}
    return None


def identity_from_runtime(factory: dict[str, Any], class_info: dict[str, Any] | None) -> dict[str, Any]:
    classes = factory.get("classes", [])
    audio = [c for c in classes if c.get("category") == "Audio Module Class"]
    chosen = class_info or (audio[0] if audio else None)
    out: dict[str, Any] = {
        "vendor": factory.get("vendor"), "url": factory.get("url"), "email": factory.get("email"),
        "product": chosen.get("name") if chosen else None, "version": chosen.get("version") if chosen else None,
        "sdk": chosen.get("sdk") if chosen else None, "subcategories": chosen.get("subcategories") if chosen else None,
        "processor_fuid": chosen.get("cid") if chosen else None, "controller_fuid": None,
        "manufacturer_code": "UNKNOWN", "plugin_code": "UNKNOWN", "codes_status": "UNKNOWN", "codes_derivation": None,
        "evidence": "VERIFIED_RUNTIME", "source": "vst3host factory",
    }
    if chosen:
        codes = juce_codes_from_cid(chosen.get("cid", ""))
        if codes:
            out.update({"manufacturer_code": codes["manufacturer_code"], "plugin_code": codes["plugin_code"],
                        "codes_status": "VERIFIED_RUNTIME (JUCE FUID derivation)", "codes_derivation": codes["derivation"]})
        for c in classes:
            if c.get("category") == "Component Controller Class":
                cc = juce_codes_from_cid(c.get("cid", ""))
                if cc and codes and cc["plugin_code"] == codes["plugin_code"]:
                    out["controller_fuid"] = c["cid"]
                elif out["controller_fuid"] is None:
                    out["controller_fuid"] = c["cid"]
    return out
