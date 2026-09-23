#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "GeneratedParams.h"

ABUnseenAudioProcessor::ABUnseenAudioProcessor()
    : AudioProcessor (BusesProperties().withInput ("Input", juce::AudioChannelSet::stereo(), true)
                                       .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, abus::kStateTreeType, abus::makeLayout())
{
    bypass = apvts.getRawParameterValue ("bypass");
    mode   = apvts.getRawParameterValue ("mode");
    trim   = apvts.getRawParameterValue ("trim");
    tone   = apvts.getRawParameterValue ("tone");
    amount = apvts.getRawParameterValue ("amount");
    level  = apvts.getRawParameterValue ("level");
    for (const auto& f : abus::kStateOnly)
        apvts.state.setProperty (f.id, f.value, nullptr);
}

void ABUnseenAudioProcessor::prepareToPlay (double sampleRate, int)
{
    for (auto& f : lp) f.prepare (sampleRate);
    trimSmoothed.reset (sampleRate, 0.01);
    levelSmoothed.reset (sampleRate, 0.01);
    refresh();
    trimSmoothed.setCurrentAndTargetValue (juce::Decibels::decibelsToGain (trim->load()));
    levelSmoothed.setCurrentAndTargetValue (juce::Decibels::decibelsToGain (level->load()));
    setLatencySamples (0);
}

bool ABUnseenAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    return layouts.getMainOutputChannelSet() == juce::AudioChannelSet::stereo()
        && layouts.getMainInputChannelSet() == layouts.getMainOutputChannelSet();
}

void ABUnseenAudioProcessor::refresh()
{
    for (auto& f : lp) f.setCutoff (tone->load());
    shaper.setAmount (amount->load());
    shaper.setHard ((int) mode->load() == 1);
    trimSmoothed.setTargetValue (juce::Decibels::decibelsToGain (trim->load()));
    levelSmoothed.setTargetValue (juce::Decibels::decibelsToGain (level->load()));
}

void ABUnseenAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;
    refresh();
    if (bypass->load() > 0.5f)
        return;
    const int numCh = juce::jmin (2, buffer.getNumChannels());
    const int n = buffer.getNumSamples();
    for (int ch = 0; ch < numCh; ++ch)
    {
        auto* d = buffer.getWritePointer (ch);
        auto tIn = trimSmoothed, tOut = levelSmoothed;
        for (int i = 0; i < n; ++i)
            d[i] = shaper.process (lp[ch].process (d[i] * tIn.getNextValue())) * tOut.getNextValue();
    }
    trimSmoothed.skip (n);
    levelSmoothed.skip (n);
}

juce::AudioProcessorEditor* ABUnseenAudioProcessor::createEditor() { return new ABUnseenAudioProcessorEditor (*this); }

void ABUnseenAudioProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    if (auto xml = apvts.copyState().createXml())
        copyXmlToBinary (*xml, destData);
}

void ABUnseenAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    if (auto xml = getXmlFromBinary (data, sizeInBytes))
        if (xml->hasTagName (apvts.state.getType()))
            apvts.replaceState (juce::ValueTree::fromXml (*xml));
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new ABUnseenAudioProcessor(); }
