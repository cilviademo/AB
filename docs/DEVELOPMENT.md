# DEVELOPMENT

## Toolchain
| Component | Needs | Notes |
|---|---|---|
| `app/` | Node 22, npm | `npm ci && npm run build` (tsc, vite, esbuild static engine); `npm test` (vitest) |
| `app/src-tauri` | Rust stable, `x86_64-pc-windows-msvc` target | `cargo check --target x86_64-pc-windows-msvc` works on Linux; `cargo tauri dev` needs Windows (WebView2) or webkit2gtk on Linux |
| `engine/` | Python 3.11 | `pip install -e ".[dev]" && pytest -q`; `ab-cli --text doctor` |
| `native/vst3host` | CMake 3.22, C++17, VST3 SDK 3.7.9 | `build_all.sh` clones the SDK into `third_party/` (git-ignored). Licence: BLOCKERS B-002 |
| `fixtures/groundtruth` | CMake, JUCE 8.0.9, MSVC (Windows) or gcc/clang | `build_all.ps1` / `build_all.sh` clone JUCE and build Debug+PDB, Release+PDB, stripped |
| Ghidra 11 + JDK 21 | downloaded into `%LOCALAPPDATA%\AB\tools` by the Phase 3 downloader (pinned SHA-256 in `tools/manifest.json`) | headless only |
| pluginval | optional | detected in `tools/pluginval` or PATH |

## Workflow
1. `scripts/setup.sh` (dev deps) · Windows: `scripts/setup-windows.ps1`.
2. Work top to bottom through `docs/EXECUTE.md`. Each step's gate result goes in the commit message.
3. Never edit `app/static-engine/src` without `ab-cli diff-baseline` passing first (fixtures/static_v2).
4. Commit format `phase-N: <area>: <change>`.

## Testing tiers
- `engine`: `pytest -q` — RPC, contracts, workers, jobs/cache, ingest, static stage (needs Node + built engine), bundle/export, ground truth.
- `app`: `npm test` — static engine regression on the synthetic fixture; `npm run build` type-checks the UI.
- `fixtures`: `ab-cli diff-baseline` (static regression) and `ab-cli ground-truth <job>` (GROUND_TRUTH_REPORT.json).
- Windows-only: `scripts/build-release.ps1` → ZIP launch; `fixtures/groundtruth/build_all.ps1` → stripped MSVC build; pluginval. Results go in `docs/STATUS.md`.

## Terminology
See `CLAUDE.md` (evidence vocabulary) and `docs/PLUGIN_RECOVERY_BENCH.md`.

## Known limitations
- The four corpus regression baselines need the owner's binaries (BLOCKERS B-001).
- Static BinaryData names shorter than three characters before `_ext` are not recognised (DECISIONS D-013).
- Ghidra cannot be downloaded from this build environment; scripts are verified on the studio PC.
- UI `paint()`/`resized()` intent is UNRECOVERABLE; layouts are rebuilt from carved assets and layout XML.
