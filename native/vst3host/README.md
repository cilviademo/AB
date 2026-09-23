# vst3host — AB's isolated VST3 host

One plugin per process. JSON request on stdin (or `--request`/`--request-file`), one JSON
response on stdout, diagnostics on stderr. Nothing is shared with the caller; nothing stays
loaded between commands. A watchdog ends the process after `timeout_s` (default 60).

| exit | meaning |
|---|---|
| 0 | ok |
| 2 | load failure (module, factory, no audio class, PlugProvider) |
| 3 | plugin exception / crash (signal, SEH, C++ exception) |
| 4 | timeout (watchdog) |
| 5 | bad request |

Commands: `factory` · `parameters` · `units` · `buses` · `info` · `state` · `setparam` · `render`
(SPEC §7). Request fields: `plugin` (path), `class_index`, `sample_rate`, `block_size`, `params`
(`{"<param_id>": normalized}`), `component_state_b64` (restore before the command), and for
`render`: `probe` (silence · impulse · dc · ramp · sine1k · sine_amp_sweep · log_sweep · white ·
pink · two_tone), `frames`, `out` (WAV path).

Build: `build_all.sh` / `build_all.ps1` (clone the VST3 SDK with submodules into `third_party/`,
git-ignored). SDK licence choice is the owner's: BLOCKERS B-002.
