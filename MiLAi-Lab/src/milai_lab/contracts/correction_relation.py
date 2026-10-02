"""Opt-in v13.4 research views; no evaluator labels or business authority."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def digest(value: Any) -> str:
    return text_sha256(canonical(value))


def check_sha(value: str) -> None:
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("CORRECTION_HASH_INVALID")


def instant(value: str) -> datetime:
    if type(value) is not str:
        raise ValueError("CORRECTION_AWARE_TIME_REQUIRED")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("CORRECTION_AWARE_TIME_REQUIRED")
    return result


@dataclass(frozen=True)
class QueryView:
    question: str
    owner: str
    bank: tuple[str, ...]
    cutoff: str
    config_sha256: str
    query_id: str

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v for v in (self.question, self.owner, self.query_id)):
            raise ValueError("CORRECTION_QUERY_INVALID")
        if (type(self.bank) is not tuple or not self.bank or self.bank[-1] != self.owner
                or any(type(v) is not str or not v for v in self.bank)):
            raise ValueError("CORRECTION_OWNER_BANK_MISMATCH")
        check_sha(self.config_sha256)
        instant(self.cutoff)


@dataclass(frozen=True)
class EvidenceCandidate:
    """Selector-visible metadata only. IDs/hashes are identities, never ranking features."""

    source_ref: str
    role: str
    observed_at: str
    source_sha256: str
    body_text_sha256: str
    codepoints: int
    unit_tokens: int
    retrieval_score: float = 0.0
    valid_time_status: str = "unknown"
    scope_status: str = "unknown"

    def __post_init__(self) -> None:
        if not self.source_ref or self.role not in {"user", "tool", "assistant"}:
            raise ValueError("CORRECTION_SOURCE_METADATA_INVALID")
        instant(self.observed_at)
        check_sha(self.source_sha256)
        check_sha(self.body_text_sha256)
        if (type(self.codepoints) is not int or self.codepoints < 0
                or type(self.unit_tokens) is not int or self.unit_tokens < 0
                or type(self.retrieval_score) not in {int, float}
                or not math.isfinite(self.retrieval_score)):
            raise ValueError("CORRECTION_CANDIDATE_COST_INVALID")
        if self.valid_time_status != "unknown" or self.scope_status != "unknown":
            raise ValueError("CORRECTION_N1_SEMANTIC_METADATA_UNAVAILABLE")


@dataclass(frozen=True)
class SegmentProfile:
    """Query-free source partition; the tokenizer identity is bound by the bank index."""

    max_body_tokens: int = 384
    algorithm: str = "paragraph_line_whitespace_codepoint_v1"

    def __post_init__(self) -> None:
        if (type(self.max_body_tokens) is not int or self.max_body_tokens <= 0
                or self.algorithm != "paragraph_line_whitespace_codepoint_v1"):
            raise ValueError("CORRECTION_SEGMENT_PROFILE_INVALID")


@dataclass(frozen=True, kw_only=True)
class EvidenceSpanCandidate(EvidenceCandidate):
    """One immutable original-body span; inherited codepoints describes the full body."""

    candidate_id: str
    start: int
    end: int
    span_sha256: str

    def __post_init__(self) -> None:
        super().__post_init__()
        check_sha(self.span_sha256)
        if (type(self.start) is not int or type(self.end) is not int
                or not 0 <= self.start < self.end <= self.codepoints
                or self.candidate_id != span_identity(
                    self.source_ref, self.source_sha256, self.body_text_sha256,
                    self.start, self.end, self.span_sha256)):
            raise ValueError("CORRECTION_SPAN_IDENTITY_INVALID")


def span_identity(
    source_ref: str, source_sha256: str, body_text_sha256: str,
    start: int, end: int, span_sha256: str,
) -> str:
    return "span-" + digest(["evidence_span_v1", source_ref, source_sha256,
                             body_text_sha256, start, end, span_sha256])


def candidate_identity(candidate: EvidenceCandidate) -> str:
    return (candidate.candidate_id if isinstance(candidate, EvidenceSpanCandidate)
            else candidate.source_ref)


@dataclass(frozen=True)
class BoundSourceSpan:
    source_ref: str
    source_sha256: str
    body_text_sha256: str
    start: int
    end: int
    span_sha256: str
    text_role: str = "source_text"

    def __post_init__(self) -> None:
        if (type(self.source_ref) is not str or not self.source_ref
                or type(self.start) is not int or type(self.end) is not int
                or not 0 <= self.start < self.end
                or self.text_role not in {"source_text", "quoted_predecessor",
                                         "correction_text", "relation_witness"}):
            raise ValueError("CORRECTION_RELATION_SPAN_INVALID")
        for value in (self.source_sha256, self.body_text_sha256, self.span_sha256):
            check_sha(value)


@dataclass(frozen=True)
class SourceRelation:
    """Public, query-free relation annotation; span binding does not verify semantics."""

    predecessor_spans: tuple[BoundSourceSpan, ...]
    successor_spans: tuple[BoundSourceSpan, ...]
    witness_spans: tuple[BoundSourceSpan, ...]
    location_status: str = "exact_quote"
    relation_kind: str = "public_correction"

    def __post_init__(self) -> None:
        if (any(type(group) is not tuple or not group
                or any(not isinstance(span, BoundSourceSpan) for span in group)
                for group in (self.predecessor_spans, self.successor_spans, self.witness_spans))
                or self.location_status not in {"exact_quote", "section_pointer", "ambiguous",
                                                "quoted_only", "unknown"}
                or self.relation_kind != "public_correction"):
            raise ValueError("CORRECTION_RELATION_INVALID")

    @property
    def relation_id(self) -> str:
        return "rel-" + digest(asdict(self))


@dataclass(frozen=True)
class FrozenEvidenceCue:
    """A public field or frozen extraction hypothesis, never a verified semantic fact."""

    dimension: str
    value: str
    quote_spans: tuple[BoundSourceSpan, ...]
    provenance: str
    time_axis: str | None = None

    def __post_init__(self) -> None:
        if (self.dimension not in {"time", "scope", "exception", "relation"}
                or type(self.value) is not str or not self.value.strip()
                or type(self.quote_spans) is not tuple or not self.quote_spans
                or any(not isinstance(span, BoundSourceSpan) for span in self.quote_spans)
                or self.provenance not in {"native_public", "frozen_writer"}
                or self.time_axis not in {None, "publication", "report", "verification",
                                          "effective"}
                or (self.time_axis is not None and self.dimension != "time")
                or (self.time_axis == "effective" and self.provenance != "frozen_writer")):
            raise ValueError("CORRECTION_CUE_INVALID")
        if len({(span.source_ref, span.source_sha256, span.body_text_sha256)
                for span in self.quote_spans}) != 1:
            raise ValueError("CORRECTION_CUE_REQUIRES_ONE_SOURCE")

    @property
    def cue_id(self) -> str:
        return "cue-" + digest(asdict(self))


@dataclass(frozen=True)
class EvidenceCueView:
    cue_id: str
    dimension: str
    value: str
    provenance: str
    time_axis: str | None
    date_literals: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    total_projected_spans: int
    partial_quote_candidate_ids: tuple[str, ...]
    quote_match_count: int


@dataclass(frozen=True)
class ChainGroup:
    group_id: str
    candidate_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    material_tokens: int


@dataclass(frozen=True)
class ResearchSnapshot:
    """Research identity, deliberately distinct from public-turn selected_snapshot_v1."""

    query: QueryView
    bank_sha256: str
    index_sha256: str
    tokenizer_sha256: str
    candidates: tuple[EvidenceCandidate, ...]
    retrieval: str = "ordinary_bm25_source_v1"

    def __post_init__(self) -> None:
        for value in (self.bank_sha256, self.index_sha256, self.tokenizer_sha256):
            check_sha(value)
        if (type(self.candidates) is not tuple or len(self.candidates) > 32
                or len({candidate_identity(c) for c in self.candidates}) != len(self.candidates)):
            raise ValueError("CORRECTION_CANDIDATE_POOL_INVALID")
        if any(instant(c.observed_at) > instant(self.query.cutoff) for c in self.candidates):
            raise ValueError("CORRECTION_CANDIDATE_AFTER_CUTOFF")

    @property
    def snapshot_sha256(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True, kw_only=True)
class ChainResearchSnapshot(ResearchSnapshot):
    groups: tuple[ChainGroup, ...]
    ordinary_seed_ids: tuple[str, ...]
    pool_omitted_ids: tuple[str, ...]
    unclosed_relation_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class MetadataChainSnapshot(ChainResearchSnapshot):
    cue_projections: tuple[EvidenceCueView, ...]
    metadata_sha256: str

    def __post_init__(self) -> None:
        super().__post_init__()
        check_sha(self.metadata_sha256)
        pool = {candidate_identity(candidate) for candidate in self.candidates}
        if (len({cue.cue_id for cue in self.cue_projections}) != len(self.cue_projections)
                or any(not cue.candidate_ids or not set(cue.candidate_ids) <= pool
                       or cue.total_projected_spans < len(cue.candidate_ids)
                       or not set(cue.partial_quote_candidate_ids) <= set(cue.candidate_ids)
                       or cue.quote_match_count < 1
                       for cue in self.cue_projections)):
            raise ValueError("CORRECTION_CUE_POOL_BINDING_CHANGED")


@dataclass(frozen=True)
class SelectionPlan:
    snapshot_sha256: str
    selected_ids: tuple[str, ...]
    omitted_ids: tuple[str, ...]
    evidence_budget: int
    estimated_tokens: int
    strategy: str = "ordered_source_v1"


@dataclass(frozen=True, kw_only=True)
class ChainSelectionPlan(SelectionPlan):
    complete_group_ids: tuple[str, ...]
    incomplete_group_ids: tuple[str, ...]
    group_cost_decisions: tuple[ChainGroupCostDecision, ...]


@dataclass(frozen=True)
class ChainGroupCostDecision:
    group_id: str
    available_in_pool: bool
    exact_group_material_tokens: int
    estimated_combined_tokens: int
    selected_as_complete: bool


@dataclass(frozen=True)
class DeliveredSpan:
    source_ref: str
    source_sha256: str
    body_text_sha256: str
    start: int
    end: int
    content_sha256: str


@dataclass(frozen=True, kw_only=True)
class DeliveredEvidenceSpan(DeliveredSpan):
    candidate_id: str


@dataclass(frozen=True)
class DeliveryReceipt:
    snapshot_sha256: str
    selected_ids: tuple[str, ...]
    read_ids: tuple[str, ...]
    delivered: tuple[DeliveredSpan, ...]
    omitted_ids: tuple[str, ...]
    material_sha256: str
    material_tokens: int
    evidence_budget: int
    tokenizer_sha256: str
    body_serialization: str = "string_verbatim_else_json_sorted_utf8_v1"
    range_basis: str = "body_text_unicode_codepoints_half_open"
    consumption_status: str = "not_evaluated"


@dataclass(frozen=True, kw_only=True)
class ChainDeliveryReceipt(DeliveryReceipt):
    complete_group_ids: tuple[str, ...]
    incomplete_group_ids: tuple[str, ...]
    unclosed_relation_ids: tuple[str, ...]
    group_cost_decisions: tuple[ChainGroupCostDecision, ...]
    planning_estimated_tokens: int
    planning_minus_material_tokens: int
    packing_omitted_ids: tuple[str, ...]
    cost_scope: str = ("first group exact; later boundaries estimated; "
                       "delta includes packing omissions")
