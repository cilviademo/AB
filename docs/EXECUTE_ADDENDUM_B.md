# EXECUTE_ADDENDUM_B.md — Post-build hardening pass
### Run after EXECUTE.md Phase 4 is green. Audit, fix, validate, harden. No redesign.

**Operating model for this tool:** the pipeline is artifact-driven; no ownership gate and no ownership assumption. Every artifact gets every technically applicable stage. Two orthogonal metadata fields describe interpretation only: `usage_context` (`USER_RECOVERY` default · `KNOWN_SOURCE_FIXTURE` · `BLACK_BOX_REFERENCE` · `SOURCE_AVAILABLE_REFERENCE` · `UNKNOWN_CONTEXT`) and `source_availability` (`SOURCE_UNKNOWN` · `SOURCE_UNAVAILABLE` · `SOURCE_PARTIAL` · `SOURCE_AVAILABLE` · `KNOWN_SOURCE_GROUND_TRUTH`). Known-source fixture source is withheld from recovery and used only by the evaluator. Licence metadata is stored and displayed, never enforced. Licensing/activation code is a normal subsystem (`LICENSING_AND_ENTITLEMENT_SUBSYSTEM`, Addendum C).

**Three-sentence philosophy:** the owner's plugins are the recovery target; open-source plugins are the answer key; free binaries without source are black-box stress tests.

Outputs required at the end (all under `docs/hardening/`, machine-readable twins under `reports/`):
`POST_BUILD_AUDIT.md` · `BUILD_VALIDATION_REPORT.md` · `ARTIFACT_COMPATIBILITY_MATRIX.md` · `PLUGIN_COMPATIBILITY_MATRIX.md` · `REFERENCE_FIXTURES.md` · `KNOWN_SOURCE_VALIDATION.md` · `PERFORMANCE_REPORT.md`

---

## B1. Audit the initial build (before any new feature)

Inspect the whole repo, not just TODO markers: unimplemented functions, `TODO/FIXME/HACK`, `notImplemented`/`panic`/`throw` placeholders, mocked success, placeholder JSON, fake analysis output, scaffold workers, pass-through DSP, dead UI buttons, disabled/unreachable paths, ignored errors, swallowed exceptions, hard-coded paths or test binaries, placeholder identities, schema mismatches, missing migrations, serialization failures, broken IPC, races, worker lifecycle and cancellation bugs, stale cache, incomplete exports, platform/extension assumptions, unsafe binary execution, missing timeouts, missing crash recovery, missing tests.

`POST_BUILD_AUDIT.md`: severity `BLOCKER | HIGH | MEDIUM | LOW | DEFERRED`; every item has issue, component, reproduction, root cause, fix, and the test that proves the fix. Fix all BLOCKER/HIGH and practical MEDIUM before B4 onward.

## B2. Run the real build matrix

Execute and record actual results (no "appears correct"): Rust check/build/tests/clippy; frontend typecheck/lint/tests; Tauri dev and release builds; CMake configure; C++ workers; `vst3host`; fixture plugins; Ghidra exporter checks; schema tests; SQLite migrations; bundle generation; ZIP export; pluginval and Steinberg validator where installed. → `BUILD_VALIDATION_REPORT.md`.

## B3. No false green states

Every stage has an explicit completion contract; a stage is green only when its contract is met:
`RUNTIME_COMPLETE` = host introspection output validated against schema · `DECOMPILATION_COMPLETE` = decompiler evidence present for ≥ the seeded entry points · `BUILD_COMPLETE` = compiler+linker succeeded and artifact exists · `VALIDATION_COMPLETE` = validator actually executed with parsed results · `BEHAVIOR_MATCHED` = measured comparison with numbers. A missing dependency yields `BLOCKED_DEPENDENCY`, never success. Launching a worker, emitting a file, or generating C++ is not completion.

---

## B4. Universal artifact ingest router

Replace extension-driven ingest with an `ArtifactRouter`: `INGEST → IDENTIFY → HASH → MIME/MAGIC → FORMAT CLASSIFY → CAPABILITY MATCH → ROUTE`, using magic bytes, container structure, extension, MIME, filename and directory context together. Handlers implement `IArtifactHandler { canHandle, inspect, extract, correlate, capabilities }` and register in an **Artifact Capability Registry** (`{artifact_type, capabilities[]}`), so adding a type touches no central switch.

**Input families (recognize, parse where possible, always preserve):** compiled plugins (`.vst3 .dll .vst .component .dylib`, CLAP later) · debug/build evidence (`.pdb .map .dSYM`, DWARF, compiler/linker logs, build dirs) · source (`.cpp .cc .c .h .hpp .mm .m .rs .swift`, CMake, Makefiles, VS/Xcode projects, Projucer) · presets/state (`.vstpreset .fxp .fxb .aupreset`, XML, JSON, INI, plist) · DAW projects (`.RPP .als .flp .cpr` — parse only what is supportable; preserve the rest) · audio (WAV, AIFF, FLAC, OGG, MP3 where a decoder exists) · MIDI · assets (PNG, JPEG, SVG, TTF, OTF, IRs, blobs) · archives (ZIP and other safe formats; recurse through the router; guard against zip bombs, traversal, nesting depth, decompression ratio) · folders (recursive inventory; never execute discovered scripts).

**Unknown files are evidence:** `UNKNOWN_ARTIFACT` records hash, size, name, MIME, magic, origin, container, relationships. Nothing is silently dropped.

**Relationship engine:** infer project membership from hashes, names, build IDs, PDB GUID/age, timestamps, plugin identities, source symbols, referenced filenames, paths, resource hashes; store relationships with confidence; never merge on filename similarity alone.

**Idempotence and duplicates:** a folder drop and per-file drops yield equivalent records (dedupe by hash; never analyze identical bytes twice). `Plugin.vst3 / Plugin_old.vst3 / Plugin_backup.vst3` are classified identical / near-related / different via hashes, class and function fingerprints, resources, identity, lineage.

**Source fragments, PDBs, sessions:** map dropped `.cpp/.h` to RTTI classes and recovered functions with confidence; validate PDB GUID/age against the binary then use it aggressively (file names, functions, classes, lines, types); extract plugin identity, path, parameter state, preset chunks and missing-plugin info from DAW sessions without modifying them.

**Fail gracefully:** `UNSUPPORTED_FORMAT | MALFORMED_BINARY | ARCHIVE_LIMIT_EXCEEDED | PARSER_FAILED | PLUGIN_HOST_CRASH | PLUGIN_TIMEOUT | MISSING_DEPENDENCY` are per-artifact records; the project continues. Large scans cancel and resume from persisted stage results.

---

## B5. Known-source validation system

**Mode `KNOWN_SOURCE_FIXTURE`:** inputs are a source tree + compiled plugin. The recovery side sees the binary only; the evaluator side holds the source. They must not share process memory or file paths during recovery (benchmark integrity, not permission). After recovery, compare: identity, exported parameters (types, defaults, units), state fields, classes, inheritance, methods, DSP modules, resources, source filenames, function relationships, behavioral output → `KNOWN_SOURCE_VALIDATION_REPORT.md` + `known_source_metrics.json`.

**Metrics (never collapsed into one percentage):** identity accuracy · parameter recall/precision · state-field recall · class recall · class-ownership precision · DSP-classification precision · resource recall · source-filename recovery · function-match precision/recall · behavioral error. Every failure is classified `PARSER | CLASSIFICATION | CORRELATION | DECOMPILER | RUNTIME | BEHAVIOR | RECONSTRUCTION | BUILD | VALIDATION | UI`; fix systemic errors before tuning any single fixture. **No fixture-specific cheats** (`if name == "MVerb"`): fixture facts live in manifests, never in recovery logic.

**Fixture manifest:** `{fixture_id, name, source_type, license, license_class, source_repository, source_commit, build_configuration, compiler, binary_sha256, expected{…}}`. Store licence text/reference; classify `PERMISSIVE | COPYLEFT | PROPRIETARY | UNKNOWN` as information only.

**Fixture corpus (heterogeneous by design, so AB is plugin recovery not JUCE recovery):**
- Known-source: DISTRHO **MVerb** and a curated **DPF-Plugins** suite (EQ, delay, reverb, distortion, synth, modulation); **iPlug2** examples; **JUCE** examples where licensing permits; **Cockos WDL**-based examples; **JSFX/EEL2** algorithms (source-form DSP) wrapped into small compiled fixtures so the engine can rediscover known DSP; **chowdsp_wdf** reference algorithms; the hand-written C++ fixture from EXECUTE §1.6.
- Black-box: MeldaProduction **MFreeFXBundle** (free, source not verified as open) for host compatibility, parameter enumeration, resource stress, robustness, crash isolation, performance and behavioral comparison — never labelled known-source. REAPER itself is proprietary and not a fixture; WDL and JSFX are the source-available parts.
- Cover EQ, compressor, clipper, delay, reverb, modulation, resampler.

**Progressive information loss:** for each known-source fixture build debug, release+symbols, and stripped; compare source function → symbol-rich binary → stripped binary → AB recovery. **Cross-compiler/optimization** (MSVC, Clang, GCC; O0/O2/O3) and **cross-version** (multiple commits) fixtures test normalized fingerprints, lineage, near-match and changed-function detection, and cache reuse: unchanged implementation recognized, modified functions isolated.

**Reference comparison as a user action:** "Compare against Reference X" (parameters, signal flow, transfer curves, frequency response, dynamics, latency, oversampling, aliasing, harmonics, state architecture, algorithm-family similarity). Algorithm-family results are `BEHAVIORAL_ALGORITHM_CANDIDATE` with RMSE, harmonic correlation, aliasing delta — never source proof. Reference code is not copied into a user project unless the user explicitly chooses; recovered projects carry the user's reconstruction plus provenance to comparisons.

**Framework detection must distinguish** JUCE, DPF, iPlug2, VST3 SDK, WDL, SoundTouch, chowdsp/WDF, unknown — validated on the fixture corpus.

---

## B6. Reference library and knowledge hardening

`ArtifactBenchData/ { artifactbench.db, objects/, knowledge/, fixtures/ }`; entries typed `USER_ARTIFACT | KNOWN_SOURCE_FIXTURE | BLACK_BOX_REFERENCE | FRAMEWORK_REFERENCE | DSP_REFERENCE`. Promotion stays `CANDIDATE → STATIC_SUPPORTED → RUNTIME_SUPPORTED → BEHAVIOR_MATCHED → IMPLEMENTATION_VERIFIED` (Addendum A). Every knowledge entry records origin, source artifact, licence if external, hash, analysis version, evidence state, verification date, relationships — the user can always answer "where did AB learn this?" External fixture source stays isolated from user recoveries.

**Reference Library UI (restrained):** Known-source fixtures · Black-box references · DSP references · Framework signatures · Shared implementations; per fixture: source/licence, binary hash, build, algorithms, verification status. Actions: *Compare Against Reference*, *Add as Fixture*, *Use as Black-Box Reference*, *Validate Recovery Against Source*. Intent is never assumed from co-dropping two plugins.

**Ground-truth dashboard** (developer-facing): parameter recall 8/8, state mapping 7/8, classes 31/35, DSP entry points 4/4, resources 12/12, implementation matches n verified, false positives n, behavioral RMSE — counts, not one percentage.

---

## B7. Compatibility matrices, robustness, portability

- `PLUGIN_COMPATIBILITY_MATRIX.md`: format × platform × arch × {static parse, runtime host, parameters, state, editor, probe, build, validation}; VST3 Win x64 first; nothing claimed before validated.
- `ARTIFACT_COMPATIBILITY_MATRIX.md`: per input type — recognized, parsed, correlated, used for reconstruction, preserved, tested (YES/PARTIAL/NO).
- Fuzz/adversarial parser tests (no execution): malformed PE, truncated VST3, invalid XML, corrupt PNG, nested archives, duplicate names, huge/Unicode/spaced paths, Windows-reserved names.
- Path portability: spaces, Unicode, long names, other drive letters; no `C:\Users\<dev>` assumptions.
- Fresh-machine test: dependency detection reports `AVAILABLE | MISSING | WRONG_VERSION | UNSUPPORTED` with setup guidance; never crashes.
- Migration tests: schema N → N+1 for projects and knowledge; old evidence never discarded.
- Export round-trip: analyze → export → close → reopen/import → identical state.
- Git checkpoints tested at ingest, static, runtime, decompilation, reconstruction, validation; no noise commits; no GitHub requirement.
- Performance: re-run the 21-plugin corpus against the frozen baseline; the XML-scan pathology must not return; record total, per-stage, peak memory, slowest fixture, cold vs cache-hit → `PERFORMANCE_REPORT.md`.

---

## B8. Acceptance tests (all must pass)

1. **Unseen plugin** — a known-source fixture never used during development: binary only → full pipeline → reveal source → metrics.
2. **Mixed drop** — one folder with VST3, PDB, presets, RPP, WAV, PNG, XML, source fragment, ZIP, unknown file: everything inventoried and routed, relationships created, unknowns preserved, nothing lost, no crash, project exported.
3. **Corpus** — several families dropped together: independent provenance, no contamination, dedupe, lineage, cache reuse, reference matching, corpus report.
4. **Source + binary** — open-source fixture blind recovery, then evaluator comparison with quantitative metrics.
5. **Owner recovery** — the user's own artifact (SP-emulation plugin) re-tested; this remains the product target. Report failures with causes.

## B9. Exit criteria

Clean build; no known blocker; workers real, not stubs; router extensible; mixed input works; unknowns preserved; workers fail safely; jobs resume; cache works; exports round-trip; ≥ 1 known-source fixture validates; ≥ 1 black-box fixture runs; 21-plugin corpus regression passes; an unseen fixture has been tested; reports distinguish failure from success.

**Final principle:** AB accepts evidence, not a perfect input package. One stripped VST3 or a VST3 + PDB + fragments + presets + session + assets + old builds — every artifact contributes what it can. IDENTIFY → PRESERVE → CORRELATE → VERIFY → RECOVER → RECONSTRUCT → VALIDATE → LEARN → EXPORT, becoming more capable with more evidence and never more certain than the evidence justifies. Begin with the audit; do not return with another design document.
