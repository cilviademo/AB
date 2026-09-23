# ARCHITECTURE

How AB is put together. SPEC.md is the contract; this explains the shape.

## Processes

```
AB.exe (Tauri 2 shell — never touches a plugin binary)
 ├─ webview (React/TS)
 │    └─ static worker (Web Worker): Static Recovery v2 port, frozen
 └─ ab-engine (Python 3.11 sidecar, JSON lines over stdio, supervised by Rust)
      ├─ node cli.mjs        static engine, headless (ab-cli / CI only)
      ├─ vst3host            C++17, one plugin per process, 60 s timeout, Job Object
      ├─ ghidra headless     Java, background, resumable
      ├─ cmake / msbuild     optional build worker
      └─ pluginval           optional validator
```

Every child is started by `ab_engine.workers.run.run_worker` (or the Rust
`spawn_worker` for the engine itself): sanitized environment, temporary
working directory, watchdog, captured stdout/stderr files, exit code, crash
dump path, `error_code` (`PLUGIN_CRASH`, `HOST_TIMEOUT`, `GHIDRA_FAILED`,
`BUILD_FAILED`, `VALIDATION_FAILED`, `WORKER_NOT_FOUND`). A worker crash
fails its stage only.

## Stages and cache

`INGESTED → STATIC_COMPLETE → RUNTIME_COMPLETE → DECOMPILATION_COMPLETE →
BEHAVIOR_COMPLETE → RECONSTRUCTION_COMPLETE → BUILD_COMPLETE →
VALIDATION_COMPLETE → EXPORT_COMPLETE` (rail: INGEST · STATIC · RUNTIME ·
DECOMPILE · PROBE · RECONSTRUCT · BUILD · COMPARE · EXPORT).

`ab_engine.jobs.runner` runs registered `StageImpl`s in order. A stage is
reused when `sha256(artifact) + tool_version + stage_version + config_hash`
matches its stored OK record; running one invalidates only later stages.
Records live in `jobs.db` (SQLite) and `<project>/stages/<stage>.json`
(`artifactbench.stage`), written before and after each run with warnings,
errors, outputs, metrics and a completeness flag.

## Storage

```
%LOCALAPPDATA%\AB\          state: jobs.db, objects/<aa>/<sha256>, knowledge/, tools/, logs/<job>/, tmp/
Documents\AB\Projects\<name>-<sha8>\   the bundle tree 00_..07_, stages/, static_result.json
Documents\AB\Exports\<name>-<sha8>\    materialised, independent export (+ .zip)
```

The object store is content-addressed with refcounts; carved bytes and
inputs are stored once. Exports never reference another project's folder.

## Data contracts

Every JSON file is `{schema, schema_version, tool, generated, data}`.
Frozen v2 outputs are `recovery.*` v2; everything AB adds is `artifactbench.*`
v1. Schemas: `engine/ab_engine/contracts/schemas/`. Unknown majors are
rejected (`ContractError`), never reinterpreted.

## Static engine hosting

`app/static-engine/src` is the verbatim port. `run.ts` is the single entry
(`runStatic`, `runCorpus`); `worker.ts` wraps it for the webview,
`cli.ts` for Node. Both produce a *bundle plan* (paths + contents) that the
engine writes (`ab_engine.static.api`). DEEP_SCAN auto-triggers (SPEC §6.3)
live in the engine; the deep switch lives in `carve()`.

## Evidence flow into the scorecard

`bundle.scorecard` reads only files: `00_manifest/recovery_summary.json`,
`01_evidence/{rtti,resources,vst3,callgraphs}`, `03_architecture/*`,
`06_validation/*`, `07_agent_handoff/reconstruction_index.json`. Missing
stages show as UNKNOWN/pending. Nothing is aggregated into one number.

## Security boundaries

- webview: no filesystem, no shell; `read_bundle_file` reads only under the AB folders
- engine: never loads a plugin; spawns isolated workers only
- vst3host: the only process that loads a plugin; killed by timeout; Job Object on Windows
- exports: path + secret scanners; `01_evidence/` is immutable after its stage
