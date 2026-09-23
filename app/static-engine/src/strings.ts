/** v2 `extractStrings` — verbatim (ASCII runs, then UTF-16LE runs). */
export function extractStrings(u8: Uint8Array, min: number): string[] {
  const out: string[] = []; let run = '';
  for (let i = 0; i < u8.length; i++) { const c = u8[i]; if (c >= 0x20 && c < 0x7f) run += String.fromCharCode(c); else { if (run.length >= min) out.push(run); run = ''; } }
  if (run.length >= min) out.push(run); run = '';
  for (let i = 0; i + 1 < u8.length; i += 2) { const c = u8[i]; if (u8[i+1] === 0 && c >= 0x20 && c < 0x7f) run += String.fromCharCode(c); else { if (run.length >= min) out.push(run); run = ''; } }
  return out;
}
