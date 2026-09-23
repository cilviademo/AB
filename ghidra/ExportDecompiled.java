// ExportDecompiled.java — v1 kit script upgraded for AB (SPEC §8.2–8.4, EXECUTE 3.2/3.3).
//
// Writes under <out>/decompiler/:
//   classes/<Class>.cpp      one pseudo-C file per class/namespace (EVIDENCE, never source)
//   functions.json           every function: address, names (raw → demangled), class, role features,
//                            noise flag (CRT/EH/alloc/refcount/thunk/JUCE plumbing), wrapper flag
//   dsp_candidates.json/.md  ranked DSP candidates (score from features; the engine re-scores with
//                            the callgraph distance and marks roles CANDIDATE|VERIFIED_CALLGRAPH)
//   symbol_map.json          raw → inferred → final names, all retained (never overwritten)
//   binarydata_resolution.json  JUCE BinaryData name → bytes (sha256, size) resolved by decompiling
//                            getNamedResource (name hash → size + pointer) and hashing the bytes
//                            straight out of program memory (§8.4): the only VERIFIED mapping path.
// Noise is *hidden from human output* but retained with addresses in functions.json.
//@category AB
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.util.demangler.DemangledObject;
import ghidra.app.util.demangler.DemanglerUtil;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.DataType;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.symbol.*;
import ghidra.util.task.TaskMonitor;

import java.io.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.regex.*;

public class ExportDecompiled extends GhidraScript {

    static String esc(String s) { return ExportRTTI.esc(s); }

    static final Pattern NOISE = Pattern.compile("(?i)^(_|__|\\?\\?|FUN_)?(security_cookie|__security|_CxxThrow|__CxxFrameHandler|_CxxFrame|__GSHandler|__std_|_std_|__scrt|_scrt|__acrt|_acrt|__vcrt|_vcrt|__dyn_tls|_initterm|_onexit|atexit|__C_specific|_RTC_|__chkstk|_alloca|memcpy|memset|memmove|malloc|free|operator new|operator delete|_purecall|__report|__telemetry|__isa_|_Unwind|__cxa_|__gxx_personality|_ZSt|_ZNSt|_ZNKSt|_ZdlPv|_Znwm|_ZdaPv|_Znam|__gnu_cxx|_init|_fini|frame_dummy|register_tm_clones|deregister_tm_clones|__do_global|__libc)");
    static final Pattern JUCE_PLUMBING = Pattern.compile("(?i)^(juce::|_ZN4juce|\\?.*@juce@@)");
    static final Pattern REFCOUNT = Pattern.compile("(?i)(AddRef|Release|incReferenceCount|decReferenceCount|ReferenceCountedObject|queryInterface|FUnknown)");

    static class Row { long addr; String raw, demangled, cls, leaf; int size; boolean noise, wrapper, thunk; String noiseKind = null; int floatOps, calls, strRefs; String code; Function fn; }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args.length > 0 ? args[0] : "ab_export");
        File dec = new File(out, "decompiler"); new File(dec, "classes").mkdirs();
        int maxFunctions = args.length > 1 ? Integer.parseInt(args[1]) : 20000;
        DecompInterface ifc = new DecompInterface();
        DecompileOptions opts = new DecompileOptions(); ifc.setOptions(opts); ifc.toggleCCode(true); ifc.setSimplificationStyle("decompile");
        ifc.openProgram(currentProgram);
        Listing listing = currentProgram.getListing();
        List<Row> rows = new ArrayList<>();
        Map<String, List<Row>> byClass = new TreeMap<>();
        for (Function f : listing.getFunctions(true)) {
            monitor.checkCancelled();
            Row r = new Row(); r.addr = f.getEntryPoint().getOffset(); r.raw = f.getName(); r.size = (int) f.getBody().getNumAddresses();
            r.demangled = demangle(f); r.cls = classOf(f, r.demangled); r.leaf = leafOf(r.demangled);
            r.thunk = f.isThunk();
            r.noise = r.thunk || NOISE.matcher(r.raw).find() || NOISE.matcher(r.demangled).find() || f.isExternal();
            if (r.noise) r.noiseKind = r.thunk ? "IMPORT_THUNK" : f.isExternal() ? "EXTERNAL" : "CRT_EH_ALLOC";
            else if (JUCE_PLUMBING.matcher(r.demangled).find()) { r.noise = true; r.noiseKind = "FRAMEWORK_PLUMBING"; }
            else if (REFCOUNT.matcher(r.demangled).find()) { r.noise = true; r.noiseKind = "REFCOUNT"; }
            InstructionIterator it = listing.getInstructions(f.getBody(), true); int ins = 0;
            while (it.hasNext()) { Instruction i = it.next(); ins++; String m = i.getMnemonicString().toLowerCase(); if (m.endsWith("ss") || m.endsWith("sd") || m.endsWith("ps") || m.endsWith("pd") || m.startsWith("cvt")) r.floatOps++; if (m.equals("call")) r.calls++; for (Reference ref : i.getReferencesFrom()) if (ref.getReferenceType().isData()) { Data d = listing.getDataAt(ref.getToAddress()); if (d != null && d.getDataType().getName().toLowerCase().contains("string")) r.strRefs++; } }
            // forward-only wrapper: tiny body, exactly one call, no float work
            r.wrapper = !r.noise && ins <= 12 && r.calls == 1 && r.floatOps == 0;
            r.fn = f;
            rows.add(r);
        }
        // pass 2: decompile only the top maxFunctions non-noise functions by DSP-likelihood
        // (float work first, size second, string-heavy functions last) — was every function (hours on JUCE binaries)
        List<Row> todo = new ArrayList<>();
        for (Row r : rows) if (!r.noise && r.size <= 400000) todo.add(r);
        todo.sort((a, b) -> Integer.compare(b.floatOps * 4 + Math.min(b.size, 4096) / 16 - b.strRefs * 8, a.floatOps * 4 + Math.min(a.size, 4096) / 16 - a.strRefs * 8));
        int done = 0;
        for (Row r : todo) {
            if (done++ >= maxFunctions) break;
            monitor.checkCancelled();
            DecompileResults res = ifc.decompileFunction(r.fn, 60, monitor);
            r.code = res != null && res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed: " + (res == null ? "null" : res.getErrorMessage());
            byClass.computeIfAbsent(r.cls, k -> new ArrayList<>()).add(r);
        }
        println("ExportDecompiled: features for " + rows.size() + " functions; decompiled top " + Math.min(done, maxFunctions) + " of " + todo.size() + " candidates");
        // per-class evidence files (hidden noise excluded; wrappers annotated)
        for (Map.Entry<String, List<Row>> e : byClass.entrySet()) {
            String fname = classFile(e.getKey());
            try (PrintWriter w = new PrintWriter(new FileWriter(new File(dec, "classes/" + fname + ".cpp")))) {
                w.println("// EVIDENCE (decompiler pseudo-C) for " + e.getKey() + " — NOT source. Addresses are the provenance; port via human_source/ only with evidence.");
                for (Row r : e.getValue()) { w.println("\n// ---- 0x" + Long.toHexString(r.addr) + " raw=" + r.raw + " demangled=" + r.demangled + (r.wrapper ? " [FORWARD_WRAPPER — collapsed in human output]" : "") + " float_ops=" + r.floatOps); w.println(r.code == null ? "// (not decompiled)" : r.code); }
            }
        }
        // functions.json
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(dec, "functions.json")))) {
            w.print("{\"schema\":\"artifactbench.decompiled_functions\",\"schema_version\":1,\"tool\":\"ghidra/ExportDecompiled.java\",\"generated\":" + esc(new Date().toString()) + ",\"data\":[");
            boolean first = true;
            for (Row r : rows) { if (!first) w.print(','); first = false; w.print("{\"addr\":\"0x" + Long.toHexString(r.addr) + "\",\"raw\":" + esc(r.raw) + ",\"demangled\":" + esc(r.demangled) + ",\"class\":" + esc(r.cls) + ",\"leaf\":" + esc(r.leaf) + ",\"size\":" + r.size + ",\"noise\":" + r.noise + ",\"noise_kind\":" + esc(r.noiseKind) + ",\"wrapper\":" + r.wrapper + ",\"float_ops\":" + r.floatOps + ",\"calls\":" + r.calls + ",\"string_refs\":" + r.strRefs + ",\"file\":" + esc(r.code == null ? null : "01_evidence/decompiler/classes/" + classFile(r.cls) + ".cpp") + "}"); }
            w.println("]}");
        }
        // symbol_map.json: raw → inferred (demangled) → final (empty until the engine names it)
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(dec, "symbol_map.json")))) {
            w.print("{\"schema\":\"artifactbench.symbol_map\",\"schema_version\":1,\"tool\":\"ghidra/ExportDecompiled.java\",\"generated\":" + esc(new Date().toString()) + ",\"data\":[");
            boolean first = true; for (Row r : rows) { if (!first) w.print(','); first = false; w.print("{\"addr\":\"0x" + Long.toHexString(r.addr) + "\",\"raw\":" + esc(r.raw) + ",\"inferred\":" + esc(r.demangled.equals(r.raw) ? null : r.demangled) + ",\"final\":null,\"status\":" + esc(r.raw.startsWith("FUN_") ? "GENERATED" : "VERIFIED_SYMBOL") + "}"); }
            w.println("]}");
        }
        // preliminary DSP ranking (the engine re-ranks with callgraph distance and parameter/state refs)
        List<Row> cands = new ArrayList<>(); for (Row r : rows) if (!r.noise && !r.wrapper && r.floatOps > 0) cands.add(r);
        cands.sort((a, b) -> Integer.compare(b.floatOps * 4 + b.size / 16 - b.strRefs * 8, a.floatOps * 4 + a.size / 16 - a.strRefs * 8));
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(dec, "dsp_candidates.json")))) {
            w.print("{\"schema\":\"artifactbench.dsp_candidates\",\"schema_version\":1,\"tool\":\"ghidra/ExportDecompiled.java\",\"generated\":" + esc(new Date().toString()) + ",\"data\":[");
            boolean first = true; int k = 0; for (Row r : cands) { if (k++ >= 200) break; if (!first) w.print(','); first = false; w.print("{\"addr\":\"0x" + Long.toHexString(r.addr) + "\",\"name\":" + esc(r.demangled) + ",\"class\":" + esc(r.cls) + ",\"float_ops\":" + r.floatOps + ",\"size\":" + r.size + ",\"string_refs\":" + r.strRefs + ",\"basis\":\"float density (static); role and distance assigned by the engine\"}"); }
            w.println("]}");
        }
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(dec, "dsp_candidates.md")))) {
            w.println("# DSP candidates (preliminary, float density) — EVIDENCE, re-ranked by the engine with callgraph distance\n"); w.println("| # | float ops | size | class | function | file |"); w.println("|---|---|---|---|---|---|");
            int k = 0; for (Row r : cands) { if (k++ >= 150) break; w.println("| " + k + " | " + r.floatOps + " | " + r.size + " | " + r.cls + " | `" + r.demangled + "` | classes/" + classFile(r.cls) + ".cpp |"); }
        }
        // BinaryData resolution (§8.4)
        resolveBinaryData(dec, ifc, rows);
        ifc.dispose();
        println("ExportDecompiled: " + rows.size() + " functions, " + byClass.size() + " class files, " + cands.size() + " DSP candidates -> " + dec);
    }

    /** JUCE BinaryData::getNamedResource(const char* name, int& size): a switch over a name hash
        returning {size, pointer}. The strings in namedResourceList are the names. We decompile every
        function that references those strings or looks like the switch, pull (numBytes, pointer)
        pairs out of the pseudo-C, read the bytes from memory and hash them. */
    void resolveBinaryData(File dec, DecompInterface ifc, List<Row> rows) throws Exception {
        Listing listing = currentProgram.getListing(); Memory mem = currentProgram.getMemory();
        List<String> names = new ArrayList<>(); List<Address> nameAddrs = new ArrayList<>();
        for (Data d : listing.getDefinedData(true)) {
            if (!d.getDataType().getName().toLowerCase().contains("string")) continue;
            Object v = d.getValue(); if (!(v instanceof String)) continue;
            String s = (String) v;
            if (s.matches("[A-Za-z][\\w-]{2,40}_(png|jpg|jpeg|svg|ttf|otf|xml|json|wav|aiff|txt)")) { names.add(s); nameAddrs.add(d.getAddress()); }
        }
        List<String> entries = new ArrayList<>(); int resolvedBySymbol = 0;
        // candidate functions: reference a name string, or contain a switch with many `return` of pointers,
        // or (symbol-free, the real case) compare against the JUCE name hash of a known resource name:
        //   getNamedResource: hash = (hash << 5) - hash + c  (== 31*hash + c, int wrap) → switch (hash) { case 0x…: }
        Set<Long> visited = new HashSet<>();
        Set<Long> hashes = new HashSet<>();
        for (String nm : names) { int h = 0; for (char c : nm.toCharArray()) h = 31 * h + c; hashes.add((long) h & 0xFFFFFFFFL); hashes.add((long) h); }
        if (!hashes.isEmpty()) {
            InstructionIterator all = listing.getInstructions(true);
            while (all.hasNext()) {
                Instruction ins = all.next();
                for (int op = 0; op < ins.getNumOperands(); op++) {
                    for (Object o : ins.getOpObjects(op)) {
                        if (o instanceof ghidra.program.model.scalar.Scalar) {
                            long v = ((ghidra.program.model.scalar.Scalar) o).getUnsignedValue();
                            long sv = ((ghidra.program.model.scalar.Scalar) o).getSignedValue();
                            if (hashes.contains(v) || hashes.contains(sv) || hashes.contains(sv & 0xFFFFFFFFL)) { Function f = listing.getFunctionContaining(ins.getAddress()); if (f != null) visited.add(f.getEntryPoint().getOffset()); }
                        }
                    }
                }
            }
        }
        for (Address a : nameAddrs) for (Reference r : currentProgram.getReferenceManager().getReferencesTo(a)) { Function f = listing.getFunctionContaining(r.getFromAddress()); if (f != null) visited.add(f.getEntryPoint().getOffset()); }
        for (Row row : rows) if (!row.noise && row.code != null && row.code.contains("switch") && row.code.split("return").length > 3) visited.add(row.addr);
        Pattern pair = Pattern.compile("\\*\\s*(?:param_2|[A-Za-z_]\\w*)\\s*=\\s*(0x[0-9a-fA-F]+|\\d+)\\s*;\\s*(?:\\n\\s*)?(?:return\\s+|\\w+\\s*=\\s*)(?:\\(char\\s*\\*\\)\\s*)?&?\\s*(?:BinaryData::)?([A-Za-z_]\\w*|0x[0-9a-fA-F]+|DAT_[0-9a-fA-F]+|PTR_[0-9a-fA-F_]+)");
        // Path 1 (symbols survive, e.g. ELF .dynsym): BinaryData::<name> data + BinaryData::<name>Size int → bytes hashed directly
        for (int i = 0; i < names.size(); i++) {
            String nm = names.get(i);
            Address dataAddr = null; Address sizeAddr = null;
            for (Symbol sy : currentProgram.getSymbolTable().getSymbols(nm)) { Namespace ns = sy.getParentNamespace(); if (ns != null && ns.getName().equals("BinaryData")) { dataAddr = sy.getAddress(); break; } }
            for (Symbol sy : currentProgram.getSymbolTable().getSymbols(nm + "Size")) { Namespace ns = sy.getParentNamespace(); if (ns != null && ns.getName().equals("BinaryData")) { sizeAddr = sy.getAddress(); break; } }
            if (dataAddr == null || sizeAddr == null) continue;
            try {
                long size = mem.getInt(sizeAddr) & 0xFFFFFFFFL;
                if (size <= 0 || size > 200_000_000L) continue;
                byte[] bytes = new byte[(int) size]; mem.getBytes(dataAddr, bytes);
                String sha = ExportRTTI.esc(hexOf(MessageDigest.getInstance("SHA-256").digest(bytes)));
                entries.add("{\"name\":" + esc(nm) + ",\"basis\":\"symbol BinaryData::" + nm + " + " + nm + "Size\",\"size\":" + size + ",\"pointer\":\"0x" + Long.toHexString(dataAddr.getOffset()) + "\",\"sha256\":" + sha + ",\"head_hex\":\"" + hexOf(Arrays.copyOf(bytes, Math.min(8, bytes.length))) + "\"}");
                resolvedBySymbol++;
            } catch (MemoryAccessException e) { /* unreadable */ }
        }
        int resolved = 0;
        for (long addr : visited) {
            Function f = listing.getFunctionAt(currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(addr)); if (f == null) continue;
            DecompileResults res = ifc.decompileFunction(f, 60, monitor); if (res == null || !res.decompileCompleted()) continue;
            String c = res.getDecompiledFunction().getC();
            // every candidate's pseudo-C is kept as evidence (also what a person needs to check a 0-resolved run)
            File cdir = new File(dec, "binarydata_candidates"); cdir.mkdirs();
            try (PrintWriter cw = new PrintWriter(new FileWriter(new File(cdir, "0x" + Long.toHexString(addr) + ".c")))) { cw.print(c); } catch (IOException ignored) {}
            Matcher m = pair.matcher(c);
            while (m.find()) {
                long size = m.group(1).startsWith("0x") ? Long.parseLong(m.group(1).substring(2), 16) : Long.parseLong(m.group(1));
                if (size <= 0 || size > 200_000_000L) continue;
                String sym = m.group(2); Address ptr = null;
                if (sym.startsWith("0x")) ptr = toAddr(Long.parseLong(sym.substring(2), 16));
                else if (sym.startsWith("DAT_") || sym.startsWith("PTR_")) { String hx = sym.replaceAll("^(DAT|PTR)_", "").replaceAll("_.*$", ""); try { ptr = toAddr(Long.parseLong(hx, 16)); } catch (NumberFormatException ignored) {} }
                else { List<Symbol> ss = currentProgram.getSymbolTable().getGlobalSymbols(sym); if (!ss.isEmpty()) ptr = ss.get(0).getAddress(); }
                if (ptr == null) continue;
                if (sym.startsWith("PTR_")) { try { long v = currentProgram.getDefaultPointerSize() == 8 ? mem.getLong(ptr) : (mem.getInt(ptr) & 0xFFFFFFFFL); ptr = toAddr(v); } catch (MemoryAccessException e) { continue; } }
                byte[] bytes = new byte[(int) size];
                try { mem.getBytes(ptr, bytes); } catch (MemoryAccessException e) { continue; }
                String sha = ExportRTTI.esc(hexOf(MessageDigest.getInstance("SHA-256").digest(bytes)));
                entries.add("{\"function\":\"0x" + Long.toHexString(addr) + "\",\"size\":" + size + ",\"pointer\":\"0x" + Long.toHexString(ptr.getOffset()) + "\",\"sha256\":" + sha + ",\"head_hex\":\"" + hexOf(Arrays.copyOf(bytes, Math.min(8, bytes.length))) + "\"}");
                resolved++;
            }
        }
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(dec, "binarydata_resolution.json")))) {
            w.print("{\"schema\":\"artifactbench.binarydata_resolution\",\"schema_version\":1,\"tool\":\"ghidra/ExportDecompiled.java\",\"generated\":" + esc(new Date().toString()) + ",\"data\":{\"names\":[" + ExportRTTI.strList(names) + "],\"name_addresses\":[");
            for (int i = 0; i < nameAddrs.size(); i++) { if (i > 0) w.print(','); w.print("\"0x" + Long.toHexString(nameAddrs.get(i).getOffset()) + "\""); }
            w.print("],\"resources\":[" + String.join(",", entries) + "],\"method\":\"getNamedResource decompile → (size, pointer) → bytes hashed from program memory\"}}");
        }
        println("BinaryData: " + names.size() + " names, " + resolvedBySymbol + " resolved by symbol, " + resolved + " (size,pointer) pairs from getNamedResource; " + visited.size() + " candidate functions (hash-immediate / string-ref / switch)");
    }

    /** File name for a class evidence file: sanitized, and shortened with a hash when longer than 80 chars (template lambdas exceed NAME_MAX). */
    static String classFile(String cls) {
        String f = cls.replaceAll("[^A-Za-z0-9_]", "_"); if (f.isEmpty()) f = "_global";
        if (f.length() > 80) f = f.substring(0, 64) + "_" + String.format("%08x", cls.hashCode());
        return f;
    }

    static String hexOf(byte[] b) { StringBuilder sb = new StringBuilder(); for (byte x : b) sb.append(String.format("%02x", x)); return sb.toString(); }

    String demangle(Function f) {
        try { DemangledObject d = DemanglerUtil.demangle(currentProgram, f.getName()); if (d != null && d.getSignature(false) != null) return d.getSignature(false); } catch (Exception ignored) {}
        Namespace ns = f.getParentNamespace();
        return (ns != null && !ns.isGlobal()) ? ns.getName(true) + "::" + f.getName() : f.getName();
    }
    static String classOf(Function f, String demangled) {
        Namespace ns = f.getParentNamespace();
        if (ns != null && !ns.isGlobal()) return ns.getName(true);
        String s = demangled.replaceAll("\\(.*$", ""); int i = s.lastIndexOf("::");
        if (i < 0) return demangled.startsWith("FUN_") ? "_stripped" : "_global";
        String cls = s.substring(0, i).replaceAll("^.*\\s", ""); return cls.isEmpty() ? "_global" : cls;
    }
    static String leafOf(String demangled) { String s = demangled.replaceAll("\\(.*$", ""); int i = s.lastIndexOf("::"); return i < 0 ? s : s.substring(i + 2); }
}
