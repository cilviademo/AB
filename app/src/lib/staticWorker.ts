/**
 * Runs the frozen static engine in a Web Worker inside the webview (SPEC §2)
 * and hands the plan to the engine. Input bytes come from the object store
 * through the shell's sandboxed `read_bundle_file`; the webview never opens
 * arbitrary paths and never loads a plugin — it reads bytes and scans them.
 */
import { api, call, shell } from "./api";

interface StaticInput { path: string; name: string; kind: string; size: number; object_path: string }
interface WireFile { name: string; path: string; kind?: "PE" | "Mach-O" | "ELF"; buffer: ArrayBuffer }

function kindOf(head: Uint8Array): "PE" | "Mach-O" | "ELF" {
  if (head[0] === 0x7f && head[1] === 0x45) return "ELF";
  if ((head[0] === 0xcf && head[1] === 0xfa) || (head[0] === 0xca && head[1] === 0xfe)) return "Mach-O";
  return "PE";
}

function b64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)));
  return btoa(s);
}

export async function runStaticInWorker(jobId: string, onProgress: (message: string) => void, deep = false): Promise<{ entries: number }> {
  const inputs = await call<{ key: string; files: StaticInput[] }>("static.inputs", { job_id: jobId });
  const load = async (f: StaticInput): Promise<WireFile> => {
    const bytes = new Uint8Array(await shell.readBundleFile(f.object_path, 512 * 1024 * 1024));
    return { name: f.name, path: f.path, kind: f.kind === "binary" ? kindOf(bytes) : undefined, buffer: bytes.buffer as ArrayBuffer };
  };
  const pick = async (kinds: string[]) => Promise.all(inputs.files.filter((f) => kinds.includes(f.kind)).map(load));
  const req = {
    id: 1, key: inputs.key, deep,
    bins: await pick(["binary"]), presets: await pick(["preset", "session"]), sources: await pick(["source"]),
    objs: await pick(["obj"]), pdbs: await pick(["pdb"]),
  };
  const worker = new Worker(new URL("../../static-engine/src/worker.ts", import.meta.url), { type: "module" });
  const result = await new Promise<{ entries: ({ path: string; bytes?: Uint8Array } & Record<string, unknown>)[] } & Record<string, unknown>>((resolve, reject) => {
    worker.onmessage = (ev: MessageEvent) => {
      const msg = ev.data;
      if (msg.event === "progress") onProgress(String(msg.message));
      else if (msg.event === "result") resolve(msg.result);
      else if (msg.event === "error") reject(new Error(String(msg.error)));
    };
    worker.onerror = (e) => reject(new Error(e.message));
    const transfer = [...req.bins, ...req.presets, ...req.sources, ...req.objs, ...req.pdbs].map((f) => f.buffer);
    worker.postMessage(req, transfer);
  });
  worker.terminate();
  const entries = result.entries.map((e) => e.bytes instanceof Uint8Array
    ? { ...e, bytes: undefined, bytes_b64: b64(e.bytes) }
    : e);
  const submitted = await api.submitStatic(jobId, { ...result, entries });
  void submitted;
  return { entries: entries.length };
}
