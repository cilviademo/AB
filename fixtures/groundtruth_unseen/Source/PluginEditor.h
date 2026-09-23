#pragma once
#include "PluginProcessor.h"

class ABUnseenAudioProcessorEditor : public juce::AudioProcessorEditor
{
public:
    explicit ABUnseenAudioProcessorEditor (ABUnseenAudioProcessor&);
    ~ABUnseenAudioProcessorEditor() override = default;
    void paint (juce::Graphics&) override;
    void resized() override;

private:
    ABUnseenAudioProcessor& processor;
    juce::Image dial;
    juce::OwnedArray<juce::Slider> sliders;
    juce::OwnedArray<juce::AudioProcessorValueTreeState::SliderAttachment> attachments;
    juce::ToggleButton bypassButton { "Bypass" };
    juce::ComboBox shapeBox;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> bypassAtt;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> shapeAtt;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ABUnseenAudioProcessorEditor)
};
