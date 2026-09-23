# fixtures/groundtruth_unseen — the *unseen* known-source fixture (ADDENDUM B8, acceptance test 1)

A second JUCE plugin **with source**, written after the recovery pipeline was built and never used to tune it.
The acceptance test is: binary only → full pipeline → reveal source → metrics. Nothing in `engine/` names this
fixture; the evaluator (`ab-cli ground-truth <job> --truth fixtures/groundtruth_unseen/truth.json`) reads every
expectation from `truth.json`, which `gen.py` derives from `spec.json`.

Deliberately different implementations from `fixtures/groundtruth`:

| | groundtruth | groundtruth_unseen |
|---|---|---|
| product / code | ABGroundTruth · Mbnd/Abgt | ABUnseen · Mbnd/Abus |
| state tree | `PARAMETERS` | `ABUNSEEN` |
| filter | `abgt::TptLowpass` (TPT, Zavalishin) | `abus::OnePoleLP` (RC one-pole `y += g (x − y)`) |
| waveshaper | `abgt::TanhShaper` (`tanh(d·x)/tanh(d)`) | `abus::AtanShaper` (`(2/π)·atan(a·x)`; Hard mode = clamp) |
| oversampling / latency | 2× when enabled | none, latency 0 |
| licensing | `abgt::LicenseStub` (serial + demo state) | none |
| parameters | bypass, mode(3), inputGain, cutoff, drive, oversample, outputGain | bypass, mode(2), trim, tone, amount, level |
| state-only fields | waveShapers_0_1 (decoy), uiScale, demoMode, serialChecksum | curves_0_2 (decoy), lastTab |
| resources | knob.png, ABMono.ttf, Init.xml | dial.png (generated 24×24), Default.xml |

Build (Linux/macOS; JUCE is shared with the first fixture): `./build_all.sh` → `out/stripped/ABUnseen.vst3`.
`AB_VARIANTS="debug release stripped"` builds all three. Binaries are never committed.
