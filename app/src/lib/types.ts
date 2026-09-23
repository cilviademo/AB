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

// ADDENDUM C1: interpretation tags — they change how results read, never what runs
export type UsageContext = "USER_RECOVERY" | "KNOWN_SOURCE_FIXTURE" | "BLACK_BOX_REFERENCE" | "SOURCE_AVAILABLE_REFERENCE" | "UNKNOWN_CONTEXT";
export type SourceAvailability = "SOURCE_UNKNOWN" | "SOURCE_UNAVAILABLE" | "SOURCE_PARTIAL" | "SOURCE_AVAILABLE" | "KNOWN_SOURCE_GROUND_TRUTH";
export interface RecoveryContext { usage_context: UsageContext; source_availability: SourceAvailability }
// docs/NAMING_CANONICALIZATION.md §5, §20 — evidence always keeps original names; this only decides what the source calls things
export type NamingMode = "PRESERVE_ORIGINAL_NAMES" | "CANONICALIZE_NAMES" | "CUSTOM_RENAME_MAP";
// ADDENDUM C3 — recovery goal; PRESERVE_ORIGINAL produces no transformation nodes
export type RecoveryGoal = "PRESERVE_ORIGINAL" | "MODERNIZE" | "MIGRATE" | "REFACTOR" | "PORT" | "REBUILD";
export interface TransformationGraph { goal: RecoveryGoal; goal_text: string; available: boolean; not_available_reason?: string | null; active_variant: "RECOVERED" | "TRANSFORMED"; validated_variant?: string; transformation_nodes: number;
  subsystems: { subsystem: string; module?: string; symbol?: string; status: string; behavioral_compatibility: string; transformation?: string | null; preserve?: string | null; nodes: { node: string; ref: string | null; status?: string }[]; intentional_behavioral_changes: { change: string; status: string }[] }[];
  comparisons?: { pair: string; renders: number; classification?: string; worst_rmse?: number | null }[]; intentional_behavioral_changes?: { subsystem: string; symbol?: string; change: string; status: string }[] }
export interface IdentifierRow { original: string; kind: string; original_address: string | null; evidence_status: string; category: string; semantic: string; active: string; reason: string; collision?: { with: string[]; resolved_by: string } }
export interface IdentifierMap { mode: NamingMode; terms: Record<string, string>; identifiers: IdentifierRow[]; parameters: { runtime_param_id: string | number; original_display_name: string; transformed_display_name: string }[]; state_keys: { legacy: string; new: string; migration_status: string }[]; resources: { original_binarydata_name: string; original_filename: string; new_filename: string }[] }
export const CONTEXT_LABEL: Record<UsageContext, string> = {
  USER_RECOVERY: "user recovery", KNOWN_SOURCE_FIXTURE: "known-source fixture", BLACK_BOX_REFERENCE: "black-box reference",
  SOURCE_AVAILABLE_REFERENCE: "source-available reference", UNKNOWN_CONTEXT: "context unknown",
};

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
  usage_context: UsageContext;
  source_availability: SourceAvailability;
  interpretation?: string;
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
