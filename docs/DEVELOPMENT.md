# DEVELOPMENT

## Toolchain
| Component | Needs | Notes |
|---|---|---|
| `app/` | Node 22, npm | `npm ci && npm run build` (tsc, vite, esbuild static engine); `npm test` (vitest) |
| `app/src-tauri` | Rust stable, `x86_64-pc-windows-msvc` target | `cargo check --target x86_64-pc-windows-msvc` works on Linux; `cargo tauri dev` needs Windows (WebView2) or webkit2gtk on Linux |
| `engine/` | Python 3.11 | `pip install -e ".[dev]" && pytest -q`; `ab-cli --text doctor` |
| `native/vst3host` | CMake 3.22, C++17, VST3 SDK 3.7.9 | `build_all.sh` clones the SDK into `third_party/` (git-ignored). Licence: BLOCKERS B-002 |
| `fixtures/groundtruth` | CMake, JUCE 8.0.9, MSVC (Windows) or gcc/clang | `build_all.ps1` / `build_all.sh` clone JUCE and build Debug+PDB, Release+PDB, stripped |
| Ghidra 11 + JDK 21 | downloaded into `%LOCALAPPDATA%\AB\tools` by the Phase 3 downloader (pinned SHA-256 in `tools/manifest.json`) | headless only; `GHIDRA_INSTALL_DIR` / `JAVA_HOME` override |
| pluginval | optional | detected in `tools/pluginval` or PATH; strictness ≥ 5 in the BUILD stage |
| JUCE 8.0.9 (BUILD stage) | pinned zip in `tools/manifest.json` (`ab-cli tools install juce`), or `AB_JUCE_DIR`, or the fixture's `third_party/JUCE` clone in a dev checkout | the rebuild compiles under the owner's JUCE licence |
| vst3host binary | `AB_VST3HOST` overrides discovery (dev: `native/vst3host/build/vst3host`) | RUNTIME / PROBE / COMPARE stages |

## Workflow
1. `scripts/setup.sh` (dev deps) · Windows: `scripts/setup-windows.ps1`.
2. Work top to bottom through `docs/EXECUTE.md`. Each step's gate result goes in the commit message.
3. Never edit `app/static-engine/src` without `ab-cli diff-baseline` passing first (fixtures/static_v2).
4. Commit format `phase-N: <area>: <change>`.

## Stage pipeline (rail)
INGEST → STATIC (frozen v2) → RUNTIME (`vst3host`) → DECOMPILE (Ghidra headless) → PROBE (behaviour renders + fits) → RECONSTRUCT (`ab_engine.reconstruct`: evidence model → recovered_source/evidence_source/Source/Active, gates) → BUILD (`ab_engine.build`: CMake in an isolated worker, pluginval) → COMPARE (`ab_engine.validate`: differential harness + state cross-load) → EXPORT (bundle, scanners, GIT_READY, agent handoff). Every stage can run alone: `ab-cli run <job> --stage <STAGE> [--option k=v]`; project-folder CLIs exist for the Phase 4 pieces (`ab-cli reconstruct <project_dir>`, `ab-cli build <project_dir>`, `ab-cli compare-wav a b`, `ab-cli handoff <job>`).

Local Phase 4 loop on the fixture (Linux):
```
export AB_VST3HOST=$PWD/native/vst3host/build/vst3host AB_JUCE_DIR=$PWD/fixtures/groundtruth/third_party/JUCE
ab-cli --workspace /tmp/gtws ingest --context KNOWN_SOURCE_FIXTURE --source-availability KNOWN_SOURCE_GROUND_TRUTH fixtures/groundtruth/out/stripped/ABGroundTruth.vst3
ab-cli --workspace /tmp/gtws run <job> --stage INGESTED --stage STATIC_COMPLETE --stage RUNTIME_COMPLETE --stage BEHAVIOR_COMPLETE \
   --stage RECONSTRUCTION_COMPLETE --stage BUILD_COMPLETE --stage VALIDATION_COMPLETE
ab-cli --workspace /tmp/gtws --text ground-truth <job> --phase 4 --allow-pending
```

## Testing tiers
- `engine`: `pytest -q` — RPC, contracts, workers, jobs/cache, ingest, static stage (needs Node + built engine), bundle/export, ground truth, runtime host fuzz, behaviour fits, reconstruction model/generator, differential harness, lineage.
- CI (`.github/workflows/ci.yml`): engine + static tests, diff-baseline (synthetic), fixture build + vst3host + phases 1–4 with `--allow-pending` for the Ghidra gates, export scans, Windows-target cargo check.
- `app`: `npm test` — static engine regression on the synthetic fixture; `npm run build` type-checks the UI.
- `fixtures`: `ab-cli diff-baseline` (static regression) and `ab-cli ground-truth <job>` (GROUND_TRUTH_REPORT.json).
- Windows-only: `scripts/build-release.ps1` → ZIP launch; `fixtures/groundtruth/build_all.ps1` → stripped MSVC build; pluginval. Results go in `docs/STATUS.md`.

## Terminology
See `CLAUDE.md` (evidence vocabulary) and `docs/PLUGIN_RECOVERY_BENCH.md`.

## Known limitations
- The four corpus regression baselines need the owner's binaries (BLOCKERS B-001).
- Static BinaryData names shorter than three characters before `_ext` are not recognised (DECISIONS D-013).
- Iterating on a Ghidra script: import + analyse once into a persistent project, then re-run scripts in seconds — `analyzeHeadless <projdir> <name> -import <bin> -max-cpu 2`, then `analyzeHeadless <projdir> <name> -process <bin> -noanalysis -scriptPath ghidra -postScript ExportRTTI.java <out>` (compile-check first: `javac -proc:none -cp "$(find $GHIDRA_INSTALL_DIR -name '*.jar' | tr '\n' ':')" -d /tmp/jc ghidra/*.java`).
- Stripped ELF/Mach-O: class names, bases and vtables come from `ExportRTTI`'s structural Itanium pass (D-025); `processBlock` and the other framework entry points are seeded from vtable layouts the knowledge base learned from a symbol build of any plugin on the same framework (`ab-cli knowledge stats` → `vtable_layouts`). Run a symbol build through DECOMPILE once per framework version to teach it.
- Ghidra runs are slow on large JUCE binaries (≈10 min analysis + decompile of the top-N functions); the DECOMPILE stage decompiles only the `max_functions` highest-scoring candidates (default 20000, fixture validated at 1500).
- The Linux "stripped" fixture keeps its `.dynsym` (exported JUCE symbols survive `-s`); the MSVC/PE stripped build is the harder test and stays pending-windows.
- UI `paint()`/`resized()` intent is UNRECOVERABLE; layouts are rebuilt from carved assets and layout XML.
