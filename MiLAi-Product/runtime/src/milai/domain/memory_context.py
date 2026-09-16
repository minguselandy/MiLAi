from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ContextAuthorityClass = Literal["EVIDENCE_ONLY", "CANONICAL_STATE", "MIXED"]
EvidenceSpeaker = Literal["USER", "ASSISTANT", "TOOL", "SYSTEM", "UNKNOWN"]
EvidenceSourceContextLineage = Literal[
    "STRUCTURED_TURN_METADATA",
    "AUTHORITATIVE_BACKFILL",
    "UNKNOWN",
]
ContextSufficiencyStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "UNSATISFIED",
    "CONTESTED",
    "UNBOUNDED",
]


class EvidenceView(BaseModel):
    """A query-time, rebuildable view over one governed Evidence observation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-view-v0.1"] = "evidence-view-v0.1"
    evidence_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str | None = None
    turn_ordinal: int | None = Field(default=None, ge=0)
    round_id: str | None = None
    round_ordinal: int | None = Field(default=None, ge=0)
    previous_turn_id: str | None = None
    next_turn_id: str | None = None
    source_context_source: EvidenceSourceContextLineage = "UNKNOWN"
    speaker: EvidenceSpeaker = "UNKNOWN"
    content: str = Field(min_length=1)
    observed_at: str | None = None
    relevance_score: float | None = None
    source_rank: int = Field(ge=1)
    query_overlap: int = Field(default=0, ge=0)
    answer_signal: bool = False
    anchor_match: bool = False
    expanded_from_evidence_id: str | None = None
    expansion_trigger: Literal["SAME_ROUND", "ADJACENT_ROUND"] | None = None
    canonical: Literal[False] = False
    authority_class: Literal["EVIDENCE_ONLY"] = "EVIDENCE_ONLY"


class ContextExpansion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: Literal[
        "SPEAKER_ADJACENCY",
        "SAME_ROUND",
        "ADJACENT_ROUND",
        "REQUIRED_SOURCE",
        "MULTI_SESSION_REQUIREMENT",
    ]
    source_evidence_id: str = Field(min_length=1)
    expanded_evidence_ids: list[str] = Field(default_factory=list)
    cost: int = Field(ge=0)
    coverage_delta: int = Field(ge=0)
    stop_reason: Literal[
        "EXPANDED",
        "NO_APPLICABLE_NEIGHBOR",
        "ALREADY_SELECTED",
        "BUDGET_EXHAUSTED",
    ]


class MemoryContextWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    source_turn_refs: list[str] = Field(min_length=1)
    speakers: list[EvidenceSpeaker] = Field(min_length=1)
    observed_at: str | None = None
    text: str = Field(min_length=1)
    source_rank: int = Field(ge=1)
    query_overlap: int = Field(ge=0)
    answer_signal: bool
    requirement_priority: bool
    truncated: bool = False
    expansions: list[ContextExpansion] = Field(default_factory=list)


class MemoryContext(BaseModel):
    """Runtime-owned, governed provider context."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["memory-context-v0.1"] = "memory-context-v0.1"
    authority_class: ContextAuthorityClass
    text: str = Field(min_length=1)
    semantic_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reader_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    token_budget: int = Field(ge=128, le=16_384)
    estimated_tokens: int = Field(ge=0)
    token_counting_method: Literal["utf8-bytes-ceil-div-3-v1"] = (
        "utf8-bytes-ceil-div-3-v1"  # noqa: S105 -- metric identity, not a secret
    )
    available_windows: int = Field(ge=0)
    selected_windows: int = Field(ge=0)
    context_truncated: bool
    selected_evidence_ids: list[str] = Field(default_factory=list)
    selected_source_turn_refs: list[str] = Field(default_factory=list)
    claim_versions: list[str] = Field(default_factory=list)
    open_issue_ids: list[str] = Field(default_factory=list)
    windows: list[MemoryContextWindow] = Field(default_factory=list)
    compile_trace: dict[str, object] = Field(default_factory=dict)


class IssueRevisionDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)
    revision: int | None = Field(default=None, ge=0)


class ReaderContextAliasMapping(BaseModel):
    """Lossless structured provenance behind one stable Reader-visible alias."""

    model_config = ConfigDict(extra="forbid")

    alias: str = Field(pattern=r"^[CDEI][1-9][0-9]*$")
    evidence_ids: list[str] = Field(default_factory=list)
    source_turn_refs: list[str] = Field(default_factory=list)
    claim_versions: list[str] = Field(default_factory=list)
    issue_revisions: list[IssueRevisionDependency] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dependency(self) -> Self:
        if not any(
            (
                self.evidence_ids,
                self.source_turn_refs,
                self.claim_versions,
                self.issue_revisions,
            )
        ):
            raise ValueError("Reader alias must map to structured provenance")
        return self


class EvidenceContextReceipt(BaseModel):
    """Formal non-canonical receipt for Evidence-only or mixed Context."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["context-receipt-v0.2"] = "context-receipt-v0.2"
    context_id: str = Field(min_length=1)
    authority_class: Literal["EVIDENCE_ONLY", "MIXED"]
    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reader_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_mapping: list[ReaderContextAliasMapping] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)
    claim_versions: list[str] = Field(default_factory=list)
    issue_revisions: list[IssueRevisionDependency] = Field(default_factory=list)
    sufficiency_status: ContextSufficiencyStatus
    missing_slots: list[str] = Field(default_factory=list)
    canonical_position: int | None = Field(default=None, ge=0)
    projection_watermarks: dict[str, int] = Field(default_factory=dict)
    issued_at: datetime
    persisted: Literal[False] = False
    canonical_mutation: Literal[False] = False
