#include "PluginEditor.h"
#include "BinaryData.h"

ABGroundTruthAudioProcessorEditor::ABGroundTruthAudioProcessorEditor (ABGroundTruthAudioProcessor& p)
    : AudioProcessorEditor (&p), processor (p)
{
    // Embedded resources exercise BinaryData recovery: one PNG, one TTF, one XML preset.
    knob = juce::ImageCache::getFromMemory (BinaryData::knob_png, BinaryData::knob_pngSize);
    mono = juce::Typeface::createSystemTypefaceFor (BinaryData::ABMono_ttf, (size_t) BinaryData::ABMono_ttfSize);
    (void) juce::XmlDocument::parse (juce::String (BinaryData::Init_xml, (size_t) BinaryData::Init_xmlSize));

    for (auto* id : { "inputGain", "cutoff", "drive", "outputGain" })
    {
        auto* s = sliders.add (new juce::Slider (juce::Slider::RotaryHorizontalVerticalDrag, juce::Slider::TextBoxBelow));
        auto* l = labels.add (new juce::Label ({}, id));
        l->attachToComponent (s, false);
        addAndMakeVisible (s);
        attachments.add (new juce::AudioProcessorValueTreeState::SliderAttachment (processor.apvts, id, *s));
    }
    addAndMakeVisible (bypassButton);
    addAndMakeVisible (oversampleButton);
    modeBox.addItemList ({ "Clean", "Warm", "Hot" }, 1);
    addAndMakeVisible (modeBox);
    bypassAtt = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment> (processor.apvts, "bypass", bypassButton);
    oversampleAtt = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment> (processor.apvts, "oversample", oversampleButton);
    modeAtt = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment> (processor.apvts, "mode", modeBox);
    setSize (520, 260);
}

void ABGroundTruthAudioProcessorEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colour (0xff0a0a0a));
    if (knob.isValid())
        g.drawImageAt (knob, 8, 8);
    g.setColour (juce::Colours::white);
    if (mono != nullptr)
        g.setFont (juce::Font (juce::FontOptions (mono).withHeight (14.0f)));
    g.drawText ("AB ground truth", getLocalBounds().removeFromBottom (24), juce::Justification::centred);
}

void ABGroundTruthAudioProcessorEditor::resized()
{
    auto r = getLocalBounds().reduced (12);
    auto top = r.removeFromTop (30);
    bypassButton.setBounds (top.removeFromLeft (100));
    oversampleButton.setBounds (top.removeFromLeft (120));
    modeBox.setBounds (top.removeFromLeft (120));
    r.removeFromTop (24);
    const int w = r.getWidth() / juce::jmax (1, sliders.size());
    for (auto* s : sliders)
        s->setBounds (r.removeFromLeft (w).reduced (6));
}
