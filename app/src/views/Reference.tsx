import { useEffect, useState } from "react";
import type { GroundTruthDashboard, ProvenanceHit, ReferenceEntry, ReferenceEntryType, ReferenceLibrary } from "../lib/types";
import { CONTEXT_LABEL, REFERENCE_TYPE_LABEL } from "../lib/types";
import { api } from "../lib/api";
import { Button, Empty, Ev, KeyValues, Note, Readout, Section } from "../components/ui";
import { shortHash, when } from "../lib/format";

/** Reference Library (ADDENDUM B6) — restrained. Every entry answers "where did AB learn this?": origin, source
 *  artifact, licence, hash, analysis version, evidence state, verification date, relationships. Actions are
 *  explicit buttons; dropping two plugins next to each other never implies a comparison or a fixture. */
const ORDER: ReferenceEntryType[] = ["KNOWN_SOURCE_FIXTURE", "BLACK_BOX_REFERENCE", "USER_ARTIFACT", "FRAMEWORK_REFERENCE", "DSP_REFERENCE"];

function evidenceText(e: ReferenceEntry): string {
  const ev = e.evidence_state;
  if (typeof ev === "string") return ev;
  const done = Object.entries(ev).filter(([, v]) => v === "OK").map(([k]) => k.replace(/_COMPLETE$/, ""));
  return done.length ? done.join(" · ") : Object.entries(ev).map(([k, v]) => `${k} ${v}`).join(" · ") || "—";
}

function Count({ c }: { c: { n: number | null; of: number | null } | null }) {
  return <span className="mono">{c && c.n !== null ? `${c.n}/${c.of}` : "—"}</span>;
}

function Dashboard({ d }: { d: GroundTruthDashboard }) {
  return (
    <KeyValues rows={[
      ["parameter recall", <Count c={d.parameter_recall} />],
      ["state mapping", <Count c={d.state_mapping} />],
      ["classes", <Count c={d.classes} />],
      ["DSP entry points", <Count c={d.dsp_entry_points} />],
      ["resources", <Count c={d.resources} />],
      ["implementation matches", <span className="mono">{d.implementation_matches_verified} verified</span>],
      ["false positives / negatives", <span className="mono">{d.false_positives} / {d.false_negatives}</span>],
      ["behavioral RMSE", <span className="mono">{d.behavioral_rmse === null ? "—" : `${d.behavioral_rmse.toExponential(2)} (${d.behavioral_classification ?? ""})`}</span>],
      ["gates", <span className="mono">{d.gates.ok} ok · {d.gates.failed} failed · {d.gates.pending} pending</span>],
    ]} />
  );
}

export function Reference({ onOpen, onChanged }: { onOpen: (jobId: string) => void; onChanged: () => void }) {
  const [lib, setLib] = useState<ReferenceLibrary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [dash, setDash] = useState<Record<string, GroundTruthDashboard | string>>({});
  const [lineage, setLineage] = useState<{ id: string; report: string } | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<ProvenanceHit[] | null>(null);

  async function load() {
    setBusy(true); setError(null);
    try { setLib(await api.referenceList()); } catch (e) { setError(String((e as Error).message ?? e)); } finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, []);

  async function act(e: ReferenceEntry, id: string) {
    if (!e.id) return;
    setBusy(true); setError(null);
    try {
      if (id === "ADD_AS_FIXTURE") { await api.referenceSetContext(e.id, "KNOWN_SOURCE_FIXTURE", "SOURCE_AVAILABLE"); onChanged(); await load(); }
      else if (id === "USE_AS_BLACK_BOX_REFERENCE") { await api.referenceSetContext(e.id, "BLACK_BOX_REFERENCE"); onChanged(); await load(); }
      else if (id === "COMPARE_AGAINST_REFERENCE") { const r = await api.lineage(e.id); setLineage({ id: e.id, report: r.report }); }
      else if (id === "VALIDATE_RECOVERY_AGAINST_SOURCE") {
        await api.groundTruth(e.id, 4);
        const r = await api.referenceDashboard(e.id);
        setDash((d) => ({ ...d, [e.id]: r.dashboard ?? (r.note ?? "no report") }));
        await load();
      }
    } catch (err) { setError(String((err as Error).message ?? err)); } finally { setBusy(false); }
  }

  async function showDashboard(e: ReferenceEntry) {
    setBusy(true);
    try { const r = await api.referenceDashboard(e.id); setDash((d) => ({ ...d, [e.id]: r.dashboard ?? (r.note ?? "no report") })); }
    catch (err) { setError(String((err as Error).message ?? err)); } finally { setBusy(false); }
  }

  async function search() {
    if (!query.trim()) { setHits(null); return; }
    setBusy(true);
    try { setHits((await api.referenceProvenance(query)).hits); } catch (err) { setError(String((err as Error).message ?? err)); } finally { setBusy(false); }
  }

  if (!lib) {
    return (
      <div className="view wide enter">
        <div className="label">Reference Library</div>
        {error ? <Note strong heading="Reference">{error}</Note> : <Empty title={busy ? "Reading the library…" : "Nothing to show"} detail="Entries appear as artifacts are recovered and as knowledge is learned." />}
      </div>
    );
  }

  return (
    <div className="view wide enter">
      <div className="row" style={{ alignItems: "baseline" }}>
        <div className="label">Reference Library</div>
        <span className="grow" />
        <Button size="sm" variant="quiet" disabled={busy} onClick={load}>Refresh</Button>
      </div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>{lib.entries.length} entries</h1>
      {error ? <div style={{ marginTop: "var(--s4)" }}><Note strong heading="Reference">{error}</Note></div> : null}
      <div style={{ marginTop: "var(--s6)" }}>
        <Readout items={ORDER.map((t) => ({ value: String(lib.counts[t] ?? 0), caption: REFERENCE_TYPE_LABEL[t] }))} />
      </div>
      <div style={{ marginTop: "var(--s4)" }}>
        <Note strong={!lib.isolation.ok} heading={lib.isolation.ok ? "Fixture source isolated" : "Fixture source leaked"}>
          {lib.isolation.checked_projects} user / black-box project{lib.isolation.checked_projects === 1 ? "" : "s"} checked against {lib.isolation.fixture_files} fixture source files
          {lib.isolation.violations.length ? ` — ${lib.isolation.violations.map((v) => `${v.job_id}: ${v.file}`).join("; ")}` : "; nothing copied."}
        </Note>
      </div>

      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Where did AB learn this?" meta="function · class · vtable layout · implementation">
          <div className="row">
            <input className="input grow" value={query} placeholder="name, fingerprint id, RTTI name…" onChange={(ev) => setQuery(ev.target.value)} onKeyDown={(ev) => { if (ev.key === "Enter") void search(); }} />
            <Button size="sm" disabled={busy} onClick={search}>Ask</Button>
          </div>
          {hits === null ? null : hits.length === 0 ? <Note>No knowledge entry matches. AB has not learned this from any artifact.</Note> : (
            <table className="grid" style={{ marginTop: "var(--s4)" }}>
              <thead><tr><th>Entry</th><th>Kind</th><th>State</th><th>Learned from</th><th>Verified</th></tr></thead>
              <tbody>
                {hits.map((h) => (
                  <tr key={h.entity_type + h.entity_id}>
                    <td className="truncate" title={h.entity_id}>{h.name ?? h.entity_id}</td>
                    <td>{h.entity_type}{h.kind ? ` · ${h.kind}` : ""}</td>
                    <td><Ev state={h.state ?? "UNKNOWN"} /> {h.state}</td>
                    <td>{h.learned_from.length ? h.learned_from.map((a) => `${a.name ?? shortHash(a.sha256)} (${REFERENCE_TYPE_LABEL[a.entry_type]})`).join(", ") : "—"}</td>
                    <td>{h.last_verified ? when(h.last_verified) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      </div>

      {ORDER.map((t) => {
        const rows = lib.entries.filter((e) => e.entry_type === t);
        return (
          <div key={t} style={{ marginTop: "var(--s8)" }}>
            <Section title={REFERENCE_TYPE_LABEL[t]} meta={`${rows.length}`}>
              {rows.length === 0 ? <Note>None yet.</Note> : rows.map((e) => {
                const isOpen = open === e.id;
                const d = dash[e.id];
                return (
                  <div key={e.id} className="stack" style={{ padding: "var(--s3) 0", borderBottom: "1px solid var(--line)" }}>
                    <div className="row" style={{ alignItems: "baseline" }}>
                      {e.project_dir
                        ? <button type="button" className="truncate" style={{ textAlign: "left", background: "none", border: 0, color: "inherit", cursor: "pointer", font: "inherit" }} onClick={() => onOpen(e.id)}>{e.name}</button>
                        : <span className="truncate">{e.name}</span>}
                      <span className="faint">{e.usage_context ? CONTEXT_LABEL[e.usage_context] : e.purpose ?? e.kind ?? ""}</span>
                      <span className="grow" />
                      <span className="faint mono">{e.hash ? shortHash(e.hash) : ""}</span>
                      <Button size="sm" variant="quiet" onClick={() => setOpen(isOpen ? null : e.id)}>{isOpen ? "Less" : "Details"}</Button>
                    </div>
                    {isOpen ? (
                      <>
                        <KeyValues rows={[
                          ["origin", e.origin],
                          ["licence", e.license ? `${e.license.class ?? "—"}${e.license.text ? ` — ${e.license.text}` : ""}` : "—"],
                          ["evidence", evidenceText(e)],
                          ["verified", e.verification_date ? when(e.verification_date) : "—"],
                          ["analysis version", Object.entries(e.analysis_version ?? {}).map(([k, v]) => `${k} ${v ?? ""}`).join(" · ") || "—"],
                          ["relationships", e.relationships.length ? e.relationships.map((r) => r.count !== undefined ? `${r.kind} ×${r.count}` : `${r.kind} ${r.a ?? ""}→${r.b ?? ""}`).join(" · ") : "—"],
                          ...(e.knowledge_learned && Object.keys(e.knowledge_learned).length ? [["knowledge learned from it", Object.entries(e.knowledge_learned).map(([k, v]) => `${v} ${k}`).join(" · ")] as [string, string]] : []),
                          ...(e.fixture ? [
                            ["fixture", e.fixture.fixture_id ?? e.fixture.note ?? "—"] as [string, string],
                            ["source", `${e.fixture.source_type ?? ""} ${e.fixture.source_repository ? `· ${e.fixture.source_repository}` : ""} ${e.fixture.source_commit ? `@ ${e.fixture.source_commit}` : ""}`.trim() || "—"] as [string, string],
                            ["build", `${e.fixture.variant ? `${e.fixture.variant} · ` : ""}${e.fixture.build_configuration ?? ""} ${e.fixture.compiler ? `· ${e.fixture.compiler}` : ""}`.trim() || "—"] as [string, string],
                            ["algorithms", (e.fixture.algorithms ?? []).join(", ") || "— (not declared)"] as [string, string],
                          ] : []),
                          ...(e.verification ? [["verification", [
                            e.verification.ground_truth ? `ground truth ${e.verification.ground_truth.gates_ok}/${e.verification.ground_truth.gates} gates, ${e.verification.ground_truth.false_positives} FP / ${e.verification.ground_truth.false_negatives} FN` : null,
                            e.verification.known_source ? `known-source integrity ${e.verification.known_source.integrity_ok ? "ok" : "not ok"}` : null,
                            e.verification.behavioral ? Object.entries(e.verification.behavioral).map(([m, c]) => `${m} ${c}`).join(", ") : null,
                          ].filter(Boolean).join(" · ") || "not validated yet"] as [string, string]] : []),
                        ]} />
                        {e.actions.length ? (
                          <div className="row" style={{ gap: "var(--s2)", flexWrap: "wrap" }}>
                            {e.actions.map((a) => <Button key={a.id} size="sm" variant="quiet" disabled={busy} title={a.needs} onClick={() => act(e, a.id)}>{a.label}</Button>)}
                            {e.verification?.ground_truth ? <Button size="sm" variant="quiet" disabled={busy} onClick={() => showDashboard(e)}>Ground-truth dashboard</Button> : null}
                          </div>
                        ) : null}
                        {d ? (typeof d === "string" ? <Note>{d}</Note> : <Dashboard d={d} />) : null}
                        {lineage && lineage.id === e.id ? (
                          <details open><summary className="faint">LINEAGE_REPORT.md</summary><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{lineage.report}</pre></details>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                );
              })}
            </Section>
          </div>
        );
      })}
      <div style={{ marginTop: "var(--s6)" }}><Note>{lib.rule}</Note></div>
    </div>
  );
}
