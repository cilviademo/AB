import { useEffect, useMemo, useState } from "react";
import type { BundleEntry, IdentifierMap, Job, ProgressEvent, StageKey } from "../lib/types";
import { CONTEXT_LABEL, STAGE_KEYS, STAGE_OF } from "../lib/types";
import { api, shell } from "../lib/api";
import {
  Advanced, Button, Ev, KeyValues, Note, Scorecard, Section, StageRail, type RailStage,
} from "../components/ui";
import { bytes, ms, shortHash } from "../lib/format";

export type BenchScreen =
  | "overview" | "evidence" | "params" | "architecture" | "dsp" | "resources"
  | "compare" | "build" | "export";

const SCREENS: { key: BenchScreen; label: string; stage: string; phase: string }[] = [
  { key: "overview", label: "Overview", stage: "", phase: "" },
  { key: "evidence", label: "Evidence", stage: "", phase: "" },
  { key: "params", label: "Parameters & State", stage: "RUNTIME", phase: "Phase 2 (vst3host)" },
  { key: "architecture", label: "Architecture", stage: "DECOMPILE", phase: "Phase 3 (Ghidra RTTI + callgraph)" },
  { key: "dsp", label: "DSP", stage: "PROBE", phase: "Phase 3–4 (DSP scoring, probes, fits)" },
  { key: "resources", label: "Resources", stage: "", phase: "" },
  { key: "compare", label: "Compare", stage: "COMPARE", phase: "Phase 4 (differential harness)" },
  { key: "build", label: "Build", stage: "BUILD", phase: "Phase 4 (CMake/MSVC, pluginval)" },
  { key: "export", label: "Export", stage: "", phase: "" },
];

function railFrom(job: Job, events: ProgressEvent[]): RailStage[] {
  const byStage = new Map<string, RailStage>();
  for (const key of STAGE_KEYS) byStage.set(key, { key, status: "PENDING" });
  for (const rec of job.stages) {
    const key = STAGE_OF[rec.stage];
    if (!key) continue;
    const elapsed = rec.started && rec.ended ? ms(new Date(rec.ended).getTime() - new Date(rec.started).getTime()) : undefined;
    const detail = rec.status === "SKIPPED" ? (rec.skip_reason ?? "skipped")
      : rec.status === "FAILED" ? (rec.errors[0]?.code ?? "failed")
      : rec.status === "OK" ? [elapsed, rec.completeness !== "NOT_APPLICABLE" ? rec.completeness : null].filter(Boolean).join(" · ")
      : rec.status.toLowerCase();
    byStage.set(key, { key, status: rec.status, detail });
  }
  for (const e of events) {
    const key = (e.stage.toUpperCase() as StageKey);
    if (!byStage.has(key)) continue;
    const status = e.status === "running" ? "RUNNING" : e.status === "ok" ? "OK" : e.status === "failed" ? "FAILED" : e.status === "skipped" ? "SKIPPED" : "PENDING";
    if (status === "RUNNING") byStage.set(key, { key, status, detail: e.detail });
  }
  return STAGE_KEYS.map((k) => byStage.get(k)!);
}

export function Bench({
  job, screen, events, onScreen, onRefresh, onRun, busy,
}: {
  job: Job; screen: BenchScreen; events: ProgressEvent[];
  onScreen: (s: BenchScreen) => void; onRefresh: () => void;
  onRun: (stages?: string[]) => void; busy: boolean;
}) {
  const rail = useMemo(() => railFrom(job, events), [job, events]);
  const failed = job.stages.filter((s) => s.status === "FAILED");

  return (
    <div className="view wide enter">
      <div className="row" style={{ alignItems: "baseline" }}>
        <div className="label">Recovery Bench</div>
        <span className="mono faint">{CONTEXT_LABEL[job.usage_context] ?? job.usage_context} · {shortHash(job.artifact_sha256)}</span>
        <span className="grow" />
        <Button size="sm" variant="quiet" onClick={onRefresh}>Refresh</Button>
        <Button size="sm" disabled={busy} onClick={() => onRun()}>{busy ? "Working" : "Run remaining stages"}</Button>
      </div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>{job.name}</h1>

      <div style={{ marginTop: "var(--s6)" }}>
        <StageRail stages={rail} />
      </div>

      {failed.length > 0 && (
        <div style={{ marginTop: "var(--s5)" }}>
          {failed.map((s) => (
            <Note key={s.stage} strong heading={`${STAGE_OF[s.stage]} failed · ${s.errors[0]?.code ?? "ERROR"}`}>
              {s.errors[0]?.message ?? "See the stage log."}
            </Note>
          ))}
        </div>
      )}

      <nav className="nav" style={{ marginTop: "var(--s7)", borderBottom: "1px solid var(--line)", height: 36 }}>
        {SCREENS.map((s) => (
          <button key={s.key} type="button" aria-current={screen === s.key ? "page" : undefined} onClick={() => onScreen(s.key)}>
            {s.label}
          </button>
        ))}
      </nav>

      <div style={{ marginTop: "var(--s6)" }}>
        {screen === "overview" && <Overview job={job} onScreen={onScreen} />}
        {screen === "evidence" && <EvidenceBrowser job={job} />}
        {screen === "resources" && <Resources job={job} />}
        {screen === "export" && <Export job={job} />}
        {screen === "params" && <ParamsState job={job} />}
        {screen === "architecture" && <Architecture job={job} />}
        {screen === "dsp" && <Dsp job={job} />}
        {screen === "build" && <Build job={job} />}
        {screen === "compare" && <Compare job={job} />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ overview -- */

function Overview({ job, onScreen }: { job: Job; onScreen: (s: BenchScreen) => void }) {
  const [cells, setCells] = useState<{ key: string; value: string; detail: string; evidence: string }[] | null>(null);
  useEffect(() => { api.scorecard(job.job_id).then((r) => setCells(r.cells)).catch(() => setCells([])); }, [job]);
  const target: Record<string, BenchScreen> = {
    "Identity": "evidence", "Runtime parameters": "params", "State schema": "params", "Class architecture": "architecture",
    "Resources": "resources", "UI": "resources", "Signal flow": "architecture", "DSP structure": "dsp",
    "DSP behavioral match": "compare", "Build readiness": "build", "State compatibility": "compare", "Repo readiness": "export",
    "Original source": "export",
  };
  return (
    <>
      <Section title="Recovery scorecard" meta="each count carries its evidence state">
        {cells === null ? <Note>Loading…</Note> : (
          <Scorecard cells={cells.map((c) => ({ key: c.key, value: c.value, detail: `${c.evidence}${c.detail ? " · " + c.detail : ""}`, onOpen: () => onScreen(target[c.key] ?? "evidence") }))} />
        )}
      </Section>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Stages">
          <div className="stages">
            {job.stages.map((s) => (
              <div key={s.stage} className="stage" data-status={s.status.toLowerCase() === "ok" ? "ok" : s.status.toLowerCase()}>
                <span className="g" aria-hidden="true">{s.status === "OK" ? "●" : s.status === "FAILED" ? "✕" : s.status === "SKIPPED" ? "–" : s.status === "RUNNING" ? "◌" : "·"}</span>
                <span className="nm">{STAGE_OF[s.stage] ?? s.stage}</span>
                <span className="dt">
                  {s.status === "SKIPPED" ? s.skip_reason : s.status === "FAILED" ? `${s.errors[0]?.code}: ${s.errors[0]?.message}` : `${s.completeness}${s.warnings.length ? ` · ${s.warnings.length} warning${s.warnings.length > 1 ? "s" : ""}` : ""}`}
                  {s.metrics && Object.keys(s.metrics).length > 0 && (
                    <span className="mono faint"> · {Object.entries(s.metrics).slice(0, 4).map(([k, v]) => `${k} ${String(v)}`).join(" · ")}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </Section>
      </div>
      <Advanced title="Job">
        <KeyValues rows={[
          ["Job id", <span className="mono" key="j">{job.job_id}</span>],
          ["Primary binary", <span className="mono" key="p">{job.primary}</span>],
          ["SHA-256", <span className="mono" key="h">{job.artifact_sha256}</span>],
          ["Project folder", <span className="mono" key="d">{job.project_dir}</span>],
          ["Usage context", `${job.usage_context} · ${job.source_availability}`],
          ["Interpretation", job.interpretation ?? "binary-derived"],
        ]} />
        <div className="row" style={{ marginTop: "var(--s4)" }}>
          <Button size="sm" onClick={() => void shell.reveal(job.project_dir)}>Show folder</Button>
        </div>
      </Advanced>
    </>
  );
}

/* ------------------------------------------------------------ evidence -- */

function EvidenceBrowser({ job }: { job: Job }) {
  const [entries, setEntries] = useState<BundleEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<{ text: string | null; schema: string | null; size: number } | null>(null);

  useEffect(() => { api.bundleTree(job.job_id).then((r) => setEntries(r.entries)).catch(() => setEntries([])); }, [job]);
  useEffect(() => {
    if (!selected) return;
    api.bundleRead(job.job_id, selected).then(setContent).catch((e) => setContent({ text: String(e), schema: null, size: 0 }));
  }, [job, selected]);

  return (
    <div className="split">
      <div className="tree">
        {entries.length === 0 && <div className="empty"><div className="d">No evidence yet</div></div>}
        {entries.map((e) => (
          <button key={e.path} type="button" className={e.kind === "dir" ? "dir" : ""} aria-current={selected === e.path ? "true" : undefined}
                  style={{ paddingLeft: `${12 + 10 * (e.path.split("/").length - 1)}px` }}
                  onClick={() => e.kind === "file" && setSelected(e.path)}>
            {e.path.split("/").pop()}
            {e.kind === "file" && <span className="sz">{bytes(e.size)}</span>}
          </button>
        ))}
      </div>
      <div className="viewer">
        <div className="head">
          <span>{selected ?? "select a file"}</span>
          {content?.schema && <span className="schema-badge">{content.schema}</span>}
          {content && <span>{bytes(content.size)}</span>}
        </div>
        <pre>{content ? (content.text ?? "(binary — open the folder to view)") : ""}</pre>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- resources -- */

interface ResourceRow {
  name: string; ext: string; status: string; semantics?: string; size: number; sha256?: string | null;
  candidate_name?: string; mapping_status?: string; dims?: string; offset: number; asset_path?: string | null;
}

function Resources({ job }: { job: Job }) {
  const [rows, setRows] = useState<ResourceRow[] | null>(null);
  useEffect(() => {
    api.bundleRead(job.job_id, "01_evidence/resources/index.json")
      .then((r) => { const doc = r.text ? JSON.parse(r.text) : null; setRows(doc?.data ?? []); })
      .catch(() => setRows([]));
  }, [job]);
  if (rows === null) return <Note>Loading…</Note>;
  if (rows.length === 0) return <Note>No carved resources. The static stage writes 01_evidence/resources/index.json.</Note>;
  return (
    <>
      <Section title="Gallery" meta="sprite sheets rendered as frame strips">
        <Gallery job={job} rows={rows} />
      </Section>
      <div style={{ marginTop: "var(--s8)" }} />
      <Section title="Carved resources" meta={`${rows.length}`}>
        <table className="grid">
          <thead><tr><th>State</th><th>Name</th><th>Size</th><th>Details</th><th>BinaryData name</th><th>Offset</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td><Ev state={r.status} /></td>
                <td className="mono">{r.name}</td>
                <td className="mono">{bytes(r.size)}</td>
                <td>{[r.dims, r.semantics].filter(Boolean).join(" · ")}</td>
                <td>{r.candidate_name ? <><span className="mono">{r.candidate_name}</span> <Ev state={(r.mapping_status ?? "UNKNOWN").split(" ")[0]} title={r.mapping_status} /></> : <span className="faint">—</span>}</td>
                <td className="mono">0x{(r.offset ?? 0).toString(16)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <div style={{ marginTop: "var(--s5)" }}>
        <Note>Names are only assigned when the mapping is content-based (font name table, singleton, or a getNamedResource decompile). Tall PNGs are SPRITE_SHEET_CANDIDATE, not corruption.</Note>
      </div>
    </>
  );
}

/** Image tiles from the project folder via the shell's sandboxed reader; tall PNGs
 *  (SPRITE_SHEET_CANDIDATE) are sliced into frames using the frame height the
 *  static stage recorded, e.g. "SPRITE_SHEET_CANDIDATE (64×100x100 or 32×100x200)". */
function Gallery({ job, rows }: { job: Job; rows: ResourceRow[] }) {
  const [urls, setUrls] = useState<Record<string, string>>({});
  const images = rows.filter((r) => (r.ext === "png" || r.ext === "jpg" || r.ext === "svg") && (r.status === "VALID_EXACT" || r.status === "PARSER_VALID"));
  useEffect(() => {
    let cancelled = false;
    const made: string[] = [];
    void (async () => {
      const next: Record<string, string> = {};
      for (const r of images) {
        const rel = `02_recovered_assets/images/${r.name}`;
        try {
          const bytes = new Uint8Array(await shell.readBundleFile(`${job.project_dir}/${rel}`, 64 * 1024 * 1024));
          const url = URL.createObjectURL(new Blob([bytes], { type: r.ext === "svg" ? "image/svg+xml" : r.ext === "jpg" ? "image/jpeg" : "image/png" }));
          made.push(url);
          next[r.name] = url;
        } catch { /* PARSER_VALID files live under 01_evidence; skip */ }
      }
      if (!cancelled) setUrls(next);
    })();
    return () => { cancelled = true; made.forEach((u) => URL.revokeObjectURL(u)); };
  }, [job, rows]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (images.length === 0) return <Note>No image resources.</Note>;
  return (
    <div className="gallery">
      {images.map((r) => {
        const frames = /SPRITE_SHEET_CANDIDATE \((\d+)×(\d+)x(\d+)/.exec(r.semantics ?? "");
        const [w, h] = (r.dims ?? "0x0").split("x").map(Number);
        const url = urls[r.name];
        return (
          <div className="tile" key={r.name} title={`${r.name} · ${r.status} · 0x${r.offset.toString(16)}`}>
            {frames && url ? (
              <div className="strip">
                {Array.from({ length: Math.min(Number(frames[1]), 24) }, (_, i) => (
                  <div key={i} style={{ width: `${(88 * w) / Number(frames[3])}px`, height: 88, backgroundImage: `url(${url})`, backgroundSize: `${(88 * w) / Number(frames[3])}px ${(88 * h) / Number(frames[3])}px`, backgroundPosition: `0 -${i * 88}px`, flex: "none" }} />
                ))}
              </div>
            ) : (
              <div className="img">{url ? <img src={url} alt="" /> : <span className="faint">…</span>}</div>
            )}
            <span className="nm">{r.candidate_name ?? r.name}</span>
            <span className="meta">{r.dims}{frames ? ` · ${frames[1]} frames` : ""} · <Ev state={r.status} /></span>
          </div>
        );
      })}
    </div>
  );
}

/* --------------------------------------------------------------- export -- */

function Export({ job }: { job: Job }) {
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.exportBundle>> | null>(null);
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (zip: boolean) => {
    setWorking(true); setErr(null);
    try { setResult(await api.exportBundle(job.job_id, zip)); } catch (e) { setErr(String((e as Error).message ?? e)); } finally { setWorking(false); }
  };
  return (
    <>
      <Section title="Export">
        <p className="copy">Materialises the recovery bundle (00_manifest … 07_agent_handoff, UNRECOVERABLE.md) as independent files under Exports/. The GIT_READY checklist runs on every export; items for later stages show as pending, never as passed.</p>
        <div className="row wrap" style={{ marginTop: "var(--s5)" }}>
          <Button variant="primary" disabled={working} onClick={() => run(false)}>Export folder</Button>
          <Button disabled={working} onClick={() => run(true)}>Export ZIP</Button>
          {result && <Button variant="quiet" onClick={() => void shell.reveal(result.out_dir)}>Show files</Button>}
          {result && <Button variant="quiet" onClick={() => void shell.openInEditor(result.out_dir)}>Open in VS Code</Button>}
        </div>
        {err && <div style={{ marginTop: "var(--s4)" }}><Note strong heading="Export failed">{err}</Note></div>}
      </Section>
      {result && (
        <div style={{ marginTop: "var(--s8)" }}>
          <Section title="GIT_READY checklist" meta={result.git_ready.ok ? "ready" : "not ready"}>
            <table className="check"><tbody>
              {result.git_ready.checks.map((c) => (
                <tr key={c.name} data-verdict={c.ok === true ? "PASS" : c.ok === false ? "FAIL" : "UNAVAILABLE"}>
                  <td className="check-verdict">{c.ok === true ? "PASS" : c.ok === false ? "FAIL" : "PENDING"}</td>
                  <td className="check-name">{c.name}</td>
                  <td className="check-detail">{c.detail}</td>
                </tr>
              ))}
            </tbody></table>
            <KeyValues rows={[["Folder", <span className="mono" key="f">{result.out_dir}</span>], ...(result.zip_path ? [["ZIP", <span className="mono" key="z">{result.zip_path}</span>] as [string, React.ReactNode]] : [])]} />
          </Section>
        </div>
      )}
    </>
  );
}

/* -------------------------------------------------------- params & state -- */

function useDoc<T>(job: Job, rel: string): T | null | undefined {
  const [doc, setDoc] = useState<T | null | undefined>(undefined);
  useEffect(() => {
    setDoc(undefined);
    api.bundleRead(job.job_id, rel).then((r) => setDoc(r.text ? (JSON.parse(r.text).data as T) : null)).catch(() => setDoc(null));
  }, [job, rel]);
  return doc;
}

interface MapRow { param_id: number | null; title: string | null; key: string | null; relationship: string; value_representation: string; tier: string; basis: string }
interface RtParam { param_id: number; title: string; units: string; step_count: number; default_normalized: number; is_bypass?: boolean; samples: { normalized: number; string: string | null }[] }

function ParamsState({ job }: { job: Job }) {
  const map = useDoc<MapRow[]>(job, "03_architecture/state_runtime_map.json");
  const params = useDoc<RtParam[]>(job, "01_evidence/vst3/runtime_parameters.json");
  const keys = useDoc<{ name: string; serialized_key_status: string; key_kind_candidate: string; observed_serialized_values: number[]; type_status: string }[]>(job, "03_architecture/serialized_keys.json");
  if (map === undefined) return <Note>Loading…</Note>;
  return (
    <>
      <Section title="Runtime parameters" meta={params ? `${params.length} · VERIFIED_RUNTIME` : "RUNTIME stage not run"}>
        {params ? (
          <table className="grid">
            <thead><tr><th>ParamID</th><th>Title</th><th>Units</th><th>Steps</th><th>Default</th><th>0 · ½ · 1</th><th>State field</th><th>Representation</th></tr></thead>
            <tbody>
              {params.map((p) => { const m = map?.find((r) => r.param_id === p.param_id); return (
                <tr key={p.param_id}>
                  <td className="mono">{p.param_id}</td><td>{p.title}{p.is_bypass ? <span className="faint"> (wrapper bypass)</span> : null}</td><td>{p.units}</td>
                  <td className="mono">{p.step_count}</td><td className="mono">{p.default_normalized.toFixed(4)}</td>
                  <td className="mono">{[0, 2, 4].map((i) => p.samples[i]?.string ?? "—").join(" · ")}</td>
                  <td className="mono">{m?.key ?? <span className="faint">—</span>} {m && <Ev state={m.relationship} />}</td>
                  <td>{m ? <Ev state={m.value_representation} /> : null}</td>
                </tr>); })}
            </tbody>
          </table>
        ) : <Note>Only vst3host can create a VST3_EXPORTED_PARAMETER. Static keys below are serialized state, not parameters.</Note>}
      </Section>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Serialized state" meta={keys ? `${keys.length} keys · representation UNKNOWN until the differential` : ""}>
          {keys && keys.length > 0 ? (
            <table className="grid">
              <thead><tr><th>Key</th><th>Status</th><th>Kind</th><th>Observed values</th><th>Tier</th></tr></thead>
              <tbody>
                {keys.map((k) => { const m = map?.find((r) => r.key === k.name); return (
                  <tr key={k.name}>
                    <td className="mono">{k.name}</td><td><Ev state={k.serialized_key_status.split(" ")[0]} title={k.serialized_key_status} /></td>
                    <td className="faint">{k.key_kind_candidate.split(" (")[0]}</td>
                    <td className="mono">{k.observed_serialized_values.slice(0, 6).join(", ")}</td>
                    <td>{m ? <span className="mono">{m.tier}</span> : <span className="faint">STATE_FIELD_CANDIDATE</span>}</td>
                  </tr>); })}
              </tbody>
            </table>
          ) : <Note>No serialized keys: no embedded preset XML. Drop presets or sessions, or run the runtime stage.</Note>}
        </Section>
      </div>
    </>
  );
}

/* ---------------------------------------------------------- architecture -- */

interface ClassRow { recovered_name: string; kind: string; role: string | null; role_status: string; name_status: string; structure_status?: string; vtables?: string[]; slot_counts?: number[]; bases?: string[]; base_status?: string }
interface FlowNode { addr: string; name: string; role: string; role_status: string; dist: number; class: string }

function Architecture({ job }: { job: Job }) {
  const classes = useDoc<ClassRow[]>(job, "03_architecture/classes.json");
  const imap = useDoc<IdentifierMap>(job, "04_reconstruction/identifier_map.json");
  const flow = useDoc<{ seed: string | null; seed_basis: string; evidence: string; nodes: FlowNode[]; edges: { from: string; to: string }[] }>(job, "03_architecture/signal_flow.json");
  const lineage = useDoc<unknown>(job, "LINEAGE_REPORT.md");
  void lineage;
  if (classes === undefined) return <Note>Loading…</Note>;
  const rows = (classes ?? []).filter((c) => c.kind === "PLUGIN_OWNED_CANDIDATE" || c.kind === "PLUGIN_OWNED");
  return (
    <>
      <Section title="Plugin-owned classes" meta={`${rows.length} · names VERIFIED_RTTI · structure ${rows.some((c) => c.structure_status === "VERIFIED_VTABLE") ? "VERIFIED_VTABLE where located" : "needs the decompiler stage"}`}>
        <table className="grid">
          <thead><tr><th>Class</th><th>Name</th><th>Structure</th><th>Vtables · slots</th><th>Bases</th><th>Role</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.recovered_name}>
                <td className="mono">{c.recovered_name}</td>
                <td><Ev state={c.name_status ?? "VERIFIED_RTTI_NAME"} /></td>
                <td><Ev state={c.structure_status ?? "UNKNOWN"} /></td>
                <td className="mono">{c.vtables?.length ? `${c.vtables.join(" ")} · ${c.slot_counts?.join("/")}` : "—"}</td>
                <td className="mono">{c.bases?.length ? c.bases.join(", ") : <span className="faint">UNKNOWN</span>}</td>
                <td>{c.role ?? "—"} {c.role && c.role !== "UNKNOWN" ? <Ev state={c.role_status ?? "CANDIDATE"} /> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Names" meta={imap ? `${imap.mode} · ${imap.identifiers.filter((r) => r.active !== r.original.split("::").pop()).length} renamed · reversible` : "RECONSTRUCT stage not run"}>
          {imap && imap.identifiers.some((r) => r.active !== r.original.split("::").pop()) ? (
            <table className="tbl">
              <thead><tr><th>active</th><th>recovered as</th><th>evidence</th><th>category</th><th>reason</th></tr></thead>
              <tbody>
                {imap.identifiers.filter((r) => r.active !== r.original.split("::").pop()).slice(0, 60).map((r) => (
                  <tr key={r.original}><td className="mono">{r.active}</td><td className="mono">{r.original}{r.original_address ? ` @ ${r.original_address}` : ""}</td><td>{r.evidence_status}</td><td>{r.category}</td><td className="faint">{r.reason}</td></tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="copy faint">{imap ? "No identifier renamed: the source uses the recovered names. Parameter ids and state keys are never renamed silently (04_reconstruction/IDENTIFIER_MAP.md)." : ""}</p>
          )}
        </Section>
        <Section title="Signal flow" meta={flow ? `${flow.evidence} · seed ${flow.seed_basis}` : "DECOMPILE stage not run"}>
          {flow && flow.nodes.length > 0 ? (
            <div className="stages">
              {flow.nodes.map((n) => (
                <div key={n.addr} className="stage" data-status="ok">
                  <span className="g mono">{n.dist}</span>
                  <span className="nm mono">{n.addr}</span>
                  <span className="dt">{n.role} <Ev state={n.role_status} /> · {n.class || "—"} · <span className="mono">{n.name}</span></span>
                </div>
              ))}
            </div>
          ) : <Note>processBlock-reachable DSP functions appear here after the Ghidra callgraph export.</Note>}
        </Section>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- dsp -- */

interface DspRow { addr: string; name: string; class: string; role: string; role_status: string; role_basis: string[]; priority: number; dist_from_processBlock: number; file?: string | null; vtable_slot: number; param_refs: number }

function Dsp({ job }: { job: Job }) {
  const cands = useDoc<DspRow[]>(job, "01_evidence/decompiler/dsp_candidates.json");
  const recon = useDoc<{ symbol: string; file: string; status: string; role?: string; validation?: string; rmse?: number }[]>(job, "07_agent_handoff/reconstruction_index.json");
  if (cands === undefined) return <Note>Loading…</Note>;
  return (
    <>
      <Section title="DSP candidates" meta={cands ? `${cands.length} · priority = reachability × plugin-specific × parameter refs × DSP evidence` : "DECOMPILE stage not run"}>
        {cands && cands.length > 0 ? (
          <table className="grid">
            <thead><tr><th>#</th><th>Priority</th><th>Role</th><th>Dist</th><th>Class</th><th>Function</th><th>Basis</th></tr></thead>
            <tbody>
              {cands.slice(0, 60).map((c, i) => (
                <tr key={c.addr}>
                  <td className="mono">{i + 1}</td><td className="mono">{c.priority}</td>
                  <td>{c.role} <Ev state={c.role_status} /></td><td className="mono">{c.dist_from_processBlock}</td>
                  <td className="mono">{c.class || "—"}</td><td className="mono">{c.name} <span className="faint">@{c.addr}</span></td>
                  <td className="faint">{c.role_basis.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Note>Ranked processing functions appear here after the decompiler stage; roles stay CANDIDATE until the callgraph confirms them.</Note>}
      </Section>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Reconstructed modules" meta={recon ? `${recon.length}` : ""}>
          {recon && recon.length > 0 ? (
            <table className="grid">
              <thead><tr><th>Symbol</th><th>Status</th><th>Validation</th><th>File</th></tr></thead>
              <tbody>
                {recon.map((r) => (
                  <tr key={r.symbol}><td className="mono">{r.symbol}</td><td><Ev state={r.status} /></td><td>{r.validation ? <Ev state={r.validation} /> : <span className="faint">—</span>}{r.rmse != null ? <span className="mono faint"> rmse {r.rmse}</span> : null}</td><td className="mono faint">{r.file}</td></tr>
                ))}
              </tbody>
            </table>
          ) : <Note>SCAFFOLD_ONLY → STATIC_RECONSTRUCTED → BEHAVIOR_MATCHED → ACTIVE (Phase 4).</Note>}
        </Section>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- build -- */

type BuildReport = {
  build_kind: string; status: string; generator?: string; juce_dir?: string; installed?: string;
  configure?: { ok: boolean; elapsed_ms: number; errors: string[]; log?: string };
  build?: { ok: boolean; elapsed_ms: number; errors: string[]; warnings?: number; log?: string };
  binary?: { path: string; sha256: string; size: number };
};
type PluginvalReport = { status: string; strictness?: number; version?: string; failures?: string[]; tests_run?: number; reason?: string; log?: string; gui_tests?: string };
type ReconModel = { build_kind: string; target?: string; identity: { verified: boolean; codes_status?: string; manufacturer_code?: string; plugin_code?: string; product?: string; fidelity_refused?: string };
  modules: { name: string; family: string; rmse: number; active: boolean; classification_at_default: string; modulation: { key: string; law: string; knob: string; status: string; basis: string }[] }[];
  parameters: { key?: string; kind: string; id_status?: string; range_status?: string; generate?: boolean; title?: string }[] };

function Build({ job }: { job: Job }) {
  const rep = useDoc<BuildReport>(job, "06_validation/build_report.json");
  const pv = useDoc<PluginvalReport>(job, "06_validation/pluginval.json");
  const model = useDoc<ReconModel>(job, "04_reconstruction/reconstruction_model.json");
  const rec = job.stages.find((s) => STAGE_OF[s.stage] === "BUILD");
  if (rep === undefined || model === undefined) return <Note>Loading…</Note>;
  const kindState = model?.build_kind === "FIDELITY" ? "VERIFIED_RUNTIME" : "GENERATED";
  return (
    <>
      <Section title="Reconstruction" meta={model ? `${model.target ?? ""} · ${model.build_kind}` : "RECONSTRUCT stage not run"}>
        {model ? (
          <KeyValues rows={[
            ["Build kind", <><Ev state={kindState} title={model.build_kind} /> {model.build_kind === "SURROGATE" ? "temporary identity — never session-compatible" : "original identity"}</>],
            ["Identity", <>{model.identity.manufacturer_code ?? "—"}/{model.identity.plugin_code ?? "—"} <span className="faint">{model.identity.codes_status ?? ""}</span>{model.identity.fidelity_refused ? <div className="faint">{model.identity.fidelity_refused}</div> : null}</>],
            ["Parameters", `${model.parameters.filter((p) => p.generate).length} generated (${model.parameters.filter((p) => p.generate && (p.id_status ?? "").startsWith("VERIFIED")).length} ids VERIFIED_RUNTIME)`],
            ["Modules", model.modules.length ? model.modules.map((m) => `${m.name}: ${m.family} · rmse ${m.rmse.toExponential(2)} · ${m.active ? "Source/Active" : "human_source only"}`).join("; ") : "none fitted"],
          ]} />
        ) : <Note>Run the RECONSTRUCT stage to derive Source/Active from the evidence; only VERIFIED_RUNTIME parameters and BEHAVIOR_MATCHED modules are compiled.</Note>}
        {model?.modules.map((m) => (
          <table className="grid" key={m.name} style={{ marginTop: "var(--s4)" }}>
            <thead><tr><th>Parameter</th><th>Law</th><th>Knob</th><th>Status</th><th>Basis</th></tr></thead>
            <tbody>
              {m.modulation.map((mo) => (
                <tr key={mo.key}><td className="mono">{mo.key}</td><td>{mo.law}</td><td className="mono">{mo.knob}</td><td><Ev state={mo.status} /></td><td className="faint">{mo.basis}</td></tr>
              ))}
            </tbody>
          </table>
        ))}
      </Section>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Build" meta={rep ? `${rep.status} · ${rep.generator ?? ""}` : rec ? `${rec.status}${rec.skip_reason ? ` — ${rec.skip_reason}` : ""}` : "not run"}>
          {rep ? (
            <KeyValues rows={[
              ["Status", <Ev state={rep.status === "BUILT" ? "VERIFIED_RUNTIME" : "FAILED"} title={rep.status} />],
              ["Configure", rep.configure ? `${rep.configure.ok ? "ok" : "failed"} · ${ms(rep.configure.elapsed_ms)}` : "—"],
              ["Compile + link", rep.build ? `${rep.build.ok ? "ok" : "failed"} · ${ms(rep.build.elapsed_ms)} · ${rep.build.warnings ?? 0} warnings` : "—"],
              ["JUCE", rep.juce_dir ?? "—"],
              ["Bundle", rep.installed ? <span className="mono">{rep.installed}{rep.binary ? ` · ${bytes(rep.binary.size)} · ${shortHash(rep.binary.sha256)}` : ""}</span> : "—"],
            ]} />
          ) : <Note>CMake + compiler build of 04_reconstruction runs in an isolated worker; a missing CMake, compiler or JUCE is reported here with setup instructions, never faked.</Note>}
          {rep && (rep.build?.errors?.length || rep.configure?.errors?.length) ? (
            <Advanced title="Errors"><pre className="mono">{[...(rep.configure?.errors ?? []), ...(rep.build?.errors ?? [])].join("\n")}</pre></Advanced>
          ) : null}
        </Section>
      </div>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="pluginval" meta={pv ? `${pv.status}${pv.strictness ? ` · strictness ${pv.strictness}` : ""}` : "not run"}>
          {pv ? (
            <KeyValues rows={[
              ["Result", <Ev state={pv.status === "PASSED" ? "VERIFIED_RUNTIME" : pv.status === "NOT_RUN" ? "UNKNOWN" : "FAILED"} title={pv.status} />],
              ["Tests", pv.tests_run != null ? `${pv.tests_run} · ${pv.gui_tests ?? ""}` : pv.reason ?? "—"],
              ["Version", pv.version ?? "—"],
            ]} />
          ) : <Note>pluginval (strictness ≥ 5) runs on the rebuilt bundle when installed (Settings → Tools).</Note>}
          {pv?.failures?.length ? <Advanced title="Failures"><pre className="mono">{pv.failures.join("\n")}</pre></Advanced> : null}
        </Section>
      </div>
    </>
  );
}

/* -------------------------------------------------------------- compare -- */

type DiffModule = { module: string; role: string; classification: string; renders: number; worst_rmse: number | null; worst_spectrum_diff_db: number | null; worst_lead_in_rmse?: number | null; failing: string[]; latency_delta?: number[] };
type DiffRender = { id: string; probe: string; sr: number; block: number; classification: string; rmse?: number | null; max_error?: number | null; spectrum_diff_db?: number | null; latency_delta?: number; lead_in_rmse?: number | null; kept?: string; error?: string };
type DiffResults = { overall: string; cross_load: string; modules: DiffModule[]; renders: DiffRender[]; thresholds?: Record<string, string> };
type CrossLoad = { classification: string; reason?: string; original_to_rebuild?: { ok: boolean; mismatches: { key: string; issue: string }[] }; rebuild_to_original?: { ok: boolean; mismatches: { key: string; issue: string }[] } };

function Compare({ job }: { job: Job }) {
  const diff = useDoc<DiffResults>(job, "06_validation/differential_results.json");
  const cross = useDoc<CrossLoad>(job, "06_validation/cross_load.json");
  const [filter, setFilter] = useState<string>("all");
  const rec = job.stages.find((s) => STAGE_OF[s.stage] === "COMPARE");
  if (diff === undefined) return <Note>Loading…</Note>;
  if (!diff) {
    return (
      <div className="empty">
        <div className="t">Compare</div>
        <div className="d">The differential harness replays every recorded probe on the rebuild and classifies each module BIT_EXACT → FAILED. {rec ? `Current state: ${rec.status}${rec.skip_reason ? ` (${rec.skip_reason})` : ""}.` : "Not run yet."}</div>
      </div>
    );
  }
  const renders = diff.renders.filter((r) => filter === "all" || r.classification === filter || (filter === "notok" && !["BIT_EXACT", "NUMERICALLY_EQUIVALENT", "BEHAVIORALLY_EQUIVALENT"].includes(r.classification)));
  const cells = [
    { key: "Overall", value: diff.overall, detail: "worst module" },
    { key: "Waveshaper (default)", value: diff.modules.find((m) => m.module === "Waveshaper")?.classification ?? "—", detail: "EXECUTE 4.3 gate" },
    { key: "Sweeps", value: diff.modules.find((m) => m.module === "WaveshaperSweeps")?.classification ?? "—", detail: "one parameter at a time" },
    { key: "State cross-load", value: diff.cross_load, detail: "both directions" },
    { key: "Renders", value: String(diff.renders.length), detail: "identical probes + state" },
  ];
  return (
    <>
      <Scorecard cells={cells} />
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Per module" meta="worst render decides; ramp renders are judged on the measurement window after the settle lead-in (D-018)">
          <table className="grid">
            <thead><tr><th>Module</th><th>Role</th><th>Class</th><th>Renders</th><th>Worst RMSE</th><th>Worst Δspectrum</th><th>Lead-in RMSE</th><th>Failing</th></tr></thead>
            <tbody>
              {diff.modules.map((m) => (
                <tr key={m.module}>
                  <td className="mono">{m.module}</td><td>{m.role}</td><td><Ev state={m.classification} /></td><td className="mono">{m.renders}</td>
                  <td className="mono">{m.worst_rmse == null ? "—" : m.worst_rmse.toExponential(2)}</td>
                  <td className="mono">{m.worst_spectrum_diff_db == null ? "—" : `${m.worst_spectrum_diff_db.toFixed(3)} dB`}</td>
                  <td className="mono">{m.worst_lead_in_rmse == null ? "—" : m.worst_lead_in_rmse.toExponential(2)}</td>
                  <td className="faint mono">{m.failing.slice(0, 4).join(", ")}{m.failing.length > 4 ? ` +${m.failing.length - 4}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="State cross-load" meta={cross?.classification ?? diff.cross_load}>
          {cross ? (
            <KeyValues rows={[
              ["Verdict", <Ev state={cross.classification === "CROSS_LOAD_VALIDATED" ? "VERIFIED_RUNTIME" : cross.classification} title={cross.classification} />],
              ["Original → rebuild", cross.original_to_rebuild ? (cross.original_to_rebuild.ok ? "every exported parameter survives" : cross.original_to_rebuild.mismatches.map((x) => `${x.key}: ${x.issue}`).join("; ")) : cross.reason ?? "—"],
              ["Rebuild → original", cross.rebuild_to_original ? (cross.rebuild_to_original.ok ? "every exported parameter survives" : cross.rebuild_to_original.mismatches.map((x) => `${x.key}: ${x.issue}`).join("; ")) : "—"],
            ]} />
          ) : <Note>Not measured.</Note>}
        </Section>
      </div>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Renders" meta={`${renders.length} of ${diff.renders.length}`}>
          <div className="row" style={{ marginBottom: "var(--s4)" }}>
            {["all", "notok", "BEHAVIORALLY_EQUIVALENT", "PERCEPTUALLY_CLOSE", "FAILED"].map((f) => (
              <Button key={f} variant={filter === f ? "primary" : "quiet"} size="sm" onClick={() => setFilter(f)}>{f === "notok" ? "not ≥ equivalent" : f}</Button>
            ))}
          </div>
          <table className="grid">
            <thead><tr><th>Render</th><th>Probe</th><th>Rate/block</th><th>Class</th><th>RMSE</th><th>Max</th><th>Δspectrum</th><th>Δlatency</th><th>Lead-in</th></tr></thead>
            <tbody>
              {renders.slice(0, 200).map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.id}{r.kept ? <span className="faint"> · kept</span> : null}</td><td>{r.probe}</td><td className="mono">{r.sr}/{r.block}</td>
                  <td><Ev state={r.classification} />{r.error ? <span className="faint"> {r.error}</span> : null}</td>
                  <td className="mono">{r.rmse == null ? "—" : r.rmse.toExponential(2)}</td><td className="mono">{r.max_error == null ? "—" : r.max_error.toExponential(2)}</td>
                  <td className="mono">{r.spectrum_diff_db == null ? "—" : r.spectrum_diff_db.toFixed(3)}</td><td className="mono">{r.latency_delta ?? "—"}</td>
                  <td className="mono">{r.lead_in_rmse == null ? "—" : r.lead_in_rmse.toExponential(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>
    </>
  );
}
