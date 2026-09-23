import { useEffect, useMemo, useState } from "react";
import type { BundleEntry, Job, ProgressEvent, StageKey } from "../lib/types";
import { STAGE_KEYS, STAGE_OF } from "../lib/types";
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
        <span className="mono faint">{job.ownership.toLowerCase().replace("_", "-")} · {shortHash(job.artifact_sha256)}</span>
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
        {(screen === "params" || screen === "architecture" || screen === "dsp" || screen === "compare" || screen === "build") && (
          <Pending screen={screen} job={job} />
        )}
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
          ["Ownership", job.ownership],
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

/* -------------------------------------------------------------- pending -- */

function Pending({ screen, job }: { screen: BenchScreen; job: Job }) {
  const meta = SCREENS.find((s) => s.key === screen)!;
  const rec = job.stages.find((s) => STAGE_OF[s.stage] === meta.stage);
  return (
    <div className="empty">
      <div className="t">{meta.label}</div>
      <div className="d">
        Populated by the {meta.stage} stage — {meta.phase}.
        {rec ? ` Current state: ${rec.status}${rec.skip_reason ? ` (${rec.skip_reason})` : ""}.` : " Not run yet."}
      </div>
    </div>
  );
}
