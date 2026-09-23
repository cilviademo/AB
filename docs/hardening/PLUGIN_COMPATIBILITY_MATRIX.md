# PLUGIN_COMPATIBILITY_MATRIX — Addendum B7 (nothing claimed before validated)

format × platform × arch → static parse · runtime host · parameters · state · editor · probe · build · validation.

| format | platform | arch | static parse | runtime host | parameters | state | editor | probe | build | validation |
|---|---|---|---|---|---|---|---|---|---|---|
| VST3 | Windows | x64 | YES (21-plugin corpus, synthetic PE) | pending-windows (vst3host built on Linux only here) | pending-windows | pending-windows | pending-windows | pending-windows | pending-windows | pending-windows |
| VST3 | Linux | x64 | YES (fixture ELF) | YES (fixture: 47/47 Steinberg validator, 79/79 probes) | YES | YES (cross-load) | headless only (editor size reported) | YES | YES (SURROGATE, pluginval 5) | YES (differential harness) |
| VST3 | macOS | arm64 / x64 | PARTIAL (LIEF inventory) | NO | NO | NO | NO | NO | NO | NO |
| VST2 (`.dll`) | Windows | x64 | PARTIAL (PE + strings) | NO | NO | NO | NO | NO | NO | NO |
| AU (`.component`) | macOS | — | NO | NO | NO | NO | NO | NO | NO | NO |
| CLAP | any | — | NO | NO | NO | NO | NO | NO | NO | NO |
