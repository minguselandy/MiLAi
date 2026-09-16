from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from milai.application.retrieval import RetrievalExecution, RetrievalService
from milai.application.state_address import StateAddressService
from milai.domain.memory_state import MemoryStateGetRequest
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import DatabaseUnavailable, SessionContext


class MemoryStateViewService:
    """Build a non-authoritative, governed State view from canonical objects."""

    def __init__(
        self,
        addresses: StateAddressService,
        retrieval: RetrievalService,
    ) -> None:
        self._addresses = addresses
        self._retrieval = retrieval

    def get(
        self,
        context: SessionContext,
        request: MemoryStateGetRequest,
        request_id: str,
    ) -> RetrievalExecution:
        address_started = perf_counter()
        try:
            resolved, valid_at, known_at = self._addresses.resolve(context, request)
        except DatabaseUnavailable:
            address_resolution_ms = (perf_counter() - address_started) * 1_000
            now = datetime.now(UTC)
            valid_at = request.valid_at or now
            known_at = request.known_at or now
            return RetrievalExecution(
                _unavailable_state_view(
                    request,
                    request_id,
                    valid_at,
                    known_at,
                    address_resolution_ms,
                ),
                status_code=503,
            )
        address_resolution_ms = (perf_counter() - address_started) * 1_000

        retrieval_request = RetrievalRequest(
            route="L0",
            memory_intent="HISTORY" if request.historical else "CURRENT_STATE",
            evidence_need="SUPPORT_POINTERS",
            claim_id=request.claim_id,
            subject_id=(request.state_key.subject if request.state_key is not None else None),
            predicate=(request.state_key.predicate if request.state_key is not None else None),
            claim_type=(request.state_key.claim_type if request.state_key is not None else None),
            requested_scope=request.requested_scope,
            required_authority=request.required_authority,
            consistency=request.consistency_mode,
            causal_token=request.causal_token,
            as_of=valid_at,
            system_as_of=known_at,
            limit=1,
        )
        execution = self._retrieval.retrieve(
            context,
            retrieval_request,
            request_id,
            resolved_claim_version_id=resolved.claim_version_id,
            resolution_dimensions={
                "addressable": resolved.addressable,
                "reachable": resolved.reachable,
                "correctly_resolved": False,
            },
            state_address_resolution_ms=address_resolution_ms,
            allow_historical=request.historical,
        )
        body = execution.body
        raw_results = body.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        items = [_minimal_state_view(item) for item in results if isinstance(item, dict)]
        raw_issues = body.get("open_issue_ids")
        open_issue_ids = (
            sorted({str(value) for value in raw_issues if isinstance(value, str)})
            if isinstance(raw_issues, list)
            else []
        )
        if body.get("abstention_reason") == "CANONICAL_UNAVAILABLE":
            status = "UNAVAILABLE"
            availability = "UNAVAILABLE"
        elif body.get("abstention_reason") == "ACCESS_DENIED":
            status = "DENIED"
            availability = "AVAILABLE"
        elif open_issue_ids:
            status = "CONTESTED"
            availability = "DEGRADED"
        elif items:
            status = "HIT"
            availability = "AVAILABLE"
        elif not resolved.addressable or not resolved.reachable:
            status = "ABSENT"
            availability = "AVAILABLE"
        else:
            status = "ABSTAINED"
            availability = "AVAILABLE"
        evidence_refs = sorted(
            {
                str(evidence_id)
                for item in items
                for evidence_id in item.get("evidence_ids", [])
                if isinstance(evidence_id, str)
            }
        )
        return RetrievalExecution(
            {
                "schema_version": "memory-state-view-v0.1",
                "status": status,
                "items": items,
                "open_issue_ids": open_issue_ids,
                "evidence_refs": evidence_refs,
                "availability": availability,
                "abstention_reason": (
                    "STATE_ADDRESS_NOT_FOUND"
                    if not resolved.addressable
                    else "STATE_VERSION_NOT_REACHABLE"
                    if not resolved.reachable
                    else body.get("abstention_reason")
                ),
                "consistency": body.get("consistency"),
                "canonical_position": body.get("snapshot"),
                "trace_id": body.get("retrieval_trace_id"),
                "access_trace": body.get("access_trace"),
                "resolution": {
                    "mode": "HISTORICAL" if request.historical else "CURRENT",
                    "valid_at": valid_at.isoformat(),
                    "known_at": known_at.isoformat(),
                    "addressable": resolved.addressable,
                    "reachable": resolved.reachable,
                    "correctly_resolved": bool(
                        ((body.get("access_trace") or {}).get("resolution_dimensions") or {}).get(
                            "correctly_resolved"
                        )
                    ),
                },
                "request_id": request_id,
            },
            status_code=execution.status_code,
        )


def _minimal_state_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "MEMORY_STATE_VIEW",
        "claim_id": item.get("claim_id"),
        "claim_version_id": item.get("claim_version_id"),
        "subject_id": item.get("subject_id"),
        "predicate": item.get("predicate"),
        "claim_type": item.get("claim_type"),
        "version_number": item.get("version_number"),
        "payload": item.get("payload"),
        "valid_time_from": item.get("valid_time_from"),
        "valid_time_to": item.get("valid_time_to"),
        "system_time": item.get("system_time"),
        "lifecycle": item.get("lifecycle"),
        "epistemic_status": item.get("epistemic_status"),
        "freshness": item.get("freshness"),
        "authority": item.get("authority"),
        "confidence": item.get("confidence"),
        "canonical_commit_seq": item.get("canonical_commit_seq"),
        "evidence_ids": list(item.get("evidence_ids", [])),
        "open_issue_ids": list(item.get("open_issue_ids", [])),
    }


def _unavailable_state_view(
    request: MemoryStateGetRequest,
    request_id: str,
    valid_at: datetime,
    known_at: datetime,
    address_resolution_ms: float,
) -> dict[str, Any]:
    return {
        "schema_version": "memory-state-view-v0.1",
        "status": "UNAVAILABLE",
        "items": [],
        "open_issue_ids": [],
        "evidence_refs": [],
        "availability": "UNAVAILABLE",
        "abstention_reason": "CANONICAL_UNAVAILABLE",
        "consistency": request.consistency_mode,
        "canonical_position": None,
        "trace_id": None,
        "access_trace": {
            "schema_version": "access-trace-v0.1",
            "retrieval_trace_id": None,
            "runtime_request_id": request_id,
            "planned_stage": "EXACT",
            "attempted_stages": [],
            "terminal_stage": "CANONICAL_STORE",
            "stop_reason": "CANONICAL_UNAVAILABLE",
            "fallback_reason": None,
            "canonical_position": None,
            "spans": {
                "runtime_kernel_ms": round(address_resolution_ms, 3),
                "repository_sql_ms": round(address_resolution_ms, 3),
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
        },
        "resolution": {
            "mode": "HISTORICAL" if request.historical else "CURRENT",
            "valid_at": valid_at.isoformat(),
            "known_at": known_at.isoformat(),
            "addressable": False,
            "reachable": False,
            "correctly_resolved": False,
        },
        "request_id": request_id,
    }
