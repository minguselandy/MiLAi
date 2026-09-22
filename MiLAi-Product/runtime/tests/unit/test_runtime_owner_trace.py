from __future__ import annotations

import copy
import hashlib
import json
import sys
from io import StringIO
from typing import Any
from uuid import UUID

import pytest
from test_dg17_sufficiency import _access_plan, _count, _EvidenceRepository, _request

from milai.application.retrieval import RetrievalService
from milai.domain.retrieval_audit import canonical_sha256
from milai.observability.retrieval_audit import AuditRecordingRepository
from milai.persistence import SessionContext
from milai.testkit.runtime_owner_trace import RuntimeOwnerTraceObserver


def _execute(
    *, missing_hash: bool = False,
) -> tuple[RuntimeOwnerTraceObserver, Any, dict[str, Any]]:
    item = _count()
    if not missing_hash:
        item["content_hash"] = hashlib.sha256(item["content"].encode()).hexdigest()
    observer = RuntimeOwnerTraceObserver()
    repository = AuditRecordingRepository(_EvidenceRepository([item]), observer)
    execution = RetrievalService(
        repository, retrieval_audit_observer=observer,  # type: ignore[arg-type]
    ).retrieve(
        SessionContext(UUID(int=1), UUID(int=2)), _request(), "owner-observation",
        access_plan=_access_plan(),
    )
    response = {"trace_id": str(UUID(int=17)),
                "memory_context": {"selected_evidence_ids": [item["evidence_id"]]}}
    return observer, execution, response


def test_runtime_exports_actual_snapshot_and_exact_owner_hash_without_body() -> None:
    observer, execution, response = _execute()
    report = observer.owner_trace(response)
    assert report["status"] == "COMPLETE"
    assert report["decision_snapshot_digest"] == execution.decision_snapshot.snapshot_digest
    assert report["gate_digest"] == execution.decision_snapshot.gate_digest
    assert report["binding_digest"] == execution.decision_snapshot.binding_digest
    assert report["evidence_set_digest"] == canonical_sha256(
        list(execution.decision_snapshot.accepted_evidence_ids)
    )
    assert report["retrieval_trace_ref"] == "retrieval:" + canonical_sha256(str(UUID(int=17)))
    assert report["canonical_position"] == 0
    assert report["selected_versions"] == report["materialized_evidence_versions"]
    assert report["selected_versions"][0]["content_sha256"] == hashlib.sha256(
        _count()["content"].encode()
    ).hexdigest()
    wire = json.dumps(report)
    assert _count()["content"] not in wire
    assert _count()["evidence_id"] not in wire
    assert "fixture-user" not in wire
    original = copy.deepcopy(report)
    report["selected_versions"].clear()
    assert observer.owner_trace(response) == original


def test_missing_content_hash_is_not_replaced_by_text_or_identity_hash() -> None:
    observer, _, response = _execute(missing_hash=True)
    report = observer.owner_trace(response)
    assert report["status"] == "PARTIAL"
    assert report["materialized_evidence_versions"] == []
    assert report["selected_versions"] == []
    assert {row["reason"] for row in report["trace_gaps"]} == {
        "EXACT_CONTENT_HASH_NOT_OBSERVED", "SELECTED_EXACT_VERSION_NOT_OBSERVED",
    }


def test_unobserved_or_wrong_execution_cannot_emit_owner_identity() -> None:
    with pytest.raises(RuntimeError, match="OWNER_TRACE_EXECUTION_NOT_OBSERVED"):
        RuntimeOwnerTraceObserver().owner_trace({})
    observer, _, response = _execute()
    response["trace_id"] = str(UUID(int=18))
    with pytest.raises(RuntimeError, match="OWNER_TRACE_RESPONSE_ID_MISMATCH"):
        observer.owner_trace(response)


def test_missing_context_is_unknown_and_not_known_empty_selection() -> None:
    observer, _, response = _execute()
    response.pop("memory_context")
    report = observer.owner_trace(response)
    assert report["status"] == "PARTIAL"
    assert {row["reason"] for row in report["trace_gaps"]} == {"CONTEXT_SELECTION_NOT_OBSERVED"}


def test_selected_unobserved_version_is_an_explicit_gap_not_acquisition() -> None:
    observer, _, response = _execute()
    response["memory_context"]["selected_evidence_ids"].append("other-evidence")
    report = observer.owner_trace(response)
    assert report["status"] == "PARTIAL"
    assert len(report["selected_evidence_refs"]) == 2
    assert len(report["selected_versions"]) == 1
    assert report["trace_gaps"][-1]["reason"] == "SELECTED_EXACT_VERSION_NOT_OBSERVED"


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_owner_export_requires_explicit_flag(
    enabled: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from milai.testkit import retrieval_trace_cli

    observed = []

    def run(request: Any, *, include_owner_trace: bool = False) -> dict[str, Any]:
        observed.append((request.run_identity, include_owner_trace))
        return {"observed": include_owner_trace}

    monkeypatch.setattr(retrieval_trace_cli, "run_live_retrieval_trace", run)
    monkeypatch.setattr(sys, "argv", ["milai-retrieval-trace-testkit"] + (
        ["--owner-trace"] if enabled else []
    ))
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps({
        "schema_version": "milai-retrieval-trace-testkit-request-v0.1",
        "run_identity": "cli-owner", "source_snapshot_as_of": "2026-09-22T00:00:00Z",
        "memory_request": {"query": "synthetic query"},
    })))
    retrieval_trace_cli.main()
    assert observed == [("cli-owner", enabled)]
    assert json.loads(capsys.readouterr().out) == {"observed": enabled}
