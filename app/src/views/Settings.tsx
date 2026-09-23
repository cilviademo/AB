import { useState } from "react";
import type { BackendStatus, Doctor, Env } from "../lib/types";
import { api, shell } from "../lib/api";
import { Advanced, Button, KeyValues, Note, Section } from "../components/ui";

export function SettingsView({ env, status }: { env: Env | null; status: BackendStatus | null }) {
  const [check, setCheck] = useState<Doctor | null>(null);
  const [checking, setChecking] = useState(false);
  const [copied, setCopied] = useState(false);

  return (
    <div className="view enter">
      <div className="label">Settings</div>
      <div className="stack-8" style={{ marginTop: "var(--s7)" }}>
        <Section title="Tools" meta="detected, never required">
          {env ? (
            <table className="check"><tbody>
              {env.tools.map((t) => (
                <tr key={t.name} data-verdict={t.present ? "PASS" : "UNAVAILABLE"}>
                  <td className="check-verdict">{t.present ? "PRESENT" : "MISSING"}</td>
                  <td className="check-name">{t.name}</td>
                  <td className="check-detail">{t.present ? `${t.path}${t.version ? " · " + t.version : ""}` : t.detail}</td>
                </tr>
              ))}
            </tbody></table>
          ) : <Note>Engine not connected.</Note>}
          <div style={{ marginTop: "var(--s4)" }}>
            <Note>Missing tools make their stage SKIPPED with a reason; nothing is faked. JDK, Ghidra and pluginval can be fetched by the first-run downloader (Phase 3) against pinned SHA-256s in tools/manifest.json.</Note>
          </div>
        </Section>

        <Section title="Doctor" meta="checked now, not assumed">
          <div className="row">
            <Button disabled={checking} onClick={async () => { setChecking(true); setCopied(false); try { setCheck(await api.doctor()); } finally { setChecking(false); } }}>
              {checking ? "Checking…" : "Run doctor"}
            </Button>
            {check && (
              <Button onClick={async () => { try { await navigator.clipboard.writeText(check.report); setCopied(true); } catch { setCopied(false); } }}>
                {copied ? "Copied" : "Copy report"}
              </Button>
            )}
            {status && <Button variant="quiet" onClick={() => void shell.reveal(status.logs)}>Open logs</Button>}
          </div>
          {check && (
            <table className="check"><tbody>
              {check.rows.map((row) => (
                <tr key={row.name} data-verdict={row.verdict}>
                  <td className="check-verdict">{row.verdict}</td>
                  <td className="check-name">{row.name}</td>
                  <td className="check-detail">{row.detail}</td>
                </tr>
              ))}
            </tbody></table>
          )}
        </Section>
      </div>

      <Advanced title="Environment">
        {env && status && (
          <KeyValues rows={[
            ["Engine", `${env.version} · ${env.frozen ? "packaged" : "source checkout"}`],
            ["Platform", env.platform],
            ["Python", env.python],
            ["Projects", <span className="mono" key="h">{status.home}</span>],
            ["App data", <span className="mono" key="s">{status.state}</span>],
            ["Logs", <span className="mono" key="l">{status.logs}</span>],
            ["Mode", status.portable ? "Portable" : "Installed"],
          ]} />
        )}
      </Advanced>
    </div>
  );
}
