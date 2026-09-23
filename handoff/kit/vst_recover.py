#!/usr/bin/env python3
"""
vst_recover.py — recover as much source-level content as possible from a compiled
VST2 (.dll) / VST3 (.vst3) plugin you own the rights to.

Subcommands (run in this order):
  inventory  Unpack the bundle, find a .pdb, dump strings, carve embedded resources
             (PNG/JPEG/SVG/XML/TTF/OTF/JSON) from JUCE BinaryData, detect JUCE version.
  params     Load the plugin in-process (pedalboard) and dump every parameter:
             id, name, range, default, units, choices  ->  params.json
  ghidra     Run Ghidra headless with ExportDecompiled.java -> per-class .cpp files,
             demangled symbol map, float-heavy "DSP candidate" ranking.
  retdec     Fallback decompiler (single big .c file) if Ghidra is unavailable.
  scaffold   Generate a JUCE PluginProcessor/PluginEditor skeleton whose APVTS
             layout is rebuilt from params.json, with recovered DSP pseudo-code
             dropped in as TODO blocks next to the matching function names.
  all        inventory -> params -> ghidra -> scaffold

Everything lands under ./recovered/<PluginName>/.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------- utils

MAGIC = {
    "png":  (b"\x89PNG\r\n\x1a\n", b"IEND\xaeB`\x82", 8),
    "jpg":  (b"\xff\xd8\xff", b"\xff\xd9", 2),
    "gif":  (b"GIF89a", b"\x00;", 2),
    "ttf":  (b"\x00\x01\x00\x00\x00", None, 0),
    "otf":  (b"OTTO", None, 0),
    "svg":  (b"<svg", b"</svg>", 6),
    "xml":  (b"<?xml", None, 0),
}


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=False)


def which(name: str) -> str | None:
    return shutil.which(name)


def out_dir(plugin: Path, root: Path) -> Path:
    d = root / plugin.stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_binaries(plugin: Path) -> list[Path]:
    """A .vst3 on Windows/mac is a folder bundle; return every real PE/Mach-O inside."""
    if plugin.is_file():
        return [plugin]
    exts = {".vst3", ".dll", ".dylib", ".so", ""}
    hits = []
    for p in plugin.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts and p.stat().st_size > 64 * 1024:
            with open(p, "rb") as f:
                head = f.read(4)
            if head[:2] == b"MZ" or head in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\x7fELF"):
                hits.append(p)
    return hits


# ----------------------------------------------------------------------- inventory

def carve_resources(data: bytes, dest: Path) -> dict[str, int]:
    """Carve JUCE BinaryData blobs by magic number. Crude but effective: JUCE stores
    resources verbatim as const char arrays, so signatures survive intact."""
    dest.mkdir(exist_ok=True)
    counts: dict[str, int] = {}
    for ext, (start, end, _) in MAGIC.items():
        idx = 0
        n = 0
        while True:
            s = data.find(start, idx)
            if s < 0:
                break
            if end:
                e = data.find(end, s)
                if e < 0:
                    break
                blob = data[s : e + len(end)]
            else:
                # no terminator: take up to next NUL run or 2 MB, whichever first
                e = data.find(b"\x00\x00\x00\x00", s + 64)
                blob = data[s : (e if e > 0 else s + 2_000_000)]
            if len(blob) > 64:
                (dest / f"{ext}_{n:03d}.{ext}").write_bytes(blob)
                n += 1
            idx = s + len(start)
        if n:
            counts[ext] = n
    return counts


def dump_strings(data: bytes, dest: Path, min_len: int = 6) -> Path:
    ascii_re = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    utf16_re = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % min_len)
    lines = set()
    for m in ascii_re.finditer(data):
        lines.add(m.group().decode("ascii", "ignore"))
    for m in utf16_re.finditer(data):
        lines.add(m.group().decode("utf-16le", "ignore"))
    p = dest / "strings.txt"
    p.write_text("\n".join(sorted(lines)), encoding="utf-8")
    return p


def classify_strings(strings_file: Path, dest: Path) -> None:
    """Sort strings into buckets that map onto source files you'll rebuild."""
    buckets = {
        "param_ids": re.compile(r"^[a-z][A-Za-z0-9_]{2,40}$"),
        "juce_classes": re.compile(r"^(juce::|JUCE|Component|Slider|Look)"),
        "source_paths": re.compile(r"\.(cpp|h|hpp|mm)$|[\\/](Source|JuceLibraryCode|modules)[\\/]"),
        "xml_state": re.compile(r"^<|/>$|ValueTree|APVTS|state"),
        "presets": re.compile(r"(?i)preset|program|bank"),
        "license_security": re.compile(r"(?i)licen|serial|activat|trial|expire|hwid|machine.?id|hmac|sha|aes|rsa|obfus"),
        "dsp_terms": re.compile(r"(?i)oversampl|adaa|tanh|limiter|lookahead|sidechain|crossover|biquad|svf|lufs|true.?peak|saturat|drive|glue|comp|eq|hpf|lpf|shelf"),
        "ui_terms": re.compile(r"(?i)knob|meter|panel|drawer|halo|thermal|font|colour|color|theme|page|tab"),
    }
    out = {k: [] for k in buckets}
    for line in strings_file.read_text(encoding="utf-8").splitlines():
        for k, rx in buckets.items():
            if rx.search(line):
                out[k].append(line)
    (dest / "strings_classified.json").write_text(json.dumps(out, indent=2))
    # source_paths is gold: it tells you the original file tree
    if out["source_paths"]:
        (dest / "ORIGINAL_FILE_TREE.txt").write_text("\n".join(sorted(set(out["source_paths"]))))


def detect_juce(strings_file: Path) -> str | None:
    txt = strings_file.read_text(encoding="utf-8")
    m = re.search(r"JUCE v?(\d+\.\d+\.\d+)", txt)
    return m.group(1) if m else None


def pe_has_pdb(data: bytes) -> str | None:
    m = re.search(rb"RSDS.{20}([\x20-\x7e]+\.pdb)", data, re.S)
    return m.group(1).decode() if m else None


def cmd_inventory(args) -> None:
    plugin = Path(args.plugin).resolve()
    dest = out_dir(plugin, Path(args.out))
    bins = find_binaries(plugin)
    if not bins:
        sys.exit("No PE/Mach-O/ELF binary found in " + str(plugin))
    report = {"plugin": str(plugin), "binaries": []}
    for b in bins:
        data = b.read_bytes()
        bdir = dest / "inventory" / b.stem
        bdir.mkdir(parents=True, exist_ok=True)
        strings = dump_strings(data, bdir)
        classify_strings(strings, bdir)
        carved = carve_resources(data, bdir / "resources")
        pdb = pe_has_pdb(data)
        entry = {
            "path": str(b),
            "size": len(data),
            "juce_version": detect_juce(strings),
            "pdb_reference": pdb,
            "pdb_present_next_to_binary": bool(pdb and (b.parent / Path(pdb).name).exists()),
            "carved_resources": carved,
        }
        report["binaries"].append(entry)
        print(json.dumps(entry, indent=2))
    (dest / "inventory.json").write_text(json.dumps(report, indent=2))
    print("\nInventory written to", dest / "inventory.json")
    if any(e["pdb_reference"] and not e["pdb_present_next_to_binary"] for e in report["binaries"]):
        print("!! Binary references a .pdb — FIND IT. Search build/, Release/, x64/, OneDrive, "
              "old CI artifacts. With the .pdb Ghidra restores every function/variable name.")


# -------------------------------------------------------------------------- params

def cmd_params(args) -> None:
    plugin = Path(args.plugin).resolve()
    dest = out_dir(plugin, Path(args.out))
    try:
        import pedalboard  # type: ignore
    except ImportError:
        sys.exit("pip install pedalboard   (must run on the OS the plugin was built for)")
    if platform.system() == "Linux" and plugin.suffix.lower() in (".dll", ".vst3") and \
            not any(p.suffix == ".so" for p in plugin.rglob("*")):
        sys.exit("A Windows/mac plugin cannot be loaded on Linux. Run `params` on the target OS.")
    p = pedalboard.load_plugin(str(plugin))
    params = {}
    for name in p.parameters:
        prm = getattr(p, name)
        d = {"name": name}
        for attr in ("label", "units", "min_value", "max_value", "step_size", "default_value",
                     "valid_values", "type", "raw_value", "string_value"):
            v = getattr(prm, attr, None)
            if v is not None:
                try:
                    json.dumps(v)
                    d[attr] = v
                except TypeError:
                    d[attr] = str(v)
        params[name] = d
    out = {
        "plugin": str(plugin),
        "name": getattr(p, "name", plugin.stem),
        "is_instrument": getattr(p, "is_instrument", False),
        "parameter_count": len(params),
        "parameters": params,
    }
    (dest / "params.json").write_text(json.dumps(out, indent=2, default=str))
    # Try to pull the full APVTS/plugin state blob — this is your saved ValueTree XML
    try:
        state = p.raw_state  # bytes in newer pedalboard
        (dest / "state.bin").write_bytes(bytes(state))
        txt = bytes(state).decode("utf-8", "ignore")
        if "<" in txt:
            (dest / "state_valuetree.xml").write_text(txt)
    except Exception as e:  # noqa: BLE001
        print("  (state blob not exposed by this pedalboard version:", e, ")")
    print(f"{len(params)} parameters -> {dest / 'params.json'}")


# -------------------------------------------------------------------------- ghidra

def find_ghidra() -> Path | None:
    env = os.environ.get("GHIDRA_INSTALL_DIR")
    cands = [env] if env else []
    cands += [str(p) for p in Path.home().glob("ghidra_*")]
    cands += [str(p) for p in Path("/opt").glob("ghidra*")]
    cands += [str(p) for p in Path("C:/").glob("ghidra*")] if platform.system() == "Windows" else []
    for c in cands:
        if not c:
            continue
        c = Path(c)
        h = c / "support" / ("analyzeHeadless.bat" if platform.system() == "Windows" else "analyzeHeadless")
        if h.exists():
            return h
    return None


def cmd_ghidra(args) -> None:
    plugin = Path(args.plugin).resolve()
    dest = out_dir(plugin, Path(args.out))
    headless = find_ghidra()
    if not headless:
        sys.exit("Ghidra not found. Set GHIDRA_INSTALL_DIR or install per README (GitHub releases).")
    script_dir = Path(__file__).parent / "ghidra_scripts"
    proj = dest / "ghidra_project"
    proj.mkdir(exist_ok=True)
    export = dest / "decompiled"
    export.mkdir(exist_ok=True)
    for b in find_binaries(plugin):
        cmd = [str(headless), str(proj), "vst_recover",
               "-import", str(b), "-overwrite",
               "-scriptPath", str(script_dir),
               "-postScript", "ExportDecompiled.java", str(export)]
        pdb = b.parent / (b.stem + ".pdb")
        if pdb.exists():
            cmd += ["-loader", "PeLoader"]  # Ghidra auto-applies a sibling .pdb during analysis
            print("  Using PDB:", pdb)
        if args.max_mem:
            os.environ["MAXMEM"] = args.max_mem
        run(cmd, check=False)
    print("\nDecompiled output ->", export)
    print("  Start with dsp_candidates.md, then classes/*.cpp")


# -------------------------------------------------------------------------- retdec

def cmd_retdec(args) -> None:
    plugin = Path(args.plugin).resolve()
    dest = out_dir(plugin, Path(args.out)) / "retdec"
    dest.mkdir(exist_ok=True)
    rd = which("retdec-decompiler") or which("retdec-decompiler.py")
    if not rd:
        sys.exit("retdec-decompiler not on PATH (https://github.com/avast/retdec/releases)")
    for b in find_binaries(plugin):
        run([rd, str(b), "-o", str(dest / (b.stem + ".c")), "--cleanup"], check=False)
    print("RetDec output ->", dest)


# ------------------------------------------------------------------------ scaffold

def _cpp_ident(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return s if not s[:1].isdigit() else "_" + s


def cmd_scaffold(args) -> None:
    plugin = Path(args.plugin).resolve()
    dest = out_dir(plugin, Path(args.out))
    pj = dest / "params.json"
    if not pj.exists():
        sys.exit("Run `params` first (params.json missing).")
    params = json.loads(pj.read_text())
    name = _cpp_ident(params.get("name") or plugin.stem)
    src = dest / "scaffold" / "Source"
    src.mkdir(parents=True, exist_ok=True)

    # ---- APVTS layout rebuilt from the live parameter dump
    layout_lines = []
    for pid, p in params["parameters"].items():
        cid = _cpp_ident(pid)
        lo, hi = p.get("min_value", 0.0), p.get("max_value", 1.0)
        dflt = p.get("default_value", lo)
        choices = p.get("valid_values")
        if isinstance(choices, list) and choices and all(isinstance(c, str) for c in choices):
            if set(choices) <= {"On", "Off", "true", "false", "True", "False"}:
                layout_lines.append(
                    f'    layout.add (std::make_unique<juce::AudioParameterBool> ("{pid}", "{p.get("name", pid)}", '
                    f'{str(str(dflt).lower() in ("on", "true", "1")).lower()}));')
            else:
                arr = ", ".join(f'"{c}"' for c in choices)
                di = choices.index(str(dflt)) if str(dflt) in choices else 0
                layout_lines.append(
                    f'    layout.add (std::make_unique<juce::AudioParameterChoice> ("{pid}", "{p.get("name", pid)}", '
                    f'juce::StringArray {{ {arr} }}, {di}));')
        else:
            try:
                lo_f, hi_f, d_f = float(lo), float(hi), float(dflt)
            except (TypeError, ValueError):
                lo_f, hi_f, d_f = 0.0, 1.0, 0.0
            layout_lines.append(
                f'    layout.add (std::make_unique<juce::AudioParameterFloat> ("{pid}", "{p.get("name", pid)}", '
                f'juce::NormalisableRange<float> ({lo_f}f, {hi_f}f), {d_f}f'
                + (f', "{p["units"]}"' if p.get("units") else "") + "));   // TODO: skew/step from decompile")
        _ = cid

    # ---- pull decompiled DSP candidates in as TODO blocks
    dsp_notes = ""
    cand = dest / "decompiled" / "dsp_candidates.md"
    if cand.exists():
        dsp_notes = "\n// ===== Recovered DSP candidates (from Ghidra) — port each into a clean class =====\n"
        dsp_notes += "".join("// " + l + "\n" for l in cand.read_text().splitlines()[:200])

    header = f"""#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>

// Reconstructed from the compiled plugin by vst_recover.py. Parameter IDs, names,
// ranges and defaults are EXACT (dumped from the live binary) — keep them so old
// sessions/presets still load. DSP bodies are TODO: port from decompiled/.

class {name}AudioProcessor : public juce::AudioProcessor
{{
public:
    {name}AudioProcessor();
    ~{name}AudioProcessor() override = default;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {{}}
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override {{ return true; }}
    const juce::String getName() const override {{ return "{params.get('name', plugin.stem)}"; }}
    bool acceptsMidi() const override {{ return false; }}
    bool producesMidi() const override {{ return false; }}
    double getTailLengthSeconds() const override {{ return 0.0; }}
    int getNumPrograms() override {{ return 1; }}
    int getCurrentProgram() override {{ return 0; }}
    void setCurrentProgram (int) override {{}}
    const juce::String getProgramName (int) override {{ return {{}}; }}
    void changeProgramName (int, const juce::String&) override {{}}
    void getStateInformation (juce::MemoryBlock&) override;
    void setStateInformation (const void*, int) override;

    juce::AudioProcessorValueTreeState apvts;

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR ({name}AudioProcessor)
}};
"""
    cpp = f"""#include "PluginProcessor.h"
#include "PluginEditor.h"

{name}AudioProcessor::{name}AudioProcessor()
    : AudioProcessor (BusesProperties().withInput ("Input", juce::AudioChannelSet::stereo(), true)
                                       .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, "PARAMETERS", createParameterLayout())
{{
}}

juce::AudioProcessorValueTreeState::ParameterLayout {name}AudioProcessor::createParameterLayout()
{{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;
{chr(10).join(layout_lines)}
    return layout;
}}

void {name}AudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{{
    juce::ignoreUnused (sampleRate, samplesPerBlock);
    // TODO: oversampling, limiter lookahead (setLatencySamples), filter prep
}}

void {name}AudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{{
    juce::ScopedNoDenormals noDenormals;
    juce::ignoreUnused (buffer);
    // TODO: port signal chain from decompiled/dsp_candidates.md
}}

void {name}AudioProcessor::getStateInformation (juce::MemoryBlock& destData)
{{
    if (auto xml = apvts.copyState().createXml())
        copyXmlToBinary (*xml, destData);
}}

void {name}AudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{{
    if (auto xml = getXmlFromBinary (data, sizeInBytes))
        if (xml->hasTagName (apvts.state.getType()))
            apvts.replaceState (juce::ValueTree::fromXml (*xml));
}}

juce::AudioProcessorEditor* {name}AudioProcessor::createEditor()
{{
    return new {name}AudioProcessorEditor (*this);
}}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() {{ return new {name}AudioProcessor(); }}
{dsp_notes}"""
    editor_h = f"""#pragma once
#include "PluginProcessor.h"

// Attachments for every recovered parameter are generated below so the UI is
// wired on day one. Replace the plain Sliders with your LookAndFeel/knob classes;
// carved images/fonts live in ../inventory/*/resources/.
class {name}AudioProcessorEditor : public juce::AudioProcessorEditor
{{
public:
    explicit {name}AudioProcessorEditor ({name}AudioProcessor&);
    void paint (juce::Graphics&) override;
    void resized() override;
private:
    {name}AudioProcessor& proc;
    juce::OwnedArray<juce::Slider> sliders;
    juce::OwnedArray<juce::Label> labels;
    juce::OwnedArray<juce::AudioProcessorValueTreeState::SliderAttachment> attachments;
}};
"""
    editor_cpp = f"""#include "PluginEditor.h"

{name}AudioProcessorEditor::{name}AudioProcessorEditor ({name}AudioProcessor& p)
    : AudioProcessorEditor (&p), proc (p)
{{
    const char* ids[] = {{ {", ".join(f'"{pid}"' for pid in params["parameters"])} }};
    for (auto* id : ids)
    {{
        if (proc.apvts.getParameter (id) == nullptr) continue;
        auto* s = sliders.add (new juce::Slider (juce::Slider::RotaryHorizontalVerticalDrag, juce::Slider::TextBoxBelow));
        auto* l = labels.add (new juce::Label ({{}}, id));
        l->attachToComponent (s, false);
        addAndMakeVisible (s);
        attachments.add (new juce::AudioProcessorValueTreeState::SliderAttachment (proc.apvts, id, *s));
    }}
    setSize (900, 600);
}}

void {name}AudioProcessorEditor::paint (juce::Graphics& g) {{ g.fillAll (juce::Colour (0xff1a1a1a)); }}

void {name}AudioProcessorEditor::resized()
{{
    juce::FlexBox fb; fb.flexWrap = juce::FlexBox::Wrap::wrap;
    for (auto* s : sliders) fb.items.add (juce::FlexItem (*s).withMinWidth (110).withMinHeight (120));
    fb.performLayout (getLocalBounds().reduced (12));
}}
"""
    (src / "PluginProcessor.h").write_text(header)
    (src / "PluginProcessor.cpp").write_text(cpp)
    (src / "PluginEditor.h").write_text(editor_h)
    (src / "PluginEditor.cpp").write_text(editor_cpp)
    cmake = f"""cmake_minimum_required(VERSION 3.22)
project({name} VERSION 1.0.0)
add_subdirectory(JUCE)   # git clone https://github.com/juce-framework/JUCE (match inventory.json juce_version)
juce_add_plugin({name}
    COMPANY_NAME "Multibanded LLC"
    PLUGIN_MANUFACTURER_CODE Mzaa
    PLUGIN_CODE {name[:4].ljust(4,'x')}
    FORMATS VST3 AU Standalone
    PRODUCT_NAME "{params.get('name', plugin.stem)}")
target_sources({name} PRIVATE Source/PluginProcessor.cpp Source/PluginEditor.cpp)
target_compile_definitions({name} PUBLIC JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_VST3_CAN_REPLACE_VST2=0)
target_link_libraries({name} PRIVATE juce::juce_audio_utils juce::juce_dsp
    PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_lto_flags juce::juce_recommended_warning_flags)
"""
    (dest / "scaffold" / "CMakeLists.txt").write_text(cmake)
    print("Scaffold ->", dest / "scaffold")
    print("  NOTE: keep PLUGIN_MANUFACTURER_CODE/PLUGIN_CODE identical to the original build so DAW sessions "
          "re-link; find them in inventory strings (4-char codes) or the old CMake/Projucer file.")


# ----------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plugin", help="path to .dll / .vst3 (file or bundle folder)")
    ap.add_argument("-o", "--out", default="recovered", help="output root (default ./recovered)")
    ap.add_argument("--max-mem", default=None, help="Ghidra heap, e.g. 8G")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("inventory", "params", "ghidra", "retdec", "scaffold", "all"):
        sub.add_parser(c)
    args = ap.parse_args()
    steps = {"inventory": cmd_inventory, "params": cmd_params, "ghidra": cmd_ghidra,
             "retdec": cmd_retdec, "scaffold": cmd_scaffold}
    if args.cmd == "all":
        for s in ("inventory", "params", "ghidra", "scaffold"):
            print(f"\n=== {s} ===")
            try:
                steps[s](args)
            except SystemExit as e:
                print("  skipped:", e)
    else:
        steps[args.cmd](args)


if __name__ == "__main__":
    main()
