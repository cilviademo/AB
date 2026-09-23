import type { PEInfo } from "./types";

/** v2 `parsePE` — verbatim. */
export function parsePE(u8: Uint8Array): PEInfo {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength), o: PEInfo = {};
  try {
    const pe = dv.getUint32(0x3c, true); if (dv.getUint32(pe, true) !== 0x4550) return o;
    o.machine = ({ 0x14c: 'x86', 0x8664: 'x64', 0xaa64: 'ARM64' } as Record<number, string>)[dv.getUint16(pe + 4, true)] || '?';
    const nsec = dv.getUint16(pe + 6, true);
    o.timestamp = new Date(dv.getUint32(pe + 8, true) * 1000).toISOString().slice(0, 16).replace('T', ' ');
    const optSize = dv.getUint16(pe + 20, true), opt = pe + 24, pe32p = dv.getUint16(opt, true) === 0x20b;
    o.linker = dv.getUint8(opt + 2) + '.' + dv.getUint8(opt + 3);
    const ddOff = opt + (pe32p ? 112 : 96), expRVA = dv.getUint32(ddOff, true);
    const secs: { name: string; va: number; vsz: number; raw: number; rsz: number }[] = []; const secOff = opt + optSize;
    for (let i = 0; i < nsec; i++) { const s = secOff + i * 40; secs.push({ name: String.fromCharCode(...u8.slice(s, s + 8)).replace(/\0+$/, ''), va: dv.getUint32(s + 12, true), vsz: dv.getUint32(s + 8, true), raw: dv.getUint32(s + 20, true), rsz: dv.getUint32(s + 16, true) }); }
    o.sectionNames = secs.map(s => s.name).join(' ');
    const rd = secs.find(s => s.name === '.rdata'); if (rd) o.rdata = [rd.raw, rd.raw + rd.rsz];
    const rva2off = (rva: number) => { const s = secs.find(x => rva >= x.va && rva < x.va + Math.max(x.vsz, x.rsz)); return s ? rva - s.va + s.raw : -1; };
    o.exports = [];
    if (expRVA) { const e = rva2off(expRVA); if (e > 0) { const nN = dv.getUint32(e + 24, true), no = rva2off(dv.getUint32(e + 32, true)); for (let i = 0; i < Math.min(nN, 64); i++) { const so = rva2off(dv.getUint32(no + i * 4, true)); if (so < 0) continue; let s = ''; for (let j = so; j < so + 128 && u8[j]; j++) s += String.fromCharCode(u8[j]); o.exports.push(s); } } }
    o.format = o.exports.includes('GetPluginFactory') ? 'VST3' : o.exports.includes('VSTPluginMain') ? 'VST2' : o.exports.includes('clap_entry') ? 'CLAP' : 'unknown';
  } catch (e) { o.error = String(e); }
  return o;
}

/** v2 `findRSDS` — verbatim. */
export function findRSDS(u8: Uint8Array): string | null {
  let i = -1;
  while ((i = u8.indexOf(0x52, i + 1)) >= 0 && i < u8.length - 30) if (u8[i+1] === 0x53 && u8[i+2] === 0x44 && u8[i+3] === 0x53) {
    let s = '', j = i + 24; while (j < u8.length && u8[j] >= 0x20 && u8[j] < 0x7f && s.length < 260) s += String.fromCharCode(u8[j++]);
    if (/\.pdb$/i.test(s)) return s;
  }
  return null;
}
