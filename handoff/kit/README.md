# vst-recover — get source-level content back out of a compiled plugin you own

Chains free/open-source tools into one pipeline that ends in real `.cpp`/`.h` files:

| Stage | Tool | Licence | What it recovers |
|---|---|---|---|
| inventory | Python (stdlib) | — | strings, original file tree (`ORIGINAL_FILE_TREE.txt`), JUCE version, `.pdb` reference, carved images/fonts/SVG/XML from BinaryData |
| params | [pedalboard](https://github.com/spotify/pedalboard) | GPL-3 | every parameter id/name/range/default/choices → `params.json`, saved state ValueTree XML |
| ghidra | [Ghidra](https://github.com/NationalSecurityAgency/ghidra/releases) | Apache-2 | pseudo-C for every function, one `.cpp` per class, DSP ranking, symbol map |
| retdec | [RetDec](https://github.com/avast/retdec/releases) | MIT | fallback single-file decompile |
| scaffold | Python | — | buildable JUCE project: exact APVTS layout, wired editor, CMake, DSP TODOs |

Optional but useful: [Detect It Easy](https://github.com/horsicq/Detect-It-Easy) (compiler/packer ID),
[x64dbg](https://github.com/x64dbg/x64dbg) (step `processBlock` live to confirm what a `FUN_` does),
[pluginval](https://github.com/Tracktion/pluginval) (validate the rebuild), `7z` (unpack `.vst3` bundles).

## Install

```bash
pip install pedalboard
# Ghidra: download the zip from the releases page, unzip, and:
export GHIDRA_INSTALL_DIR=~/ghidra_11.x_PUBLIC     # needs JDK 21 on PATH
# RetDec (optional): unpack release, add bin/ to PATH
```

`params` must run on the OS the plugin was built for (a Windows `.dll` cannot load on Linux/mac).
`inventory`, `ghidra`, `retdec`, `scaffold` run anywhere.

## Run

```bash
python vst_recover.py "C:/Program Files/Common Files/VST3/BTZ.vst3" all --max-mem 8G
# or step by step
python vst_recover.py BTZ.vst3 inventory
python vst_recover.py BTZ.vst3 params
python vst_recover.py BTZ.vst3 ghidra
python vst_recover.py BTZ.vst3 scaffold
```

Output:

```
recovered/BTZ/
  inventory.json                    # juce_version, pdb_reference, resource counts
  inventory/<bin>/strings.txt
  inventory/<bin>/strings_classified.json   # param_ids, presets, license_security, dsp_terms, ui_terms…
  inventory/<bin>/ORIGINAL_FILE_TREE.txt    # source paths baked in by the compiler (assert/JUCE_ASSERT lines)
  inventory/<bin>/resources/*.png|jpg|svg|ttf|xml
  params.json / state_valuetree.xml
  decompiled/dsp_candidates.md      # START HERE — ranked signal-chain functions
  decompiled/classes/*.cpp          # one file per recovered class/namespace
  decompiled/symbols.tsv, string_refs.tsv
  scaffold/CMakeLists.txt, Source/PluginProcessor.{h,cpp}, Source/PluginEditor.{h,cpp}
```

## Before you decompile anything: find the .pdb

`inventory.json` → `pdb_reference`. If it's set, the compiler wrote a symbol file. Search the
old build tree (`build/`, `x64/Release`, `Builds/VisualStudio*/`), OneDrive version history,
GitHub Actions artifact zips, Manus/Codex sandbox exports. Drop it next to the binary and rerun
`ghidra` — every `FUN_140012a30` becomes `BTZ::TruePeakLimiter::processSample` and class
member names come back. This single file is worth more than every decompiler combined.

## What comes back, honestly

- **Exact**: parameter IDs/ranges/defaults, preset/state XML schema, plugin/manufacturer codes,
  embedded artwork, fonts, JUCE version, original file/folder names.
- **Recoverable with work**: DSP math. Float constants and control flow survive; you read the
  pseudo-C, identify the algorithm (biquad, SVF, ADAA tanh, lookahead limiter, envelope
  follower), and rewrite it cleanly. Release builds inline and vectorise, so one function may
  contain three classes' worth of code.
- **Mostly gone**: JUCE UI code. `paint()`/`resized()` decompile into geometry calls with no
  intent. Rebuild the editor from the carved images + `params.json` + your moodboard/handoff
  docs, not from the pseudo-C.
- **Gone**: comments, variable names (without pdb), templates as written, macros, CMake logic.

Licence/anti-tamper code reverse-engineers easily — which is exactly why you rewrite it rather
than restore it.

## Rebuild order

1. `inventory` → read `ORIGINAL_FILE_TREE.txt`; recreate the folder/file skeleton with those names.
2. `params` → `scaffold` → confirm it compiles and loads old presets (`state_valuetree.xml`).
3. `dsp_candidates.md` top 20 → port each into its own class; verify with a null-test against
   the original binary (render the same file through both, subtract, expect −∞ dBFS drift only).
4. Paste the C++ that already exists in your BTZ chat history (ADAA tanh, TruePeakLimiter,
   macro/APVTS port) over the scaffold — it will match the parameter IDs the binary reports.
5. UI last, from resources + design docs.
6. Commit the scaffold to GitHub on day one; every recovered function is a commit.
