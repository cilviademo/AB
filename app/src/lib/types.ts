/** Shapes returned by the engine. Mirrors engine/ab_engine/api.py and the
 *  artifactbench.* contracts; keep the two in step. */

export type StageKey =
  | "INGEST" | "STATIC" | "RUNTIME" | "DECOMPILE" | "PROBE"
  | "RECONSTRUCT" | "BUILD" | "COMPARE" | "EXPORT";

export const STAGE_KEYS: StageKey[] = [
  "INGEST", "STATIC", "RUNTIME", "DECOMPILE", "PROBE", "RECONSTRUCT", "BUILD", "COMPARE", "EXPORT",
];

/** Engine stage names (SPEC §5) ↔ rail keys (SPEC §14 + brief). */
export const STAGE_OF: Record<string, StageKey> = {
  INGESTED: "INGEST", STATIC_COMPLETE: "STATIC", RUNTIME_COMPLETE: "RUNTIME",
  DECOMPILATION_COMPLETE: "DECOMPILE", BEHAVIOR_COMPLETE: "PROBE",
  RECONSTRUCTION_COMPLETE: "RECONSTRUCT", BUILD_COMPLETE: "BUILD",
  VALIDATION_COMPLETE: "COMPARE", EXPORT_COMPLETE: "EXPORT",
};

export type StageStatus = "PENDING" | "RUNNING" | "OK" | "FAILED" | "SKIPPED";

export type Ownership = "OWNED" | "AUTHORIZED" | "THIRD_PARTY";

export interface StageRecord {
  job_id: string;
  stage: string;
  status: StageStatus;
  input_hashes: string[];
  tool_versions: Record<string, string>;
  config_hash: string;
  stage_version: number;
  started: string | null;
  ended: string | null;
  warnings: { code: string; message: string }[];
  errors: { code: string; message: string }[];
  outputs: string[];
  completeness: string;
  metrics?: Record<string, unknown>;
  skip_reason?: string | null;
}

export interface Job {
  job_id: string;
  name: string;
  artifact_sha256: string;
  ownership: Ownership;
  created: string;
  primary: string;          // path of the primary binary
  project_dir: string;      // Projects/<slug>/
  stages: StageRecord[];
}

export interface ProgressEvent {
  id: number;
  stage: string;
  status: string;
  detail: string;
  extra: Record<string, unknown>;
}

export interface BackendStatus {
  ok: boolean;
  portable: boolean;
  safeMode: boolean;
  home: string;
  state: string;
  logs: string;
  coreVersion?: string;
  coreExecutable?: string;
  error?: string;
}

export interface DoctorRow { name: string; verdict: "PASS" | "WARNING" | "UNAVAILABLE" | "FAIL"; detail: string }
export interface Doctor {
  ok: boolean; rows: DoctorRow[]; counts: Record<string, number>;
  workspace: { home: string; state: string; version: string }; report: string;
}

export interface ToolInfo { name: string; path: string | null; version: string | null; detail: string; present: boolean }
export interface Env {
  version: string; platform: string; python: string; frozen: boolean;
  home: string; state: string; tools: ToolInfo[];
}

export interface IngestedFile {
  path: string; size: number; sha256: string; kind: string; attached_to?: string | null;
}
export interface IngestResult {
  jobs: Job[]; files: IngestedFile[]; duplicates: string[][]; ignored: number;
}

export interface BundleEntry { path: string; size: number; kind: "file" | "dir"; schema?: string }
