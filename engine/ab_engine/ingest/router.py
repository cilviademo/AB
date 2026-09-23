"""Universal artifact ingest router (ADDENDUM B4).

    INGEST → IDENTIFY → HASH → MIME/MAGIC → FORMAT CLASSIFY → CAPABILITY MATCH → ROUTE

* ``identify`` reads magic bytes, container structure, extension, file name and directory context
  together and returns one identity per artifact (type, family, mime, magic, confidence, evidence).
* ``REGISTRY`` is the Artifact Capability Registry: ``{artifact_type: capabilities[]}``. Adding a type is
  one entry (plus a handler when a parser exists); no central switch grows.
* ``route`` builds the per-artifact route records (``ROUTED`` · ``PRESERVED_UNPARSED`` ·
  ``UNKNOWN_ARTIFACT``) and the relationship engine's edges (identical bytes, PDB ↔ binary by CodeView
  GUID + age, ELF build-id, bundle-name candidates, resource hash equality), each with a confidence and
  its basis. Nothing is merged on file-name similarity alone; unknown files are evidence, never dropped.

Nothing here executes or opens a dropped file beyond reading bytes.
"""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------------------------
# artifact types (B4 input families) and the capability registry

CAPABILITIES = ("preserve", "static_parse", "runtime_host", "decompile", "fingerprint", "probe", "carve_resources", "state_keys", "preset_parse",
                "session_extract", "source_map", "symbol_db", "resource_decode", "archive_expand", "build_evidence", "identity")

REGISTRY: dict[str, dict[str, Any]] = {
    # compiled plugins
    "PLUGIN_PE": {"family": "compiled_plugin", "capabilities": ["preserve", "static_parse", "runtime_host", "decompile", "fingerprint", "probe", "carve_resources", "state_keys", "identity"], "parser": "static-recovery-v2 + LIEF + vst3host + Ghidra"},
    "PLUGIN_ELF": {"family": "compiled_plugin", "capabilities": ["preserve", "static_parse", "runtime_host", "decompile", "fingerprint", "probe", "carve_resources", "state_keys", "identity"], "parser": "LIEF + vst3host + Ghidra"},
    "PLUGIN_MACHO": {"family": "compiled_plugin", "capabilities": ["preserve", "static_parse", "fingerprint"], "parser": "LIEF (inventory); host/decompile pending"},
    "CLAP": {"family": "compiled_plugin", "capabilities": ["preserve"], "parser": None},
    # debug / build evidence
    "PDB": {"family": "debug_evidence", "capabilities": ["preserve", "symbol_db", "build_evidence"], "parser": "MSF 7 header (GUID/age) — full symbol import pending"},
    "MAP": {"family": "debug_evidence", "capabilities": ["preserve", "build_evidence"], "parser": None},
    "DSYM": {"family": "debug_evidence", "capabilities": ["preserve"], "parser": None},
    "BUILD_LOG": {"family": "debug_evidence", "capabilities": ["preserve", "build_evidence"], "parser": None},
    "OBJECT": {"family": "debug_evidence", "capabilities": ["preserve"], "parser": None},
    # source
    "SOURCE_CPP": {"family": "source", "capabilities": ["preserve", "source_map"], "parser": "attached; RTTI/function mapping pending"},
    "SOURCE_OTHER": {"family": "source", "capabilities": ["preserve"], "parser": None},
    "BUILD_SCRIPT": {"family": "source", "capabilities": ["preserve", "build_evidence"], "parser": None},
    "PROJUCER": {"family": "source", "capabilities": ["preserve", "build_evidence"], "parser": None},
    # presets / state
    "VSTPRESET": {"family": "preset", "capabilities": ["preserve", "preset_parse", "state_keys"], "parser": "container header; chunk decoding pending"},
    "FXP_FXB": {"family": "preset", "capabilities": ["preserve", "preset_parse"], "parser": "CcnK header"},
    "AUPRESET": {"family": "preset", "capabilities": ["preserve", "preset_parse"], "parser": "plist XML"},
    "XML_STATE": {"family": "preset", "capabilities": ["preserve", "preset_parse", "state_keys"], "parser": "static-recovery-v2 XML"},
    "JSON": {"family": "preset", "capabilities": ["preserve", "preset_parse"], "parser": "json"},
    "INI": {"family": "preset", "capabilities": ["preserve"], "parser": None},
    # DAW sessions
    "SESSION_RPP": {"family": "daw_session", "capabilities": ["preserve", "session_extract"], "parser": "text (<REAPER_PROJECT); plugin/state extraction pending"},
    "SESSION_ALS": {"family": "daw_session", "capabilities": ["preserve"], "parser": None},
    "SESSION_FLP": {"family": "daw_session", "capabilities": ["preserve"], "parser": None},
    "SESSION_CPR": {"family": "daw_session", "capabilities": ["preserve"], "parser": None},
    "SESSION_OTHER": {"family": "daw_session", "capabilities": ["preserve"], "parser": None},
    # audio / midi
    "AUDIO_WAV": {"family": "audio", "capabilities": ["preserve", "resource_decode"], "parser": "RIFF walk"},
    "AUDIO_AIFF": {"family": "audio", "capabilities": ["preserve", "resource_decode"], "parser": "IFF walk"},
    "AUDIO_FLAC": {"family": "audio", "capabilities": ["preserve"], "parser": None},
    "AUDIO_OGG": {"family": "audio", "capabilities": ["preserve"], "parser": None},
    "AUDIO_MP3": {"family": "audio", "capabilities": ["preserve"], "parser": None},
    "MIDI": {"family": "midi", "capabilities": ["preserve"], "parser": None},
    # assets
    "IMAGE_PNG": {"family": "asset", "capabilities": ["preserve", "resource_decode"], "parser": "PNG chunk walk"},
    "IMAGE_JPEG": {"family": "asset", "capabilities": ["preserve", "resource_decode"], "parser": "JPEG markers"},
    "IMAGE_SVG": {"family": "asset", "capabilities": ["preserve", "resource_decode"], "parser": "XML"},
    "IMAGE_GIF": {"family": "asset", "capabilities": ["preserve"], "parser": None},
    "FONT_SFNT": {"family": "asset", "capabilities": ["preserve", "resource_decode"], "parser": "sfnt table directory"},
    "BLOB": {"family": "asset", "capabilities": ["preserve"], "parser": None},
    # archives / containers
    "ARCHIVE_ZIP": {"family": "archive", "capabilities": ["preserve", "archive_expand"], "parser": "zipfile (traversal / symlink / size guarded)"},
    "ARCHIVE_GZIP": {"family": "archive", "capabilities": ["preserve"], "parser": None},
    "ARCHIVE_7Z": {"family": "archive", "capabilities": ["preserve"], "parser": None},
    "ARCHIVE_RAR": {"family": "archive", "capabilities": ["preserve"], "parser": None},
    "ARCHIVE_TAR": {"family": "archive", "capabilities": ["preserve"], "parser": None},
    "INSTALLER": {"family": "archive", "capabilities": ["preserve"], "parser": None},
    "DOCUMENT": {"family": "documentation", "capabilities": ["preserve"], "parser": None},
    "UNKNOWN": {"family": "unknown", "capabilities": ["preserve"], "parser": None},
}

#: the v2 ingest kind each type maps to (the frozen grouping rules keep working)
KIND_OF = {"PLUGIN_PE": "binary", "PLUGIN_ELF": "binary", "PLUGIN_MACHO": "binary", "CLAP": "binary", "PDB": "pdb", "MAP": "map", "DSYM": "other", "BUILD_LOG": "other", "OBJECT": "obj",
           "SOURCE_CPP": "source", "SOURCE_OTHER": "source", "BUILD_SCRIPT": "source", "PROJUCER": "source", "VSTPRESET": "preset", "FXP_FXB": "preset", "AUPRESET": "preset",
           "XML_STATE": "preset", "JSON": "preset", "INI": "preset", "SESSION_RPP": "session", "SESSION_ALS": "session", "SESSION_FLP": "session", "SESSION_CPR": "session",
           "SESSION_OTHER": "session", "AUDIO_WAV": "asset", "AUDIO_AIFF": "asset", "AUDIO_FLAC": "asset", "AUDIO_OGG": "asset", "AUDIO_MP3": "asset", "MIDI": "other",
           "IMAGE_PNG": "asset", "IMAGE_JPEG": "asset", "IMAGE_SVG": "asset", "IMAGE_GIF": "asset", "FONT_SFNT": "asset", "BLOB": "other", "ARCHIVE_ZIP": "archive",
           "ARCHIVE_GZIP": "other", "ARCHIVE_7Z": "other", "ARCHIVE_RAR": "other", "ARCHIVE_TAR": "other", "INSTALLER": "other", "DOCUMENT": "other", "UNKNOWN": "other"}

MIME = {"PLUGIN_PE": "application/vnd.microsoft.portable-executable", "PLUGIN_ELF": "application/x-elf", "PLUGIN_MACHO": "application/x-mach-binary", "PDB": "application/vnd.ms-pdb",
        "IMAGE_PNG": "image/png", "IMAGE_JPEG": "image/jpeg", "IMAGE_SVG": "image/svg+xml", "IMAGE_GIF": "image/gif", "FONT_SFNT": "font/sfnt", "AUDIO_WAV": "audio/wav",
        "AUDIO_AIFF": "audio/aiff", "AUDIO_FLAC": "audio/flac", "AUDIO_OGG": "audio/ogg", "AUDIO_MP3": "audio/mpeg", "MIDI": "audio/midi", "ARCHIVE_ZIP": "application/zip",
        "ARCHIVE_GZIP": "application/gzip", "ARCHIVE_7Z": "application/x-7z-compressed", "ARCHIVE_RAR": "application/vnd.rar", "ARCHIVE_TAR": "application/x-tar",
        "JSON": "application/json", "XML_STATE": "application/xml", "AUPRESET": "application/xml", "SESSION_RPP": "text/plain", "DOCUMENT": "application/pdf"}

HEAD_BYTES = 512

_PLUGIN_EXT = re.compile(r"\.(vst3|vst|component|dll|dylib|so|clap)$", re.I)
_SRC_EXT = re.compile(r"\.(cpp|cc|cxx|c|h|hpp|hh|mm|m|rs|swift)$", re.I)
_BUILD_EXT = re.compile(r"(CMakeLists\.txt|\.cmake|Makefile|\.vcxproj|\.sln|\.xcodeproj|\.pbxproj)$", re.I)
_DOC_EXT = re.compile(r"\.(md|txt|rtf|pdf|html?)$", re.I)


def _magic(head: bytes, name: str, size: int) -> tuple[str | None, str, float]:
    """(type, magic description, confidence) from bytes alone."""
    h = head
    if h[:2] == b"MZ":
        return ("PLUGIN_PE" if _PLUGIN_EXT.search(name) or size > 32 * 1024 else "INSTALLER"), "MZ (PE)", 0.95
    if h[:4] == b"\x7fELF":
        return "PLUGIN_ELF", "7f ELF", 0.95
    if h[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
        return "PLUGIN_MACHO", "Mach-O", 0.95
    if h.startswith(b"Microsoft C/C++ MSF 7.00"):
        return "PDB", "MSF 7.00", 1.0
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "IMAGE_PNG", "PNG", 1.0
    if h[:3] == b"\xff\xd8\xff":
        return "IMAGE_JPEG", "JPEG SOI", 1.0
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "IMAGE_GIF", "GIF", 1.0
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "AUDIO_WAV", "RIFF/WAVE", 1.0
    if h[:4] == b"FORM" and h[8:12] in (b"AIFF", b"AIFC"):
        return "AUDIO_AIFF", "FORM/AIFF", 1.0
    if h[:4] == b"fLaC":
        return "AUDIO_FLAC", "fLaC", 1.0
    if h[:4] == b"OggS":
        return "AUDIO_OGG", "OggS", 1.0
    if h[:3] == b"ID3" or (h[:2] == b"\xff\xfb" and name.lower().endswith(".mp3")):
        return "AUDIO_MP3", "ID3 / MPEG frame", 0.9
    if h[:4] == b"MThd":
        return "MIDI", "MThd", 1.0
    if h[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf"):
        return "FONT_SFNT", "sfnt", 0.95
    if h[:4] == b"PK\x03\x04" or h[:4] == b"PK\x05\x06":
        return "ARCHIVE_ZIP", "PK", 0.95
    if h[:2] == b"\x1f\x8b":
        return ("SESSION_ALS" if name.lower().endswith(".als") else "ARCHIVE_GZIP"), "gzip", 0.95
    if h[:6] == b"7z\xbc\xaf\x27\x1c":
        return "ARCHIVE_7Z", "7z", 1.0
    if h[:4] == b"Rar!":
        return "ARCHIVE_RAR", "Rar!", 1.0
    if len(h) > 262 and h[257:262] == b"ustar":
        return "ARCHIVE_TAR", "ustar", 1.0
    if h[:4] == b"%PDF":
        return "DOCUMENT", "%PDF", 1.0
    if h[:4] == b"VST3":
        return "VSTPRESET", "VST3 preset container", 1.0
    if h[:4] == b"CcnK":
        return "FXP_FXB", "CcnK", 1.0
    if h[:4] == b"FLhd":
        return "SESSION_FLP", "FLhd", 1.0
    if h[:4] == b"RIFF" and b"NUND" in h[:64]:
        return "SESSION_CPR", "RIFF/NUND", 0.8
    if h.lstrip()[:15] == b"<REAPER_PROJECT":
        return "SESSION_RPP", "<REAPER_PROJECT", 1.0
    t = h.lstrip()
    if t[:5] == b"<?xml" or t[:1] == b"<":
        low = t[:400].lower()
        if b"<plist" in low:
            return "AUPRESET" if name.lower().endswith(".aupreset") else "XML_STATE", "XML plist", 0.9
        if b"<svg" in low:
            return "IMAGE_SVG", "XML svg", 0.95
        return "XML_STATE", "XML", 0.8
    if t[:1] in (b"{", b"[") and name.lower().endswith(".json"):
        return "JSON", "JSON", 0.9
    return None, "", 0.0


def identify(path: str, size: int, head: bytes, *, context: list[str] | None = None) -> dict[str, Any]:
    """Identity of one artifact from magic + container + extension + name + directory context."""
    name = path.replace("\\", "/").split("/")[-1]
    low = path.lower().replace("\\", "/")
    ev: list[str] = []
    t, magic, conf = _magic(head, name, size)
    if t:
        ev.append(f"magic {magic}")
    ext_t: str | None = None
    if name.lower().endswith(".pdb"):
        ext_t = "PDB"
    elif name.lower().endswith(".map"):
        ext_t = "MAP"
    elif name.lower().endswith(".clap"):
        ext_t = "CLAP"
    elif re.search(r"\.(obj|o|ilk|pch)$", name, re.I):
        ext_t = "OBJECT"
    elif name.lower().endswith(".dsym") or "/contents/resources/dwarf/" in low:
        ext_t = "DSYM"
    elif _BUILD_EXT.search(name):
        ext_t = "BUILD_SCRIPT"
    elif name.lower().endswith(".jucer"):
        ext_t = "PROJUCER"
    elif _SRC_EXT.search(name):
        ext_t = "SOURCE_CPP"
    elif name.lower().endswith(".vstpreset"):
        ext_t = "VSTPRESET"
    elif re.search(r"\.(fxp|fxb)$", name, re.I):
        ext_t = "FXP_FXB"
    elif name.lower().endswith(".aupreset"):
        ext_t = "AUPRESET"
    elif name.lower().endswith(".rpp"):
        ext_t = "SESSION_RPP"
    elif name.lower().endswith(".als"):
        ext_t = "SESSION_ALS"
    elif name.lower().endswith(".flp"):
        ext_t = "SESSION_FLP"
    elif name.lower().endswith(".cpr"):
        ext_t = "SESSION_CPR"
    elif re.search(r"\.(logicx|ptx|song|bwproject)$", name, re.I):
        ext_t = "SESSION_OTHER"
    elif re.search(r"\.(ini|cfg|conf)$", name, re.I):
        ext_t = "INI"
    elif re.search(r"\.(log)$", name, re.I) or re.search(r"(build|link|compile).*\.txt$", name, re.I):
        ext_t = "BUILD_LOG"
    elif re.search(r"\.(exe|msi|pkg|dmg)$", name, re.I):
        ext_t = "INSTALLER"
    elif _DOC_EXT.search(name):
        ext_t = "DOCUMENT"
    elif re.search(r"\.(wav|aiff|aif|flac|ogg|mp3|mid|midi|png|jpe?g|svg|gif|ttf|otf)$", name, re.I):
        ext_t = {"wav": "AUDIO_WAV", "aiff": "AUDIO_AIFF", "aif": "AUDIO_AIFF", "flac": "AUDIO_FLAC", "ogg": "AUDIO_OGG", "mp3": "AUDIO_MP3", "mid": "MIDI", "midi": "MIDI", "png": "IMAGE_PNG",
                 "jpg": "IMAGE_JPEG", "jpeg": "IMAGE_JPEG", "svg": "IMAGE_SVG", "gif": "IMAGE_GIF", "ttf": "FONT_SFNT", "otf": "FONT_SFNT"}[name.lower().rsplit(".", 1)[-1]]
    elif _PLUGIN_EXT.search(name):
        ext_t = "PLUGIN_PE" if name.lower().endswith((".dll", ".vst3", ".vst")) else "PLUGIN_MACHO" if name.lower().endswith((".component", ".dylib")) else "PLUGIN_ELF"
    if ext_t:
        ev.append(f"extension → {ext_t}")
    # directory context: a .vst3/.component bundle folder, Source/, Resources/
    ctx_hint = None
    if re.search(r"\.(vst3|component|vst)/", low):
        ctx_hint = "inside a plugin bundle folder"
    elif re.search(r"(^|/)(source|src|include)/", low):
        ctx_hint = "source tree"
    elif re.search(r"(^|/)(resources|assets)/", low):
        ctx_hint = "resources folder"
    if ctx_hint:
        ev.append(f"directory context: {ctx_hint}")
    if t and ext_t and t != ext_t:
        # magic wins for containers; the extension refines only when the magic is generic
        generic = {"XML_STATE", "ARCHIVE_ZIP", "ARCHIVE_GZIP", "INSTALLER", "JSON"}
        if t in generic and ext_t in ("VSTPRESET", "AUPRESET", "SESSION_ALS", "SESSION_OTHER", "PROJUCER", "INI", "BUILD_SCRIPT", "SESSION_CPR", "PLUGIN_PE", "DSYM"):
            final, conf, ev = ext_t, max(conf, 0.7), ev + ["extension refines the generic container"]
        else:
            final, ev = t, ev + [f"magic ({t}) and extension ({ext_t}) disagree: magic wins"]
            conf = min(conf, 0.85)
    elif t:
        final = t
    elif ext_t:
        final, conf = ext_t, 0.5
        if ctx_hint and ext_t in ("SOURCE_CPP", "SOURCE_OTHER") and ctx_hint == "source tree":
            conf = 0.7
    else:
        final, conf = "UNKNOWN", 0.0
    if final == "PLUGIN_ELF" and not (_PLUGIN_EXT.search(name) or "/x86_64-linux/" in low or "/contents/" in low) and size < 32 * 1024:
        final, conf = "BLOB", 0.4
    reg = REGISTRY.get(final, REGISTRY["UNKNOWN"])
    return {"type": final, "family": reg["family"], "mime": MIME.get(final, "application/octet-stream"), "magic": magic or None, "confidence": round(conf, 2),
            "evidence": ev or ["no magic, no known extension"], "capabilities": list(reg["capabilities"]), "parser": reg["parser"], "kind": KIND_OF.get(final, "other"),
            "status": "UNKNOWN_ARTIFACT" if final == "UNKNOWN" else ("ROUTED" if reg["parser"] else "PRESERVED_UNPARSED")}


# ---------------------------------------------------------------------------------------------
# PDB (MSF 7) GUID / age and PE CodeView — the relationship engine's strongest edge

def pdb_guid_age(path: Path) -> dict[str, Any] | None:
    """Read the PDB info stream (stream 1) of an MSF 7.00 file: version, signature, age, GUID.
    Returns None when the file is not an MSF 7 PDB or is malformed (recorded as PARSER_FAILED by the caller)."""
    try:
        with open(path, "rb") as fh:
            sb = fh.read(64)
            if not sb.startswith(b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00"):
                return None
            page, _free, npages, dir_size, _unk, dir_map_page = struct.unpack_from("<IIIIII", sb, 32)
            if page not in (512, 1024, 2048, 4096, 8192) or dir_size <= 0 or dir_size > 64 * 1024 * 1024:
                return None

            def read_page(n: int) -> bytes:
                fh.seek(n * page)
                return fh.read(page)

            n_dir_pages = (dir_size + page - 1) // page
            map_bytes = read_page(dir_map_page)
            dir_pages = struct.unpack_from("<%dI" % n_dir_pages, map_bytes, 0)
            directory = b"".join(read_page(p) for p in dir_pages)[:dir_size]
            n_streams = struct.unpack_from("<I", directory, 0)[0]
            if n_streams < 2 or n_streams > 100000:
                return None
            sizes = struct.unpack_from("<%dI" % n_streams, directory, 4)
            off = 4 + 4 * n_streams
            page_lists = []
            for s in sizes:
                k = 0 if s in (0, 0xFFFFFFFF) else (s + page - 1) // page
                page_lists.append(struct.unpack_from("<%dI" % k, directory, off))
                off += 4 * k
            s1 = sizes[1]
            if s1 in (0, 0xFFFFFFFF) or s1 < 28:
                return None
            info = b"".join(read_page(p) for p in page_lists[1])[:s1]
            version, signature, age = struct.unpack_from("<III", info, 0)
            guid = info[12:28]
            g = guid
            guid_str = "%08x-%04x-%04x-%s-%s" % (struct.unpack("<I", g[0:4])[0], struct.unpack("<H", g[4:6])[0], struct.unpack("<H", g[6:8])[0], g[8:10].hex(), g[10:16].hex())
            return {"version": version, "signature": signature, "age": age, "guid": guid_str.upper(), "page_size": page, "streams": n_streams}
    except (OSError, struct.error, ValueError):
        return None


def pe_codeview(path: Path) -> dict[str, Any] | None:
    """CodeView RSDS record of a PE (GUID, age, pdb path) through LIEF; None when absent or LIEF is missing."""
    try:
        import lief  # noqa: PLC0415

        b = lief.parse(str(path))
        if b is None or not hasattr(b, "debug"):
            return None
        for d in b.debug:
            cv = getattr(d, "code_view", None)
            if cv is None:
                continue
            guid = getattr(cv, "guid", None)
            age = getattr(cv, "age", None)
            fname = getattr(cv, "filename", None)
            if guid is not None:
                return {"guid": str(guid).upper().replace("{", "").replace("}", ""), "age": int(age or 0), "pdb_path": fname}
    except Exception:  # noqa: BLE001 — a malformed PE is a MALFORMED_BINARY record, never a crash
        return None
    return None


def elf_build_id(path: Path) -> str | None:
    try:
        import lief  # noqa: PLC0415

        b = lief.parse(str(path))
        if b is None or not hasattr(b, "notes"):
            return None
        for n in b.notes:
            if "BUILD_ID" in str(getattr(n, "type", "")).upper():
                desc = getattr(n, "description", None)
                if desc is not None:
                    return bytes(desc).hex()
    except Exception:  # noqa: BLE001
        return None
    return None


# ---------------------------------------------------------------------------------------------
# routing + relationships

def route(files: list[dict[str, Any]], *, read_head=None) -> dict[str, Any]:
    """``files``: rows with path, size, sha256 and fs_path (or ``head`` bytes). Returns the route table
    (one record per artifact) and the relationship edges."""
    records: list[dict[str, Any]] = []
    for f in files:
        head = f.get("head")
        if head is None and f.get("fs_path"):
            try:
                with open(f["fs_path"], "rb") as fh:
                    head = fh.read(HEAD_BYTES)
            except OSError:
                head = b""
        ident = identify(f["path"], int(f.get("size", 0)), head or b"")
        rec = {"path": f["path"], "size": int(f.get("size", 0)), "sha256": f.get("sha256"), **ident, "errors": []}
        fs = Path(f["fs_path"]) if f.get("fs_path") else None
        if ident["type"] == "PDB" and fs:
            meta = pdb_guid_age(fs)
            if meta:
                rec["pdb"] = meta
            else:
                rec["errors"].append({"code": "PARSER_FAILED", "detail": "not a readable MSF 7 PDB (GUID/age unavailable); preserved"})
        if ident["type"] == "PLUGIN_PE" and fs and f.get("want_codeview", True):
            cv = pe_codeview(fs)
            if cv:
                rec["codeview"] = cv
        if ident["type"] == "PLUGIN_ELF" and fs and f.get("want_build_id", True):
            bid = elf_build_id(fs)
            if bid:
                rec["build_id"] = bid
        records.append(rec)
    edges = relationships(records)
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"records": records, "relationships": edges, "counts": counts, "registry_types": len(REGISTRY),
            "rule": "identify → hash → magic/mime → classify → capability match → route; unknown files are UNKNOWN_ARTIFACT records, never dropped; relationships carry a confidence and a basis and never come from file-name similarity alone (ADDENDUM B4)"}


def relationships(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    by_sha: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if r.get("sha256"):
            by_sha.setdefault(r["sha256"], []).append(r)
    for sha, group in by_sha.items():
        for a, b in zip(group, group[1:]):
            edges.append({"kind": "IDENTICAL_BYTES", "a": a["path"], "b": b["path"], "confidence": 1.0, "basis": f"same sha256 {sha[:12]}…"})
    bins = [r for r in records if r["family"] == "compiled_plugin"]
    pdbs = [r for r in records if r["type"] == "PDB"]
    for p in pdbs:
        meta = p.get("pdb")
        for b in bins:
            cv = b.get("codeview")
            if meta and cv:
                same = meta["guid"].replace("-", "") == cv["guid"].replace("-", "") and int(meta["age"]) == int(cv["age"])
                edges.append({"kind": "PDB_MATCHES_BINARY" if same else "PDB_MISMATCH", "a": p["path"], "b": b["path"], "confidence": 1.0 if same else 0.0,
                              "basis": f"CodeView GUID/age {cv['guid']}/{cv['age']} vs PDB {meta['guid']}/{meta['age']}"})
            elif b["type"] == "PLUGIN_PE":
                stem_p = Path(p["path"]).stem.lower()
                stem_b = Path(b["path"]).stem.lower()
                if stem_p and stem_p == stem_b:
                    edges.append({"kind": "PDB_UNVERIFIED", "a": p["path"], "b": b["path"], "confidence": 0.3, "basis": "same file stem only; GUID/age not available on one side — never merged on this alone"})
    for i, a in enumerate(bins):
        for b in bins[i + 1:]:
            if a.get("sha256") and a.get("sha256") == b.get("sha256"):
                continue
            if a.get("build_id") and a.get("build_id") == b.get("build_id"):
                edges.append({"kind": "SAME_BUILD_ID", "a": a["path"], "b": b["path"], "confidence": 0.95, "basis": f"ELF build-id {a['build_id'][:12]}…"})
            elif a.get("codeview") and b.get("codeview") and a["codeview"]["guid"] == b["codeview"]["guid"]:
                edges.append({"kind": "SAME_PDB_GUID", "a": a["path"], "b": b["path"], "confidence": 0.9, "basis": "same CodeView GUID (same link, different bytes: patched or resigned)"})
            else:
                sa, sb = _plugin_stem(a["path"]), _plugin_stem(b["path"])
                if sa and sa == sb:
                    ratio = min(a["size"], b["size"]) / max(1, max(a["size"], b["size"]))
                    edges.append({"kind": "NEAR_RELATED_CANDIDATE", "a": a["path"], "b": b["path"], "confidence": round(0.3 + 0.3 * ratio, 2),
                                  "basis": f"same plugin name, different bytes (size ratio {ratio:.2f}); class / function fingerprints decide in DECOMPILE (lineage), not this edge"})
    return edges


def _plugin_stem(path: str) -> str:
    m = re.search(r"([^\\/]+?)(?:[ _-](?:old|backup|copy|v?\d+(?:\.\d+)*))*\.(vst3|vst|component|dll|dylib|so)", path, re.I)
    return (m.group(1).lower() if m else Path(path).stem.lower())


__all__ = ["REGISTRY", "CAPABILITIES", "KIND_OF", "identify", "route", "relationships", "pdb_guid_age", "pe_codeview", "elf_build_id"]
