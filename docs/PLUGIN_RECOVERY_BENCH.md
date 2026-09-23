# Plugin Recovery Bench

Drop the compiled plugin, then keep dropping anything else you have: presets, DAW sessions, old build folders, a `.pdb`, source fragments, assets, installers, or related binaries. Each drop adds more evidence and can fill in more of the reconstructed repo.

**Nothing leaves your device.**

---

## Drop files

**Drop plugin binaries, presets, sessions, or whole folders**

Supported examples:

- Plugin binaries: `.dll` `.vst3` `.vst` `.component` `.dylib`
- Presets/state: `.vstpreset` `.fxp` `.fxb` `.aupreset`
- DAW sessions: `.RPP` `.als` `.flp` `.cpr`
- Debug/build evidence: `.pdb` `.map`
- Source/project files: `.cpp` `.h` `.hpp` `.c` `.cc` `.cmake` `CMakeLists.txt`
- Assets: `.png` `.jpg` `.svg` `.ttf` `.otf` `.wav` `.aiff` `.xml` `.json`
- Archives: `.zip`
- Folders: old build folders, installers, source trees, preset libraries, release folders
- Corpus mode: drop many plugins or a `.zip` containing them for cross-plugin comparison

**Choose files** · **Choose a folder**

> On a phone, tap **Choose files** and multi-select from Files or iCloud. Results, reports, and exported ZIPs work here too.

---

## How much of the repo is back

Recovery is evidence-based. The tool never treats inferred or generated code as original source.

| Area | Status | What it means |
|---|---|---|
| Plugin identity | — | Vendor, product, format, architecture, class/FUID metadata |
| Parameters | — | Runtime-exported parameters vs serialized state fields |
| State / presets | — | Preset schema, state keys, cross-load compatibility |
| Classes | — | Plugin-owned, shared-internal, framework, third-party, OS/runtime |
| DSP | — | Processing graph, filters, dynamics, modulation, saturation, reverb, etc. |
| UI | — | Layout XML, resources, controls, fonts, skins |
| Resources | — | Images, fonts, IRs, WAVs, XML, embedded BinaryData |
| Build | — | Toolchain, SDK, CMake/project reconstruction |
| Validation | — | Build, plugin scan, state tests, audio/differential tests |
| Repo readiness | — | Portable project + agent handoff + ZIP |

Evidence labels:

- `VERIFIED` — directly recovered or confirmed by authoritative runtime/build evidence
- `INFERRED` — strongly supported but not proven
- `CANDIDATE` — plausible evidence requiring validation
- `GENERATED` — reconstruction/scaffold created by the tool
- `UNRECOVERABLE` — information removed or unavailable in the compiled artifact

---

## Binary

### Input artifact

- File:
- Format:
- Architecture:
- Size:
- SHA-256:
- Build timestamp:
- Exports:
- Sections:
- Symbols:
- PDB/debug information:
- JUCE/framework detection:
- VST/VST3 SDK evidence:

### Runtime identity

- Vendor:
- Product:
- Version:
- Processor FUID:
- Controller FUID:
- Plugin classes:
- Audio/MIDI buses:
- Reported latency:
- Tail length:
- Editor support:

---

## Build fingerprints

Recovered or inferred build evidence:

- Compiler:
- Linker:
- Runtime:
- SDK:
- Framework:
- Framework version:
- Build configuration:
- Target architecture:
- Original format(s):
- Source-path evidence:
- Third-party libraries:
- Shared internal library family:
- Codebase generation/family:

Fingerprint states:

- `SHARED_NAME`
- `SHARED_ARCHITECTURE_CANDIDATE`
- `SHARED_IMPLEMENTATION_CANDIDATE`
- `SHARED_IMPLEMENTATION_VERIFIED`

A matching name is never treated as proof of identical implementation.

---

## Recovered

### Parameters

Separate the following:

1. **VST3-exported parameters**
2. **Serialized state fields**
3. **Preset-only fields**
4. **UI-only controls**
5. **Unknown properties**

For each runtime parameter capture:

- ParamID
- Name
- Short name
- Units
- Step count
- Default normalized value
- Flags
- Unit/group
- Value-to-string behavior
- State-field mapping
- DSP destination

### Classes

Classify recovered RTTI/classes as:

- `PLUGIN_OWNED`
- `SHARED_INTERNAL`
- `FRAMEWORK`
- `THIRD_PARTY`
- `OS_RUNTIME`
- `UNKNOWN`
- `FALSE_POSITIVE`

Prioritize deep recovery for:

**plugin-specific + processBlock-reachable + DSP-related code**

### DSP

Recover where possible:

- processBlock path
- signal-flow order
- gain stages
- clipping/saturation
- compressors/limiters/gates
- filters/EQ
- oversampling
- modulation
- delays
- chorus/phaser/flanger
- wow/flutter
- pitch/time processing
- reverbs
- convolution/IR processing
- stereo/mid-side
- noise
- meters
- smoothing/coefficient updates

Every reconstructed DSP function keeps a link back to:

- binary address
- decompiler function
- class/vtable evidence
- parameters/state fields
- constants
- behavioral probes
- validation result

---

## Recovered content

```text
Recovered_Project/
├── 00_manifest/
│   ├── input_manifest.json
│   ├── hashes.json
│   ├── tool_versions.json
│   └── recovery_summary.json
│
├── 01_evidence/
│   ├── binary/
│   ├── runtime/
│   ├── rtti/
│   ├── strings/
│   ├── state/
│   ├── presets/
│   ├── resources/
│   ├── decompiler/
│   └── callgraphs/
│
├── 02_recovered_assets/
│   ├── images/
│   ├── fonts/
│   ├── audio/
│   ├── IRs/
│   ├── presets/
│   └── XML/
│
├── 03_architecture/
│   ├── classes.json
│   ├── parameters.json
│   ├── serialized_properties.json
│   ├── state_runtime_map.json
│   ├── signal_flow.json
│   ├── ui_map.json
│   └── architecture.md
│
├── 04_reconstruction/
│   ├── evidence_source/
│   ├── human_source/
│   ├── Source/
│   │   ├── Active/
│   │   └── RecoveredScaffolds/
│   ├── Resources/
│   └── CMakeLists.txt
│
├── 05_reference_behavior/
│   ├── probes/
│   ├── original_renders/
│   ├── transfer_curves/
│   ├── spectra/
│   └── measurements.json
│
├── 06_validation/
│   ├── compile.log
│   ├── pluginval.log
│   ├── state_tests.json
│   ├── differential_results.json
│   └── validation_report.html
│
├── 07_agent_handoff/
│   ├── HANDOFF.md
│   ├── TODO.md
│   ├── reconstruction_index.json
│   ├── binary_symbol_map.json
│   └── agent_prompt.md
│
├── UNRECOVERABLE.md
└── recovered-project.zip
```

---

## Carved resources

Recovered resources remain tied to their original binary offsets and hashes.

Resource states:

- `VALID_EXACT`
- `PARSER_VALID`
- `BOUNDARY_VERIFIED`
- `CARVED_PARTIAL`
- `SPRITE_SHEET_CANDIDATE`
- `DUPLICATE`
- `INVALID`
- `UNKNOWN`

Where possible, embedded BinaryData names are mapped back to their bytes so generic names such as:

```text
png_003.png
```

can become verified original resource names such as:

```text
AutoGain.png
background.png
tr_knob.png
TWIN_REVERB__V4__220924.wav
```

only when the mapping is supported by evidence.

---

## Reconstructed code

The recovery bundle keeps two source representations.

### Evidence reconstruction

Close to the recovered binary/decompiler structure.

Use this when checking:

- addresses
- member offsets
- vtable relationships
- calls
- constants
- state access
- implementation provenance

### Human reconstruction

Concise, maintainable C++/JUCE intended for continued development.

The simplifier may:

- rename generated symbols
- collapse trivial wrappers
- remove compiler/runtime noise
- replace equivalent verbose code with idiomatic C++
- organize recovered functions into sensible classes/files

It must not silently invent new DSP behavior.

Example:

```cpp
// BEHAVIOR_MATCHED
float HardClipper::processSample (float x) const
{
    return juce::jlimit (-threshold, threshold, x);
}
```

The code above is only promoted into active reconstruction after evidence and/or behavioral testing supports it.

---

## Behavioral validation

For DSP reconstruction, behavior is the arbiter.

Reference probes may include:

- impulse
- silence
- DC
- amplitude ramp
- sine
- frequency sweep
- amplitude sweep
- white noise
- pink noise
- two-tone IMD

Test across representative:

- sample rates
- block sizes
- parameter positions
- presets
- state snapshots

Comparison states:

- `BIT_EXACT`
- `NUMERICALLY_EQUIVALENT`
- `BEHAVIORALLY_EQUIVALENT`
- `PERCEPTUALLY_CLOSE`
- `STRUCTURALLY_PLAUSIBLE`
- `SCAFFOLD_ONLY`
- `FAILED`

---

## Corpus / library mode

Drop multiple related plugins to identify shared code families.

Corpus analysis may compare:

- class-name sets
- RTTI
- resource hashes
- parameter/state schemas
- function fingerprints
- vtable fingerprints
- CFG signatures
- compiler/build fingerprints
- recurring BinaryData resources

The tool should first recognize known shared/framework code, then concentrate deep analysis on the residual:

**unknown + plugin-specific + processBlock-reachable code**

Corpus recurrence is supporting evidence, not proof of identical implementation.

---

## Known-library cache

The standalone app may maintain a local knowledge base of previously verified implementations.

Possible cache categories:

- known JUCE/framework
- known OS/runtime
- known third-party
- known shared internal
- known plugin-specific
- unknown

Cache matches must be content/fingerprint-based.

A matching class name alone never proves implementation identity.

---

## Repo readiness

The project is considered repo-ready only when:

- filenames are portable
- no secrets are included
- machine-specific paths are removed
- dependencies are documented
- identity provenance is clear
- generated code is labeled
- scaffolds are separated from active source
- CMake/project files configure
- reconstructed plugin builds where dependencies are available
- validation status is recorded
- agent handoff is complete

---

## What to do next

### If this is the first drop

Add anything else you still have:

- presets
- old builds
- screenshots
- installer files
- project folders
- DAW sessions
- `.pdb` / `.map`
- source fragments
- old binaries
- documentation
- original assets

Each additional artifact can resolve more uncertainty.

### If static recovery is complete

Run:

1. **Runtime introspection**
2. **State differential analysis**
3. **Ghidra / RTTI / callgraph analysis**
4. **Behavioral probes**
5. **One-module reconstruction**
6. **Build**
7. **pluginval**
8. **Original vs rebuild comparison**
9. **Agent handoff**
10. **Export repo / ZIP**

### If an owned plugin has lost source

Start with one high-confidence DSP module:

```text
binary
→ verified parameter
→ state mapping
→ class/vtable
→ processBlock path
→ DSP function
→ behavioral model
→ concise C++
→ build
→ differential validation
```

Once one module is proven end to end, expand outward until the full product is tangible source again.

---

## Recovery principle

The goal is not to pretend a compiled binary can magically reproduce every original line of source.

The goal is to recover the **maximum verifiable project**, reconstruct what was lost, validate it against the original product, and return a maintainable buildable repo that a human or coding agent can continue without starting over.
