// ExportRTTI.java — AB (Artifact Bench) Ghidra headless post-script (SPEC §8, EXECUTE 3.2).
//
// Runs after auto-analysis (which includes the MSVC RTTI analyzer on PE and the
// Itanium/GCC RTTI recovery on ELF) and exports every recovered class with its
// vtable(s), inheritance, slot count, ctor/dtor candidates and method addresses to
// <out>/rtti/classes_verified.json. Names come from RTTI TypeDescriptors /
// typeinfo objects: name_status VERIFIED_RTTI, structure_status VERIFIED_VTABLE
// when a vftable was located. Never guesses a base class; UNKNOWN stays UNKNOWN.
//
//   analyzeHeadless <proj> <name> -import <bin> -postScript ExportRTTI.java <outdir>
//@category AB
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.DataType;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.*;
import ghidra.app.util.demangler.DemangledObject;
import ghidra.app.util.demangler.DemanglerUtil;

import java.io.*;
import java.util.*;

public class ExportRTTI extends GhidraScript {

    static String esc(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"') b.append("\\\""); else if (c == '\\') b.append("\\\\"); else if (c == '\n') b.append("\\n");
            else if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
        }
        return b.append('"').toString();
    }

    static class Cls {
        String name; String rttiKind; long typeDescriptor = -1; List<Long> vtables = new ArrayList<>();
        List<Integer> slotCounts = new ArrayList<>(); List<String> bases = new ArrayList<>();
        List<Long> methods = new ArrayList<>(); List<Long> ctorDtor = new ArrayList<>();
        List<List<Long>> vtableSlots = new ArrayList<>(); List<List<String>> vtableSlotNames = new ArrayList<>();
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args.length > 0 ? args[0] : "ab_export");
        new File(out, "rtti").mkdirs();
        Map<String, Cls> classes = new TreeMap<>();
        boolean isPE = currentProgram.getExecutableFormat().contains("Portable Executable");
        SymbolTable st = currentProgram.getSymbolTable();
        Listing listing = currentProgram.getListing();
        ReferenceManager refs = currentProgram.getReferenceManager();

        // 1. Class names and type descriptors. Ghidra's RTTI analyzers create symbols in the
        //    "RTTI_Type_Descriptor" / "vftable" / "typeinfo" families with the class namespace.
        for (Symbol s : st.getAllSymbols(true)) {
            String n = s.getName();
            Namespace ns = s.getParentNamespace();
            boolean td = isPE ? n.startsWith("RTTI_Type_Descriptor") : (n.equals("typeinfo") || n.startsWith("typeinfo_"));
            boolean vt = isPE ? n.startsWith("vftable") || n.contains("::vftable") : (n.equals("vtable") || n.startsWith("vtable_"));
            if (!td && !vt) continue;
            if (ns == null || ns.isGlobal()) continue;
            String cname = ns.getName(true);
            Cls c = classes.computeIfAbsent(cname, k -> new Cls());
            c.name = cname; c.rttiKind = isPE ? "MSVC_RTTI" : "ITANIUM_RTTI";
            if (td) c.typeDescriptor = s.getAddress().getOffset();
            if (vt) {
                c.vtables.add(s.getAddress().getOffset());
                List<Long> slots = new ArrayList<>(); List<String> names = new ArrayList<>();
                c.slotCounts.add(countSlots(s.getAddress(), c.methods, slots, names));
                c.vtableSlots.add(slots); c.vtableSlotNames.add(names);
            }
        }
        // 1b. Stripped ELF / Mach-O: no typeinfo/vtable symbols exist. Recover the Itanium RTTI structurally
        //     (typeinfo-name string → typeinfo object → vtables), which is what the product faces on a real
        //     stripped Linux/macOS build. Names become VERIFIED_RTTI only when a typeinfo object references
        //     the string; vtables VERIFIED_VTABLE only when a table's typeinfo pointer resolves to that object.
        if (!isPE) structuralItanium(classes, listing);
        // 2. Inheritance from the class namespaces Ghidra built (base class descriptors on PE;
        //    on ELF from the typeinfo layout). Ghidra records it as "Data Type" class structures.
        // functions grouped by namespace once (was O(classes × functions): hung on 700 classes × 40k functions)
        Map<String, List<Function>> fnByNs = new HashMap<>();
        for (Function f : listing.getFunctions(true)) {
            Namespace fns = f.getParentNamespace();
            if (fns == null || fns.isGlobal()) continue;
            fnByNs.computeIfAbsent(fns.getName(true), k -> new ArrayList<>()).add(f);
        }
        for (Cls c : classes.values()) {
            try {
                DataType dt = currentProgram.getDataTypeManager().getDataType("/" + c.name.replace("::", "/"));
                if (dt != null && dt.getDescription() != null && dt.getDescription().contains(":")) {
                    String d = dt.getDescription();
                    int i = d.indexOf(':');
                    for (String b : d.substring(i + 1).split(",")) { String t = b.trim(); if (!t.isEmpty()) c.bases.add(t); }
                }
            } catch (Exception ignored) {}
            // functions inside the class namespace whose name looks like a ctor/dtor
            Set<Long> methodSet = new HashSet<>(c.methods);
            for (Function f : fnByNs.getOrDefault(c.name, Collections.emptyList())) {
                String leaf = c.name.contains("::") ? c.name.substring(c.name.lastIndexOf("::") + 2) : c.name;
                if (f.getName().equals(leaf) || f.getName().equals("~" + leaf) || f.getName().contains("ctor") || f.getName().contains("dtor"))
                    c.ctorDtor.add(f.getEntryPoint().getOffset());
                if (methodSet.add(f.getEntryPoint().getOffset())) c.methods.add(f.getEntryPoint().getOffset());
            }
        }
        // 3. Write.
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(out, "rtti/classes_verified.json")))) {
            w.println("{\"schema\":\"artifactbench.classes_verified\",\"schema_version\":1,\"tool\":\"ghidra/ExportRTTI.java\",\"generated\":" + esc(new Date().toString()) + ",\"data\":[");
            boolean first = true;
            for (Cls c : classes.values()) {
                if (!first) w.println(","); first = false;
                w.print("{\"name\":" + esc(c.name) + ",\"name_status\":\"VERIFIED_RTTI\",\"rtti_kind\":" + esc(c.rttiKind)
                    + ",\"type_descriptor\":" + (c.typeDescriptor < 0 ? "null" : "\"0x" + Long.toHexString(c.typeDescriptor) + "\"")
                    + ",\"structure_status\":" + (c.vtables.isEmpty() ? "\"UNKNOWN\"" : "\"VERIFIED_VTABLE\"")
                    + ",\"vtables\":[" + hexList(c.vtables) + "],\"slot_counts\":" + c.slotCounts
                    + ",\"bases\":[" + strList(c.bases) + "],\"base_status\":" + (c.bases.isEmpty() ? "\"UNKNOWN\"" : "\"VERIFIED_RTTI\"")
                    + ",\"methods\":[" + hexList(c.methods) + "],\"ctor_dtor_candidates\":[" + hexList(c.ctorDtor) + "]"
                    + ",\"vtable_slots\":" + hexLists(c.vtableSlots) + ",\"vtable_slot_names\":" + strLists(c.vtableSlotNames) + "}");
            }
            w.println("]}");
        }
        println("ExportRTTI: " + classes.size() + " classes -> " + out);
    }

    /** Port of the v2 demangleItaniumType rule (nested-name grammar only). */
    static String demangleItanium(String m) {
        int i = 0; boolean nested = false;
        if (m.startsWith("_ZTS")) i = 4;
        if (i < m.length() && m.charAt(i) == 'N') { nested = true; i++; }
        List<String> parts = new ArrayList<>();
        while (i < m.length()) {
            int j = i; while (j < m.length() && Character.isDigit(m.charAt(j))) j++;
            if (j == i) break;
            if (j - i > 4) return null;   // no identifier is longer than 9999 chars; a longer digit run is data, not a name
            int len = Integer.parseInt(m.substring(i, j)); i = j;
            if (i + len > m.length()) return null;
            parts.add(m.substring(i, i + len)); i += len;
            if (!nested) break;
        }
        if (nested && (i >= m.length() || m.charAt(i) != 'E')) return null;
        return parts.isEmpty() ? null : String.join("::", parts);
    }

    static boolean itaniumWellFormed(String m) {
        return m.matches("(N(\\d+[A-Za-z_]\\w*)+E|\\d+[A-Za-z_]\\w*)") && demangleItanium(m) != null;
    }

    /** Itanium ABI without symbols: typeinfo objects are {vptr, name*, …} in .data.rel.ro/.rodata; vtables are
        {offset_to_top, typeinfo*, slots…}. Everything is found by scanning aligned pointer words. */
    void structuralItanium(Map<String, Cls> classes, Listing listing) throws Exception {
        Memory mem = currentProgram.getMemory(); int ptr = currentProgram.getDefaultPointerSize();
        if (ptr != 8) { println("structuralItanium: only 64-bit images supported here"); return; }
        // name strings by address: raw scan of every initialized data block for NUL-terminated ASCII runs that
        // parse as an Itanium nested/unqualified name (Ghidra defines only the strings something references,
        // and nothing references a typeinfo name string by a code xref, so the defined-data view misses most)
        Map<Long, String> nameAt = new HashMap<>();
        List<Object[]> blocks = new ArrayList<>();           // {base, bytes}
        for (MemoryBlock b : mem.getBlocks()) {
            if (!b.isInitialized() || b.isExecute()) continue;
            String bn = b.getName();
            if (!(bn.contains("data") || bn.contains("rodata") || bn.contains("const") || bn.contains("got"))) continue;
            long size = b.getSize(); if (size > 256L * 1024 * 1024) continue;
            byte[] buf = new byte[(int) size]; b.getBytes(b.getStart(), buf);
            blocks.add(new Object[] { b.getStart().getOffset(), buf });
            int start = -1;
            for (int i = 0; i <= buf.length; i++) {
                int ch = i < buf.length ? (buf[i] & 0xFF) : 0;
                boolean ident = ch == '_' || (ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z');
                if (ident) { if (start < 0) start = i; continue; }
                if (start >= 0 && ch == 0 && i - start >= 3 && i - start <= 400) {
                    String m = new String(buf, start, i - start, java.nio.charset.StandardCharsets.US_ASCII);
                    if (itaniumWellFormed(m)) { String name = demangleItanium(m); if (name != null && (name.contains("::") || name.length() >= 3)) nameAt.put(((Long) blocks.get(blocks.size() - 1)[0]) + start, name); }
                }
                start = -1;
            }
        }
        // scan pointer words in data blocks
        Map<Long, Long> typeinfoOf = new HashMap<>();   // typeinfo object addr -> name addr
        List<long[]> words = new ArrayList<>();          // [addr, value] for every aligned word in data blocks
        for (Object[] blk : blocks) {
            long base = (Long) blk[0]; byte[] buf = (byte[]) blk[1];
            for (int i = 0; i + 8 <= buf.length; i += 8) {
                long v = 0; for (int k = 7; k >= 0; k--) v = (v << 8) | (buf[i + k] & 0xFFL);
                if (v == 0) continue;
                words.add(new long[] { base + i, v });
                if (nameAt.containsKey(v)) typeinfoOf.put(base + i - 8, v);   // name pointer sits at typeinfo+8
            }
        }
        // typeinfo sanity: the word at the object start must be a pointer (vptr into a data block)
        Map<Long, Long> tiValid = new HashMap<>();
        for (Map.Entry<Long, Long> e : typeinfoOf.entrySet()) {
            try { long vptr = mem.getLong(toAddr(e.getKey())); if (mem.getBlock(toAddr(vptr)) != null) tiValid.put(e.getKey(), e.getValue()); } catch (MemoryAccessException ignored) {}
        }
        int nv = 0;
        for (Map.Entry<Long, Long> e : tiValid.entrySet()) {
            long ti = e.getKey(); String name = nameAt.get(e.getValue());
            Cls c = classes.computeIfAbsent(name, k -> new Cls());
            if (c.name == null) { c.name = name; c.rttiKind = "ITANIUM_RTTI_STRUCTURAL"; c.typeDescriptor = ti; }
            // bases: si (typeinfo* at +16) or vmi (flags int at +16, count at +20, then {typeinfo*, offset_flags} pairs at +24)
            try {
                long w16 = mem.getLong(toAddr(ti + 16));
                if (tiValid.containsKey(w16)) { c.bases.add(nameAt.get(tiValid.get(w16))); }
                else {
                    int flags = mem.getInt(toAddr(ti + 16)), count = mem.getInt(toAddr(ti + 20));
                    if (flags >= 0 && flags < 16 && count > 0 && count <= 8) for (int k = 0; k < count; k++) { long bt = mem.getLong(toAddr(ti + 24 + k * 16L)); if (tiValid.containsKey(bt)) c.bases.add(nameAt.get(tiValid.get(bt))); }
                }
            } catch (MemoryAccessException ignored) {}
            // vtables: words equal to the typeinfo address whose preceding word is offset_to_top (0 or small negative)
            for (long[] w : words) {
                if (w[1] != ti) continue;
                long a = w[0];
                try {
                    long off = mem.getLong(toAddr(a - 8));
                    if (off != 0 && (off > 0 || off < -65536)) continue;
                    long slots0 = a + 8;
                    if (!isCodeSlot(mem.getLong(toAddr(slots0)))) continue;   // first slot must be code (a function, a PLT stub or an import such as __cxa_pure_virtual)
                    if (c.vtables.contains(a - 8)) continue;
                    c.vtables.add(a - 8);
                    List<Long> slots = new ArrayList<>(); List<String> names = new ArrayList<>();
                    c.slotCounts.add(countSlots(toAddr(a - 8), c.methods, slots, names));
                    c.vtableSlots.add(slots); c.vtableSlotNames.add(names);
                    nv++;
                } catch (MemoryAccessException ignored) {}
            }
        }
        println("structuralItanium: " + nameAt.size() + " typeinfo-name strings, " + tiValid.size() + " typeinfo objects, " + nv + " vtables");
        if (nameAt.size() <= 64) { List<String> dbg = new ArrayList<>(); for (Map.Entry<Long, String> e : nameAt.entrySet()) dbg.add(Long.toHexString(e.getKey()) + "=" + e.getValue()); println("structuralItanium names: " + dbg); }
    }

    /** A vtable slot holds code: a defined function, or a pointer into an executable block / the EXTERNAL block
        (pure virtuals point at the imported __cxa_pure_virtual, which Ghidra keeps in EXTERNAL). Data pointers
        (the next table's typeinfo, a string) end the table. */
    boolean isCodeSlot(long v) {
        if (v == 0) return false;
        try {
            Address t = toAddr(v);
            if (currentProgram.getFunctionManager().getFunctionAt(t) != null) return true;
            MemoryBlock b = currentProgram.getMemory().getBlock(t);
            return b != null && (b.isExecute() || b.getName().toUpperCase().contains("EXTERNAL"));
        } catch (RuntimeException e) { return false; }   // offset_to_top of a secondary table is negative
    }

    String slotName(long v) {
        Address t = toAddr(v);
        Function f = currentProgram.getFunctionManager().getFunctionAt(t);
        if (f != null) { if (f.isThunk() && f.getThunkedFunction(true) != null) return f.getThunkedFunction(true).getName(); return f.getName(); }
        Symbol s = currentProgram.getSymbolTable().getPrimarySymbol(t);
        return s == null ? "" : s.getName();
    }

    int countSlots(Address vt, List<Long> methods, List<Long> slotsOut, List<String> namesOut) {
        int n = 0; Address p = vt; int ptr = currentProgram.getDefaultPointerSize();
        // Itanium ABI: the vtable symbol points at {offset_to_top, typeinfo*}; the function slots start after them
        if (!currentProgram.getExecutableFormat().contains("Portable Executable")) p = p.add(2L * ptr);
        try {
            for (int i = 0; i < 4096; i++) {
                long v = ptr == 8 ? currentProgram.getMemory().getLong(p) : (currentProgram.getMemory().getInt(p) & 0xFFFFFFFFL);
                if (!isCodeSlot(v)) break;
                if (!methods.contains(v)) methods.add(v);
                slotsOut.add(v); namesOut.add(slotName(v));
                n++; p = p.add(ptr);
                // stop at the next symbol (another vtable / RTTI object) so tables do not run together
                if (i > 0 && currentProgram.getSymbolTable().getPrimarySymbol(p) != null) break;
            }
        } catch (MemoryAccessException e) { /* end of readable memory */ }
        return n;
    }

    static String hexList(List<Long> xs) { StringBuilder b = new StringBuilder(); for (int i = 0; i < xs.size(); i++) { if (i > 0) b.append(','); b.append("\"0x").append(Long.toHexString(xs.get(i))).append('"'); } return b.toString(); }
    static String hexLists(List<List<Long>> xs) { StringBuilder b = new StringBuilder("["); for (int i = 0; i < xs.size(); i++) { if (i > 0) b.append(','); b.append('[').append(hexList(xs.get(i))).append(']'); } return b.append(']').toString(); }
    static String strLists(List<List<String>> xs) { StringBuilder b = new StringBuilder("["); for (int i = 0; i < xs.size(); i++) { if (i > 0) b.append(','); b.append('[').append(strList(xs.get(i))).append(']'); } return b.append(']').toString(); }
    static String strList(List<String> xs) { StringBuilder b = new StringBuilder(); for (int i = 0; i < xs.size(); i++) { if (i > 0) b.append(','); b.append(esc(xs.get(i))); } return b.toString(); }
}
