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

# ADDENDUM C1: two orthogonal interpretation fields; nothing runs or stops on them (D-026)
USAGE_CONTEXTS = ("USER_RECOVERY", "KNOWN_SOURCE_FIXTURE", "BLACK_BOX_REFERENCE", "SOURCE_AVAILABLE_REFERENCE", "UNKNOWN_CONTEXT")
SOURCE_AVAILABILITIES = ("SOURCE_UNKNOWN", "SOURCE_UNAVAILABLE", "SOURCE_PARTIAL", "SOURCE_AVAILABLE", "KNOWN_SOURCE_GROUND_TRUTH")
#: the retired ownership declaration, accepted as an alias so older scripts and job rows keep working
LEGACY_OWNERSHIP = {"OWNED": ("USER_RECOVERY", "SOURCE_UNKNOWN"), "AUTHORIZED": ("USER_RECOVERY", "SOURCE_UNKNOWN"),
                    "THIRD_PARTY": ("BLACK_BOX_REFERENCE", "SOURCE_UNAVAILABLE")}
INTERPRETATION = {
    "USER_RECOVERY": "user recovery: every supplied artifact is evidence for maximum recoverability",
    "KNOWN_SOURCE_FIXTURE": "known-source fixture: source withheld from recovery, read only by the evaluator; results are validated against known source",
    "BLACK_BOX_REFERENCE": "binary-derived reconstruction (reference): full pipeline, results labelled binary-derived; reference code is not copied into a user project unless the user chooses",
    "SOURCE_AVAILABLE_REFERENCE": "reference with available source: binary-derived results, the source is available for comparison",
    "UNKNOWN_CONTEXT": "context not declared: binary-derived results",
}


def normalize_context(usage_context: str | None, source_availability: str | None, ownership: str | None = None) -> tuple[str, str]:
    """Defaults USER_RECOVERY / SOURCE_UNKNOWN; a legacy ownership word maps through LEGACY_OWNERSHIP."""
    uc = (usage_context or "").upper()
    sa = (source_availability or "").upper()
    if ownership and not uc:
        uc, legacy_sa = LEGACY_OWNERSHIP.get(ownership.upper(), ("USER_RECOVERY", "SOURCE_UNKNOWN"))
        sa = sa or legacy_sa
    if uc not in USAGE_CONTEXTS:
        if uc:
            raise ValueError(f"usage_context must be one of {', '.join(USAGE_CONTEXTS)}")
        uc = "USER_RECOVERY"
    if sa not in SOURCE_AVAILABILITIES:
        if sa:
            raise ValueError(f"source_availability must be one of {', '.join(SOURCE_AVAILABILITIES)}")
        sa = "SOURCE_UNKNOWN"
    return uc, sa


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
    usage_context: str
    created: str
    primary: str
    project_dir: str
    stages: list[StageRecord] = field(default_factory=list)
    source_availability: str = "SOURCE_UNKNOWN"

    def __post_init__(self) -> None:
        # rows and callers from before D-026 pass an ownership word here
        if self.usage_context in LEGACY_OWNERSHIP:
            self.usage_context, self.source_availability = LEGACY_OWNERSHIP[self.usage_context]

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stages"] = [s.as_dict() for s in self.stages]
        return d

    def stage(self, name: str) -> StageRecord | None:
        return next((s for s in self.stages if s.stage == name), None)

    @property
    def interpretation(self) -> str:
        """How reports read this job's results (ADDENDUM C1) — never what runs."""
        return INTERPRETATION.get(self.usage_context, INTERPRETATION["UNKNOWN_CONTEXT"])

    @property
    def context(self) -> dict[str, str]:
        return {"usage_context": self.usage_context, "source_availability": self.source_availability, "interpretation": self.interpretation}
