# Ground-truth fixture #2 — iPlug2 (EXECUTE_ADDENDUM_A §A5)

Same content as `fixtures/groundtruth` (the JUCE fixture) — 7 parameters, one TPT low-pass, one
normalised tanh waveshaper, 2× oversampling toggle, a PNG, a TTF, a preset XML and a deliberate
`LICENSING_AND_ENTITLEMENT_SUBSYSTEM` stub (serial check + demo state) — built with **iPlug2** so the engine is proven not to be
"JUCE recovery". `gen.py` derives `GeneratedParams.h` and `truth.json` from the *same*
`../groundtruth/spec.json`; only the framework, the product name (`ABGroundTruthIP`) and the
plugin code (`Abgi`) differ.

## Status
**Not built in the development environment (BLOCKERS B-008).** iPlug2 targets Windows and macOS;
its Linux VST3 build is not maintained. `build_all.ps1` clones iPlug2 and its dependencies and
builds Release+PDB and Release-stripped on the studio PC. Nothing here has been compiled or
measured yet; gate A5's second `GROUND_TRUTH_REPORT.json` is pending-windows.

## Build (Windows)
```
fixtures\groundtruth_iplug2\build_all.ps1        # clones iPlug2 (pinned), runs gen.py, builds out\release and out\stripped
ab-cli ingest --context KNOWN_SOURCE_FIXTURE --source-availability KNOWN_SOURCE_GROUND_TRUTH out\stripped\ABGroundTruthIP.vst3
ab-cli run <job> --stage INGESTED --stage STATIC_COMPLETE --stage RUNTIME_COMPLETE
ab-cli --text ground-truth <job> --truth fixtures/groundtruth_iplug2/truth.json --phase 2
```

## What differs from the JUCE fixture, by design
- No JUCE symbols, no APVTS, no `BinaryData` namespace: resources are embedded through the
  platform's resource mechanism (Windows `.rc`), so the BinaryData-name gates are expected to
  report `NOT_APPLICABLE`, and `AB.Framework.JUCE` must not fire (A4).
- VST3 parameter ids are the parameter indices (iPlug2), not a hash of a string id.
- State: iPlug2's chunk serialisation carries the two state-only fields
  (`waveShapers_0_1`, `uiScale`) after the parameter values; they are never exported.
