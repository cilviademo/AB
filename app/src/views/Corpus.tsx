import { useState } from "react";
import type { Job } from "../lib/types";
import { CONTEXT_LABEL } from "../lib/types";
import { api, type LineageReport } from "../lib/api";
import { Button, Empty, Ev, Note, Section } from "../components/ui";
import { shortHash, when } from "../lib/format";

/** Corpus Bench — multi-plugin lineage and signature analysis (SPEC §9).
 *  Cross-plugin views never merge evidence into a single plugin's package: every family is
 *  INFERRED_CODEBASE_FAMILY until implementation fingerprints (Phase 3) reinforce it. */
export function Corpus({ jobs, onOpen }: { jobs: Job[]; onOpen: (jobId: string) => void }) {
  const [target, setTarget] = useState<string | null>(null);
  const [report, setReport] = useState<LineageReport | null>(null);
  const [corpus, setCorpus] = useState<{ plugins: number; report: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const names = new Map(jobs.map((j) => [j.job_id, j.name]));

  async function lineage(jobId: string) {
    setBusy(true); setError(null); setTarget(jobId);
    try { setReport(await api.lineage(jobId)); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function runCorpus() {
    setBusy(true); setError(null);
    try { setCorpus(await api.corpusRun()); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  if (jobs.length === 0) {
    return (
      <div className="view wide enter">
        <div className="label">Corpus Bench</div>
        <Empty title="No plugins on the bench yet" detail="Recover two or more plugins to compare class-name sets, shared resources, state schemas and implementation fingerprints." />
      </div>
    );
  }
  return (
    <div className="view wide enter">
      <div className="row" style={{ alignItems: "baseline" }}>
        <div className="label">Corpus Bench</div>
        <span className="grow" />
        <Button size="sm" variant="quiet" disabled={busy || jobs.length < 2} onClick={runCorpus} title={jobs.length < 2 ? "needs two or more plugins analysed by the static host" : ""}>Run corpus report (v2)</Button>
      </div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>{jobs.length} plugin{jobs.length === 1 ? "" : "s"}</h1>
      {error ? <div style={{ marginTop: "var(--s4)" }}><Note strong heading="Corpus">{error}</Note></div> : null}
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Plugins" meta="pick one to compute its lineage against the rest">
          <div className="data-head" style={{ gridTemplateColumns: "1fr 120px 140px 110px 100px" }}>
            <span>Plugin</span><span>Context</span><span>SHA-256</span><span>Added</span><span></span>
          </div>
          {jobs.map((j) => (
            <div key={j.job_id} className="data-row" style={{ gridTemplateColumns: "1fr 120px 140px 110px 100px" }}>
              <button type="button" className="truncate" style={{ textAlign: "left", background: "none", border: 0, color: "inherit", cursor: "pointer" }} onClick={() => onOpen(j.job_id)}>{j.name}</button>
              <span className="c">{CONTEXT_LABEL[j.usage_context] ?? j.usage_context}</span>
              <span className="c mono">{shortHash(j.artifact_sha256)}</span>
              <span className="c">{when(j.created)}</span>
              <span className="c"><Button size="sm" variant={target === j.job_id ? "primary" : "quiet"} disabled={busy} onClick={() => lineage(j.job_id)}>Lineage</Button></span>
            </div>
          ))}
        </Section>
      </div>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Lineage" meta={report ? `${names.get(target ?? "") ?? ""} · ${report.families.length} famil${report.families.length === 1 ? "y" : "ies"}` : "INFERRED_CODEBASE_FAMILY"}>
          {!report ? (
            <Note>Class-name-set Jaccard (connected components ≥ 0.5, medoid + average link), shared resources by hash, state-schema overlap and known-library fingerprint matches. Families are INFERRED until implementation fingerprints reinforce them.</Note>
          ) : (
            <>
              {report.families.length > 0 ? (
                <table className="grid">
                  <thead><tr><th>Family</th><th>Members</th><th>Medoid</th><th>Average link</th></tr></thead>
                  <tbody>
                    {report.families.map((f, i) => (
                      <tr key={i}><td><Ev state="INFERRED" title="INFERRED_CODEBASE_FAMILY" /> #{i + 1} ({f.size})</td>
                        <td>{f.members.map((m) => names.get(m) ?? m).join(", ")}</td><td>{names.get(f.medoid) ?? f.medoid}</td><td className="mono">{f.average_link}</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : <Note>No family inferred: single plugin or no shared owned class names.</Note>}
              {report.pairs.length > 0 ? (
                <table className="grid" style={{ marginTop: "var(--s4)" }}>
                  <thead><tr><th>Pair</th><th>Class-name Jaccard</th></tr></thead>
                  <tbody>
                    {report.pairs.slice(0, 12).map((p) => (
                      <tr key={p[0] + p[1]}><td>{names.get(p[0]) ?? p[0]} · {names.get(p[1]) ?? p[1]}</td><td className="mono">{p[2]}</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
              <details style={{ marginTop: "var(--s4)" }}>
                <summary className="faint">LINEAGE_REPORT.md</summary>
                <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{report.report}</pre>
              </details>
            </>
          )}
        </Section>
      </div>
      {corpus ? (
        <div style={{ marginTop: "var(--s8)" }}>
          <Section title="Corpus report (Static Recovery v2, frozen)" meta={`${corpus.plugins} plugins`}>
            <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{corpus.report || "(empty)"}</pre>
          </Section>
        </div>
      ) : null}
    </div>
  );
}
