# How to use this corpus in the standalone SPEC

## 1. Known-library cache seed

Seed only safe knowledge:

- framework/runtime classifications;
- third-party namespace/dependency hints;
- resource hashes;
- class-name family hints;
- standard algorithm candidates from `observed_symbols.json`.

Do **not** seed any generic reference implementation as `IMPLEMENTATION_VERIFIED`.

## 2. Candidate generation

When Ghidra/runtime evidence yields a DSP class/function:

1. Find the symbol in `catalog/observed_symbols.json`.
2. Load its `reference_component` as one or more clean-room candidate families.
3. Fit/configure those candidates against original-plugin probes.
4. Reject candidates whose residuals/latency/state behavior disagree.
5. Only promote the surviving implementation after differential validation.

## 3. State/parameter interpretation

`catalog/parameter_state_catalog.json` contains all static IDs aggregated from the 21 test packages. They remain state/schema observations until the native host confirms VST3 export.

Useful fields for the spec:

- `semantic_hint`
- `plugin_count`
- indexed state-field pattern
- runtime export status (initially UNVERIFIED)

## 4. Family-aware recovery

`plugin_families.json` provides Gen A/B/C hypotheses. Use them to prioritize fingerprint matching, never to bypass it.

## 5. Clean-room boundary

This repository should live in the standalone project as a **reference/inference library**, separate from:

- `evidence/` recovered from binaries;
- `reconstruction/evidence_source/` derived from decompiler output;
- `reconstruction/Source/Active/` validated project code.

Suggested destination:

`reference/music_reference_corpus/`

## 6. Best use in an agent prompt

Tell the coding agent:

> Use the clean-room music reference corpus to propose standard DSP hypotheses. Do not copy a reference component into Active/ merely because a class name matches. Require static/runtime evidence and original-vs-rebuild behavioral validation.
