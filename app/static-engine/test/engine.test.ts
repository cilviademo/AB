/**
 * Regression tests for the frozen Static Recovery v2 port, on the deterministic
 * synthetic fixture (fixtures/synthetic/SynthPlug.vst3). Every expectation is a
 * v2 rule from docs/CLAUDE_CODE_PROMPT.md §2 or SPEC §6.
 */
import { readFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { describe, expect, it, beforeAll } from "vitest";
import { parsePE, findRSDS } from "../src/pe";
import { extractStrings } from "../src/strings";
import { classifyClass, classifyPath, demangleMsvcType, demangleItaniumType } from "../src/classify";
import { carve } from "../src/carve";
import { validateResources, xmlWellFormed, pngDims, jpegDims, fontName } from "../src/validate";
import { mapBinaryData } from "../src/binarydata";
import { roleFor, typeInfo, serializedKeyRecord } from "../src/generate";
import { extractStateXml } from "../src/statexml";
import { scanConstants } from "../src/constants";
import { analyzeBinary, analyzeGroup, withSchema } from "../src/analyze";
import { buildBundle } from "../src/bundle";
import { runStatic } from "../src/run";
import type { Resource } from "../src/types";

const ROOT = resolve(__dirname, "../../..");
const FIXTURE = resolve(ROOT, "fixtures/synthetic/SynthPlug.vst3");
let u8: Uint8Array;

beforeAll(() => {
  if (!existsSync(FIXTURE)) execFileSync("python3", [resolve(ROOT, "fixtures/synthetic/make_fixture.py"), FIXTURE]);
  u8 = new Uint8Array(readFileSync(FIXTURE));
});

const tick = async () => {};

describe("PE", () => {
  it("reads machine, linker, sections, exports and format", () => {
    const pe = parsePE(u8);
    expect(pe.machine).toBe("x64");
    expect(pe.linker).toBe("14.0");
    expect(pe.sectionNames).toBe(".text .rdata");
    expect(pe.exports).toEqual(["GetPluginFactory", "InitDll", "ExitDll"]);
    expect(pe.format).toBe("VST3");
    expect(pe.rdata![0]).toBeGreaterThan(0);
  });
  it("finds the RSDS pdb reference", () => {
    expect(findRSDS(u8)).toBe("C:\\dev\\SynthPlug\\build\\SynthPlug.pdb");
  });
  it("is harmless on non-PE bytes", () => {
    expect(parsePE(new Uint8Array(100))).toEqual({});
  });
});

describe("strings and classification", () => {
  it("extracts ASCII and UTF-16 runs", () => {
    const s = extractStrings(u8, 5);
    expect(s).toContain("JUCE v7.0.5");
    expect(s).toContain("MSVC 14.0 x64"); // UTF-16LE
  });
  it("classifies RTTI names by namespace, never by guess", () => {
    expect(classifyClass("juce::Slider")).toBe("FRAMEWORK");
    expect(classifyClass("soundtouch::SoundTouch")).toBe("THIRD_PARTY");
    expect(classifyClass("std::basic_string")).toBe("OS_RUNTIME");
    expect(classifyClass("IUnknown")).toBe("OS_RUNTIME");
    expect(classifyClass("ab")).toBe("FALSE_POSITIVE");
    expect(classifyClass("synth::SynthClipper")).toBe("PLUGIN_OWNED");
  });
  it("demangles MSVC and Itanium type descriptors", () => {
    expect(demangleMsvcType(".?AVSynthClipper@synth@@")).toBe("synth::SynthClipper");
    expect(demangleItaniumType("_ZTSN5synth12SynthClipperE")).toBe("synth::SynthClipper");
    expect(demangleItaniumType("_ZTS7Foo")).toBe("Foo");
  });
  it("classifies build paths into PROJECT_SOURCE | FRAMEWORK | SDK | CRT | BUILD_TOOL | BUILD_MACHINE | UNKNOWN", () => {
    expect(classifyPath("C:\\dev\\SynthPlug\\Source\\PluginProcessor.cpp")).toBe("PROJECT_SOURCE");
    expect(classifyPath("C:\\JUCE\\modules\\juce_dsp\\juce_dsp.h")).toBe("FRAMEWORK");
    expect(classifyPath("C:\\Program Files (x86)\\Windows Kits\\10\\Include\\ucrt\\corecrt_internal_strtox.h")).toBe("CRT");
    expect(classifyPath("D:\\a\\1\\s\\build\\x64\\Release\\junk.obj")).toBe("BUILD_MACHINE");
    expect(classifyPath("C:\\dev\\vst3sdk\\pluginterfaces\\base\\funknown.h")).toBe("SDK");
    expect(classifyPath("C:\\x\\CMakeFiles\\y.cmake")).toBe("BUILD_TOOL");
  });
});

describe("roles (CamelCase tokenized, word boundaries)", () => {
  it("does not match substrings", () => {
    expect(roleFor("ParameterQueue")).not.toBe("METER");   // 'Parameter' contains 'meter'
    expect(roleFor("EventQueue")).not.toBe("FILTER");      // 'Queue' once matched 'eq'
    expect(roleFor("MorphHardClipper")).toBe("WAVESHAPER");
    expect(roleFor("ParametericEQ")).toBe("FILTER");
    expect(roleFor("RotaryKnob")).toBe("GUI");
    expect(roleFor("LicenseManager")).toBe("STATE_CONTROL"); // v2 order: 'manager' before 'licen*'
    expect(roleFor("ActivationDialog")).toBe("PROTECTED_SUBSYSTEM");
    expect(roleFor("SerialScreen")).toBe("UNKNOWN");
  });
});

describe("state XML", () => {
  it("reads embedded <PARAM> keys and the enclosing document", () => {
    const r = extractStateXml(u8, true);
    expect(r.params.map((p) => p.id)).toEqual(["drive", "oversample", "waveShapers_4_2", "drive"]);
    expect(r.xml.startsWith("<PARAMETERS>")).toBe(true);
  });
  it("decodes preset files including base64 blobs", () => {
    const xml = '<PARAMETERS><PARAM id="mix" value="0.3"/></PARAMETERS>';
    const b64 = Buffer.from(xml + " ".repeat(200)).toString("base64");
    const rpp = `<VST "x" y\n${b64.slice(0, 100)}\n${b64.slice(100)}\n>`;
    const r = extractStateXml(new TextEncoder().encode(rpp));
    expect(r.params).toEqual([{ id: "mix", value: 0.3 }]);
  });
});

describe("carving and structural validation", () => {
  let res: Resource[];
  beforeAll(async () => { res = carve(u8); await validateResources(res); });
  it("carves PNG/WAV/TTF/XML with verified boundaries and rejects fakes", () => {
    const byName = Object.fromEntries(res.map((x) => [x.name, x]));
    expect(byName["png_000.png"].status).toBe("VALID_EXACT");
    expect(byName["png_000.png"].dims).toBe("16x16");
    expect(byName["png_001.png"].semantics).toMatch(/^SPRITE_SHEET_CANDIDATE/);
    expect(byName["wav_000.wav"].status).toBe("VALID_EXACT");
    expect(byName["wav_000.wav"].root).toMatch(/^BWF \(JUNK,bext,fmt,data\)/);   // JUNK/bext before fmt: chunk walk, never offset 12
    expect(byName["ttf_000.ttf"].status).toBe("VALID_EXACT");
    expect(byName["ttf_000.ttf"].embeddedName).toBe("Synth Sans");
    expect(res.filter((x) => x.ext === "ttf").length).toBe(1);                   // the 00 01 00 00 in code was rejected by the sfnt check
    expect(res.filter((x) => x.ext === "png").length).toBe(2);                   // the truncated PNG has no IEND → not carved
    expect(byName["jpg_000.jpg"].status).toBe("INVALID");                        // JFIF marker but no frame → INVALID, parser PARSER_INVALID
    expect(byName["jpg_000.jpg"].parser).toBe("PARSER_INVALID");
  });
  it("carves both XML documents and marks the scan complete", () => {
    const xml = res.filter((x) => x.ext === "xml");
    expect(xml.map((x) => x.root).sort()).toEqual(["PARAMETERS", "layout"]);
    expect(xml.every((x) => x.status === "VALID_EXACT" && x.boundary === "BOUNDARY_VERIFIED")).toBe(true);
    expect((carve(u8) as { xml_scan_status?: string }).xml_scan_status).toMatch(/^FAST_SCAN_COMPLETE/);
  });
  it("deep mode reports DEEP_SCAN_COMPLETE and finds no fewer resources", () => {
    const deep = carve(u8, true);
    expect(deep.xml_scan_status).toMatch(/^DEEP_SCAN_COMPLETE/);
    expect(deep.length).toBeGreaterThanOrEqual(res.length);
  });
  it("structural helpers match what the browser reported", () => {
    expect(pngDims(u8.subarray(0, 10))).toBeNull();
    expect(jpegDims(new Uint8Array([0xff, 0xd8, 0xff, 0xe0]))).toBeNull();
    const jpg = new Uint8Array([0xff, 0xd8, 0xff, 0xc0, 0x00, 0x11, 0x08, 0x00, 0x20, 0x00, 0x10, 0x03, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0, 0xff, 0xd9]);
    expect(jpegDims(jpg)).toEqual({ w: 16, h: 32 });
    expect(xmlWellFormed('<a x="1"><b/><c>t</c></a>')).toBe("a");
    expect(xmlWellFormed("<a><b></a>")).toBeNull();
    expect(xmlWellFormed("<a/> trailing")).toBeNull();
    expect(xmlWellFormed('<?xml version="1.0"?><!-- c --><r a="b"/>')).toBe("r");
    expect(fontName(new Uint8Array(20))).toBeNull();
  });
  it("marks duplicates by hash", async () => {
    const a = res.find((x) => x.ext === "png")!;
    const twin: Resource = { ...a, name: "png_dup.png", data: a.data.slice(), offset: 1 };
    const list = [a, twin];
    await validateResources(list);
    expect(list[1].status).toBe("DUPLICATE");
    expect(list[1].dupOf).toBe(a.name);
  });
});

describe("BinaryData mapping is content-based only", () => {
  it("maps the font by its name table and leaves two PNGs UNRESOLVED", async () => {
    const res = carve(u8); await validateResources(res);
    const map = mapBinaryData(res, ["knob_png", "SynthSans_ttf", "bg_png"]);
    const font = map.find((m) => m.binarydata_name === "SynthSans_ttf")!;
    expect(font.carved).toBe("ttf_000.ttf");
    expect(font.mapping_status).toMatch(/^VERIFIED \(font name table/);
    expect(map.filter((m) => /UNRESOLVED/.test(m.mapping_status)).map((m) => m.binarydata_name).sort()).toEqual(["bg_png", "knob_png"]);
    expect(res.filter((x) => x.ext === "png").every((x) => !x.candidate_name)).toBe(true);   // never by declaration order
  });
  it("uses the singleton rule only when exactly one name and one asset remain", async () => {
    const res = carve(u8); await validateResources(res);
    const map = mapBinaryData(res.filter((x) => x.ext === "wav"), ["ir_wav"]);
    expect(map[0].mapping_status).toMatch(/^INFERRED_SINGLETON/);
  });
});

describe("serialized keys are not parameters", () => {
  it("records observed values with representation UNKNOWN and flags indexed keys", () => {
    const rec = serializedKeyRecord({ id: "waveShapers_4_2", values: [0.25], source: "XML embedded in binary", conf: 2 });
    expect(rec.key_kind_candidate).toMatch(/^INTERNAL_EFFECT_PROPERTY/);
    expect(rec.value_representation).toBe("UNKNOWN");
    expect(rec.runtime_parameter_status).toBe("UNVERIFIED");
    expect(rec.legal_range).toBe("UNKNOWN");
    expect(typeInfo({ id: "x", values: [0, 1, 0] }).status).toMatch(/bool\/discrete/);
    expect(typeInfo({ id: "x", values: [0] }).status).toBe("TYPE_UNKNOWN");
  });
});

describe("constants", () => {
  it("finds the planted π, 2π, 44.1 kHz and 1/√2 in .rdata", () => {
    const pe = parsePE(u8);
    const labels = scanConstants(u8, pe.rdata).map((c) => c.label);
    for (const l of ["π", "2π", "44.1 kHz", "1/√2 (Butterworth Q)"]) expect(labels).toContain(l);
  });
});

describe("analyzeBinary / analyzeGroup / bundle", () => {
  it("produces v2 envelopes and the v2 file set", async () => {
    const file = { name: "SynthPlug.vst3", path: "SynthPlug.vst3/Contents/x86_64-win/SynthPlug.vst3", size: u8.length, kind: "PE" as const, bytes: async () => u8 };
    const R = await analyzeGroup([file], [], [], [], [], tick);
    expect(R.classes).toEqual(["SerialScreen", "SynthLookAndFeel", "SynthPlugAudioProcessor", "synth::SynthClipper", "synth::SynthFilter"]);
    expect(Object.keys(R.params).sort()).toEqual(["drive", "oversample", "waveShapers_4_2"]);
    expect(R.params.drive.values).toEqual([0.75, 0.5]);
    expect(R.juce).toBe("7.0.5");
    expect(R.pdbFound).toBe(false);
    const plan = buildBundle(R);
    const paths = plan.entries.map((e) => e.path);
    for (const p of ["00_manifest/input_manifest.json", "00_manifest/recovery_summary.json", "01_evidence/rtti/classes.json", "01_evidence/paths/build_path_evidence.json",
      "01_evidence/resources/index.json", "01_evidence/resources/binarydata_map.json", "01_evidence/strings/all.txt", "01_evidence/binary/dsp_constants.json",
      "03_architecture/serialized_keys.json", "03_architecture/classes.json", "03_architecture/parameters.json", "03_architecture/identity.json",
      "04_reconstruction/CMakeLists.txt", "04_reconstruction/Source/Active/PluginProcessor.cpp", "07_agent_handoff/reconstruction_index.json",
      "07_agent_handoff/HANDOFF.md", "07_agent_handoff/UNRECOVERABLE.md", "07_agent_handoff/agent_prompt.md", "02_recovered_assets/fonts/ttf_000.ttf"]) {
      expect(paths).toContain(p);
    }
    const env = withSchema("01_evidence/rtti/classes.json", []);
    expect(env.schema).toBe("recovery.classes");
    expect(env.schema_version).toBe(2);
    expect(withSchema("corpus/performance.json", {}).schema).toBe("recovery.corpus.performance");
    const cmake = (plan.entries.find((e) => e.path === "04_reconstruction/CMakeLists.txt") as { text: string }).text;
    expect(cmake).toContain("FATAL_ERROR");           // FIDELITY fails loudly without identity
    expect(cmake).toContain("RECOVERY_SURROGATE_BUILD");
    expect(cmake).not.toContain("Source/RecoveredScaffolds/DSP");  // scaffolds never in target_sources
    const proc = (plan.entries.find((e) => e.path === "04_reconstruction/Source/Active/PluginProcessor.cpp") as { text: string }).text;
    expect(proc).toContain("GENERATED_PLACEHOLDER_RANGE");
    expect(proc).not.toContain("NormalisableRange<float> (0.0f, 0.75f");   // observed values never become ranges
  });
  it("runStatic exposes instrumentation, completeness and deep-scan trigger data", async () => {
    const file = { name: "SynthPlug.vst3", path: "SynthPlug.vst3", size: u8.length, kind: "PE" as const, bytes: async () => u8 };
    const { result } = await runStatic({ key: "SynthPlug.vst3", bins: [file], presets: [], sources: [], objs: [], pdbs: [] }, tick, {});
    expect(result.instrumentation.completeness).toBe("FAST_SCAN_COMPLETE");
    expect(result.instrumentation.bytes_processed).toBe(u8.length);
    expect(Object.keys(result.instrumentation.stages_ms)).toEqual(["pe_parse", "string_scan", "classify_rtti_paths_xml", "resource_carve", "constant_scan", "resource_validate"]);
    expect(result.triggers.binarydata_names_by_ext).toEqual({ png: 1, ttf: 1 });   // "bg_png" is too short for the v2 name rule
    expect(result.triggers.keys_in_documents).toEqual(["drive", "oversample", "waveShapers_4_2"]);
  });
  it("analyzeBinary tolerates a non-PE blob", async () => {
    const r = await analyzeBinary(new Uint8Array(4096), "x.bin", "ELF", tick);
    expect(r.classes).toEqual([]);
    expect(r.resources.length).toBe(0);
  });
});
