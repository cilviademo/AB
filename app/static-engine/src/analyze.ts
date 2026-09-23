import { append, now, sha256Hex, uniq } from "./bytes";
import { carve } from "./carve";
import { classifyClass, classifyPath, demangleItaniumType, demangleMsvcType } from "./classify";
import { scanConstants } from "./constants";
import { findRSDS, parsePE } from "./pe";
import { extractStateXml } from "./statexml";
import { extractStrings } from "./strings";
import { mapBinaryData } from "./binarydata";
import { validateResources } from "./validate";
import { SCHEMA_VERSION, TOOL_VERSION, type AnalyzeOptions, type BinaryKind, type BinaryResult, type GroupResult, type InputFile, type Tick } from "./types";

/** v2 `withSchema` — verbatim: the `recovery.*` / v2 envelope. */
export function withSchema(path: string, obj: unknown) { const name = path.split('/').pop()!.replace(/\.json$/, ''); const schema = 'recovery.' + (path.includes('corpus/') ? 'corpus.' : '') + name; return { schema, schema_version: SCHEMA_VERSION, tool: TOOL_VERSION, generated: new Date().toISOString(), data: obj }; }
export function safeFolder(s: string): string { return s.replace(/\.(vst3|vst|dll|dylib|component)$/i, '').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60) || 'plugin'; }

/** v2 `analyzeBinary` — verbatim (plus `deep` passed to carve). */
export async function analyzeBinary(u8: Uint8Array, name: string, kind: BinaryKind, tick: Tick, opts: AnalyzeOptions = {}): Promise<BinaryResult> {
  const r: BinaryResult = { name, kind, size: u8.length, pe: {}, strings: [], classes: [], tree: [], paramIds: [], resources: [] as never, consts: [], juce: null, pdb: null, buckets: {} };
  const stages: Record<string, number> = {}; let t0 = now(); const lap = (name: string) => { stages[name] = Math.round(now() - t0); t0 = now(); };
  if (kind === 'PE') r.pe = parsePE(u8); lap('pe_parse');
  await tick('Extracting strings…');
  r.strings = extractStrings(u8, 5); lap('string_scan');
  await tick(`Classifying ${r.strings.length.toLocaleString()} strings…`);
  const T = r.strings;
  r.juce = (T.map(s => (s.match(/JUCE v?(\d+\.\d+\.\d+)/) || [])[1]).find(Boolean)) || null;
  r.pdb = findRSDS(u8);
  r.pathsAll = uniq(T.filter(s => /^[A-Za-z]:[\\/]|^[\\/]?[\w.-]+([\\/][\w .-]+)+\.(cpp|h|hpp|mm|c|jucer|cmake|txt)$/i.test(s) || /[\\/](Source|JuceLibraryCode|modules|src|vst3sdk|pluginterfaces)[\\/][\w .-]+/i.test(s) || /\b(VST 3\.\d|JUCE v?\d)/.test(s))).map(s => ({ path: s, kind: classifyPath(s) }));
  r.tree = r.pathsAll.filter(x => x.kind === 'PROJECT_SOURCE').map(x => x.path);
  // RTTI class names
  const msvc = T.filter(s => /^\.\?A[UV][A-Za-z_][\w@?$]*@@$/.test(s)).map(demangleMsvcType);
  const itan = T.filter(s => /^_ZTS(N(\d+[A-Za-z_]\w*)+E|\d+[A-Za-z_]\w*)$/.test(s)).map(demangleItaniumType).filter(Boolean) as string[];
  r.classesAll = uniq(msvc.concat(itan)).map(c => ({ name: c, kind: classifyClass(c) }));
  r.classes = r.classesAll.filter(x => x.kind === 'PLUGIN_OWNED').map(x => x.name);
  const test = (rx: RegExp) => uniq(T.filter(s => rx.test(s)));
  r.buckets = {
    'Preset / state XML': test(/^<|\/>$|ValueTree|PARAMETERS|preset/i),
    'DSP terms': test(/oversampl|adaa|tanh|limiter|lookahead|sidechain|crossover|biquad|svf|lufs|true.?peak|saturat|glue|shelf|hpf|lpf|drive|punch|warmth|boom|texture|spark|shine/i),
    'UI terms': test(/knob|meter|panel|drawer|halo|thermal|font|colour|theme|page|LookAndFeel|Slider|Button|Label|Tooltip/i),
    'Licence / security': test(/licen[cs]|serial|activat|trial|expir|hwid|machine.?id|hmac|sha-?256|\baes\b|\brsa\b|obfusc|keygen|ilok|pace\b|unlock|register|demo\b/i).filter(s => !/^\.\?A|oversampl/i.test(s)),
    'Build / toolchain': test(/MSVC|Visual Studio|clang|GCC|cmake|Projucer|JUCE_|VST3|Steinberg|AudioUnit|CLAP|_MSC_VER|mingw/i),
    'Plugin codes': test(/^JucePlugin_/),
  };
  // parameter IDs: JUCE stores id and display name as adjacent literals; keep camelCase/snake identifiers that are not C++ keywords or juce symbols
  const bad = /^(true|false|null|std|juce|const|static|void|float|double|int|char|bool|size|data|name|value|type|text|state|error|input|output|Input|Output|main|init|reset|update|render|paint|resized|operator|nullptr|volatile|short|wchar_t|char8_t|char16_t|char32_t|kernel32|advapi32|ntdll|user32)$/;
  const libm = /^(sqrt|log|log10|log2|exp|pow|sin|cos|tan|atan|atan2|floor|ceil|ldexp|frexp|fmod|fabs|tanh|sinh|cosh)f?$/;
  const looksMangled = (s: string) => /^[a-z]{1,2}[A-Z0-9][A-Za-z0-9]{2,6}$/.test(s) && /\d/.test(s) || /^(f{4,}|g?f{3,}[A-Z]?)$/.test(s) || /^[a-z]{2}[A-Z]\d/.test(s);
  const hasJuce = !!r.juce || T.some(s => /^JucePlugin_|juce::|AudioProcessorValueTreeState/.test(s));
  void bad; void libm; void looksMangled;
  const embedded = extractStateXml(u8, true);
  r.paramIds = uniq(embedded.params.map(x => x.id));
  r.embeddedParams = embedded.params; r.embeddedXml = embedded.xml;
  r.paramNote = r.paramIds.length ? '' : (hasJuce ? 'JUCE build, but no parameter XML is embedded. Drop a .vstpreset/.fxp/DAW session, or run vst_recover.py params for the exact list.' : 'No JUCE parameter table in this binary — parameters are host-side. Drop presets/sessions to recover IDs, or run vst_recover.py params.');
  r.hasJuce = hasJuce;
  r.candidateStrings = uniq(T.filter(s => /^[a-z][A-Za-z0-9_]{2,28}$/.test(s) && !bad.test(s) && !libm.test(s) && !looksMangled(s))).slice(0, 5000);
  r.binaryDataNames = uniq(T.filter(s => /^[A-Za-z][\w-]{2,40}_(png|jpg|jpeg|svg|ttf|otf|xml|json|wav|aiff|txt)$/.test(s) || /^[A-Za-z][\w]{2,30}(Knob|knob|_knob|Button|button|_bg|Background|background)$/.test(s)));
  lap('classify_rtti_paths_xml');
  await tick('Carving artwork and fonts…');
  r.resources = carve(u8, !!opts.deep); r.xmlScanStatus = r.resources.xml_scan_status; lap('resource_carve');
  await tick('Scanning DSP constants…');
  r.consts = scanConstants(u8, r.pe.rdata); lap('constant_scan');
  r.stages = stages;
  return r;
}

/** v2 `analyzeGroup` — verbatim, over `InputFile` providers instead of `File` objects. */
export async function analyzeGroup(bins: InputFile[], presets: InputFile[], sources: InputFile[], objs: InputFile[], pdbs: InputFile[], tick: Tick, opts: AnalyzeOptions = {}): Promise<GroupResult> {
  const R: GroupResult = { bins: [], classes: [], params: {}, tree: [], juce: null, pdb: null, pdbFound: false, resources: [], consts: [], strings: [], buckets: {}, rescued: [], presetFiles: [], inputs: [] };
  bins = bins.slice().sort((a, b) => b.size - a.size);
  for (const b of bins) {
    await tick(`reading ${b.name} (${(b.size/1048576).toFixed(1)} MB)`);
    const u8 = await b.bytes();
    let sha: string | null = null; try { sha = await sha256Hex(u8); } catch (e) { /* no digest available */ }
    R.inputs.push({ path: b.path, size: b.size, sha256: sha });
    const a = await analyzeBinary(u8, b.name, b.kind || 'PE', tick, opts); a.sha256 = sha;
    R.bins.push(a);
    R.classes = R.classes.concat(a.classes); R.classesAll = (R.classesAll || []).concat(a.classesAll || []); R.pathsAll = (R.pathsAll || []).concat(a.pathsAll || []);
    R.tree = R.tree.concat(a.tree); R.resources = R.resources.concat(a.resources.map(x => ({ ...x, from: a.name }))); R.consts = R.consts.concat(a.consts); R.strings = append(R.strings, a.strings);
    R.candidateStrings = uniq((R.candidateStrings || []).concat(a.candidateStrings || []));
    R.juce = R.juce || a.juce; R.pdb = R.pdb || a.pdb;
    for (const { id, value } of (a.embeddedParams || [])) { const e = R.params[id] || { id, values: [] }; e.values = e.values || []; e.values.push(value); e.source = 'XML embedded in binary'; e.conf = 2; R.params[id] = e; }
    if (a.embeddedXml) R.presetFiles.push({ name: a.name + ' (embedded)', count: (a.embeddedParams || []).length, xml: a.embeddedXml });
    for (const [k, v] of Object.entries(a.buckets)) R.buckets[k] = uniq((R.buckets[k] || []).concat(v));
  }
  R.classes = uniq(R.classes).sort(); R.tree = uniq(R.tree).sort();
  R.pdbFound = pdbs.some(p => R.pdb && p.name.toLowerCase() === R.pdb.split(/[\\/]/).pop()!.toLowerCase());
  for (const p of presets) {
    const u8 = await p.bytes();
    const found = extractStateXml(u8);
    if (found.params.length) { R.presetFiles.push({ name: p.name, count: found.params.length, xml: found.xml });
      for (const { id, value } of found.params) { const e = R.params[id] || { id, values: [] }; e.values = e.values || []; e.values.push(value); e.source = 'preset/session XML'; e.conf = 3; R.params[id] = e; } }
    R.inputs.push({ path: p.path, size: p.size });
  }
  for (const s of sources) R.rescued.push({ path: s.path, data: await s.bytes() });
  for (const o of objs) { const u8 = await o.bytes(); R.tree = R.tree.concat(extractStrings(u8, 8).filter(x => /\.(cpp|h|hpp|mm)$/i.test(x))); }
  R.tree = uniq(R.tree).sort();
  await tick('validating resources');
  { const t0 = now(); await validateResources(R.resources); R.stageValidate = Math.round(now() - t0); }
  R.binaryDataMap = mapBinaryData(R.resources, uniq(R.bins.flatMap(x => x.binaryDataNames || [])));
  return R;
}
