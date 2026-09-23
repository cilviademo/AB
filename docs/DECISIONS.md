# DECISIONS

Every deviation from `SPEC.md` / `EXECUTE.md` / `AB_BRIEF.md`, with the reason.
Architecture is never changed silently: a reversed decision is edited here.

## D-001 Product name: AB — Artifact Bench
SPEC uses the working name Palimpsest and says "rename freely; nothing depends
on it". The owner's brief (`docs/AB_BRIEF.md`) fixes the name as **AB —
Artifact Bench**, tagline *Recover. Reconstruct. Rebuild.* Top-level branding
never says "Plugin Recovery Bench"; that phrase survives only as a functional
description. Consequences: executable `AB.exe`, Tauri identifier
`com.multibanded.ab`, Python package `ab_engine`, CLI `ab-cli` (EXECUTE's
`palimpsest-cli` commands exist verbatim under `ab-cli`), app-data folder
`%LOCALAPPDATA%\AB`.

## D-002 Repository layout is SPEC §3 at the repository root
The repo *is* the product, so `palimpsest/` in SPEC §3 maps to the repo root:
`app/`, `engine/`, `native/`, `ghidra/`, `reference/`, `fixtures/`, `tools/`,
`docs/`. `handoff/` holds the frozen originals (v2 HTML, v1 kit) read-only.

## D-003 Prosody is a UX/UI and packaging pattern, not a code fork
The owner said Prosody is a separate repo; AB lives here and mimics Prosody's
UX/UI. Prosody was cloned read-only and its design tokens, base/component CSS,
UI primitives, titlebar/nav shell, stdio JSON-lines supervisor, path policy,
WebView2 check, PE runnability check and portable-ZIP packaging were re-created
here under AB names (same owner, same licence). FL-specific code was not
copied. SPEC §14 adds one thing Prosody's monochrome system lacks: fixed
evidence-state colours (VERIFIED green, INFERRED amber, CANDIDATE grey,
GENERATED blue, UNRECOVERABLE red-strike). They are the only hues in the
product and are defined once in `app/src/styles/tokens.css`.

## D-004 Schema naming: frozen v2 keeps `recovery.*` v2; new contracts are `artifactbench.*` v1
SPEC §6.1 preserves all v2 contracts as `schema_version: 2` under `recovery.*`
and §17 lists every contract under `recovery.*`. The brief asks for
`artifactbench.<name>` with `schema_version: 1`. Both are honoured: files the
frozen static engine emits keep their exact v2 identity (baselines diff on
them), and every contract introduced by AB (runtime, correlation, fingerprints,
callgraph, lineage, validation, ground truth, manifests, stage records) is
`artifactbench.<name>` v1. The contract validator knows both prefixes; an
unknown major version is rejected.

## D-005 Static engine runs in two hosts: webview Worker (GUI) and Node (CLI/CI)
SPEC §2 puts the frozen TS engine in a Web Worker. `ab-cli run --stage static`
and `diff-baseline` must run headlessly and in CI, and PyInstaller cannot run
JavaScript, so the same pure-TS modules are also bundled as a Node entry
(`app/static-engine/dist/cli.mjs`). The Python engine spawns Node when present
and reports `STATIC_ENGINE_UNAVAILABLE` (with the GUI as the alternative) when
not. Analysis code is identical in both hosts; only the transport differs.

## D-006 Browser-only validation replaced by structural parsers, same verdicts
v2's `validateResources` used `Image`, `DOMParser` and `crypto.subtle`. The
port rules forbid DOM. Replacements return the same fields and states:
PNG dimensions from IHDR; JPEG dimensions from the SOF marker; a full-document
XML/SVG well-formedness parser (balanced tags, quoted attributes) for
`CARVED_PARTIAL` vs `VALID_EXACT`; SHA-256 via WebCrypto in the worker and
`node:crypto` under Node. The sprite-sheet rule (h ≥ 4w, frame heights w, 1.5w,
2w) is unchanged. These are recorded as the one intentional behavioural delta
of the port and are covered by unit tests.

## D-007 Regression baselines are generated from the owner's four binaries; a synthetic PE fixture covers the port meanwhile
The four corpus binaries are not in the handoff. `fixtures/static_v2/` is
populated the first time they are dropped (EXECUTE 1.4 first task). Until then
the port is verified against a deterministic synthetic PE fixture built by
`fixtures/synthetic/make_fixture.py` (a real PE layout with RTTI descriptors, an
embedded APVTS XML, PNG, TTF, WAV and BinaryData names). It is test data, never
evidence, and is labelled as such in every output. See BLOCKERS B-001.

## D-008 Windows-only gates run on the studio PC; Linux runs everything else
This session runs on Linux. The Tauri shell is type-checked for
`x86_64-pc-windows-msvc`; `vst3host` and the ground-truth fixture are also
built for Linux here so the runtime, correlation and behavioural stages can be
exercised end to end against a real plugin build. PE-specific gates (stripped
MSVC build, MSVC RTTI in Ghidra, pluginval on Windows, `AB.exe` launch from a
clean ZIP) are scripted (`fixtures/groundtruth/build_all.ps1`,
`scripts/build-release.ps1`) and marked pending in `docs/STATUS.md` until run
on Windows. Nothing is reported green that was not run.

## D-009 UI stage rail includes INGEST; screens follow the brief
SPEC §14 rail starts at STATIC. The brief adds `INGEST`. Rail: `INGEST · STATIC
· RUNTIME · DECOMPILE · PROBE · RECONSTRUCT · BUILD · COMPARE · EXPORT`. Screens
are the brief's superset of SPEC's: Recover, Overview, Evidence, Parameters &
State, Architecture, DSP, Resources, Compare, Build, Corpus, Export. Screens
whose stage is not yet implemented show the stage that populates them and
nothing else; no placeholder data.

## D-010 Role vocabulary is the union of SPEC §8.2 and the brief
`PITCH_TIME` and `MODULATION` (brief) join SPEC's list; v2's static role names
(`DELAY_REVERB`, `ENVELOPE`, `STATE_CONTROL`) are preserved unchanged inside
the frozen engine and mapped to the final vocabulary in the engine when the
callgraph stage promotes a role. `STRUCTURALLY_PLAUSIBLE` (brief, help doc) is
part of the validation vocabulary.

## D-011 Python 3.11 in the engine, pydantic-free contracts
SPEC fixes Python 3.11. Contracts are JSON Schema files under
`engine/ab_engine/contracts/` validated with `jsonschema`; dataclasses carry
them in code. Prosody's pydantic pattern was not adopted because the contracts
are shared with the TS engine and Ghidra scripts, which read the schema files
directly.

## D-012 The v2 bundle plan omits `recovery_kit/`; the kit stays frozen in `handoff/kit`
The browser bundle shipped `recovery_kit/{vst_recover.py, ExportDecompiled.java,
run_recovery.ps1, run_recovery.sh}` as the interim desktop stage (pedalboard +
Ghidra). AB *is* that desktop stage, so the port does not emit the kit into
recovery bundles (it would tell an agent to run tools AB already runs). The
frozen kit remains in `handoff/kit/`; `vst_recover.py`'s pedalboard path stays
available as a diagnostic fallback only. `recovery_kit/` is not a §6.1
contract, so baselines are unaffected. Also not part of the plan: the archive
root prefix (`<Name>_RECOVERED/`) — the engine names project folders.

## D-013 Short BinaryData names
v2's BinaryData-name rule needs ≥ 3 characters before the `_ext` suffix, so a
resource named `bg_png` is not recognised statically. Kept as-is (frozen);
Phase 3's `namedResourceList` decompile recovers such names from the binary.

## D-014 JUCE plugin/manufacturer codes are read from the FUID, with the rule recorded
JUCE's VST3 wrapper builds its class IDs as `FUID(0xABCDEF01, 0x9182FAEB,
ManufacturerCode, PluginCode)` (component) and `FUID(0xABCDEF01, 0x1234ABCD,
…)` (controller). When a factory reports IDs of that shape, the two
four-character codes are present in the bytes and are reported as
`VERIFIED_RUNTIME (JUCE FUID derivation)` with the derivation string beside
them — never as a guess. Both FUID byte layouts (COM and inline) are tried and
the one reproducing the magic words wins. Non-JUCE FUIDs leave the codes
`UNKNOWN`; FIDELITY builds then need them from the owner.

## D-015 The JUCE wrapper's own bypass parameter is reported, not hidden
JUCE's VST3 wrapper adds a `Bypass` parameter (`kIsBypass`) that does not
live in the APVTS state. It is a real exported parameter, so it stays in
`runtime_parameters.json` and maps as `RUNTIME_ONLY`; the ground-truth
comparator ignores it for false-positive counting and never lets it shadow a
plugin parameter of the same title.

## D-016 State-only ValueTree properties are found by the runtime stage
JUCE serialises non-parameter ValueTree properties as root attributes. The
frozen v2 extractor reads `<PARAM>` entries only, so those properties appear
in `03_architecture/serialized_properties.json` (runtime `getState`) rather
than in the static `serialized_keys.json`. The Phase 1 gate counts `<PARAM>`
keys; a Phase 2 gate counts all fields from static ∪ runtime.

## D-017 — Ramp probe carries a settle lead-in
The reference `amplitudeRamp` is a single linear sweep. Measured on the ground-truth fixture, the first ~20 ms of every ramp render reflected parameter smoothing (JUCE `SmoothedValue`, 20 ms) and oversampling-filter start-up, which corrupted the head of every transfer curve and pushed the fits (input gain −24 dB: RMSE 3.7e-2 instead of ~4e-5). AB's `ramp` probe therefore ramps 0 → −4 over its first half (settle), then sweeps −4 → +4 over the second half; the transfer curve is taken from the second half only, in both `vst3host` (`abprobe::rampLeadIn`) and `ab_engine.behavior.probes.ramp_lead_in`. Ramp renders use 16384 frames so the measured half keeps 8192 samples. The probe *set* is unchanged; only the ramp's shape and the extraction window differ from the reference corpus, and every measurement file records the probe request so this is auditable.

## D-018 — Differential harness: measurement window and level scaling
Sample-level comparison of a ramp render is classified on the probe's measurement window (the second half, after the settle lead-in of D-017); the lead-in error is reported separately per render and per module (`lead_in_rmse`). Reason: the original smooths parameter changes (~20 ms) while a fitted module applies them per block; that transient is a real, separately reported difference, but it must not mask whether the static transfer is right. Signals whose original peak exceeds 1.0 are scaled to that peak before the error is taken, so the absolute thresholds (RMSE ≤ 1e-4 …) mean the same thing at +24 dB as at 0 dB; signals at or below unity are never scaled up. Non-ramp probes are always classified on the full render (an impulse's transient is the behaviour).

## D-019 — Module proof vs parameter-law sweeps
`Waveshaper` in `differential_results.json` is the fitted module at the verified default (the amplitude ramp with no parameter moved) — the EXECUTE 4.3 gate. Every one-parameter sweep is classified separately as `Law:<key>` and aggregated as `WaveshaperSweeps`; `Unmodeled:<key>` collects sweeps of parameters whose effect is not a static transfer change (e.g. a filter cutoff). A module reaching BEHAVIORALLY_EQUIVALENT at the default while its sweeps stay PERCEPTUALLY_CLOSE is reported exactly that way, with the failing renders named, never rolled into one verdict.
