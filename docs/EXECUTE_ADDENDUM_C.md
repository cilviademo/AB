# EXECUTE_ADDENDUM_C.md — Context model, full-system recovery, transformation
### Read before Phase 1 (it defines metadata every stage writes). Implement transformation in Phase 5. Supersedes any earlier "protected subsystem" or "assume owned" wording.

**Principle:** Artifact Bench recovers what survived, infers what evidence supports, reconstructs what was lost, transforms it when the owner asks, and measures every result against the surviving artifact. The subsystem being recovered — DSP, UI, state, presets, serialization, build code, licensing, activation, update infrastructure — never changes that discipline.

---

## C1. Context metadata (orthogonal to the pipeline)

AB does not require, request, or infer an ownership decision, and it never disables a technical capability. Two fields are recorded per artifact/project and propagate into every report:

`usage_context` — `USER_RECOVERY` (default) · `KNOWN_SOURCE_FIXTURE` · `BLACK_BOX_REFERENCE` · `SOURCE_AVAILABLE_REFERENCE` · `UNKNOWN_CONTEXT`
`source_availability` — `SOURCE_UNKNOWN` (default) · `SOURCE_UNAVAILABLE` · `SOURCE_PARTIAL` · `SOURCE_AVAILABLE` · `KNOWN_SOURCE_GROUND_TRUTH`

```json
{ "usage_context": "USER_RECOVERY",        "source_availability": "SOURCE_UNAVAILABLE" }
{ "usage_context": "KNOWN_SOURCE_FIXTURE", "source_availability": "KNOWN_SOURCE_GROUND_TRUTH" }
```

Effects (interpretation only):
- `KNOWN_SOURCE_FIXTURE`: source is withheld from every recovery stage and read only by the evaluator (benchmark integrity).
- `BLACK_BOX_REFERENCE`: full STATIC → RUNTIME → DECOMPILE → FINGERPRINT → PROBE → COMPARE runs; reports label results "binary-derived reconstruction"; reconstructed third-party code (licensing included) is reference evidence and is not auto-exported into a user project.
- `USER_RECOVERY`: every supplied artifact is evidence for maximum recoverability — binary, PDB, MAP, source fragments, presets, DAW sessions, assets, older builds, installers, documentation.

**Gate C1:** no code path branches on an ownership flag; every JSON report and every UI status carries both fields; the mixed-drop acceptance test (Addendum B) shows identical stage execution for all contexts.

---

## C2. Full-system recovery — licensing is a normal subsystem

Classification `LICENSING_AND_ENTITLEMENT_SUBSYSTEM` (alias for the frozen static engine's `PROTECTED_SUBSYSTEM` label) covers serial validation, licence-file parsing, entitlement/activation/demo/trial state, machine binding, feature flags, offline/online activation interfaces, licence persistence, licence UI, error states, registration and authentication.

Treatment is identical to every other subsystem: **recognize → isolate architecturally → preserve provenance → recover interfaces → recover state/data relationships → reconstruct implementation when evidence supports it → transform when the goal asks → validate.** If a PDB names `LicenseManager`, use it; if RTTI reveals it, use it; if decompilation recovers `SerialValidator::check`, retain it; if source fragments exist, correlate them; if the original still runs, compare behavior.

**Reconstruction ≠ bypass.** Turning `licenseValid = validateLicense(...)` into `licenseValid = true` is a behavioral modification. It may be an explicit transformation the owner chooses (status `TRANSFORMED_BREAKING`, recorded in the transformation graph) but is never labelled recovery and never happens silently. Reconstruction records use the ordinary evidence states:

```json
{ "symbol": "LicenseManager::validate", "classification": "LICENSING_AND_ENTITLEMENT_SUBSYSTEM",
  "recovery_status": "STATIC_RECONSTRUCTED", "confidence": 0.81 }
```

**Licensing validation states:** `LICENSE_BEHAVIOR_MATCHED · LICENSE_STATE_COMPATIBLE · LICENSE_MIGRATION_VALIDATED · LICENSE_TRANSFORMED · LICENSE_REQUIRES_MANUAL_REVIEW`. Test where applicable: valid, invalid, expired, missing, offline, machine mismatch, corrupt file, feature entitlement, trial/demo, legacy migration, serialization/restore, restart persistence — original vs reconstruction whenever the original runs.

**Licence data migration:** `OLD_LICENSE_FORMAT → PARSE → NORMALIZED_ENTITLEMENT_MODEL → NEW_LICENSE_FORMAT`, preserving original hash, original fields, mapped fields, unmapped fields and migration decisions. Unknown licence data is never discarded.

**Gate C2:** the ground-truth fixture's licensing stub (serial check + demo state) is recovered with the same metrics as its DSP; a deliberate bypass edit in a test project is detected and reported as `TRANSFORMED_BREAKING`.

---

## C3. Transformation as a first-class capability

Recovery does not stop at "reproduce the old project." After evidence recovery the owner selects a **recovery goal** — `PRESERVE ORIGINAL` (default) · `MODERNIZE` · `MIGRATE` · `REFACTOR` · `PORT` · `REBUILD` — with per-subsystem preservation switches (e.g. *preserve DSP behavior: YES · preserve preset compatibility: YES · preserve legacy licence format: OPTIONAL · replace activation backend: YES*).

Typical transformations: legacy C++ → modern C++; old JUCE API → current; custom state code → maintainable state layer; old build system → CMake; obsolete activation server → owned entitlement backend; old serial-file format → new licence schema; machine-specific paths → portable config; deprecated APIs → current; monolithic DSP → modules.

**Transformation graph per subsystem (all nodes retained):**
`binary evidence → recovered implementation → semantic reconstruction → transformed implementation → validation`

**Stored separately, never merged:** `ORIGINAL_BEHAVIOR` · `RECOVERED_BEHAVIOR` · `TRANSFORMED_BEHAVIOR`. Behavioral changes are always recorded:

```json
{ "subsystem": "Licensing", "original_state": "RECOVERED", "transformation": "LEGACY_SERVER_REPLACED",
  "behavioral_compatibility": "PARTIAL", "migration_required": true }
```

**Status model** (UI + exported metadata): `RECOVERED_EXACT · RECONSTRUCTED · MODERNIZED_EQUIVALENT · TRANSFORMED_COMPATIBLE · TRANSFORMED_WITH_MIGRATION · TRANSFORMED_BREAKING · UNRECOVERABLE`.

**Source output:**
```
04_reconstruction/
  evidence_source/      binary/decompiler representation
  recovered_source/     closest semantic reconstruction of the original
  transformed_source/   modernized / migrated / ported implementation
  Source/Active/        the implementation currently being built
  Source/RecoveredScaffolds/
```

**Artifact transformation** (originals always preserved under `evidence/original/`, results under `transformed/`): embedded BinaryData → files; old preset XML → documented schema; old preset format → migrated presets; PDB/MAP → symbol database; old VS project → CMake; old resources → portable resource tree; DAW state → parameter/state evidence; legacy installer assets → documented dependency package.

**Validation of transformed artifacts:** DSP original render vs transformed render · old state loads into reconstruction · old preset → migrated preset → equivalent settings · resources hash/decode/render · legacy licence → transformed entitlement → expected feature state · old artifact behavior vs new binary. Comparisons: ORIGINAL↔RECOVERED, RECOVERED↔TRANSFORMED, ORIGINAL↔TRANSFORMED (a modernization may differ architecturally while preserving external behavior; measure it).

**Knowledge base:** distinguish `ORIGINAL_IMPLEMENTATION_KNOWLEDGE` · `RECOVERED_IMPLEMENTATION_KNOWLEDGE` · `TRANSFORMED_IMPLEMENTATION_KNOWLEDGE`; never overwrite one with another (Addendum A versioning applies).

**Gate C3:** on the ground-truth fixture, goal `MODERNIZE` with "preserve DSP behavior: YES" produces `transformed_source/` that builds, passes the differential harness at ≥ `BEHAVIORALLY_EQUIVALENT` for DSP, and lists every intentional behavioral change with its status; goal `PRESERVE ORIGINAL` produces no transformation nodes.

---

## C4. Where this slots into EXECUTE

| Step | Change |
|---|---|
| 1.3 Ingest | write `usage_context` / `source_availability` into `00_manifest/input_manifest.json`; UI tags optional, defaults applied |
| 1.4 Static | map static `PROTECTED_SUBSYSTEM` role → `LICENSING_AND_ENTITLEMENT_SUBSYSTEM` in the alias table |
| 1.6 Fixture | include the licensing stub (serial check + demo state) in both ground-truth fixtures and in `truth.json` |
| 2–4 | licensing functions scored, decompiled, fitted and validated like any other; licensing validation states added to `06_validation` |
| 5 | recovery goal selector; transformation graph; `recovered_source/` + `transformed_source/`; artifact transformations; three-way comparisons; knowledge tiers |
| Addendum B | acceptance tests run under each `usage_context`; reports checked for "binary-derived" vs "validated against known source" wording |

**Product principle:** SURVIVING ARTIFACTS → RECOVER ORIGINAL SYSTEM → UNDERSTAND IT → RECONSTRUCT IT → TRANSFORM / MODERNIZE IT → VALIDATE AGAINST ORIGINAL → BUILD → EXPORT MAINTAINABLE PROJECT — for the entire project, licensing and entitlement included, with a clear chain back to the original evidence at every node.
