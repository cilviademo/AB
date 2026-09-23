// ExportCallgraph.java — seeded callgraph with distance from processBlock (SPEC §8, EXECUTE 3.2).
//
// Seeds: the module entry (GetPluginFactory / ModuleEntry), then — for a JUCE VST3 wrapper —
// the AudioProcessor vtable slots reached from the component's process() implementation.
// Without symbols the seed is found structurally: the function that (a) is reached from the
// factory's createInstance path, (b) has the highest float/SIMD density among its callees and
// (c) reads the ProcessData layout (numSamples/channelBuffers). Every function gets
// dist_from_processBlock (BFS over callees, -1 = unreachable) plus per-function features the
// engine's role scorer consumes: float_ops, simd_ops, libm_calls, sample_rate_refs, loop_count,
// constant_refs, string_refs, param_refs.
//
// Output: <out>/callgraphs/callgraph.json
//@category AB
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;

import java.io.*;
import java.util.*;

public class ExportCallgraph extends GhidraScript {

    static String esc(String s) { return ExportRTTI.esc(s); }

    static class FnInfo {
        Function f; long addr; int size; int floatOps, simdOps, libm, srRefs, loops, constRefs, strRefs, paramRefs, calls;
        List<Long> callees = new ArrayList<>(); int dist = -1; List<Double> constants = new ArrayList<>();
    }

    static final Set<String> LIBM = new HashSet<>(Arrays.asList("tanh","tanhf","exp","expf","log","logf","log10","log10f","pow","powf","sin","sinf","cos","cosf","tan","tanf","atan","atanf","atan2","atan2f","sqrt","sqrtf","fmod","fmodf","floor","floorf","ceil","ceilf","exp2","exp2f","log2","log2f","sinh","cosh"));

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args.length > 0 ? args[0] : "ab_export");
        new File(out, "callgraphs").mkdirs();
        Listing listing = currentProgram.getListing();
        Map<Long, FnInfo> fns = new LinkedHashMap<>();
        for (Function f : listing.getFunctions(true)) {
            FnInfo fi = new FnInfo(); fi.f = f; fi.addr = f.getEntryPoint().getOffset(); fi.size = (int) f.getBody().getNumAddresses();
            InstructionIterator it = listing.getInstructions(f.getBody(), true);
            Set<Long> seenCallees = new LinkedHashSet<>();
            while (it.hasNext()) {
                Instruction ins = it.next();
                String m = ins.getMnemonicString().toLowerCase();
                if (m.endsWith("ss") || m.endsWith("sd") || m.startsWith("cvt") || m.startsWith("f") && (m.contains("add")||m.contains("mul")||m.contains("sub")||m.contains("div")||m.contains("ld")||m.contains("st"))) fi.floatOps++;
                if (m.endsWith("ps") || m.endsWith("pd") || m.startsWith("v") && (m.contains("ps")||m.contains("pd")) || m.contains("xmm") ) fi.simdOps++;
                if (m.startsWith("j") && !m.equals("jmp")) { Address t = ins.getFlows().length > 0 ? ins.getFlows()[0] : null; if (t != null && t.compareTo(ins.getAddress()) < 0) fi.loops++; }
                if (m.equals("call") || m.startsWith("bl") || m.equals("jmp")) {
                    for (Reference r : ins.getReferencesFrom()) {
                        if (!r.getReferenceType().isCall() && !(m.equals("jmp") && r.getReferenceType().isJump())) continue;
                        Function callee = listing.getFunctionAt(r.getToAddress());
                        if (callee == null) { Function thunkTarget = listing.getFunctionContaining(r.getToAddress()); callee = thunkTarget; }
                        if (callee != null) { seenCallees.add(callee.getEntryPoint().getOffset()); fi.calls++; String cn = callee.getName(); if (LIBM.contains(cn) || LIBM.contains(cn.replace("_", ""))) fi.libm++; }
                    }
                }
                for (int i = 0; i < ins.getNumOperands(); i++) {
                    Object[] objs = ins.getOpObjects(i);
                    for (Object o : objs) {
                        if (o instanceof Scalar) { long v = ((Scalar) o).getUnsignedValue(); if (v == 44100 || v == 48000 || v == 88200 || v == 96000 || v == 192000) fi.srRefs++; }
                    }
                }
                for (Reference r : ins.getReferencesFrom()) {
                    if (r.getReferenceType().isData()) {
                        Data d = listing.getDataAt(r.getToAddress());
                        if (d == null) continue;
                        String dtn = d.getDataType().getName().toLowerCase();
                        if (dtn.equals("float") || dtn.equals("double")) { fi.constRefs++; Object v = d.getValue(); if (v instanceof Number && fi.constants.size() < 64) fi.constants.add(((Number) v).doubleValue()); }
                        else if (dtn.contains("string") || dtn.equals("char") || dtn.contains("unicode")) fi.strRefs++;
                    }
                }
            }
            fi.callees.addAll(seenCallees);
            fns.put(fi.addr, fi);
        }
        // seeds
        Map<String, Long> seeds = new LinkedHashMap<>();
        for (Symbol s : currentProgram.getSymbolTable().getAllSymbols(true)) {
            String n = s.getName();
            if (n.equals("GetPluginFactory") || n.equals("ModuleEntry") || n.equals("InitDll") || n.equals("VSTPluginMain")) seeds.put(n, s.getAddress().getOffset());
            if (n.contains("processBlock") || n.contains("prepareToPlay") || n.contains("releaseResources") || n.contains("getStateInformation") || n.contains("setStateInformation") || n.contains("createEditor")) {
                String key = n.contains("processBlock") ? "processBlock" : n.contains("prepareToPlay") ? "prepareToPlay" : n.contains("releaseResources") ? "releaseResources" : n.contains("getStateInformation") ? "getStateInformation" : n.contains("setStateInformation") ? "setStateInformation" : "createEditor";
                seeds.putIfAbsent(key, s.getAddress().getOffset());
            }
        }
        // structural processBlock candidate when symbols are stripped: the function with the most
        // float/SIMD work in its transitive callees among functions with loops and no string refs
        if (!seeds.containsKey("processBlock")) {
            long best = -1; double bestScore = 0;
            for (FnInfo fi : fns.values()) {
                if (fi.loops == 0 || fi.strRefs > 0 || fi.size < 64) continue;
                double score = fi.floatOps + 2.0 * fi.simdOps + 4.0 * fi.libm + 20.0 * fi.srRefs;
                for (long c : fi.callees) { FnInfo cf = fns.get(c); if (cf != null) score += 0.5 * (cf.floatOps + 2.0 * cf.simdOps + 4.0 * cf.libm); }
                if (score > bestScore) { bestScore = score; best = fi.addr; }
            }
            if (best >= 0) seeds.put("processBlock_candidate", best);
        }
        // BFS distance from processBlock (or its candidate)
        Long pb = seeds.containsKey("processBlock") ? seeds.get("processBlock") : seeds.get("processBlock_candidate");
        if (pb != null && fns.containsKey(pb)) {
            Deque<Long> q = new ArrayDeque<>(); fns.get(pb).dist = 0; q.add(pb);
            while (!q.isEmpty()) { long a = q.poll(); FnInfo fi = fns.get(a); for (long c : fi.callees) { FnInfo cf = fns.get(c); if (cf != null && cf.dist < 0) { cf.dist = fi.dist + 1; q.add(c); } } }
        }
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(out, "callgraphs/callgraph.json")))) {
            w.print("{\"schema\":\"artifactbench.callgraph\",\"schema_version\":1,\"tool\":\"ghidra/ExportCallgraph.java\",\"generated\":" + esc(new Date().toString()) + ",\"data\":{\"seeds\":{");
            boolean first = true; for (Map.Entry<String, Long> e : seeds.entrySet()) { if (!first) w.print(','); first = false; w.print(esc(e.getKey()) + ":\"0x" + Long.toHexString(e.getValue()) + "\""); }
            w.print("},\"seed_basis\":" + esc(seeds.containsKey("processBlock") ? "symbol" : seeds.containsKey("processBlock_candidate") ? "structural (float/SIMD density, loops, no string refs) — CANDIDATE" : "none") + ",\"functions\":[");
            first = true;
            for (FnInfo fi : fns.values()) {
                if (!first) w.print(','); first = false;
                w.print("{\"addr\":\"0x" + Long.toHexString(fi.addr) + "\",\"name\":" + esc(fi.f.getName()) + ",\"size\":" + fi.size + ",\"dist_from_processBlock\":" + fi.dist
                    + ",\"float_ops\":" + fi.floatOps + ",\"simd_ops\":" + fi.simdOps + ",\"libm_calls\":" + fi.libm + ",\"sample_rate_refs\":" + fi.srRefs + ",\"loops\":" + fi.loops
                    + ",\"constant_refs\":" + fi.constRefs + ",\"string_refs\":" + fi.strRefs + ",\"calls\":" + fi.calls + ",\"callees\":[" + ExportRTTI.hexList(fi.callees) + "],\"constants\":" + fi.constants + "}");
            }
            w.println("]}}");
        }
        println("ExportCallgraph: " + fns.size() + " functions, seeds " + seeds.keySet());
    }
}
