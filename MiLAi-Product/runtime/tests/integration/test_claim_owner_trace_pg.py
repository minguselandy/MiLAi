from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from test_retrieval_api import (
    SCOPE,
    _create_claim,
    _headers,
    _supersede,
    retrieval_runtime,  # noqa: F401
)

from milai.api import create_app
from milai.application import state_address
from milai.domain.retrieval_audit import canonical_sha256
from milai.observability.retrieval_audit import ProductRetrievalAuditObserver
from milai.testkit.observed_runtime import ObservedRuntime
from milai.testkit.runtime_owner_trace import RuntimeOwnerTraceObserver

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("visible", [True, False])
def test_claim_owner_observes_exact_governed_version_without_changing_execution(
    retrieval_runtime: Any, visible: bool, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    settings, app, _ = retrieval_runtime
    token = "claimowner" + uuid4().hex
    claim = _create_claim(app.test_client(), token)
    instant = datetime.now(UTC)

    class ReadTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return instant

    # Hold the read's effective time constant, without changing CURRENT into HISTORY.
    monkeypatch.setattr(state_address, "datetime", ReadTime)
    payload = {
        "query": "Read the exact current receipt state",
        "claim_ids": [claim["claim_id"]],
        "requested_scope": SCOPE if visible else {"project_ids": ["other"]},
        "required_authority": "ACTION_SAFE",
    }
    responses: list[dict[str, Any]] = []
    baseline = ProductRetrievalAuditObserver(enabled=False)
    traced = RuntimeOwnerTraceObserver()
    for observer in (None, baseline, traced):
        observed_app = create_app(
            settings, database=app.extensions["milai.database"],
            steward_database=app.extensions["milai.steward_database"],
            retrieval_audit_observer=observer,
            record_retrieval_audit_repository_calls=observer is not None,
        )
        response = observed_app.test_client().post(
            "/v1/memory/resolve", headers=_headers(), json=payload,
        )
        assert response.status_code == 200
        responses.append(response.json)
    # Compare reader/governance semantics; trace/capsule IDs and timings are per-read.
    fields = ("status", "availability", "items", "open_issue_ids", "evidence_refs",
              "abstention_reason", "resolution", "canonical_position", "memory_context")
    for body in responses[1:]:
        for key in fields:
            assert body.get(key) == responses[0].get(key), key
    assert baseline.semantic_digest == traced.semantic_digest
    assert baseline.repository_semantic_digest() == traced.repository_semantic_digest()
    facts = traced.owner_trace(responses[-1])
    assert facts["status"] == "COMPLETE", facts
    assert facts["selected_versions"] == []  # Supporting IDs are not Evidence bodies.
    assert facts["materialized_evidence_versions"] == []
    if visible:
        assert facts["selected_claim_versions"] == facts["materialized_claim_versions"]
        version = facts["selected_claim_versions"][0]
        assert version["memory_ref"] == "claim:" + canonical_sha256(claim["claim_id"])
        assert version["version_id"] == "claim-version:" + canonical_sha256(
            claim["claim_version_id"]
        )
        assert len(version["content_sha256"]) == 64
        assert facts["selected_claim_version_refs"] == [version["version_id"]]
        assert facts["selected_support_evidence_refs"] == [
            "evidence:" + canonical_sha256(claim["evidence_id"])
        ]
        assert responses[-1]["context_receipt"]["context_capsule_id"]
    else:
        assert facts["selected_claim_versions"] == []
        assert facts["selected_support_evidence_refs"] == []
    assert token not in json.dumps(facts)
    assert claim["claim_id"] not in json.dumps(facts)


@pytest.mark.parametrize("change", ["none", "scope", "canonical"])
def test_http_cache_owner_links_current_validation_to_original_claim_execution(
    retrieval_runtime: Any, change: str,  # noqa: F811
) -> None:
    settings, app, _ = retrieval_runtime
    client = app.test_client()
    claim = _create_claim(client, "cacheowner" + uuid4().hex)
    payload = {
        "query": "Read the exact current receipt state",
        "claim_ids": [claim["claim_id"]], "requested_scope": SCOPE,
        "required_authority": "ACTION_SAFE",
    }

    def resolve(runtime: ObservedRuntime, data: dict[str, Any]) -> Any:
        request = Request(  # noqa: S310 — harness owns the fixed http://127.0.0.1 endpoint
            runtime.base_url + "/v1/memory/resolve", data=json.dumps(data).encode(),
            headers={**_headers(), "Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=5) as response:  # noqa: S310
            return json.load(response)

    config = settings.model_dump()
    config["environment"] = "test"
    with ObservedRuntime(config) as runtime:
        first = resolve(runtime, payload)
        capsule_id = first["context_receipt"]["context_capsule_id"]
        followup = {**payload, "previous_context_id": capsule_id}
        if change == "scope":
            followup["requested_scope"] = {"project_ids": ["other"]}
        elif change == "canonical":
            _supersede(client, claim, "replacement" + uuid4().hex)
        second = resolve(runtime, followup)
        original, current = runtime.owner_traces()
    assert original["owner_trace"]["status"] == "COMPLETE"
    assert original["reader_gate"] == "ADMITTED"
    assert original["selected_claim_version_refs"] == [
        "claim-version:" + canonical_sha256(claim["claim_version_id"])
    ]
    assert original["reuse_validation"] is None
    assert original["request_ref"] != current["request_ref"]
    assert current["observation_gap"] is None
    assert original["context_capsule_ref"] == "context-capsule:" + canonical_sha256(capsule_id)
    if change == "none":
        assert second["receipt_reused"] is True
        assert current["owner_trace"] is None  # No invented fresh DecisionSnapshot.
        assert current["retrieval_trace_ref"] == original["retrieval_trace_ref"]
        assert current["reader_context_sha256"] == original["reader_context_sha256"]
        assert current["selected_claim_version_refs"] == original["selected_claim_version_refs"]
        validation = current["reuse_validation"]
        assert validation["runtime_request_ref"] == current["request_ref"]
        assert validation["context_capsule_ref"] == original["context_capsule_ref"]
        assert validation["origin_retrieval_trace_ref"] == original["retrieval_trace_ref"]
        assert validation["validation_canonical_position"] == second["access_trace"][
            "canonical_position"]
        assert validation["dependency_digest"] == first["context_receipt"]["dependency_digest"]
        assert current["reader_gate"] == "ADMITTED"
    else:
        assert second["receipt_reused"] is False
        assert current["reuse_validation"] is None
        assert current["retrieval_trace_ref"] != original["retrieval_trace_ref"]
        assert current["owner_trace"]["status"] == "COMPLETE"
        assert current["selected_claim_version_refs"] != original["selected_claim_version_refs"]
        if change == "scope":
            assert current["reader_gate"] == "ABSTAIN"
            assert current["selected_claim_version_refs"] == []
        else:
            assert current["reader_gate"] == "ADMITTED"
            assert current["owner_trace"]["selected_claim_versions"][0]["content_sha256"] != (
                original["owner_trace"]["selected_claim_versions"][0]["content_sha256"]
            )
