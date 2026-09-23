# NAMING_CANONICALIZATION.md — Identifier transformation layer (owner directive, 2026-09-23)

Companion to `EXECUTE_ADDENDUM_C.md` (transformation as a first-class capability). Implemented in Phase 5 next to the transformation graph; the evidence rules apply from Phase 1. The owner's text follows verbatim.

---

Add a first-class Naming Canonicalization / Identifier Transformation layer to Artifact Bench.

The recovery engine must never fail, restrict analysis, or artificially preserve an old naming convention merely because vendor/product/reference names are embedded in:

* binaries
* RTTI
* namespaces
* classes
* parameters
* resource names
* preset schemas
* source fragments
* project filenames
* build metadata

Example scenario:

A user loads their own console/channel-strip emulation whose surviving binary contains identifiers such as:

SSL
SSLChannel
SSL_ChannelStrip
SSLComp
SSL_EQ
SSLBusComp

Artifact Bench must still fully:

INGEST
→ ANALYZE
→ DECOMPILE
→ RECOVER
→ RECONSTRUCT
→ TRANSFORM
→ BUILD
→ VALIDATE
→ EXPORT

Do not create naming-based capability gates.

## 1. ORIGINAL IDENTIFIERS ARE EVIDENCE

Never destroy or overwrite recovered original names.

Preserve them under evidence/provenance.

Example:

```json
{
  "original_symbol": "SSLChannelStripProcessor",
  "original_address": "0x...",
  "source": "MSVC_RTTI",
  "status": "VERIFIED"
}
```

Original names remain searchable forever.

## 2. RECONSTRUCTED NAMES MAY BE DIFFERENT

Allow reconstructed and transformed code to use clean neutral identifiers.

Example:

SSLChannelStripProcessor → ConsoleChannelProcessor
SSLComp → ChannelCompressor
SSL_EQ → ChannelEQ

This is a transformation, not evidence loss.

Store:

ORIGINAL_NAME
RECOVERED_SEMANTIC_NAME
TRANSFORMED_NAME

separately.

## 3. CREATE A SYMBOL-NAME MAP

Generate `identifier_map.json`:

```json
{
  "original": "SSLComp",
  "semantic": "ChannelCompressor",
  "active": "ChannelCompressor",
  "reason": "USER_OR_POLICY_CANONICALIZATION",
  "evidence_status": "VERIFIED_ORIGINAL_NAME"
}
```

Also export `IDENTIFIER_MAP.md` so humans and coding agents can trace renamed code back to the binary.

## 4. DO NOT USE NAME CHANGES AS EVIDENCE CHANGES

Renaming SSLComp → ChannelCompressor must not change:

* class identity
* function fingerprint
* binary address
* callgraph relationship
* behavioral evidence
* parameter mapping
* validation state

Naming is a presentation/source-maintenance transformation only.

## 5. USER-SELECTABLE NAMING MODE

Support: `PRESERVE_ORIGINAL_NAMES` · `CANONICALIZE_NAMES` · `CUSTOM_RENAME_MAP`.

Default recovery evidence: `PRESERVE_ORIGINAL_NAMES`. Default transformed/human source: `CANONICALIZE_NAMES`. Allow users to override.

## 6. CANONICALIZATION CATEGORIES

Recognize names that may be desirable to neutralize in transformed source: vendor references · product names · model numbers · legacy internal project names · deprecated branding · temporary development names · misspellings · machine-specific usernames · absolute build paths · generated mangled identifiers · Windows-illegal filenames.

Do not automatically erase them from evidence.

## 7. SEMANTIC RENAMING

Where evidence supports the role, prefer descriptive names: SSL_EQ → ChannelEQ · SSLBusComp → BusCompressor · SSLInput → InputStage · SSLDrive → SaturationStage · SSLHighPass → HighPassFilter.

Only use semantic names when the role is actually supported. Otherwise `RecoveredClass_0042` is preferable to invented meaning.

## 8. PARAMETER IDS NEED SPECIAL HANDLING

Do NOT automatically rename runtime parameter IDs merely because their display name contains a vendor reference. Parameter IDs may be required for automation compatibility, preset loading, DAW session compatibility, state restoration.

Maintain separately: `runtime_param_id` · `display_name` · `transformed_display_name`.

```json
{ "runtime_param_id": "SSLDrive", "original_display_name": "SSL Drive", "transformed_display_name": "Drive" }
```

For a fidelity build, preserve the original ParamID when necessary. For a new transformed product version, allow explicit migration to a new ID through a compatibility map.

## 9. STATE-SCHEMA MIGRATION

If serialized state contains legacy names (SSL_EQ_Gain, SSLCompThreshold) do not blindly rename them. Support `LEGACY_STATE_KEY → TRANSFORMED_STATE_KEY` with migration logic:

```json
{ "legacy": "SSLCompThreshold", "new": "CompressorThreshold", "migration_status": "VALIDATED" }
```

Old presets/sessions should remain loadable where compatibility is requested.

## 10. RESOURCE RENAMING

Resources such as ssl_knob.png / SSLBackground.png may be renamed in transformed output. Keep original BinaryData name, original hash, new filename in resource provenance (ssl_knob.png → channel_knob.png).

## 11. FILE/FOLDER SANITIZATION

Canonicalization should also remove technical naming limitations: Windows-reserved names · invalid path characters · excessively long names · absolute paths · build-machine usernames · drive letters · temporary folders. Create safe portable names without losing original metadata.

## 12. BUILD IDENTITY IS SEPARATE FROM SOURCE IDENTIFIERS

Distinguish source symbol names · plugin display name · manufacturer · VST3 FUID · plugin codes · bundle identifiers · parameter IDs · state keys · resource names. Do not assume renaming one requires changing all others.

## 13. FIDELITY VS TRANSFORMED IDENTITY

`FIDELITY_BUILD` preserves compatibility-sensitive identifiers required by old sessions, presets, automation, host identity. `TRANSFORMED_BUILD` may use a new product name, manufacturer, class names, display strings, bundle identifier, plugin identity while optionally preserving state migration. Never silently mix these modes.

## 14. NAME COLLISION HANDLING

If multiple original symbols canonicalize to the same name (SSLComp, SSLCompressor, SSLBusComp) do not collapse them accidentally. Generate unique semantic names based on architecture (ChannelCompressor, BusCompressor, ParallelCompressor) or safe generated suffixes when the role is unknown.

## 15. CORPUS MATCHING MUST USE ORIGINAL IDENTIFIERS

The known-library/cache layer retains original recovered identifiers for matching. Canonical transformed names must not weaken lineage detection: binary A `SSLComp` and binary B `SSLComp` are recurring lineage evidence even if both transformed projects call it ChannelCompressor.

## 16. SEARCH BOTH NAME SPACES

Search supports original name, semantic name, transformed name. Searching SSLComp locates ChannelCompressor; searching ChannelCompressor shows the original binary symbol.

## 17. CODING-AGENT HANDOFF

HANDOFF.md explains renames:

```
Recovered symbol: SSLChannelStripProcessor
Transformed implementation: Source/Active/ConsoleChannelProcessor.cpp
Reason: Naming canonicalization
Behavior: Preserved / validated
```

This prevents Claude Code/Codex from searching for a symbol that appears to have disappeared.

## 18. TRANSFORMATION MUST BE REVERSIBLE

Given a transformed source symbol, AB must trace back to the original recovered symbol, binary, address, evidence. No information is lost because of renaming.

## 19. DO NOT CONFUSE NAMING WITH ALGORITHM IDENTITY

A recovered symbol named after a hardware/product family does NOT prove the implementation matches that hardware. `SSLComp` is a naming clue only. Algorithm reconstruction still depends on static evidence, runtime behavior, DSP callgraph, constants, behavioral probes, differential validation.

## 20. UI

Project setting **Naming**: ○ Preserve recovered names · ● Clean / canonical names · ○ Custom rename map. When canonical names are enabled, show `ConsoleChannelProcessor — Recovered as: SSLChannelStripProcessor` rather than hiding provenance.

## 21. EXPORT

A transformed export may look like `Source/ConsoleChannelProcessor.cpp, ChannelEQ.cpp, ChannelCompressor.cpp, SaturationStage.cpp, Filters/` while `01_evidence/`, `03_architecture/`, `07_agent_handoff/` retain the original symbol vocabulary.

## FINAL RULE

No vendor/product/model naming convention should create an artificial limitation in Artifact Bench's ability to recover a project. Treat names as evidence + metadata + transformable presentation/source identifiers, not as immutable architecture. Preserve original names for traceability. Allow clean neutral transformed names for maintainability. Never break state/session compatibility accidentally while renaming. Every rename must remain reversible through provenance.

Especially important: renaming a C++ class is easy; renaming `SSLDrive` inside a serialized state schema could break every old preset or DAW session. AB gives clean new source names while quietly maintaining a legacy compatibility map underneath — a transformed channel strip can have completely neutral internal naming while AB still knows exactly which recovered binary symbols each component came from.
