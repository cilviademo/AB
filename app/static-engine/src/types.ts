/**
 * Static Recovery v2 — data shapes.
 *
 * These mirror the ad-hoc objects the frozen browser engine built. Field
 * names are kept exactly: the engine's outputs are the v2 contracts
 * (`recovery.*`, schema_version 2) and the regression baselines diff on them.
 */

export const SCHEMA_VERSION = 2;
export const TOOL_VERSION = "static-recovery-v2";
/** Port identity, recorded beside TOOL_VERSION in stage records (never in v2 files). */
export const PORT_VERSION = "ab-static-engine 1.0.0";

export type BinaryKind = "PE" | "Mach-O" | "ELF";

export interface PEInfo {
  machine?: string;
  timestamp?: string;
  linker?: string;
  sectionNames?: string;
  rdata?: [number, number];
  exports?: string[];
  format?: string;
  error?: string;
}

export interface ClassRec { name: string; kind: string }
export interface PathRec { path: string; kind: string }
export interface ConstHit { label: string; value: number; count: number; offsets: string[] }
export interface EmbeddedParam { id: string; value: number }

export interface Resource {
  ext: string;
  mime: string;
  data: Uint8Array;
  offset: number;
  boundary: "BOUNDARY_VERIFIED" | "HEURISTIC";
  name: string;
  from?: string;
  sha256?: string | null;
  status?: string;
  parser?: string;
  dupOf?: string;
  dims?: string;
  root?: string;
  semantics?: string;
  embeddedName?: string | null;
  candidate_name?: string;
  mapping_status?: string;
}

export interface CarveResult extends Array<Resource> { xml_scan_status?: string }

export interface BinaryResult {
  name: string;
  kind: BinaryKind;
  size: number;
  pe: PEInfo;
  strings: string[];
  classes: string[];
  classesAll?: ClassRec[];
  tree: string[];
  pathsAll?: PathRec[];
  paramIds: string[];
  resources: CarveResult;
  consts: ConstHit[];
  juce: string | null;
  pdb: string | null;
  buckets: Record<string, string[]>;
  embeddedParams?: EmbeddedParam[];
  embeddedXml?: string;
  paramNote?: string;
  hasJuce?: boolean;
  candidateStrings?: string[];
  binaryDataNames?: string[];
  xmlScanStatus?: string;
  stages?: Record<string, number>;
  sha256?: string | null;
}

export interface ParamRec { id: string; values: number[]; source?: string; conf?: number }
export interface PresetFile { name: string; count: number; xml: string }
export interface InputRec { path: string; size: number; sha256?: string | null }
export interface Rescued { path: string; data: Uint8Array }

export interface GroupResult {
  bins: BinaryResult[];
  classes: string[];
  classesAll?: ClassRec[];
  pathsAll?: PathRec[];
  params: Record<string, ParamRec>;
  tree: string[];
  juce: string | null;
  pdb: string | null;
  pdbFound: boolean;
  resources: Resource[];
  consts: ConstHit[];
  strings: string[];
  buckets: Record<string, string[]>;
  rescued: Rescued[];
  presetFiles: PresetFile[];
  inputs: InputRec[];
  candidateStrings?: string[];
  binaryDataMap?: BinaryDataMapEntry[];
  stageValidate?: number;
  key?: string;
  ms?: number;
  heap?: number | null;
  stringsCount?: number;
}

export interface BinaryDataMapEntry {
  binarydata_name: string;
  carved: string | null;
  offset?: number;
  size?: number;
  mapping_status: string;
}

/** A dropped file as the engine sees it: bytes plus its logical path. */
export interface InputFile {
  name: string;
  path: string;
  size: number;
  kind?: BinaryKind;
  bytes: () => Promise<Uint8Array>;
}

export type Tick = (message: string) => Promise<void>;

export interface AnalyzeOptions {
  /** SPEC §6.3 DEEP_SCAN: exhaustive anchors, no early stop, full-file window. */
  deep?: boolean;
}
