"""ADDENDUM C2 consistency: nothing AB writes for an agent may prohibit reconstructing the licensing subsystem.
The frozen Static Recovery v2 port still says PROTECTED_SUBSYSTEM / "do not reimplement"; AB's own layer translates
that before any current report, instruction or export uses it, and keeps the original label for provenance."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ab_engine.bundle.api import export_job
from ab_engine.contracts import read_json
from ab_engine.handoff import writer
from ab_engine.jobs import db as jobs_db
from ab_engine.jobs.model import Job
from ab_engine.reconstruct import generate, model
from ab_engine.static import api as static_api
from tests.test_reconstruct import _synthetic_project

PROHIBITIONS = re.compile(r"(?i)do not reimplement|never reimplement|not reimplemented|do not bypass|or bypass it|architecture only|owner supplies a replacement|reconstruction is (forbidden|prohibited|not allowed)")
STALE = "Licensing code is PROTECTED_SUBSYSTEM: document its architecture, do not reimplement or bypass it."


def _v2_files(pd: Path) -> list[str]:
    """What the frozen v2 bundle would have installed for a plugin with a licensing class (its exact wording)."""
    files = {
        "07_agent_handoff/agent_prompt.md": f"You are continuing an evidence-first reconstruction.\n\nRules:\n- {STALE}\n- Never invent.\n",
        "07_agent_handoff/HANDOFF.md": "# HANDOFF\n\n- test::Lic — PROTECTED_SUBSYSTEM scaffold under RecoveredScaffolds/Protected/\n",
        "04_reconstruction/Source/RecoveredScaffolds/Protected/Lic.h": "// GENERATED scaffold — PROTECTED_SUBSYSTEM\n#pragma once\nclass Lic {};\n",
        "04_reconstruction/Source/RecoveredScaffolds/README.md": "# RecoveredScaffolds\nProtected/ holds PROTECTED_SUBSYSTEM classes.\n",
    }
    out = []
    for rel, text in files.items():
        dst = pd / static_api.canonical_rel(rel)       # the install mapping: Protected/ → Licensing/
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        out.append(static_api.canonical_rel(rel))
    idx = pd / "07_agent_handoff" / "reconstruction_index.json"
    idx.write_text(json.dumps({"schema": "recovery.reconstruction_index", "schema_version": 2, "tool": "static-recovery-v2", "generated": "x",
                               "data": [{"symbol": "test::Lic", "role": "PROTECTED_SUBSYSTEM", "file": "04_reconstruction/Source/RecoveredScaffolds/Protected/Lic.h", "status": "SCAFFOLD_ONLY"}]}), encoding="utf-8")
    out.append("07_agent_handoff/reconstruction_index.json")
    return out


def test_v2_licensing_wording_is_canonicalized_and_nothing_prohibits_reconstruction(tmp_path: Path, ws):
    pd = _synthetic_project(tmp_path)                 # 01_evidence/rtti/classes.json carries test::Lic as v2 PROTECTED_SUBSYSTEM (legacy input)
    written = _v2_files(pd)
    report = static_api.canonicalize_v2(pd, written)
    # provenance kept, label translated, folder renamed, stale instruction gone
    assert {c["class"] for c in report["classes"]} == {"test::Lic"} and report["classes"][0]["original_role"] == "PROTECTED_SUBSYSTEM" and report["classes"][0]["canonical_role"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM"
    assert not (pd / "04_reconstruction/Source/RecoveredScaffolds/Protected").exists() and (pd / "04_reconstruction/Source/RecoveredScaffolds/Licensing/Lic.h").is_file()
    canon = read_json(pd / "01_evidence/rtti/role_canonicalization.json", expect="artifactbench.role_canonicalization")["data"]
    assert canon["classes"] == report["classes"]
    v2_idx = json.loads((pd / "07_agent_handoff/reconstruction_index.json").read_text(encoding="utf-8"))["data"][0]
    assert v2_idx["role"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" and v2_idx["original_role"] == "PROTECTED_SUBSYSTEM" and v2_idx["canonical_role"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" and "Licensing/" in v2_idx["file"]
    for rel in ("07_agent_handoff/agent_prompt.md", "07_agent_handoff/HANDOFF.md", "04_reconstruction/Source/RecoveredScaffolds/Licensing/Lic.h", "04_reconstruction/Source/RecoveredScaffolds/README.md"):
        text = (pd / rel).read_text(encoding="utf-8")
        assert STALE not in text and "PROTECTED_SUBSYSTEM" not in text and not PROHIBITIONS.search(text), rel
        assert "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" in text
    assert "recover, reconstruct, transform and validate" in (pd / "07_agent_handoff/agent_prompt.md").read_text(encoding="utf-8")
    # the v2 evidence JSON is untouched (frozen contract): the legacy label is accepted as input …
    rtti = json.loads((pd / "01_evidence/rtti/classes.json").read_text(encoding="utf-8"))["data"]
    assert any(c["role"] == "PROTECTED_SUBSYSTEM" for c in rtti)
    # … and every current output is canonical: reconstruction index, handoff, agent prompt, export
    m = model.build(pd)
    out = generate.generate(pd, m)
    lic = next(e for e in out["index"] if e["symbol"] == "test::Lic")
    assert lic["role"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" and lic["subsystem"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" and lic["file"].endswith("RecoveredScaffolds/Licensing/Lic.h")
    assert "recover" in " ".join(lic["todos"]).lower() and "TRANSFORMED_BREAKING" in lic["promotion"]
    job = Job("ab-lic", "LicPlug", "a" * 64, "USER_RECOVERY", "2026-01-01T00:00:00Z", "LicPlug.vst3", str(pd))
    writer.write_all(job)
    for name in ("agent_prompt.md", "HANDOFF.md", "TODO.md", "reconstruction_index.json"):
        text = (pd / "07_agent_handoff" / name).read_text(encoding="utf-8")
        assert not PROHIBITIONS.search(text), name
        assert '"role": "PROTECTED_SUBSYSTEM"' not in text and (name.endswith(".json") or "PROTECTED_SUBSYSTEM" not in text), name   # original_role stays as provenance in the index
    prompt = (pd / "07_agent_handoff" / "agent_prompt.md").read_text(encoding="utf-8")
    assert "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" in prompt and "reconstruct" in prompt and "TRANSFORMED_BREAKING" in prompt
    idx_text = (pd / "07_agent_handoff" / "reconstruction_index.json").read_text(encoding="utf-8")
    assert "LICENSING_AND_ENTITLEMENT_SUBSYSTEM" in idx_text
    # an exported bundle carries the same: nothing in it tells an agent to leave the licensing code alone
    (pd / "00_manifest").mkdir(exist_ok=True)
    from ab_engine.contracts import write_json
    write_json(pd / "00_manifest" / "input_manifest.json", "artifactbench.input_manifest",
               {"job_id": job.job_id, "name": job.name, "usage_context": "USER_RECOVERY", "source_availability": "SOURCE_UNKNOWN", "interpretation": job.interpretation,
                "primary": {"path": job.primary, "size": 1, "sha256": job.artifact_sha256, "kind": "binary", "format_hint": "pe"}, "inputs": [{"path": job.primary, "size": 1, "sha256": job.artifact_sha256, "kind": "binary", "status": "IDENTIFIED", "artifact_type": "PLUGIN_PE"}],
                "attachments": {}, "ignored": 0, "duplicates": []})
    conn = jobs_db.connect(ws.db_path)
    jobs_db.upsert_job(conn, job)
    e = export_job(ws, conn, job, zip_it=False)
    out_dir = Path(e["out_dir"])
    for rel in ("agent_prompt.md", "HANDOFF.md", "TODO.md", "reconstruction_index.json"):
        text = (out_dir / rel).read_text(encoding="utf-8")
        assert not PROHIBITIONS.search(text) and '"role": "PROTECTED_SUBSYSTEM"' not in text and (rel.endswith(".json") or "PROTECTED_SUBSYSTEM" not in text), rel
    assert (out_dir / "Source" / "RecoveredScaffolds" / "Licensing" / "Lic.h").is_file() and not (out_dir / "Source" / "RecoveredScaffolds" / "Protected").exists()


def test_canonicalize_text_is_idempotent_and_targeted():
    text, n = static_api.canonicalize_v2_text(f"- {STALE}\nSee RecoveredScaffolds/Protected/X.h (PROTECTED_SUBSYSTEM)\n")
    assert n == 3 and "PROTECTED_SUBSYSTEM" not in text and "RecoveredScaffolds/Licensing/X.h" in text and "TRANSFORMED_BREAKING" in text
    again, k = static_api.canonicalize_v2_text(text)
    assert k == 0 and again == text
    assert static_api.canonicalize_v2_text("nothing to do")[1] == 0
