/** Byte helpers shared by the ported modules. Behaviour identical to v2's inline lambdas. */

export const uniq = <T,>(a: T[]): T[] => [...new Set(a)];

/** v2 `indexOf(pat, from)`: first occurrence of a byte pattern at or after `from`, else -1. */
export function indexOfBytes(u8: Uint8Array, pat: number[] | Uint8Array, from: number): number {
  let i = from;
  while ((i = u8.indexOf(pat[0], i)) >= 0 && i <= u8.length - pat.length) {
    let ok = true;
    for (let k = 1; k < pat.length; k++) if (u8[i + k] !== pat[k]) { ok = false; break; }
    if (ok) return i;
    i++;
  }
  return -1;
}

export const hex = (buf: ArrayBuffer | Uint8Array): string =>
  [...new Uint8Array(buf instanceof Uint8Array ? buf : buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

export async function sha256Hex(data: Uint8Array): Promise<string | null> {
  try {
    const subtle = (globalThis as unknown as { crypto?: Crypto }).crypto?.subtle;
    if (subtle) {
      const copy = data.byteOffset === 0 && data.byteLength === data.buffer.byteLength ? data : data.slice();
      return hex(await subtle.digest("SHA-256", copy as unknown as BufferSource));
    }
  } catch { /* fall through */ }
  try {
    const nodeCrypto = await import("node:crypto");
    return nodeCrypto.createHash("sha256").update(data).digest("hex");
  } catch {
    return null;
  }
}

export const latin1 = new TextDecoder("latin1");
export const utf8 = new TextEncoder();

export const now = (): number => (typeof performance !== "undefined" ? performance.now() : Date.now());

/** Append without spreading: `arr.push(...huge)` blew the stack on a 45 MB binary (CLAUDE_CODE_PROMPT §2). */
export function append<T>(target: T[], more: T[]): T[] {
  for (let i = 0; i < more.length; i++) target.push(more[i]);
  return target;
}
