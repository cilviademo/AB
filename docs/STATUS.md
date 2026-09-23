# STATUS — what has been run, where

Every gate below is either **measured** (run here, output quoted in the commit),
**pending-windows** (scripted, needs the studio PC) or **blocked** (see
BLOCKERS.md). Nothing is marked green without a run.

| Step | Gate | State |
|---|---|---|
| 1.1 | `ab-cli doctor` reports shell, engine, disk, tools | measured (Linux): 11 pass · 1 warning · 4 unavailable · 0 fail |
| 1.1 | `AB.exe` launches from a clean ZIP with no dev tools | pending-windows |
| 1.2 | no-change re-run does zero work; DECOMPILATION version bump re-runs only it and later | measured: engine/tests/test_jobs.py (24 tests green) |
| 1.3 | 4 fixtures + 3 presets → 4 jobs, correct attachments; 500 MB under 400 MB RSS | measured (synthetic PEs): 4 jobs, attachments by prefix, pdb to all; 513 MB corpus → peak RSS 39 MB, 4.0 s |
| 1.4 | `diff-baseline` zero evidence-status diffs, ≤ 20 % timing variance | measured on the synthetic fixture (see commit); the four corpus fixtures are blocked (B-001): descriptors in place, `ab-cli diff-baseline --init <name>` once the binaries are dropped |
| 1.5 | invalid-path and secret scanners pass on the four fixtures | measured on the synthetic fixture export (GIT_READY true, build/validation rows pending); corpus fixtures blocked (B-001). The secret scanner caught a real leak (absolute tool paths in tool_versions.json) which was fixed |
| 1.6 | stripped fixture → static bundle; GROUND_TRUTH_REPORT thresholds | measured (Linux stripped ELF build): RTTI 5/5, resources 3/3 VALID_EXACT, BinaryData names 3/3, <PARAM> keys 7/7, 0 illegal paths, 0 keys promoted. MSVC/PE variant: pending-windows (`fixtures/groundtruth/build_all.ps1`) |
| 2.1 | factory/parameters/units/buses/info/state match truth.json | measured (Linux): identity vendor+product VERIFIED_RUNTIME, codes Mbnd/Abgt from the JUCE FUID, 7/7 parameters with defaults/steps/units/types |
| 2.2 | 100 % params mapped with representation; decoy classified from runtime | measured (Linux): see commit; JUCE wrapper bypass is RUNTIME_ONLY by design |
| 2.3 | FIDELITY build configures with recovered identity | identity.cmake written from VERIFIED_RUNTIME facts; configure run pending (needs JUCE in the export, Phase 4 build worker) |
| CI-5 | vst3host fuzz: 20 hostile inputs → codes 2–5 | measured: engine/tests/test_runtime_host.py |
| 4.1 | probes at 44.1/48/96 kHz × blocks 32…1024, one parameter at a time; measurements.json | measured (Linux, fixture): 79 renders, 0 failures; ramp probe carries a settle lead-in (D-017) after the fits exposed the original's 20 ms parameter smoothing |
| 4.2 | fit by residual; evidence_source/ + human_source/; gates in code | measured: default ramp → `tanh_normalized` (RMSE 6.85e-5, tie with `tanh` broken by law simplicity); laws recovered one-at-a-time: inputGain dB→pre, outputGain dB→post, drive ∝ plain value, Mode Clean=linear 0.5012 / Hot=×2, bypass=passthrough, oversample=no static effect, cutoff=unmodeled (filter); Active gets the module only at ≤ 1e-4 RMSE; FIDELITY refused without VERIFIED_RUNTIME identity (test) |
| 4.3 | SURROGATE build + pluginval ≥ 5 + differential harness | measured (Linux, g++/Ninja/JUCE 8.0.9): BUILT in 120 s, 0 errors; pluginval 1.0.4 strictness 5 PASSED (16 tests, GUI skipped); state cross-load CROSS_LOAD_VALIDATED both ways (7/7 params) |
| 4 exit | fixture waveshaper BEHAVIORALLY_EQUIVALENT (RMSE ≤ 1e-4, spectrum ≤ 0.1 dB) with build + pluginval green | measured: Waveshaper (default ramp) BEHAVIORALLY_EQUIVALENT — RMSE 6.85e-5, Δspectrum 0.0002 dB; sweeps PERCEPTUALLY_CLOSE (worst 3.4e-4 at Hot/+24 dB drive: fractional-sample latency of the original's oversampling FIR, recorded as a TODO); filter / oversampling / whole plugin FAILED as expected (scaffolds, not compiled); MSVC variant pending-windows; owned SP plugin blocked (B-003) |
| 1.6 (re-measured, D-022) | stripped fixture → static bundle; GROUND_TRUTH_REPORT phase-1 thresholds | measured on the **truly stripped** ELF (`.symtab` 0, `-fvisibility=hidden`): RTTI 5/5 — 0 from v2 static (no `_ZTS` symbols), 5 as `CANDIDATE_TYPEINFO_STRING` from the AB typeinfo-name scan; resources 3/3, BinaryData names 3/3, `<PARAM>` keys 7/7, 0 illegal paths, 0 keys promoted. The earlier 1.6 row measured a build that still carried its symbol table |
| 2.1–2.2 (re-measured) | runtime + state-differential on the stripped build | measured: identity/params/state gates all PASS on the stripped build (phase 2 OK); SDK validator 47/47 PASSED as the second validation source |
| A1 | doctor lists every dependency with version, licence, pinned hash; LIEF inventory reproduces v2 `pe` | measured: `dep:*` rows for lief/capstone/tlsh/yara/numpy/jsonschema + `tool:*` rows incl. validator and juce; `v2_pe_crosscheck` MATCH on the synthetic PE fixture (exports walked v2-style: LIEF refuses the hand-made table) and on the fixture ELF; corpus fixtures blocked (B-001) |
