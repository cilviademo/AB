import type { ConstHit } from "./types";

/** v2 known DSP-relevant constants — verbatim. Presence is a CANDIDATE hint, never a DSP claim. */
export const KNOWN: [number, string][] = [[Math.PI,'π'],[2*Math.PI,'2π'],[Math.PI/2,'π/2'],[Math.SQRT2,'√2'],[Math.SQRT1_2,'1/√2 (Butterworth Q)'],[Math.E,'e'],[Math.LN10/20,'ln10/20 (dB→gain)'],[20/Math.LN10,'20/ln10 (gain→dB)'],[44100,'44.1 kHz'],[48000,'48 kHz'],[88200,'88.2 kHz'],[96000,'96 kHz'],[192000,'192 kHz'],[20,'20 Hz'],[20000,'20 kHz'],[0.001,'1 ms / -60 dB'],[-0.691,'LUFS offset (-0.691)'],[0.3,'0.3 (ceiling/dB?)'],[1.0/3.0,'1/3'],[0.7071,'0.7071'],[1.4142,'1.4142']];

/** v2 `scanConstants` — verbatim (4-byte stride over `.rdata` when known, else the whole file). */
export function scanConstants(u8: Uint8Array, range?: [number, number]): ConstHit[] {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength); const [a, b] = range || [0, u8.length]; const hits = new Map<string, ConstHit>();
  const step = 4;
  for (let i = a; i + 8 <= b; i += step) {
    const f = dv.getFloat32(i, true), d = dv.getFloat64(i, true);
    for (const v of [f, d]) { if (!isFinite(v) || v === 0) continue;
      for (const [k, label] of KNOWN) { if (Math.abs(v - k) <= Math.abs(k) * 1e-5) { const key = label; const e = hits.get(key) || { label, value: k, count: 0, offsets: [] }; e.count++; if (e.offsets.length < 5) e.offsets.push('0x' + i.toString(16)); hits.set(key, e); } } }
  }
  return [...hits.values()].sort((x, y) => y.count - x.count);
}
