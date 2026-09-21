from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from milai.application.recollection import (
    MatchedReplayPolicy,
    MatchedRetrievalReplay,
)
from milai.application.retrieval_core.assembly import (
    _projection_state_payload,
    _response_body,
)
from milai.application.sufficiency import unavailable_decision
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.observability import OperationTimer
from milai.persistence.retrieval_repository import ProjectionState

_AssembledResults = tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, Any]],
    list[str],
]


@dataclass(frozen=True, slots=True)
class _LegacyReplayPrefix:
    assembled: _AssembledResults
    derived_result: dict[str, Any] | None
    progressive_l1: dict[str, Any]
    degraded: set[str]
    fallback_used: bool
    fallback_reason: str | None
    stage_metrics: dict[str, Any]
    stage_sequence: tuple[str, ...]


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_matched_retrieval_replay(
    *,
    request: RetrievalRequest,
    plan: QueryPlan,
    request_id: str,
    query_fingerprint: str,
    state: ProjectionState,
    trace_id: UUID,
    current_body: dict[str, Any],
    legacy_prefix: _LegacyReplayPrefix | None,
    minimum_outbox_sequence: int | None,
    causal_wait_outcome: str | None,
    causal_waited_ms: int,
) -> MatchedRetrievalReplay:
    evidence_snapshot = {
        "schema_version": "runtime-evidence-snapshot-v0.1",
        "projection_state": _projection_state_payload(state),
        "start_end_projection_identity_equal": True,
        "capture_mode": "ONE_RETRIEVAL_EXECUTION_PREFIX_REPLAY",
    }
    snapshot_digest = _canonical_sha256(evidence_snapshot)
    current = deepcopy(current_body)
    legacy_early_stop = legacy_prefix is not None
    if legacy_prefix is None:
        legacy = deepcopy(current_body)
    else:
        accepted, _rejected, results, open_issue_ids = legacy_prefix.assembled
        legacy_execution_trace = _execution_trace(
            request=request,
            plan=plan,
            stage_sequence=legacy_prefix.stage_sequence,
            progressive_l1=legacy_prefix.progressive_l1,
            fallback_reason=legacy_prefix.fallback_reason,
            abstention_reason=None,
            result_count=len(results),
        )
        legacy_access_trace = _access_trace_view(
            trace_id=trace_id,
            request_id=request_id,
            canonical_position=state.canonical_snapshot_outbox_sequence,
            execution_trace=legacy_execution_trace,
            stage_metrics=legacy_prefix.stage_metrics,
        )
        legacy_access_trace["matched_replay_view"] = True
        legacy_access_trace["shared_execution_trace_id"] = str(trace_id)
        legacy = _response_body(
            plan=plan,
            results=deepcopy(results),
            open_issue_ids=deepcopy(open_issue_ids),
            trace_id=trace_id,
            state=state,
            degraded=set(legacy_prefix.degraded),
            fallback_used=legacy_prefix.fallback_used,
            fallback_reason=legacy_prefix.fallback_reason,
            abstained=not bool(results),
            abstention_reason=None if results else "NO_CANDIDATE",
            minimum_outbox_sequence=minimum_outbox_sequence,
            causal_wait_outcome=causal_wait_outcome,
            causal_waited_ms=causal_waited_ms,
            derived_result=deepcopy(legacy_prefix.derived_result),
            stage_metrics=deepcopy(legacy_prefix.stage_metrics),
            progressive_l1=deepcopy(legacy_prefix.progressive_l1),
            access_trace=legacy_access_trace,
        )
        # The accepted prefix is deliberately retained only as replay metadata;
        # it is not persisted as a second RetrievalTrace or canonical outcome.
        legacy["matched_replay_accepted_count"] = len(accepted)
    policy_bodies: dict[MatchedReplayPolicy, dict[str, Any]] = {
        "DG16_ANY_EVIDENCE_STOP": legacy,
        "DG17_QUERY_SPECIFIC_STOP": current,
    }
    policy_metadata: dict[MatchedReplayPolicy, dict[str, Any]] = {
        "DG16_ANY_EVIDENCE_STOP": {
            "policy": "DG16_ANY_EVIDENCE_STOP",
            "early_stop_applied": legacy_early_stop,
            "stop_trigger": (
                "EVIDENCE_OBSERVATION_PRESENT"
                if legacy_early_stop
                else "NO_EVIDENCE_PREFIX_USE_CURRENT_OUTCOME"
            ),
            "typed_sufficiency_preserved": True,
            "fresh_retrieval_calls": 0,
        },
        "DG17_QUERY_SPECIFIC_STOP": {
            "policy": "DG17_QUERY_SPECIFIC_STOP",
            "early_stop_applied": False,
            "stop_trigger": "QUERY_SPECIFIC_SUFFICIENCY",
            "typed_sufficiency_preserved": True,
            "fresh_retrieval_calls": 1,
        },
    }
    shared = {
        "query_fingerprint": query_fingerprint,
        "retrieval_trace_id": str(trace_id),
        "retrieval_execution_count": 1,
        "evidence_snapshot_digest": snapshot_digest,
        "canonical_mutation": False,
    }
    for metadata in policy_metadata.values():
        metadata["shared_execution"] = dict(shared)
    return MatchedRetrievalReplay(
        schema_version="matched-retrieval-replay-v0.1",
        evidence_snapshot=evidence_snapshot,
        evidence_snapshot_digest=snapshot_digest,
        policy_bodies=policy_bodies,
        policy_metadata=policy_metadata,
    )


def _stage_metrics(stages: OperationTimer, started: float) -> dict[str, Any]:
    snapshot = stages.snapshot()
    elapsed_ms = (perf_counter() - started) * 1_000
    measured_stage_ms = sum(snapshot["durations_ms"].values())
    snapshot["durations_ms"]["query_total_ms"] = round(max(elapsed_ms, measured_stage_ms), 3)
    snapshot["counts"]["query_total_ms"] = 1
    return snapshot


def _public_acquisition_probe_disposition(value: Any) -> dict[str, Any]:
    """Keep the stable progressive trace while retaining the internal typed reason."""

    payload = cast(dict[str, Any], value.model_dump(mode="json"))
    payload["candidate_count"] = value.selected_candidate_count
    if value.reason_code in {
        "EVENT_TIME_FILTER_UNAVAILABLE",
        "SOURCE_TIME_FILTER_UNAVAILABLE",
    }:
        payload["status"] = value.reason_code
    return payload


def _public_temporal_acquisition_trace(
    query_axis: str,
    disposition: Any,
) -> dict[str, Any]:
    reason = str(disposition.reason_code)
    if disposition.channel == "TEMPORAL_EVENT" and reason in {
        "EVENT_PROJECTION_NOT_READY",
        "EVENT_PROJECTION_UNAVAILABLE",
    }:
        return {
            "query_axis": query_axis,
            "scan_axis": "CANDIDATE_SET",
            "disposition": "EVENT_PROJECTION_UNAVAILABLE",
        }
    return {
        "query_axis": query_axis,
        "scan_axis": (
            "SOURCE_OBSERVED_TIME"
            if disposition.channel == "SOURCE_OBSERVED_RANGE_SCAN"
            else "EVENT_OCCURRENCE_TIME"
        ),
        "disposition": reason,
    }


_EXECUTION_STAGE_BY_OPERATION = {
    "l0_ms": "EXACT",
    "state_address_resolution_ms": "EXACT",
    "evidence_fts_ms": "EVIDENCE_FTS",
    "evidence_slot_fts_ms": "EVIDENCE_FTS",
    "evidence_range_scan_ms": "EVIDENCE_RANGE_SCAN",
    "evidence_composition_ms": "COMPOSITION",
    "exact_ms": "EXACT",
    "fts_ms": "FTS",
    "vector_ms": "VECTOR",
    "recent_canonical_ms": "CANONICAL_FALLBACK",
    "canonical_fallback_ms": "CANONICAL_FALLBACK",
    "canonical_gate_ms": "CANONICAL_GATE",
    "result_assembly_preview_ms": "HYDRATE",
    "result_assembly_ms": "HYDRATE",
    "reranker_ms": "RERANKER",
    "query_operator_preview_ms": "SUFFICIENCY",
    "query_operator_ms": "SUFFICIENCY",
    "sufficiency_decision_ms": "SUFFICIENCY",
}


def _abstract_stage_sequence(operations: tuple[str, ...]) -> list[str]:
    stages: list[str] = []
    for operation in operations:
        stage = _EXECUTION_STAGE_BY_OPERATION.get(operation)
        if stage is not None and (not stages or stages[-1] != stage):
            stages.append(stage)
    return stages


def _execution_trace(
    *,
    request: RetrievalRequest,
    plan: QueryPlan,
    stage_sequence: tuple[str, ...],
    progressive_l1: dict[str, Any],
    fallback_reason: str | None,
    abstention_reason: str | None,
    result_count: int,
    resolution_dimensions: dict[str, bool] | None = None,
) -> dict[str, object]:
    attempted_stages = _abstract_stage_sequence(stage_sequence)
    progressive_stop = progressive_l1.get("stop_stage")
    if abstention_reason is not None:
        terminal_stage = (
            "SUFFICIENCY" if abstention_reason.startswith("OPERATOR_") else "CANONICAL_GATE"
        )
        stop_reason = abstention_reason
    elif isinstance(progressive_stop, str):
        terminal_stage = progressive_stop
        stop_reason = str(
            progressive_l1.get("sufficiency_reason") or "PROGRESSIVE_STOP_CONDITION_MET"
        )
    elif request.route == "L0":
        terminal_stage = "EXACT"
        stop_reason = "CANONICAL_EXACT_RESULT_RESOLVED"
    elif fallback_reason is not None and "CANONICAL_FALLBACK" in attempted_stages:
        terminal_stage = "CANONICAL_FALLBACK"
        stop_reason = fallback_reason
    else:
        terminal_stage = next(
            (
                stage
                for stage in reversed(attempted_stages)
                if stage in {"RERANKER", "VECTOR", "FTS", "EXACT", "CANONICAL_FALLBACK"}
            ),
            "CANONICAL_GATE",
        )
        stop_reason = "CANONICAL_RESULTS_RESOLVED"
    trace: dict[str, object] = {
        "schema_version": "retrieval-execution-v1",
        "requested_intent": request.memory_intent,
        "planned_stage": "EXACT" if plan.complexity == "L0" else "SEARCH",
        "attempted_stages": attempted_stages,
        "terminal_stage": terminal_stage,
        "stop_reason": stop_reason,
        "fallback_reason": fallback_reason,
        "result_count": result_count,
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "sufficiency_decision": progressive_l1.get("terminal_sufficiency_decision"),
    }
    if resolution_dimensions is not None:
        trace["resolution_dimensions"] = dict(resolution_dimensions)
    acquisition_state = progressive_l1.get("acquisition_state")
    if isinstance(acquisition_state, dict):
        trace["acquisition_state"] = dict(acquisition_state)
    return trace


def _latency_spans(stage_metrics: dict[str, Any]) -> dict[str, float | None]:
    raw_durations = stage_metrics.get("durations_ms")
    durations = raw_durations if isinstance(raw_durations, dict) else {}

    def duration(name: str) -> float:
        value = durations.get(name, 0.0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return 0.0

    sql_operations = (
        "projection_state_ms",
        "l0_ms",
        "state_address_resolution_ms",
        "exact_ms",
        "fts_ms",
        "vector_ms",
        "recent_canonical_ms",
        "canonical_fallback_ms",
        "canonical_gate_ms",
    )
    return {
        "mcp_decode_ms": None,
        "broker_ipc_ms": None,
        "state_address_ms": duration("state_address_resolution_ms"),
        "runtime_kernel_ms": duration("query_total_ms"),
        "formation_selection_ms": duration("formation_selection_ms"),
        "formation_hydration_ms": duration("formation_hydration_ms"),
        "repository_sql_ms": round(sum(duration(name) for name in sql_operations), 3),
        "rerank_ms": duration("reranker_ms"),
        "hydrate_ms": round(
            duration("result_assembly_preview_ms") + duration("result_assembly_ms"), 3
        ),
        "host_total_ms": None,
    }


def _structural_cost(stage_metrics: dict[str, Any]) -> dict[str, int]:
    raw_counts = stage_metrics.get("counts")
    counts = raw_counts if isinstance(raw_counts, dict) else {}

    def count(name: str) -> int:
        value = counts.get(name, 0)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0

    return {
        "auxiliary_llm_calls": 0,
        "embedding_calls": count("query_embedding_ms"),
        "vector_search_calls": count("vector_ms"),
        "reranker_calls": count("reranker_ms"),
        "broad_head_scan_calls": count("canonical_fallback_ms"),
    }


def _access_trace_view(
    *,
    trace_id: UUID,
    request_id: str,
    canonical_position: int,
    execution_trace: dict[str, object],
    stage_metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "access-trace-v0.1",
        "retrieval_trace_id": str(trace_id),
        "runtime_request_id": request_id,
        "requested_intent": execution_trace.get("requested_intent"),
        "planned_stage": execution_trace.get("planned_stage"),
        "attempted_stages": execution_trace.get("attempted_stages", []),
        "terminal_stage": execution_trace.get("terminal_stage"),
        "stop_reason": execution_trace.get("stop_reason"),
        "fallback_reason": execution_trace.get("fallback_reason"),
        "canonical_position": canonical_position,
        "spans": _latency_spans(stage_metrics),
        "structural_cost": _structural_cost(stage_metrics),
        "resolution_dimensions": execution_trace.get("resolution_dimensions"),
        "route_trace_complete": execution_trace.get("route_trace_complete") is True,
        "trace_gap_reason": execution_trace.get("trace_gap_reason"),
        "sufficiency_decision": execution_trace.get("sufficiency_decision"),
        "acquisition_state": execution_trace.get("acquisition_state"),
    }


def _unavailable_access_trace(
    *,
    request: RetrievalRequest,
    plan: QueryPlan,
    request_id: str,
    stage_sequence: tuple[str, ...],
    fallback_reason: str | None,
    stage_metrics: dict[str, Any],
    resolution_dimensions: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "access-trace-v0.1",
        "retrieval_trace_id": None,
        "runtime_request_id": request_id,
        "requested_intent": request.memory_intent,
        "planned_stage": "EXACT" if plan.complexity == "L0" else "SEARCH",
        "attempted_stages": _abstract_stage_sequence(stage_sequence),
        "terminal_stage": "CANONICAL_STORE",
        "stop_reason": "CANONICAL_UNAVAILABLE",
        "fallback_reason": fallback_reason,
        "canonical_position": None,
        "spans": _latency_spans(stage_metrics),
        "structural_cost": _structural_cost(stage_metrics),
        "resolution_dimensions": resolution_dimensions,
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "sufficiency_decision": unavailable_decision().payload(),
    }
