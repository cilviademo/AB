// ExportDecompiled.java — Ghidra headless post-script.
// Decompiles every function, demangles C++ names, groups output into one .cpp per
// class/namespace, and ranks functions by "DSP likelihood" (float ops, constants,
// calls to tanh/exp/log/sin, loop density) so you port the signal chain first.
//
// Usage (called by vst_recover.py):
//   analyzeHeadless <proj> <name> -import plugin.dll -postScript ExportDecompiled.java <outDir>
//@category VSTRecover

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.app.util.demangler.DemangledObject;
import ghidra.app.util.demangler.DemanglerUtil;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.*;

public class ExportDecompiled extends GhidraScript {

    static final String[] DSP_CALLS = { "tanh", "tanhf", "exp", "expf", "log", "logf", "log10", "pow", "powf",
            "sin", "sinf", "cos", "cosf", "sqrt", "sqrtf", "atan", "fabs", "floor", "ceil" };

    static class Row {
        String name, cls; Address addr; int score; int floatOps; int calls; int size; String code;
    }

    @Override
    protected void run() throws Exception {
        String[] a = getScriptArgs();
        File out = new File(a.length > 0 ? a[0] : "decompiled");
        File classes = new File(out, "classes");
        classes.mkdirs();

        DecompInterface ifc = new DecompInterface();
        ifc.toggleCCode(true);
        ifc.toggleSyntaxTree(false);
        ifc.setSimplificationStyle("decompile");
        ifc.openProgram(currentProgram);

        List<Row> rows = new ArrayList<>();
        Map<String, List<Row>> byClass = new TreeMap<>();
        Map<String, Integer> stringRefs = new HashMap<>();

        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        int n = 0;
        while (it.hasNext() && !monitor.isCancelled()) {
            Function f = it.next();
            if (f.isThunk() || f.isExternal()) continue;
            n++;
            monitor.setMessage("Decompiling " + n + ": " + f.getName());

            Row r = new Row();
            r.addr = f.getEntryPoint();
            r.name = demangle(f.getName());
            r.cls = classOf(r.name);
            r.size = (int) f.getBody().getNumAddresses();

            // score: count float/SSE instructions + libm calls
            InstructionIterator ii = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (ii.hasNext()) {
                Instruction ins = ii.next();
                String m = ins.getMnemonicString().toLowerCase();
                if (m.endsWith("ss") || m.endsWith("sd") || m.endsWith("ps") || m.endsWith("pd") || m.startsWith("f") || m.startsWith("cvt"))
                    r.floatOps++;
                if (m.startsWith("call")) {
                    r.calls++;
                    for (Reference ref : ins.getReferencesFrom()) {
                        Symbol s = getSymbolAt(ref.getToAddress());
                        if (s == null) continue;
                        String sn = s.getName().toLowerCase();
                        for (String d : DSP_CALLS) if (sn.equals(d) || sn.endsWith("::" + d)) r.score += 25;
                    }
                }
                for (Reference ref : ins.getReferencesFrom()) {
                    Object dat = getDataAt(ref.getToAddress()) == null ? null : getDataAt(ref.getToAddress()).getValue();
                    if (dat instanceof String) stringRefs.merge(r.name, 1, Integer::sum);
                }
            }
            r.score += Math.min(r.floatOps, 400);
            if (r.name.toLowerCase().matches(".*(process|render|filter|limit|satur|drive|oversampl|compress|eq|shelf|biquad|svf|lookahead|tanh|adaa|lufs|peak|meter).*"))
                r.score += 150;
            if (r.name.toLowerCase().matches(".*(paint|resized|mouse|lookandfeel|draw|component|button|slider|label|timer).*"))
                r.score -= 100; // UI: still exported, just not in the DSP list

            DecompileResults res = ifc.decompileFunction(f, 60, monitor);
            r.code = (res != null && res.decompileCompleted()) ? res.getDecompiledFunction().getC()
                    : "// decompile failed: " + (res == null ? "null" : res.getErrorMessage());
            rows.add(r);
            byClass.computeIfAbsent(r.cls, k -> new ArrayList<>()).add(r);
        }

        // one .cpp per class / namespace
        for (Map.Entry<String, List<Row>> e : byClass.entrySet()) {
            String fn = e.getKey().replaceAll("[^A-Za-z0-9_]", "_");
            if (fn.isEmpty()) fn = "_global";
            try (PrintWriter w = new PrintWriter(new FileWriter(new File(classes, fn + ".cpp")))) {
                w.println("// ===== Recovered from binary: " + e.getKey() + " =====");
                w.println("// " + e.getValue().size() + " functions. Names are demangled where symbols survived;");
                w.println("// FUN_xxxx names mean the symbol was stripped — infer role from body + dsp_candidates.md.");
                w.println();
                for (Row r : e.getValue()) {
                    w.println("// ---- " + r.name + " @ " + r.addr + "  (size " + r.size + ", floatOps " + r.floatOps + ", dspScore " + r.score + ")");
                    w.println(r.code);
                    w.println();
                }
            }
        }

        // symbol map
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(out, "symbols.tsv")))) {
            w.println("address\tclass\tfunction\tsize\tfloatOps\tdspScore");
            for (Row r : rows) w.println(r.addr + "\t" + r.cls + "\t" + r.name + "\t" + r.size + "\t" + r.floatOps + "\t" + r.score);
        }

        // DSP ranking
        rows.sort((x, y) -> Integer.compare(y.score, x.score));
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(out, "dsp_candidates.md")))) {
            w.println("# DSP candidates (highest first) — port these into clean classes");
            w.println();
            w.println("| rank | dspScore | floatOps | size | class | function | file |");
            w.println("|---|---|---|---|---|---|---|");
            int k = 0;
            for (Row r : rows) {
                if (r.score <= 0 || k >= 150) break;
                k++;
                w.println("| " + k + " | " + r.score + " | " + r.floatOps + " | " + r.size + " | " + r.cls + " | `" + r.name
                        + "` | classes/" + r.cls.replaceAll("[^A-Za-z0-9_]", "_") + ".cpp |");
            }
            w.println();
            w.println("Tips: constants like 0.5f, 1.4142f, 6.2831853f, 20.0/20000.0 mark filter/oversampling code;");
            w.println("look for exp(-1/(sr*t)) shapes = envelope coefficients; tanh/ADAA = saturation; ");
            w.println("max()/abs() ladders with a delay line = true-peak limiter.");
        }

        // string-reference map (which functions touch which UI/preset/licence strings)
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(out, "string_refs.tsv")))) {
            w.println("function\tstringRefs");
            stringRefs.entrySet().stream().sorted((p, q) -> q.getValue() - p.getValue())
                    .forEach(en -> w.println(en.getKey() + "\t" + en.getValue()));
        }

        ifc.dispose();
        println("Exported " + rows.size() + " functions into " + byClass.size() + " class files -> " + out);
    }

    String demangle(String name) {
        try {
            DemangledObject d = DemanglerUtil.demangle(currentProgram, name);
            if (d != null && d.getSignature(false) != null) return d.getSignature(false);
        } catch (Exception ignored) { }
        return name;
    }

    String classOf(String demangled) {
        // "juce::Slider::mouseDrag(...)"  -> "juce::Slider" ; "BTZ::ADAATanh::process(...)" -> "BTZ::ADAATanh"
        String s = demangled.replaceAll("\\(.*$", "");
        int i = s.lastIndexOf("::");
        if (i < 0) return demangled.startsWith("FUN_") ? "_stripped" : "_global";
        String cls = s.substring(0, i).replaceAll("^.*\\s", "");
        return cls.isEmpty() ? "_global" : cls;
    }
}
