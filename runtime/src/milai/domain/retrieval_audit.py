"""Internal, behavior-neutral retrieval audit contracts for DG-24.

The contracts in this module are deliberately absent from the MCP transport
surface.  They describe observations of an already-authorized read; they do
not authorize retrieval, Binding, policy changes, or canonical writes.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetrievalAuditReason(StrEnum):
    CHANNEL_NOT_AVAILABLE = "CHANNEL_NOT_AVAILABLE"
    CHANNEL_NOT_ENABLED = "CHANNEL_NOT_ENABLED"
    CHANNEL_ELIGIBLE_NOT_INVOKED = "CHANNEL_ELIGIBLE_NOT_INVOKED"
    QUERY_EXPRESSION_MISMATCH = "QUERY_EXPRESSION_MISMATCH"
    INDEX_REPRESENTATION_MISSING = "INDEX_REPRESENTATION_MISSING"
    TEMPORAL_SCOPE_MISROUTED = "TEMPORAL_SCOPE_MISROUTED"
    ENTITY_ALIAS_MISMATCH = "ENTITY_ALIAS_MISMATCH"
    NO_CHANNEL_RETRIEVED_GOLD = "NO_CHANNEL_RETRIEVED_GOLD"
    LEXICAL_ANCHOR_HARD_DROP = "LEXICAL_ANCHOR_HARD_DROP"
    ENTITY_ANCHOR_HARD_DROP = "ENTITY_ANCHOR_HARD_DROP"
    SOURCE_ROLE_FILTER_DROP = "SOURCE_ROLE_FILTER_DROP"
    TIME_FILTER_DROP = "TIME_FILTER_DROP"
    SCOPE_FILTER_DROP = "SCOPE_FILTER_DROP"
    REGEX_TYPE_MISCLASSIFICATION = "REGEX_TYPE_MISCLASSIFICATION"
    RULE_ASSOCIATION = "RULE_ASSOCIATION"
    CHANNEL_CUTOFF_DROP = "CHANNEL_CUTOFF_DROP"
    FIXED_PRIORITY_SUPPRESSION = "FIXED_PRIORITY_SUPPRESSION"
    GLOBAL_CUTOFF_DROP = "GLOBAL_CUTOFF_DROP"
    SESSION_AGGREGATION_SUPPRESSION = "SESSION_AGGREGATION_SUPPRESSION"
    REDUNDANCY_DISPLACEMENT = "REDUNDANCY_DISPLACEMENT"
    DEDUP_WRONG_REPRESENTATIVE = "DEDUP_WRONG_REPRESENTATIVE"
    ACCESS_DENIED_EXPECTED = "ACCESS_DENIED_EXPECTED"
    REVOCATION_FILTERED_EXPECTED = "REVOCATION_FILTERED_EXPECTED"
    POLICY_SCOPE_MISMATCH = "POLICY_SCOPE_MISMATCH"
    HYDRATION_NOT_FOUND = "HYDRATION_NOT_FOUND"
    HYDRATION_VERSION_MISMATCH = "HYDRATION_VERSION_MISMATCH"
    UNREADABLE_EVIDENCE = "UNREADABLE_EVIDENCE"
    SPAN_NOT_GROUNDED = "SPAN_NOT_GROUNDED"
    SUBJECT_MISMATCH = "SUBJECT_MISMATCH"
    PREDICATE_MISMATCH = "PREDICATE_MISMATCH"
    VALUE_TYPE_MISMATCH = "VALUE_TYPE_MISMATCH"
    SOURCE_ROLE_MISMATCH = "SOURCE_ROLE_MISMATCH"
    EVENT_TIME_MISMATCH = "EVENT_TIME_MISMATCH"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    DUPLICATE_BINDING = "DUPLICATE_BINDING"
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
    INTERPRETATION_NOT_PRODUCED = "INTERPRETATION_NOT_PRODUCED"
    PROOF_ACTION_NOT_AVAILABLE = "PROOF_ACTION_NOT_AVAILABLE"
    PROOF_ACTION_NOT_SELECTED = "PROOF_ACTION_NOT_SELECTED"
    BOUNDED_SCAN_INCOMPLETE = "BOUNDED_SCAN_INCOMPLETE"
    MAX_ITEMS_HIT = "MAX_ITEMS_HIT"
    SOURCE_PARTITION_NOT_CLOSED = "SOURCE_PARTITION_NOT_CLOSED"
    PROJECTION_BACKFILL_GAP = "PROJECTION_BACKFILL_GAP"
    AMBIGUOUS_EVENT_TIME = "AMBIGUOUS_EVENT_TIME"
    EVENT_IDENTITY_UNRESOLVED = "EVENT_IDENTITY_UNRESOLVED"
    DEDUP_INCOMPLETE = "DEDUP_INCOMPLETE"
    RAW_FALLBACK_INCOMPLETE = "RAW_FALLBACK_INCOMPLETE"
    ACCESS_SNAPSHOT_INVALID = "ACCESS_SNAPSHOT_INVALID"
    PROOF_VALIDATION_FAILED = "PROOF_VALIDATION_FAILED"


class RetrievalAuditIntegrityReason(StrEnum):
    STAGE_IMPLEMENTATION_UNBOUND = "STAGE_IMPLEMENTATION_UNBOUND"
    OCCURRENCE_LINEAGE_MISSING = "OCCURRENCE_LINEAGE_MISSING"
    DEDUP_LINEAGE_MISSING = "DEDUP_LINEAGE_MISSING"
    GOLD_ROLE_MAPPING_UNRESOLVED = "GOLD_ROLE_MAPPING_UNRESOLVED"
    PRODUCT_PROBE_PATH_DIVERGENCE = "PRODUCT_PROBE_PATH_DIVERGENCE"
    LABEL_PRODUCT_BOUNDARY_VIOLATION = "LABEL_PRODUCT_BOUNDARY_VIOLATION"
    TRACING_BEHAVIOR_CHANGED = "TRACING_BEHAVIOR_CHANGED"
    SNAPSHOT_IDENTITY_MISMATCH = "SNAPSHOT_IDENTITY_MISMATCH"
    SEAL_IDENTITY_MISMATCH = "SEAL_IDENTITY_MISMATCH"


class RetrievalDocumentIdentityV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    projection_kind: str
    projection_version: str
    index_identity: str
    document_id: str
    source_locator: str | None = None
    content_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class EvidenceRecordIdentityV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_id: str
    source_identity: str
    source_ref: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: str | None = None
    retention_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    permission_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceSpanIdentityV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    span_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_role: str
    occurrence_time: str | None = None

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be greater than span_start")
        return self


class RetrievalOccurrenceV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["retrieval-occurrence-v0.1"] = "retrieval-occurrence-v0.1"
    occurrence_id: str
    request_identity: str
    requirement_id: str | None = None
    channel: str
    channel_query_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    channel_query_semantic_summary: str
    normalized_terms: list[str] = Field(default_factory=list)
    generated_feature_ids: list[str] = Field(default_factory=list)
    retrieval_document_identity: RetrievalDocumentIdentityV01
    evidence_record_identity: EvidenceRecordIdentityV01 | None = None
    raw_rank: int = Field(ge=1)
    raw_score: float | None = None
    score_direction: Literal["HIGHER_IS_BETTER", "LOWER_IS_BETTER", "NOT_EXPOSED"]
    latency_ms: float | None = Field(default=None, ge=0)


class EvidenceCandidateV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["evidence-candidate-v0.1"] = "evidence-candidate-v0.1"
    candidate_identity: str
    evidence_record_identity: EvidenceRecordIdentityV01
    hydrated_span_identities: list[EvidenceSpanIdentityV01] = Field(default_factory=list)
    session_id: str | None = None
    turn_id: str | None = None
    region_id: str | None = None
    discovery_lineage: list[dict[str, Any]] = Field(default_factory=list)


class DedupDecisionV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["dedup-decision-v0.1"] = "dedup-decision-v0.1"
    dedup_policy_version: str
    dedup_key_version: str
    dedup_key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    winner_candidate_identity: str
    loser_candidate_identities: list[str]
    winner_reason: str
    preserved_channel_lineage: list[str]


class LifecycleDisposition(StrEnum):
    KEPT = "KEPT"
    DROPPED = "DROPPED"
    REJECTED = "REJECTED"
    REDISCOVERED = "REDISCOVERED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CandidateLifecycleStepV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_index: int = Field(ge=0)
    stage_id: str
    disposition: LifecycleDisposition
    reason_code: str
    rank_before: int | None = Field(default=None, ge=1)
    rank_after: int | None = Field(default=None, ge=1)
    cutoff: int | None = Field(default=None, ge=1)
    validator_identity: str
    decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateLifecycleTraceV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["candidate-lifecycle-trace-v0.1"] = "candidate-lifecycle-trace-v0.1"
    occurrence_id: str
    candidate_identity: str
    requirement_candidates: list[str]
    discovery: dict[str, Any]
    lifecycle: list[CandidateLifecycleStepV01]


class ProductRetrievalTraceV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["product-retrieval-trace-v0.1"] = "product-retrieval-trace-v0.1"
    run_identity: str
    request_identity: str
    query_identity: str
    query_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements: list[dict[str, Any]]
    channel_decisions: list[dict[str, Any]]
    occurrences: list[RetrievalOccurrenceV01]
    candidates: list[EvidenceCandidateV01]
    dedup_decisions: list[DedupDecisionV01]
    candidate_lifecycles: list[CandidateLifecycleTraceV01]
    proof_obligations: list[dict[str, Any]]
    terminal_digests: dict[str, str]
    behavior_neutrality: dict[str, Any]
    repository_call_trace: list[dict[str, Any]]
    safety: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def reject_gold_fields(cls, value: Any) -> Any:
        forbidden = {
            "expected_answer",
            "acceptable_evidence_ids",
            "acceptable_span_ids",
            "equivalence_group_id",
            "equivalence_group_ids",
            "gold_label",
            "correct_case",
            "correctness_labels",
        }
        if forbidden.intersection(_recursive_keys(value)):
            raise ValueError("gold fields are forbidden from product retrieval traces")
        return value


class OfficialAuditProbeTraceV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["official-audit-probe-trace-v0.1"] = "official-audit-probe-trace-v0.1"
    run_identity: str
    product_seal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_identity: str
    requirement_id: str
    channel: str
    official_executor_identity: str
    repository_identity: str
    index_identity: str
    snapshot_identity: str
    scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_audit_cap: int = Field(ge=1)
    disposition: str
    reason_code: str
    returned_occurrences: list[RetrievalOccurrenceV01]
    offline_cut_views: list[dict[str, Any]]
    mutations: dict[str, Literal[False]]
    product_binding_consumed: Literal[False] = False


def canonical_json(value: Any) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def semantic_sha256(value: Any) -> str:
    """Digest semantic fields while excluding characterization-only data."""

    return canonical_sha256(_strip_nonsemantic(_json_value(value)))


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _strip_nonsemantic(value: Any) -> Any:
    excluded = {
        "latency_ms",
        "created_at",
        "timestamp",
        "trace_id",
        "duration_ms",
        "durations_ms",
        "elapsed_ms",
        "total_ms",
        "causal_waited_ms",
        "waited_ms",
    }
    if isinstance(value, dict):
        return {
            key: _strip_nonsemantic(item)
            for key, item in value.items()
            if key not in excluded and not key.endswith("_latency_ms")
        }
    if isinstance(value, list):
        return [_strip_nonsemantic(item) for item in value]
    return value


def _recursive_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value}.union(
            *(_recursive_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value), set())
    return set()


__all__ = [
    "CandidateLifecycleStepV01",
    "CandidateLifecycleTraceV01",
    "DedupDecisionV01",
    "EvidenceCandidateV01",
    "EvidenceRecordIdentityV01",
    "EvidenceSpanIdentityV01",
    "LifecycleDisposition",
    "OfficialAuditProbeTraceV01",
    "ProductRetrievalTraceV01",
    "RetrievalAuditIntegrityReason",
    "RetrievalAuditReason",
    "RetrievalDocumentIdentityV01",
    "RetrievalOccurrenceV01",
    "canonical_json",
    "canonical_sha256",
    "semantic_sha256",
]
