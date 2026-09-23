#pragma once
#include "PluginProcessor.h"

class ABGroundTruthAudioProcessorEditor : public juce::AudioProcessorEditor
{
public:
    explicit ABGroundTruthAudioProcessorEditor (ABGroundTruthAudioProcessor&);
    ~ABGroundTruthAudioProcessorEditor() override = default;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    ABGroundTruthAudioProcessor& processor;
    juce::Image knob;
    juce::Typeface::Ptr mono;
    juce::OwnedArray<juce::Slider> sliders;
    juce::OwnedArray<juce::Label> labels;
    juce::OwnedArray<juce::AudioProcessorValueTreeState::SliderAttachment> attachments;
    juce::ToggleButton bypassButton { "Bypass" }, oversampleButton { "Oversample" };
    juce::ComboBox modeBox;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> bypassAtt, oversampleAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> modeAtt;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ABGroundTruthAudioProcessorEditor)
};
