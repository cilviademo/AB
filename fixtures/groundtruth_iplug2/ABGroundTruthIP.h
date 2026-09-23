#pragma once
#include "IPlug_include_in_plug_hdr.h"
#include "GeneratedParams.h"
#include "Dsp.h"
#include "LicenseStub.h"

using namespace iplug;
using namespace igraphics;

/** Ground-truth fixture #2 (ADDENDUM A5): the JUCE fixture's parameters, DSP, resources and
    LICENSING_AND_ENTITLEMENT_SUBSYSTEM stub on iPlug2 (recovered, reconstructed and validated like the DSP). Signal flow: inputGain → TptLowpass → TanhShaper
    (2× oversampled when enabled; Clean bypasses the shaper, Hot doubles drive) → outputGain. */
class ABGroundTruthIP final : public Plugin
{
public:
    ABGroundTruthIP (const InstanceInfo& info);

    void OnReset() override;
    void OnParamChange (int paramIdx) override;
    void ProcessBlock (sample** inputs, sample** outputs, int nFrames) override;

    // State: parameter values, then the two state-only fields (never exported as parameters)
    bool SerializeState (IByteChunk& chunk) const override;
    int UnserializeState (const IByteChunk& chunk, int startPos) override;

private:
    void updateFromParameters();

    abgt::TptLowpass filter[2];
    abgt::TanhShaper shaper;
    abgt::Oversampler2x oversampler[2];
    abgt::LicenseStub license;
    float inGain = 1.0f, outGain = 0.5f;
    float inGainZ = 1.0f, outGainZ = 0.5f;   // 20 ms one-pole smoothing like the JUCE fixture
    float smoothCoef = 0.0f;
    float waveShapers_0_1 = 0.25f;           // STATE_SCHEMA_FIELD decoy
    float uiScale = 1.0f;                    // UI_ONLY_CONTROL
    float demoMode = 1.0f, serialChecksum = 0.0f;   // LICENSING_AND_ENTITLEMENT_SUBSYSTEM state fields
};
