# Third-party components

| Component | Where | Licence | Note |
|---|---|---|---|
| Tauri 2, plugins dialog/opener | app/src-tauri | MIT/Apache-2.0 | shell |
| React 18, Vite, TypeScript | app | MIT | UI |
| Python 3.11 (bundled by PyInstaller) | engine | PSF | sidecar |
| jsonschema | engine | MIT | contract validation |
| Steinberg VST3 SDK (hosting classes) | native/vst3host (not vendored) | GPLv3 **or** Steinberg proprietary — owner decision pending, see docs/BLOCKERS.md B-002 | downloaded at build time |
| JUCE | fixtures/groundtruth (not vendored); pinned 8.0.9 download in tools/manifest.json for the BUILD stage | JUCE licence (AGPLv3 / commercial) | ground-truth fixture; rebuilds compile under the owner's own JUCE licence |
| Ghidra | downloaded into %LOCALAPPDATA%\AB\tools | Apache-2.0 | decompiler |
| Eclipse Temurin JDK 21 | downloaded | GPLv2+CE | for Ghidra |
| pluginval | downloaded | GPLv3 | validator, optional |
| music_reference_corpus_21 | reference/ | see reference/music_reference_corpus_21/LICENSE | clean-room reference |
