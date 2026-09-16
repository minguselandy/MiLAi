"""Typed DG-15 successor adapter contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from evals.dg14.contracts import (
    DG14AdapterConfig,
    DG14CaseNamespace,
    DG14HistoryEvent,
    DG14StageRecord,
    McpProfile,
)

METHOD_ID = "DG15-MILAI-MCP"
TokenCounter = Callable[[str], int]
BarrierProjection = Literal["evidence", "fts", "vector"]
CaptureProfile = Literal[
    "LONGMEMEVAL_DEIDENTIFIED",
    "MVP01_SYNTHETIC_WARM",
]


@dataclass(frozen=True, slots=True)
class DG15AdapterConfig:
    base_url: str
    executable: Path | str
    profile_tokens: Mapping[McpProfile, str]
    tenant_id: str | None = None
    principal_id: str | None = None
    scope: Mapping[str, object] = field(default_factory=dict)
    max_limit: int = 50
    allowed_budgets: tuple[int, ...] = (512, 2048)
    project_prefix: str = "dg15-lme"
    mcp_concurrency: Literal[1, 2, 4, 8] = 4
    barrier_timeout_ms: int = 15_000
    barrier_projections: tuple[BarrierProjection, ...] = ("evidence",)
    max_latency_ms: int = 500
    formation_mode: Literal["OFF", "SHADOW", "CANARY"] = "OFF"
    capture_profile: CaptureProfile = "LONGMEMEVAL_DEIDENTIFIED"

    def __post_init__(self) -> None:
        if self.mcp_concurrency not in {1, 2, 4, 8}:
            raise ValueError("mcp_concurrency must be one of 1, 2, 4, or 8")
        if not 1 <= self.max_limit <= 50:
            raise ValueError("max_limit must be between 1 and 50")
        if not 0 <= self.barrier_timeout_ms <= 120_000:
            raise ValueError("barrier_timeout_ms must be between 0 and 120000")
        if not 25 <= self.max_latency_ms <= 2_000:
            raise ValueError("max_latency_ms must be between 25 and 2000")
        if self.formation_mode not in {"OFF", "SHADOW", "CANARY"}:
            raise ValueError("formation_mode is invalid")
        if self.capture_profile not in {
            "LONGMEMEVAL_DEIDENTIFIED",
            "MVP01_SYNTHETIC_WARM",
        }:
            raise ValueError("capture_profile is invalid")
        if not self.barrier_projections:
            raise ValueError("barrier_projections must not be empty")
        if len(set(self.barrier_projections)) != len(self.barrier_projections):
            raise ValueError("barrier_projections must be unique")
        self.dg14_config()

    def dg14_config(self) -> DG14AdapterConfig:
        return DG14AdapterConfig(
            base_url=self.base_url,
            executable=self.executable,
            profile_tokens=self.profile_tokens,
            tenant_id=self.tenant_id,
            principal_id=self.principal_id,
            scope=self.scope,
            max_limit=self.max_limit,
            allowed_budgets=self.allowed_budgets,
            project_prefix=self.project_prefix,
        )


@dataclass(frozen=True, slots=True)
class DG15CallRecord:
    sequence: int
    physical_batch_sequence: int
    stage: str
    profile: McpProfile
    tool_name: str
    request_sha256: str
    response_sha256: str | None
    batch_latency_ms: float
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: str | None = None
    runtime_request_id: str | None = None
    retrieval_trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class DG15Provenance:
    rank: int
    source_id: str
    session_id: str
    session_ordinal: int
    evidence_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    relevance_score: float | None
    context_selected: bool
    candidate_kind: Literal["EVIDENCE_OBSERVATION"] = "EVIDENCE_OBSERVATION"
    canonical: bool = False


@dataclass(frozen=True, slots=True)
class DG15QueryResult:
    method_id: str
    status: str
    context: str
    source_ids: tuple[str, ...]
    selected_source_refs: tuple[str, ...]
    provenance: tuple[DG15Provenance, ...]
    stage_trace: tuple[DG14StageRecord, ...]
    declared_tokens: int
    latency_ms: float
    usage: Mapping[str, object]
    raw_resolve: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DG15AdapterStats:
    method_id: str
    case_id: str | None
    evidence_count: int
    claim_count: int
    query_count: int
    logical_mcp_calls: int
    physical_mcp_batches: int
    evidence_ingest_ms: float
    finalize_ms: float
    query_ms: tuple[float, ...]
    context_tokens: tuple[int, ...]


__all__ = [
    "METHOD_ID",
    "CaptureProfile",
    "DG14CaseNamespace",
    "DG14HistoryEvent",
    "DG14StageRecord",
    "DG15AdapterConfig",
    "DG15AdapterStats",
    "DG15CallRecord",
    "DG15Provenance",
    "DG15QueryResult",
    "TokenCounter",
]
