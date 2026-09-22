"""Published, label-free observation of one official Memory resolve execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from milai.application.memory_resolve import MemoryResolveService
from milai.config import RuntimeSettings
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.domain.retrieval_audit import canonical_sha256
from milai.observability.retrieval_audit import ProductRetrievalAuditObserver
from milai.persistence import SessionContext
from milai.testkit.runtime_owner_trace import RuntimeOwnerTraceObserver

_STAGE_REGISTRY = (
    "S12:OFFICIAL_REPOSITORY_RETURN",
    "S14:OFFICIAL_CHANNEL_ORDER",
    "S15:OFFICIAL_PRODUCT_CUTOFF",
    "S20:CROSS_CHANNEL_UNION",
    "S21:EVIDENCE_ID_DEDUP",
    "S22:FIXED_PRIORITY_SUPPRESSION",
    "S23:GLOBAL_RESULT_CUTOFF",
    "S30:BODY_HYDRATION",
    "S31:GOVERNANCE_GATE",
    "S32:EVIDENCE_SET",
    "S40:SPAN_PROJECTION",
    "S41:INTERPRETATION",
    "S42:BINDING",
    "S43:REQUIREMENT_STATE",
    "S44:SUFFICIENCY",
    "S45:OPERATOR_READINESS",
    "C50:CONTEXT_ADMISSION",
    "M60:MCP_RENDER",
)


class RetrievalTraceTestkitRequest(BaseModel):
    """Versioned stdin contract for ``milai-retrieval-trace-testkit``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["milai-retrieval-trace-testkit-request-v0.1"]
    run_identity: str = Field(min_length=1, max_length=256)
    source_snapshot_as_of: datetime
    memory_request: MemoryResolveRequest
    comparison_semantics_version: Literal["v0.1", "v0.2"] = "v0.1"

    @field_validator("source_snapshot_as_of")
    @classmethod
    def validate_source_snapshot(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source_snapshot_as_of must include a timezone offset")
        return value


def run_live_retrieval_trace(
    request: RetrievalTraceTestkitRequest,
    *,
    settings: RuntimeSettings | None = None,
    include_owner_trace: bool = False,
) -> dict[str, Any]:
    """Run normal/baseline/traced reads and publish only an exactly neutral trace."""

    from milai.config import load_settings

    runtime_settings = settings or load_settings()
    memory_request = request.memory_request
    if memory_request.required_authority != "INFORMATIONAL":
        raise ValueError("retrieval trace testkit supports informational reads only")
    if memory_request.state_keys or memory_request.claim_ids:
        raise ValueError("retrieval trace testkit does not observe Canonical exact reads")
    if memory_request.previous_context_id is not None:
        raise ValueError("X1 trace cannot start from a previous Context")
    source_snapshot = request.source_snapshot_as_of

    normal_body = _resolve_once(
        runtime_settings,
        memory_request,
        source_snapshot=source_snapshot,
        observer=None,
        record_repository_calls=False,
        request_id=f"{request.run_identity}:normal",
        verify_binding=request.comparison_semantics_version == "v0.2",
    )
    baseline_observer = ProductRetrievalAuditObserver(enabled=False)
    baseline_body = _resolve_once(
        runtime_settings,
        memory_request,
        source_snapshot=source_snapshot,
        observer=baseline_observer,
        record_repository_calls=True,
        request_id=f"{request.run_identity}:baseline",
        verify_binding=request.comparison_semantics_version == "v0.2",
    )
    traced_observer = (
        RuntimeOwnerTraceObserver()
        if include_owner_trace else ProductRetrievalAuditObserver(enabled=True)
    )
    traced_body = _resolve_once(
        runtime_settings,
        memory_request,
        source_snapshot=source_snapshot,
        observer=traced_observer,
        record_repository_calls=True,
        request_id=f"{request.run_identity}:traced",
        verify_binding=request.comparison_semantics_version == "v0.2",
    )

    semantics = (_response_semantics_v2 if request.comparison_semantics_version == "v0.2"
                 else _response_semantics)
    normal_semantics = semantics(normal_body)
    baseline_semantics = semantics(baseline_body)
    traced_semantics = semantics(traced_body)
    response_equal = normal_semantics == baseline_semantics == traced_semantics
    observer_equal = baseline_observer.semantic_digest == traced_observer.semantic_digest
    repository_equal = (
        baseline_observer.repository_semantic_digest()
        == traced_observer.repository_semantic_digest()
    )
    if not response_equal or not observer_equal or not repository_equal:
        detail = {
            "comparison_semantics_version": request.comparison_semantics_version,
            "response_equal": response_equal,
            "response_field_diff": {
                "normal_baseline": _response_field_diff(normal_semantics, baseline_semantics),
                "baseline_traced": _response_field_diff(baseline_semantics, traced_semantics),
            },
            "observer_equal": observer_equal,
            "repository_equal": repository_equal,
            "normal_response_digest": canonical_sha256(normal_semantics),
            "baseline_response_digest": canonical_sha256(baseline_semantics),
            "traced_response_digest": canonical_sha256(traced_semantics),
            "baseline_observer_digest": baseline_observer.semantic_digest,
            "traced_observer_digest": traced_observer.semantic_digest,
            "baseline_repository_digest": (
                baseline_observer.repository_semantic_digest()
            ),
            "traced_repository_digest": traced_observer.repository_semantic_digest(),
            "repository_call_diff": _repository_call_diff(
                baseline_observer.repository_calls,
                traced_observer.repository_calls,
            ),
        }
        raise RuntimeError(
            "TRACING_BEHAVIOR_CHANGED "
            + json.dumps(detail, sort_keys=True, separators=(",", ":"))
        )
    query_ir = traced_observer.captured_query_plan.memory_query_ir
    if query_ir is None:
        raise RuntimeError("RETRIEVAL_AUDIT_QUERY_IR_NOT_AVAILABLE")
    product_trace = traced_observer.build_product_trace(
        run_identity=request.run_identity,
        query_ir=query_ir,
        stage_registry_digest=canonical_sha256(_STAGE_REGISTRY),
        baseline_digest=baseline_observer.semantic_digest,
    )
    if product_trace.behavior_neutrality.get("exact_match") is not True:
        raise RuntimeError("TRACING_BEHAVIOR_CHANGED")
    join = _mcp_join_expectation(traced_body)
    report = {
        "schema_version": "milai-retrieval-trace-testkit-report-"
                          + request.comparison_semantics_version,
        "comparison_semantics_version": request.comparison_semantics_version,
        "legacy_response_semantic_digests": {
            name: canonical_sha256(_response_semantics(body))
            for name, body in (("normal", normal_body), ("baseline", baseline_body),
                               ("traced", traced_body))
        },
        "local_identity_bindings": {
            name: deepcopy(body.get("_testkit_root_binding"))
            for name, body in (("normal", normal_body), ("baseline", baseline_body),
                               ("traced", traced_body))
        },
        "run_identity": request.run_identity,
        "source_snapshot_as_of": source_snapshot.isoformat(),
        "stage_registry_digest": canonical_sha256(_STAGE_REGISTRY),
        "normal_response_semantic_digest": canonical_sha256(normal_semantics),
        "baseline_response_semantic_digest": canonical_sha256(baseline_semantics),
        "traced_response_semantic_digest": canonical_sha256(traced_semantics),
        "product_trace": product_trace.model_dump(mode="json"),
        "context_admission": join,
        "context_plan_trace": _context_plan_trace(traced_body),
        "mcp_join_expectation": join,
        "invariants": {
            "normal_baseline_traced_response_equal": response_equal,
            "baseline_traced_observer_semantics_equal": observer_equal,
            "baseline_traced_repository_calls_equal": repository_equal,
            "label_fields_present": False,
            "raw_evidence_text_emitted": False,
            "context_mutation_performed": False,
            "normal_resolve_may_persist_continuation_roots": True,
            "testkit_additional_mutations": False,
            "canonical_mutation": False,
            "reader_calls": 0,
            "generative_provider_calls": 0,
            "automatic_retries": 0,
        },
    }
    if isinstance(traced_observer, RuntimeOwnerTraceObserver):
        report["runtime_owner_trace"] = traced_observer.owner_trace(traced_body)
    return report


def _resolve_once(
    settings: RuntimeSettings,
    memory_request: MemoryResolveRequest,
    *,
    source_snapshot: datetime,
    observer: ProductRetrievalAuditObserver | None,
    record_repository_calls: bool,
    request_id: str,
    verify_binding: bool = False,
) -> dict[str, Any]:
    from milai.api import create_app

    app = create_app(
        settings,
        retrieval_audit_observer=observer,
        record_retrieval_audit_repository_calls=record_repository_calls,
    )
    runtime_database = app.extensions["milai.database"]
    steward_database = app.extensions["milai.steward_database"]
    try:
        service = cast(
            MemoryResolveService,
            app.extensions["milai.memory_resolve_service"],
        )
        execution = service.resolve(
            SessionContext(settings.tenant_id, settings.local_actor_id),
            memory_request,
            request_id,
            source_snapshot_as_of=source_snapshot,
        )
        body = deepcopy(execution.body)
        if verify_binding and isinstance(body.get("continuation"), dict):
            from milai.application.retrieval_continuation import (
                _query_digest,
                _request_digest,
                continuation_assertion,
            )
            from milai.persistence.retrieval_continuation_repository import (
                RetrievalContinuationRepository,
            )

            continuation = body["continuation"]
            state = RetrievalContinuationRepository(runtime_database).get_owned(
                SessionContext(settings.tenant_id, settings.local_actor_id),
                UUID(continuation["context_id"]),
            )
            valid = (
                state is not None
                and state.state_id == state.root_state_id
                and state.predecessor_state_id is None
                and state.generation == 0
                and state.query_digest == _query_digest(memory_request.query)
                and state.request_digest == _request_digest(
                    memory_request, semantics_version=state.payload_semantics_version
                )
                and state.snapshot_as_of == source_snapshot
                and continuation == continuation_assertion(state)
                and list(state.selected_evidence_ids)
                    == body.get("memory_context", {}).get("selected_evidence_ids")
            )
            if not valid:
                raise RuntimeError("TRACING_IDENTITY_BINDING_INVALID persisted_root")
            body["_testkit_root_binding"] = {
                "verified": True,
                "context_id_sha256": canonical_sha256(continuation["context_id"]),
                "query_sha256": _query_digest(memory_request.query),
                "request_scope_sha256": _request_digest(memory_request),
                "snapshot_as_of": source_snapshot.isoformat(),
            }
        return body
    finally:
        runtime_database.close()
        steward_database.close()


def _response_semantics(body: Mapping[str, Any]) -> dict[str, Any]:
    items = body.get("items")
    item_rows = items if isinstance(items, list) else []
    context = body.get("memory_context")
    context_map = context if isinstance(context, Mapping) else {}
    windows = context_map.get("windows")
    window_rows = windows if isinstance(windows, list) else []
    compile_trace = context_map.get("compile_trace")
    trace_map = compile_trace if isinstance(compile_trace, Mapping) else {}
    return {
        "status": body.get("status"),
        "availability": body.get("availability"),
        "abstention_reason": body.get("abstention_reason"),
        "fallback_used": body.get("fallback_used"),
        "fallback_reason": body.get("fallback_reason"),
        "continuation": deepcopy(body.get("continuation")),
        "evidence_refs": _strings(body.get("evidence_refs")),
        "accepted_binding_evidence_refs": _strings(
            body.get("accepted_binding_evidence_refs")
        ),
        "items": [
            {
                key: item.get(key)
                for key in ("kind", "evidence_id", "source_ref", "content_hash")
                if item.get(key) is not None
            }
            for item in item_rows
            if isinstance(item, Mapping)
        ],
        "memory_context": {
            "selected_evidence_ids": _strings(context_map.get("selected_evidence_ids")),
            "selected_source_turn_refs": _strings(
                context_map.get("selected_source_turn_refs")
            ),
            "reader_context_digest": context_map.get("reader_context_digest"),
            "estimated_tokens": context_map.get("estimated_tokens"),
            "windows": [_window_semantics(window) for window in window_rows],
            "compile_trace": {
                key: deepcopy(trace_map.get(key))
                for key in (
                    "reader_evidence_boundary",
                    "selected_unit_ids",
                    "selected_conditional_unit_ids",
                    "omitted_unit_reasons",
                    "evidence_set_digest",
                    "canonical_mutation",
                )
            },
        },
    }


def _response_semantics_v2(body: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize only a verified initial root; preserve all other response semantics."""
    result = _response_semantics(body)
    result.update({key: deepcopy(body.get(key)) for key in (
        "continuation_reason", "context_receipt_issue_reason", "degraded_components",
        "receipt_reused",
    )})
    continuation = result["continuation"]
    receipt = body.get("context_receipt")
    if isinstance(continuation, dict):
        binding = body.get("_testkit_root_binding")
        context_id = continuation.get("context_id")
        if not (
            isinstance(receipt, dict)
            and receipt.get("context_id") == context_id
            and continuation.get("root_context_id") == context_id
            and continuation.get("generation") == 0
            and isinstance(binding, dict) and binding.get("verified") is True
            and binding.get("context_id_sha256") == canonical_sha256(context_id)
        ):
            raise RuntimeError("TRACING_IDENTITY_BINDING_INVALID receipt_root")
        continuation["context_id"] = "VERIFIED_INITIAL_ROOT"
        continuation["root_context_id"] = "VERIFIED_INITIAL_ROOT"
        result["root_binding"] = {
            key: deepcopy(value) for key, value in binding.items()
            if key != "context_id_sha256"
        }
    if isinstance(receipt, dict) and receipt.get("schema_version") == "context-receipt-v0.2":
        result["receipt_semantics"] = {
            key: deepcopy(value) for key, value in receipt.items()
            if key not in {"context_id", "issued_at"}
        }
    else:
        result["receipt_semantics"] = deepcopy(receipt)
    return result


def _response_field_diff(left: Any, right: Any, *, limit: int = 32) -> dict[str, Any]:
    """Bounded JSON-pointer diagnostics: identities and text are hashes, never values."""
    if not 1 <= limit <= 32:
        raise ValueError("response diff limit must be between 1 and 32")
    entries: list[dict[str, Any]] = []
    truncated = False
    missing = object()

    def summary(value: Any) -> dict[str, Any]:
        if value is missing:
            return {"type": "missing", "cardinality": None, "sha256": None}
        return {
            "type": type(value).__name__,
            "cardinality": len(value) if isinstance(value, (dict, list, str)) else None,
            "sha256": canonical_sha256(value),
        }

    def visit(a: Any, b: Any, path: str) -> None:
        nonlocal truncated
        if type(a) is type(b) and a == b:
            return
        if len(entries) >= limit:
            truncated = True
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                # Semantic keys may include identities; do not disclose dynamic keys.
                safe_key = key if key.isidentifier() and len(key) <= 64 else (
                    "key-sha256-" + canonical_sha256(key)
                )
                visit(a.get(key, missing), b.get(key, missing), path + "/" + safe_key)
                if truncated:
                    break
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for index, (av, bv) in enumerate(zip(a, b, strict=True)):
                visit(av, bv, f"{path}/{index}")
                if truncated:
                    break
        else:
            entries.append({"path": path or "/", "left": summary(a), "right": summary(b)})

    visit(left, right, "")
    return {"entries": entries, "limit": limit, "truncated": truncated}


def _repository_call_diff(
    baseline: Sequence[Any],
    traced: Sequence[Any],
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for index in range(max(len(baseline), len(traced))):
        left = baseline[index] if index < len(baseline) else None
        right = traced[index] if index < len(traced) else None
        if left is None or right is None:
            values.append(
                {
                    "ordinal": index + 1,
                    "baseline_method": getattr(left, "method", None),
                    "traced_method": getattr(right, "method", None),
                    "changed_components": ["CALL_CARDINALITY"],
                }
            )
            continue
        changed = sorted(
            key
            for key in set(left.input_component_digests).union(
                right.input_component_digests
            )
            if left.input_component_digests.get(key)
            != right.input_component_digests.get(key)
        )
        if (
            left.method != right.method
            or left.input_digest != right.input_digest
            or left.output_digest != right.output_digest
        ):
            values.append(
                {
                    "ordinal": index + 1,
                    "baseline_method": left.method,
                    "traced_method": right.method,
                    "changed_components": changed,
                    "output_digest_equal": left.output_digest == right.output_digest,
                }
            )
    return values


def _mcp_join_expectation(body: Mapping[str, Any]) -> dict[str, Any]:
    context = body.get("memory_context")
    context_map = context if isinstance(context, Mapping) else {}
    windows = context_map.get("windows")
    window_rows = windows if isinstance(windows, list) else []
    return {
        "selected_evidence_ids": _strings(context_map.get("selected_evidence_ids")),
        "selected_source_turn_refs": _strings(
            context_map.get("selected_source_turn_refs")
        ),
        "reader_context_digest": context_map.get("reader_context_digest"),
        "windows": [_window_semantics(window) for window in window_rows],
    }


def _context_plan_trace(body: Mapping[str, Any]) -> dict[str, Any]:
    """Publish the label-free Context admission/omission identity surface."""

    context = body.get("memory_context")
    context_map = context if isinstance(context, Mapping) else {}
    raw_trace = context_map.get("compile_trace")
    trace = raw_trace if isinstance(raw_trace, Mapping) else {}
    raw_plan_omitted = trace.get("plan_omitted_units")
    plan_omitted = raw_plan_omitted if isinstance(raw_plan_omitted, list) else []
    raw_windows = trace.get("candidate_window_trace")
    windows = raw_windows if isinstance(raw_windows, list) else []
    raw_budget_envelope = trace.get("budget_envelope")
    budget_envelope = (
        deepcopy(raw_budget_envelope)
        if isinstance(raw_budget_envelope, Mapping)
        else {}
    )
    raw_omitted_reasons = trace.get("omitted_unit_reasons")
    omitted_reasons = (
        deepcopy(raw_omitted_reasons)
        if isinstance(raw_omitted_reasons, Mapping)
        else {}
    )
    raw_activation_thresholds = trace.get("conditional_activation_thresholds")
    activation_thresholds = (
        deepcopy(raw_activation_thresholds)
        if isinstance(raw_activation_thresholds, Mapping)
        else {}
    )
    scalar_keys = (
        "reader_evidence_plan_digest",
        "stable_order_version",
        "reader_evidence_boundary",
        "reader_readiness",
        "protected_unit_count",
        "conditional_unit_count",
        "protected_closure_tokens",
        "semantic_saturated",
        "atomic_unit_truncation_count",
        "long_turn_split_count",
        "rank_first_prefix_violation_count",
        "whole_unit_admission",
        "candidate_evidence_views",
        "baseline_candidate_evidence_views",
        "derived_operand_source_recoveries",
        "multi_session_requirement",
        "query_preserving_union_enabled",
        "evidence_set_selection_enabled",
        "instance_preserving_admission_enabled",
        "required_evidence_packing_loss_count",
        "required_source_turn_packing_loss_count",
        "canonical_mutation",
    )
    return {
        "schema_version": "milai-context-admission-trace-v0.1",
        **{key: deepcopy(trace.get(key)) for key in scalar_keys},
        "budget_envelope": budget_envelope,
        "selected_unit_ids": _strings(trace.get("selected_unit_ids")),
        "conditional_unit_order": _strings(trace.get("conditional_unit_order")),
        "selected_conditional_unit_ids": _strings(
            trace.get("selected_conditional_unit_ids")
        ),
        "omitted_unit_reasons": omitted_reasons,
        "conditional_activation_thresholds": activation_thresholds,
        "plan_omitted_units": [
            {
                "unit_id": item.get("unit_id"),
                "reason": item.get("reason"),
            }
            for item in plan_omitted
            if isinstance(item, Mapping)
        ],
        "candidate_window_trace": [
            {
                key: deepcopy(item.get(key))
                for key in (
                    "window_id",
                    "evidence_ids",
                    "source_turn_refs",
                    "session_id",
                    "source_rank",
                    "query_overlap",
                    "answer_signal",
                    "requirement_priority",
                    "estimated_tokens",
                )
            }
            for item in windows
            if isinstance(item, Mapping)
        ],
        "recall_workspace_trace": deepcopy(trace.get("recall_workspace_trace")),
    }


def _window_semantics(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"invalid": True}
    text = value.get("text")
    return {
        "window_id": value.get("window_id"),
        "evidence_ids": _strings(value.get("evidence_ids")),
        "source_turn_refs": _strings(value.get("source_turn_refs")),
        "session_id": value.get("session_id"),
        "observed_at": value.get("observed_at"),
        "text_sha256": (
            hashlib.sha256(text.encode()).hexdigest() if isinstance(text, str) else None
        ),
    }


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


__all__ = ["RetrievalTraceTestkitRequest", "run_live_retrieval_trace"]
