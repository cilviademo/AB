#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include "Dsp.h"

class ABUnseenAudioProcessor : public juce::AudioProcessor
{
public:
    ABUnseenAudioProcessor();
    ~ABUnseenAudioProcessor() override = default;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
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
    void refresh();

    std::atomic<float>* bypass = nullptr;
    std::atomic<float>* mode   = nullptr;
    std::atomic<float>* trim   = nullptr;
    std::atomic<float>* tone   = nullptr;
    std::atomic<float>* amount = nullptr;
    std::atomic<float>* level  = nullptr;

    abus::OnePoleLP lp[2];
    abus::AtanShaper shaper;
    juce::SmoothedValue<float> trimSmoothed, levelSmoothed;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ABUnseenAudioProcessor)
};
