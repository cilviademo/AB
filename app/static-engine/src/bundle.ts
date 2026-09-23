import { uniq } from "./bytes";
import { classFiles, cmakeFor, identity, ident, processorFiles, serializedKeyRecord, type ClassFiles } from "./generate";
import { withSchema, safeFolder } from "./analyze";
import { corpusReport, type Corpus } from "./corpus";
import type { GroupResult } from "./types";

/**
 * The v2 bundle, as a plan instead of a zip: every path the browser's
 * "Download repo zip" wrote, with the same contents. The engine writes the
 * plan into the project folder and the object store (SPEC §6.1: the v2
 * contracts are preserved byte-for-byte in shape; `recovery.*` / v2).
 *
 * Differences from the browser writer, all recorded in DECISIONS D-012:
 * `recovery_kit/` is not emitted (AB's own stages replace the interim kit;
 * the frozen kit lives in handoff/kit) and the archive root prefix is not
 * part of the plan (the engine decides folder names).
 */

export type PlanEntry =
  | { path: string; json: unknown; schema: string }
  | { path: string; text: string }
  | { path: string; bytes: Uint8Array; sha256?: string | null; carved?: boolean };

export interface BundlePlan {
  nm: string;
  entries: PlanEntry[];
  summary: Record<string, unknown>;
}

const J = (path: string, obj: unknown): PlanEntry => ({ path, json: withSchema(path, obj), schema: withSchema(path, obj).schema });

export function buildBundle(r: GroupResult, generatedAt: string = new Date().toISOString()): BundlePlan {
  const b = r.bins[0] || ({ name: 'unknown', kind: '?', size: 0, pe: {} } as unknown as GroupResult['bins'][0]);
  const nm = ident(b.name);
  const classes: ClassFiles[] = r.classes.map((c, i) => classFiles(c, i, b.name));
  const kinds: Record<string, number> = {}; (r.classesAll || []).forEach(x => kinds[x.kind] = (kinds[x.kind] || 0) + 1);
  const pkinds: Record<string, number> = {}; (r.pathsAll || []).forEach(x => pkinds[x.kind] = (pkinds[x.kind] || 0) + 1);
  const rstat: Record<string, number> = {}; r.resources.forEach(x => rstat[x.status || 'UNKNOWN'] = (rstat[x.status || 'UNKNOWN'] || 0) + 1);
  const validRes = r.resources.filter(x => x.status === 'VALID_EXACT');
  const usableRes = r.resources.filter(x => x.status === 'VALID_EXACT' || x.status === 'PARSER_VALID');
  const proc = processorFiles(r, nm);
  const P = Object.values(r.params); const pcount = P.length, withVals = P.filter(x => x.values && x.values.length).length;
  const idn = identity(r, b);
  const E: PlanEntry[] = [];

  // 00 manifest
  E.push(J('00_manifest/input_manifest.json', { inputs: r.inputs, mode: 'OWNER_RECOVERY (static stage)', tool: 'Static Recovery v2 (AB static engine port)', generated: generatedAt }));
  E.push(J('00_manifest/recovery_summary.json', { binary: b.name, format: b.pe.format, arch: b.pe.machine, juce: r.juce || (b.hasJuce ? 'unversioned' : null), classes: kinds, parameters: { verified: pcount, withValues: withVals, candidateStrings: (r.candidateStrings || []).length }, resources: rstat, paths: pkinds, pdb: r.pdb, pdbFound: r.pdbFound }));
  // 01 evidence
  for (const bb of r.bins) E.push(J('01_evidence/binary/' + bb.name + '.json', { kind: bb.kind, size: bb.size, sha256: bb.sha256, pe: bb.pe, juce: bb.juce, hasJuce: bb.hasJuce, pdb: bb.pdb, xml_scan_status: bb.xmlScanStatus, stages_ms: bb.stages }));
  E.push(J('01_evidence/rtti/classes.json', (r.classesAll || []).map(x => { const c = classes.find(k => k.cls === x.name); return { recovered_name: x.name, kind: x.kind === 'PLUGIN_OWNED' ? 'PLUGIN_OWNED_CANDIDATE' : x.kind, library: x.kind === 'THIRD_PARTY' ? x.name.split('::')[0] : undefined, role: c ? c.role : null, role_status: c && c.role !== 'UNKNOWN' ? 'CANDIDATE' : 'UNKNOWN', role_basis: c ? c.roleBasis : [], inferred_base: c ? c.base || null : null, base_status: c && c.base ? 'INFERRED' : 'UNKNOWN', safe_name: c ? c.safe : null, name_status: 'VERIFIED_RTTI_NAME', source: 'RTTI type descriptor string' }; })));
  E.push(J('01_evidence/paths/build_path_evidence.json', r.pathsAll || []));
  E.push({ path: '01_evidence/strings/all.txt', text: r.strings.join('\n') });
  E.push(J('01_evidence/strings/candidate_strings.json', r.candidateStrings || []));
  E.push(J('01_evidence/strings/classified.json', r.buckets));
  E.push(J('01_evidence/binary/dsp_constants.json', r.consts));
  E.push(J('01_evidence/resources/index.json', r.resources.map(x => ({ name: x.name, ext: x.ext, status: x.status, parser: x.parser, boundary: x.boundary, semantics: x.semantics || (x.status === 'VALID_EXACT' ? 'BOUNDARY_VALID_SEMANTICS_UNKNOWN' : undefined), offset: x.offset, size: x.data.length, sha256: x.sha256, from: x.from, dims: x.dims, root: x.root, dupOf: x.dupOf, candidate_name: x.candidate_name, mapping_status: x.mapping_status, extraction: x.boundary === 'BOUNDARY_VERIFIED' ? 'structural parse' : 'signature carve (heuristic end)' }))));
  E.push(J('01_evidence/resources/binarydata_map.json', r.binaryDataMap || []));
  r.resources.filter(x => x.status !== 'VALID_EXACT').forEach(x => E.push({ path: '01_evidence/resources/' + x.name, bytes: x.data, sha256: x.sha256, carved: true }));
  r.presetFiles.forEach((p, i) => E.push({ path: `01_evidence/presets/preset_${i}_${p.name.replace(/[^\w.-]/g, '_')}.xml`, text: p.xml }));
  // 02 assets
  validRes.forEach(x => E.push({ path: '02_recovered_assets/' + (x.ext === 'ttf' || x.ext === 'otf' ? 'fonts/' : x.ext === 'xml' ? 'xml/' : x.ext === 'wav' ? 'impulses/' : 'images/') + x.name, bytes: x.data, sha256: x.sha256, carved: true }));
  // 03 architecture
  E.push(J('03_architecture/classes.json', classes.map(c => ({ name: c.cls, safe_name: c.safe, role: c.role, role_status: c.role === 'UNKNOWN' ? 'UNKNOWN' : 'CANDIDATE', role_basis: c.roleBasis, inferred_base: c.base || null, file: '04_reconstruction/Source/' + c.dir + c.safe + '.cpp', status: 'SCAFFOLD_ONLY', compiled: false }))));
  E.push(J('03_architecture/serialized_keys.json', P.map(p => serializedKeyRecord(p))));
  E.push(J('03_architecture/parameters.json', { note: 'EXPORTED_VST_PARAMETER records are produced only by the standalone runtime host (IEditController). This static stage contributes serialized keys; see serialized_keys.json.', runtime_parameters: [], state_runtime_map: [] }));
  E.push(J('03_architecture/identity.json', idn));
  // 04 reconstruction
  E.push({ path: '04_reconstruction/CMakeLists.txt', text: cmakeFor(r, nm, classes, validRes, b) });
  E.push({ path: '04_reconstruction/.gitignore', text: 'build/\nrecovery_kit/tools/\n*.pdb\n' });
  E.push({ path: '04_reconstruction/Source/Active/PluginProcessor.h', text: proc.h }); E.push({ path: '04_reconstruction/Source/Active/PluginProcessor.cpp', text: proc.cpp });
  E.push({ path: '04_reconstruction/Source/Active/PluginEditor.h', text: proc.eh }); E.push({ path: '04_reconstruction/Source/Active/PluginEditor.cpp', text: proc.ec });
  E.push({ path: '04_reconstruction/Source/RecoveredScaffolds/README.md', text: '# RecoveredScaffolds\nGenerated from VERIFIED RTTI names. NOT compiled. Promote a class to Source/Active/ (and add it to CMake) only after it is BEHAVIOR_MATCHED against the original.\n' });
  classes.forEach(c => { E.push({ path: '04_reconstruction/Source/' + c.dir + c.safe + '.h', text: c.h }); E.push({ path: '04_reconstruction/Source/' + c.dir + c.safe + '.cpp', text: c.cpp }); });
  validRes.forEach(x => E.push({ path: '04_reconstruction/Resources/' + x.name, bytes: x.data, sha256: x.sha256, carved: true }));
  usableRes.filter(x => x.status === 'PARSER_VALID').forEach(x => E.push({ path: '01_evidence/resources/parser_valid_unbounded/' + x.name, bytes: x.data, sha256: x.sha256, carved: true }));
  for (const s of r.rescued) E.push({ path: '04_reconstruction/Source/rescued/' + s.path.replace(/[<>:"|?*]/g, '_'), bytes: s.data });
  // 05/06 placeholders
  E.push({ path: '05_reference_behavior/README.md', text: '# Reference behaviour\nPopulated by the desktop stage (Phase 2 probes: impulse, DC, amplitude ramp, sine, log sweep, noise, two-tone at 44.1/48/96k).\n' });
  E.push({ path: '06_validation/README.md', text: '# Validation\nPopulated by the desktop stage (Phase 4: build, pluginval, original-vs-rebuild differential).\n' });
  // 07 handoff
  E.push(J('07_agent_handoff/reconstruction_index.json', [
    { symbol: nm + 'AudioProcessor', file: '04_reconstruction/Source/Active/PluginProcessor.cpp', status: 'SCAFFOLD_ONLY', compiled: true, evidence: ['JUCE_TEMPLATE'], parameters: P.map(p => p.id), placeholders: ['acceptsMidi', 'producesMidi', 'getTailLengthSeconds', 'getNumPrograms', 'hasEditor', 'bus layout', 'state serialization', 'all parameter ranges/defaults'], todos: ['Phase 2: replace GENERATED_BUILD_PLACEHOLDER values and GENERATED_PLACEHOLDER_RANGE from vst3host', 'Phase 2: state-differential test before trusting APVTS serialization', 'Phase 3: port processBlock from decompiler evidence'] },
    ...classes.map(c => ({ symbol: c.cls, safe_name: c.safe, file: '04_reconstruction/Source/' + c.dir + c.safe + '.cpp', status: 'SCAFFOLD_ONLY', compiled: false, role: c.role, role_status: c.role === 'UNKNOWN' ? 'UNKNOWN' : 'CANDIDATE', role_basis: c.roleBasis, base: c.base || null, base_status: c.base ? 'INFERRED' : 'UNKNOWN', evidence: ['RTTI_TYPE_DESCRIPTOR'], binary_addresses: [], promotion: 'SCAFFOLD_ONLY → STATIC_RECONSTRUCTED → BEHAVIOR_MATCHED → Source/Active', todos: ['confirm base/role from Ghidra RTTI + callgraph', 'recover members', 'port method bodies', 'behavioural validation'] })),
  ]));
  E.push({ path: '07_agent_handoff/UNRECOVERABLE.md', text: `# Unrecoverable from a stripped optimised binary\n\nRecreate these; do not keep searching for them.\n\n- original source comments\n- original whitespace/formatting\n- original local variable names${r.pdbFound ? '' : '\n- original function/member names (no .pdb)'}\n- dead source removed by the compiler/linker\n- excluded #if branches and unused files\n- template abstractions optimised away\n- Git history\n- original CMake/Projucer formatting\n` });
  E.push({ path: '07_agent_handoff/HANDOFF.md', text: `# Handoff: ${nm}\n\n**Binary:** ${b.name} (${b.pe.format || '?'}, ${b.pe.machine || '?'}, ${(b.size/1048576).toFixed(1)} MB) · JUCE ${r.juce || (b.hasJuce ? 'yes' : 'no')} · built ${b.pe.timestamp || '?'}\n\n## Verified\n- ${pcount} parameter IDs (XML/presets)\n- ${kinds.PLUGIN_OWNED || 0} plugin-owned class names (RTTI)\n- ${validRes.length} valid embedded resources\n- ${r.tree.length} project-source paths\n\n## Inferred\n- class base classes and DSP roles (from names)\n- parameter ranges (${withVals} from observed values)\n\n## Generated / scaffold-only\n- every method body in 04_reconstruction/Source\n- PluginProcessor/Editor shells\n\n## Unverified\n- plugin identity (vendor, codes, FUID) — CMake fails until supplied\n\n## Next best tasks (in order)\n1. Phase 2: run vst3host introspection → replace parameters.json and identity.json with VERIFIED_RUNTIME values.\n2. Phase 3: Ghidra RTTI + seeded callgraph → fill binary_addresses in reconstruction_index.json.\n3. Phase 4: pick the one module with strongest evidence${classes.filter(c => c.role === 'WAVESHAPER' || c.role === 'FILTER' || c.role === 'OVERSAMPLER').slice(0, 3).map(c => ' (' + c.cls + ')').join('') || ''}; decompile → behavioural fit → concise C++ → build → differential test.\n` });
  E.push({ path: '07_agent_handoff/agent_prompt.md', text: `You are continuing an evidence-first reconstruction of ${nm} from its compiled binary.\n\nRules:\n- Read 07_agent_handoff/reconstruction_index.json first; work TODOs in confidence order.\n- Treat 01_evidence/ as immutable. Never edit it.\n- Never promote a CANDIDATE or INFERRED item to VERIFIED without new evidence (runtime introspection, RTTI export, behavioural test).\n- Any algorithmic operation not present in static or behavioural evidence must be marked INFERRED in code comments.\n- Keep 04_reconstruction buildable at every commit. Do not invent identity codes; leave the CMake FATAL_ERROR until real values exist.\n- After changing any DSP, run the differential harness (06_validation) and record the result in reconstruction_index.json.\n- Licensing code is PROTECTED_SUBSYSTEM: document its architecture, do not reimplement or bypass it.\n\nUnrecoverable items are listed in UNRECOVERABLE.md — recreate them, do not search for them.\n` });
  E.push({ path: 'README_RECOVERY.md', text: `# ${nm} — recovery bundle (STATIC RECOVERY v2)\n\nLayout: 00_manifest · 01_evidence (immutable) · 02_recovered_assets · 03_architecture · 04_reconstruction (Git-ready skeleton) · 05/06 (desktop stages) · 07_agent_handoff.\n\nStart with 07_agent_handoff/HANDOFF.md. The runtime, decompiler, behavioural and build stages are run by AB (Artifact Bench); their outputs land beside these files.\n` });

  const summary = {
    binary: b.name, format: b.pe.format, arch: b.pe.machine, juce: r.juce || (b.hasJuce ? 'unversioned' : null),
    classes: kinds, plugin_owned: r.classes.length, parameters: { verified: pcount, withValues: withVals, candidateStrings: (r.candidateStrings || []).length },
    resources: rstat, valid_resources: validRes.length, paths: pkinds, pdb: r.pdb, pdbFound: r.pdbFound,
    binarydata: { verified: (r.binaryDataMap || []).filter(m => /^VERIFIED/.test(m.mapping_status)).length, inferred: (r.binaryDataMap || []).filter(m => /^INFERRED/.test(m.mapping_status)).length, unresolved: (r.binaryDataMap || []).filter(m => /UNRESOLVED/.test(m.mapping_status)).length },
    xml_scan_status: b.xmlScanStatus, consts: r.consts.length, strings: r.stringsCount || r.strings.length,
  };
  return { nm, entries: E, summary };
}

/** v2 corpus zip contents (cross-plugin JSON only; per-plugin bundles come from `buildBundle`). */
export function buildCorpusBundle(C: Corpus, generatedAt: string = new Date().toISOString()): PlanEntry[] {
  const report = corpusReport(C);
  const E: PlanEntry[] = [];
  E.push({ path: 'corpus/CORPUS_REPORT.md', text: report });
  E.push(J('corpus/corpus_manifest.json', { generated: generatedAt, plugins: C.results.map(r => ({ key: r.key, folder: 'plugins/' + safeFolder(r.key!), inputs: r.inputs })), shared_threshold: C.sharedThreshold, rule: 'evidence never merged across plugins; recurrence only adjusts classification confidence' }));
  E.push(J('corpus/shared_class_names.json', C.classList.filter(c => c.count > 1)));
  E.push(J('corpus/plugin_specific_class_names.json', C.classList.filter(c => c.corpus_class === 'PLUGIN_SPECIFIC_NAME' && c.kind === 'PLUGIN_OWNED')));
  E.push(J('corpus/shared_resources.json', C.resList.filter(r => r.count > 1)));
  E.push(J('corpus/shared_binary_signatures.json', { note: 'name/hash-level evidence only; function/vtable fingerprints are a standalone-stage output', builds: C.builds, class_name_set_similarity: C.pairs, binarydata_names: C.bdNames, xml_roots: C.xmlRoots, dsp_constant_candidates: C.consts, serialized_key_names: C.params }));
  E.push(J('corpus/classification_errors.json', C.errors));
  E.push(J('corpus/performance.json', C.performance));
  for (const r of C.results) {
    const b = r.bins[0]; const P = Object.values(r.params);
    const kinds: Record<string, number> = {}; (r.classesAll || []).forEach(x => kinds[x.kind] = (kinds[x.kind] || 0) + 1);
    E.push(J('plugins/' + safeFolder(r.key!) + '/00_manifest/recovery_summary.json', { key: r.key, binary: b.name, sha256: b.sha256, format: b.pe.format, arch: b.pe.machine, size: b.size, juce: r.juce || (b.hasJuce ? 'unversioned' : null), classes: kinds, parameters: P.length, resources: r.resources.length, valid_resources: r.resources.filter(x => x.status === 'VALID_EXACT').length, pdb: r.pdb, scan_ms: r.ms }));
  }
  return E;
}

export { uniq };
