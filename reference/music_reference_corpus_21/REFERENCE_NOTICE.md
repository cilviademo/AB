# Clean-room reference notice

This repository is **not recovered source code** from any of the analyzed VST3 binaries.

It is a clean-room, generic reference library created from standard audio/DSP knowledge and a corpus-level index of names, roles, state keys, resources, and architectural hints observed by the user's Static Recovery v2 tooling across 21 test VST3 files.

Use it for:

- algorithm-family inference;
- reconstruction hypotheses;
- unit and behavioral tests;
- coding-agent context;
- identifying standard components that should be implemented from known DSP formulas or existing dependencies rather than hallucinated from class names.

Do **not** use a mapping in `catalog/observed_symbols.json` as proof that a vendor class used the mapped implementation. `reference_component` is a clean-room candidate selected from the available evidence. Runtime/decompiler/behavioral evidence must decide fidelity.

Third-party names such as JUCE, Steinberg VST3, SoundTouch, and chowdsp WDF are represented as dependency references only. Their original source is not copied here.
