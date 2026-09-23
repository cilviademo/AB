# CLAUDE.md — AB (Artifact Bench)

AB recovers a compiled audio plugin into a portable, buildable, evidence-backed
source project, and transforms it when the owner asks. `docs/SPEC.md` is the
contract, `docs/EXECUTE.md` the ordered directives with gates; the addenda amend
them in place — `EXECUTE_ADDENDUM_A.md` (dependency stack, cumulative knowledge
base, Git checkpoints, iPlug2 fixture), `EXECUTE_ADDENDUM_B.md` (post-build
hardening pass, after Phase 4), `EXECUTE_ADDENDUM_C.md` (context model,
full-system recovery incl. licensing, transformation), `NAMING_CANONICALIZATION.md`
(identifier transformation layer). `docs/AB_BRIEF.md` is the product brief. When
they disagree, SPEC wins; every deviation is recorded in `docs/DECISIONS.md`.
Reading order for a fresh session: SPEC → EXECUTE → A → B → C → naming.
Project history and corpus priors: `docs/CLAUDE_CODE_PROMPT.md` (read it once).

## Standing instructions (from EXECUTE.md)
- **Static Recovery v2 is frozen.** `app/static-engine/` is a port of
  `handoff/static-engine/plugin-recovery-bench.v2.html`; never "improve" it.
  Any change there must pass `ab-cli diff-baseline` (fixtures/static_v2) first.
- **No invention.** Never write `VERIFIED` for anything not read from an
  authoritative artifact or a runtime API. Never invent identity, FUIDs,
  plugin/manufacturer codes, ranges, defaults, class names, paths, algorithms
  or licensing logic. Unknown stays `UNKNOWN`.
- **Every JSON is wrapped** `{schema, schema_version, tool, generated, data}`
  and validated against `engine/ab_engine/contracts/`. Frozen v2 files keep
  `recovery.*` / `schema_version: 2`; new files use `artifactbench.*` / `1`.
  Unknown major versions are rejected, never reinterpreted.
- **No ownership gate, no ownership assumption (SPEC rule 9, Addendum C1).** The same
  pipeline runs on every artifact by technical capability. Two orthogonal metadata
  fields govern only how reports read: `usage_context` (`USER_RECOVERY` default ·
  `KNOWN_SOURCE_FIXTURE` · `BLACK_BOX_REFERENCE` · `SOURCE_AVAILABLE_REFERENCE` ·
  `UNKNOWN_CONTEXT`) and `source_availability` (`SOURCE_UNKNOWN` default ·
  `SOURCE_UNAVAILABLE` · `SOURCE_PARTIAL` · `SOURCE_AVAILABLE` ·
  `KNOWN_SOURCE_GROUND_TRUTH`). Known-source fixture source is withheld from
  recovery stages (benchmark integrity); reference code is never copied into a
  user project unless the user explicitly chooses. No code path branches on an
  ownership flag.
- **Licensing is a normal subsystem.** `LICENSING_AND_ENTITLEMENT_SUBSYSTEM` (the
  frozen static engine still emits `PROTECTED_SUBSYSTEM`; alias it) is recovered,
  reconstructed, transformed and validated like DSP. `validate → true` is a
  `TRANSFORMED_BREAKING` transformation, recorded in the transformation graph,
  never labelled recovery and never silent.
- **Names are evidence + transformable identifiers.** Original identifiers stay
  under evidence/provenance forever; reconstructed/transformed source may use
  canonical names through a reversible `identifier_map.json`. Parameter IDs,
  state keys and identity are never renamed silently (compatibility/migration
  maps). No naming-based capability gate.
- **Plugins are untrusted.** Only `native/vst3host` loads a plugin. If you find
  yourself writing `LoadLibrary` / `ctypes.CDLL` on a plugin anywhere else, stop.
  Workers run isolated: timeout, temp cwd, scrubbed env, captured stdout/stderr,
  exit code, crash state. A plugin crash fails its stage only.
- **Repo buildable at every commit**: `app` (`npm run build`), `engine`
  (`pytest`), `native` (`cmake --build`) each have a one-command build.
- Commit small. Message format: `phase-N: <area>: <change>`; paste the gate
  result for the EXECUTE step into the body.
- Mirror Prosody's shell pattern (Tauri 2 + React/TS/Vite, Python sidecar
  bundled with PyInstaller, ZIP with a single `AB.exe`) and its UI language.
- `reference/music_reference_corpus_21/` is a clean-room candidate library and
  vocabulary. Nothing from it enters `Active/` on a name match.

## Evidence vocabulary (mandatory on every recovered/generated item)
Evidence: `VERIFIED` · `INFERRED` · `CANDIDATE` · `GENERATED` · `UNRECOVERABLE`
Validation: `BIT_EXACT` · `NUMERICALLY_EQUIVALENT` · `BEHAVIORALLY_EQUIVALENT`
· `PERCEPTUALLY_CLOSE` · `STRUCTURALLY_PLAUSIBLE` · `SCAFFOLD_ONLY` · `FAILED`
Completeness: `FAST_SCAN_COMPLETE` · `FAST_SCAN_EARLY_TERMINATED`
· `DEEP_SCAN_COMPLETE` · `SCAN_INCOMPLETE`
Resources: `VALID_EXACT` (= `PARSER_VALID` + `BOUNDARY_VERIFIED`) ·
`PARSER_VALID` · `BOUNDARY_VERIFIED` · `CARVED_PARTIAL` ·
`SPRITE_SHEET_CANDIDATE` · `DUPLICATE` · `INVALID` · `UNKNOWN`
Parameters: `VST3_EXPORTED_PARAMETER` · `STATE_SCHEMA_FIELD` · `PRESET_FIELD`
· `UI_ONLY_CONTROL` · `UNKNOWN_PROPERTY`; static hint `STATE_FIELD_CANDIDATE`.
Serialized values are `observed_serialized_values`, `value_representation:
UNKNOWN` until the state-differential harness resolves them.
Lineage: `SHARED_NAME` → `SHARED_ARCHITECTURE_CANDIDATE` →
`SHARED_IMPLEMENTATION_CANDIDATE` → `SHARED_IMPLEMENTATION_VERIFIED` (needs
function/vtable fingerprints; a name is never enough). Families are
`INFERRED_CODEBASE_FAMILY`.
Cache: `KNOWN_FRAMEWORK` · `KNOWN_THIRD_PARTY` · `KNOWN_SHARED_INTERNAL` ·
`KNOWN_PLUGIN_SPECIFIC` · `UNKNOWN`; keyed by fingerprints, never by name; a
match is downgraded and re-analysed on any contradiction.
Licensing: `LICENSING_AND_ENTITLEMENT_SUBSYSTEM` (alias of v2 `PROTECTED_SUBSYSTEM`);
validation `LICENSE_BEHAVIOR_MATCHED` · `LICENSE_STATE_COMPATIBLE` ·
`LICENSE_MIGRATION_VALIDATED` · `LICENSE_TRANSFORMED` · `LICENSE_REQUIRES_MANUAL_REVIEW`.
Transformation status: `RECOVERED_EXACT` · `RECONSTRUCTED` · `MODERNIZED_EQUIVALENT` ·
`TRANSFORMED_COMPATIBLE` · `TRANSFORMED_WITH_MIGRATION` · `TRANSFORMED_BREAKING` ·
`UNRECOVERABLE`; behaviours `ORIGINAL_BEHAVIOR` / `RECOVERED_BEHAVIOR` /
`TRANSFORMED_BEHAVIOR` stored separately. Recovery goal: `PRESERVE ORIGINAL`
(default) · `MODERNIZE` · `MIGRATE` · `REFACTOR` · `PORT` · `REBUILD`.
Naming: `PRESERVE_ORIGINAL_NAMES` (evidence) · `CANONICALIZE_NAMES` (transformed
source default) · `CUSTOM_RENAME_MAP`.

## Rules learned the hard way (each shipped as a bug once — see CLAUDE_CODE_PROMPT §2)
- Parameters come only from XML keys (static) or the runtime host; bare strings
  are `CANDIDATE_STRINGS` evidence, never parameters.
- BinaryData mapping is content-based only (font name table, singleton, or
  `getNamedResource` decompile). Never by declaration order.
- Resource carving is structural (PNG chunk walk, RIFF chunk walk, sfnt table
  directory, balanced XML); signatures alone are never trusted; hit counts capped.
- Never `push(...hugeArray)`; use loops/concat. Applies in TS and Python.
- Fast paths record completeness and can trigger `DEEP_SCAN` (SPEC §6.3).
- Paths are classified `PROJECT_SOURCE | FRAMEWORK | SDK | CRT | BUILD_TOOL |
  BUILD_MACHINE | UNKNOWN`; word boundaries in every keyword classifier.
- Role classification tokenizes CamelCase; roles are `CANDIDATE` with a
  `role_basis` until the callgraph confirms them.
- `usage_context` / `source_availability` are stored in
  `00_manifest/input_manifest.json`; they change wording ("binary-derived" vs
  "validated against known source"), never what runs. (The former ownership gate
  is gone — D-026.)

## Layout (SPEC §3, at repo root)
`app/` Tauri+React shell and `app/static-engine/` · `engine/` Python sidecar
(`ab_engine` package, `ab-cli`; source tree `evidence_source/` ·
`recovered_source/` (formerly `human_source/`) · `transformed_source/` ·
`Source/Active`) · `native/vst3host/` · `ghidra/` ·
`reference/` · `fixtures/{groundtruth,static_v2}` · `tools/` · `docs/` ·
`handoff/` (frozen originals, read-only).

## Commands
```
cd app && npm ci && npm run build            # tsc + vite; static engine tests: npm test
cd app/src-tauri && cargo check --target x86_64-pc-windows-msvc
cd engine && pip install -e ".[dev]" && pytest -q
ab-cli doctor | run --stage static <file> | diff-baseline | export <job>
```

## When unsure
Pick the reversible default, record it in `docs/DECISIONS.md`, keep going. A
blocker that needs the owner goes in `docs/BLOCKERS.md` with the options listed.
Owner decisions still open: VST3 SDK licence for distribution, fixture binaries,
SP plugin location, BTZ fixture, GitHub usage.
