#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>
#include "Dsp.h"
#include "LicenseStub.h"

class ABGroundTruthAudioProcessor : public juce::AudioProcessor
{
public:
    ABGroundTruthAudioProcessor();
    ~ABGroundTruthAudioProcessor() override = default;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return "Default"; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    juce::AudioProcessorValueTreeState apvts;

private:
    void updateFromParameters();

    std::atomic<float>* bypass     = nullptr;
    std::atomic<float>* mode       = nullptr;
    std::atomic<float>* inputGain  = nullptr;
    std::atomic<float>* cutoff     = nullptr;
    std::atomic<float>* drive      = nullptr;
    std::atomic<float>* oversample = nullptr;
    std::atomic<float>* outputGain = nullptr;

    abgt::TptLowpass filter[2];
    abgt::TanhShaper shaper;
    abgt::LicenseStub license;
    juce::dsp::Oversampling<float> oversampling { 2, 1, juce::dsp::Oversampling<float>::filterHalfBandPolyphaseIIR, true };
    juce::SmoothedValue<float> inGainSmoothed, outGainSmoothed;
    double currentSampleRate = 48000.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ABGroundTruthAudioProcessor)
};
