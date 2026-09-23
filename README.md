# AB — Artifact Bench

**Recover. Reconstruct. Rebuild.**

AB is a local-first Windows desktop workbench that takes an **owned** compiled
audio plugin (`.vst3` / `.dll` / `.vst`) plus whatever survives around it
(presets, DAW sessions, old builds, `.pdb`, assets, source fragments) and
returns a portable, buildable, evidence-backed source project with a
behavioural comparison against the original and a coding-agent handoff.

It never pretends generated code is original source. Every item carries an
evidence state (`VERIFIED · INFERRED · CANDIDATE · GENERATED · UNRECOVERABLE`)
and, where validated, a validation state (`BIT_EXACT … FAILED`).

| Document | Role |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | The contract (wins on conflict) |
| [docs/EXECUTE.md](docs/EXECUTE.md) | Ordered build directives with gates |
| [docs/AB_BRIEF.md](docs/AB_BRIEF.md) | Owner's product brief (naming, screens, principles) |
| [docs/PLUGIN_RECOVERY_BENCH.md](docs/PLUGIN_RECOVERY_BENCH.md) | Functional description, bundle layout, in-app help source |
| [docs/DECISIONS.md](docs/DECISIONS.md) · [docs/BLOCKERS.md](docs/BLOCKERS.md) · [docs/STATUS.md](docs/STATUS.md) | Deviations, owner decisions, what has actually been run |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Process model, workers, data contracts |
| [CLAUDE.md](CLAUDE.md) | Standing rules for agents working in this repo |

## Layout
```
app/              Tauri 2 + React/TS/Vite shell; app/static-engine/ = Static Recovery v2 port (frozen)
engine/           Python 3.11 sidecar (ab_engine) and ab-cli
native/vst3host/  C++17 isolated VST3 host (JSON over stdio)
ghidra/           Ghidra headless scripts (RTTI, callgraph, fingerprints, decompile)
reference/        Clean-room DSP reference corpus (candidates, never Active source by name)
fixtures/         Ground-truth JUCE plugin (source) and static regression baselines
tools/            Pinned tool manifests (JDK, Ghidra, pluginval)
handoff/          Frozen originals: v2 browser extractor, v1 kit (read-only)
```

## Build (development)
```
cd app && npm ci && npm run build                     # UI + static engine (Node 22)
cd app/src-tauri && cargo check --target x86_64-pc-windows-msvc
cd engine && pip install -e ".[dev]" && pytest -q      # Python 3.11
ab-cli doctor
```
Release packaging (Windows): `scripts/build-release.ps1` produces a ZIP with a
single `AB.exe` plus its bundled engine; no dev tooling is needed to run it.

## Pipeline (one plugin, from the CLI)
```
export AB_VST3HOST=.../vst3host AB_JUCE_DIR=.../JUCE            # or install pinned tools: ab-cli tools install
ab-cli ingest --ownership OWNED <plugin.vst3> [presets/ sessions/ *.pdb]
ab-cli run <job> --stage INGESTED --stage STATIC_COMPLETE --stage RUNTIME_COMPLETE \
    --stage DECOMPILATION_COMPLETE --stage BEHAVIOR_COMPLETE                      # INGEST · STATIC · RUNTIME · DECOMPILE · PROBE
ab-cli loop <job>                                                                # RECONSTRUCT → BUILD → COMPARE → handoff (repeat after edits)
ab-cli run <job> --stage EXPORT_COMPLETE                                         # bundle + scanners + GIT_READY
ab-cli --text ground-truth <job> --phase 4                                       # fixture only: GROUND_TRUTH_REPORT.json gates
```

## Status
See [docs/STATUS.md](docs/STATUS.md). Gates are reported as measured,
pending-windows or blocked; nothing is marked green without a run.
