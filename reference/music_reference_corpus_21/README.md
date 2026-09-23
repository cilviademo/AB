# Music Reference Corpus — 21-plugin clean-room DSP index

This is a **clean-room reference package** derived from the 21-plugin Static Recovery v2 corpus. It is intended to be placed beside the standalone recovery-engine specification so a coding agent has concrete, standard musical DSP implementations and a machine-readable symbol/state lookup catalog.

It contains:

- **33 standard DSP/reference components** in portable C++17;
- **657 observed class/symbol mappings** from the corpus;
- **946 static XML/state IDs** aggregated across the 21 test plugins;
- the Gen A / Gen B / Gen C corpus family hypotheses;
- standard probe-signal generation for behavioral testing;
- no recovered proprietary function bodies.

## Build

```bash
cmake -S . -B build
cmake --build build
./build/musicref_smoke
```

## Primary files

- `include/musicref/` — generic reference DSP code
- `catalog/observed_symbols.json` — every recovered corpus symbol mapped to a clean-room reference/dependency/metadata category
- `catalog/parameter_state_catalog.json` — all observed static state IDs, explicitly not assumed to be VST3 parameters
- `catalog/plugin_families.json` — lineage hypotheses
- `docs/SPEC_INTEGRATION.md` — how the standalone app should consume the package
- `REFERENCE_NOTICE.md` — provenance boundary

## Recommended role

Use this as **candidate code and vocabulary** for reconstruction. Runtime VST3 metadata, Ghidra evidence, function fingerprints, and differential audio tests remain authoritative.
