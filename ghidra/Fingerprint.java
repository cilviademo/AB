// Fingerprint.java — implementation fingerprints per function and class (SPEC §8.1, EXECUTE 3.2).
//
// Per function, stored separately and never merged:
//   RAW_BYTE_HASH                 sha256 of the function bytes
//   NORMALIZED_INSTRUCTION_HASH   sha256 of mnemonics + operand *shapes*: registers kept,
//                                 immediates kept unless they are addresses/relocations or
//                                 stack offsets (masked as ADDR / STACK), so the same source
//                                 function linked at another address hashes the same
//   CFG_SIGNATURE                 basic-block count + sha256 of the edge shape (block index pairs)
//   CALLGRAPH_SIGNATURE           sha256 of the sorted multiset of callee NORMALIZED hashes (depth 1)
//   CONSTANT_SIGNATURE            sorted float/int immediates and referenced float/double data
//   STRING_XREF_SIGNATURE         sha256 of the sorted referenced string literals
//   RTTI_XREF / VTABLE_SLOT       class name and slot index when the function sits in a vtable
// Class fingerprint = RTTI name + vtable slot fingerprints + ctor/dtor fingerprints + member-offset access pattern.
//
// Output: <out>/decompiler/fingerprints.json
//@category AB
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.block.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import ghidra.util.task.TaskMonitor;

import java.io.*;
import java.security.MessageDigest;
import java.util.*;

public class Fingerprint extends GhidraScript {

    static String esc(String s) { return ExportRTTI.esc(s); }
    static String hex(byte[] b) { StringBuilder sb = new StringBuilder(); for (byte x : b) sb.append(String.format("%02x", x)); return sb.toString(); }
    static String sha(String s) throws Exception { return hex(MessageDigest.getInstance("SHA-256").digest(s.getBytes("UTF-8"))); }
    static String sha(byte[] b) throws Exception { return hex(MessageDigest.getInstance("SHA-256").digest(b)); }

    static class FP { long addr; String name; int size; String raw, norm, cfg, callg, strx; int blocks; List<String> consts = new ArrayList<>(); String rtti; int slot = -1; List<Integer> memberOffsets = new ArrayList<>(); }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args.length > 0 ? args[0] : "ab_export");
        new File(out, "decompiler").mkdirs();
        Listing listing = currentProgram.getListing();
        BasicBlockModel bbm = new BasicBlockModel(currentProgram);
        Map<Long, FP> all = new LinkedHashMap<>();
        Map<Long, List<Long>> callees = new HashMap<>();

        // vtable slot ownership
        Map<Long, String> slotOwner = new HashMap<>(); Map<Long, Integer> slotIndex = new HashMap<>();
        int ptr = currentProgram.getDefaultPointerSize();
        for (Symbol s : currentProgram.getSymbolTable().getAllSymbols(true)) {
            String n = s.getName();
            if (!(n.startsWith("vftable") || n.contains("::vftable") || n.equals("vtable") || n.startsWith("vtable_"))) continue;
            Namespace ns = s.getParentNamespace(); if (ns == null || ns.isGlobal()) continue;
            Address p = s.getAddress();
            try {
                for (int i = 0; i < 2048; i++) {
                    long v = ptr == 8 ? currentProgram.getMemory().getLong(p) : (currentProgram.getMemory().getInt(p) & 0xFFFFFFFFL);
                    Function f = listing.getFunctionAt(currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(v));
                    if (f == null) break;
                    slotOwner.putIfAbsent(f.getEntryPoint().getOffset(), ns.getName(true)); slotIndex.putIfAbsent(f.getEntryPoint().getOffset(), i);
                    p = p.add(ptr); if (i > 0 && currentProgram.getSymbolTable().getPrimarySymbol(p) != null) break;
                }
            } catch (MemoryAccessException ignored) {}
        }

        for (Function f : listing.getFunctions(true)) {
            FP fp = new FP(); fp.addr = f.getEntryPoint().getOffset(); fp.name = f.getName(true); fp.size = (int) f.getBody().getNumAddresses();   // qualified name (namespace::class::method) so a learned name hint carries its class
            // raw bytes
            ByteArrayOutputStream raw = new ByteArrayOutputStream();
            StringBuilder norm = new StringBuilder(); TreeSet<String> strs = new TreeSet<>(); List<Long> cl = new ArrayList<>();
            InstructionIterator it = listing.getInstructions(f.getBody(), true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                try { raw.write(ins.getBytes()); } catch (MemoryAccessException ignored) {}
                norm.append(ins.getMnemonicString());
                for (int i = 0; i < ins.getNumOperands(); i++) {
                    norm.append(' ');
                    for (Object o : ins.getOpObjects(i)) {
                        if (o instanceof ghidra.program.model.lang.Register) norm.append(((ghidra.program.model.lang.Register) o).getName());
                        else if (o instanceof Scalar) {
                            long v = ((Scalar) o).getSignedValue();
                            boolean isAddr = false;
                            for (Reference r : ins.getReferencesFrom()) if (r.getOperandIndex() == i && (r.getReferenceType().isData() || r.getReferenceType().isCall() || r.getReferenceType().isJump())) isAddr = true;
                            boolean isStack = false; for (Object o2 : ins.getOpObjects(i)) if (o2 instanceof ghidra.program.model.lang.Register && ((ghidra.program.model.lang.Register) o2).getName().matches("(?i)r?[se]bp|r?[se]sp|sp|fp")) isStack = true;
                            if (isAddr) norm.append("ADDR"); else if (isStack) norm.append("STACK"); else { norm.append(v); fp.consts.add(Long.toString(v)); }
                            if (isStack && !isAddr && Math.abs(v) < 4096 && fp.memberOffsets.size() < 64) { /* stack, not member */ }
                            else if (!isAddr && !isStack && Math.abs(v) < 4096 && fp.memberOffsets.size() < 64 && ins.getMnemonicString().toLowerCase().startsWith("mov")) fp.memberOffsets.add((int) v);
                        } else if (o instanceof Address) norm.append("ADDR");
                        else norm.append(o.toString().replaceAll("0x[0-9a-fA-F]+", "IMM"));
                        norm.append(',');
                    }
                }
                norm.append('\n');
                for (Reference r : ins.getReferencesFrom()) {
                    if (r.getReferenceType().isCall()) { Function c = listing.getFunctionAt(r.getToAddress()); if (c != null) cl.add(c.getEntryPoint().getOffset()); }
                    if (r.getReferenceType().isData()) { Data d = listing.getDataAt(r.getToAddress()); if (d != null) { String tn = d.getDataType().getName().toLowerCase(); Object v = d.getValue();
                        if ((tn.equals("float") || tn.equals("double")) && v != null && fp.consts.size() < 256) fp.consts.add(String.valueOf(v));
                        else if (tn.contains("string") && v != null && strs.size() < 64) strs.add(String.valueOf(v)); } }
                }
            }
            fp.raw = sha(raw.toByteArray()); fp.norm = sha(norm.toString());
            // CFG
            CodeBlockIterator bi = bbm.getCodeBlocksContaining(f.getBody(), TaskMonitor.DUMMY);
            List<CodeBlock> blocks = new ArrayList<>(); while (bi.hasNext()) blocks.add(bi.next());
            blocks.sort(Comparator.comparing(CodeBlock::getFirstStartAddress));
            Map<Address, Integer> idx = new HashMap<>(); for (int i = 0; i < blocks.size(); i++) idx.put(blocks.get(i).getFirstStartAddress(), i);
            StringBuilder edges = new StringBuilder();
            for (int i = 0; i < blocks.size(); i++) { CodeBlockReferenceIterator di = blocks.get(i).getDestinations(TaskMonitor.DUMMY); List<Integer> ds = new ArrayList<>(); while (di.hasNext()) { Integer j = idx.get(di.next().getDestinationAddress()); if (j != null) ds.add(j); } Collections.sort(ds); edges.append(i).append("->").append(ds).append(';'); }
            fp.blocks = blocks.size(); fp.cfg = sha(edges.toString());
            Collections.sort(fp.consts);
            fp.strx = sha(String.join("\n", strs));
            fp.rtti = slotOwner.get(fp.addr); fp.slot = slotIndex.getOrDefault(fp.addr, -1);
            Collections.sort(fp.memberOffsets);
            callees.put(fp.addr, cl); all.put(fp.addr, fp);
        }
        for (FP fp : all.values()) { List<String> cs = new ArrayList<>(); for (long c : callees.get(fp.addr)) { FP cf = all.get(c); if (cf != null) cs.add(cf.norm); } Collections.sort(cs); fp.callg = sha(String.join(",", cs)); }

        try (PrintWriter w = new PrintWriter(new FileWriter(new File(out, "decompiler/fingerprints.json")))) {
            w.print("{\"schema\":\"artifactbench.fingerprints\",\"schema_version\":1,\"tool\":\"ghidra/Fingerprint.java\",\"generated\":" + esc(new Date().toString()) + ",\"data\":{\"functions\":[");
            boolean first = true;
            for (FP fp : all.values()) {
                if (!first) w.print(','); first = false;
                w.print("{\"addr\":\"0x" + Long.toHexString(fp.addr) + "\",\"name\":" + esc(fp.name) + ",\"size\":" + fp.size + ",\"RAW_BYTE_HASH\":\"" + fp.raw + "\",\"NORMALIZED_INSTRUCTION_HASH\":\"" + fp.norm + "\",\"CFG_SIGNATURE\":{\"blocks\":" + fp.blocks + ",\"hash\":\"" + fp.cfg + "\"},\"CALLGRAPH_SIGNATURE\":\"" + fp.callg + "\",\"CONSTANT_SIGNATURE\":[" + ExportRTTI.strList(fp.consts.size() > 64 ? fp.consts.subList(0, 64) : fp.consts) + "],\"STRING_XREF_SIGNATURE\":\"" + fp.strx + "\",\"RTTI_XREF\":" + esc(fp.rtti) + ",\"VTABLE_SLOT\":" + fp.slot + ",\"member_offsets\":" + fp.memberOffsets + "}");
            }
            w.println("]}}");
        }
        println("Fingerprint: " + all.size() + " functions");
    }
}
