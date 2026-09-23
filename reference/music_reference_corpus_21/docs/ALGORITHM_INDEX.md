# Reference algorithm index

The code in `include/musicref/` intentionally implements **standard, compact DSP hypotheses**, not recovered product algorithms.

| Area | Reference implementation | Typical corpus hints |
|---|---|---|
| Gain | `GainStage` | `MorphGain`, `MorphVolume`, Input/Output/InGain/OutGain |
| Waveshaping | `hardClip`, `tanhClip`, `atanClip`, `cubicSoftClip`, `diodeLikeClip` | `MorphHardClipper`, `MorphDistortion*`, `MorphDiodeClipper`, `DisotrtionEffect` |
| Bit/sample reduction | `BitCrusher`, `SampleHoldReducer` | `MorphBitcrusher` |
| Dynamics | `Compressor`, `Limiter`, `Gate`, `AutoGain` | compressor/limiter/gate/autogain families |
| Filters | `Biquad`, `TPTOnePole`, `StateVariableFilter`, `FourPoleLadder` | EQ/IIR/TPT/ladder/filter classes |
| Analog topology references | `BaxandallReference`, `SallenKeyReference`, `DiodeClipperReference` | Gen B WDF/topology names |
| Delay | `StereoDelay`, `PingPongDelay`, `PreDelay` | delay classes and time state |
| Modulation | `Chorus`, `Phaser`, `Tremolo`, `WowFlutter` | corresponding Morph classes/LFO hints |
| Reverb/convolution | `SchroederReverb`, `FIRConvolver` | MorphReverb/Convolution/MultiConvo, embedded IR hints |
| Stereo | mid/side + `applyStereoWidth` | MorphMidSide/MorphWidth |
| Pitch/time | autocorrelation + generic resampling | tuner/tuna/pitch names; SoundTouch stays an external dependency |
| Probes | impulse/ramp/sine/log sweep/noise | standalone behavioral-validation phase |

## Important inference rule

A corpus mapping means **"try/compare this standard family"**, never **"this is the vendor implementation"**. The standalone differential harness should select or reject candidates using measured behavior.
