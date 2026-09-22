from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_retrieval_continuation_state import continuation_app  # noqa: F401

from milai.adapters import DeterministicHashEmbedding, LocalContentAddressedBlobStore
from milai.domain.retrieval_audit import canonical_sha256
from milai.persistence import SessionContext
from milai.persistence.projection_repository import ProjectionRepository
from milai.testkit.retrieval_trace import RetrievalTraceTestkitRequest, run_live_retrieval_trace
from milai.workers.main import FoundationWorker

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("with_evidence,read_scope", [
    (False, "owner-trace"), (True, "owner-trace"), (True, "other-scope"),
])
def test_owner_export_binds_real_postgresql_execution_without_changing_retrieval(
    continuation_app, with_evidence: bool, read_scope: str,  # type: ignore[no-untyped-def] # noqa: F811
) -> None:
    settings, app, worker_database = continuation_app
    content = "Purchase marker: synthetic ceramic cups await pickup."
    if with_evidence:
        worker = FoundationWorker(
            settings, worker_database, repository=ProjectionRepository(worker_database),
            blob_store=LocalContentAddressedBlobStore(settings.blob_root),
            embedding=DeterministicHashEmbedding(), worker_id=f"owner-trace-{uuid4()}",
        )
        response = app.test_client().post(
            "/v1/evidence",
            headers={"Authorization": "Bearer test-token-with-at-least-32-characters",
                     "Idempotency-Key": str(uuid4())},
            json={
                "source_type": "RUNTIME_OBSERVATION", "source_ref": "owner-trace://synthetic-1",
                "subject_id": "owner-trace", "speaker": "user",
                "observed_at": "2026-01-01T10:00:00Z", "content": content,
                "media_type": "text/plain", "retention_state": "READABLE",
                "permission_snapshot": {"readable": True, "project_ids": ["owner-trace"]},
            },
        )
        assert response.status_code == 201
        assert worker.run_once() > 0
    run_id = "owner-export-" + uuid4().hex
    request = RetrievalTraceTestkitRequest.model_validate({
        "schema_version": "milai-retrieval-trace-testkit-request-v0.1",
        "comparison_semantics_version": "v0.2", "run_identity": run_id,
        "source_snapshot_as_of": datetime.now(UTC).isoformat(),
        "memory_request": {"query": "Recall purchase marker cups awaiting pickup",
                           "requested_scope": {"project_ids": [read_scope]}},
    })
    report = run_live_retrieval_trace(request, settings=settings, include_owner_trace=True)
    facts = report["runtime_owner_trace"]
    assert report["invariants"]["normal_baseline_traced_response_equal"]
    assert report["invariants"]["baseline_traced_observer_semantics_equal"]
    assert report["invariants"]["baseline_traced_repository_calls_equal"]
    assert report["invariants"]["generative_provider_calls"] == 0
    database = app.extensions["milai.database"]
    with database.connection(
        SessionContext(settings.tenant_id, settings.local_actor_id), read_only=True,
    ) as connection:
        row = connection.execute(
            "SELECT trace_id, canonical_snapshot_outbox_sequence FROM milai.retrieval_trace "
            "WHERE tenant_id = %s AND request_id = %s",
            (settings.tenant_id, run_id + ":traced"),
        ).fetchone()
    assert row is not None
    assert facts["retrieval_trace_ref"] == "retrieval:" + canonical_sha256(str(row[0]))
    assert facts["canonical_position"] == row[1]
    assert len(facts["decision_snapshot_digest"]) == 64
    assert facts["status"] == "COMPLETE"
    if with_evidence and read_scope == "owner-trace":
        assert len(facts["selected_versions"]) == 1
        assert facts["selected_versions"][0]["content_sha256"] == hashlib.sha256(
            content.encode()
        ).hexdigest()
    else:
        assert facts["materialized_evidence_versions"] == []
        assert facts["selected_versions"] == []
    assert content not in json.dumps(facts)
    assert "owner-trace://synthetic-1" not in json.dumps(facts)
