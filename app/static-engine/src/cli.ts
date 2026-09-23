/**
 * Node host for the frozen static engine (DECISIONS D-005): used by ab-cli and CI.
 *
 *   node cli.mjs analyze --inputs inputs.json --out <dir> [--deep] [--key NAME]
 *   node cli.mjs corpus  --groups g1.json,g2.json --out <dir>
 *   node cli.mjs selftest <binary>
 *   node cli.mjs plan --inputs inputs.json [--deep]      → StaticRunResult as JSON, bytes base64 (what the GUI worker submits)
 *
 * inputs.json: [{ "path": "<logical path>", "fs_path": "<file on disk>", "kind": "binary|preset|session|source|obj|pdb|map|asset|other", "format": "PE|Mach-O|ELF" }]
 * The plan is written under <out>/: JSON entries as files, binary entries as
 * files plus `static_result.json` (entries, summary, instrumentation, triggers)
 * so the Python engine can index them into the object store.
 */
import { readFileSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { dirname, join, basename } from "node:path";
import { runStatic, runCorpus, type CategorizedInputs } from "./run";
import type { GroupResult, InputFile } from "./types";

function arg(name: string, def?: string): string | undefined {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : def;
}
const flag = (name: string) => process.argv.includes(name);

function fileInput(path: string, fsPath: string, format?: string): InputFile {
  const size = statSync(fsPath).size;
  return { name: basename(path), path, size, kind: (format as InputFile["kind"]) || "PE", bytes: async () => new Uint8Array(readFileSync(fsPath)) };
}

async function analyze(): Promise<number> {
  const inputsPath = arg("--inputs"); const out = arg("--out");
  if (!inputsPath || !out) { console.error("usage: analyze --inputs inputs.json --out <dir> [--deep] [--key NAME]"); return 5; }
  const list = JSON.parse(readFileSync(inputsPath, "utf-8")) as { path: string; fs_path: string; kind: string; format?: string }[];
  const cat: CategorizedInputs = { key: arg("--key", basename(dirname(inputsPath)))!, bins: [], presets: [], sources: [], objs: [], pdbs: [] };
  for (const f of list) {
    const inp = fileInput(f.path, f.fs_path, f.format);
    if (f.kind === "binary") cat.bins.push(inp);
    else if (f.kind === "preset" || f.kind === "session") cat.presets.push(inp);
    else if (f.kind === "source") cat.sources.push(inp);
    else if (f.kind === "obj") cat.objs.push(inp);
    else if (f.kind === "pdb") cat.pdbs.push(inp);
  }
  if (!cat.bins.length) { console.error("no binary inputs"); return 5; }
  const { result, group } = await runStatic(cat, async (m) => { process.stderr.write(JSON.stringify({ event: "progress", message: m }) + "\n"); }, { deep: flag("--deep"), peakRss: () => Math.round(process.memoryUsage().rss / 1048576) });
  mkdirSync(out, { recursive: true });
  const written: { path: string; kind: string; schema?: string; size: number; sha256?: string | null; carved?: boolean }[] = [];
  for (const e of result.entries) {
    const target = join(out, e.path);
    mkdirSync(dirname(target), { recursive: true });
    if ("json" in e) { const text = JSON.stringify(e.json, null, 2); writeFileSync(target, text); written.push({ path: e.path, kind: "json", schema: e.schema, size: text.length }); }
    else if ("text" in e) { writeFileSync(target, e.text); written.push({ path: e.path, kind: "text", size: e.text.length }); }
    else { writeFileSync(target, e.bytes); written.push({ path: e.path, kind: "bytes", size: e.bytes.length, sha256: e.sha256, carved: e.carved }); }
  }
  // Group result without the heavy arrays, for corpus mode (SPEC §9) and the engine's triggers.
  const slim: Partial<GroupResult> = { ...group, strings: [], rescued: [], resources: group.resources.map(x => ({ ...x, data: new Uint8Array(0) })) as GroupResult["resources"], stringsCount: group.strings.length };
  slim.bins = group.bins.map(b => ({ ...b, strings: [], resources: [] as never }));
  writeFileSync(join(out, "static_result.json"), JSON.stringify({ key: result.key, summary: result.summary, instrumentation: result.instrumentation, triggers: result.triggers, files: written }, null, 2));
  writeFileSync(join(out, "static_group.json"), JSON.stringify(slim));
  process.stdout.write(JSON.stringify({ ok: true, key: result.key, files: written.length, instrumentation: result.instrumentation, summary: result.summary, triggers: result.triggers }) + "\n");
  return 0;
}

async function corpus(): Promise<number> {
  const groupsArg = arg("--groups"); const out = arg("--out");
  if (!groupsArg || !out) { console.error("usage: corpus --groups a.json,b.json --out <dir>"); return 5; }
  const groups = groupsArg.split(",").map(p => JSON.parse(readFileSync(p, "utf-8")) as GroupResult);
  const { entries, report } = runCorpus(groups, { user_agent: `node ${process.version}`, hardware_threads: (await import("node:os")).cpus().length, device_memory_gb: null });
  mkdirSync(out, { recursive: true });
  for (const e of entries) {
    const target = join(out, e.path); mkdirSync(dirname(target), { recursive: true });
    if ("json" in e) writeFileSync(target, JSON.stringify(e.json, null, 1));
    else if ("text" in e) writeFileSync(target, e.text);
  }
  process.stdout.write(JSON.stringify({ ok: true, files: entries.length, report_chars: report.length }) + "\n");
  return 0;
}

async function plan(): Promise<number> {
  const inputsPath = arg("--inputs");
  if (!inputsPath) { console.error("usage: plan --inputs inputs.json [--deep]"); return 5; }
  const list = JSON.parse(readFileSync(inputsPath, "utf-8")) as { path: string; fs_path: string; kind: string; format?: string }[];
  const cat: CategorizedInputs = { key: arg("--key", basename(dirname(inputsPath)))!, bins: [], presets: [], sources: [], objs: [], pdbs: [] };
  for (const f of list) {
    const inp = fileInput(f.path, f.fs_path, f.format);
    if (f.kind === "binary") cat.bins.push(inp); else if (f.kind === "preset" || f.kind === "session") cat.presets.push(inp);
    else if (f.kind === "source") cat.sources.push(inp); else if (f.kind === "obj") cat.objs.push(inp); else if (f.kind === "pdb") cat.pdbs.push(inp);
  }
  const { result } = await runStatic(cat, async () => {}, { deep: flag("--deep") });
  const entries = result.entries.map((e) => "bytes" in e ? { path: e.path, bytes_b64: Buffer.from(e.bytes).toString("base64"), sha256: e.sha256, carved: e.carved } : e);
  process.stdout.write(JSON.stringify({ ...result, entries }) + "\n");
  return 0;
}

async function selftest(): Promise<number> {
  const file = process.argv[3];
  if (!file) { console.error("usage: selftest <binary>"); return 5; }
  const inp = fileInput(basename(file), file);
  const { result } = await runStatic({ key: basename(file), bins: [inp], presets: [], sources: [], objs: [], pdbs: [] }, async () => {}, {});
  process.stdout.write(JSON.stringify({ ok: true, summary: result.summary, instrumentation: result.instrumentation }, null, 2) + "\n");
  return 0;
}

const cmd = process.argv[2];
const main = cmd === "analyze" ? analyze : cmd === "corpus" ? corpus : cmd === "selftest" ? selftest : cmd === "plan" ? plan : async () => { console.error("commands: analyze | corpus | selftest | plan"); return 5; };
// Never process.exit() right after writing: a piped stdout is flushed asynchronously and
// a large plan would be truncated at 64 KiB. Set the exit code and let the loop drain.
main().then((code) => { process.exitCode = code; }, (err) => { console.error(err?.stack || String(err)); process.exitCode = 1; });
