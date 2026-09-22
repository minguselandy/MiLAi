from __future__ import annotations

import copy
from typing import Any

import pytest

from milai_lab.analysis.trace_join import CACHE_SCHEMA_VERSION, join_attempts, join_trace


def _pair() -> list[dict[str, Any]]:
    version = {"memory_ref": "claim:one", "version_id": "claim-version:one",
               "content_sha256": "a" * 64}
    result = []
    for i in (1, 2):
        runtime_id, attempt = f"runtime:{i}", f"attempt:{i}"
        result.append({
            "schema_version": CACHE_SCHEMA_VERSION, "run_id": "run:one",
            "product_lock_digest": "b" * 64,
            "host": {"host_attempt_trace_id": attempt, "task_identity_digest": "c" * 64,
                     "retry_of": None, "terminal": "SUCCESS"},
            "runtime": [{
                "runtime_request_id": runtime_id, "retrieval_trace_id": "retrieval:origin",
                "execution_kind": "FRESH" if i == 1 else "CACHE_REUSE",
                "origin_runtime_request_id": None if i == 1 else "runtime:1",
                "origin_host_attempt_trace_id": None if i == 1 else "attempt:1",
                "decision_snapshot_digest": "d" * 64 if i == 1 else None,
                "evidence_set_digest": "e" * 64 if i == 1 else None,
                "missing_reason": None if i == 1 else "NO_NEW_RETRIEVAL",
                "gate": "ADMITTED", "context_capsule_ref": "capsule:one",
                "reader_context_sha256": "f" * 64, "canonical_position": 7,
                "requirement_coverage_digest": "1" * 64, "dependency_digest": "2" * 64,
                "acquired_versions": [copy.deepcopy(version)] if i == 1 else [],
                "selected_versions": [copy.deepcopy(version)],
            }],
            "mcp": [{
                "invocation_id": f"mcp:{i}", "host_attempt_trace_id": attempt,
                "runtime_request_id": runtime_id, "retrieval_trace_id": "retrieval:origin",
                "receipt_reused": i == 2, "context_capsule_ref": "capsule:one",
                "previous_context_ref": "capsule:one" if i == 2 else None, "status": "SUCCESS",
            }],
            "provider": [{
                "request_id": f"provider:{i}", "host_attempt_trace_id": attempt,
                "provider_native_request_id": f"native:{i}", "native_id_missing_reason": None,
                "status": "SUCCESS", "exposure_status": "DISPATCHED",
                "reader_context_sha256": "f" * 64, "runtime_request_ids": [runtime_id],
                "exposed_versions": [copy.deepcopy(version)],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }],
            "lab": {"result_ref": f"result:{i}", "observable_support": []},
        })
    return result


def test_cache_reuses_origin_without_new_acquisition_and_preserves_unknown_use() -> None:
    facts = _pair()
    original = copy.deepcopy(facts)
    result = join_attempts(facts)
    assert [r["join_status"] for r in result] == ["COMPLETE", "COMPLETE"]
    reused = result[1]["runtime"][0]
    assert reused["retrieval_trace_id"] == result[0]["runtime"][0]["retrieval_trace_id"]
    assert reused["acquired_versions"] == [] and reused["decision_snapshot_digest"] is None
    assert result[1]["requests"][0]["observable_use"] == "UNKNOWN"
    assert result[1]["requests"][0]["causal_attribution"] == "NOT_ESTABLISHED"
    assert facts == original
    with pytest.raises(ValueError, match="CACHE_ORIGIN_NOT_OBSERVED"):
        join_trace(facts[1])


@pytest.mark.parametrize("field,value,reason", [
    ("origin_runtime_request_id", "missing", "CACHE_ORIGIN_NOT_OBSERVED"),
    ("origin_host_attempt_trace_id", "other", "CACHE_ORIGIN_ATTEMPT_MISMATCH"),
    ("retrieval_trace_id", "other", "CACHE_ORIGIN_BINDING_MISMATCH"),
    ("context_capsule_ref", "other", "CACHE_ORIGIN_BINDING_MISMATCH"),
    ("reader_context_sha256", "0" * 64, "CACHE_ORIGIN_BINDING_MISMATCH"),
    ("canonical_position", 8, "CACHE_ORIGIN_BINDING_MISMATCH"),
    ("requirement_coverage_digest", "0" * 64, "CACHE_ORIGIN_BINDING_MISMATCH"),
    ("dependency_digest", "0" * 64, "CACHE_ORIGIN_BINDING_MISMATCH"),
    ("decision_snapshot_digest", "0" * 64, "CACHE_REUSE_IS_NOT_FRESH_ACQUISITION"),
    ("selected_versions", [], "CACHE_REUSE_IS_NOT_FRESH_ACQUISITION"),
    ("gate", "BLOCKED", "CACHE_REUSE_IS_NOT_FRESH_ACQUISITION"),
])
def test_cache_origin_mismatch_is_not_guessed(field: str, value: Any, reason: str) -> None:
    facts = _pair()
    facts[1]["runtime"][0][field] = value
    with pytest.raises(ValueError, match=reason):
        join_attempts(facts)


@pytest.mark.parametrize("change,reason", [
    ("fresh-replay", "RETRIEVAL_REPLAY"),
    ("runtime-replay", "RUNTIME_REQUEST_REPLAY"),
    ("mcp-request", "AMBIGUOUS_OR_MISSING_RUNTIME_JOIN"),
    ("mcp-origin", "MCP_RUNTIME_ORIGIN_MISMATCH"),
    ("mcp-locator", "MCP_RUNTIME_ORIGIN_MISMATCH"),
    ("provider-request", "UNBOUND_PROVIDER_RETRIEVAL"),
    ("provider-context", "PROVIDER_RUNTIME_CONTEXT_MISMATCH"),
    ("task", "CACHE_ORIGIN_ATTEMPT_MISMATCH"),
    ("lock", "MIXED_RUN_OR_PRODUCT_LOCK"),
])
def test_current_execution_is_not_confused_with_the_cache_origin(change: str, reason: str) -> None:
    facts = _pair()
    current = facts[1]
    if change == "fresh-replay":
        current["runtime"][0] = copy.deepcopy(facts[0]["runtime"][0])
        current["runtime"][0]["runtime_request_id"] = "runtime:2"
        current["mcp"][0]["receipt_reused"] = False
    elif change == "runtime-replay":
        current["runtime"][0]["runtime_request_id"] = "runtime:1"
        current["mcp"][0]["runtime_request_id"] = "runtime:1"
        current["provider"][0]["runtime_request_ids"] = ["runtime:1"]
    elif change == "mcp-request":
        current["mcp"][0]["runtime_request_id"] = "runtime:1"
    elif change == "mcp-origin":
        current["mcp"][0]["retrieval_trace_id"] = "other"
    elif change == "mcp-locator":
        current["mcp"][0]["previous_context_ref"] = None
    elif change == "provider-request":
        current["provider"][0]["runtime_request_ids"] = ["runtime:1"]
    elif change == "provider-context":
        current["provider"][0]["reader_context_sha256"] = "0" * 64
    elif change == "task":
        current["host"]["task_identity_digest"] = "0" * 64
    else:
        current["product_lock_digest"] = "0" * 64
    with pytest.raises(ValueError, match=reason):
        join_attempts(facts)
