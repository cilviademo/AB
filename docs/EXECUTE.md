# EXECUTE.md — Palimpsest build directives for Claude Code
### Read SPEC.md first. Work top to bottom. Do not start a phase until the previous phase's gate is green.

**Standing instructions for every session**
- Static Recovery v2 is frozen. Port it; do not "improve" it. Any change to `app/static-engine/` must pass `palimpsest-cli diff-baseline` (fixtures/static_v2) before commit.
- Never write `VERIFIED` for anything not read from an authoritative artifact or runtime API. Never invent identity, ranges, defaults, or algorithms. Unknown stays `UNKNOWN`.
- Every JSON you emit is wrapped `{schema, schema_version, tool, generated, data}` and validated against `engine/contracts/`.
- Plugins are untrusted: only `native/vst3host` loads them. If you find yourself writing `LoadLibrary`/`ctypes.CDLL` on a plugin anywhere else, stop.
- Keep the repo buildable at every commit (`app`, `engine`, `native` each have a one-command build). Commit small; message format `phase-N: <area>: <change>`.
- Mirror Prosody: Tauri 2 + React/TS + Vite shell, Python sidecar bundled with PyInstaller, ZIP distribution containing `Palimpsest.exe`. Reuse Prosody's supervisor, updater, logging and theme code where licenses/paths allow; do not copy Prosody's FL-specific code.
- Reference material lives in `reference/music_reference_corpus_21/` (user-supplied). It is a clean-room candidate library and vocabulary, not recovered source; never promote it into `Active/` by name.

---

## PHASE 1 — Shell, jobs, static port, fixture

### 1.1 Repo + shell
- Scaffold `palimpsest/` per SPEC §3. Fork Prosody's Tauri shell: window, tray, updater stub, theme tokens, logger, sidecar supervisor.
- Rust side: `spawn_worker(kind, args, timeout, env_allowlist, cwd_temp)` returning `{pid, exit_code, stdout_path, stderr_path, timed_out, crash_dump}`; Job Object on Windows so child trees die with the worker.
- Python sidecar `engine/` exposes a JSON-lines RPC (`method, params, id`) over stdio; every method has a CLI twin in `palimpsest-cli`.
- **Gate:** `palimpsest-cli doctor` reports shell, engine, disk, and tool status; `Palimpsest.exe` launches from a clean ZIP on a machine with no dev tools.

### 1.2 Job system + cache
- SQLite `jobs.db`: `jobs(job_id, artifact_sha256, ownership, created)`, `stages(job_id, stage, status, input_hashes, tool_versions, config_hash, started, ended, warnings, outputs, completeness)`.
- Object store `objects/<sha256>` with refcounts; helpers `put_bytes`, `get_path`, `materialize(logical_tree)`.
- Cache rule implemented exactly: reuse a stage when `artifact_sha256 + tool_version + stage_version + config_hash` match; invalidate downstream only.
- **Gate:** re-running a job with no changes performs zero work; changing `stage_version` of DECOMPILATION re-runs only DECOMPILATION and later.

### 1.3 Ingest
- Accept files, folders, zips. Group binaries by bundle; attach presets/sources/pdb/objs by path prefix. Hash everything (SHA-256, streamed). Detect duplicates. Record ownership declaration.
- Write `00_manifest/input_manifest.json`, `hashes.json`, `tool_versions.json`.
- **Gate:** dropping the 4 regression fixtures + 3 preset files yields 4 jobs with correct attachments and hashes; 500 MB corpus ingests under 400 MB peak RSS (streamed).

### 1.4 Static Recovery v2 port
- Move the browser engine's analysis functions into `app/static-engine/` as pure TS modules (no DOM). Run in a Web Worker; stream stage progress to the UI; return contracts to the engine via IPC.
- Add stage instrumentation (SPEC §6.4) and completeness flags (§1.10). Implement `DEEP_SCAN` mode and its auto-triggers (§6.3).
- Engine writes `01_evidence/{binary,rtti,strings,paths,resources,presets}`, `02_recovered_assets` (content-addressed), `03_architecture/{serialized_keys,classes}.json`, `07_agent_handoff/*` exactly as v2, plus `stage.json`.
- **Gate:** `palimpsest-cli diff-baseline` shows zero evidence-status diffs and ≤ 20% timing variance against `fixtures/static_v2/` for all four fixtures.

### 1.5 Evidence viewer + bundle export
- Screens: Recover (drop zone, ownership, RECOVER PROJECT, stage rail), Scorecard, Evidence browser (JSON with schema badge, resource gallery with sprite-strip rendering), Export (folder/ZIP; `GIT_READY` checklist runs but may show pending items for later stages).
- Bundle writer produces the `00_..07_` tree; single-project export materializes assets from the object store.
- **Gate:** a Windows-invalid-path scanner and secret scanner run on every export; both pass on the four fixtures.

### 1.6 Ground-truth fixture
- Create `fixtures/groundtruth/` JUCE plugin per SPEC §12 (source + CMake). Build Debug+PDB, Release+PDB, Release-stripped via a script (`fixtures/groundtruth/build_all.ps1`). Commit the source and the build script; store built binaries as CI artifacts (not in git).
- Write `engine/groundtruth/compare.py` producing `GROUND_TRUTH_REPORT.json` (SPEC §12 metrics) from any bundle vs the fixture's `truth.json` (generated from source at build time).
- **Gate (Phase 1 exit):** stripped fixture → static bundle; `GROUND_TRUTH_REPORT.json` shows RTTI classes ≥ 95% recovered, resources 100% VALID_EXACT, BinaryData names present, serialized keys found, 0 illegal paths.

---

## PHASE 2 — Native runtime host

### 2.1 `native/vst3host`
- C++17, VST3 SDK hosting classes (`module`, `hostclasses`, `plugprovider`). Commands per SPEC §7. Single JSON request on stdin, single JSON response on stdout, diagnostics on stderr, exit codes: 0 ok, 2 load failure, 3 plugin exception, 4 timeout (watchdog thread), 5 bad request.
- Never share memory with the caller; never keep the plugin loaded between commands.
- **Gate:** `factory`, `parameters`, `units`, `buses`, `info`, `state` on the fixture return `VERIFIED_RUNTIME` data matching `truth.json` exactly (IDs, titles, step counts, defaults, units, FUIDs).

### 2.2 Correlation
- Engine merges static `serialized_keys.json` with `runtime_parameters.json` → `state_runtime_map.json` (`SAME_ID|MAPPED|STATE_ONLY|RUNTIME_ONLY|UNKNOWN`).
- State-differential harness: for each runtime parameter, `setparam` then `state`, diff against baseline (XML if decodable, else byte-diff), locate field, infer `value_representation`.
- Update `03_architecture/parameters.json` with tiers `VST3_EXPORTED_PARAMETER | STATE_SCHEMA_FIELD | UI_ONLY_CONTROL | UNKNOWN_PROPERTY`. Static `STATE_FIELD_CANDIDATE` never blocks promotion.
- **Gate:** fixture: 100% of exported parameters mapped to state fields with correct representation; the indexed decoy field in the fixture is correctly classified from runtime evidence, not from its name.

### 2.3 Identity + placeholders
- Replace `GENERATED_BUILD_PLACEHOLDER` values (buses, latency, tail, programs, editor) with `VERIFIED_RUNTIME` values in the generated processor shell. FIDELITY CMake mode auto-fills identity from `factory.json`; SURROGATE remains available.
- **Gate (Phase 2 exit):** fixture FIDELITY build configures with recovered identity; owned SP binary (when available) yields `VERIFIED_RUNTIME` identity and parameters with no manual input.

---

## PHASE 3 — Decompiler, fingerprints, lineage

### 3.1 Tool provisioning
- First-run downloader for JDK 21 + Ghidra + pluginval into `%LOCALAPPDATA%\Palimpsest\tools\` with pinned SHA-256 from `tools/manifest.json`; resumable; offline mode allowed (stages degrade to SKIPPED with reason).

### 3.2 Ghidra scripts
- `ExportRTTI.java`: run MSVC RTTI analyzer; export `classes_verified.json` (inheritance, vtables, slots, ctor/dtor candidates). Merge with v2 `classes.json` → `name_status: VERIFIED_RTTI`, `structure_status: VERIFIED_VTABLE`.
- `ExportCallgraph.java`: seed from exports → JUCE wrapper → `AudioProcessor` vtable slots; export callgraph with `dist_from_processBlock`.
- `Fingerprint.java`: SPEC §8.1 signatures per function and class; write `fingerprints.json`.
- `ExportDecompiled.java` (upgrade of v1): role scoring (§8.2), noise suppression and wrapper collapse (§8.3), per-class files under `01_evidence/decompiler/classes/`, `dsp_candidates.md`, `symbol_map.json` (raw → inferred → final names, all retained).
- Ghidra runs as a background, resumable job; partial exports are marked `SCAN_INCOMPLETE`.
- **Gate:** fixture: `processBlock`, `prepareToPlay`, state functions located; waveshaper and filter functions in the top-5 DSP candidates; fingerprints for the same source function match across Release+PDB and Release-stripped builds on `NORMALIZED_INSTRUCTION_HASH` and `CFG_SIGNATURE` (raw hashes may differ).

### 3.3 BinaryData resolution
- Locate `namedResourceList` / `getNamedResource`; resolve name → bytes; SHA-256 match to carved assets; set `mapping_status: VERIFIED`; rename in `02_recovered_assets/` only on VERIFIED.
- **Gate:** fixture PNG and TTF resolve to their original filenames.

### 3.4 Known-library cache + lineage
- `knowledge/` store per SPEC §8.5; matching pipeline: fingerprint → match → `KNOWN_*` → suppress deep work for framework/third-party → reuse classifications for shared-internal **with §1.6 contradiction check**.
- Library screen: families via `CLASS_NAME_GRAPH_CLUSTER` (INFERRED) plus average-link/medoid; `LINEAGE_REPORT.md` per plugin; `SYMBOL_LINEAGE_FINGERPRINT` recorded as supporting evidence.
- Seed the cache with JUCE and SoundTouch fingerprints from the fixture builds and from the 21-plugin corpus signatures (`KNOWN_FRAMEWORK` / `KNOWN_THIRD_PARTY` only; corpus internal classes stay `SHARED_IMPLEMENTATION_CANDIDATE` until an owned binary verifies them).
- **Gate (Phase 3 exit):** re-analysing the fixture after cache seeding skips ≥ 80% of JUCE functions; a deliberately modified fixture build (one DSP constant changed) is NOT matched as identical for that function.

---

## PHASE 4 — One-module proof

### 4.1 Behavioral probes
- `vst3host render`: probes per SPEC §11 at 44.1/48/96 kHz, block sizes 32…1024, one parameter swept at a time. Metrics written to `05_reference_behavior/measurements.json`, audio to object store.

### 4.2 Fit + reconstruction
- Target: fixture waveshaper first. Transfer-curve fit against candidate families (from `reference/` and SPEC §11); choose by residual. Produce `evidence_source/` (from decompiler) and `human_source/` (concise), with `reconstruction_index.json` entries carrying addresses, evidence, rmse.
- Evidence gates enforced in code (SPEC §10): promotion to `Active/` requires `BEHAVIOR_MATCHED`.

### 4.3 Build + validate
- SURROGATE build via CMake/MSVC (detected); pluginval strictness 5 minimum; differential harness original vs rebuild on identical probes/state → per-module classification.
- **Gate (Phase 4 exit):** fixture waveshaper reaches `BEHAVIORALLY_EQUIVALENT` (RMSE ≤ 1e-4 on the ramp probe, spectrum diff ≤ 0.1 dB to 20 kHz at 48 kHz) with build + pluginval green; then repeat on one module of the owned SP plugin and record the result honestly, including `FAILED` with cause if it fails.

---

## PHASE 5 — Whole-project loop and handoff

- Reconstruct → build → compare → locate error → patch → rebuild loop over remaining modules in priority order; `LINEAGE_REPORT.md`; `UNRECOVERABLE.md`; `HANDOFF.md`; `agent_prompt.md`; `GIT_READY` checklist enforced; optional GitHub push.
- **Gate:** owned SP bundle opens in Claude Code and a fresh session can make a correct DSP change guided only by `reconstruction_index.json`, without re-running analysis.

---

## Always-on checks (CI on every PR)
1. `diff-baseline` on the four static fixtures.
2. `GROUND_TRUTH_REPORT.json` thresholds for the current phase.
3. Contract validation of every emitted JSON.
4. Path-portability and secret scans on generated bundles.
5. `vst3host` fuzz: 20 malformed/hostile inputs must fail with codes 2–5, never crash the engine.

## Definition of done for the product
An owned lost-source plugin can be dropped in and returned as a portable, maintainable, buildable, evidence-backed project that a human or coding agent continues without restarting development from zero — with every claim in the bundle traceable to runtime, static, decompiler, or behavioral evidence.
