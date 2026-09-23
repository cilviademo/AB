import { useCallback, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import type { Job, Ownership } from "../lib/types";
import { Button, Note, Segmented } from "../components/ui";
import { shortHash, when } from "../lib/format";

const Glyph = () => (
  <svg className="glyph" viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M16 4v18m0 0-6-6m6 6 6-6" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const KIND_RX: [RegExp, string][] = [
  [/\.(vst3|dll|vst|component|dylib)$/i, "binary"],
  [/\.(vstpreset|fxp|fxb|aupreset)$/i, "preset"],
  [/\.(rpp|als|flp|cpr|logicx|ptx|song)$/i, "session"],
  [/\.(pdb|map)$/i, "symbols"],
  [/\.(cpp|cc|cxx|c|h|hpp|hh|mm|jucer|cmake)$|CMakeLists\.txt$/i, "source"],
  [/\.(png|jpg|jpeg|svg|ttf|otf|wav|aiff|xml|json)$/i, "asset"],
  [/\.zip$/i, "archive"],
];

function kindOf(path: string): string {
  const name = path.split(/[\\/]/).pop() ?? path;
  for (const [rx, k] of KIND_RX) if (rx.test(name)) return k;
  return /\.[A-Za-z0-9]{1,5}$/.test(name) ? "file" : "folder";
}

/** Recover Project — the primary screen (AB_BRIEF "Main UI", SPEC §14.1). */
export function Recover({
  dropped, onDropped, recent, busy, error, onRecover, onOpen,
}: {
  dropped: string[];
  onDropped: (paths: string[]) => void;
  recent: Job[];
  busy: boolean;
  error: string | null;
  onRecover: (paths: string[], ownership: Ownership, name?: string) => void;
  onOpen: (jobId: string) => void;
}) {
  const [hot, setHot] = useState(false);
  const [ownership, setOwnership] = useState<Ownership>("OWNED");

  const chooseFiles = useCallback(async () => {
    const chosen = await open({ multiple: true, directory: false });
    if (Array.isArray(chosen)) onDropped(Array.from(new Set([...dropped, ...chosen])));
    else if (typeof chosen === "string") onDropped(Array.from(new Set([...dropped, chosen])));
  }, [dropped, onDropped]);

  const chooseFolder = useCallback(async () => {
    const chosen = await open({ multiple: false, directory: true });
    if (typeof chosen === "string") onDropped(Array.from(new Set([...dropped, chosen])));
  }, [dropped, onDropped]);

  const hasBinary = dropped.some((p) => kindOf(p) === "binary" || kindOf(p) === "folder" || kindOf(p) === "archive");

  return (
    <div className="home enter">
      <header className="hero">
        <div className="name">AB · Artifact Bench</div>
        <div className="line">Recover. Reconstruct. Rebuild.</div>
      </header>

      <div
        className="drop"
        data-hot={hot}
        data-busy={busy}
        onClick={busy ? undefined : chooseFiles}
        onDragOver={(e) => { e.preventDefault(); setHot(true); }}
        onDragLeave={() => setHot(false)}
        onDrop={() => setHot(false)}
      >
        <span className="grid" aria-hidden="true" />
        <span className="tick tl" aria-hidden="true" /><span className="tick tr" aria-hidden="true" />
        <span className="tick bl" aria-hidden="true" /><span className="tick br" aria-hidden="true" />
        <Glyph />
        <div className="lead">{busy ? "Recovering" : "Drop plugin binaries, presets, sessions, project folders, debug files, assets, or archives"}</div>
        <div className="ext">vst3 · dll · vst · component · dylib · vstpreset · fxp · rpp · als · flp · pdb · map · zip · folders</div>
      </div>

      <div className="row" style={{ marginTop: "var(--s5)" }}>
        <Button onClick={chooseFiles} disabled={busy} variant="quiet">Choose Files</Button>
        <Button onClick={chooseFolder} disabled={busy} variant="quiet">Choose Folder</Button>
      </div>

      {dropped.length > 0 && (
        <div style={{ width: "100%" }}>
          <div className="intake">
            {dropped.map((p) => (
              <span className="chip" key={p} title={p}>
                <span className="kind">{kindOf(p)}</span>
                {p.split(/[\\/]/).pop()}
              </span>
            ))}
          </div>

          <div className="ownership">
            <Segmented<Ownership>
              ariaLabel="Ownership"
              value={ownership}
              onChange={setOwnership}
              options={[
                { value: "OWNED", label: "My plugin", caption: "reconstruction + export" },
                { value: "AUTHORIZED", label: "Authorized", caption: "reconstruction + export" },
                { value: "THIRD_PARTY", label: "Third-party", caption: "analysis only" },
              ]}
              tall
            />
          </div>

          <div className="row" style={{ marginTop: "var(--s6)" }}>
            <Button variant="primary" size="lg" disabled={busy || !hasBinary} onClick={() => onRecover(dropped, ownership)}>
              RECOVER PROJECT
            </Button>
            <Button variant="quiet" disabled={busy} onClick={() => onDropped([])}>Clear</Button>
          </div>
          {!hasBinary && (
            <div style={{ marginTop: "var(--s4)" }}>
              <Note>Add the plugin binary (or a folder or archive that contains it). Presets, sessions and sources attach to it.</Note>
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{ marginTop: "var(--s6)", width: "100%" }}>
          <Note strong heading="Could not recover">{error}</Note>
        </div>
      )}

      {recent.length > 0 && (
        <section className="recent">
          <div className="head">
            <span className="label">Recent</span>
            <span className="label">{recent.length}</span>
          </div>
          {recent.slice(0, 8).map((j) => (
            <button key={j.job_id} className="recent-row" type="button" title={j.primary} onClick={() => onOpen(j.job_id)}>
              <span className="nm">{j.name}</span>
              <span className="meta">{j.ownership.toLowerCase().replace("_", "-")} · {shortHash(j.artifact_sha256)}</span>
              <span className="meta">{when(j.created)}</span>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
