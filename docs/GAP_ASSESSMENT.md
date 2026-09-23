# Implementation-gap assessment (before Phase 1)

Repository `cilviademo/AB` was empty at start (no commits). Everything below
is what exists in the handoff and what it maps to.

| Exists and works | Where it goes | Phase |
|---|---|---|
| Static Recovery v2 (single-file browser extractor, 21-plugin corpus run) | `handoff/static-engine/` frozen; analysis functions ported verbatim to `app/static-engine/` behind `analyzeBinary/analyzeGroup/buildCorpus` | 1.4 |
| v1 kit `vst_recover.py` (inventory, pedalboard params, Ghidra runner, scaffold) | `handoff/kit/` frozen; Ghidra-runner logic reused in `engine/ab_engine/workers/ghidra.py`; pedalboard kept only as a diagnostic fallback | 3 |
| v1 `ExportDecompiled.java` | `ghidra/ExportDecompiled.java`, upgraded per SPEC §8 | 3 |
| Reference DSP corpus (33 components, catalogs, families, probes) | `reference/music_reference_corpus_21/` verbatim; `ProbeSignals.h` mirrored by `engine/ab_engine/behavior/probes.py` | 4 |
| Corpus knowledge (families, shared symbols, state-key catalog) | seeds for `knowledge/` cache as `KNOWN_*` hints only | 3 |
| Bundle layout `00_..07_` + `UNRECOVERABLE.md` (PLUGIN_RECOVERY_BENCH.md) | `engine/ab_engine/bundle/` and the in-app Help | 1.5 |
| Prosody shell pattern (separate repo, read-only) | re-created under AB names in `app/` | 1.1 |

| Missing entirely | Phase |
|---|---|
| Tauri shell, sidecar supervisor with `spawn_worker`, Python RPC + CLI | 1.1 |
| Job system, object store, cache rule | 1.2 |
| Ingest with streamed hashing and manifests | 1.3 |
| Worker/Node hosting of the static engine, instrumentation, DEEP_SCAN, baselines | 1.4 |
| Screens, bundle export, path/secret scanners | 1.5 |
| Ground-truth fixture, truth.json, compare.py | 1.6 |
| `vst3host`, correlation, state-differential harness | 2 |
| Ghidra scripts, fingerprints, knowledge cache, lineage | 3 |
| Probes, fits, reconstruction generators, gates, differential harness | 4 |
| Whole-project loop, handoff writers, GIT_READY, CI | 5 |

Not available on this machine: the four regression binaries, the SP plugin,
Windows (MSVC, pluginval, WebView2), Ghidra release downloads. See BLOCKERS.
