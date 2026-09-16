from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from milai.application.errors import ContextOperationError
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.persistence import SessionContext
from milai.persistence.context_repository import ContextRepository


@dataclass(frozen=True, slots=True)
class ContextReceiptReuse:
    body: dict[str, Any] | None
    miss_reason: str | None
    validation_ms: float


class ContextReceiptService:
    """Issue and online-validate task-free ContextReceipt wire views."""

    def __init__(
        self,
        repository: ContextRepository,
        *,
        ttl_seconds: int = 300,
        byte_budget: int = 1_000_000,
    ) -> None:
        if not 1 <= ttl_seconds <= 86_400:
            raise ValueError("ContextReceipt TTL must be between 1 second and 1 day")
        if not 64 <= byte_budget <= 1_000_000:
            raise ValueError("ContextReceipt byte budget is outside ContextCapsule limits")
        self._repository = repository
        self._ttl_seconds = ttl_seconds
        self._byte_budget = byte_budget

    def reuse(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        request_id: str,
    ) -> ContextReceiptReuse:
        if request.previous_context_id is None:
            return ContextReceiptReuse(None, None, 0.0)
        started = perf_counter()
        # RYW must replay its causal token through the primary retrieval kernel.
        if request.consistency_mode == "READ_YOUR_WRITES":
            return ContextReceiptReuse(
                None,
                "RECEIPT_RYW_REQUIRES_PRIMARY",
                _elapsed_ms(started),
            )
        coverage = requirement_coverage(request)
        now = datetime.now(UTC)
        historical = request.valid_at is not None or request.known_at is not None
        validation = self._repository.validate_task_free_capsule(
            context,
            request.previous_context_id,
            expected_coverage=coverage,
            requested_scope=dict(request.requested_scope),
            required_authority=request.required_authority,
            required_freshness=request.required_freshness,
            valid_at=request.valid_at or now,
            known_at=request.known_at or now,
            historical=historical,
        )
        validation_ms = _elapsed_ms(started)
        if not validation.valid or validation.sections is None:
            return ContextReceiptReuse(None, validation.reason, validation_ms)
        state_view = validation.sections.get("MEMORY STATE VIEW")
        metadata = validation.sections.get("RECEIPT METADATA")
        if not isinstance(state_view, dict) or not isinstance(metadata, dict):
            return ContextReceiptReuse(None, "RECEIPT_SHAPE_INVALID", validation_ms)
        current_dependency = dependency_digest(
            state_view,
            validation.gate_outcomes,
        )
        if metadata.get("dependency_digest") != current_dependency:
            return ContextReceiptReuse(None, "RECEIPT_DEPENDENCY_CHANGED", validation_ms)
        if (
            validation.capsule_id is None
            or validation.issued_at is None
            or validation.expires_at is None
        ):
            return ContextReceiptReuse(None, "RECEIPT_SHAPE_INVALID", validation_ms)

        body = dict(state_view)
        body["context_receipt"] = _wire_receipt(
            validation.capsule_id,
            metadata,
            validation.issued_at,
            validation.expires_at,
        )
        body["request_id"] = request_id
        body["fallback_used"] = False
        body["fallback_reason"] = None
        body["receipt_reused"] = True
        body["access_trace"] = _reuse_access_trace(
            body,
            request,
            request_id,
            validation.canonical_position,
            validation_ms,
        )
        return ContextReceiptReuse(body, None, validation_ms)

    def issue(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        body: dict[str, Any],
    ) -> dict[str, Any] | None:
        if body.get("status") not in {"HIT", "PARTIAL"}:
            return None
        items = body.get("items")
        trace_value = body.get("trace_id")
        if not isinstance(items, list) or not items or not isinstance(trace_value, str):
            return None
        try:
            trace_id = UUID(trace_value)
            evidence_ids = sorted(
                {UUID(str(value)) for value in body.get("evidence_refs", [])}, key=str
            )
        except (TypeError, ValueError):
            return None
        canonical_position = _canonical_position(body)
        if canonical_position is None:
            return None
        coverage = requirement_coverage(request)
        outcome = _stored_outcome(body)
        receipt_evidence = self._repository.task_free_evidence(context, evidence_ids)
        evidence = [
            {**item, "pointer_id": str(uuid4())}
            for item in receipt_evidence
        ]
        gate_like = tuple(
            {
                "claim_id": item.get("claim_id"),
                "claim_version_id": item.get("claim_version_id"),
                "evidence_ids": item.get("evidence_ids", []),
                "open_issue_ids": item.get("open_issue_ids", []),
            }
            for item in items
            if isinstance(item, dict)
        )
        metadata: dict[str, Any] = {
            "schema_version": "context-receipt-v0.1",
            "requirement_coverage": coverage,
            "dependency_digest": dependency_digest(outcome, gate_like),
            "canonical_position": canonical_position,
            "invalidation_sequence": canonical_position,
            "freshness_at_issue": request.required_freshness,
            "consistency_mode_at_issue": request.consistency_mode,
            "historical": request.valid_at is not None or request.known_at is not None,
        }
        sections: dict[str, object] = {
            "MEMORY STATE VIEW": outcome,
            "OPEN ISSUE IDS": sorted(
                str(value) for value in body.get("open_issue_ids", [])
            ),
            "RETRIEVED EVIDENCE": evidence,
            "TRACE POINTERS": {"retrieval_trace_id": str(trace_id)},
            "RECEIPT METADATA": metadata,
        }
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
        built = self._repository.create_task_free_capsule(
            context,
            trace_id,
            sections,
            self._byte_budget,
            expires_at,
        )
        issued_at = _timestamp(built.get("issued_at"))
        actual_expires_at = _timestamp(built.get("expires_at"))
        return _wire_receipt(
            UUID(str(built["capsule_id"])),
            metadata,
            issued_at,
            actual_expires_at,
        )


def requirement_coverage(request: MemoryResolveRequest) -> dict[str, object]:
    return {
        "schema_version": "memory-requirement-coverage-v0.1",
        "query_digest": _sha256(request.query),
        "invocation_mode": request.invocation_mode,
        "requested_scope": request.requested_scope,
        "required_authority": request.required_authority,
        "required_freshness": request.required_freshness,
        "consistency_mode": request.consistency_mode,
        "causal_token_digest": (
            _sha256(request.causal_token) if request.causal_token is not None else None
        ),
        "budget": request.budget.model_dump(mode="json"),
        "entities": request.entities,
        "memory_types": request.memory_types,
        "temporal": request.temporal,
        "state_keys": [value.model_dump(mode="json") for value in request.state_keys],
        "claim_ids": [str(value) for value in request.claim_ids],
        "valid_at": request.valid_at.astimezone(UTC).isoformat()
        if request.valid_at is not None
        else None,
        "known_at": request.known_at.astimezone(UTC).isoformat()
        if request.known_at is not None
        else None,
    }


def dependency_digest(
    state_view: dict[str, Any],
    gate_outcomes: tuple[dict[str, Any], ...],
) -> str:
    items = state_view.get("items")
    rows = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    return _sha256(
        {
            "claim_heads": sorted(
                (
                    {
                        "claim_id": str(item.get("claim_id")),
                        "claim_version_id": str(item.get("claim_version_id")),
                    }
                    for item in rows
                ),
                key=lambda value: (value["claim_id"], value["claim_version_id"]),
            ),
            "evidence_refs": sorted(
                {
                    str(evidence_id)
                    for outcome in gate_outcomes
                    for evidence_id in outcome.get("evidence_ids", [])
                }
            ),
            "open_issue_ids": sorted(
                {
                    str(issue_id)
                    for outcome in gate_outcomes
                    for issue_id in outcome.get("open_issue_ids", [])
                }
            ),
        }
    )


def annotate_receipt_fallback(
    body: dict[str, Any], reason: str, validation_ms: float
) -> None:
    body["receipt_reused"] = False
    body["receipt_fallback_reason"] = reason
    body["fallback_used"] = True
    body["primary_fallback_reason"] = body.get("fallback_reason")
    body["fallback_reason"] = reason
    access_trace = body.get("access_trace")
    if not isinstance(access_trace, dict):
        return
    trace = dict(access_trace)
    attempted = trace.get("attempted_stages")
    stages = list(attempted) if isinstance(attempted, list) else []
    trace["attempted_stages"] = ["REUSE_VALIDATION", *stages]
    trace["fallback_reason"] = reason
    spans = trace.get("spans")
    updated_spans = dict(spans) if isinstance(spans, dict) else {}
    updated_spans["receipt_validation_ms"] = round(validation_ms, 3)
    repository_ms = updated_spans.get("repository_sql_ms")
    if isinstance(repository_ms, (int, float)) and not isinstance(repository_ms, bool):
        updated_spans["repository_sql_ms"] = round(repository_ms + validation_ms, 3)
    trace["spans"] = updated_spans
    body["access_trace"] = trace


def _stored_outcome(body: dict[str, Any]) -> dict[str, Any]:
    omitted = {
        "access_trace",
        "context_receipt",
        "fallback_reason",
        "fallback_used",
        "request_id",
        "receipt_fallback_reason",
        "receipt_reused",
        "task_enhancement",
    }
    return {key: value for key, value in body.items() if key not in omitted}


def _wire_receipt(
    capsule_id: UUID,
    metadata: dict[str, Any],
    issued_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": "context-receipt-v0.1",
        "context_capsule_id": str(capsule_id),
        "requirement_coverage": metadata["requirement_coverage"],
        "dependency_digest": metadata["dependency_digest"],
        "canonical_position": metadata["canonical_position"],
        "issued_at": issued_at.astimezone(UTC).isoformat(),
        "expires_at": expires_at.astimezone(UTC).isoformat(),
        "invalidation_sequence": metadata["invalidation_sequence"],
        "freshness_at_issue": metadata["freshness_at_issue"],
        "consistency_mode_at_issue": metadata["consistency_mode_at_issue"],
    }


def _reuse_access_trace(
    body: dict[str, Any],
    request: MemoryResolveRequest,
    request_id: str,
    canonical_position: int | None,
    validation_ms: float,
) -> dict[str, Any]:
    return {
        "schema_version": "access-trace-v0.1",
        "retrieval_trace_id": body.get("trace_id"),
        "runtime_request_id": request_id,
        "requested_intent": (body.get("interpretation") or {}).get("retrieval_intent"),
        "planned_stage": (
            "EXACT" if request.state_keys or request.claim_ids else "SEARCH"
        ),
        "attempted_stages": ["REUSE_VALIDATION"],
        "terminal_stage": "REUSE",
        "stop_reason": "CONTEXT_RECEIPT_VALIDATED",
        "fallback_reason": None,
        "canonical_position": canonical_position,
        "spans": {
            "mcp_decode_ms": None,
            "broker_ipc_ms": None,
            "state_address_ms": 0.0,
            "runtime_kernel_ms": round(validation_ms, 3),
            "repository_sql_ms": round(validation_ms, 3),
            "receipt_validation_ms": round(validation_ms, 3),
            "rerank_ms": 0.0,
            "hydrate_ms": 0.0,
            "host_total_ms": None,
        },
        "structural_cost": {
            "auxiliary_llm_calls": 0,
            "embedding_calls": 0,
            "vector_search_calls": 0,
            "reranker_calls": 0,
            "broad_head_scan_calls": 0,
        },
        "resolution_dimensions": None,
        "route_trace_complete": True,
        "trace_gap_reason": None,
    }


def _canonical_position(body: dict[str, Any]) -> int | None:
    raw = body.get("canonical_position")
    if isinstance(raw, dict):
        raw = raw.get("canonical_outbox_sequence")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return raw


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ContextOperationError("INVALID_TASK_FREE_CONTEXT_CAPSULE")
    return result


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)
