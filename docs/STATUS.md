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
