# BLOCKERS

Things only the owner can resolve. Each lists the options. Work continues
around them; nothing here is faked.

## B-001 Regression fixture binaries (EXECUTE 1.4 gate)
`fixtures/static_v2/` baselines require the four corpus binaries: Twin Panda FX,
Rhino Reverb, Fox Echo Chorus, TimeMachine. Not in the handoff.
Options: (a) drop the four `.vst3` files into `fixtures/static_v2/binaries/`
(git-ignored) and run `ab-cli baseline-init`; (b) supply the v2 browser
bundles you already exported for them and run `ab-cli baseline-import <zip>`.
Until then `diff-baseline` runs on the synthetic fixture only and says so.

## B-002 VST3 SDK licence for distribution (SPEC §2)
`native/vst3host` links the Steinberg hosting classes. Internal use is fine
under either licence; a distributed `AB.exe` needs a choice: GPLv3 or the
Steinberg proprietary licence. Default assumed until decided: GPLv3 for
in-house builds, `THIRD-PARTY.md` says so.

## B-003 Owned SP-emulation plugin (Phase 2/4/5 acceptance fixture)
Binary + surviving folder not supplied yet. Needed only after the ground-truth
gates pass. Drop location: anywhere; declare `My plugin` at ingest.

## B-004 BTZ build with source as a second ground-truth fixture
Optional. If a BTZ build with source exists, say where; it becomes
`fixtures/groundtruth_btz/` with the same truth.json generator.

## B-005 Windows runs
The Phase 1 exit gate on the stripped MSVC build, Ghidra MSVC RTTI, pluginval
and the clean-ZIP launch need the studio PC. Scripts are in place; results are
recorded in `docs/STATUS.md` when run.

## B-006 GitHub usage
Assumed: commit and push to `claude/blissful-ritchie-1408h8` only; no PR
unless asked. `Push to GitHub` in the Export screen stays optional.

## B-007 Pin the JDK 21 download hashes in tools/manifest.json — RESOLVED
Adoptium's API is blocked from the build environment, but the exact Temurin
release assets on GitHub are reachable: `tools/manifest.json` now pins
Temurin 21.0.8+9 (Windows x64 zip, Linux x64 tar.gz, macOS aarch64 tar.gz)
with the sha256 values published beside each asset (`.sha256.txt`). JUCE
8.0.9 (Windows/Linux release zips) and pluginval 1.0.4 (Windows/Linux/macOS)
are pinned the same way. No `PIN_ME` entries remain.

## B-008 iPlug2 ground-truth fixture cannot be built in this environment
ADDENDUM A5 asks for a second fixture in iPlug2. iPlug2 targets Windows and
macOS (Linux support is experimental and its VST3 build is not maintained), so
`fixtures/groundtruth_iplug2/` ships the source (same parameters, DSP,
resources and LICENSING_AND_ENTITLEMENT_SUBSYSTEM stub (serial check + demo state) as the JUCE fixture, generated from the
same `spec.json`) with `build_all.ps1`, but it has not been compiled here.
Studio-PC action: run `fixtures/groundtruth_iplug2/build_all.ps1` (clones
iPlug2 and its dependencies), then ingest `out/stripped/ABGroundTruthIP.vst3`
and run `ab-cli --text ground-truth <job> --truth fixtures/groundtruth_iplug2/truth.json --phase 2`.
Until then gate A5's second report is pending-windows, and the JUCE rule
non-firing check (A4) is unverified.
