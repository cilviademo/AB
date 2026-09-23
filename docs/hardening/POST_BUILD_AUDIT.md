# POST_BUILD_AUDIT — Addendum B1 (living document)

Severity `BLOCKER | HIGH | MEDIUM | LOW | DEFERRED`. Every item names the issue, component, reproduction, root cause, fix and the test that proves the fix. Items found during the build so far; the full repo inspection of B1 (placeholders, swallowed exceptions, races, cancellation, migrations, IPC, timeouts, crash recovery, missing tests) continues here.

Repo-wide marker scan (2026-09-23): no `TODO/FIXME/HACK/NotImplemented` placeholders in engine/, app/src, native/vst3host/src or ghidra/ (the only matches are the words inside generated handoff text).

| id | severity | component | issue | status |
|---|---|---|---|---|
| AUD-001 | HIGH | `ghidra/Fingerprint.java` | every Ghidra fingerprint carried size 0 after the qualified-name change (a comment swallowed the size assignment); the knowledge base skipped all of them (min size 32) and no name could be lent to a stripped build | FIXED |
| AUD-002 | HIGH | `engine/ab_engine/static/api.py` | the frozen v2 bundle's 00_manifest/input_manifest.json was installed over AB's ingest manifest, losing usage_context / source_availability (and before D-026 the ownership declaration) after STATIC | FIXED |
| AUD-003 | HIGH | `engine/ab_engine/bundle` | exports carried build-machine paths (workspace, temp, repo, JUCE dir) in six JSON files; the scanner flagged one (only /home and C:\Users patterns) | FIXED |
| AUD-004 | MEDIUM | `engine/ab_engine/handoff/api.py (loop)` | the whole-project loop regenerated the handoff after the validation checkpoint, leaving the project git tree dirty (A6 gate: status clean) | FIXED |
| AUD-005 | MEDIUM | `engine/ab_engine/knowledge/db.py` | a function first recorded from a stripped build kept its decompiler label (FUN_…) as name_hint even after a symbol build named it; names could never be lent | FIXED |
| AUD-006 | MEDIUM | `ghidra/ExportRTTI.java` | Ghidra's symbol-keyed RTTI recovery found none of the plugin's classes on a stripped ELF (33 classes, all std/cxxabi) | FIXED |
| AUD-007 | MEDIUM | `ghidra/ExportDecompiled.java` | BinaryData getNamedResource pairs could not be resolved on a stripped image (pointer symbols PTR_DAT_/PTR_PNG_/PTR_s_<… not matched; pairs unnamed) | FIXED |
| AUD-008 | LOW | `engine/ab_engine/decompile/api.py` | the DSP top-5 gate on stripped builds depends on names the knowledge base lends; a stripped build analysed before any symbol build shows only structural roles | OPEN |
| AUD-009 | DEFERRED | `fixtures/groundtruth_iplug2` | the iPlug2 fixture is written but unbuilt in the Linux environment (no maintained Linux VST3 target) | DEFERRED |
| AUD-010 | DEFERRED | `transform (MIGRATE / PORT / REBUILD)` | goals accepted and recorded NOT_AVAILABLE; no generator | DEFERRED |

## Details

### AUD-001 — HIGH — ghidra/Fingerprint.java
- issue: every Ghidra fingerprint carried size 0 after the qualified-name change (a comment swallowed the size assignment); the knowledge base skipped all of them (min size 32) and no name could be lent to a stripped build
- reproduction: run DECOMPILE on any job; 01_evidence/decompiler/fingerprints.json → all size 0; knowledge stats: ghidra occurrences do not grow
- root cause: misplaced end-of-line comment in Fingerprint.java
- fix: size restored; the stage and `knowledge refresh` fill a missing size from the callgraph row (same evidence)
- test: engine/tests/test_decompile.py, test_knowledge.py; DECOMPILE stage version 5 re-run on both fixture jobs
- status: FIXED

### AUD-002 — HIGH — engine/ab_engine/static/api.py
- issue: the frozen v2 bundle's 00_manifest/input_manifest.json was installed over AB's ingest manifest, losing usage_context / source_availability (and before D-026 the ownership declaration) after STATIC
- reproduction: ingest → STATIC → read 00_manifest/input_manifest.json: keys generated/inputs/mode/tool only
- root cause: v2 layout and AB layout share the file name; install copied blindly
- fix: the v2 file is installed as static_input_manifest.json
- test: engine/tests/test_bundle.py::test_context_changes_wording_never_capability
- status: FIXED

### AUD-003 — HIGH — engine/ab_engine/bundle
- issue: exports carried build-machine paths (workspace, temp, repo, JUCE dir) in six JSON files; the scanner flagged one (only /home and C:\Users patterns)
- reproduction: export the fixture job; grep /tmp and the repo path in validation/*.json
- root cause: no scrubbing of this machine's roots; scanner blind to temp roots and JSON-escaped Windows paths
- fix: scrub_machine_paths replaces project / workspace / state / tools / env tool roots / home / temp with placeholders (evidence/01_evidence/{paths,strings,binary} exempt: original developer's paths are evidence); scanner patterns extended
- test: engine/tests/test_bundle.py::test_export_scrubs_this_machines_paths
- status: FIXED

### AUD-004 — MEDIUM — engine/ab_engine/handoff/api.py (loop)
- issue: the whole-project loop regenerated the handoff after the validation checkpoint, leaving the project git tree dirty (A6 gate: status clean)
- reproduction: ab-cli loop <job>; git -C <project> status
- root cause: handoff written after the last stage checkpoint
- fix: loop commits `validation: agent handoff regenerated` after writing the handoff
- test: engine/tests/test_checkpoint_rules.py; fixture-level sequence on the next full run
- status: FIXED

### AUD-005 — MEDIUM — engine/ab_engine/knowledge/db.py
- issue: a function first recorded from a stripped build kept its decompiler label (FUN_…) as name_hint even after a symbol build named it; names could never be lent
- reproduction: analyse stripped then symbol build; SELECT name_hint FROM function → FUN_…
- root cause: COALESCE(name_hint, new) kept the first value
- fix: a real name always replaces a decompiler label; `ab-cli knowledge refresh <job>` re-records stored evidence
- test: measured: refresh recorded 16 455 Ghidra fingerprints with qualified names
- status: FIXED

### AUD-006 — MEDIUM — ghidra/ExportRTTI.java
- issue: Ghidra's symbol-keyed RTTI recovery found none of the plugin's classes on a stripped ELF (33 classes, all std/cxxabi)
- reproduction: DECOMPILE on the stripped fixture before commit 433e130
- root cause: typeinfo/vtable symbols absent when stripped
- fix: structural Itanium pass (raw typeinfo-name scan → typeinfo object → bases → vtables, null-slot tolerant)
- test: measured: 709 classes / 592 vtables on the stripped fixture; engine/tests/test_vtable_layout.py
- status: FIXED

### AUD-007 — MEDIUM — ghidra/ExportDecompiled.java
- issue: BinaryData getNamedResource pairs could not be resolved on a stripped image (pointer symbols PTR_DAT_/PTR_PNG_/PTR_s_<… not matched; pairs unnamed)
- reproduction: DECOMPILE on the stripped fixture before commit 8b3…
- root cause: regex assumed identifier-like symbols and DAT_/PTR_ + hex
- fix: symbol-table resolution, deref for PTR_, name from the branch's JUCE name-hash case constant; pseudo-C of every candidate kept as evidence
- test: measured 3/3 VERIFIED; engine/tests/test_decompile.py
- status: FIXED

### AUD-008 — LOW — engine/ab_engine/decompile/api.py
- issue: the DSP top-5 gate on stripped builds depends on names the knowledge base lends; a stripped build analysed before any symbol build shows only structural roles
- reproduction: phase 3 gate 'waveshaper and filter in top-5' on a fresh workspace
- root cause: by design: names come from symbols or fingerprint knowledge
- fix: documented; the gate prints the basis; knowledge refresh + rerun after a symbol build
- test: phase-3 re-measurement (in progress)
- status: OPEN

### AUD-009 — DEFERRED — fixtures/groundtruth_iplug2
- issue: the iPlug2 fixture is written but unbuilt in the Linux environment (no maintained Linux VST3 target)
- reproduction: n/a
- root cause: BLOCKERS B-008
- fix: build_all.ps1 on the studio PC
- test: pending-windows
- status: DEFERRED

### AUD-010 — DEFERRED — transform (MIGRATE / PORT / REBUILD)
- issue: goals accepted and recorded NOT_AVAILABLE; no generator
- reproduction: ab-cli run <job> --stage RECONSTRUCTION_COMPLETE --option goal=MIGRATE → warning GOAL_NOT_AVAILABLE
- root cause: not implemented in this version
- fix: interface + honest status shipped (D-027); generators later
- test: engine/tests/test_transform_graph.py
- status: DEFERRED

