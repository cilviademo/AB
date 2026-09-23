import type { BinaryDataMapEntry, Resource } from "./types";

// JUCE BinaryData mapping. Emission order is NOT preserved by the linker (verified on Twin Panda: the font name tables
// contradicted declaration order), so no order-based pairing. Only content-based evidence maps a name to bytes:
//   fonts → embedded name table (VERIFIED); a lone name + lone asset of one type → INFERRED_SINGLETON; else UNRESOLVED (Phase 3 decompile of getNamedResource).
/** v2 `mapBinaryData` — verbatim. */
export function mapBinaryData(resources: Resource[], names: string[]): BinaryDataMapEntry[] {
  const extOf = (n: string) => (n.match(/_(png|jpg|jpeg|svg|ttf|otf|xml|json|wav|aiff|txt)$/) || [])[1];
  const byExt: Record<string, string[]> = {};
  for (const n of names) { const e = extOf(n); if (!e) continue; const k = e === 'jpeg' ? 'jpg' : e === 'aiff' ? 'wav' : e; (byExt[k] = byExt[k] || []).push(n); }
  const groups: Record<string, Resource[]> = {};
  for (const x of resources) { if (x.status !== 'VALID_EXACT' && x.status !== 'PARSER_VALID') continue; (groups[x.ext] = groups[x.ext] || []).push(x); }
  const map: BinaryDataMapEntry[] = []; const norm = (s: string) => s.replace(/_(png|jpg|jpeg|svg|ttf|otf|xml|json|wav|aiff|txt)$/, '').replace(/[^A-Za-z0-9]/g, '').toLowerCase();
  const toFile = (n: string) => n.replace(/_(png|jpg|jpeg|svg|ttf|otf|xml|json|wav|aiff|txt)$/, '.$1');
  for (const [ext, list] of Object.entries(groups)) {
    const ns = (byExt[ext] || []).slice(); const used = new Set<string>();
    if (ext === 'ttf' || ext === 'otf') for (const x of list) { if (!x.embeddedName) continue; const key = norm(x.embeddedName); const hit = ns.find(n => !used.has(n) && (norm(n) === key || norm(n).includes(key) || key.includes(norm(n)))); if (hit) { used.add(hit); x.candidate_name = toFile(hit); x.mapping_status = 'VERIFIED (font name table: "' + x.embeddedName + '")'; map.push({ binarydata_name: hit, carved: x.name, offset: x.offset, size: x.data.length, mapping_status: x.mapping_status }); } }
    const remainingNames = ns.filter(n => !used.has(n)), remainingAssets = list.filter(x => !x.candidate_name);
    if (remainingNames.length === 1 && remainingAssets.length === 1) { const x = remainingAssets[0], n = remainingNames[0]; x.candidate_name = toFile(n); x.mapping_status = 'INFERRED_SINGLETON (only name and only asset of this type)'; map.push({ binarydata_name: n, carved: x.name, offset: x.offset, size: x.data.length, mapping_status: x.mapping_status }); }
    else remainingNames.forEach(n => map.push({ binarydata_name: n, carved: null, mapping_status: 'UNRESOLVED (' + remainingAssets.length + ' candidate assets of this type; needs Phase 3 getNamedResource decompile)' }));
  }
  return map;
}
