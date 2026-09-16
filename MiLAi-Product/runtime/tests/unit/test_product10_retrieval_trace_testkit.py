from __future__ import annotations

import pytest
from pydantic import ValidationError

from milai.domain.retrieval_audit import canonical_sha256
from milai.testkit.retrieval_trace import (
    RetrievalTraceTestkitRequest,
    _context_plan_trace,
    _response_field_diff,
    _response_semantics,
    _response_semantics_v2,
)


def _root_body(identity: str) -> dict:
    body = _body("request", "trace")
    body["continuation"] = {
        "context_id": identity, "root_context_id": identity, "generation": 0,
        "available": True, "reason": "UNEXPANDED_FRONTIER", "persisted_frontier_count": 4,
        "attempted_frontier_count": 0, "online_ineligible_count": 0,
        "operation_replayed": False,
    }
    body["context_receipt"] = {"schema_version": "context-receipt-v0.2",
                               "context_id": identity, "issued_at": identity,
                               "source_evidence_ids": ["evidence-1"]}
    body["_testkit_root_binding"] = {"verified": True,
                                    "context_id_sha256": canonical_sha256(identity),
                                    "query_sha256": "query", "request_scope_sha256": "scope"}
    return body


def test_v2_only_normalizes_verified_initial_identity_and_keeps_legacy() -> None:
    first, second = _root_body("root-a"), _root_body("root-b")
    assert _response_semantics(first) != _response_semantics(second)
    assert _response_semantics_v2(first) == _response_semantics_v2(second)


@pytest.mark.parametrize("field,value", [
    ("available", False), ("reason", "PERSISTED_FRONTIER_EXHAUSTED"),
    ("persisted_frontier_count", 3), ("attempted_frontier_count", 1),
    ("online_ineligible_count", 1), ("operation_replayed", True),
])
def test_v2_keeps_continuation_capability_changes(field: str, value: object) -> None:
    body = _root_body("root-b")
    body["continuation"][field] = value
    first, second = _response_semantics_v2(_root_body("root-a")), _response_semantics_v2(body)
    assert first != second
    assert _response_field_diff(first, second)["entries"][0]["path"] == "/continuation/" + field


@pytest.mark.parametrize("change", ["root", "receipt", "generation", "proof"])
def test_v2_rejects_invalid_identity_relationships(change: str) -> None:
    body = _root_body("root")
    if change == "root":
        body["continuation"]["root_context_id"] = "other"
    elif change == "receipt":
        body["context_receipt"]["context_id"] = "other"
    elif change == "generation":
        body["continuation"]["generation"] = 1
    else:
        body["_testkit_root_binding"]["verified"] = False
    with pytest.raises(RuntimeError, match="TRACING_IDENTITY_BINDING_INVALID"):
        _response_semantics_v2(body)


@pytest.mark.parametrize("change", ["evidence", "order", "body", "degraded", "scope"])
def test_v2_preserves_material_negative_controls(change: str) -> None:
    first, second = _root_body("root-a"), _root_body("root-b")
    for body in (first, second):
        body["evidence_refs"] = ["evidence-1", "evidence-2"]
    if change == "evidence":
        second["evidence_refs"][0] = "evidence-3"
    elif change == "order":
        second["evidence_refs"].reverse()
    elif change == "body":
        second["items"][0]["content_hash"] = "changed"
    elif change == "degraded":
        second["degraded_components"] = ["retrieval_continuation"]
    else:
        second["_testkit_root_binding"]["request_scope_sha256"] = "other"
    assert _response_semantics_v2(first) != _response_semantics_v2(second)


def test_response_diff_is_bounded_and_does_not_emit_values() -> None:
    left = {"continuation": {"context_id": "secret-left"}, "rows": list(range(40))}
    right = {"continuation": {"context_id": "secret-right"}, "rows": list(range(1, 41))}
    diff = _response_field_diff(left, right)
    assert len(diff["entries"]) == 32
    assert diff["truncated"] is True
    assert diff["entries"][0]["path"] == "/continuation/context_id"
    assert "secret-left" not in str(diff)
    assert "secret-right" not in str(diff)


def test_response_diff_distinguishes_missing_null_type_and_cardinality() -> None:
    diff = _response_field_diff({"a": None, "b": True, "c": [1]}, {"b": 1, "c": []})
    assert [item["path"] for item in diff["entries"]] == ["/a", "/b", "/c"]
    assert diff["entries"][0]["right"]["type"] == "missing"
    assert diff["entries"][2]["left"]["cardinality"] == 1
    assert diff["truncated"] is False


def test_response_semantics_excludes_run_local_ids_and_preserves_host_identity() -> None:
    first = _response_semantics(_body("request-a", "trace-a"))
    second = _response_semantics(_body("request-b", "trace-b"))

    assert first == second
    assert first["memory_context"]["selected_evidence_ids"] == ["evidence-1"]
    assert first["memory_context"]["selected_source_turn_refs"] == ["turn-1"]


def test_response_semantics_detects_context_identity_drift() -> None:
    first = _response_semantics(_body("request-a", "trace-a"))
    changed = _body("request-b", "trace-b")
    changed["memory_context"]["selected_evidence_ids"] = ["evidence-2"]

    assert first != _response_semantics(changed)


def test_trace_request_keeps_query_reference_time_separate_from_source_snapshot() -> None:
    request = RetrievalTraceTestkitRequest.model_validate(
        {
            "schema_version": "milai-retrieval-trace-testkit-request-v0.1",
            "run_identity": "run-1",
            "source_snapshot_as_of": "2026-09-03T14:00:00Z",
            "memory_request": {
                "query": "What happened in January?",
                "reference_time": "2026-02-01T00:00:00Z",
            },
        }
    )

    assert request.source_snapshot_as_of != request.memory_request.reference_time


def test_trace_request_rejects_naive_source_snapshot() -> None:
    with pytest.raises(ValidationError):
        RetrievalTraceTestkitRequest.model_validate(
            {
                "schema_version": "milai-retrieval-trace-testkit-request-v0.1",
                "run_identity": "run-1",
                "source_snapshot_as_of": "2026-09-03T14:00:00",
                "memory_request": {"query": "historical query"},
            }
        )


def test_context_plan_trace_publishes_identities_and_omission_without_text() -> None:
    body = _body("request-a", "trace-a")
    compile_trace = body["memory_context"]["compile_trace"]  # type: ignore[index]
    compile_trace.update(  # type: ignore[union-attr]
        {
            "reader_evidence_plan_digest": "c" * 64,
            "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
            "selected_unit_ids": ["evidence:window-1"],
            "selected_conditional_unit_ids": ["evidence:window-1"],
            "omitted_unit_reasons": {
                "evidence:window-2": "AVAILABLE_MEMORY_BELOW_UNIT_ACTIVATION_THRESHOLD"
            },
            "plan_omitted_units": [
                {
                    "unit_id": "evidence:window-3",
                    "reason": "NO_ADMISSIBLE_SEMANTIC_GAIN",
                    "text": "must not escape",
                }
            ],
            "candidate_window_trace": [
                {
                    "window_id": "window-2",
                    "evidence_ids": ["evidence-2"],
                    "source_turn_refs": ["turn-2"],
                    "session_id": "session-2",
                    "source_rank": 2,
                    "query_overlap": 1,
                    "answer_signal": False,
                    "requirement_priority": False,
                    "estimated_tokens": 12,
                    "text": "must not escape",
                }
            ],
        }
    )

    trace = _context_plan_trace(body)

    assert trace["selected_unit_ids"] == ["evidence:window-1"]
    assert trace["candidate_window_trace"][0]["evidence_ids"] == ["evidence-2"]
    assert trace["plan_omitted_units"][0]["reason"] == "NO_ADMISSIBLE_SEMANTIC_GAIN"
    assert "must not escape" not in str(trace)


def test_context_plan_trace_normalizes_missing_mapping_fields() -> None:
    trace = _context_plan_trace(_body("request-a", "trace-a"))

    assert trace["budget_envelope"] == {}
    assert trace["omitted_unit_reasons"] == {}
    assert trace["conditional_activation_thresholds"] == {}


def _body(request_id: str, trace_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "trace_id": trace_id,
        "status": "PARTIAL",
        "availability": "DEGRADED",
        "fallback_used": False,
        "evidence_refs": ["evidence-1"],
        "accepted_binding_evidence_refs": [],
        "items": [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "evidence-1",
                "source_ref": "turn-1",
                "content_hash": "a" * 64,
                "content": "not emitted in trace semantics",
            }
        ],
        "memory_context": {
            "selected_evidence_ids": ["evidence-1"],
            "selected_source_turn_refs": ["turn-1"],
            "reader_context_digest": "b" * 64,
            "estimated_tokens": 4,
            "windows": [
                {
                    "window_id": "window-1",
                    "evidence_ids": ["evidence-1"],
                    "source_turn_refs": ["turn-1"],
                    "text": "visible evidence",
                }
            ],
            "compile_trace": {
                "selected_unit_ids": ["unit-1"],
                "canonical_mutation": False,
            },
        },
    }
