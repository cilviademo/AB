#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "GeneratedParams.h"

ABGroundTruthAudioProcessor::ABGroundTruthAudioProcessor()
    : AudioProcessor (BusesProperties().withInput ("Input", juce::AudioChannelSet::stereo(), true)
                                       .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, abgt::kStateTreeType, abgt::makeLayout())
{
    bypass     = apvts.getRawParameterValue ("bypass");
    mode       = apvts.getRawParameterValue ("mode");
    inputGain  = apvts.getRawParameterValue ("inputGain");
    cutoff     = apvts.getRawParameterValue ("cutoff");
    drive      = apvts.getRawParameterValue ("drive");
    oversample = apvts.getRawParameterValue ("oversample");
    outputGain = apvts.getRawParameterValue ("outputGain");

    // State-only fields: serialized in the ValueTree, never exported as parameters (EXECUTE 2.2 gate).
    for (const auto& f : abgt::kStateOnly)
        apvts.state.setProperty (f.id, f.value, nullptr);

    // Licensing stub (ADDENDUM C2): an (invalid) serial is checked at construction, so the fixture starts in
    // demo state; the ValueTree records the state-only fields demoMode / serialChecksum the stub produced.
    license.checkSerial (juce::String ("ABGT-0000-0000-0000"));
    apvts.state.setProperty ("demoMode", license.isDemo() ? 1.0f : 0.0f, nullptr);
    apvts.state.setProperty ("serialChecksum", (float) license.lastSerialChecksum(), nullptr);
}

void ABGroundTruthAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    currentSampleRate = sampleRate;
    for (auto& f : filter) f.prepare (sampleRate);
    oversampling.initProcessing ((size_t) samplesPerBlock);
    oversampling.reset();
    inGainSmoothed.reset (sampleRate, 0.02);
    outGainSmoothed.reset (sampleRate, 0.02);
    updateFromParameters();
    inGainSmoothed.setCurrentAndTargetValue (juce::Decibels::decibelsToGain (inputGain->load()));
    outGainSmoothed.setCurrentAndTargetValue (juce::Decibels::decibelsToGain (outputGain->load()));
    setLatencySamples (oversample->load() > 0.5f ? (int) oversampling.getLatencyInSamples() : 0);
}

void ABGroundTruthAudioProcessor::releaseResources() {}

bool ABGroundTruthAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    return layouts.getMainOutputChannelSet() == juce::AudioChannelSet::stereo()
        && layouts.getMainInputChannelSet() == layouts.getMainOutputChannelSet();
}

void ABGroundTruthAudioProcessor::updateFromParameters()
{
    for (auto& f : filter) f.setCutoff (cutoff->load());
    const int m = (int) mode->load();
    shaper.setDrive (drive->load() * (m == 2 ? 2.0f : 1.0f));
    inGainSmoothed.setTargetValue (juce::Decibels::decibelsToGain (inputGain->load()));
    outGainSmoothed.setTargetValue (juce::Decibels::decibelsToGain (outputGain->load()));
}

void ABGroundTruthAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    license.noteRender();   // demo render budget (no audible effect in the fixture)
    juce::ScopedNoDenormals noDenormals;
    updateFromParameters();

    if (bypass->load() > 0.5f)
        return;

    const int numCh = juce::jmin (2, buffer.getNumChannels());
    const int n = buffer.getNumSamples();

    // 1. input gain + TPT low-pass, per channel
    for (int ch = 0; ch < numCh; ++ch)
    {
        auto* d = buffer.getWritePointer (ch);
        auto smoother = inGainSmoothed; // per-channel copy so both channels see the same ramp
        for (int i = 0; i < n; ++i)
            d[i] = filter[ch].process (d[i] * smoother.getNextValue());
    }
    inGainSmoothed.skip (n);

    // 2. tanh waveshaper (mode 0 = Clean bypasses it), optionally 2x oversampled
    const int m = (int) mode->load();
    if (m != 0)
    {
        juce::dsp::AudioBlock<float> block (buffer);
        if (oversample->load() > 0.5f)
        {
            auto up = oversampling.processSamplesUp (block);
            for (size_t ch = 0; ch < up.getNumChannels(); ++ch)
            {
                auto* d = up.getChannelPointer (ch);
                for (size_t i = 0; i < up.getNumSamples(); ++i)
                    d[i] = shaper.process (d[i]);
            }
            oversampling.processSamplesDown (block);
        }
        else
        {
            for (int ch = 0; ch < numCh; ++ch)
            {
                auto* d = buffer.getWritePointer (ch);
                for (int i = 0; i < n; ++i)
                    d[i] = shaper.process (d[i]);
            }
        }
    }

    // 3. output gain
    for (int ch = 0; ch < numCh; ++ch)
    {
        auto* d = buffer.getWritePointer (ch);
        auto smoother = outGainSmoothed;
        for (int i = 0; i < n; ++i)
            d[i] *= smoother.getNextValue();
    }
    outGainSmoothed.skip (n);
}

juce::AudioProcessorEditor* ABGroundTruthAudioProcessor::createEditor()
{
    return new ABGroundTruthAudioProcessorEditor (*this);
}

void ABGroundTruthAudioProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    if (auto xml = apvts.copyState().createXml())
        copyXmlToBinary (*xml, destData);
}

void ABGroundTruthAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    if (auto xml = getXmlFromBinary (data, sizeInBytes))
        if (xml->hasTagName (apvts.state.getType()))
            apvts.replaceState (juce::ValueTree::fromXml (*xml));
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new ABGroundTruthAudioProcessor();
}
