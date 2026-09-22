from __future__ import annotations

import hashlib
from typing import Any

import pytest
from flask import Flask, g

from milai.testkit import observed_runtime


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
        str(error) if str(error) == "OWNER_TRACE_EXECUTION_NOT_OBSERVED"
        else "OWNER_TRACE_EXPORT_FAILED"
    )
    assert report["reader_context_sha256"] == hashlib.sha256(b"private content").hexdigest()
    assert "private" not in str(report) and "raw-id" not in str(report)
    report["selected_evidence_refs"].clear()
    assert len(harness.owner_traces()[0]["selected_evidence_refs"]) == 1
