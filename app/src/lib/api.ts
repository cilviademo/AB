/** Thin wrapper over the Tauri command that talks to the AB engine. */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type {
  BackendStatus, BundleEntry, Doctor, Env, IngestResult, Job, Ownership, ProgressEvent,
} from "./types";

export class BackendError extends Error {
  readonly code: string;
  constructor(code: string, detail: string) {
    super(detail);
    this.code = code;
    this.name = "BackendError";
  }
}

interface Envelope<T> { id?: number; ok: boolean; data?: T; error?: string; detail?: string }

export async function call<T>(method: string, payload: Record<string, unknown> = {}): Promise<T> {
  let envelope: Envelope<T>;
  try {
    envelope = await invoke<Envelope<T>>("api", { method, payload });
  } catch (err) {
    throw new BackendError("bridge", String(err));
  }
  if (!envelope.ok) {
    throw new BackendError(envelope.error ?? "unknown", envelope.detail ?? "Something went wrong.");
  }
  return envelope.data as T;
}

export const api = {
  environment: () => call<Env>("environment"),
  doctor: () => call<Doctor>("doctor"),
  settings: () => call<Record<string, unknown>>("settings.get"),
  saveSettings: (settings: Record<string, unknown>) => call<Record<string, unknown>>("settings.set", { settings }),

  // -- jobs (1.2 / 1.3) --
  ingest: (paths: string[], ownership: Ownership, name?: string) =>
    call<IngestResult>("ingest.run", { paths, ownership, name }),
  jobs: () => call<{ jobs: Job[] }>("job.list").then((r) => r.jobs),
  job: (jobId: string) => call<Job>("job.get", { job_id: jobId }),
  runJob: (jobId: string, stages?: string[], options?: Record<string, unknown>) =>
    call<Job>("job.run", { job_id: jobId, stages, options }),
  cancelJob: (jobId: string) => call<{ cancelled: boolean }>("job.cancel", { job_id: jobId }),

  // -- static results delivered from the webview worker (1.4) --
  submitStatic: (jobId: string, result: unknown) => call<Job>("static.submit", { job_id: jobId, result }),

  // -- bundle browsing / export (1.5) --
  bundleTree: (jobId: string) => call<{ entries: BundleEntry[]; root: string }>("bundle.tree", { job_id: jobId }),
  bundleRead: (jobId: string, path: string) => call<{ text: string | null; schema: string | null; size: number }>("bundle.read", { job_id: jobId, path }),
  scorecard: (jobId: string) => call<{ cells: { key: string; value: string; detail: string; evidence: string }[] }>("bundle.scorecard", { job_id: jobId }),
  exportBundle: (jobId: string, zip: boolean) => call<{ out_dir: string; zip_path: string | null; git_ready: { ok: boolean; checks: { name: string; ok: boolean | null; detail: string }[] } }>("bundle.export", { job_id: jobId, zip }),
};

/** Subscribe to job progress. Returns an unsubscribe function. */
export function onProgress(handler: (event: ProgressEvent) => void) {
  const promise = listen<ProgressEvent>("job-progress", (e) => handler(e.payload));
  return () => { void promise.then((un) => un()); };
}

export async function backendStatus(): Promise<BackendStatus> {
  const raw = await invoke<Record<string, unknown>>("backend_status");
  return {
    ok: Boolean(raw.ok),
    portable: Boolean(raw.portable),
    safeMode: Boolean(raw.safe_mode),
    home: String(raw.home ?? ""),
    state: String(raw.state ?? ""),
    logs: String(raw.logs ?? ""),
    coreVersion: raw.core_version as string | undefined,
    coreExecutable: raw.core_executable as string | undefined,
    error: raw.error as string | undefined,
  };
}

export async function restartCore(): Promise<BackendStatus> {
  await invoke("restart_core");
  return backendStatus();
}

export async function saveWindow(bounds: { width: number; height: number; x: number; y: number }) {
  try { await invoke("save_window", bounds); } catch { /* geometry is a convenience */ }
}

export const shell = {
  reveal: (path: string) => invoke<void>("reveal", { path }),
  openInEditor: (path: string) => invoke<void>("open_in_editor", { path }),
  readBundleFile: (path: string, maxBytes?: number) => invoke<number[]>("read_bundle_file", { path, maxBytes }),
};
