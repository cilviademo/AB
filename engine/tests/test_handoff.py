"""Agent handoff writers: derived from evidence only, task order, export hook."""
from __future__ import annotations

import json
from pathlib import Path

from ab_engine.contracts import write_json
from ab_engine.handoff import writer
from ab_engine.jobs.model import Job, StageRecord


def _job(tmp_path: Path) -> Job:
    pd = tmp_path / "proj"
    for d in ("00_manifest", "03_architecture", "06_validation", "07_agent_handoff", "04_reconstruction"):
        (pd / d).mkdir(parents=True)
    write_json(pd / "00_manifest/recovery_summary.json", "recovery.summary", {"binary": "x.so", "juce": "8.0.9", "pdbFound": False})
    write_json(pd / "03_architecture/identity.json", "artifactbench.identity", {"vendor": "V", "product": "P", "processor_fuid": "00", "manufacturer_code": "Abcd", "plugin_code": "Efgh", "codes_status": "VERIFIED_RUNTIME", "evidence": "VERIFIED_RUNTIME", "latency_samples": 0, "buses": {"input_audio": [{}], "output_audio": [{}]}, "editor": {"width": 1, "height": 1}})
    write_json(pd / "06_validation/differential_results.json", "artifactbench.differential_results",
               {"overall": "FAILED", "cross_load": "CROSS_LOAD_VALIDATED", "renders": [{"id": "a"}],
                "modules": [{"module": "Waveshaper", "role": "WAVESHAPER", "classification": "BEHAVIORALLY_EQUIVALENT", "renders": 1, "worst_rmse": 1e-5, "worst_spectrum_diff_db": 0.0, "failing": []},
                            {"module": "FrequencyResponse", "role": "FILTER", "classification": "FAILED", "renders": 1, "worst_rmse": 0.2, "worst_spectrum_diff_db": 2.0, "failing": ["log_sweep_48k_256"]},
                            {"module": "WaveshaperSweeps", "role": "WAVESHAPER_LAWS", "classification": "PERCEPTUALLY_CLOSE", "renders": 5, "worst_rmse": 3e-4, "worst_spectrum_diff_db": 0.0, "failing": ["ramp_x_1.0"]}]})
    write_json(pd / "06_validation/build_report.json", "artifactbench.build_report", {"build_kind": "SURROGATE", "status": "BUILT"})
    write_json(pd / "07_agent_handoff/reconstruction_index.json", "artifactbench.reconstruction_index",
               [{"symbol": "ab_rebuild::Waveshaper", "role": "WAVESHAPER", "file": "04_reconstruction/human_source/Waveshaper.h", "status": "BEHAVIOR_MATCHED", "compiled": True, "validation": "BEHAVIORALLY_EQUIVALENT", "validation_sweeps": "PERCEPTUALLY_CLOSE", "todos": ["t1"]},
                {"symbol": "ns::Filt", "role": "FILTER", "file": "04_reconstruction/Source/RecoveredScaffolds/DSP/Filt.h", "status": "SCAFFOLD_ONLY", "compiled": False, "structure_status": "VERIFIED_VTABLE"},
                {"symbol": "ns::Lic", "role": "PROTECTED_SUBSYSTEM", "file": "x", "status": "SCAFFOLD_ONLY", "compiled": False}])
    write_json(pd / "04_reconstruction/reconstruction_model.json", "artifactbench.reconstruction_model",
               {"modules": [{"name": "Waveshaper", "family": "tanh", "rmse": 1e-5, "modulation": [{"key": "cut", "law": "unmodeled", "basis": "filter"}, {"key": "g", "law": "db", "basis": "x"}, {"key": "t", "law": "table", "basis": "y"}]}]})
    job = Job(job_id="ab-1", name="P", primary="x.so", artifact_sha256="a" * 64, ownership="OWNED", project_dir=str(pd), created="now")
    for st in ("INGESTED", "STATIC_COMPLETE", "RUNTIME_COMPLETE", "BEHAVIOR_COMPLETE", "RECONSTRUCTION_COMPLETE", "BUILD_COMPLETE", "VALIDATION_COMPLETE"):
        job.stages.append(StageRecord(job_id="ab-1", stage=st, status="OK"))
    return job


def test_handoff_files_are_evidence_driven(tmp_path):
    job = _job(tmp_path)
    written = writer.write_all(job)
    pd = Path(job.project_dir)
    assert set(written) == {"07_agent_handoff/HANDOFF.md", "07_agent_handoff/TODO.md", "07_agent_handoff/agent_prompt.md", "07_agent_handoff/UNRECOVERABLE.md"}
    h = (pd / "07_agent_handoff/HANDOFF.md").read_text()
    assert "codes Abcd/Efgh — VERIFIED_RUNTIME" in h and "`Waveshaper` BEHAVIORALLY_EQUIVALENT" in h and "SURROGATE BUILT" in h
    assert "no PDB" in h and "JUCE 8.0.9" in h
    tasks = writer.next_tasks(writer.gather(job))
    texts = [t["task"] for t in tasks]
    assert any("DECOMPILE" in t for t in texts)                      # decompile stage never ran
    assert any("`cut` is not a static transfer effect" in t for t in texts)
    assert any("`FrequencyResponse` is FAILED" in t for t in texts)
    assert any("sweeps reach PERCEPTUALLY_CLOSE" in t for t in texts)
    assert any("Scaffold `ns::Filt`" in t for t in texts) and not any("ns::Lic" in t for t in texts)  # protected subsystem is never a porting task
    assert any("FIDELITY" in t for t in texts)
    prio = [int(t["priority"]) for t in tasks]
    assert prio == sorted(prio)
    u = (pd / "07_agent_handoff/UNRECOVERABLE.md").read_text()
    assert "no .pdb" in u and "`t` between measured positions" in u
    a = (pd / "07_agent_handoff/agent_prompt.md").read_text()
    assert "PROTECTED_SUBSYSTEM" in a and "human_source/Waveshaper.h" in a and "PERCEPTUALLY_CLOSE" in a
