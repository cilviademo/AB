/// <reference lib="webworker" />
/**
 * Web Worker host for the frozen static engine (SPEC §2, §4). The webview
 * sends the categorized inputs as ArrayBuffers; progress streams back; the
 * bundle plan returns with its binary entries transferred, and the shell
 * hands it to the engine via `static.submit`. No DOM, no clipboard, no zip.
 */
import { runStatic, type CategorizedInputs } from "./run";
import type { InputFile } from "./types";

interface WireFile { name: string; path: string; kind?: "PE" | "Mach-O" | "ELF"; buffer: ArrayBuffer }
interface WireRequest { id: number; key: string; deep?: boolean; bins: WireFile[]; presets: WireFile[]; sources: WireFile[]; objs: WireFile[]; pdbs: WireFile[] }

const toInput = (f: WireFile): InputFile => ({ name: f.name, path: f.path, size: f.buffer.byteLength, kind: f.kind, bytes: async () => new Uint8Array(f.buffer) });

self.onmessage = async (ev: MessageEvent<WireRequest>) => {
  const req = ev.data;
  const post = (msg: unknown, transfer: Transferable[] = []) => (self as unknown as Worker).postMessage(msg, transfer);
  try {
    const inputs: CategorizedInputs = { key: req.key, bins: req.bins.map(toInput), presets: req.presets.map(toInput), sources: req.sources.map(toInput), objs: req.objs.map(toInput), pdbs: req.pdbs.map(toInput) };
    const perfMem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    const { result } = await runStatic(inputs, async (message) => { post({ id: req.id, event: "progress", message }); }, { deep: !!req.deep, peakRss: () => perfMem ? Math.round(perfMem.usedJSHeapSize / 1048576) : null });
    const transfer: Transferable[] = [];
    for (const e of result.entries) if ("bytes" in e) transfer.push(e.bytes.buffer as ArrayBuffer);
    post({ id: req.id, event: "result", result }, transfer);
  } catch (err) {
    post({ id: req.id, event: "error", error: String((err as Error)?.stack || err) });
  }
};
