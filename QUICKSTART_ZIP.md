# AB — Artifact Bench · quickstart for the source snapshot

This zip is `git archive` of branch `claude/blissful-ritchie-1408h8` (tracked files only; no build outputs, no
JUCE/VST3 SDK checkouts, no fixture binaries — they are fetched or built by the scripts below).

## Windows: one command

```
powershell -ExecutionPolicy Bypass -File .\bootstrap_windows.ps1
```

It checks Python 3.11+ / Node 20+ / Git, installs the engine, builds the static engine, prints `doctor`, runs the
pipeline on the committed synthetic plugin (ingest → static → route → export), lists the reference library and
runs the engine unit tests. Honest note: the engine has so far been exercised on Linux (127 tests, every fixture
gate); this is its first Windows run — please send back any red line. Every failure is named in the summary; to soak the suite (sequential + CPU hog + random order) run `powershell -File tools\test_series.ps1`. The deeper stages need the native host
(`native\vst3host\build_all.ps1`, CMake + MSVC) and the pinned tools (`ab-cli tools install`).

## What runs where

| | Windows (studio PC) | Linux / macOS / WSL |
|---|---|---|
| engine + CLI (`ab-cli`), all 127 tests | yes (Python 3.11+) | yes |
| static stage (frozen Static Recovery v2, Node) | yes (Node 20+) | yes |
| runtime / probes (`native/vst3host`) | build with `native\vst3host\build_all.ps1` (CMake + MSVC) | `native/vst3host/build_all.sh` |
| ground-truth fixtures (JUCE, with source) | `fixtures\groundtruth\build_all.ps1` | `fixtures/groundtruth/build_all.sh`, `fixtures/groundtruth_unseen/build_all.sh` |
| Ghidra / pluginval / JDK / JUCE | `ab-cli tools install` (pinned SHA-256 downloads) | same |
| desktop shell (Tauri 2) | `cd app && npm ci && npm run tauri dev` (Rust toolchain) — the single-file `AB.exe` ZIP is not built yet (B-005) | dev mode only |

## 1. Engine + CLI (5 minutes)

```
cd engine
python -m pip install -e ".[dev]"
python -m pytest -q                 # 127 tests
ab-cli doctor                       # every dependency/tool: AVAILABLE | MISSING | WRONG_VERSION | UNSUPPORTED + what to install
```

## 2. Static engine (needed by the STATIC stage)

```
cd app
npm ci
npm run build                       # tsc + vite + static-engine/dist
node static-engine/dist/cli.mjs selftest fixtures/synthetic/SynthPlug.vst3
```

## 3. Try the pipeline on a plugin

```
ab-cli ingest "C:\path\to\MyPlugin.vst3"            # or a folder / zip with presets, PDB, sessions, assets…
ab-cli run <job_id> --stage INGESTED --stage STATIC_COMPLETE
ab-cli run <job_id> --stage RUNTIME_COMPLETE         # needs vst3host built
ab-cli --text loop <job_id>                          # behaviour → reconstruct → build → compare (needs tools: ab-cli tools install; JUCE via AB_JUCE_DIR)
ab-cli export <job_id> --zip                         # <Plugin>_RECOVERED/ + zip, GIT_READY checks
ab-cli --text reference                              # reference library: where did AB learn this?
ab-cli route <path>                                  # what AB makes of any dropped file
```

Options worth knowing: `--option goal=MODERNIZE --option naming=CANONICALIZE_NAMES` on the reconstruct stage
(ADDENDUM C3 / naming layer); `ab-cli ingest --context KNOWN_SOURCE_FIXTURE --source-availability KNOWN_SOURCE_GROUND_TRUTH`
for a known-source run scored with `ab-cli ground-truth <job> --truth fixtures/<fixture>/truth.json --phase 4`.

## 4. Where to read results

`<workspace>/Projects/<Plugin>-<hash>/` — `00_manifest` … `07_agent_handoff` (HANDOFF.md, TODO.md,
reconstruction_index.json), `06_validation/VALIDATION.md`, `04_reconstruction/{recovered_source,transformed_source,Source/Active}`.
Workspace default: `Documents\AB` (state in `%LOCALAPPDATA%\AB`); override with `--workspace`.

Status of every gate: `docs/STATUS.md`; decisions: `docs/DECISIONS.md`; open owner decisions: `docs/BLOCKERS.md`.
