import { latin1, sha256Hex } from "./bytes";
import type { Resource } from "./types";

/**
 * v2 `validateResources` with structural parsers in place of the browser
 * (`Image`, `DOMParser`) — DECISIONS D-006. Field names and verdict rules are
 * unchanged: VALID_EXACT = PARSER_VALID + BOUNDARY_VERIFIED; a parser-valid
 * carve without a verified boundary is PARSER_VALID; duplicates by SHA-256.
 */

/** PNG dimensions from IHDR (the browser decoded the image to learn these). */
export function pngDims(d: Uint8Array): { w: number; h: number } | null {
  if (d.length < 24 || d[0] !== 0x89 || d[1] !== 0x50 || String.fromCharCode(d[12], d[13], d[14], d[15]) !== 'IHDR') return null;
  const dv = new DataView(d.buffer, d.byteOffset, d.byteLength);
  const w = dv.getUint32(16), h = dv.getUint32(20);
  // A decodable PNG needs an IEND and a sane header; the chunk walk mirrors carve().
  let p = 8, sawIEND = false, sawIDAT = false;
  for (let n = 0; n < 100000 && p + 12 <= d.length; n++) {
    const len = dv.getUint32(p); const type = String.fromCharCode(d[p+4], d[p+5], d[p+6], d[p+7]);
    if (!/^[A-Za-z]{4}$/.test(type) || p + 12 + len > d.length) return null;
    if (type === 'IDAT') sawIDAT = true;
    p += 12 + len;
    if (type === 'IEND') { sawIEND = true; break; }
  }
  return w > 0 && h > 0 && sawIEND && sawIDAT ? { w, h } : null;
}

/** JPEG dimensions from the first SOF marker (what the browser decode reported). */
export function jpegDims(d: Uint8Array): { w: number; h: number } | null {
  if (d.length < 4 || d[0] !== 0xff || d[1] !== 0xd8) return null;
  const dv = new DataView(d.buffer, d.byteOffset, d.byteLength);
  let p = 2;
  while (p + 4 <= d.length) {
    if (d[p] !== 0xff) { p++; continue; }
    const marker = d[p + 1];
    if (marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0x01 || marker === 0xff) { p += 2; continue; }
    if (marker === 0xd9) return null;
    const len = dv.getUint16(p + 2);
    if ((marker >= 0xc0 && marker <= 0xcf) && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      if (p + 9 > d.length) return null;
      const h = dv.getUint16(p + 5), w = dv.getUint16(p + 7);
      return w > 0 && h > 0 && d[d.length - 2] === 0xff && d[d.length - 1] === 0xd9 ? { w, h } : null;
    }
    p += 2 + len;
  }
  return null;
}

/**
 * Well-formedness check standing in for `DOMParser`: one root element,
 * balanced tags, quoted attributes, no stray text after the root. Returns the
 * root element name or null. Comments, PIs, CDATA and doctype are tolerated.
 */
export function xmlWellFormed(text: string): string | null {
  let i = 0; const n = text.length; const stack: string[] = []; let root: string | null = null; let closedRoot = false;
  const skipWs = () => { while (i < n && /\s/.test(text[i])) i++; };
  while (i < n) {
    const lt = text.indexOf('<', i);
    if (lt < 0) { return text.slice(i).trim() === '' && root !== null && stack.length === 0 ? root : null; }
    const between = text.slice(i, lt);
    if (between.trim() !== '' && (stack.length === 0)) return null; // text outside the root
    i = lt;
    if (text.startsWith('<!--', i)) { const e = text.indexOf('-->', i + 4); if (e < 0) return null; i = e + 3; continue; }
    if (text.startsWith('<?', i)) { const e = text.indexOf('?>', i + 2); if (e < 0) return null; i = e + 2; continue; }
    if (text.startsWith('<![CDATA[', i)) { const e = text.indexOf(']]>', i + 9); if (e < 0 || stack.length === 0) return null; i = e + 3; continue; }
    if (text.startsWith('<!', i)) { const e = text.indexOf('>', i + 2); if (e < 0) return null; i = e + 1; continue; }
    if (text.startsWith('</', i)) {
      const e = text.indexOf('>', i + 2); if (e < 0) return null;
      const name = text.slice(i + 2, e).trim();
      if (stack.length === 0 || stack[stack.length - 1] !== name) return null;
      stack.pop(); i = e + 1;
      if (stack.length === 0) { closedRoot = true; }
      continue;
    }
    if (closedRoot) return null; // a second root
    // start tag
    i++;
    const m = /^[A-Za-z_:][\w.:-]*/.exec(text.slice(i, i + 256)); if (!m) return null;
    const name = m[0]; i += name.length;
    let selfClose = false;
    for (;;) {
      skipWs();
      if (i >= n) return null;
      if (text[i] === '/' && text[i + 1] === '>') { selfClose = true; i += 2; break; }
      if (text[i] === '>') { i++; break; }
      const am = /^[A-Za-z_:][\w.:-]*\s*=\s*/.exec(text.slice(i, i + 256)); if (!am) return null;
      i += am[0].length;
      const q = text[i]; if (q !== '"' && q !== "'") return null;
      const e = text.indexOf(q, i + 1); if (e < 0) return null;
      if (text.slice(i + 1, e).includes('<')) return null;
      i = e + 1;
    }
    if (root === null) root = name;
    if (!selfClose) stack.push(name); else if (stack.length === 0) closedRoot = true;
  }
  return root !== null && stack.length === 0 ? root : null;
}

/** v2 `fontName` — verbatim. sfnt 'name' table: Windows platform, nameID 4 (full) else 1 (family). */
export function fontName(d: Uint8Array): string | null {
  try { const dv = new DataView(d.buffer, d.byteOffset); const n = dv.getUint16(4); for (let i = 0; i < n; i++) { const rec = 12 + i * 16; if (String.fromCharCode(d[rec], d[rec+1], d[rec+2], d[rec+3]) !== 'name') continue; const off = dv.getUint32(rec + 8); const cnt = dv.getUint16(off + 2), so = dv.getUint16(off + 4); const out: Record<number, string> = {};
      for (let k = 0; k < cnt; k++) { const r = off + 6 + k * 12; const pid = dv.getUint16(r), nid = dv.getUint16(r + 6), l = dv.getUint16(r + 8), o = dv.getUint16(r + 10); if (pid === 3 && (nid === 1 || nid === 4)) { let s = ''; for (let q = 0; q < l; q += 2) s += String.fromCharCode(dv.getUint16(off + so + o + q)); out[nid] = s; } }
      return out[4] || out[1] || null; } } catch (e) { /* not a font */ } return null; }

export async function validateResources(list: Resource[]): Promise<void> {
  const seen = new Map<string, string>();
  for (const x of list) {
    try { x.sha256 = await sha256Hex(x.data); } catch (e) { x.sha256 = null; }
    if (x.sha256 && seen.has(x.sha256)) { x.status = 'DUPLICATE'; x.dupOf = seen.get(x.sha256); continue; }
    if (x.sha256) seen.set(x.sha256, x.name);
    x.status = 'UNKNOWN'; x.parser = 'UNKNOWN';
    try {
      if (x.ext === 'png' || x.ext === 'jpg') { const dims = x.ext === 'png' ? pngDims(x.data) : jpegDims(x.data); const ok = !!dims; if (dims) { x.dims = dims.w + 'x' + dims.h; const w = dims.w, h = dims.h; if (w > 0 && h >= 4 * w) { const frames: string[] = []; for (const fh of [w, Math.round(w * 1.5), w * 2]) if (h % fh === 0 && h / fh >= 4) frames.push(`${h / fh}×${w}x${fh}`); x.semantics = 'SPRITE_SHEET_CANDIDATE' + (frames.length ? ' (' + frames.join(' or ') + ')' : ' (frame height unknown)'); } } x.status = ok ? 'VALID_EXACT' : 'INVALID'; }
      else if (x.ext === 'svg' || x.ext === 'xml') { const txt = latin1.decode(x.data); const root = xmlWellFormed(txt); x.status = root === null ? 'CARVED_PARTIAL' : 'VALID_EXACT'; if (x.status === 'VALID_EXACT') { x.root = root!; x.boundary = 'BOUNDARY_VERIFIED'; /* a full-document parse rejects trailing bytes, so a clean parse bounds the carve */ } }
      else if (x.ext === 'ttf' || x.ext === 'otf') { x.status = 'VALID_EXACT'; x.embeddedName = fontName(x.data); if (x.embeddedName) x.dims = x.embeddedName; }
      else if (x.ext === 'json') { JSON.parse(latin1.decode(x.data)); x.status = 'VALID_EXACT'; }
      else if (x.ext === 'wav') { const d = x.data, dv = new DataView(d.buffer, d.byteOffset); let p = 12, fmt: { ch: number; sr: number; bits: number } | null = null, dataLen = 0; const chunks: string[] = [];
        while (p + 8 <= d.length) { const tag = String.fromCharCode(d[p], d[p+1], d[p+2], d[p+3]); const sz = dv.getUint32(p + 4, true); chunks.push(tag.trim()); if (tag === 'fmt ') fmt = { ch: dv.getUint16(p + 10, true), sr: dv.getUint32(p + 12, true), bits: dv.getUint16(p + 22, true) }; if (tag === 'data') dataLen = sz; p += 8 + sz + (sz & 1); }
        x.status = fmt && dataLen ? 'VALID_EXACT' : 'CARVED_PARTIAL'; if (fmt) { const secs = dataLen / (fmt.sr * fmt.ch * (fmt.bits / 8)); x.dims = `${fmt.ch}ch ${fmt.sr}Hz ${fmt.bits}bit ${secs.toFixed(2)}s`; x.root = chunks.includes('bext') ? 'BWF (' + chunks.join(',') + ')' : chunks.join(','); } }
    } catch (e) { x.status = 'INVALID'; }
    if (x.status === 'VALID_EXACT') { x.parser = 'PARSER_VALID'; if (x.boundary !== 'BOUNDARY_VERIFIED') x.status = 'PARSER_VALID'; }
    else if (x.status === 'INVALID') x.parser = 'PARSER_INVALID';
  }
}
