# DEPENDENCIES — adopted stack (EXECUTE_ADDENDUM_A §A1)

Every dependency sits behind a small internal interface so it can be swapped; `ab-cli doctor`
reports each with its installed version, licence and pinned hash (`dep:*` and `tool:*` rows).
Nothing is imported ad hoc: Python libraries go through `ab_engine.deps`, tools through
`ab_engine.tools`, downloads through `tools/manifest.json` (sha256-pinned, no auto-update).

| Need | Adopted | Version (pinned) | Licence | sha256 of the pinned artifact | Interface / slot |
|---|---|---|---|---|---|
| PE/ELF/Mach-O/PDB inventory | LIEF | 1.0.0 | Apache-2.0 | `96277e45…bd06f` (`lief-1.0.0-cp311-manylinux_2_28_x86_64.whl`) | `ab_engine.inventory.lief_inventory` — `01_evidence/binary/inventory.json` beside the frozen v2 record, with a `v2_pe_crosscheck` (D-021) |
| Lightweight disassembly + fingerprints | Capstone | 5.0.9 | BSD-3-Clause | `273fd8d7…193e` | `ab_engine.fingerprint` (A3) — signatures before Ghidra |
| Deep RE / decompile / RTTI / callgraph | Ghidra headless | 11.3.2 | Apache-2.0 | `99d45035…dac2` (tools/manifest.json) | `ab_engine.decompile` — automated, never replaced |
| Ghidra runtime | Eclipse Temurin JDK | 21.0.8+9 | GPLv2+CE | per platform in tools/manifest.json | `ab_engine.tools.find_jdk` |
| VST3 runtime host | Steinberg VST3 SDK hosting classes | v3.7.9_build_61 | MIT (hosting classes; BLOCKERS B-002 for distribution) | git tag, cloned at build time, never vendored | `native/vst3host` |
| Second validation source | VST3 SDK `validator` (sample host) | from the same SDK | MIT | built from the pinned SDK (`target validator`) | `ab_engine.runtime.validator` → `01_evidence/vst3/validator.json` |
| Plugin validation | pluginval | 1.0.4 | GPLv3 — external executable only, never linked or copied | per platform in tools/manifest.json | `ab_engine.build.run_pluginval` |
| Knowledge index / job db | SQLite | Python stdlib | public domain | — | `ab_engine.jobs.db`, `ab_engine.lineage.knowledge` (A2) |
| Exact identity | SHA-256 | hashlib | — | — | everywhere |
| Approximate similarity | TLSH (py-tlsh) | 5.0.0 (optional extra `similarity`) | Apache-2.0 / BSD-3 | `a21cb75e…ad1b` (sdist) | `ab_engine.fingerprint` — a relatedness signal, never identity |
| Family / pattern recognition | YARA (yara-python) | 4.5.4 | BSD-3-Clause | `1a1721b6…8f3` | `ab_engine.lineage.rules` (A4) — emits CANDIDATE_FAMILY only |
| Rebuild framework | JUCE | 8.0.9 | AGPLv3 / commercial (owner's licence) | per platform in tools/manifest.json | `ab_engine.build` |
| Contract validation | jsonschema | ≥ 4.20 | MIT | — | `ab_engine.contracts` |
| Numerics | numpy | ≥ 1.26 | BSD-3-Clause | — | behaviour, fits, harness |
| WDF reference algorithms | chowdsp_wdf | not yet added | BSD-3 | — | `reference/` (Gen-B candidates) — planned, not required for the fixture |
| Resampling reference | libsamplerate | not yet added | BSD-2 | — | `reference/` / probe harness — planned |
| Audio I/O in workers | own WAV writer (`native/vst3host/src/wav.h`) | — | — | — | miniaudio/libsndfile not needed yet; revisit if compressed formats appear |
| Secondary RE backend | Rizin | deferred (Phase 5+) | LGPL-3 | — | only when Ghidra fails or for corroboration |
| Advanced dataflow | angr | deferred (after the one-module proof) | BSD-2 | — | — |
| Second fixture framework | iPlug2 | A5 | zlib-like | — | `fixtures/groundtruth_iplug2` |

Cost ordering (A1): LIEF → Capstone fingerprints → knowledge cache → Ghidra only on the residual →
runtime host → probes → reference candidate → compile → pluginval + SDK validator → differential →
knowledge promotion. The expensive tool never runs first.
