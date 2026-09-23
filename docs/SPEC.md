# ARTIFACT BENCH (AB) — Artifact Recovery Workbench
### SPEC.md · v1.0 · standalone Windows app (Prosody-pattern)

> Product name: **Artifact Bench**, abbreviated **AB** in code, docs and logs. Recovery by evidence, never by guessing.

---

## 0. Product statement

**Input:** a compiled plugin (`.vst3` / `.dll` / `.vst`) — the user's own lost-source plugin is the product target; the same pipeline runs on any artifact (rule 9) — plus whatever survives around it (presets, DAW sessions, old builds, resources, partial source, `.pdb`).
**Output:** a portable, Git-ready, buildable source project with statement-level provenance, a behavioral comparison against the original, and a coding-agent handoff — such that a human or agent can continue the product without restarting from zero.

**Success chain (the only definition of "done"):**

```
COMPILED PLUGIN → VERIFIED RUNTIME FACTS → VERIFIED ARCHITECTURE → TARGET DSP LOCATED
→ DSP RECONSTRUCTED → PROJECT BUILDS → VST3 LOADS → STATE/PARAMETERS FUNCTION
→ ORIGINAL AND REBUILD COMPARED → BEHAVIORAL MATCH MEASURED → PORTABLE SOURCE PROJECT EXPORTED
```

**Milestone that gates everything else:** ONE MODULE END TO END on the ground-truth fixture (§12), then on the owned SP-emulation plugin.

**Non-goals:** literal original source recovery; licence bypass; whole-corpus batch reconstruction before the one-module proof passes.

---

## 1. Hard rules (apply everywhere, every stage, every file)

1. **Evidence vocabulary is mandatory.** Every recovered/generated item carries one of `VERIFIED` · `INFERRED` · `CANDIDATE` · `GENERATED` · `UNRECOVERABLE`, and where validated one of `BIT_EXACT` · `NUMERICALLY_EQUIVALENT` · `BEHAVIORALLY_EQUIVALENT` · `PERCEPTUALLY_CLOSE` · `SCAFFOLD_ONLY` · `FAILED`. "Exact" is used only for bytes/values read directly from an authoritative artifact or runtime API.
2. **No invention.** Never fabricate parameters, ranges, defaults, FUIDs, plugin/manufacturer codes, class names, file paths, build settings, DSP algorithms, or licensing logic. Unknown stays `UNKNOWN`.
3. **Provenance on everything important:** source artifact + hash, address/offset, extraction method, supporting evidence, evidence state, related entities.
4. **Family evidence ≠ implementation evidence.** Name recurrence, Jaccard, build dates, shared resource hashes establish lineage only. Implementation reuse requires function/vtable fingerprints (§8). States: `SHARED_NAME` → `SHARED_ARCHITECTURE_CANDIDATE` → `SHARED_IMPLEMENTATION_CANDIDATE` → `SHARED_IMPLEMENTATION_VERIFIED`.
5. **Runtime is authoritative for parameters.** Static XML proves a serialized key exists; only `vst3host` may create an `EXPORTED_VST_PARAMETER`. Indexed names (`waveShapers_4_2`) are `STATE_FIELD_CANDIDATE`, never an exclusion.
6. **Cache never poisons.** A known-library match is downgraded and re-analysed if any fingerprint, vtable shape, constant, parameter reference, or behavior disagrees. "We already know `MorphCompressor`" by name is forbidden.
7. **Evidence is immutable.** `01_evidence/` is written once per stage and never edited by later stages.
8. **Scaffolds never enter `Active/`.** Evidence gates in §10 decide promotion.
9. **Artifact-driven recovery, no ownership gate.** AB exposes the same pipeline (static, runtime, decompile, fingerprint, probe, reconstruct, transform, compare, export) to every artifact based on technical capability. AB makes no ownership or legal determination and does not assume one. Two orthogonal metadata fields describe how results are *interpreted*, never what may *run*: `usage_context` = `USER_RECOVERY` (default) · `KNOWN_SOURCE_FIXTURE` · `BLACK_BOX_REFERENCE` · `SOURCE_AVAILABLE_REFERENCE` · `UNKNOWN_CONTEXT`; and `source_availability` = `SOURCE_UNKNOWN` · `SOURCE_UNAVAILABLE` · `SOURCE_PARTIAL` · `SOURCE_AVAILABLE` · `KNOWN_SOURCE_GROUND_TRUTH`. Reports therefore say "binary-derived reconstruction" or "validated against known source" and never confuse the two. Licence text/metadata for external references is stored and shown (`PERMISSIVE | COPYLEFT | PROPRIETARY | UNKNOWN`), never used to block. Licensing, activation, entitlement, registration, demo-state and authentication code is classified `LICENSING_AND_ENTITLEMENT_SUBSYSTEM` (the frozen static engine's `PROTECTED_SUBSYSTEM` label aliases to it) and is recovered, reconstructed, transformed and validated under the **same** evidence discipline as DSP, state, UI and build code. Reconstruction preserves supported original behavior; silently replacing validation logic with unconditional success is a behavioral modification and must be recorded as a transformation, never presented as recovery. Reference evidence stays reference evidence: reconstructed third-party licensing is never auto-exported into a user project.
10. **Performance optimizations must record completeness.** Every fast path emits `FAST_SCAN_COMPLETE` / `FAST_SCAN_EARLY_TERMINATED` / `DEEP_SCAN_COMPLETE` / `SCAN_INCOMPLETE`; a deep pass is available on demand and auto-triggered on inconsistency (§6.3).

---

## 2. Platform (mirror Prosody)

| Layer | Choice | Notes |
|---|---|---|
| Shell | **Tauri 2 + React 18 + TypeScript + Vite** | Same scaffold, packaging, updater pattern as Prosody |
| Static engine | TypeScript, ported verbatim from Static Recovery v2 | Runs in a Web Worker inside the webview; frozen behavior, versioned |
| Orchestrator / analysis | **Python 3.11** sidecar (bundled, no system Python) | Job system, fingerprints, fits, reports, bundle assembly |
| Native host | **`vst3host.exe`** — C++17 on Steinberg VST3 SDK hosting classes | Separate process, JSON over stdio, hard timeout |
| Decompiler | **Ghidra** headless + JDK 21 | Downloaded on first use into `%LOCALAPPDATA%\ArtifactBench\tools\` |
| Validation | **pluginval**, CMake + MSVC Build Tools (optional) | Detected, not required; build stage degrades gracefully |
| Distribution | ZIP → `ArtifactBench.exe`, no dev tooling required | Later: installer, auto-update |
| CLI | `ab-cli` (Python) kept for diagnostics and CI | Every GUI action has a CLI equivalent |

**Licensing note (decide before distribution):** VST3 SDK hosting code is GPLv3 or Steinberg proprietary. Internal Multibanded use is fine under either; distribution requires choosing.

---

## 3. Repository layout

```
artifact-bench/
├── app/                      # Tauri + React (Prosody shell fork)
│   ├── src/                  # screens, evidence viewer, job monitor
│   ├── src-tauri/            # Rust: process supervision, IPC, fs sandbox
│   └── static-engine/        # Static Recovery v2 port (TS), versioned
├── engine/                   # Python sidecar
│   ├── jobs/                 # stages, resume, cache
│   ├── contracts/            # JSON schemas (recovery.*, v2+)
│   ├── fingerprint/          # function/class/resource fingerprints
│   ├── lineage/              # family clustering, known-library cache
│   ├── behavior/             # probes, fits, differential
│   ├── reconstruct/          # evidence_source / recovered_source / transformed_source generators, gates
│   └── bundle/               # 00_..07_ writers, GIT_READY checks
├── native/vst3host/          # C++ host (introspect, state, render)
├── ghidra/                   # ExportRTTI.java, ExportCallgraph.java, Fingerprint.java
├── reference/music_reference_corpus_21/   # clean-room candidate algorithms (§9)
├── fixtures/
│   ├── groundtruth/          # §12 test plugin: source + Debug/Release/stripped builds
│   └── static_v2/            # frozen corpus baselines (§13)
├── tools/                    # first-run downloader manifests (JDK, Ghidra, pluginval)
└── docs/                     # SPEC.md, EXECUTE.md, ARCHITECTURE.md, HANDOFF templates
```

---

## 4. Process architecture

```
ArtifactBench.exe (Tauri GUI, never touches a plugin binary directly)
 ├─ static worker      (webview Web Worker; TS)            → 01_evidence/{binary,rtti,strings,paths,resources,presets}
 ├─ engine sidecar     (Python; supervised by Rust)         → jobs, cache, correlation, reports, bundles
 │    ├─ vst3host.exe  (C++; per call, timeout 60 s)        → 01_evidence/vst3/*, 05_reference_behavior/*
 │    ├─ ghidra        (Java; background, resumable)        → 01_evidence/decompiler/*, fingerprints
 │    ├─ build worker  (cmake/msbuild; optional)            → 06_validation/compile.log
 │    └─ pluginval     (optional)                           → 06_validation/pluginval.log
 └─ IPC: versioned JSON lines; every worker exit code, stdout, stderr, timeout and crash dump path are captured
```

- A worker crash or timeout fails **its stage only**; earlier stage outputs stay valid.
- Workers run with: temp working dir, sanitized environment (no tokens/keys), no network except the tool downloader, CPU/RAM limits where the OS allows, and `vst3host.exe` additionally under a Job Object so orphaned plugin threads die with it.
- Bounded concurrency: static scans up to `min(4, cores/2)`; exactly one Ghidra job; exactly one `vst3host` instance per plugin at a time.

---

## 5. Job system and cache

**Stages (per plugin):**
`INGESTED → STATIC_COMPLETE → RUNTIME_COMPLETE → DECOMPILATION_COMPLETE → BEHAVIOR_COMPLETE → RECONSTRUCTION_COMPLETE → BUILD_COMPLETE → VALIDATION_COMPLETE → EXPORT_COMPLETE`

Each stage record: `input_hashes[]`, `tool_versions{}`, `config_hash`, `started/ended`, `status` (`PENDING|RUNNING|OK|FAILED|SKIPPED`), `warnings[]`, `outputs[]`, `completeness` (§1.10).

**Cache key:** `sha256(artifact) + tool_version + stage_version + config_hash`. Changing the reconstruction generator must not re-carve resources; changing the Ghidra exporter invalidates only `DECOMPILATION_COMPLETE` and downstream.

**Storage:** SQLite (`jobs.db`) for stage state + content-addressed object store (`objects/<sha256>`) for artifacts and carved bytes. Per-plugin evidence folders reference objects; single-project export materializes real files.

---

## 6. Static stage (Static Recovery v2, frozen)

**6.1 Port rules.** The TS engine is moved unchanged except: no DOM, no clipboard, no zip; outputs go to the engine via IPC. All v2 contracts (`schema_version: 2`) are preserved: `binary.json`, `rtti/classes.json`, `paths/build_path_evidence.json`, `resources/index.json`, `resources/binarydata_map.json`, `presets/*.xml`, `03_architecture/serialized_keys.json`, `classes.json`, `07_agent_handoff/reconstruction_index.json`, `corpus/shared_class_names.json`, `corpus/performance.json`.

**6.2 Terminology carried in:** serialized keys (not parameters), `observed_serialized_values` with `value_representation: UNKNOWN`, `SHARED_SYMBOL_FAMILY`, `class_name_set_jaccard`, DSP-relevant constant *candidates*, `SPRITE_SHEET_CANDIDATE`, `BOUNDARY_VALID_SEMANTICS_UNKNOWN`.

**6.3 Deep scan.** The fast XML/doc scan is default. `DEEP_SCAN` (exhaustive anchors, no early stop, full-file window) runs when: the fast scan reports `EARLY_TERMINATED`; BinaryData names outnumber carved assets of a type; state references keys not found in any carved document; the user selects Forensic mode; or validation later reports a missing resource.

**6.4 Stage instrumentation.** Per stage: `elapsed_ms`, `bytes_processed`, `objects_found`, `peak_rss_mb`. Corpus/performance reports median, p90, p95, max, MB/s per stage and list outliers (> 3× median) with dominant stage.

---

## 7. Runtime stage — `vst3host.exe`

**Commands (JSON in → JSON out, one per invocation, 60 s timeout, non-zero exit on any plugin fault):**

| command | output | notes |
|---|---|---|
| `factory` | vendor, url, email, flags, classes[{name, cid/FUID, category, subcategories, version, sdk}] | `VERIFIED_RUNTIME` identity |
| `parameters` | for each: `param_id, title, short_title, units, step_count, default_normalized, flags, unit_id`, plus `normalized→string` samples at 0, .25, .5, .75, 1 and `string→normalized` round-trips where supported | writes `vst3/runtime_parameters.json` |
| `units` | IUnitInfo units, parent ids, program lists, program names | |
| `buses` | audio/event buses, arrangements, default activation | replaces bus placeholders |
| `info` | latency, tail (`getTailSamples`), editor availability, editor initial size, process context requirements | |
| `state` | `getState`/`getControllerState` blobs (base64) at current values | |
| `setparam` + `state` | one parameter changed → new state blob | drives the state-differential harness |
| `render` | probe rendering (§11) at given sample rate/block size/parameter snapshot | writes WAV + metrics |

**Correlation (engine):** `state/serialized_properties.json` (static keys) × `vst3/runtime_parameters.json` → `state_runtime_map.json` with relationship `SAME_ID | MAPPED | STATE_ONLY | RUNTIME_ONLY | UNKNOWN`, and `value_representation` resolved to `NORMALIZED | PLAIN | ENUM | BOOLEAN | OTHER` from the differential harness (change one param, diff serialized state, locate the field, compare value forms).

**Parameter tiers (final):** `VST3_EXPORTED_PARAMETER` · `STATE_SCHEMA_FIELD` · `UI_ONLY_CONTROL` · `UNKNOWN_PROPERTY`. Static `STATE_FIELD_CANDIDATE` is a hint that the host may overrule.

---

## 8. Decompiler stage — Ghidra

**Scripts:** `ExportRTTI.java` (run Ghidra's MSVC RTTI analyzer; export TypeDescriptor, CompleteObjectLocator, ClassHierarchyDescriptor, BaseClassDescriptor, vftables → `rtti/classes_verified.json` with inheritance, vtable address, slot count, ctor/dtor candidates), `ExportCallgraph.java` (seed from `GetPluginFactory` → JUCE VST3 wrapper → `AudioProcessor` vtable slots for `prepareToPlay/processBlock/releaseResources/get/setStateInformation/createEditor`; export callgraph with distance-from-processBlock), `Fingerprint.java` (§8.1), `ExportDecompiled.java` (v1 script, upgraded: noise suppression, wrapper collapse, per-class files under `01_evidence/decompiler/classes/`, never under `reconstruction/`).

**8.1 Function fingerprints (stored separately, never merged):**
`RAW_BYTE_HASH` · `NORMALIZED_INSTRUCTION_HASH` (operands masked: relocations, absolute addresses, stack offsets normalized) · `CFG_SIGNATURE` (basic-block count, edge shape hash) · `CALLGRAPH_SIGNATURE` (callee fingerprint multiset, depth 1) · `CONSTANT_SIGNATURE` (sorted float/int immediates) · `STRING_XREF_SIGNATURE` · `RTTI_XREF` · `VTABLE_SLOT` (class, index).
Class fingerprint = RTTI name + vtable slot fingerprints + ctor/dtor fingerprints + member-offset access pattern.

**8.2 Function role scoring:** distance from `processBlock`, float/SIMD density, buffer/channel loops, sample-rate refs, DSP constant refs, libm calls, parameter reads, delay-line/FFT patterns. Classes: `AUDIO_LOOP, GAIN, WAVESHAPER, FILTER, FILTER_COEFFICIENT, OVERSAMPLER, COMPRESSOR, LIMITER, GATE, DELAY, REVERB, CONVOLUTION, METER, PARAMETER_UPDATE, STATE, GUI, RESOURCE, FRAMEWORK, RUNTIME, LICENSING_AND_ENTITLEMENT_SUBSYSTEM, UNKNOWN`, each with `role_status: CANDIDATE|VERIFIED_CALLGRAPH` and `role_basis[]`.

**8.3 Noise suppression / wrapper collapse:** CRT init, security cookies, allocators, EH machinery, refcounting, JUCE plumbing, RTTI helpers, import thunks, destructor thunks, forward-only wrappers are hidden from human output; addresses retained in provenance.

**8.4 BinaryData resolution:** locate `namedResourceList`, `originalFilenames`, `getNamedResource` → name → pointer → size → bytes → SHA-256 → match carved asset → `mapping_status: VERIFIED`; rename in `02_recovered_assets/` only then.

**8.5 Known-library cache (`knowledge/`):** entries keyed by normalized fingerprint tuples, never by name. Entry: `schema_version, tool_version, source_artifact_hashes[], compiler_fingerprint, state (KNOWN_FRAMEWORK|KNOWN_THIRD_PARTY|KNOWN_SHARED_INTERNAL|KNOWN_PLUGIN_SPECIFIC|UNKNOWN), function_fingerprints[], class_fingerprints[], last_verification`. Matching suppresses deep work on `KNOWN_FRAMEWORK/THIRD_PARTY` and reuses classifications for `KNOWN_SHARED_INTERNAL` — subject to §1.6.

**8.6 Priority = processBlock-reachable × plugin-specific × has verified parameter/state relationship × DSP evidence × not matched to a verified known implementation.**

---

## 9. Lineage / corpus mode

Separate screen ("Library"), never mixed into per-plugin evidence.

- Keeps v2 `CLASS_NAME_GRAPH_CLUSTER` (connected components at Jaccard ≥ 0.5) labelled **INFERRED** and adds average-link and medoid similarity, anchor-class analysis, and — once available — fingerprint, resource-hash and state-schema similarities. Family membership is `INFERRED` until fingerprints reinforce it.
- `SYMBOL_LINEAGE_FINGERPRINT`: recurring uncommon spellings (`DisotrtionEffect`, `ParametericEQ`) recorded as supporting evidence only.
- Outputs `LINEAGE_REPORT.md` per plugin: family (INFERRED), verified shared implementation matches (functions/classes), near matches, unique functions/resources/state fields, deep-analysis priority list.
- `reference/music_reference_corpus_21/` is a **clean-room candidate library**: `catalog/observed_symbols.json` suggests candidate algorithm families per symbol and external dependencies; `parameter_state_catalog.json` is state-schema vocabulary only. No mapping is proof; nothing from `reference/` enters `Active/` on name matching alone — only after behavioral validation against the original (§11).

---

## 10. Reconstruction model and evidence gates

```
04_reconstruction/
  evidence_source/     close to decompiler semantics; uncertain fields kept; auditable
  recovered_source/    closest semantic reconstruction of the ORIGINAL (formerly human_source/)
  transformed_source/  modernized / migrated / ported implementation chosen by the recovery goal
  Source/Active/       the implementation currently being built (recovered or transformed, per goal)
  Source/RecoveredScaffolds/   credible architecture, not compiled
  CMakeLists.txt       FIDELITY (needs VERIFIED_RUNTIME identity) | SURROGATE (temporary identity, never session-compatible)
```
Transformation status per module: `RECOVERED_EXACT · RECONSTRUCTED · MODERNIZED_EQUIVALENT · TRANSFORMED_COMPATIBLE · TRANSFORMED_WITH_MIGRATION · TRANSFORMED_BREAKING · UNRECOVERABLE`. `ORIGINAL_BEHAVIOR`, `RECOVERED_BEHAVIOR` and `TRANSFORMED_BEHAVIOR` are stored separately; comparisons run ORIGINAL↔RECOVERED, RECOVERED↔TRANSFORMED and ORIGINAL↔TRANSFORMED. See EXECUTE_ADDENDUM_C.

| Artifact | Gate to generate as production source |
|---|---|
| Parameter layout | `VST3_EXPORTED_PARAMETER` set is `VERIFIED_RUNTIME` |
| DSP class body in `Active/` | `STATIC_RECONSTRUCTED` **or** `BEHAVIOR_MATCHED` |
| Identity in FIDELITY build | `VERIFIED_RUNTIME` factory identity |
| State compatibility claim | `CROSS_LOAD_VALIDATED` (original→rebuild and rebuild→original) |
| Promotion scaffold → Active | `BEHAVIOR_MATCHED` at ≥ `BEHAVIORALLY_EQUIVALENT` |

Statement-level provenance is stored in `07_agent_handoff/reconstruction_index.json` (symbol, file, status, binary addresses, evidence[], parameters[], validation, rmse, todos) with optional light in-source tags (`// VERIFIED_RTTI`, `// BEHAVIOR_MATCHED 0.9998`, `// INFERRED`). The simplifier may rename, collapse, extract helpers, and replace equivalents; any operation absent from static or behavioral evidence is marked `INFERRED`.

---

## 11. Behavioral stage

Probes (from `reference/.../ProbeSignals.h`, deterministic seeds): silence, impulse, DC, amplitude ramp −4..+4, sine 1 kHz, sine amplitude sweep, log frequency sweep 20 Hz–20 kHz, white noise, pink noise, two-tone IMD (19/20 kHz). Sample rates 44.1/48/96 kHz; block sizes 32…1024. One parameter varied at a time from the verified default.
Captured: audio, latency (measured vs reported), tail, peak, RMS, frequency/phase response, harmonics, THD, aliasing energy, transfer curve.
Nonlinear fitting: hard clip, tanh, atan, cubic, higher-order polynomial, piecewise polynomial, rational, LUT → RMSE, max error, correlation; model chosen by residual, never by name.
Differential harness: original vs rebuild on identical probes/state → classification per module (§1) with sample-level error, RMSE, spectral diff, latency diff.

---

## 12. Ground-truth fixture (built first, before any owned binary)

`fixtures/groundtruth/` — a small JUCE plugin **with source**: 5–8 parameters (one bool, one enum, one gain, one filter cutoff, one drive), one TPT filter, one `tanh` waveshaper, oversampling toggle (JUCE `dsp::Oversampling`), APVTS state, one PNG, one TTF, one preset XML, a deliberate `LICENSING_AND_ENTITLEMENT_SUBSYSTEM` stub (serial check + demo state) so licensing recovery is measured too. Built three ways: Debug+PDB, Release+PDB, Release stripped. The stripped build is the recovery input; the source is the answer key.

`GROUND_TRUTH_REPORT.json` metrics: identity correct; param IDs/types/defaults/units recovered; state fields mapped; RTTI classes recovered; ownership accuracy; processBlock path accuracy; DSP-function identification accuracy; resource recovery accuracy; fingerprint stability across the three builds; false positives; false negatives. This report is the CI gate for Phases 1–4.

---

## 13. Regression baselines

`fixtures/static_v2/` stores the v2 corpus outputs for Twin Panda FX (Gen A/SoundTouch/IR), Rhino Reverb (Gen B/WDF), Fox Echo Chorus (Gen C/perf stress), TimeMachine (scale). Any static-engine change must show a diff against these before merge: no new false positives, no state keys reinterpreted as parameters, no lost resources, no evidence-status changes, no perf regression > 20%, no illegal paths.

---

## 14. UX / UI

**Principle:** the user sees milestones, not forensics. One primary button.

**Screens**
1. **Recover** — drop zone (`.vst3/.dll/.vst`, presets, folders, zips), optional context tags (`usage_context`, `source_availability`; defaults `USER_RECOVERY` / `SOURCE_UNKNOWN`), recovery goal (`PRESERVE ORIGINAL` default · `MODERNIZE` · `MIGRATE` · `REFACTOR` · `PORT` · `REBUILD`), big **RECOVER PROJECT**. Stage rail: `STATIC · RUNTIME · DECOMPILE · PROBE · RECONSTRUCT · BUILD · COMPARE · EXPORT`, each with status chip, elapsed time, and a "details" drawer (logs, warnings, completeness flags).
2. **Scorecard** — the v2 scorecard extended: Identity, Runtime parameters, State schema, UI assets, Class architecture, Signal flow, DSP structure, DSP numerical match, Source symbols, Original source (always 0%). Each score opens the underlying evidence; every count carries its evidence state in the label.
3. **Evidence browser** — tree over `00_..07_`, JSON viewer with schema badge, resource gallery (sprite sheets rendered as frame strips), decompiled function viewer with role/priority, fingerprint matches.
4. **Reconstruction** — module list with status (`SCAFFOLD_ONLY → STATIC_RECONSTRUCTED → BEHAVIOR_MATCHED → ACTIVE`), residual plots (transfer curve, spectrum, error), promote/demote actions gated by §10.
5. **Library** — corpus/lineage: families (INFERRED), known-library cache entries, similarity views, `LINEAGE_REPORT.md`.
6. **Export** — bundle preview, `GIT_READY` checklist (legal filenames, no secrets, no machine paths, deps documented, `.gitignore`, build instructions, provenance manifest, no bundled SDK, configure/build passed, validation passed), actions: *Export folder*, *Export ZIP*, *Agent handoff*, *Open in VS Code*, *Push to GitHub* (optional, never required).

**Final screen (target):**
```
RECOVERY COMPLETE
Project buildable       YES          VST3 validated        YES
Parameters recovered    14 / 14      State fields mapped   14 / 14
Resources recovered     31 / 33      Plugin-owned classes  18
DSP modules             5 / 7 reconstructed · 4 validated · 1 scaffold · 2 need review
Behavioral comparison   99.2%
[ Open Project ] [ Export ZIP ] [ Agent Handoff ] [ Evidence ] [ Validation Report ]
```

**Visual language:** reuse Prosody's shell theme; evidence states get fixed colors (VERIFIED green, INFERRED amber, CANDIDATE grey, GENERATED blue, UNRECOVERABLE red-strike) used identically in UI, reports and file badges. Dark/light follow OS. Keyboard-first; every long operation cancellable; no modal spinners.

---

## 15. Security

- Plugins are untrusted code: loaded only inside `vst3host.exe` (Job Object, timeout, temp dir, scrubbed env, no network). GUI and engine never `LoadLibrary` a plugin.
- Downloaded tools (JDK, Ghidra, pluginval) verified by pinned SHA-256 in `tools/manifest.json`; no auto-update of tools without manifest change.
- Secrets never enter worker environments or bundles; export scanner blocks tokens, keys, absolute user paths.
- All IPC JSON validated against schemas; unknown major `schema_version` rejected.
- Ghidra runs with its own user dir under the app data folder; no scripts loaded outside `ghidra/`.
- `LICENSING_AND_ENTITLEMENT_SUBSYSTEM` code follows the same recovery/transformation path as everything else; every behavioral change to it (e.g. replacing an activation backend) is recorded in the transformation graph, and bypass-style edits (`validate → true`) are flagged `TRANSFORMED_BREAKING`, never labelled recovered.
- `usage_context` and `source_availability` are stored in `00_manifest/input_manifest.json`; neither disables a capability. Known-source fixture source is isolated from recovery stages (benchmark integrity, not permission) and reference code is never copied into a user project unless the user explicitly chooses to incorporate it.

---

## 16. Debugging and observability

- Structured logs (JSONL) per job and per worker in `%LOCALAPPDATA%\ArtifactBench\logs\<job>\`; GUI "Copy diagnostics" bundles logs + `performance.json` + tool versions with secrets scrubbed.
- Every stage writes `stage.json` (status, timings, warnings, completeness) before and after; partial outputs are never left unmarked.
- `ab-cli doctor` checks tools, versions, disk, sandbox; `ab-cli run --stage static <file>` reproduces any stage headlessly; `ab-cli diff-baseline` runs §13.
- Crash dumps from `vst3host.exe` collected via WER local dumps; Ghidra stdout/stderr captured with a tail visible in the stage drawer.
- Feature flags for deep scan, fingerprint variants, and reference-corpus suggestions.

---

## 17. Data contracts (all `{schema, schema_version, tool, generated, data}`)

`recovery.binary` · `recovery.classes` (rtti) · `recovery.classes_verified` · `recovery.build_path_evidence` · `recovery.index` (resources) · `recovery.binarydata_map` · `recovery.serialized_keys` · `recovery.runtime_parameters` · `recovery.state_runtime_map` · `recovery.factory` · `recovery.buses` · `recovery.callgraph` · `recovery.fingerprints` · `recovery.reconstruction_index` · `recovery.validation` · `recovery.lineage` · `recovery.corpus.shared_class_names` · `recovery.corpus.performance` · `recovery.ground_truth_report`. Major version bumps require migration code or explicit rejection.

---

## 18. Phases (see EXECUTE.md for directives and gates)

| Phase | Scope | Exit |
|---|---|---|
| 1 | Shell, job system, ingest, hashing, static port, evidence viewer, bundle export, cache, ground-truth fixture built | Fixture stripped build → full static bundle; §13 baselines diff clean |
| 2 | `vst3host.exe`: factory, parameters, units, buses, info, state, differential harness; correlation | Fixture: 100% params/identity/state mapped; owned SP binary: `VERIFIED_RUNTIME` parameters |
| 3 | Ghidra: RTTI, callgraph, scoring, noise suppression, fingerprints, known-library cache, BinaryData resolution | Fixture: processBlock path and DSP functions identified; fingerprints stable across 3 builds |
| 4 | One-module proof: probes, fit, evidence/human source, build (SURROGATE), pluginval, differential | Fixture module `BEHAVIORALLY_EQUIVALENT`; then owned SP module |
| 5 | Whole-project loop, LINEAGE, GIT_READY export, handoff | Owned SP plugin exported and continued in Claude Code without re-analysis |

Deferred: SSA/IR engine, taint tracing, graph DB, runtime editor screenshots, version triangulation, broad agent orchestration.
