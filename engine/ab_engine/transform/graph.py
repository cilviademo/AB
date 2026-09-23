"""The transformation graph (ADDENDUM C3): one chain per subsystem, every node retained.

    binary evidence → recovered implementation → semantic reconstruction → transformed implementation → validation

``build`` derives it at RECONSTRUCT time from the reconstruction model, the recovery goal and the identifier
map; ``update_with_validation`` fills the validation node and the final status from the differential results
and the licensing report. ``ORIGINAL_BEHAVIOR`` / ``RECOVERED_BEHAVIOR`` / ``TRANSFORMED_BEHAVIOR`` stay
separate files (05_reference_behavior, 06_validation/recovered_behavior, 06_validation/transformed_behavior);
the graph only points at them.
"""

from __future__ import annotations

from typing import Any

from ab_engine.transform import goals as goals_mod

EQUIV = ("BIT_EXACT", "NUMERICALLY_EQUIVALENT", "BEHAVIORALLY_EQUIVALENT")


def _node(kind: str, ref: str | None, **extra: Any) -> dict[str, Any]:
    return {"node": kind, "ref": ref, **extra}


def build(model: dict[str, Any], plan: dict[str, Any], imap: dict[str, Any] | None, *, licensing_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    subsystems: list[dict[str, Any]] = []
    transformed = plan["transformed"] and plan["available"]
    renamed = {r["original"]: r["active"] for r in (imap or {}).get("identifiers", []) if r.get("active") != r.get("original", "").split("::")[-1]}

    # DSP modules (fitted)
    for ws in model.get("modules", []):
        nodes = [_node("BINARY_EVIDENCE", "05_reference_behavior/transfer_curves", basis=ws.get("reference")),
                 _node("RECOVERED_IMPLEMENTATION", "04_reconstruction/recovered_source/Waveshaper.h", family=ws.get("family"), rmse=ws.get("rmse"), classification=ws.get("classification_at_default")),
                 _node("SEMANTIC_RECONSTRUCTION", "04_reconstruction/reconstruction_model.json", laws={mo["key"]: mo["law"] for mo in ws.get("modulation", [])})]
        if transformed:
            nodes.append(_node("TRANSFORMED_IMPLEMENTATION", "04_reconstruction/transformed_source/DSP/Saturation.h", goal=plan["goal"],
                               changes=["block-processing API (prepare/process/reset over juce::dsp::ProcessContextReplacing)", "parameter handles cached at prepare (no per-block string lookups)",
                                        "noexcept / [[nodiscard]] / constexpr laws", "canonical names (identifier_map.json)"],
                               intended_behavioral_change=False))
        nodes.append(_node("VALIDATION", "06_validation/differential_results.json", status="PENDING"))
        subsystems.append({"subsystem": "DSP", "module": ws.get("name"), "role": ws.get("role"), "nodes": nodes,
                           "status": "PENDING_VALIDATION" if transformed else ("RECONSTRUCTED" if ws.get("active") else "UNRECOVERABLE"),
                           "original_state": "RECOVERED" if ws.get("active") else "PARTIAL",
                           "transformation": plan["goal"] if transformed else None, "behavioral_compatibility": "PENDING" if transformed else ("FULL" if ws.get("active") else "PARTIAL"),
                           "migration_required": False, "preserve": plan["switches"].get("preserve_dsp_behavior"),
                           "intentional_behavioral_changes": []})
    # state layer
    st = model.get("state") or {}
    subsystems.append({"subsystem": "State", "nodes": [_node("BINARY_EVIDENCE", "01_evidence/vst3/state_baseline.json"), _node("RECOVERED_IMPLEMENTATION", "04_reconstruction/Source/Active/Parameters.h", root_tag=st.get("root_tag")),
                                                       *([_node("TRANSFORMED_IMPLEMENTATION", None, changes=["state keys and parameter ids preserved (switch YES); migrations only proposed in identifier_map.json"])] if transformed else []),
                                                       _node("VALIDATION", "06_validation/cross_load.json", status="PENDING")],
                       "status": "PENDING_VALIDATION" if transformed else "RECONSTRUCTED", "original_state": "RECOVERED", "transformation": ("KEYS_PRESERVED" if transformed else None),
                       "behavioral_compatibility": "PENDING", "migration_required": False, "preserve": plan["switches"].get("preserve_state_keys"), "intentional_behavioral_changes": []})
    # identity
    ident = model.get("identity") or {}
    subsystems.append({"subsystem": "Identity", "nodes": [_node("BINARY_EVIDENCE", "03_architecture/identity.json", codes_status=ident.get("codes_status")), _node("RECOVERED_IMPLEMENTATION", "04_reconstruction/identity.cmake"),
                                                          _node("VALIDATION", None, status="N/A")],
                       "status": "RECOVERED_EXACT" if str(ident.get("codes_status", "")).startswith("VERIFIED_RUNTIME") else "RECONSTRUCTED",
                       "original_state": "RECOVERED", "transformation": ("SURROGATE_IDENTITY" if model.get("build_kind") == "SURROGATE" else None),
                       "behavioral_compatibility": "FULL" if model.get("build_kind") == "FIDELITY" else "N/A (SURROGATE identity: not session-compatible by design)",
                       "migration_required": False, "preserve": plan["switches"].get("preserve_identity"), "intentional_behavioral_changes": []})
    # licensing (scaffolds)
    for e in licensing_entries or []:
        subsystems.append({"subsystem": "Licensing", "symbol": e.get("symbol"), "nodes": [_node("BINARY_EVIDENCE", "01_evidence/decompiler/roles.json", addresses=e.get("binary_addresses", [])[:4]),
                                                                                          _node("RECOVERED_IMPLEMENTATION", e.get("file"), status=e.get("status")),
                                                                                          *([_node("TRANSFORMED_IMPLEMENTATION", None, changes=[], note="no licensing transformation requested (replace_activation_backend=" + plan["switches"].get("replace_activation_backend", "NO") + ")")] if transformed else []),
                                                                                          _node("VALIDATION", "06_validation/licensing_validation.json", status="PENDING")],
                           "status": "RECONSTRUCTED" if e.get("compiled") else "UNRECOVERABLE" if e.get("status") == "UNRECOVERABLE" else "PENDING_VALIDATION",
                           "original_state": "RECOVERED" if e.get("compiled") else "PARTIAL", "transformation": None, "behavioral_compatibility": "PENDING", "migration_required": False,
                           "preserve": plan["switches"].get("preserve_legacy_license_format"), "intentional_behavioral_changes": []})
    # other scaffolds (not transformed: nothing to transform until reconstructed)
    for c in model.get("scaffolds", []):
        if c.get("role") in ("LICENSING_AND_ENTITLEMENT_SUBSYSTEM", "PROTECTED_SUBSYSTEM"):
            continue
        subsystems.append({"subsystem": "Scaffold", "symbol": c.get("name"), "role": c.get("role"), "active_name": renamed.get(c.get("name")),
                           "nodes": [_node("BINARY_EVIDENCE", "03_architecture/classes.json", vtables=c.get("vtables", [])[:2]), _node("RECOVERED_IMPLEMENTATION", None, status="SCAFFOLD_ONLY"), _node("VALIDATION", None, status="N/A")],
                           "status": "UNRECOVERABLE" if c.get("structure_status") == "UNKNOWN" else "RECONSTRUCTED" if False else "PENDING_VALIDATION", "original_state": "PARTIAL",
                           "transformation": None, "behavioral_compatibility": "N/A", "migration_required": False, "preserve": None, "intentional_behavioral_changes": []})
    return {"goal": plan["goal"], "goal_text": plan["goal_text"], "switches": plan["switches"], "available": plan["available"], "not_available_reason": plan.get("not_available_reason"),
            "active_variant": plan["active_variant"], "behaviours": {"ORIGINAL_BEHAVIOR": "05_reference_behavior/", "RECOVERED_BEHAVIOR": "06_validation/recovered_behavior/", "TRANSFORMED_BEHAVIOR": "06_validation/transformed_behavior/"},
            "subsystems": subsystems, "transformation_nodes": sum(1 for s in subsystems for n in s["nodes"] if n["node"] == "TRANSFORMED_IMPLEMENTATION"),
            "rule": "every node retained; ORIGINAL / RECOVERED / TRANSFORMED behaviour stored separately; a behavioural change is always listed with its status (ADDENDUM C3)"}


def update_with_validation(graph: dict[str, Any], *, variant: str, modules: list[dict[str, Any]], cross: dict[str, Any], licensing: dict[str, Any] | None,
                           comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    """Fill the VALIDATION nodes and final statuses from a COMPARE run of ``variant`` (RECOVERED | TRANSFORMED)."""
    mod_by = {m.get("module"): m for m in modules}
    lic_by = {r.get("symbol"): r for r in (licensing or {}).get("entries", [])}
    bypass = (licensing or {}).get("bypass_findings", [])
    graph["validated_variant"] = variant
    graph["comparisons"] = comparisons
    for s in graph["subsystems"]:
        val = next((n for n in s["nodes"] if n["node"] == "VALIDATION"), None)
        if s["subsystem"] == "DSP":
            m = mod_by.get("Waveshaper") or next(iter(mod_by.values()), None)
            cls = (m or {}).get("classification", "NOT_VALIDATED")
            if val:
                val.update({"status": cls, "worst_rmse": (m or {}).get("worst_rmse"), "variant": variant})
            if variant == "TRANSFORMED" and graph.get("transformation_nodes"):
                if cls in EQUIV:
                    s["status"], s["behavioral_compatibility"] = "MODERNIZED_EQUIVALENT", "FULL"
                elif cls == "PERCEPTUALLY_CLOSE":
                    s["status"], s["behavioral_compatibility"] = "TRANSFORMED_COMPATIBLE", "PARTIAL"
                else:
                    s["status"], s["behavioral_compatibility"] = "TRANSFORMED_BREAKING", "NONE"
                    if s.get("preserve") == "YES":
                        s["intentional_behavioral_changes"].append({"change": "DSP behaviour differs from the original", "status": "TRANSFORMED_BREAKING", "intended": False, "rule": "preserve_dsp_behavior=YES: this transformation must not ship"})
            else:
                s["status"] = "RECONSTRUCTED" if cls in EQUIV else ("RECOVERED_EXACT" if cls == "BIT_EXACT" else s["status"] if cls == "NOT_VALIDATED" else "UNRECOVERABLE" if cls == "FAILED" else "RECONSTRUCTED")
                s["behavioral_compatibility"] = "FULL" if cls in EQUIV else "PARTIAL" if cls == "PERCEPTUALLY_CLOSE" else "NONE" if cls == "FAILED" else s["behavioral_compatibility"]
        elif s["subsystem"] == "State":
            c = cross.get("classification", "NOT_VALIDATED")
            if val:
                val.update({"status": c, "variant": variant})
            s["status"] = ("TRANSFORMED_COMPATIBLE" if variant == "TRANSFORMED" else "RECONSTRUCTED") if c == "CROSS_LOAD_VALIDATED" else ("TRANSFORMED_BREAKING" if variant == "TRANSFORMED" and c == "FAILED" else s["status"])
            s["behavioral_compatibility"] = "FULL" if c == "CROSS_LOAD_VALIDATED" else "NONE" if c == "FAILED" else "PENDING"
        elif s["subsystem"] == "Licensing":
            r = lic_by.get(s.get("symbol"))
            if val and r:
                val.update({"status": r.get("state"), "reason": r.get("reason")})
            s_leaf = str(s.get("symbol") or "").split("::")[-1]
            mine = [b for b in bypass if s_leaf and (s_leaf in str(b.get("symbol", "")) or str(b.get("symbol", "")).split("::")[-1] in str(s.get("symbol")))]
            if mine:
                s["status"] = "TRANSFORMED_BREAKING"
                s["intentional_behavioral_changes"] += [{"change": f"{b['symbol']}: {b['kind']}", "status": b["status"], "intended": None, "rule": "a validate → true edit is a transformation, never recovery (C2)"} for b in mine]
    graph["status_summary"] = {}
    for s in graph["subsystems"]:
        graph["status_summary"][s["status"]] = graph["status_summary"].get(s["status"], 0) + 1
    graph["intentional_behavioral_changes"] = [dict(ch, subsystem=s["subsystem"], symbol=s.get("symbol") or s.get("module")) for s in graph["subsystems"] for ch in s["intentional_behavioral_changes"]]
    return graph


__all__ = ["build", "update_with_validation", "EQUIV"]
