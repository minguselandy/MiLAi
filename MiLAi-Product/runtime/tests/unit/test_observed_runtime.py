from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest
from flask import Flask, g

from milai.domain.retrieval_audit import canonical_sha256
from milai.testkit import observed_runtime


@pytest.mark.parametrize("tamper", [None, "stage", "request", "position", "digest", "trace"])
def test_reuse_exports_current_validation_only_when_runtime_binding_is_complete(
    tamper: str | None,
) -> None:
    body: dict[str, Any] = {
        "receipt_reused": True, "trace_id": "origin-trace",
        "context_receipt": {
            "schema_version": "context-receipt-v0.1", "context_capsule_id": "capsule",
            "requirement_coverage": {"query_digest": "a" * 64},
            "dependency_digest": "b" * 64,
            "canonical_position": 1,
        },
        "access_trace": {
            "terminal_stage": "REUSE", "stop_reason": "CONTEXT_RECEIPT_VALIDATED",
            "attempted_stages": ["REUSE_VALIDATION"], "runtime_request_id": "current-request",
            "retrieval_trace_id": "origin-trace", "canonical_position": 7,
        },
    }
    if tamper == "stage":
        body["access_trace"]["terminal_stage"] = "FRESH"
    elif tamper == "request":
        body["access_trace"]["runtime_request_id"] = "other-request"
    elif tamper == "position":
        body["access_trace"]["canonical_position"] = None
    elif tamper == "digest":
        body["context_receipt"]["dependency_digest"] = "private malformed value"
    elif tamper == "trace":
        body["access_trace"]["retrieval_trace_id"] = "other-trace"
    request_ref = "runtime-request:" + canonical_sha256("current-request")
    original = copy.deepcopy(body)
    if tamper is not None:
        with pytest.raises(RuntimeError, match="OWNER_TRACE_REUSE_VALIDATION_NOT_OBSERVED"):
            observed_runtime._reuse_validation(body, request_ref)
    else:
        result = observed_runtime._reuse_validation(body, request_ref)
        assert result is not None
        assert result["validation_canonical_position"] == 7  # Not issuance position 1.
        assert result["runtime_request_ref"] == request_ref
        assert "origin-trace" not in str(result) and "current-request" not in str(result)
    assert body == original
    assert observed_runtime._reuse_validation({"receipt_reused": False}, request_ref) is None


@pytest.mark.parametrize("status,availability,issues,selected,expected", [
    ("HIT", "AVAILABLE", [], ["e1"], "ADMITTED"),
    ("PARTIAL", "DEGRADED", [], ["e1"], "ADMITTED"),
    ("ABSENT", "AVAILABLE", [], [], "ABSTAIN"),
    ("DENIED", "AVAILABLE", [], ["e1"], "BLOCKED"),
    ("HIT", "AVAILABLE", ["issue"], ["e1"], "BLOCKED"),
    ("HIT", "UNAVAILABLE", [], ["e1"], "ERROR"),
    ("OTHER", "AVAILABLE", [], ["e1"], "UNKNOWN"),
])
def test_reader_gate_is_a_fail_closed_projection_not_typed_completion(
    status: str, availability: str, issues: list[str], selected: list[str], expected: str,
) -> None:
    body = {"status": status, "availability": availability, "open_issue_ids": issues,
            "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
            "memory_context": {"selected_evidence_ids": selected}}
    assert observed_runtime._reader_gate(body, 200) == expected
    assert observed_runtime._reader_gate(body, 503) == "ERROR"


@pytest.mark.parametrize("error", [
    RuntimeError("OWNER_TRACE_EXECUTION_NOT_OBSERVED"),
    RuntimeError("OWNER_TRACE_REUSE_VALIDATION_NOT_OBSERVED"),
    RuntimeError("OWNER_TRACE_PRIVATE secret"), ValueError("private body"),
])
def test_http_observation_failure_keeps_original_response_and_redacts_error(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, error: Exception,
) -> None:
    app = Flask(__name__)
    body = {"trace_id": "synthetic-trace", "status": "PARTIAL", "open_issue_ids": [],
            "memory_context": {"text": "private content", "selected_evidence_ids": ["raw-id"]}}

    @app.before_request
    def identify() -> None:
        g.request_id = "synthetic-request"

    @app.post("/v1/memory/resolve")
    def resolve() -> tuple[dict[str, Any], int]:
        return body, 200

    def fail(self: Any, response: Any) -> None:
        raise error

    monkeypatch.setattr(observed_runtime, "create_app", lambda *a, **kw: app)
    monkeypatch.setattr(observed_runtime.RuntimeOwnerTraceObserver, "owner_trace", fail)
    harness = observed_runtime.ObservedRuntime({
        "environment": "test", "data_mode": "SYNTHETIC_ONLY",
        "database_url": "postgresql://milai_api:test@127.0.0.1/test",
        "steward_database_url": "postgresql://milai_steward:test@127.0.0.1/test",
        "blob_root": str(tmp_path / "blobs"),
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "local_actor_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "api_token": "synthetic-api-token-at-least-32-characters",
        "causal_token_secret": "synthetic-causal-secret-at-least-32-characters",
        "embedding_provider": "deterministic_hash",
    })
    response = app.test_client().post("/v1/memory/resolve", json={})
    assert response.status_code == 200 and response.json == body
    report, = harness.owner_traces()
    assert report["owner_trace"] is None
    assert report["observation_gap"] == (
        str(error) if str(error) in {"OWNER_TRACE_EXECUTION_NOT_OBSERVED",
                                  "OWNER_TRACE_REUSE_VALIDATION_NOT_OBSERVED"}
        else "OWNER_TRACE_EXPORT_FAILED"
    )
    assert report["reader_context_sha256"] == hashlib.sha256(b"private content").hexdigest()
    assert "private" not in str(report) and "raw-id" not in str(report)
    report["selected_evidence_refs"].clear()
    assert len(harness.owner_traces()[0]["selected_evidence_refs"]) == 1
