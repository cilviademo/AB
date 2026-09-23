# PERFORMANCE_REPORT — ADDENDUM B7

Measured on this Linux container (4 vCPU, Python 3.11, Node 20, Ghidra 11.3.2 with MAXMEM=4G).
Every number below was read from a run's stage records (`jobs.db`, `started`/`ended`) or from the
process itself; nothing is estimated. The 21-plugin corpus regression is **blocked (B-001)**: the
fixture binaries are not in the repository, so the frozen-baseline re-run stays pending-windows.

## Cold vs cache-hit (synthetic PE `fixtures/synthetic/SynthPlug.vst3`, INGEST + STATIC via Node)

| run | INGESTED | STATIC_COMPLETE | wall | peak RSS (children) |
|---|---|---|---|---|
| cold | ran | ran | 1.33 s | 103.7 MB |
| cache hit (nothing changed) | reused | reused | 0.23 s | — |

The cache key is `artifact | tool version | stage version | config`; a no-change re-run does zero work
(EXECUTE 1.2 gate, `engine/tests/test_jobs.py`).

## Per-stage, ground-truth fixture (stripped ELF, 9.97 MB, 20 271 function starts)

| stage | ABGroundTruth-stripped3 (`ab-018943e1cc9f`) | ABGroundTruth (Release+symbols, `ab-8a4f348c9bb9`) |
|---|---|---|
| INGESTED | 0.1 s | 0.1 s |
| STATIC_COMPLETE | 1.6 s | 4.8 s |
| RUNTIME_COMPLETE | 0.4 s | 0.4 s |
| BEHAVIOR_COMPLETE | 6.3 s (`ab-4888ec4da30e`, 79 renders) | — |
| DECOMPILATION_COMPLETE | 786.8 s (Capstone 20 271 fingerprints + Ghidra headless + RTTI/callgraph/fingerprint/decompile scripts) | 803.2 s |
| RECONSTRUCTION_COMPLETE | 0.6 s | — |
| BUILD_COMPLETE | 8.5 s (SURROGATE, JUCE 8.0.9, `build_jobs=2`, incremental; 120 s from a clean build dir) | — |
| VALIDATION_COMPLETE | 33.8 s (79 differential renders + pluginval strictness 5 + cross-load) | — |

Slowest stage by far is DECOMPILE, and inside it Ghidra's headless auto-analysis of the 9.97 MB
stripped ELF (~10 min). The knowledge base makes the second build cheaper only for Ghidra-free work:
Capstone fingerprints of an already-seen artifact are 100 % KNOWN and skip deep analysis
(`knowledge_match.json` delta: known 98.3 % / near 1.7 % on the stripped job after the symbol build).

## Memory

- Ingest of a 513 MB synthetic corpus: peak RSS 39 MB (streamed hashing, EXECUTE 1.3 gate).
- Static engine worker on the synthetic PE: 103.7 MB peak (Node + esbuild bundle).
- Ghidra headless: bounded by `MAXMEM` (4 GB here); the engine process itself stays below 300 MB while
  it waits (the worker is a separate, isolated process — a crash fails its stage only).

## The XML-scan pathology (CLAUDE_CODE_PROMPT §2) must not return

The frozen Static Recovery v2 port scans for balanced XML structurally with capped hit counts, and the
Python side never does `push(...hugeArray)` / list splats on large scans. Guards in code:
`app/static-engine` (frozen; `ab-cli diff-baseline` must pass), `engine/tests/test_static.py::test_deep_scan_auto_trigger`.
Fast paths record completeness (`FAST_SCAN_COMPLETE` / `FAST_SCAN_EARLY_TERMINATED`) and may trigger `DEEP_SCAN`.

## Pending (needs the corpus, B-001)

total / per-stage / peak memory across the 21 plugins, slowest fixture, cold vs cache-hit for the whole
corpus. The table above is the fixture-level record until the corpus binaries are provided.
