import { uniq } from "./bytes";
import { roleFor } from "./generate";
import { SCHEMA_VERSION, type GroupResult } from "./types";

/** v2 corpus layer — verbatim (cross-plugin; never merges evidence into a single plugin's package). */

export interface CorpusHost { user_agent: string; hardware_threads: number | null; device_memory_gb: number | null }

export function buildCorpus(results: GroupResult[], host: CorpusHost = { user_agent: 'ab-static-engine', hardware_threads: null, device_memory_gb: null }) {
  const N = results.length;
  const jaccard = (A: string[], B: string[]) => { const a = new Set(A), b = new Set(B); let i = 0; for (const x of a) if (b.has(x)) i++; const u = a.size + b.size - i; return u ? i / u : 0; };
  const classes: Record<string, { name: string; kind: string; plugins: string[]; roles: Set<string> }> = {};
  for (const r of results) for (const x of (r.classesAll || [])) { const c = classes[x.name] || (classes[x.name] = { name: x.name, kind: x.kind, plugins: [], roles: new Set() }); if (!c.plugins.includes(r.key!)) c.plugins.push(r.key!); c.roles.add(roleFor(x.name)); }
  const sharedThreshold = Math.max(3, Math.ceil(N * 0.3));
  const classList = Object.values(classes).map(c => ({ name: c.name, kind: c.kind, plugins: c.plugins, count: c.plugins.length, role_candidate: [...c.roles][0],
    corpus_class: c.plugins.length === 1 ? 'PLUGIN_SPECIFIC_NAME' : c.plugins.length >= sharedThreshold ? 'SHARED_SYMBOL_FAMILY' : 'RECURRING_NAME',
    implementation_status: 'SHARED_NAME (implementation identity UNVERIFIED — needs function/vtable fingerprints in the standalone stage)',
    note: c.kind === 'PLUGIN_OWNED' && c.plugins.length >= sharedThreshold ? 'name recurs across plugins: likely shared internal code family; do not treat as plugin-specific DSP and do not assume identical machine code' : '' }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const resources: Record<string, { sha256: string; ext: string; size: number; status?: string; dims: string; plugins: string[]; names: string[] }> = {};
  for (const r of results) for (const x of r.resources) { if (!x.sha256) continue; const e = resources[x.sha256] || (resources[x.sha256] = { sha256: x.sha256, ext: x.ext, size: x.data.length, status: x.status, dims: x.dims || x.root || '', plugins: [], names: [] }); if (!e.plugins.includes(r.key!)) e.plugins.push(r.key!); if (x.candidate_name && !e.names.includes(x.candidate_name)) e.names.push(x.candidate_name); }
  const resList = Object.values(resources).map(e => ({ ...e, count: e.plugins.length })).sort((a, b) => b.count - a.count || b.size - a.size);
  const bdNames: Record<string, string[]> = {};
  for (const r of results) for (const n of uniq(r.bins.flatMap(x => x.binaryDataNames || []))) (bdNames[n] = bdNames[n] || []).push(r.key!);
  const params: Record<string, string[]> = {};
  for (const r of results) for (const id of Object.keys(r.params)) (params[id] = params[id] || []).push(r.key!);
  const consts: Record<string, { label: string; total: number; plugins: string[] }> = {};
  for (const r of results) for (const c of r.consts) { const e = consts[c.label] || (consts[c.label] = { label: c.label, total: 0, plugins: [] }); e.total += c.count; if (!e.plugins.includes(r.key!)) e.plugins.push(r.key!); }
  const xmlRoots: Record<string, string[]> = {};
  for (const r of results) for (const x of r.resources) if (x.ext === 'xml' && x.root) (xmlRoots[x.root] = xmlRoots[x.root] || []).push(r.key!);
  const builds = results.map(r => { const b = r.bins[0]; return { plugin: r.key, sha256: b.sha256, size: b.size, format: b.pe.format, arch: b.pe.machine, linker: b.pe.linker, built: b.pe.timestamp, sections: b.pe.sectionNames, juce: r.juce || (b.hasJuce ? 'unversioned' : null), pdb: !!r.pdb, exports: (b.pe.exports || []).slice(0, 6) }; });
  const ownedSets = results.map(r => ({ key: r.key!, set: (r.classesAll || []).filter(x => x.kind === 'PLUGIN_OWNED').map(x => x.name) }));
  const pairs: { a: string; b: string; class_name_set_jaccard: number }[] = [];
  for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) pairs.push({ a: ownedSets[i].key, b: ownedSets[j].key, class_name_set_jaccard: +jaccard(ownedSets[i].set, ownedSets[j].set).toFixed(3) });
  pairs.sort((x, y) => y.class_name_set_jaccard - x.class_name_set_jaccard);
  const errors: { type: string; item: string; in_plugins?: number; value?: string | number; suggestion: string }[] = [];
  for (const c of classList) if (c.kind === 'PLUGIN_OWNED' && c.count >= sharedThreshold) errors.push({ type: 'OWNERSHIP', item: c.name, in_plugins: c.count, suggestion: 'reclassify SHARED_INTERNAL_LIBRARY (recurs in ' + c.count + '/' + N + ')' });
  for (const c of classList) if (c.kind === 'PLUGIN_OWNED' && /^[a-z]{2,8}$/.test(c.name)) errors.push({ type: 'SUSPICIOUS_NAME', item: c.name, in_plugins: c.count, suggestion: 'short lowercase RTTI name; verify it is a real class' });
  for (const r of results) { const unk = (r.classesAll || []).filter(x => x.kind === 'PLUGIN_OWNED' && roleFor(x.name) === 'UNKNOWN').length, own = (r.classesAll || []).filter(x => x.kind === 'PLUGIN_OWNED').length; if (own) errors.push({ type: 'ROLE_COVERAGE', item: r.key!, value: `${unk}/${own} owned classes have UNKNOWN role`, suggestion: 'role classifier is name-only; callgraph needed' }); }
  for (const r of results) { const bad = r.resources.filter(x => x.status === 'INVALID' || x.status === 'CARVED_PARTIAL').length; if (bad) errors.push({ type: 'RESOURCE_BOUNDARY', item: r.key!, value: `${bad} invalid/partial carves`, suggestion: 'heuristic-ended signatures (jpg/svg/xml windows)' }); }
  for (const r of results) { const un = (r.binaryDataMap || []).filter(m => /UNRESOLVED/.test(m.mapping_status)).length; if (un) errors.push({ type: 'BINARYDATA_UNRESOLVED', item: r.key!, value: un, suggestion: 'Phase 3 getNamedResource decompile' }); }
  for (const r of results) if (!Object.keys(r.params).length) errors.push({ type: 'PARAMS_NONE', item: r.key!, suggestion: 'no embedded preset XML; needs presets/sessions or Phase 2 host' });
  const stageNames = ['pe_parse', 'string_scan', 'classify_rtti_paths_xml', 'resource_carve', 'constant_scan', 'resource_validate'];
  const perPlugin = results.map(r => ({ plugin: r.key!, size_mb: +(r.bins[0].size/1048576).toFixed(1), ms: r.ms!, mb_per_s: +((r.bins[0].size/1048576) / Math.max(0.001, r.ms!/1000)).toFixed(2), strings: r.stringsCount || r.strings.length, resources: r.resources.length, heap_mb_after: r.heap ?? null, stages_ms: { ...(r.bins[0].stages || {}), resource_validate: r.stageValidate || 0 } as Record<string, number> }));
  const q = (arr: number[], f: number) => { const s = arr.slice().sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(f * (s.length - 1)))] : 0; };
  const stageStats: Record<string, { median_ms: number; p90_ms: number; p95_ms: number; max_ms: number; max_plugin: string; total_ms: number }> = {}; for (const s of stageNames) { const v = perPlugin.map(p => p.stages_ms[s] || 0); stageStats[s] = { median_ms: q(v, 0.5), p90_ms: q(v, 0.9), p95_ms: q(v, 0.95), max_ms: Math.max(...v), max_plugin: perPlugin[v.indexOf(Math.max(...v))].plugin, total_ms: v.reduce((a, b) => a + b, 0) }; }
  const totals = perPlugin.map(p => p.ms); const medianTotal = q(totals, 0.5);
  const outliers = perPlugin.filter(p => p.ms > 3 * medianTotal).map(p => { const worst = Object.entries(p.stages_ms).sort((a, b) => b[1] - a[1])[0]; return { plugin: p.plugin, ms: p.ms, median_ms: medianTotal, dominant_stage: worst ? worst[0] : null, dominant_stage_ms: worst ? worst[1] : null }; });
  const perf = { total_ms: results.reduce((a, r) => a + r.ms!, 0), per_plugin: perPlugin, stage_stats: stageStats, outliers, user_agent: host.user_agent, hardware_threads: host.hardware_threads, device_memory_gb: host.device_memory_gb };
  return { N, results, classList, sharedThreshold, resList, bdNames, params, consts: Object.values(consts).sort((a, b) => b.plugins.length - a.plugins.length), xmlRoots, builds, pairs, errors, performance: perf };
}

export type Corpus = ReturnType<typeof buildCorpus>;

export function corpusReport(C: Corpus): string {
  const N = C.N, L: string[] = [];
  const shared = C.classList.filter(c => c.corpus_class === 'SHARED_SYMBOL_FAMILY'), specific = C.classList.filter(c => c.corpus_class === 'PLUGIN_SPECIFIC_NAME' && c.kind === 'PLUGIN_OWNED');
  const sharedOwned = shared.filter(c => c.kind === 'PLUGIN_OWNED');
  const nsOf = (n: string) => n.includes('::') ? n.split('::')[0] : (n.match(/^([A-Z][a-z]+|[a-z]+)/) || ['?'])[0];
  const nsCount: Record<string, number> = {}; sharedOwned.forEach(c => nsCount[nsOf(c.name)] = (nsCount[nsOf(c.name)] || 0) + 1);
  const topNs = Object.entries(nsCount).sort((a, b) => b[1] - a[1]).slice(0, 12);
  const sharedRes = C.resList.filter(r => r.count > 1);
  const linkers: Record<string, number> = {}; C.builds.forEach(b => linkers[b.linker || '?'] = (linkers[b.linker || '?'] || 0) + 1);
  const withParams = C.results.filter(r => Object.keys(r.params).length).length;
  const totalMB = C.results.reduce((a, r) => a + r.bins[0].size, 0) / 1048576;
  L.push(`# CORPUS_REPORT — ${N} plugins, static recovery v2`, '', `Total ${totalMB.toFixed(0)} MB scanned in ${(C.performance.total_ms/1000).toFixed(1)} s (${(totalMB / (C.performance.total_ms/1000)).toFixed(1)} MB/s). Evidence per plugin stays in its own folder; this report only correlates.`, '');
  L.push('## Plugins', '| plugin | MB | format | linker | built | JUCE | owned class names | serialized keys | valid res | ms |', '|---|---|---|---|---|---|---|---|---|---|');
  for (const r of C.results) { const b = r.bins[0]; const ids = Object.keys(r.params); const sf = ids.filter(i => /_\d+(_\d+)*$/.test(i)).length; L.push(`| ${r.key} | ${(b.size/1048576).toFixed(1)} | ${b.pe.format || '?'} ${b.pe.machine || ''} | ${b.pe.linker || '?'} | ${(b.pe.timestamp || '?').slice(0, 10)} | ${r.juce || (b.hasJuce ? 'yes' : 'no')} | ${(r.classesAll || []).filter(x => x.kind === 'PLUGIN_OWNED').length} | ${ids.length - sf}${sf ? ' (+' + sf + ' state fields)' : ''} | ${r.resources.filter(x => x.status === 'VALID_EXACT').length}/${r.resources.length} | ${r.ms} |`); }
  L.push('', '## Shared vs plugin-specific class NAMES (name recurrence ≠ implementation identity)', `Threshold for SHARED_SYMBOL_FAMILY: present in ≥${C.sharedThreshold} of ${N}.`, `- SHARED_SYMBOL_FAMILY (any kind): ${shared.length}; of which classified PLUGIN_OWNED: ${sharedOwned.length} → likely internal shared code family (verify implementations by fingerprint in standalone)`, `- RECURRING (2..${C.sharedThreshold - 1}): ${C.classList.filter(c => c.corpus_class === 'RECURRING_NAME').length}`, `- PLUGIN_SPECIFIC owned: ${specific.length} across ${N} plugins (${(specific.length / N).toFixed(1)} per plugin) — this is where deep analysis should focus`, '', 'Shared internal namespaces/prefixes (by class count):', ...topNs.map(([k, v]) => `- ${k}: ${v}`), '', 'Top shared owned classes:', ...sharedOwned.slice(0, 40).map(c => `- ${c.name} (${c.count}/${N}) [${c.role_candidate}]`), '', 'Plugin-specific owned classes by plugin:');
  for (const r of C.results) { const s = specific.filter(c => c.plugins[0] === r.key).map(c => c.name); L.push(`- ${r.key} (${s.length}): ${s.slice(0, 25).join(', ')}${s.length > 25 ? ' …' : ''}`); }
  L.push('', '## Class-NAME-set similarity (owned class names, Jaccard; not code similarity) — top pairs', ...C.pairs.slice(0, 15).map(p => `- ${p.a} ↔ ${p.b}: ${p.class_name_set_jaccard}`));
  { const parent: Record<string, string> = {}; const find = (x: string): string => parent[x] === undefined ? x : (parent[x] = find(parent[x])); const union = (a: string, b: string) => { const ra = find(a), rb = find(b); if (ra !== rb) parent[ra] = rb; };
    for (const p of C.pairs) if (p.class_name_set_jaccard >= 0.5) union(p.a, p.b);
    const fam: Record<string, string[]> = {}; for (const r of C.results) (fam[find(r.key!)] = fam[find(r.key!)] || []).push(r.key!);
    L.push('', '## Codebase families (connected at Jaccard ≥ 0.5) — analyse shared code once per family', ...Object.values(fam).sort((a, b) => b.length - a.length).map((m, i) => `- Family ${i + 1} (${m.length}): ${m.join(', ')}`)); }
  L.push('', '## Shared resources (identical SHA-256 across plugins)', ...(sharedRes.slice(0, 40).map(r => `- ${r.ext} ${(r.size/1024).toFixed(0)} KB ${r.dims} ${r.names.join('/')} in ${r.count}: ${r.plugins.join(', ')}`)), sharedRes.length ? '' : '- none');
  L.push('## Recurring BinaryData names', ...Object.entries(C.bdNames).sort((a, b) => b[1].length - a[1].length).slice(0, 30).map(([n, p]) => `- ${n}: ${p.length}`));
  L.push('', '## Serialized key names (recurrence; NOT verified VST parameters, NOT merged across plugins)', `${withParams}/${N} plugins have embedded preset XML.`, ...Object.entries(C.params).sort((a, b) => b[1].length - a[1].length).slice(0, 40).map(([id, p]) => `- ${id}: ${p.length} plugin(s)`));
  L.push('', '## XML/state schema roots', ...Object.entries(C.xmlRoots).sort((a, b) => b[1].length - a[1].length).map(([r, p]) => `- <${r}>: ${uniq(p).length} plugin(s)`));
  L.push('', '## DSP-relevant constant CANDIDATES (recurrence; not yet linked to processing code)', ...C.consts.slice(0, 20).map(c => `- ${c.label}: ${c.plugins.length}/${N} plugins, ${c.total} hits`));
  L.push('', '## Build fingerprints', ...Object.entries(linkers).map(([k, v]) => `- linker ${k}: ${v} plugins`), `- with .pdb reference: ${C.builds.filter(b => b.pdb).length}`, `- JUCE detected: ${C.builds.filter(b => b.juce).length}`);
  L.push('', '## Classifier error flags (grouped, max 15 per type)');
  for (const type of uniq(C.errors.map(e => e.type))) { const es = C.errors.filter(e => e.type === type); L.push(`### ${type} (${es.length})`, ...es.slice(0, 15).map(e => `- ${e.item}${e.value !== undefined ? ' · ' + e.value : ''}${e.in_plugins ? ' · in ' + e.in_plugins : ''} → ${e.suggestion}`), es.length > 15 ? `- … ${es.length - 15} more in classification_errors.json` : ''); }
  L.push('', '## Performance by stage (ms: median / p90 / p95 / max)', ...Object.entries(C.performance.stage_stats).map(([s, v]) => `- ${s}: ${v.median_ms} / ${v.p90_ms} / ${v.p95_ms} / ${v.max_ms} (max: ${v.max_plugin})`),
    '', '## Outliers (> 3× median total)', ...(C.performance.outliers.map(o => `- ${o.plugin}: ${o.ms} ms vs median ${o.median_ms} ms — dominant stage ${o.dominant_stage} (${o.dominant_stage_ms} ms)`)), C.performance.outliers.length ? '' : '- none',
    '## Per plugin', ...C.performance.per_plugin.map(p => `- ${p.plugin}: ${p.size_mb} MB, ${p.ms} ms (${p.mb_per_s} MB/s), ${p.strings.toLocaleString()} strings, ${p.resources} carves${p.heap_mb_after ? ', heap ' + p.heap_mb_after + ' MB' : ''}`));
  // spec delta
  const fixtures = C.results.slice().sort((a, b) => (Object.keys(b.params).length + b.resources.filter(x => x.ext === 'wav').length * 5 + (b.classesAll || []).filter(x => x.kind === 'THIRD_PARTY').length) - (Object.keys(a.params).length + a.resources.filter(x => x.ext === 'wav').length * 5 + (a.classesAll || []).filter(x => x.kind === 'THIRD_PARTY').length)).slice(0, 3).map(r => r.key);
  const biggest = C.results.slice().sort((a, b) => b.bins[0].size - a.bins[0].size)[0];
  L.push('', '## Standalone Build Spec Delta',
    `1. Corpus revealed: ${sharedOwned.length} "plugin-owned" classes recur across ≥${C.sharedThreshold} plugins — a shared internal library the single-plugin view mislabels as plugin DSP. Only ${(specific.length / N).toFixed(1)} owned classes per plugin are actually unique.`,
    `2. Classifiers needing redesign: ownership (needs corpus recurrence + vtable identity, not names); role (name-only; ${C.errors.filter(e => e.type === 'ROLE_COVERAGE').length} plugins with UNKNOWN-heavy coverage); BinaryData mapping (content-based only).`,
    `3. Trustworthy extraction: PE header/exports, RTTI class names, PNG/WAV/TTF/XML with structural bounds, embedded preset parameter IDs, font-name mapping, DSP-constant presence.`,
    `4. Freeze as complete: static scan, resource carving+validation, evidence bundle layout, scorecard, handoff files.`,
    `5. Standalone-only: identity/FUID, legal ranges/defaults/steps, vtables/inheritance, function bodies, callgraph roles, BinaryData→bytes for images, behavioural probes, build/differential tests.`,
    `6. Data contracts to consume (all wrapped {schema, schema_version: ${SCHEMA_VERSION}, data}): 00_manifest/*.json, 01_evidence/rtti/classes.json, 01_evidence/resources/index.json + binarydata_map.json, 03_architecture/serialized_keys.json (+ empty parameters.json for the runtime host to fill), classes.json, 07_agent_handoff/reconstruction_index.json, corpus/shared_class_names.json, corpus/performance.json.`,
    `7. Performance: ${(totalMB / (C.performance.total_ms/1000)).toFixed(1)} MB/s in-browser overall; stage outliers: ${C.performance.outliers.map(o => o.plugin + ' (' + o.dominant_stage + ' ' + o.dominant_stage_ms + ' ms)').join(', ') || 'none'}; largest binary ${biggest.key} took ${biggest.ms} ms${C.performance.per_plugin.some(p => (p.heap_mb_after ?? 0) > 1500) ? '; heap exceeded 1.5 GB' : ''}. Instrument every standalone stage the same way.`,
    `8. Remove before standalone: candidate-string parameter heuristics, name-based base-class inference in generated headers, per-plugin full strings.txt in corpus exports.`,
    `9. Regression fixtures: ${fixtures.join(', ')} (most parameters/assets/third-party coverage) plus ${biggest.key} for scale.`,
    `10. One-module target: requires an OWNED binary in the corpus — none is tagged as owned here; prefer the owned plugin's waveshaper/filter/resampler with a verified parameter and a carved IR or preset corpus.`);
  return L.join('\n');
}
