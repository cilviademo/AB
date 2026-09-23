# BUILD_VALIDATION_REPORT — Addendum B2 (actual results, this environment)

Environment: Linux x86_64 (cloud dev container, 4 CPU), Python 3.11, Node 20, g++ 13, CMake 3.28, Ninja, JUCE 8.0.9, Ghidra 11.3.2 + Temurin 21, pluginval 1.0.4, Steinberg validator (built with vst3host). Windows-only rows are marked pending-windows: nothing is claimed for them.

| check | command | result | date |
|---|---|---|---|
| engine unit + integration tests | `cd engine && pytest -q` | 102 passed | 2026-09-23 |
| static engine (frozen v2 port) tests | `cd app && npm test` | 22 passed | 2026-09-23 |
| static regression baseline | `ab-cli diff-baseline` | no evidence-status changes; timing +12 % (≤ 20 %) | 2026-09-23 |
| frontend typecheck + bundle | `cd app && npm run build` (tsc + vite) | ok | 2026-09-23 |
| Tauri shell cargo check (Windows target) | `cargo check --target x86_64-pc-windows-msvc` | CI job (.github/workflows/ci.yml); not run in this container | pending-windows |
| Tauri dev / release builds | `npm run tauri build` | pending-windows (studio PC) | — |
| native host | `native/vst3host/build_all.sh` → `vst3host --version` | 0.1.0 built; used by RUNTIME / PROBE / COMPARE stages | 2026-09-23 |
| ground-truth fixture (JUCE) | `fixtures/groundtruth/build_all.sh` (release, stripped) | both built with the licensing stub; stripped `.symtab` 0 | 2026-09-23 |
| ground-truth fixture (iPlug2) | `fixtures/groundtruth_iplug2/build_all.ps1` | pending-windows (BLOCKERS B-008) | — |
| Ghidra exporter scripts | `javac` against the Ghidra jars + headless run on the persistent fixture project | ExportRTTI / ExportCallgraph / Fingerprint / ExportDecompiled compile and run; outputs validated by the DECOMPILE stage contracts | 2026-09-23 |
| schema tests | `pytest engine/tests/test_contracts.py` | pass (part of the 102) | 2026-09-23 |
| SQLite migrations | jobs.db `source_availability` column, knowledge.db `vtable_layout` table + `implementation.tier` column added on open | exercised by the test suite on fresh DBs and by the ground-truth workspace on existing DBs | 2026-09-23 |
| bundle / ZIP export | `ab-cli export <job>` on the stripped fixture job | `<Plugin>_RECOVERED/` + zip; GIT_READY rows green after the machine-path scrub | 2026-09-23 |
| fresh-clone build of the export | clone → `cmake -DJUCE_DIR=… -DAB_BUILD_KIND=SURROGATE` → build | exit 0 in 3 m 53 s, `.vst3` produced | 2026-09-23 |
| pluginval | strictness 5 on the rebuilt fixture | PASSED (16 tests, GUI skipped) | 2026-09-23 |
| Steinberg validator | RUNTIME stage second validation source | 47/47 on the stripped fixture | 2026-09-23 |
