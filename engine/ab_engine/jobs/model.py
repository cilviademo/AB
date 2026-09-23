"""Job and stage records (SPEC §5)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

#: Stage order. Each stage's cache key covers only its own inputs; invalidating
#: one stage invalidates everything after it, nothing before.
STAGES: tuple[str, ...] = (
    "INGESTED", "STATIC_COMPLETE", "RUNTIME_COMPLETE", "DECOMPILATION_COMPLETE", "BEHAVIOR_COMPLETE",
    "RECONSTRUCTION_COMPLETE", "BUILD_COMPLETE", "VALIDATION_COMPLETE", "EXPORT_COMPLETE",
)

#: Rail names shown in the UI (SPEC §14 + AB_BRIEF).
RAIL: dict[str, str] = {
    "INGESTED": "INGEST", "STATIC_COMPLETE": "STATIC", "RUNTIME_COMPLETE": "RUNTIME",
    "DECOMPILATION_COMPLETE": "DECOMPILE", "BEHAVIOR_COMPLETE": "PROBE", "RECONSTRUCTION_COMPLETE": "RECONSTRUCT",
    "BUILD_COMPLETE": "BUILD", "VALIDATION_COMPLETE": "COMPARE", "EXPORT_COMPLETE": "EXPORT",
}

OWNERSHIPS = ("OWNED", "AUTHORIZED", "THIRD_PARTY")


def stage_index(stage: str) -> int:
    return STAGES.index(stage)


def downstream(stage: str) -> tuple[str, ...]:
    return STAGES[stage_index(stage) + 1:]


def config_hash(config: dict[str, Any] | None) -> str:
    """Canonical hash of the options a stage depends on."""
    canon = json.dumps(config or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def cache_key(artifact_sha256: str, tool_version: str, stage_version: int, cfg_hash: str) -> str:
    """SPEC §5: ``sha256(artifact) + tool_version + stage_version + config_hash``."""
    return hashlib.sha256(f"{artifact_sha256}|{tool_version}|{stage_version}|{cfg_hash}".encode()).hexdigest()


@dataclass
class StageRecord:
    job_id: str
    stage: str
    status: str = "PENDING"
    input_hashes: list[str] = field(default_factory=list)
    tool_versions: dict[str, str] = field(default_factory=dict)
    config_hash: str = ""
    stage_version: int = 0
    started: str | None = None
    ended: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    completeness: str = "NOT_APPLICABLE"
    metrics: dict[str, Any] = field(default_factory=dict)
    skip_reason: str | None = None
    cache_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def contract_data(self) -> dict[str, Any]:
        d = self.as_dict()
        d.pop("cache_key", None)
        return d


@dataclass
class Job:
    job_id: str
    name: str
    artifact_sha256: str
    ownership: str
    created: str
    primary: str
    project_dir: str
    stages: list[StageRecord] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stages"] = [s.as_dict() for s in self.stages]
        return d

    def stage(self, name: str) -> StageRecord | None:
        return next((s for s in self.stages if s.stage == name), None)

    @property
    def reconstruction_allowed(self) -> bool:
        """SPEC §1.9 / §15: third-party jobs never get Active/ or a reconstruction export."""
        return self.ownership in ("OWNED", "AUTHORIZED")
