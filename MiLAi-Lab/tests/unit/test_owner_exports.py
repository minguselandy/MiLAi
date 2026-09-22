from __future__ import annotations

import copy
from typing import Any

import pytest

from milai_lab.analysis.owner_exports import assemble_owner_attempts


def _case() -> dict[str, Any]:
    version = {"memory_ref": "evidence:one", "version_id": "version:one",
               "content_sha256": "a" * 64}
    binding = {"mcp_invocation_id": "mcp:one", "retrieval_trace_ref": "retrieval:one",
               "reader_context_sha256": "b" * 64, "selected_evidence_refs": ["evidence:one"]}
    return {
        "route": "PROVIDER_AVAILABLE",
        "host": {"schema_version": "milai-host-owner-trace-v1",
                 "host_attempt_trace_id": "attempt:one", "task_identity_digest": "c" * 64,
                 "retry_of": None, "terminal": "RETURNED",
                 "mcp_invocations": [{"invocation_id": "mcp:one", "receipt_reused": False,
                                      "host_attempt_trace_id": "attempt:one",
                                      "retrieval_trace_ref": "retrieval:one", "status": "SUCCESS"}],
                 "provider_requests": [{
                     "request_ref": "request:one", "host_attempt_trace_id": "attempt:one",
                     "prepared_context_bindings": [copy.deepcopy(binding)],
                     "context_bindings": [binding], "exposure_status": "DISPATCHED",
                     "request_started": True, "native_request_ref": "native:one",
                     "status": "SUCCESS", "input_tokens": 5, "output_tokens": 3,
                 }]},
        "runtime": [{
            "schema_version": "milai-runtime-http-owner-v1", "receipt_reused": False,
            "observation_gap": None, "retrieval_trace_ref": "retrieval:one",
            "reader_context_sha256": "b" * 64, "selected_evidence_refs": ["evidence:one"],
            "reader_gate": "ADMITTED", "owner_trace": {
                "schema_version": "milai-runtime-owner-trace-v1", "status": "COMPLETE",
                "trace_gaps": [], "retrieval_trace_ref": "retrieval:one",
                "selected_evidence_refs": ["evidence:one"], "selected_versions": [version],
                "materialized_evidence_versions": [copy.deepcopy(version)],
                "decision_snapshot_digest": "d" * 64, "evidence_set_digest": "e" * 64,
            },
        }],
    }


def _assemble(case: dict[str, Any]) -> dict[str, Any]:
    return assemble_owner_attempts([case], run_id="run:one", product_lock_digest="f" * 64,
                                   result_refs=["result:one"])[0]


def test_same_execution_join_keeps_exact_version_and_unknown_use() -> None:
    case = _case()
    original = copy.deepcopy(case)
    result = _assemble(case)
    assert result["join_status"] == "COMPLETE"
    request, = result["requests"]
    assert request["observable_use"] == "UNKNOWN"
    assert request["exposed_versions"] == case["runtime"][0]["owner_trace"]["selected_versions"]
    assert request["causal_attribution"] == "NOT_ESTABLISHED"
    assert case == original


@pytest.mark.parametrize("dispatch,started,reason", [
    ("NOT_STARTED", False, "NOT_ACCEPTED"),
    ("DISPATCHED", True, "RESPONSE_LOST"),
    ("UNKNOWN", None, "NOT_OBSERVED"),
])
def test_failed_transport_retains_dispatch_and_unknown_usage(
    dispatch: str, started: bool | None, reason: str,
) -> None:
    case = _case()
    case["host"]["terminal"] = "FAILURE"
    request = case["host"]["provider_requests"][0]
    request.update(exposure_status=dispatch, request_started=started, native_request_ref=None,
                   status="UNKNOWN" if started is None else "FAILURE",
                   input_tokens=None, output_tokens=None)
    if started is not True:
        request["context_bindings"] = []
    result = _assemble(case)
    joined, = result["requests"]
    assert joined["exposure_status"] == dispatch
    assert joined["native_id_missing_reason"] == reason
    assert joined["unknown_usage"]
    assert len(joined["exposed_versions"]) == (1 if started is True else 0)
    if started is None:
        assert {"request_id": "request:one", "reason": "EXPOSURE_UNKNOWN"} in result["trace_gaps"]


@pytest.mark.parametrize("change,reason", [
    ("context", "CONTEXT_NOT_BOUND_TO_RUNTIME_AND_MCP"),
    ("selection", "RUNTIME_SELECTION_VERSION_MISMATCH"),
    ("cache", "CACHE_ORIGIN_JOIN_NOT_YET_SUPPORTED"),
    ("missing-version", "INCOMPLETE_RUNTIME_OWNER_EXPORT"),
    ("gate", "RUNTIME_READER_GATE_UNKNOWN"),
    ("false-exposure", "EXPOSURE_WITHOUT_KNOWN_DISPATCH"),
])
def test_missing_or_mismatched_owner_facts_cannot_be_reconstructed(
    change: str, reason: str,
) -> None:
    case = _case()
    row = case["runtime"][0]
    if change == "context":
        row["reader_context_sha256"] = "9" * 64
    elif change == "selection":
        row["selected_evidence_refs"] = []
    elif change == "cache":
        row["receipt_reused"] = True
    elif change == "missing-version":
        row["owner_trace"]["status"] = "PARTIAL"
    elif change == "gate":
        row["reader_gate"] = "UNKNOWN"
    else:
        case["host"]["provider_requests"][0]["exposure_status"] = "NOT_STARTED"
    with pytest.raises(ValueError, match=reason):
        _assemble(case)
