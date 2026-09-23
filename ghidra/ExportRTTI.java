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
import ghidra.program.model.mem.MemoryAccessException;
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
                c.slotCounts.add(countSlots(s.getAddress(), c.methods));
            }
        }
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
                    + ",\"methods\":[" + hexList(c.methods) + "],\"ctor_dtor_candidates\":[" + hexList(c.ctorDtor) + "]}");
            }
            w.println("]}");
        }
        println("ExportRTTI: " + classes.size() + " classes -> " + out);
    }

    int countSlots(Address vt, List<Long> methods) {
        int n = 0; Address p = vt; int ptr = currentProgram.getDefaultPointerSize();
        // Itanium ABI: the vtable symbol points at {offset_to_top, typeinfo*}; the function slots start after them
        if (!currentProgram.getExecutableFormat().contains("Portable Executable")) p = p.add(2L * ptr);
        try {
            for (int i = 0; i < 4096; i++) {
                long v = ptr == 8 ? currentProgram.getMemory().getLong(p) : (currentProgram.getMemory().getInt(p) & 0xFFFFFFFFL);
                Address target = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(v);
                Function f = currentProgram.getFunctionManager().getFunctionAt(target);
                if (f == null) break;
                if (!methods.contains(target.getOffset())) methods.add(target.getOffset());
                n++; p = p.add(ptr);
                // stop at the next symbol (another vtable / RTTI object) so tables do not run together
                if (i > 0 && currentProgram.getSymbolTable().getPrimarySymbol(p) != null) break;
            }
        } catch (MemoryAccessException e) { /* end of readable memory */ }
        return n;
    }

    static String hexList(List<Long> xs) { StringBuilder b = new StringBuilder(); for (int i = 0; i < xs.size(); i++) { if (i > 0) b.append(','); b.append("\"0x").append(Long.toHexString(xs.get(i))).append('"'); } return b.toString(); }
    static String strList(List<String> xs) { StringBuilder b = new StringBuilder(); for (int i = 0; i < xs.size(); i++) { if (i > 0) b.append(','); b.append(esc(xs.get(i))); } return b.toString(); }
}
