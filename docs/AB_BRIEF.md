# AB — Artifact Bench: product brief (owner, 2026-09-23)

Received in chat at kickoff. Authoritative alongside SPEC.md and EXECUTE.md;
where it disagrees with SPEC, DECISIONS.md records the resolution.

You are now implementing AB — Artifact Bench. AB is a local-first Windows
desktop recovery and reconstruction workbench for owned/authorized compiled
audio plugins and related project artifacts. Its purpose is not merely to
inspect or decompile binaries. Its purpose is: take an owned compiled plugin
and whatever surviving files still exist, recover the maximum verifiable
project structure and behavior, reconstruct concise maintainable source,
rebuild the plugin, compare it against the original, and return a portable
source repository that a human or coding agent can continue without starting
over.

Treat all uploaded project files as authoritative source material. Before
changing code, read and reconcile SPEC.md, EXECUTE.md,
PLUGIN_RECOVERY_BENCH.md, MUSIC_REFERENCE_CODEBOOK_21.md, Static Recovery v2
outputs, 21-plugin corpus outputs, corpus manifests/reports, the reference DSP
corpus, reconstruction indexes, existing recovery scripts, the browser
artifact/source, test fixtures and any uploaded owned binaries. Do not casually
replace decisions already made in those files. If SPEC.md and EXECUTE.md
disagree, preserve both, document the conflict, and choose the interpretation
most consistent with the product goal and current architecture.

## Product name
Product: **AB**. Expanded: **Artifact Bench**. Workspace terminology: *Bench*
(Artifact Bench, Recovery Bench, Corpus Bench, Evidence, Reconstruction,
Validation, Export). Do not call the product "Plugin Recovery Bench" in
top-level branding; the phrase may remain as a functional description.
Product line: **AB — Artifact Bench. Recover. Reconstruct. Rebuild.**

## Core principle
AB must distinguish what is directly known, from what is inferred, from what
is reconstructed, from what is generated solely to make a project build. The
tool must never visually or structurally imply that generated reconstruction
is literal original source. Evidence states: `VERIFIED` `INFERRED` `CANDIDATE`
`GENERATED` `UNRECOVERABLE`. Validation states: `BIT_EXACT`
`NUMERICALLY_EQUIVALENT` `BEHAVIORALLY_EQUIVALENT` `PERCEPTUALLY_CLOSE`
`STRUCTURALLY_PLAUSIBLE` `SCAFFOLD_ONLY` `FAILED`.

## Primary user story
1. User drops `.vst3` `.dll` `.vst` `.component` `.dylib`, presets, sessions,
   `.pdb`, `.map`, source fragments, assets, folders, older builds, archives.
2. AB inventories and hashes everything. 3. Static recovery. 4. Isolated
runtime plugin introspection. 5. Decompiler/RTTI analysis. 6. Maps plugin
identity, runtime parameters, serialized state, classes, resources, signal
flow, DSP candidates. 7. Behavioral probes against the original. 8.
Reconstructs one or more modules. 9. Builds the recovered plugin. 10.
Validates loading, state, parameters, audio behavior, pluginval,
original-vs-reconstruction. 11. Exports maintainable source, evidence,
reconstruction index, agent handoff, Git-ready project, ZIP.

Ultimate success: an owned lost-source plugin can be dropped into Artifact
Bench and returned as a maintainable, buildable, evidence-backed project that
can be continued in Claude Code, Codex, VS Code, Cursor or another coding
environment without restarting development from zero.

## Do not rebuild everything from scratch
Inspect the current repository first. Preserve working functionality from
Static Recovery v2. Reuse working implementations. Refactor only to satisfy
the standalone architecture. Port the validated browser/static extractor
behind a stable analysis interface.

## Static Recovery v2 is frozen
Frozen except for real bugs and schema migration. Its responsibilities: binary
identification, PE/static inspection, export detection, strings, RTTI name
evidence, XML/state/preset recovery, BinaryData-name discovery, resource
carving, resource structural validation, hashes, path evidence,
compiler/linker hints, static state-schema discovery, corpus recurrence,
evidence bundle generation. Do not expand it into runtime/decompiler
functionality; those live in desktop workers.

## Terminology
Not every XML `<PARAM>` is a VST parameter. Concepts: `VST3_EXPORTED_PARAMETER`
`STATE_SCHEMA_FIELD` `PRESET_FIELD` `UI_ONLY_CONTROL` `UNKNOWN_PROPERTY`.
Indexed entries (`waveShapers_4_2`, `bandBypass1_0_0`) may be classified
statically as `STATE_FIELD_CANDIDATE`; only runtime introspection establishes
host export. An observed serialized value is not a normalized VST value: use
`observed_serialized_values` until representation is established.

## Desktop architecture
Tauri GUI · Static Analysis Worker · vst3host.exe · Ghidra Worker ·
Behavioral Probe Worker · Reconstruction Worker · Build Worker · Validation
Worker · Local Knowledge/Corpus Cache. Never load unknown plugin code in the
GUI process; a plugin crash must not crash AB. Every risky worker has timeout,
process isolation, stdout/stderr capture, exit code, crash state, structured
output, temporary workspace, bounded resources.

## Job system
Resumable projects. Stage states `INGESTED` `STATIC_COMPLETE`
`RUNTIME_COMPLETE` `DECOMPILATION_COMPLETE` `BEHAVIOR_COMPLETE`
`RECONSTRUCTION_COMPLETE` `BUILD_COMPLETE` `VALIDATION_COMPLETE`
`EXPORT_COMPLETE`. Each stage records input hashes, schema version, tool
version, configuration hash, start/end time, warnings, errors, produced files.
Do not redo completed valid work.

## Cache
Key by artifact SHA-256, stage, stage version, tool version, configuration
hash. If only human reconstruction logic changes, do not rerun carving, RTTI
extraction or runtime parameter enumeration.

## Known-library cache (first-class)
Persistent local cache of framework, third-party and shared-internal
signatures, function/class fingerprints, resource hashes, build fingerprints,
state-schema patterns, known behavior. Classes `KNOWN_FRAMEWORK`
`KNOWN_THIRD_PARTY` `KNOWN_SHARED_INTERNAL` `KNOWN_PLUGIN_SPECIFIC` `UNKNOWN`.
Identity keyed by implementation evidence, not symbol name.

## Implementation fingerprints
Functions: raw byte hash, normalized instruction hash, CFG signature,
basic-block count, call signature, constant signature, string-reference
signature, RTTI association, vtable association. Classes: RTTI name, vtable
layout, method fingerprint set, inheritance, ctor/dtor candidates,
member-access pattern. States `SHARED_NAME` → `SHARED_ARCHITECTURE_CANDIDATE`
→ `SHARED_IMPLEMENTATION_CANDIDATE` → `SHARED_IMPLEMENTATION_VERIFIED`; a name
is never enough for the last.

## Corpus lineage
Family inference (Gen A Studio/Safari, Gen B Morph/WDF, Gen C Hammer) is
`INFERRED_CODEBASE_FAMILY`, from class-name-set similarity, shared resources,
build fingerprint, state schema, function/vtable fingerprints. Naive
connected-component chaining is not authoritative.

## Native VST3 host
VST3 SDK directly. Recover factory, metadata, class entries, FUIDs,
processor/controller identity, parameters (ParamID, title, short title, units,
stepCount, defaultNormalizedValue, flags, unitId), units, program lists, buses,
latency, tail, editor support; normalized→string and string→normalized where
supported. Runtime parameter evidence stored separately from serialized state.

## State model
`runtime_parameters.json` `serialized_properties.json` `state_runtime_map.json`
with `SAME_ID` `MAPPED` `STATE_ONLY` `RUNTIME_ONLY` `UNKNOWN`. Differential
harness: baseline state → change exactly one parameter → capture → diff → map.

## Ghidra
MSVC RTTI analysis; export RTTI classes, TypeDescriptors, vtables,
inheritance, ctors/dtors, method addresses, callgraph, xrefs. Seed from
processBlock, prepareToPlay, releaseResources, get/setStateInformation,
processor ctor, editor ctor, parameter creation, preset/state code.

## DSP prioritization
Rank by distance from processBlock, float density, SIMD, buffer loops,
sample-rate refs, DSP constants, parameter/state refs, coefficient math,
nonlinear math, delay lines, FFT/convolution. Categories `AUDIO_LOOP` `GAIN`
`WAVESHAPER` `FILTER` `FILTER_COEFFICIENT` `OVERSAMPLER` `COMPRESSOR` `LIMITER`
`GATE` `DELAY` `REVERB` `CONVOLUTION` `PITCH_TIME` `MODULATION` `METER`
`PARAMETER_UPDATE` `STATE` `GUI` `RESOURCE` `FRAMEWORK` `RUNTIME` `UNKNOWN`.
Noise suppression: CRT, allocators, security cookies, EH scaffolding, refcount
plumbing, JUCE wrappers, import trampolines, destructor thunks; provenance
kept separately.

## Reference codebook
`MUSIC_REFERENCE_CODEBOOK_21.md` and the library are clean-room candidates
(hypothesis/test), never Active source on a name match; require static
and/or behavioral evidence.

## Behavioral probes and fitting
Signals: silence, impulse, DC, amplitude ramp, sine, amplitude sweep, frequency
sweep, white noise, pink noise, two-tone IMD. Rates 44100/48000/96000; buffers
32…1024. Capture raw audio, peak, RMS, latency, tail, frequency response,
phase, harmonic spectrum, THD, aliasing, transfer function. Fit hard clip,
tanh, atan, cubic, higher-order polynomial, piecewise polynomial, rational;
measure RMSE, max error, correlation; choose by evidence, never by name.

## Reconstruction output and provenance
`04_reconstruction/{evidence_source, human_source, Source/{Active,
RecoveredScaffolds}, Resources}`. Never compile pass-through scaffolds into
Active by default. Concise human source may rename, collapse wrappers, remove
noise, replace equivalents (e.g. `juce::jlimit`) only when behavior is
equivalent. `reconstruction_index.json` and `binary_symbol_map.json` map every
important item to symbol, file, status, address, Ghidra symbol, RTTI class,
parameter/resource refs, tests, validation state.

## Build modes, build system, validation, differential
`FIDELITY_BUILD` (recovered identity; session relinking, state compatibility)
vs `SURROGATE_BUILD` (generated temporary identity; DSP, pluginval, UI,
behavioral tests; never session-compatible). Windows x64 VST3 first; no AU/AAX/
Standalone unless requested. pluginval where installed (pass/fail, strictness,
fuzz, state, crashes); no `BUILD_READY` on critical validation failure.
Differential harness under identical input/params/state/rate/buffer: sample
error, RMSE, max error, spectrum delta, latency delta, state compatibility.

## Resources, storage, protected subsystems
Structural validation states as above; BinaryData mapping name → pointer →
size → bytes → filename; no renaming unless verified. Corpus object storage
`objects/<sha256>`; single-project exports materialize independent files.
Licensing code is `PROTECTED_SUBSYSTEM`; no bypass; clean replacement
interface for the owner.

## UI
Primary screen **Recover Project**: drop zone ("Drop plugin binaries, presets,
sessions, project folders, debug files, assets, or archives."), Choose Files,
Choose Folder. Stages `INGEST` `STATIC` `RUNTIME` `DECOMPILE` `PROBE`
`RECONSTRUCT` `BUILD` `COMPARE` `EXPORT`. Raw forensics behind drill-downs.
Visual design: clean, restrained, black/white/neutral, dense enough for
engineering, not cyberpunk/hacker/skeuomorphic, minimal gradients, strong
hierarchy; modern audio-plugin tooling meets IDE utility meets forensic
workbench. Screens: Recover, Overview, Evidence, Parameters & State,
Architecture, DSP, Resources, Compare, Build, Corpus, Export. Scorecard has
separate categories (identity, runtime parameters, state schema, class
architecture, resources, UI, signal flow, DSP structure, DSP behavioral match,
build readiness, state compatibility, repo readiness), each exposing evidence;
no single fake percentage.

## Bundle, handoff, GIT_READY
`Recovered_Project/00_..07_`, `UNRECOVERABLE.md`, `recovered-project.zip`.
Handoff: `HANDOFF.md` `TODO.md` `reconstruction_index.json`
`binary_symbol_map.json` `agent_prompt.md` stating what is verified, inferred,
reconstructed, what builds, what fails, which modules need work, which tests
must stay passing. GIT_READY requires legal filenames, no secrets, no absolute
developer paths, documented dependencies, `.gitignore`, provenance,
generated-vs-recovered separation, build instructions, validated CMake,
documented known failures. GitHub optional; folder/ZIP primary.

## Ground-truth fixture, regression fixtures, one-module proof
Known-source JUCE fixture (bool, enum, gain, filter, waveshaper, oversampling,
APVTS, embedded resource, preset) built Debug+symbols, Release+symbols,
stripped Release; analyze stripped; `GROUND_TRUTH_REPORT.json` measures
parameter/type/default/unit recovery, state mapping, RTTI, ownership, DSP
identification, resources, fingerprint stability, false positives/negatives.
Do not skip. Retain the four static regression fixtures (Twin Panda FX, Rhino
Reverb, Fox Echo Chorus, TimeMachine). One-module proof first (waveshaper,
clipper, filter or resampler): binary → runtime parameter → state mapping →
RTTI/vtable → processBlock path → DSP function → evidence reconstruction →
probe → clean C++ → build → pluginval → comparison; complete only when it
builds, loads, parameters and state work, comparison runs, error is quantified.

## Phases
1 shell, UI skeleton, jobs, ingest, hashing, v2 port, bundle export, cache ·
2 native host, runtime identity/parameters/buses/units, state capture,
differential · 3 Ghidra, RTTI, vtables, callgraph, seeding, scoring,
fingerprints, known-library matching · 4 probes, one-module reconstruction,
candidate fitting, evidence/human source, build, pluginval, differential ·
5 broader reconstruction, corpus acceleration, export/handoff. Do not skip
forward to make the UI look complete.

## Quality, schemas, errors, performance, security, offline
Typed schemas, small modules, explicit interfaces, deterministic outputs,
structured logs, testable workers, no hidden global state, stable file
contracts. Schema metadata `{"schema": "artifactbench.parameters",
"schema_version": 1}`; reject unsupported majors. Visible, actionable errors:
`PLUGIN_CRASH` `HOST_TIMEOUT` `GHIDRA_FAILED` `RESOURCE_PARTIAL` `BUILD_FAILED`
`VALIDATION_FAILED` `STATE_MAPPING_INCOMPLETE`. Instrument each step (elapsed,
bytes, objects, peak memory), track outliers, stream/mmap, bounded
concurrency. Untrusted plugin input even in owner mode; isolated helpers;
sanitized paths; never auto-execute scripts found in dropped folders; no
secrets in bundles. Offline-first: GitHub, cloud APIs, LLMs never mandatory.

## Documentation, deferrals, completion
Document architecture, installation, dependencies, toolchain, VST3 SDK,
Ghidra, pluginval, workflow, testing, terminology, limitations. Defer custom
SSA compiler, graph database, screenshot recreation, autonomous multi-agent
architecture, automatic license replacement, whole-plugin magic before the
one-module proof, unsupported formats. After each phase: run tests, build, fix,
update status, keep a working checkpoint. If a dependency prevents execution
on the current machine, implement the interface, validation, detection and
setup instructions rather than faking success.

## Final standard
"I lost the source to a plugin I built years ago. I still have the VST3, some
presets, an old project folder and maybe a DAW session. I drop all of it into
AB. AB tells me exactly what it knows, reconstructs what it can, tests its
reconstruction against the original, rebuilds a working plugin, and gives me a
clean source repo plus evidence and an agent handoff."
