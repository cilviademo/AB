# EXECUTE_ADDENDUM_A.md — Cumulative knowledge, open-source stack, checkpoints
### Read after SPEC.md and EXECUTE.md. These directives amend the phases in place; they do not replace them.

**Naming.** The product is **Artifact Bench (AB)**. Repo `artifact-bench`, executable `ArtifactBench.exe`, CLI `ab-cli`, app-data folder `ArtifactBench`, schema prefix `ab.` (contracts formerly `recovery.*` become `ab.*`; keep a one-line alias map for Static Recovery v2 files, which stay `recovery.*` as frozen inputs). Earlier drafts used the working name Artifact Bench; treat any remaining occurrence as a typo and fix it.

**Guiding sentence for this addendum:** every owned plugin analysed must make the next one easier, and nothing becomes trusted knowledge because an LLM guessed it.

---

## A1. Dependency stack — adopt, do not reinvent

Add these as the core dependencies. Wrap each behind a small internal interface so any one can be swapped. Record licence and pin version in `docs/DEPENDENCIES.md`.

| Need | Adopt | Licence | Where it slots |
|---|---|---|---|
| PE/Mach-O/ELF/PDB inventory | **LIEF** (Python) | Apache-2.0 | Phase 1 static stage: replaces the hand-written `parsePE`; keeps v2 outputs byte-for-byte compatible via a mapping test |
| Lightweight disassembly + function fingerprints | **Capstone** (Python bindings) | BSD-3 | Phase 3 `fingerprint/`: normalized instruction streams before Ghidra runs |
| Deep RE / decompile / RTTI / callgraph | **Ghidra** headless | Apache-2.0 | Phase 3, unchanged — automated, never replaced |
| VST3 runtime host | **Steinberg VST3 SDK** hosting classes + Validator | MIT (current SDK) | Phase 2 `vst3host.exe`; also run Steinberg's validator as a second validation source |
| Plugin validation | **pluginval** as an external executable only | GPLv3 | Phase 4; never link or copy its code |
| Knowledge index | **SQLite** | public domain | Phase 1 job db; Phase 3+ knowledge db (A2) |
| Exact identity | SHA-256 | — | everywhere |
| Approximate similarity | **TLSH** (py-tlsh) | Apache-2.0/BSD | Phase 3 fingerprints; a *relatedness* signal, never identity |
| Family / pattern recognition | **YARA** (yara-python) | BSD-3 | Phase 3 lineage: rules emit `CANDIDATE_FAMILY` only |
| WDF reference algorithms | **chowdsp_wdf** (header-only) | BSD-3 | `reference/` beside `music_reference_corpus_21` for Gen-B candidates |
| Resampling reference | **libsamplerate** | BSD-2 | `reference/` and probe harness |
| Audio I/O in workers | **miniaudio** or **libsndfile** | MIT-0 / LGPL | probe/render workers; prefer miniaudio (single header) |
| Secondary RE backend | **Rizin** (rz-bin, rz-diff, rz-hash, rz-sign) | LGPL-3 | optional, Phase 5+, only when Ghidra fails or for corroboration |
| Advanced dataflow (parameter→DSP reachability) | **angr** | BSD-2 | Phase 5+ only; do not start it before the one-module proof |
| Second ground-truth fixture framework | **iPlug2** | zlib-like | Phase 1.6b (A5) — proves the engine is not "JUCE recovery" |

Ordering rule for cost: **LIEF → Capstone fingerprints → knowledge cache → Ghidra only on the residual → runtime host → probes → reference candidate → compile → pluginval + Steinberg validator → differential → knowledge promotion.** The expensive tool never runs first.

**Gate A1:** `ab-cli doctor` lists every dependency with version, licence, and pinned hash; LIEF-based inventory reproduces v2 `binary.json` for the four fixtures (diff-baseline clean).

---

## A2. Local knowledge base (cumulative, content-addressed, versioned)

**Layout**
```
%LOCALAPPDATA%/ArtifactBench/knowledge/
  knowledge.db                 # SQLite index
  objects/sha256/ab/cd/<hash>  # bytes: artifacts, carved resources, renders, decompiled text
```
Bytes are stored once by hash; every table row that needs bytes references an object hash. Per-project bundles reference objects; single-project export materializes files.

**Tables (minimum)**
`artifact` (sha256, kind, size, first_seen, last_seen, ownership, compiler_fingerprint) ·
`analysis_run` (run_id, artifact_sha256, tool_versions, stage_versions, config_hash, started, ended) ·
`plugin_identity` (artifact_sha256, vendor, product, version, processor_fuid, controller_fuid, status) ·
`class` (class_id, rtti_name, vtable_fingerprint, ctor_fp, dtor_fp, kind, state) ·
`vtable` (class_id, slot, function_fp) ·
`function` (function_fp_id, raw_sha256, norm_sha256, tlsh, cfg_sig, callgraph_sig, const_sig, strxref_sig, length, role, role_status, state) ·
`function_occurrence` (function_fp_id, artifact_sha256, address) ·
`implementation` (impl_id, name_hint, member function_fp_ids, family_id, state, behavior_ref) ·
`family` (family_id, label, method, state) ·
`resource` (sha256, ext, dims/format, binarydata_name, mapping_status) ·
`parameter` (artifact_sha256, param_id, title, units, step_count, default_norm, flags, tier) ·
`state_field` (artifact_sha256, key, representation, mapped_param_id, relation) ·
`behavior` (behavior_id, impl_id, probe_set_hash, metrics_ref, result_state) ·
`reconstruction` (impl_id, evidence_source_ref, recovered_source_ref, validation_state, rmse) ·
`classification_history` (entity_type, entity_id, previous, current, changed_at, tool_version, evidence_version, reason)

**Versioning rule.** Never mutate a classification in place. Write the new row, append to `classification_history`, keep `first_seen`, `last_verified`, `tool_version`, `evidence_version`. A later run that contradicts earlier knowledge downgrades it and records why.

**Promotion ladder (the only path to trusted reuse)**
`CANDIDATE → STATIC_SUPPORTED → RUNTIME_SUPPORTED → BEHAVIOR_MATCHED → IMPLEMENTATION_VERIFIED`
- `STATIC_SUPPORTED`: fingerprints/RTTI/vtable agree.
- `RUNTIME_SUPPORTED`: parameter/state relationship confirmed by the host.
- `BEHAVIOR_MATCHED`: differential harness ≥ `BEHAVIORALLY_EQUIVALENT`.
- `IMPLEMENTATION_VERIFIED`: normalized function hash + vtable + constants + CFG agree across ≥ 2 binaries **and** behavior matched at least once.
Only `BEHAVIOR_MATCHED` and `IMPLEMENTATION_VERIFIED` may be reused to skip analysis. `CANDIDATE` and `STATIC_SUPPORTED` may only *prioritize*.

**Three stores, never merged:** raw evidence (immutable objects) · reconstructed source (evidence_source / recovered_source / transformed_source, versioned) · validated implementation knowledge (`implementation` rows at `BEHAVIOR_MATCHED`+). Cleaned-up C++ never overwrites evidence.

**Provenance on every reuse decision.** When the app says "appears to be the same implementation as X", the UI and `LINEAGE_REPORT.md` must show: which signatures matched (norm hash, vtable, constants, CFG, TLSH distance), in how many prior binaries, and how many behavior confirmations. A name match alone is never shown as a reason.

**Delta summary.** After matching, every job reports: `known_implementation %`, `near_match %`, `unknown %` (by processBlock-reachable function count and by bytes), and deep analysis is scheduled on the unknown slice first.

**Gate A2:** analysing the ground-truth fixture twice yields a second run with ≥ 80% functions matched `KNOWN_*`; a modified fixture build (one constant changed in the waveshaper) reports that function as `near_match`, not known; `classification_history` shows the downgrade with reason.

---

## A3. Function signature set (compute all, store separately)

Per function: `SHA256(raw bytes)`, `SHA256(normalized instructions)` (Capstone: mask immediates that are relocations/addresses, normalize stack offsets and register allocation where safe), `TLSH(normalized instructions)`, CFG signature (block count + edge-shape hash), constant signature (sorted float/int immediates), string-xref signature, call-target signature (callee norm hashes, depth 1), RTTI/vtable relation. Ghidra results add decompiler-level signatures later; Capstone signatures exist before Ghidra runs so cache matching can short-circuit it.

**Gate A3:** across Debug+PDB, Release+PDB and Release-stripped fixture builds, same-source functions match on norm hash or CFG+constants in ≥ 90% of DSP functions; TLSH distances are reported, never used as a sole match criterion.

---

## A4. YARA family rules

`lineage/rules/*.yar` derived from corpus evidence: RTTI strings, resource names, typo fingerprints (`DisotrtionEffect`, `ParametericEQ`), XML roots, third-party markers (SoundTouch, chowdsp WDF), framework markers (JUCE, VST3 SDK). Rule names `AB.Family.GenA_StudioSafari`, `AB.Family.GenB_MorphWDF`, `AB.Family.GenC_Hammer`, `AB.ThirdParty.SoundTouch`, `AB.ThirdParty.chowdsp_wdf`, `AB.Framework.JUCE`. Output is `CANDIDATE_FAMILY` with matched conditions listed; promotion to `INFERRED`/`VERIFIED` family follows A2.

**Gate A4:** the four fixtures classify to their expected candidate families; the iPlug2 fixture matches no Gen rule and `AB.Framework.JUCE` does not fire on it.

---

## A5. Ingestion matrix and second fixture

**Ingest anything, run everything.** For each dropped item: identify (magic + extension + LIEF), hash, choose parser/worker, attach to the project, record `usage_context`/`source_availability` when known (defaults `USER_RECOVERY`/`SOURCE_UNKNOWN`), and run every applicable stage — capability, not permission, decides. Types: plugin binaries, `.pdb/.map`, presets/state, DAW sessions (`.RPP .als .flp .cpr`), source fragments, CMake/Projucer files, images/fonts/IRs/samples, installers, ZIPs, folders. **Unsupported or unparsed types are preserved in the object store and listed in `00_manifest/input_manifest.json` as `PRESERVED_UNPARSED` — never silently dropped.**

**Second ground-truth fixture in iPlug2** (`fixtures/groundtruth_iplug2/`): same parameter/DSP/resource content as the JUCE fixture, built stripped. Both fixtures run in CI; `GROUND_TRUTH_REPORT.json` is produced for each.

**Gate A5:** one drop containing all listed artifact types produces one project with every item identified or `PRESERVED_UNPARSED`; both fixtures' reports meet the Phase-1 thresholds; nothing JUCE-specific is required for the iPlug2 fixture's static and runtime stages to pass.

---

## A6. Local Git checkpoints (for the reconstructed project only)

Each recovery project is a local Git repo initialized at ingest. The engine commits at stage boundaries with fixed message prefixes:
```
ingest: add recovered artifacts
recovery: import verified runtime metadata
recovery: add RTTI and callgraph evidence
reconstruction: implement <module>
validation: <module> matched original (<state>, rmse=<x>)
build: validated VST3 reconstruction
export: repo-ready bundle
```
Transient analysis events are not committed. Evidence objects are committed by reference (manifest of hashes), large binaries via `.gitignore` + optional LFS recommendation. GitHub push is an explicit user action, never automatic.

**Gate A6:** after a full fixture run the project log shows the sequence above; `git status` is clean; the repo builds from a fresh clone with documented dependencies.

---

## A7. Export is the product; the database is not

Export materializes:
```
<Plugin>_RECOVERED/
  Source/ (Active + RecoveredScaffolds) · Resources/ · CMakeLists.txt
  evidence/ (01_evidence, immutable) · validation/ (06_validation)
  HANDOFF.md · reconstruction_index.json · UNRECOVERABLE.md
```
plus ZIP and the local Git repo. Every claim in `HANDOFF.md` links to an evidence path or a knowledge row id. Knowledge rows used during the run are listed in `evidence/knowledge_used.json` with their promotion state and provenance, so the export is auditable without the database.

**Gate A7:** an exported fixture project builds on a machine without the app installed, and `knowledge_used.json` explains every skipped-analysis decision.

---

## A8. Where these slot into EXECUTE.md

| EXECUTE step | Addendum change |
|---|---|
| 1.2 Job system | add `knowledge.db` schema (A2) and object store path; job db and knowledge db are separate files |
| 1.3 Ingest | ingestion matrix + `PRESERVED_UNPARSED` (A5); Git init + `ingest:` commit (A6) |
| 1.4 Static port | LIEF inventory behind the v2 contract (A1); mapping test against `binary.json` |
| 1.6 Fixture | add iPlug2 fixture (A5) |
| 2.x Runtime | Steinberg validator run alongside `vst3host` (A1); `recovery:` commit |
| 3.2 Ghidra | Capstone fingerprints computed **before** Ghidra; Ghidra scheduled only on unmatched/high-priority functions (A3); YARA candidate families (A4) |
| 3.4 Cache | replace "knowledge/ store" with A2 tables, promotion ladder, history, provenance-on-reuse, delta summary |
| 4.x Proof | promotion to `BEHAVIOR_MATCHED` writes `implementation` + `behavior` rows; `validation:` commit |
| 5 | `IMPLEMENTATION_VERIFIED` promotion across ≥ 2 binaries; Rizin/angr remain optional/deferred; `export:` commit; A7 export |

---

## A9. Post-build proof sequence (run in this order, report each honestly)

1. **Ingestion breadth** — one drop of every artifact type (A5 gate).
2. **Ground truth ×2** — JUCE and iPlug2 stripped fixtures → `GROUND_TRUTH_REPORT.json` each.
3. **Owned SP plugin** — artifact → recovered architecture → DSP → source → build → load → compare → repo. Report `FAILED` states with causes; do not soften.
4. **Cumulative check** — re-run the SP plugin after promotion; show `known / near / unknown` percentages moving in the right direction and every reuse decision carrying provenance.

Definition of success for this addendum: the second owned plugin analysed is measurably cheaper than the first, and every shortcut taken can be clicked open to its evidence.
