import { uniq } from "./bytes";
import type { BinaryResult, GroupResult, ParamRec, Resource } from "./types";

/** v2 generation helpers — verbatim. Everything here is GENERATED / SCAFFOLD_ONLY output. */

export function ident(s: string): string { return (s.replace(/\.(dll|vst3|vst|dylib|component)$/i, '').replace(/[^A-Za-z0-9_]/g, '_') || 'Plugin'); }
export function safeName(cls: string, i: number): string { const leaf = cls.split('::').pop()!; return /^[A-Za-z_]\w{2,60}$/.test(leaf) ? leaf : 'RecoveredClass_' + String(i + 1).padStart(4, '0'); }
export function baseFor(cls: string): string {
  const n = cls.split('::').pop()!;
  if (/AudioProcessorEditor|Editor$/.test(n)) return 'juce::AudioProcessorEditor';
  if (/AudioProcessor$|Processor$/.test(n)) return 'juce::AudioProcessor';
  if (/LookAndFeel/.test(n)) return 'juce::LookAndFeel_V4';
  if (/Knob|Slider|Dial/.test(n)) return 'juce::Slider';
  if (/Button/.test(n)) return 'juce::TextButton';
  if (/Meter|Visualiz|Panel|Drawer|Strip|View|Canvas|Display|Component|Overlay|Grid|Page|Tab|Window/.test(n)) return 'juce::Component';
  return '';
}
export function roleFor(cls: string): string {
  const n = ' ' + cls.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2').replace(/[:_]+/g, ' ').toLowerCase() + ' ';
  const has = (rx: RegExp) => rx.test(n);
  if (has(/ (clip\w*|satur\w*|distort\w*|shaper|drive|tanh|fold\w*) /)) return 'WAVESHAPER';
  if (has(/ limit\w* /)) return 'LIMITER'; if (has(/ (compress\w*|comp|glue) /)) return 'COMPRESSOR'; if (has(/ gate\w* /)) return 'GATE';
  if (has(/ (filter|lpf|hpf|shelf|eq|ladder|svf|tpt|biquad|crossover|lowpass|highpass|bandpass|iir|fir) /)) return 'FILTER';
  if (has(/ (oversampl\w*|resampl\w*|upsamp\w*|downsamp\w*|transposer|stretch) /)) return 'OVERSAMPLER'; if (has(/ (delay|reverb|convo\w*|convolution) /)) return 'DELAY_REVERB';
  if (has(/ (env|envelope|detector|follower) /)) return 'ENVELOPE'; if (has(/ (meter|lufs|peak|rms|vu) /)) return 'METER';
  if (has(/ (preset|state|manager|chain|modulation|macro|parameters|property) /)) return 'STATE_CONTROL';
  if (has(/ (editor|panel|knob|button|look and feel|lookandfeel|window|component|page|view|slider|label|tooltip|alert|box|led) /)) return 'GUI';
  if (has(/ (licen\w*|activ\w*|auth\w*) /)) return 'PROTECTED_SUBSYSTEM';
  return 'UNKNOWN';
}

export interface ClassFiles { cls: string; safe: string; base: string; role: string; roleBasis: string[]; h: string; cpp: string; dir: string }

export function classFiles(cls: string, i: number, binName: string): ClassFiles {
  const parts = cls.split('::'), name = parts.pop(), ns = parts.filter(p => /^[A-Za-z_]\w*$/.test(p));
  void name;
  const safe = safeName(cls, i), base = baseFor(cls), role = roleFor(cls);
  const roleBasis = role === 'UNKNOWN' ? [] : ['name tokens'];
  const open = ns.map(n => `namespace ${n} {`).join(' '), close = ns.map(() => '}').join(' ');
  const isComp = /juce::(Component|AudioProcessorEditor|Slider|TextButton)/.test(base);
  const h = `#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>
// GENERATED scaffold — NOT compiled (lives in RecoveredScaffolds/, promote to Active/ only after BEHAVIOR_MATCHED).
// Class identity: VERIFIED_RTTI name (${binName}). Base class: INFERRED from name. Role: ${role} (CANDIDATE, basis: name tokens).
// Method bodies: SCAFFOLD_ONLY — fill from 01_evidence/decompiler after the desktop Ghidra stage; see 07_agent_handoff/reconstruction_index.json
${open}
class ${safe}${base ? ' : public ' + base : ''}
{
public:
    ${safe}();
    ~${safe}()${base ? ' override' : ''};
${isComp ? '    void paint (juce::Graphics&) override;\n    void resized() override;\n' : ''}${/AudioProcessor$/.test(base) ? '    void prepareToPlay (double, int) override;\n    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;\n' : ''}${!base ? '    void prepare (double sampleRate, int maxBlock);   // GENERATED signature\n    float processSample (float x);                    // GENERATED signature\n' : ''}
private:
    // members: UNKNOWN until decompile (look for this+offset accesses in the constructor)
};
${close}
`;
  const cpp = `#include "${safe}.h"
${open}
${safe}::${safe}() {}
${safe}::~${safe}() {}
${isComp ? `void ${safe}::paint (juce::Graphics& g) { juce::ignoreUnused (g); } // SCAFFOLD_ONLY\nvoid ${safe}::resized() {}\n` : ''}${!base ? `void ${safe}::prepare (double, int) {}\nfloat ${safe}::processSample (float x) { return x; } // SCAFFOLD_ONLY — pass-through, not recovered behaviour\n` : ''}${close}
`;
  return { cls, safe, base, role, roleBasis, h, cpp, dir: 'RecoveredScaffolds/' + (role === 'GUI' ? 'UI/' : role === 'STATE_CONTROL' ? 'State/' : role === 'PROTECTED_SUBSYSTEM' ? 'Protected/' : role === 'UNKNOWN' ? 'Unclassified/' : 'DSP/') };
}

export const nice = (v: number): string => Number.isInteger(v) ? v.toFixed(1) : String(+v.toFixed(6));

export function typeInfo(p: ParamRec): { status: string; basis: string } {
  const vals = uniq(p.values || []);
  if (vals.length >= 2 && vals.every(v => v === 0 || v === 1)) return { status: 'INFERRED_TYPE_STRONG: bool/discrete', basis: 'both 0 and 1 observed, nothing else' };
  if (vals.length === 1 && (vals[0] === 0 || vals[0] === 1)) return { status: 'TYPE_UNKNOWN' + (/oversampl|bypass|enable|on|off|switch|mode|auto/i.test(p.id) ? ' (discrete candidate from name)' : ''), basis: 'single observed value' };
  if (vals.length >= 3) return { status: 'INFERRED_TYPE_WEAK: continuous', basis: 'multiple distinct non-binary values' };
  return { status: 'TYPE_UNKNOWN', basis: 'insufficient observations' };
}

export function serializedKeyRecord(p: ParamRec) {
  const ti = typeInfo(p); const v = p.values || []; const indexed = /_\d+(_\d+)*$/.test(p.id);
  return { name: p.id, serialized_key_status: (p.conf ?? 0) >= 3 ? 'VERIFIED_XML (preset/session file)' : p.conf === 2 ? 'VERIFIED_XML (embedded in binary)' : 'CANDIDATE', runtime_parameter_status: 'UNVERIFIED', key_kind_candidate: indexed ? 'INTERNAL_EFFECT_PROPERTY (indexed array element)' : 'XML_PARAMETER_KEY (may or may not be an exported VST parameter)', source: p.source, observed_serialized_values: v, observed_min: v.length ? Math.min(...v) : null, observed_max: v.length ? Math.max(...v) : null, value_representation: 'UNKNOWN', legal_range: 'UNKNOWN', factory_default: 'UNKNOWN', units: 'UNKNOWN', step_count: 'UNKNOWN', type_status: ti.status, type_basis: ti.basis, note: 'existence in serialized state is verified; automatability, representation (normalized/plain/enum), range and default require the runtime host and state-differential test' };
}

export function processorFiles(r: GroupResult, nm: string) {
  const ps = Object.values(r.params).sort((a, b) => (b.conf||0) - (a.conf||0) || a.id.localeCompare(b.id));
  const layout = ps.map(p => {
    const vals = p.values || []; const t = typeInfo(p);
    return `    layout.add (std::make_unique<juce::AudioParameterFloat> ("${p.id}", "${p.id}", juce::NormalisableRange<float> (0.0f, 1.0f), 0.0f)); // serialized key VERIFIED (${p.source}); runtime parameter UNVERIFIED; range GENERATED_PLACEHOLDER_RANGE; default UNKNOWN (placeholder 0); type ${t.status}${vals.length ? '; observed serialized values ' + nice(Math.min(...vals)) + '..' + nice(Math.max(...vals)) + ' n=' + vals.length : ''}`;
  }).join('\n');
  const h = `#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>
// GENERATED. IDs are VERIFIED serialized keys from XML, NOT verified VST parameters; every range/default is a GENERATED_PLACEHOLDER until vst3host introspection (Phase 2).
// All AudioProcessor overrides below are GENERATED_BUILD_PLACEHOLDER values, not recovered behaviour.
class ${nm}AudioProcessor : public juce::AudioProcessor {
public:
    ${nm}AudioProcessor();
    void prepareToPlay (double, int) override;
    void releaseResources() override {}
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }                    // GENERATED_BUILD_PLACEHOLDER
    const juce::String getName() const override { return "${nm}"; }   // from file name — UNVERIFIED
    bool acceptsMidi() const override { return false; }               // GENERATED_BUILD_PLACEHOLDER (verify via runtime bus/event inputs)
    bool producesMidi() const override { return false; }              // GENERATED_BUILD_PLACEHOLDER
    double getTailLengthSeconds() const override { return 0.0; }      // GENERATED_BUILD_PLACEHOLDER — likely WRONG if reverb/convolution present; recover from runtime
    int getNumPrograms() override { return 1; }                       // GENERATED_BUILD_PLACEHOLDER (IUnitInfo program lists)
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}
    void getStateInformation (juce::MemoryBlock&) override;           // GENERATED_STATE_COMPATIBILITY_SCAFFOLD
    void setStateInformation (const void*, int) override;             // GENERATED_STATE_COMPATIBILITY_SCAFFOLD
    juce::AudioProcessorValueTreeState apvts;
private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
};
`;
  const cpp = `#include "PluginProcessor.h"
#include "PluginEditor.h"
// Bus layout: GENERATED_BUILD_PLACEHOLDER (stereo in/out assumed; verify via IComponent::getBusInfo)
${nm}AudioProcessor::${nm}AudioProcessor()
    : AudioProcessor (BusesProperties().withInput ("Input", juce::AudioChannelSet::stereo(), true).withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, "PARAMETERS", createParameterLayout()) {}

juce::AudioProcessorValueTreeState::ParameterLayout ${nm}AudioProcessor::createParameterLayout()
{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;
${layout || '    // no VERIFIED parameter IDs yet — run Phase 2 introspection or drop presets/sessions'}
    return layout;
}
void ${nm}AudioProcessor::prepareToPlay (double sr, int block) { juce::ignoreUnused (sr, block); }
void ${nm}AudioProcessor::processBlock (juce::AudioBuffer<float>& b, juce::MidiBuffer&) { juce::ScopedNoDenormals nd; juce::ignoreUnused (b); } // SCAFFOLD_ONLY (pass-through; nothing from RecoveredScaffolds is wired in)
// GENERATED_STATE_COMPATIBILITY_SCAFFOLD — standard APVTS XML; original serialization NOT yet recovered. Verify by state-differential test (Phase 2).
void ${nm}AudioProcessor::getStateInformation (juce::MemoryBlock& d) { if (auto x = apvts.copyState().createXml()) copyXmlToBinary (*x, d); }
void ${nm}AudioProcessor::setStateInformation (const void* d, int n) { if (auto x = getXmlFromBinary (d, n)) if (x->hasTagName (apvts.state.getType())) apvts.replaceState (juce::ValueTree::fromXml (*x)); }
juce::AudioProcessorEditor* ${nm}AudioProcessor::createEditor() { return new ${nm}AudioProcessorEditor (*this); }
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new ${nm}AudioProcessor(); }
`;
  const eh = `#pragma once
#include "PluginProcessor.h"
// GENERATED generic editor — original UI NOT recovered. Rebuild from 02_recovered_assets + BinaryData mapping.
class ${nm}AudioProcessorEditor : public juce::AudioProcessorEditor {
public:
    explicit ${nm}AudioProcessorEditor (${nm}AudioProcessor&);
    void paint (juce::Graphics& g) override { g.fillAll (juce::Colour (0xff182430)); }
    void resized() override;
private:
    ${nm}AudioProcessor& proc; juce::OwnedArray<juce::Slider> sliders; juce::OwnedArray<juce::Label> labels;
    juce::OwnedArray<juce::AudioProcessorValueTreeState::SliderAttachment> att;
};
`;
  const ec = `#include "PluginEditor.h"
${nm}AudioProcessorEditor::${nm}AudioProcessorEditor (${nm}AudioProcessor& p) : AudioProcessorEditor (&p), proc (p)
{
    for (auto* prm : proc.getParameters())
        if (auto* wid = dynamic_cast<juce::AudioProcessorParameterWithID*> (prm)) {
            auto* s = sliders.add (new juce::Slider (juce::Slider::RotaryHorizontalVerticalDrag, juce::Slider::TextBoxBelow));
            auto* l = labels.add (new juce::Label ({}, wid->getParameterID())); l->attachToComponent (s, false);
            addAndMakeVisible (s); att.add (new juce::AudioProcessorValueTreeState::SliderAttachment (proc.apvts, wid->getParameterID(), *s)); }
    setSize (900, 600);
}
void ${nm}AudioProcessorEditor::resized() { juce::FlexBox fb; fb.flexWrap = juce::FlexBox::Wrap::wrap; for (auto* s : sliders) fb.items.add (juce::FlexItem (*s).withMinWidth (110).withMinHeight (120)); fb.performLayout (getLocalBounds().reduced (12)); }
`;
  return { h, cpp, eh, ec };
}

export function identity(r: GroupResult, b: BinaryResult) {
  const codes = (r.buckets['Plugin codes'] || []);
  const vendor = (r.strings.find(s => /^JucePlugin_Manufacturer$/.test(s)) ? null : null);
  return { format: b.pe.format || 'unknown', arch: b.pe.machine || 'unknown', manufacturerCode: 'UNVERIFIED', pluginCode: 'UNVERIFIED', vendor: vendor || 'UNVERIFIED', product: ident(b.name) + ' (from file name — UNVERIFIED)', fuid: 'UNVERIFIED (Phase 2: vst3host GetPluginFactory)', jucePluginMacros: codes };
}

export function cmakeFor(r: GroupResult, nm: string, classes: ClassFiles[], validRes: Resource[], b: BinaryResult): string {
  const fmt = b.pe.format === 'VST2' ? 'VST' : 'VST3';
  return `cmake_minimum_required(VERSION 3.22)
project(${nm} VERSION 1.0.0)
add_subdirectory(JUCE) # git clone https://github.com/juce-framework/JUCE${r.juce ? ' --branch ' + r.juce : ' (version not embedded in binary — match your original toolchain)'}

# ---- BUILD MODES
#  FIDELITY  (default): requires the ORIGINAL identity. Only this mode can claim DAW-session / preset relinking.
#  SURROGATE (-DRECOVERY_SURROGATE_BUILD=ON): temporary generated identity so DSP work, pluginval and differential
#            tests can run before Phase 2 recovers the real FUID/codes. NEVER session-compatible.
option(RECOVERY_SURROGATE_BUILD "Build with a temporary generated identity (not session-compatible)" OFF)
set(RECOVERED_COMPANY "")           # UNVERIFIED — fill from 01_evidence/vst3/factory.json (Phase 2) or original project files
set(RECOVERED_MANUFACTURER_CODE "") # UNVERIFIED
set(RECOVERED_PLUGIN_CODE "")       # UNVERIFIED
if(RECOVERY_SURROGATE_BUILD)
  set(RECOVERED_COMPANY "SURROGATE-RECOVERY")
  set(RECOVERED_MANUFACTURER_CODE "Srgt")
  set(RECOVERED_PLUGIN_CODE "R${nm.replace(/[^A-Za-z]/g, '').slice(0, 3).padEnd(3, 'x')}")
  message(WARNING "SURROGATE identity in use: this build cannot relink old sessions.")
elseif(RECOVERED_MANUFACTURER_CODE STREQUAL "" OR RECOVERED_PLUGIN_CODE STREQUAL "")
  message(FATAL_ERROR "FIDELITY build needs the original identity (UNVERIFIED). Set RECOVERED_* above, or configure with -DRECOVERY_SURROGATE_BUILD=ON for DSP work.")
endif()

# Only the analysed format (${b.pe.format || '?'} ${b.pe.machine || '?'}). Enable Standalone/AU deliberately, later.
juce_add_plugin(${nm} COMPANY_NAME "\${RECOVERED_COMPANY}" PLUGIN_MANUFACTURER_CODE \${RECOVERED_MANUFACTURER_CODE} PLUGIN_CODE \${RECOVERED_PLUGIN_CODE} FORMATS ${fmt} PRODUCT_NAME "${nm}")
${validRes.length ? `juce_add_binary_data(${nm}Data SOURCES ${validRes.map(x => 'Resources/' + x.name).join(' ')})` : '# no VALID_EXACT resources carved'}

# Only Source/Active is compiled. Source/RecoveredScaffolds/ (${classes.length} classes) is evidence-derived scaffolding and is
# deliberately NOT in the build; promote a class here only once it is BEHAVIOR_MATCHED (see 07_agent_handoff/reconstruction_index.json).
target_sources(${nm} PRIVATE
    Source/Active/PluginProcessor.cpp
    Source/Active/PluginEditor.cpp)
target_compile_definitions(${nm} PUBLIC JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_VST3_CAN_REPLACE_VST2=0)
target_link_libraries(${nm} PRIVATE ${validRes.length ? nm + 'Data ' : ''}juce::juce_audio_utils juce::juce_dsp PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_lto_flags juce::juce_recommended_warning_flags)
`;
}
