# ARTIFACT_COMPATIBILITY_MATRIX — Addendum B7 (current state, honest)

Per input type: recognized · parsed · correlated · used for reconstruction · preserved · tested (YES / PARTIAL / NO). "Preserved" is always YES: every dropped byte is stored in the object store and listed in `00_manifest/input_manifest.json` (PRESERVED_UNPARSED when no parser exists).

| input | recognized | parsed | correlated | used for reconstruction | preserved | tested |
|---|---|---|---|---|---|---|
| VST3 bundle / `.dll` / `.so` (PE, ELF) | YES | YES (v2 static + LIEF) | YES (identity, RTTI, resources, state) | YES | YES | YES (fixture, synthetic PE, 21-plugin corpus static) |
| Mach-O plugin | YES (LIEF) | PARTIAL (inventory only) | NO | NO | YES | NO |
| CLAP | NO (listed as `other`) | NO | NO | NO | YES | NO |
| `.pdb` | YES | PARTIAL (attached by prefix; GUID/age not yet validated against the binary) | PARTIAL | NO | YES | PARTIAL (attachment tests) |
| `.map` | YES | NO | NO | NO | YES | NO |
| DWARF (in-binary) | YES (Ghidra) | YES (Ghidra DWARF importer during DECOMPILE) | YES (function names → knowledge) | indirectly (names) | YES | YES (release fixture build) |
| presets (`.vstpreset .fxp .fxb .aupreset`, XML) | YES | PARTIAL (XML/APVTS keys; binary preset containers not decoded) | PARTIAL (state keys) | YES (state model) | YES | PARTIAL |
| DAW sessions (`.RPP .als .flp .cpr`) | YES (kind `session`) | NO | NO | NO | YES | NO |
| source fragments (`.cpp .h …`, CMake, Projucer) | YES (kind `source`) | NO (not mapped to RTTI classes yet) | NO | NO | YES | NO |
| audio (WAV, AIFF, FLAC, OGG, MP3) | YES (WAV carved/validated; others as assets) | PARTIAL | NO | NO | YES | PARTIAL |
| MIDI | NO (`other`) | NO | NO | NO | YES | NO |
| images / fonts (PNG, JPEG, SVG, TTF, OTF) | YES | YES (structural carving, validation) | YES (BinaryData mapping) | YES (Resources/) | YES | YES |
| archives (ZIP) | YES | YES (recursed; traversal guarded) | YES | as contents | YES | YES |
| folders | YES | YES (recursive inventory; scripts never executed) | YES | as contents | YES | YES |
| unknown files | YES (`UNKNOWN`/`other`) | NO | NO | NO | YES (`PRESERVED_UNPARSED`) | YES |

Rows marked NO are the B4 universal-router work items (relationship engine, PDB GUID/age validation, source-fragment ↔ RTTI mapping, DAW session extraction, CLAP, MIDI).
