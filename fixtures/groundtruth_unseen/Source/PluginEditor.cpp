#include "PluginEditor.h"
#include "BinaryData.h"

ABUnseenAudioProcessorEditor::ABUnseenAudioProcessorEditor (ABUnseenAudioProcessor& p)
    : AudioProcessorEditor (&p), processor (p)
{
    dial = juce::ImageCache::getFromMemory (BinaryData::dial_png, BinaryData::dial_pngSize);
    (void) juce::XmlDocument::parse (juce::String (BinaryData::Default_xml, (size_t) BinaryData::Default_xmlSize));
    for (auto* id : { "trim", "tone", "amount", "level" })
    {
        auto* s = sliders.add (new juce::Slider (juce::Slider::RotaryHorizontalVerticalDrag, juce::Slider::TextBoxBelow));
        addAndMakeVisible (s);
        attachments.add (new juce::AudioProcessorValueTreeState::SliderAttachment (processor.apvts, id, *s));
    }
    addAndMakeVisible (bypassButton);
    shapeBox.addItemList ({ "Soft", "Hard" }, 1);
    addAndMakeVisible (shapeBox);
    bypassAtt = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment> (processor.apvts, "bypass", bypassButton);
    shapeAtt = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment> (processor.apvts, "mode", shapeBox);
    setSize (440, 220);
}

void ABUnseenAudioProcessorEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colour (0xff141416));
    if (dial.isValid())
        g.drawImageAt (dial, 8, 8);
    g.setColour (juce::Colours::white);
    g.drawText ("AB unseen", getLocalBounds().removeFromBottom (22), juce::Justification::centred);
}

void ABUnseenAudioProcessorEditor::resized()
{
    auto r = getLocalBounds().reduced (12);
    auto top = r.removeFromTop (28);
    bypassButton.setBounds (top.removeFromLeft (90));
    shapeBox.setBounds (top.removeFromLeft (110));
    r.removeFromTop (16);
    const int w = r.getWidth() / juce::jmax (1, sliders.size());
    for (auto* s : sliders)
        s->setBounds (r.removeFromLeft (w).reduced (6));
}
