# CLAUDE_CODE_PROMPT.md — Kickoff for the Palimpsest build

Paste this file as the first message in a fresh Claude Code session opened at the root of an empty repo. Everything it references is in the `handoff/` folder shipped beside it.

---

## 0. What you are building

A standalone Windows desktop application that takes an **owned compiled audio plugin** (`.vst3/.dll/.vst`) plus whatever survives around it and returns a **portable, buildable, evidence-backed source project** with a behavioral comparison against the original and a coding-agent handoff. Product statement, hard rules, architecture, UX, security, debugging, data contracts and phases are in **`SPEC.md`**. Ordered build directives with acceptance gates are in **`EXECUTE.md`**. Read both fully before writing code. This file adds the context that lives only in the project history.

Working name: **Palimpsest**. Owner: Marc, Multibanded LLC. Mirror the build pattern of his existing app **Prosody** (FL Studio `.flp` extraction + arrangement): Tauri 2 + React/TypeScript/Vite shell, bundled Python sidecar, CLI kept for diagnostics, distributed as a ZIP containing a single `.exe` that needs no dev tooling, Windows studio PC first. If the Prosody repo is available locally, fork its shell/supervisor/updater/theme; if not, scaffold equivalently and say so.

---

## 1. Files in `handoff/` and what each is for

| Path | Role | How to use it |
|---|---|---|
| `SPEC.md`, `EXECUTE.md`, `EXECUTE_ADDENDUM_A.md` | The contract | Authoritative. Addendum A amends EXECUTE in place (dependency stack, cumulative knowledge base, Git checkpoints, iPlug2 fixture). When this file and SPEC disagree, SPEC wins. |
| `handoff/static-engine/plugin-recovery-bench.v2.html` | **Static Recovery v2 — frozen** | The single-file browser extractor that ran the 21-plugin corpus. The `<script>` block is the reference implementation of the static stage. Port its analysis functions to `app/static-engine/` **without behavioral changes** (EXECUTE §1.4). The UI parts (drop zone, tabs, JSZip bundle writer) are throwaway; the analysis functions are canon. |
| `handoff/kit/vst_recover.py`, `ExportDecompiled.java`, `README.md` | v1 desktop kit | Starting point for `ghidra/ExportDecompiled.java` (upgrade per SPEC §8) and for the Python stage runner. `pedalboard` in the kit was an interim host — replaced by `vst3host.exe` in Phase 2; keep it only as a diagnostic fallback. |
| `handoff/reference/music_reference_corpus_21.zip` | Clean-room candidate DSP library + corpus vocabulary | Unzip to `reference/music_reference_corpus_21/`. 33 reference components (C++17, builds with its own CMake, smoke test passes), `catalog/observed_symbols.json` (657 corpus symbols → candidate families/dependencies), `parameter_state_catalog.json` (946 serialized-key names), `plugin_families.json` (Gen A/B/C hypotheses marked `CORPUS_INFERENCE_NOT_IMPLEMENTATION_PROOF`), `ProbeSignals.h` (deterministic probes for Phase 4). **Never** promote anything from here into `Active/` on a name match. |
| `handoff/reference/MUSIC_REFERENCE_CODEBOOK_21.md` | Same library as one readable document | Load into context when reconstructing a DSP module; contains the full listings and the reference rules. |
| `handoff/docs/PLUGIN_RECOVERY_BENCH.md` | Product page / in-app help | Use as the source for the app's Help screen and README. Its bundle tree (`00_..07_`, `UNRECOVERABLE.md`) is the canonical layout; note it adds `01_evidence/runtime/`, `01_evidence/state/`, `03_architecture/serialized_properties.json`, `state_runtime_map.json`, `signal_flow.json`, `ui_map.json`, `07_agent_handoff/binary_symbol_map.json` — implement these names exactly. |

Regression fixtures (`fixtures/static_v2/`) and the ground-truth plugin (`fixtures/groundtruth/`) are **not** in the handoff; the first is produced by running the v2 engine on the four fixture binaries the owner supplies, the second you build in EXECUTE §1.6.

---

## 2. Project history you must not relearn the hard way

These are bugs the browser tool actually shipped and had to fix. Each is now a rule.

| What went wrong | Rule |
|---|---|
| A regex over bare strings produced **14,246 "parameters"** for one plugin and compiled them into `AudioParameterFloat`s | Parameters come only from XML keys (static) or the runtime host. Bare strings are `CANDIDATE_STRINGS` evidence, nothing more. |
| Preset min/max were emitted as `NormalisableRange`, first preset value as default, all-zero observations as `Bool` | Observed values are `observed_serialized_values`, `value_representation: UNKNOWN`; range/default/type come from `IEditController` + state-differential only. |
| CMake shipped invented `PLUGIN_CODE`/`MANUFACTURER_CODE` while claiming session compatibility | FIDELITY build fails loudly without `VERIFIED_RUNTIME` identity; SURROGATE build is explicit and never session-compatible. |
| 353 stub `.cpp` files, 51 with Windows-illegal names, `IUnknown.cpp` included, all in `target_sources` | Ownership classifier + safe names; scaffolds live in `RecoveredScaffolds/`, only `Active/` compiles. |
| Role classifier matched substrings (`Parameter`→METER, `Queue`→FILTER) | Tokenize CamelCase incl. acronym runs; roles are `CANDIDATE` with `role_basis` until callgraph confirms. |
| BinaryData mapped by declaration order — **proven wrong** by font name tables (4/5 mismatched) | Mapping is content-based only: font `name` table, singleton, or Phase 3 `getNamedResource` decompile. Never order. |
| PNG carve trusted the 8-byte signature and ran to a far IEND (6.6 MB false file); 14 fake JPEGs from `FF D8 FF` in code | Structural parsing only: PNG chunk walk, JFIF/Exif marker check, RIFF length, sfnt table extents, XML balanced parse. `VALID_EXACT` = `PARSER_VALID` + `BOUNDARY_VERIFIED`. |
| A Pro Tools BWF IR (`JUNK`,`bext` before `fmt `) was marked partial | Walk RIFF chunks; never assume `fmt ` at offset 12. |
| TrueType signature `00 01 00 00` matched thousands of times in code and hung the scan | Validate sfnt table directory before any forward scan; cap candidate hits. |
| `arr.push(...hugeArray)` blew the call stack on a 45 MB binary | Never spread large arrays; use `concat`/loops. Applies to Python/TS alike. |
| 600 KB regex windows per `<PARAM` anchor made a 17 MB plugin take 73 s | Structural anchors first, small windows, skip covered ranges, early stop — **and record** `FAST_SCAN_EARLY_TERMINATED` so a deep pass can be triggered (SPEC §6.3). |
| "Original file tree" listed `corecrt_internal_strtox.h` as project source | Paths are classified `PROJECT_SOURCE | FRAMEWORK | SDK | CRT | BUILD_TOOL | BUILD_MACHINE | UNKNOWN`. |
| Licence bucket flagged `rSavedState` as RSA | Word boundaries in every keyword classifier. |

---

## 3. What the 21-plugin corpus established (use as priors, never as facts)

- 455 MB, 21 VST3 binaries, all JUCE, all MSVC linker 14.0, three build batches (2024-05-15, 2024-07, 2025-02). All are **third-party** (a single vendor's catalogue); they are regression fixtures and corpus signatures only — no reconstruction export for them.
- **Three codebase families by class-name-set Jaccard** (INFERRED): Gen A "Studio/Safari" (`StudioChainEffect→StudioNodeEffect→Morph*`, `SafariPlugin`, `ModulationManager`, SoundTouch, `tdps/tuner/pitchcommon`), Gen B "Morph/WDF" (`chowdsp::wdft`, `MorphDiodeClipper`, `MorphBaxendell`, resonators), Gen C "Hammer" (`HammerEffectBase`, `DisotrtionEffect`, `ParametericEQ`, `RotaryKnob` kit). Products are forks: Gorilla Drive contains `TimeMachineAudioProcessor` (Jaccard 0.926, zero unique classes); Silver Llama FX ↔ Twin Panda FX 0.927.
- 88 "plugin-owned" class names recur in ≥ 7 plugins (shared internal symbol family); ~4.2 unique owned names per plugin, mostly LookAndFeel/formatter subclasses. Deep-analysis budget belongs to processBlock-reachable, plugin-specific code.
- Embedded preset XML mixes exported parameters with engine state (`waveShapers_4_2`, `bandBypass1_0_0`, `masterMorph`): 715 keys in one plugin, ~12 real controls. Hence the tier split in SPEC §7.
- `juce::dsp::Oversampling<float>` is JUCE's stock oversampler in 18/21; `SerialScreen`/`isLicensed`/`serial_number_background` is the shared licence subsystem (`PROTECTED_SUBSYSTEM`).
- Shared byte-identical assets: Baumans font, preset-browser icon set, several 4–18 MB knob filmstrips (tall PNGs are `SPRITE_SHEET_CANDIDATE`, not corruption).
- Typos `DisotrtionEffect`, `ParametericEQ` recur → `SYMBOL_LINEAGE_FINGERPRINT`, supporting evidence only.
- Static throughput 1.8 MB/s in-browser overall; the standalone target is ≥ 10 MB/s for the static stage with per-stage instrumentation.

Regression fixtures and why: **Twin Panda FX** (Gen A, SoundTouch, embedded IR, 19 presets), **Rhino Reverb** (Gen B, WDF, fast), **Fox Echo Chorus** (Gen C, 167 state keys, performance stress), **TimeMachine** (47 MB, scale).

---

## 4. Owner context and fixtures

- The owner's genuine recovery target is a **lost-source SP-emulation plugin** (binary and surviving folder to be supplied). It is the Phase 4/5 acceptance fixture — never the thing you debug the engine on.
- The owner also builds his own JUCE plugin line (BTZ); if any BTZ build with source exists, it is a second, richer ground-truth fixture. Ask before assuming.
- Ownership mode is declared per job at ingest and stored in `00_manifest/input_manifest.json`; third-party jobs disable `Active/` generation and reconstruction export.

---

## 5. Session protocol

1. Read `SPEC.md`, `EXECUTE.md`, `EXECUTE_ADDENDUM_A.md`, this file, `handoff/docs/PLUGIN_RECOVERY_BENCH.md`, and skim the `<script>` in `handoff/static-engine/plugin-recovery-bench.v2.html` (functions: `parsePE`, `extractStrings`, `classifyClass`, `classifyPath`, `roleFor`, `carve`, `pngLen/riffLen/fontLen`, `validateResources`, `fontName`, `mapBinaryData`, `extractStateXml`, `scanConstants`, `serializedKeyRecord`, `typeInfo`, `buildCorpus`, `corpusReport`, `withSchema`).
2. Create `CLAUDE.md` at repo root containing: the standing instructions from EXECUTE.md, the evidence vocabulary, the "no invention" rule, the untrusted-plugin rule, the commit format, and a pointer to this file. Keep it under 150 lines.
3. Create `docs/DECISIONS.md` and record every deviation from SPEC with reason.
4. Execute EXECUTE.md top to bottom. After each numbered step, run its gate and paste the gate result into the commit message. Do not proceed on a red gate; fix or record a blocker in `docs/BLOCKERS.md` and ask.
5. Before touching `app/static-engine/`, run `palimpsest-cli diff-baseline`. If baselines don't exist yet, generating them from the four fixtures **is** step 1.4's first task.
6. When a decision needs the owner (product name Palimpsest vs Artifact Bench, VST3 SDK licence choice, Prosody repo path, fixture binaries, SP plugin location, GitHub usage), stop and ask in one message with the options listed.

---

## 6. Definition of done for this engagement

Phase 4 gate green on the ground-truth fixture: the stripped build's waveshaper is recovered end to end — runtime parameter → state field → RTTI/vtable → processBlock path → DSP function → fitted transfer curve → concise C++ in `Active/` → SURROGATE build → pluginval → `BEHAVIORALLY_EQUIVALENT` in the differential harness — with every claim traceable in `07_agent_handoff/reconstruction_index.json`. Then the same path on one module of the owner's SP plugin, reported honestly.
