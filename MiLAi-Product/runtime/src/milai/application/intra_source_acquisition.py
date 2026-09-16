from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from milai.domain.memory_resolve import MemoryResolveRequest
from milai.persistence import SessionContext

_MAX_COARSE_SESSIONS = 50
_MAX_HITS_PER_SESSION = 8
_MAX_FINE_CANDIDATES = 120
_STRUCTURED_CONTEXT_SOURCES = frozenset(
    {"STRUCTURED_TURN_METADATA", "AUTHORITATIVE_BACKFILL"}
)


class IntraSourceEvidenceSearch(Protocol):
    def search_evidence_within_sources(
        self,
        context: SessionContext,
        query: str,
        coarse_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        *,
        hits_per_session: int,
        max_items: int,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class IntraSourceShadowResult:
    candidate_items: tuple[dict[str, Any], ...]
    trace: dict[str, object]


class IntraSourceAcquisitionService:
    """Run label-blind lexical turn retrieval inside acquired source/session pairs."""

    def __init__(self, repository: IntraSourceEvidenceSearch) -> None:
        self._repository = repository

    def shadow(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        *,
        coarse_candidate_items: tuple[dict[str, Any], ...],
        snapshot_as_of: datetime,
        decision_digest: str | None,
    ) -> IntraSourceShadowResult:
        pool = _coarse_pool(coarse_candidate_items)
        session_ids = list(dict.fromkeys(item["session_id"] for item in pool))
        if len(session_ids) > _MAX_COARSE_SESSIONS:
            raise ValueError("structured coarse session pool exceeds the fixed limit")
        pool_digest = _digest(pool)
        coarse_evidence_ids = [item["evidence_id"] for item in pool]
        effective_decision_digest = decision_digest or _digest(
            {
                "query": request.query,
                "coarse_pool_digest": pool_digest,
                "snapshot_as_of": snapshot_as_of.astimezone(UTC).isoformat(),
            }
        )
        items: list[dict[str, Any]] = []
        if session_ids:
            items = self._repository.search_evidence_within_sources(
                context,
                request.query,
                coarse_evidence_ids,
                dict(request.requested_scope),
                snapshot_as_of,
                hits_per_session=_MAX_HITS_PER_SESSION,
                max_items=_MAX_FINE_CANDIDATES,
                statement_timeout_ms=request.budget.max_latency_ms,
            )
        unique_items = _unique_evidence(items)
        coarse_evidence_id_set = {
            item["evidence_id"] for item in pool if isinstance(item.get("evidence_id"), str)
        }
        summaries = [
            _candidate_summary(
                item,
                coarse_evidence_ids=coarse_evidence_id_set,
                scope_digest=_digest(request.requested_scope),
                snapshot_as_of=snapshot_as_of,
                decision_digest=effective_decision_digest,
            )
            for item in unique_items
        ]
        trace: dict[str, object] = {
            "schema_version": "intra-source-acquisition-shadow-v0.1",
            "mode": "SHADOW",
            "status": "COMPLETE" if session_ids else "NO_STRUCTURED_SESSION_POOL",
            "acquisition_channel": "FTS_INTRA_SOURCE",
            "requested_coarse_pool": pool,
            "requested_coarse_pool_digest": pool_digest,
            "requested_coarse_session_ids": session_ids,
            "requested_coarse_session_count": len(session_ids),
            "requested_coarse_candidate_count": len(pool),
            "coarse_candidates_without_structured_session": max(
                0, len(coarse_candidate_items) - len(pool)
            ),
            "snapshot_as_of": snapshot_as_of.astimezone(UTC).isoformat(),
            "scope_digest": _digest(request.requested_scope),
            "decision_digest": effective_decision_digest,
            "hits_per_session_limit": _MAX_HITS_PER_SESSION,
            "fine_candidate_limit": _MAX_FINE_CANDIDATES,
            "fine_candidate_count": len(summaries),
            "matched_eligible_source_keys": _matched_source_keys(summaries),
            "rejected_or_duplicate_candidate_count": len(items) - len(unique_items),
            "novel_fine_candidate_count": sum(
                1 for item in summaries if item["already_in_coarse_pool"] is False
            ),
            "candidates": summaries,
            "public_context_changed": False,
            "frontier_changed": False,
            "new_global_source_acquisition_calls": 0,
            "hydration_credited_as_discovery": False,
            "hidden_model_calls": 0,
            "canonical_mutation": False,
        }
        return IntraSourceShadowResult(tuple(unique_items), trace)


def _coarse_pool(items: tuple[dict[str, Any], ...]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if item.get("kind") != "EVIDENCE_OBSERVATION":
            continue
        source_context = item.get("source_context")
        if not isinstance(source_context, dict):
            continue
        if item.get("source_context_source") not in _STRUCTURED_CONTEXT_SOURCES:
            continue
        session_id = source_context.get("session_id")
        evidence_id = item.get("evidence_id")
        if not isinstance(session_id, str) or not session_id:
            continue
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        identity = (session_id, evidence_id)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            {
                "session_id": session_id,
                "evidence_id": evidence_id,
                "source_ref": str(item.get("source_ref", "")),
            }
        )
    return result


def _unique_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not _valid_fine_candidate(item):
            continue
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        result.append(dict(item))
    return result[:_MAX_FINE_CANDIDATES]


def _valid_fine_candidate(item: dict[str, Any]) -> bool:
    evidence_id = item.get("evidence_id")
    source_type = item.get("source_type")
    source_ref = item.get("source_ref")
    content_hash = item.get("content_hash")
    source_context = item.get("source_context")
    if not all(
        isinstance(value, str) and bool(value)
        for value in (evidence_id, source_type, source_ref, content_hash)
    ):
        return False
    assert isinstance(content_hash, str)
    if len(content_hash) != 64 or any(value not in "0123456789abcdef" for value in content_hash):
        return False
    if not isinstance(source_context, dict):
        return False
    return all(
        isinstance(source_context.get(key), str) and bool(source_context[key])
        for key in ("session_id", "turn_id")
    )


def _candidate_summary(
    item: dict[str, Any],
    *,
    coarse_evidence_ids: set[str],
    scope_digest: str,
    snapshot_as_of: datetime,
    decision_digest: str,
) -> dict[str, object]:
    source_context = item.get("source_context")
    context_values = source_context if isinstance(source_context, dict) else {}
    evidence_id = str(item["evidence_id"])
    return {
        "evidence_id": evidence_id,
        "source_type": str(item.get("source_type", "")),
        "source_ref": str(item.get("source_ref", "")),
        "session_id": str(context_values.get("session_id", "")),
        "turn_or_span_id": str(context_values.get("turn_id", "")),
        "content_hash": str(item.get("content_hash", "")),
        "scope_digest": scope_digest,
        "snapshot_as_of": snapshot_as_of.astimezone(UTC).isoformat(),
        "decision_digest": decision_digest,
        "acquisition_channels": ["FTS_INTRA_SOURCE"],
        "channel_ranks": {
            "FTS_INTRA_SOURCE": int(item.get("fine_source_rank", 0))
        },
        "global_rank": int(item.get("fine_global_rank", 0)),
        "discovery_disposition": "DIRECT_ANCHOR",
        "already_in_coarse_pool": evidence_id in coarse_evidence_ids,
        "included_in_public_context": False,
        "included_in_frontier": False,
    }


def _matched_source_keys(items: list[dict[str, object]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        source_type = str(item["source_type"])
        session_id = str(item["session_id"])
        identity = (source_type, session_id)
        if identity in seen:
            continue
        seen.add(identity)
        result.append({"source_type": source_type, "session_id": session_id})
    return result


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "IntraSourceAcquisitionService",
    "IntraSourceShadowResult",
]
