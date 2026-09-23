/**
 * The engine-facing entry: categorized inputs in, bundle plan + instrumentation out.
 * Shared by the Web Worker (GUI) and the Node CLI (ab-cli / CI).
 */
import { analyzeGroup } from "./analyze";
import { buildBundle, buildCorpusBundle, type PlanEntry } from "./bundle";
import { buildCorpus, type CorpusHost } from "./corpus";
import { now } from "./bytes";
import { PORT_VERSION, TOOL_VERSION, type AnalyzeOptions, type GroupResult, type InputFile, type Tick } from "./types";

export interface CategorizedInputs {
  key: string;
  bins: InputFile[]; presets: InputFile[]; sources: InputFile[]; objs: InputFile[]; pdbs: InputFile[];
}

export interface Instrumentation {
  tool: string; port: string; deep: boolean;
  elapsed_ms: number; bytes_processed: number; objects_found: number; peak_rss_mb: number | null;
  stages_ms: Record<string, number>; strings: number; resources: number;
  completeness: "FAST_SCAN_COMPLETE" | "FAST_SCAN_EARLY_TERMINATED" | "DEEP_SCAN_COMPLETE";
  xml_scan_status: string;
}

export interface StaticRunResult {
  key: string;
  entries: PlanEntry[];
  summary: Record<string, unknown>;
  instrumentation: Instrumentation;
  /** Enough of the group result for the engine's DEEP_SCAN triggers (SPEC §6.3). */
  triggers: { binarydata_names_by_ext: Record<string, number>; carved_by_ext: Record<string, number>; state_keys: string[]; keys_in_documents: string[] };
}

export async function runStatic(inputs: CategorizedInputs, tick: Tick, opts: AnalyzeOptions & { peakRss?: () => number | null } = {}): Promise<{ result: StaticRunResult; group: GroupResult }> {
  const t0 = now();
  const R = await analyzeGroup(inputs.bins, inputs.presets, inputs.sources, inputs.objs, inputs.pdbs, tick, opts);
  R.key = inputs.key; R.ms = Math.round(now() - t0);
  R.heap = opts.peakRss ? opts.peakRss() : null;
  const plan = buildBundle(R);
  const bytes = inputs.bins.reduce((a, b) => a + b.size, 0) + inputs.presets.reduce((a, b) => a + b.size, 0);
  const b0 = R.bins[0];
  const xmlStatus = b0?.xmlScanStatus || '';
  const completeness: Instrumentation["completeness"] = opts.deep ? 'DEEP_SCAN_COMPLETE' : /EARLY_TERMINATED/.test(xmlStatus) ? 'FAST_SCAN_EARLY_TERMINATED' : 'FAST_SCAN_COMPLETE';
  const byExt = (names: string[]) => { const m: Record<string, number> = {}; for (const n of names) { const e = (n.match(/_(png|jpg|jpeg|svg|ttf|otf|xml|json|wav|aiff|txt)$/) || [])[1]; if (!e) continue; const k = e === 'jpeg' ? 'jpg' : e === 'aiff' ? 'wav' : e; m[k] = (m[k] || 0) + 1; } return m; };
  const carved: Record<string, number> = {}; for (const x of R.resources) if (x.status === 'VALID_EXACT' || x.status === 'PARSER_VALID') carved[x.ext] = (carved[x.ext] || 0) + 1;
  const docs = R.resources.filter(x => x.ext === 'xml' && (x.status === 'VALID_EXACT' || x.status === 'PARSER_VALID')).map(x => new TextDecoder('latin1').decode(x.data)).concat(R.presetFiles.map(p => p.xml)).join('\n');
  const keys = Object.keys(R.params);
  const result: StaticRunResult = {
    key: inputs.key, entries: plan.entries, summary: plan.summary,
    instrumentation: {
      tool: TOOL_VERSION, port: PORT_VERSION, deep: !!opts.deep, elapsed_ms: R.ms, bytes_processed: bytes,
      objects_found: R.resources.length + (R.classesAll || []).length + keys.length, peak_rss_mb: R.heap ?? null,
      stages_ms: { ...(b0?.stages || {}), resource_validate: R.stageValidate || 0 }, strings: R.strings.length, resources: R.resources.length,
      completeness, xml_scan_status: xmlStatus,
    },
    triggers: { binarydata_names_by_ext: byExt(R.bins.flatMap(x => x.binaryDataNames || [])), carved_by_ext: carved, state_keys: keys, keys_in_documents: keys.filter(k => docs.includes(`id="${k}"`)) },
  };
  return { result, group: R };
}

export function runCorpus(groups: GroupResult[], host?: CorpusHost): { entries: PlanEntry[]; report: string } {
  const C = buildCorpus(groups, host);
  const entries = buildCorpusBundle(C);
  const report = (entries.find(e => e.path === 'corpus/CORPUS_REPORT.md') as { text: string }).text;
  return { entries, report };
}
