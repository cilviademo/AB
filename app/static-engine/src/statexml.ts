import { latin1 } from "./bytes";
import type { EmbeddedParam } from "./types";

/** base64 decode without `atob` (absent in some workers, present in Node ≥ 16 as globalThis.atob). */
function b64(s: string): string {
  if (typeof atob === "function") return atob(s);
  return Buffer.from(s, "base64").toString("latin1");
}

/** v2 `extractStateXml` — verbatim. `isBinary` = byte-level scan around `<PARAM` only. */
export function extractStateXml(u8: Uint8Array, isBinary?: boolean): { params: EmbeddedParam[]; xml: string } {
  const dec = latin1;
  if (isBinary) { // byte-level: only look around '<PARAM' occurrences
    const params: EmbeddedParam[] = []; let xml = ''; const pat = [0x3c,0x50,0x41,0x52,0x41,0x4d,0x20]; let i = 0, n = 0;
    const idxOf = (from: number) => { let k = from; while ((k = u8.indexOf(0x3c, k)) >= 0 && k <= u8.length - 7) { let ok = true; for (let q = 1; q < 7; q++) if (u8[k+q] !== pat[q]) { ok = false; break; } if (ok) return k; k++; } return -1; };
    while (n++ < 3000) { const a = idxOf(i); if (a < 0) break; const s = dec.decode(u8.subarray(a, Math.min(u8.length, a + 300)));
      const m = s.match(/^<PARAM\s+(?:id="([^"]+)"\s+value="([^"]+)"|value="([^"]+)"\s+id="([^"]+)")/); if (m) params.push({ id: m[1] || m[4], value: parseFloat(m[2] || m[3]) });
      if (!xml && m) { const ws = Math.max(0, a - 4000); const win = dec.decode(u8.subarray(ws, Math.min(u8.length, a + 60000))).replace(/[^\x20-\x7e\n\r\t]/g, ' '); const d = win.match(/<([A-Za-z_][\w.-]*)[^<>]*>\s*(?:<[^<>]*>\s*)*?<PARAM[\s\S]*?<\/\1>/); if (d) xml = d[0]; }
      i = a + 7; }
    return { params, xml };
  }
  const txt = dec.decode(u8.subarray(0, Math.min(u8.length, 200e6))).replace(/[^\x20-\x7e\n\r\t]/g, ' ');
  // also decode base64 blobs (Reaper RPP, Ableton, FL chunks)
  let extra = '';
  for (const m of txt.matchAll(/(?:^|\s)([A-Za-z0-9+\/=]{200,})(?=\s|$)/g)) { try { const bin = b64(m[1].replace(/\s/g, '')); if (/<PARAM|ValueTree|<\w+ /.test(bin)) extra += ' ' + bin; } catch (e) { /* not base64 */ } }
  // Reaper splits base64 across lines inside <VST … > blocks
  for (const m of txt.matchAll(/<VST[^\n]*\n([\s\S]*?)\n\s*>/g)) { try { const b64s = m[1].replace(/\s+/g, ''); const bin = b64(b64s); extra += ' ' + bin.replace(/[^\x20-\x7e]/g, ' '); } catch (e) { /* not base64 */ } }
  const all = txt + extra;
  const params: EmbeddedParam[] = [];
  for (const m of all.matchAll(/<PARAM\s+id="([^"]+)"\s+value="([^"]+)"/g)) params.push({ id: m[1], value: parseFloat(m[2]) });
  for (const m of all.matchAll(/<PARAM\s+value="([^"]+)"\s+id="([^"]+)"/g)) params.push({ id: m[2], value: parseFloat(m[1]) });
  const xm = all.match(/<PARAMETERS[\s\S]*?<\/PARAMETERS>|<[A-Za-z_][\w-]*[^>]*>\s*<PARAM[\s\S]*?<\/[A-Za-z_][\w-]*>/);
  return { params, xml: xm ? xm[0] : '' };
}
