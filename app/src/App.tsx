import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import type { BackendStatus, Env, Job, NamingMode, RecoveryContext, RecoveryGoal, ProgressEvent } from "./lib/types";
import { api, backendStatus, onProgress, saveWindow } from "./lib/api";
import { runStaticInWorker } from "./lib/staticWorker";
import { Recover } from "./views/Recover";
import { Bench, type BenchScreen } from "./views/Bench";
import { Corpus } from "./views/Corpus";
import { SettingsView } from "./views/Settings";
import { Diagnostics } from "./views/Diagnostics";
import { Help } from "./views/Help";

/** The AB mark: a bench — a rail over two legs. Survives an 11px render. */
const Mark = () => (
  <svg className="mark" viewBox="0 0 12 11" fill="none" aria-hidden="true">
    <rect x="0" y="2" width="12" height="2" fill="currentColor" />
    <rect x="2" y="4" width="2" height="6" fill="currentColor" opacity="0.6" />
    <rect x="8" y="4" width="2" height="6" fill="currentColor" opacity="0.6" />
  </svg>
);

type Tab = "recover" | "bench" | "corpus" | "settings" | "help";

export default function App() {
  const [tab, setTab] = useState<Tab>("recover");
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [env, setEnv] = useState<Env | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [screen, setScreen] = useState<BenchScreen>("overview");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dropped, setDropped] = useState<string[]>([]);
  const pageRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { pageRef.current?.scrollTo({ top: 0 }); }, [tab, screen]);

  const refreshJobs = useCallback(() => {
    api.jobs().then(setJobs).catch(() => undefined);
  }, []);

  useEffect(() => {
    void (async () => {
      let reported: BackendStatus;
      try {
        reported = await backendStatus();
      } catch (e) {
        reported = { ok: false, portable: false, safeMode: false, home: "", state: "", logs: "", error: String(e) };
      }
      setStatus(reported);
      if (!reported.ok) return;
      try {
        setEnv(await api.environment());
        refreshJobs();
      } catch (e) {
        setStatus({ ...reported, ok: false, error: String((e as Error).message ?? e) });
      }
    })();
  }, [refreshJobs]);

  // Remember window geometry; Tauri's own events cover moves between monitors.
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    const unlisten: Array<() => void> = [];
    const remember = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        void saveWindow({ width: window.outerWidth, height: window.outerHeight, x: window.screenX, y: window.screenY });
      }, 500);
    };
    void (async () => {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        const w = getCurrentWindow();
        const off = await Promise.all([w.onMoved(remember), w.onResized(remember)]);
        if (cancelled) off.forEach((fn) => fn()); else unlisten.push(...off);
      } catch {
        window.addEventListener("resize", remember);
        unlisten.push(() => window.removeEventListener("resize", remember));
      }
    })();
    return () => { cancelled = true; window.clearTimeout(timer); unlisten.forEach((fn) => fn()); };
  }, []);

  // Native file drop anywhere in the window feeds the Recover screen.
  useEffect(() => {
    let dispose: (() => void) | undefined;
    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (event.payload.type !== "drop") return;
        const paths = event.payload.paths ?? [];
        if (paths.length) {
          setDropped((prev) => Array.from(new Set([...prev, ...paths])));
          setTab("recover");
        }
      })
      .then((un) => { dispose = un; })
      .catch(() => undefined);
    return () => dispose?.();
  }, []);

  useEffect(() => onProgress((e) => setEvents((prev) => [...prev, e])), []);

  const openJob = useCallback(async (jobId: string) => {
    try {
      const found = await api.job(jobId);
      setJob(found);
      setScreen("overview");
      setTab("bench");
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, []);

  const recover = useCallback(async (paths: string[], context: RecoveryContext, name?: string, naming: NamingMode = "PRESERVE_ORIGINAL_NAMES", goal: RecoveryGoal = "PRESERVE_ORIGINAL") => {
    setBusy(true);
    setError(null);
    setEvents([]);
    try {
      const result = await api.ingest(paths, context, name);
      refreshJobs();
      if (result.jobs.length === 0) {
        setError("Nothing usable in that drop. Try the plugin file, a preset, or your old project folder.");
        return;
      }
      const first = result.jobs[0];
      setJob(first);
      setTab("bench");
      setScreen("overview");
      setDropped([]);
      // The static stage runs in the webview worker (SPEC §2) and is handed to the engine;
      // every later stage is the engine's. A worker failure is a STATIC failure, not a crash.
      const staticDone = first.stages.some((s) => s.stage === "STATIC_COMPLETE" && s.status === "OK");
      if (!staticDone) {
        try {
          setEvents((prev) => [...prev, { id: 0, stage: "STATIC", status: "running", detail: "starting worker", extra: {} }]);
          await runStaticInWorker(first.job_id, (m) => setEvents((prev) => [...prev, { id: 0, stage: "STATIC", status: "running", detail: m, extra: {} }]));
        } catch (e) {
          setEvents((prev) => [...prev, { id: 0, stage: "STATIC", status: "failed", detail: `STATIC_WORKER: ${String((e as Error).message ?? e)}`, extra: {} }]);
        }
      }
      const ran = await api.runJob(first.job_id, undefined, { naming, goal });
      setJob(ran);
      refreshJobs();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }, [refreshJobs]);

  if (status && !status.ok) {
    return (
      <div className="shell">
        <header className="titlebar"><span className="wordmark"><Mark />AB</span></header>
        <div className="page">
          <Diagnostics status={status} onRecovered={(next) => { setStatus(next); api.environment().then(setEnv).catch(() => undefined); }} />
        </div>
      </div>
    );
  }

  const running = events.length > 0 && events[events.length - 1].status === "running";

  return (
    <div className="shell">
      <header className="titlebar">
        <span className="wordmark"><Mark />AB · Artifact Bench</span>
        <nav className="nav">
          {(["recover", "bench", "corpus", "settings", "help"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              aria-current={tab === t ? "page" : undefined}
              disabled={t === "bench" && !job}
              onClick={() => { setTab(t); if (t === "recover") refreshJobs(); }}
            >
              {t}
            </button>
          ))}
        </nav>
        <span className="grow" />
        <button className="status-chip" data-on={Boolean(env)} type="button" onClick={() => setTab("settings")}
                title={env ? `engine ${env.version}` : undefined}>
          <span className="led" aria-hidden="true" />
          {running ? "Working" : env ? `Engine ${env.version}` : "Engine starting"}
        </button>
      </header>

      {status?.safeMode && (
        <div className="safe-mode" role="status">
          <strong>Safe Mode.</strong> AB will not write files or start workers. You can inspect existing
          projects and read Diagnostics. Remove <span className="mono">safemode.flag</span> or start without{" "}
          <span className="mono">--safe</span> to leave it.
        </div>
      )}

      <div className="page" ref={pageRef}>
        {tab === "recover" && (
          <Recover
            dropped={dropped}
            onDropped={setDropped}
            recent={jobs}
            busy={busy}
            error={error}
            onRecover={recover}
            onOpen={openJob}
          />
        )}
        {tab === "bench" && job && (
          <Bench
            job={job}
            screen={screen}
            events={events}
            onScreen={setScreen}
            onRefresh={() => openJob(job.job_id)}
            onRun={async (stages) => { setBusy(true); try { setJob(await api.runJob(job.job_id, stages)); } catch (e) { setError(String((e as Error).message ?? e)); } finally { setBusy(false); } }}
            busy={busy}
          />
        )}
        {tab === "corpus" && <Corpus jobs={jobs} onOpen={openJob} />}
        {tab === "settings" && <SettingsView env={env} status={status} />}
        {tab === "help" && <Help />}
      </div>
    </div>
  );
}
