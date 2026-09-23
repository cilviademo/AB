# ARTIFACT_COMPATIBILITY_MATRIX — Addendum B7 (current state, honest)

Per input type: recognized · parsed · correlated · used for reconstruction · preserved · tested (YES / PARTIAL / NO). "Preserved" is always YES: every dropped byte is stored in the object store and listed in `00_manifest/input_manifest.json` (PRESERVED_UNPARSED when no parser exists).

| input | recognized | parsed | correlated | used for reconstruction | preserved | tested |
|---|---|---|---|---|---|---|
| VST3 bundle / `.dll` / `.so` (PE, ELF) | YES | YES (v2 static + LIEF) | YES (identity, RTTI, resources, state) | YES | YES | YES (fixture, synthetic PE, 21-plugin corpus static) |
| Mach-O plugin | YES (LIEF) | PARTIAL (inventory only) | NO | NO | YES | NO |
| CLAP | YES (router type CLAP, by extension) | NO | NO | NO | YES | YES (router) |
| `.pdb` | YES (MSF 7 magic) | PARTIAL (GUID/age from the PDB info stream; full symbol import pending) | YES (PDB_MATCHES_BINARY / PDB_MISMATCH by CodeView GUID+age; same-stem only → PDB_UNVERIFIED 0.3) | NO | YES | YES (engine/tests/test_router.py) |
| `.map` | YES | NO | NO | NO | YES | YES (router) |
| DWARF (in-binary) | YES (Ghidra) | YES (Ghidra DWARF importer during DECOMPILE) | YES (function names → knowledge) | indirectly (names) | YES | YES (release fixture build) |
| presets (`.vstpreset .fxp .fxb .aupreset`, XML) | YES | PARTIAL (XML/APVTS keys; binary preset containers not decoded) | PARTIAL (state keys) | YES (state model) | YES | PARTIAL |
| DAW sessions (`.RPP .als .flp .cpr`) | YES (magic: <REAPER_PROJECT, gzip+als, FLhd, RIFF/NUND) | NO (extraction pending) | NO | NO | YES | YES (router) |
| source fragments (`.cpp .h …`, CMake, Projucer) | YES (kind `source`) | NO (not mapped to RTTI classes yet) | NO | NO | YES | NO |
| audio (WAV, AIFF, FLAC, OGG, MP3) | YES (RIFF/WAVE, FORM/AIFF, fLaC, OggS, ID3 magic) | PARTIAL (WAV/AIFF walked) | NO | NO | YES | YES (router) |
| MIDI | YES (MThd) | NO | NO | NO | YES | YES (router) |
| images / fonts (PNG, JPEG, SVG, TTF, OTF) | YES | YES (structural carving, validation) | YES (BinaryData mapping) | YES (Resources/) | YES | YES |
| archives (ZIP) | YES | YES (recursed; traversal guarded) | YES | as contents | YES | YES |
| folders | YES | YES (recursive inventory; scripts never executed) | YES | as contents | YES | YES |
| unknown files | YES (`UNKNOWN_ARTIFACT` record: hash, size, name, mime, magic, evidence) | NO | NO | NO | YES | YES (router) |

The router (`ab_engine.ingest.router`, `ab-cli route <paths>`, `00_manifest/artifact_routes.json`) identifies every type above from magic + container + extension + directory context and records relationships with confidence (identical bytes, PDB↔binary by GUID/age, ELF build-id, near-related candidates). Remaining NO cells are parsers, not recognition: source-fragment ↔ RTTI mapping, DAW session extraction, full PDB symbol import, CLAP/AU hosting.
