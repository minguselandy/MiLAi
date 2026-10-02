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
                or len({c.source_ref for c in self.candidates}) != len(self.candidates)):
            raise ValueError("CORRECTION_CANDIDATE_POOL_INVALID")
        if any(instant(c.observed_at) > instant(self.query.cutoff) for c in self.candidates):
            raise ValueError("CORRECTION_CANDIDATE_AFTER_CUTOFF")

    @property
    def snapshot_sha256(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class SelectionPlan:
    snapshot_sha256: str
    selected_ids: tuple[str, ...]
    omitted_ids: tuple[str, ...]
    evidence_budget: int
    estimated_tokens: int
    strategy: str = "ordered_source_v1"


@dataclass(frozen=True)
class DeliveredSpan:
    source_ref: str
    source_sha256: str
    body_text_sha256: str
    start: int
    end: int
    content_sha256: str


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
