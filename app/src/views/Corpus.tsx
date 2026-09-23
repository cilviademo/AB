import type { Job } from "../lib/types";
import { Empty, Section } from "../components/ui";
import { shortHash, when } from "../lib/format";

/** Corpus Bench — multi-plugin lineage and signature analysis (SPEC §9).
 *  Cross-plugin views never merge evidence into a single plugin's package. */
export function Corpus({ jobs, onOpen }: { jobs: Job[]; onOpen: (jobId: string) => void }) {
  if (jobs.length === 0) {
    return (
      <div className="view wide enter">
        <div className="label">Corpus Bench</div>
        <Empty title="No plugins on the bench yet" detail="Recover two or more plugins to compare class-name sets, shared resources, state schemas and (from Phase 3) implementation fingerprints." />
      </div>
    );
  }
  return (
    <div className="view wide enter">
      <div className="label">Corpus Bench</div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>{jobs.length} plugin{jobs.length === 1 ? "" : "s"}</h1>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Plugins">
          <div className="data-head" style={{ gridTemplateColumns: "1fr 120px 140px 110px" }}>
            <span>Plugin</span><span>Ownership</span><span>SHA-256</span><span>Added</span>
          </div>
          {jobs.map((j) => (
            <button key={j.job_id} className="data-row" style={{ gridTemplateColumns: "1fr 120px 140px 110px" }} type="button" onClick={() => onOpen(j.job_id)}>
              <span className="truncate">{j.name}</span>
              <span className="c">{j.ownership.toLowerCase().replace("_", "-")}</span>
              <span className="c mono">{shortHash(j.artifact_sha256)}</span>
              <span className="c">{when(j.created)}</span>
            </button>
          ))}
        </Section>
      </div>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Lineage" meta="INFERRED_CODEBASE_FAMILY">
          <div className="empty"><div className="d">Family clustering (class-name-set Jaccard, shared resources, state schema) and the known-library cache arrive with Phase 3; the corpus report from Static Recovery v2 is produced when two or more plugins are ingested together.</div></div>
        </Section>
      </div>
    </div>
  );
}
