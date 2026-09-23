import { indexOfBytes, latin1, utf8 } from "./bytes";
import type { CarveResult, Resource } from "./types";

/**
 * v2 `carve` — verbatim, plus the SPEC §6.3 `deep` switch.
 *
 * Fast mode (default) is exactly v2: structural anchors first, small windows
 * (−60 KB … +160 KB), covered ranges skipped, early stop after 8 misses, caps
 * of 60 hits per anchor / 30 documents / 40 per signature, and the scan
 * status recorded as FAST_SCAN_COMPLETE or FAST_SCAN_EARLY_TERMINATED.
 * Deep mode lifts every cap and early stop and widens the document window to
 * the whole file; its status is DEEP_SCAN_COMPLETE.
 */
export function carve(u8: Uint8Array, deep = false): CarveResult {
  const sigs = [
    { ext: 'png', start: [0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a], end: null as number[] | null, mime: 'image/png', png: true },
    { ext: 'jpg', start: [0xff,0xd8,0xff,0xe0,0x00,0x10,0x4a,0x46,0x49,0x46], end: [0xff,0xd9], mime: 'image/jpeg' },
    { ext: 'jpg', start: [0xff,0xd8,0xff,0xe1], end: [0xff,0xd9], mime: 'image/jpeg', exif: true },
    { ext: 'wav', start: [0x52,0x49,0x46,0x46], end: null, mime: 'audio/wav', riff: true },
    { ext: 'svg', start: [0x3c,0x73,0x76,0x67,0x20], end: [0x3c,0x2f,0x73,0x76,0x67,0x3e], mime: 'image/svg+xml' },
    { ext: 'ttf', start: [0x00,0x01,0x00,0x00], end: null, mime: 'font/ttf', font: true },
    { ext: 'otf', start: [0x4f,0x54,0x54,0x4f], end: null, mime: 'font/otf', font: true },
    { ext: 'xml', start: [0x3c,0x3f,0x78,0x6d,0x6c,0x20], end: null, mime: 'text/xml' },
  ] as Array<{ ext: string; start: number[]; end: number[] | null; mime: string; png?: boolean; riff?: boolean; font?: boolean; exif?: boolean }>;
  const found: CarveResult = [] as unknown as CarveResult;
  const indexOf = (pat: number[], from: number) => indexOfBytes(u8, pat, from);
  const pngLen = (a: number) => { // walk chunks: 8-byte sig, then [len u32be][type 4][data][crc 4] ... until IEND
    const dv = new DataView(u8.buffer, u8.byteOffset); let p = a + 8; if (a + 16 > u8.length || String.fromCharCode(u8[a+12], u8[a+13], u8[a+14], u8[a+15]) !== 'IHDR') return 0;
    for (let n = 0; n < 100000 && p + 12 <= u8.length; n++) { const len = dv.getUint32(p); const type = String.fromCharCode(u8[p+4], u8[p+5], u8[p+6], u8[p+7]); if (!/^[A-Za-z]{4}$/.test(type) || len > 80e6) return 0; p += 12 + len; if (type === 'IEND') return p - a; }
    return 0; };
  const riffLen = (a: number) => { const dv = new DataView(u8.buffer, u8.byteOffset); if (a + 12 > u8.length || String.fromCharCode(u8[a+8], u8[a+9], u8[a+10], u8[a+11]) !== 'WAVE') return 0; const L = dv.getUint32(a + 4, true) + 8; return L > 1024 && a + L <= u8.length ? L : 0; };
  const fontLen = (a: number) => { // validate sfnt header: numTables sane and table tags ASCII; compute length from table records
    const dv = new DataView(u8.buffer, u8.byteOffset); const n = dv.getUint16(a + 4); if (n < 2 || n > 64 || a + 12 + n * 16 > u8.length) return 0;
    let end = 0; for (let k = 0; k < n; k++) { const rec = a + 12 + k * 16; for (let c = 0; c < 4; c++) { const ch = u8[rec + c]; if (ch < 0x20 || ch > 0x7e) return 0; } const off = dv.getUint32(rec + 8), len = dv.getUint32(rec + 12); if (off > 50e6 || len > 50e6) return 0; end = Math.max(end, off + len); }
    return end > 1024 && a + end <= u8.length ? end : 0; };
  // header-less XML documents (JUCE ValueTree exports, layout files): find '<' + Name followed later by matching close tag
  const docRx = /<([A-Za-z_][\w.-]{1,40})(\s[^<>]{0,400})?>\s*<[\s\S]{200,400000}?<\/\1>/g;
  const dec = latin1; const seen: [number, number][] = []; let xn = 0; let earlyStop = false, capHit = false;
  const anchors = ['<PARAMETERS', '<PRESET', '<Preset', '<MacroMasterPreset', '<layout', '<PARAM ', '<button ', '<slider ', '<knob '];
  const maxDocs = deep ? Infinity : 30, maxHits = deep ? Infinity : 60, maxMisses = deep ? Infinity : 8;
  const winBefore = deep ? u8.length : 60000, winAfter = deep ? u8.length : 160000;
  for (const anchor of anchors) {
    const pat = [...anchor].map(c => c.charCodeAt(0)); let idx = 0, hits = 0, misses = 0;
    while (xn < maxDocs && hits++ < maxHits && misses < maxMisses) { const a = indexOf(pat, idx); if (a < 0) break; idx = a + pat.length;
      if (hits >= maxHits || xn >= maxDocs - 1) capHit = true;
      const cover = seen.find(([s, e]) => a >= s && a < e); if (cover) { idx = cover[1]; continue; }
      const ws = Math.max(0, a - winBefore), we = Math.min(u8.length, a + winAfter);
      const win = dec.decode(u8.subarray(ws, we)).replace(/[^\x20-\x7e\n\r\t]/g, ' ');
      const rel = a - ws; let best: RegExpExecArray | null = null, m: RegExpExecArray | null; docRx.lastIndex = 0;
      while ((m = docRx.exec(win))) { if (m.index <= rel && m.index + m[0].length >= rel) { best = m; break; } if (m.index > rel) break; docRx.lastIndex = m.index + 1; }
      if (best) { seen.push([ws + best.index, ws + best.index + best[0].length]); found.push({ ext: 'xml', mime: 'text/xml', data: utf8.encode(best[0]), offset: ws + best.index, boundary: 'BOUNDARY_VERIFIED', name: `xml_${best[1]}_${String(xn).padStart(2,'0')}.xml` }); xn++; idx = ws + best.index + best[0].length; misses = 0; }
      else { misses++; if (misses >= maxMisses) earlyStop = true; }
    }
  }
  found.xml_scan_status = deep ? 'DEEP_SCAN_COMPLETE (exhaustive anchors, full-file window, no early stop)' : earlyStop || capHit ? 'FAST_SCAN_EARLY_TERMINATED (heuristic stop; run DEEP_SCAN in standalone for exhaustive coverage)' : 'FAST_SCAN_COMPLETE (all anchors examined)';
  const maxPerSig = deep ? Infinity : 40, maxTries = deep ? Infinity : 20000;
  for (const s of sigs) {
    let idx = 0, n = 0, tries = 0;
    while (n < maxPerSig && tries++ < maxTries) {
      const a = indexOf(s.start, idx); if (a < 0) break; idx = a + 1;
      let b: number;
      if (s.font) { const L = fontLen(a); if (!L) continue; b = a + L; }
      else if (s.png) { const L = pngLen(a); if (!L) continue; b = a + L; }
      else if (s.riff) { const L = riffLen(a); if (!L) continue; b = a + L; }
      else if (s.exif) { if (String.fromCharCode(u8[a+6], u8[a+7], u8[a+8], u8[a+9]) !== 'Exif') continue; b = indexOf(s.end!, a + 10); if (b < 0) break; b += 2; if (b - a > 8e6 || b - a < 2048) continue; }
      else if (s.end) { b = indexOf(s.end, a + s.start.length); if (b < 0) break; b += s.end.length; if (b - a > 8e6) continue; }
      else { b = a + 64; const lim = Math.min(u8.length, a + 1.5e6); while (b < lim && !(u8[b] === 0 && u8[b+1] === 0)) b++; }
      const blob = u8.slice(a, b);
      if (blob.length > 96) { found.push({ ext: s.ext, mime: s.mime, data: blob, offset: a, boundary: (s.png || s.riff || s.font) ? 'BOUNDARY_VERIFIED' : 'HEURISTIC', name: `${s.ext}_${String(found.filter(f => f.ext === s.ext).length).padStart(3,'0')}.${s.ext}` } as Resource); n++; idx = b; }
    }
  }
  return found;
}
