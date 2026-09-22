from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from milai_lab.analysis.trace_join import SCHEMA_VERSION, join_attempts, join_trace


def _facts(index: int = 1) -> dict[str, Any]:
    version = {"memory_ref": "memory-1", "version_id": "v1", "content_sha256": "a" * 64}
    attempt = f"attempt-{index}"
    retrieval = f"retrieval-{index}"
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "run-1", "product_lock_digest": "b" * 64,
        "host": {"host_attempt_trace_id": attempt, "task_identity_digest": "c" * 64,
                 "retry_of": None, "terminal": "SUCCESS"},
        "runtime": [{
            "retrieval_trace_id": retrieval, "decision_snapshot_digest": "d" * 64,
            "evidence_set_digest": "e" * 64, "missing_reason": None, "gate": "ADMITTED",
            "acquired_versions": [copy.deepcopy(version)],
            "selected_versions": [copy.deepcopy(version)],
        }],
        "mcp": [{"invocation_id": f"mcp-{index}", "host_attempt_trace_id": attempt,
                 "retrieval_trace_id": retrieval, "status": "SUCCESS"}],
        "provider": [{
            "request_id": f"request-{index}", "host_attempt_trace_id": attempt,
            "provider_native_request_id": f"native-{index}", "native_id_missing_reason": None,
            "status": "SUCCESS", "reader_context_sha256": "f" * 64,
            "retrieval_trace_ids": [retrieval], "exposed_versions": [copy.deepcopy(version)],
            "usage": {"input_tokens": 20, "output_tokens": 5},
        }],
        "lab": {"result_ref": "result-1", "observable_support": []},
    }


@pytest.mark.parametrize("kind", ["EVIDENCE_ALIAS", "STRUCTURED_CITATION", "TOOL_REFERENCE",
                                 "EXACT_VERSION_REVISION"])
def test_success_joins_exact_version_with_observable_support_without_causal_credit(
    kind: str,
) -> None:
    facts = _facts()
    facts["lab"]["observable_support"] = [{
        "request_id": "request-1", "version": facts["provider"][0]["exposed_versions"][0],
        "kind": kind, "support_ref": "support-1",
    }]
    original = copy.deepcopy(facts)
    result = join_trace(facts)
    row = result["requests"][0]
    assert result["join_status"] == "COMPLETE"
    assert row["observable_use"] == "OBSERVABLY_USED"
    assert row["causal_attribution"] == "NOT_ESTABLISHED"
    assert row["outcome_association"] == "ORDERED_EXPOSURE_SEQUENCE"
    assert facts == original
    assert join_trace(json.loads(json.dumps(facts))) == result
    row["exposed_versions"].clear()
    assert facts == original


def test_exposed_with_success_and_outcome_is_still_unknown_use() -> None:
    result = join_trace(_facts())
    assert result["result_ref"] == "result-1"
    assert result["requests"][0]["observable_use"] == "UNKNOWN"


def test_missing_runtime_fields_are_partial_not_fabricated_digests() -> None:
    facts = _facts()
    facts["runtime"][0].update(decision_snapshot_digest=None, missing_reason="NOT_EXPORTED")
    result = join_trace(facts)
    assert result["join_status"] == "PARTIAL"
    assert result["runtime"][0]["decision_snapshot_digest"] is None
    assert result["trace_gaps"] == [{"retrieval_trace_id": "retrieval-1", "reason": "NOT_EXPORTED"}]


def test_retry_keeps_failed_request_and_unknown_usage_in_order() -> None:
    failed, retry = _facts(), _facts(2)
    failed["host"]["terminal"] = "FAILURE"
    failed["provider"][0].update(
        status="UNKNOWN", provider_native_request_id=None,
        native_id_missing_reason="RESPONSE_LOST", usage={"input_tokens": 20, "output_tokens": None},
    )
    retry["host"]["retry_of"] = "attempt-1"
    results = join_attempts([failed, retry])
    assert [row["requests"][0]["request_id"] for row in results] == ["request-1", "request-2"]
    assert results[0]["requests"][0]["unknown_usage"]
    assert results[0]["requests"][0]["usage"] == {"input_tokens": 20, "output_tokens": None}
    assert results[0]["requests"][0]["observable_use"] == "UNKNOWN"
    assert results[0]["join_status"] == "PARTIAL"
    assert not results[1]["requests"][0]["unknown_usage"]


def test_abstain_does_not_invent_provider_or_memory_use() -> None:
    facts = _facts()
    facts["host"]["terminal"] = "ABSTAIN"
    facts["runtime"][0].update(gate="BLOCKED", selected_versions=[])
    facts["mcp"][0]["status"] = "BLOCKED"
    facts["provider"] = []
    result = join_trace(facts)
    assert result["requests"] == []
    assert result["runtime"][0]["gate"] == "BLOCKED"


def test_no_memory_may_have_provider_output_without_memory_use() -> None:
    facts = _facts()
    facts["host"]["terminal"] = "NO_MEMORY"
    facts["runtime"], facts["mcp"] = [], []
    facts["provider"][0].update(
        exposed_versions=[], retrieval_trace_ids=[], reader_context_sha256=None,
    )
    result = join_trace(facts)
    assert result["requests"][0]["observable_use"] == "UNKNOWN"
    assert result["requests"][0]["reader_context_sha256"] is None


@pytest.mark.parametrize("field", ["content", "prompt", "answer", "gold", "score", "token"])
def test_owner_boundary_rejects_private_content_labels_and_credentials_without_echo(
    field: str,
) -> None:
    facts = _facts()
    facts["runtime"][0][field] = "private payload should never appear in an error"
    with pytest.raises(ValueError, match=r"^INVALID_TRACE_OWNER_FACTS$"):
        join_trace(facts)


@pytest.mark.parametrize("change,reason", [
    ("mcp-attempt", "CROSS_ATTEMPT_MCP_JOIN"),
    ("provider-attempt", "CROSS_ATTEMPT_PROVIDER_JOIN"),
    ("selected-digest", "SELECTED_VERSION_NOT_ACQUIRED"),
    ("exposed-digest", "EXPOSURE_NOT_ADMITTED_AND_SELECTED"),
    ("blocked", "EXPOSURE_NOT_ADMITTED_AND_SELECTED"),
    ("mcp-failed", "EXPOSURE_NOT_ADMITTED_AND_SELECTED"),
    ("context-missing", "EXPOSURE_REQUIRES_CONTEXT_DIGEST"),
    ("native-missing", "MISSING_NATIVE_ID_REASON_MISMATCH"),
    ("missing-reason", "MISSING_TRACE_REASON_MISMATCH"),
    ("runtime-missing", "AMBIGUOUS_OR_MISSING_RUNTIME_JOIN"),
    ("duplicate-request", "DUPLICATE_TRACE_ID"),
])
def test_mismatched_owner_join_is_rejected(change: str, reason: str) -> None:
    facts = _facts()
    if change == "mcp-attempt":
        facts["mcp"][0]["host_attempt_trace_id"] = "other"
    elif change == "provider-attempt":
        facts["provider"][0]["host_attempt_trace_id"] = "other"
    elif change == "selected-digest":
        facts["runtime"][0]["selected_versions"][0]["content_sha256"] = "0" * 64
    elif change == "exposed-digest":
        facts["provider"][0]["exposed_versions"][0]["content_sha256"] = "0" * 64
    elif change == "blocked":
        facts["runtime"][0]["gate"] = "BLOCKED"
    elif change == "mcp-failed":
        facts["mcp"][0]["status"] = "FAILURE"
    elif change == "context-missing":
        facts["provider"][0]["reader_context_sha256"] = None
    elif change == "native-missing":
        facts["provider"][0]["provider_native_request_id"] = None
    elif change == "missing-reason":
        facts["runtime"][0]["decision_snapshot_digest"] = None
    elif change == "runtime-missing":
        facts["runtime"].clear()
    elif change == "duplicate-request":
        facts["provider"] *= 2
    with pytest.raises(ValueError, match=f"^{reason}$"):
        join_trace(facts)


def test_use_support_must_name_an_exposed_exact_version() -> None:
    facts = _facts()
    version = copy.deepcopy(facts["provider"][0]["exposed_versions"][0])
    version["version_id"] = "v2"
    facts["lab"]["observable_support"] = [{
        "request_id": "request-1", "version": version,
        "kind": "STRUCTURED_CITATION", "support_ref": "citation-1",
    }]
    with pytest.raises(ValueError, match="USE_SUPPORT_NOT_BOUND_TO_EXPOSED_VERSION"):
        join_trace(facts)


def test_selected_not_exposed_and_later_versions_keep_distinct_sequences() -> None:
    first, second = _facts(), _facts(2)
    first["provider"][0]["exposed_versions"] = []
    second["host"]["retry_of"] = "attempt-1"
    for rows in [
        second["runtime"][0]["acquired_versions"],
        second["runtime"][0]["selected_versions"],
        second["provider"][0]["exposed_versions"],
    ]:
        rows[0].update(version_id="v2", content_sha256="0" * 64)
    result = join_attempts([first, second])
    assert result[0]["requests"][0]["exposed_versions"] == []
    assert result[1]["requests"][0]["exposed_versions"][0]["version_id"] == "v2"
    assert all(row["requests"][0]["observable_use"] == "UNKNOWN" for row in result)


def test_attempt_and_request_replays_are_not_double_counted() -> None:
    with pytest.raises(ValueError, match="ATTEMPT_REPLAY"):
        join_attempts([_facts(), _facts()])
    first, second = _facts(), _facts(2)
    second["provider"][0]["provider_native_request_id"] = "native-1"
    with pytest.raises(ValueError, match="REQUEST_REPLAY"):
        join_attempts([first, second])


def test_retry_cannot_cross_task_or_require_a_future_attempt() -> None:
    first, second = _facts(), _facts(2)
    second["host"].update(retry_of="attempt-1", task_identity_digest="0" * 64)
    with pytest.raises(ValueError, match="UNBOUND_RETRY"):
        join_attempts([first, second])
    with pytest.raises(ValueError, match="UNBOUND_RETRY"):
        join_attempts([second])


@pytest.mark.parametrize("key", ["run_id", "product_lock_digest"])
def test_attempt_batch_cannot_mix_run_or_product_lock(key: str) -> None:
    first, second = _facts(), _facts(2)
    second[key] = "0" * 64
    with pytest.raises(ValueError, match="MIXED_RUN_OR_PRODUCT_LOCK"):
        join_attempts([first, second])


@pytest.mark.parametrize("owner", ["runtime", "mcp"])
def test_retry_requires_fresh_runtime_and_transport_invocations(owner: str) -> None:
    first, second = _facts(), _facts(2)
    second["host"]["retry_of"] = "attempt-1"
    if owner == "runtime":
        second["runtime"][0]["retrieval_trace_id"] = "retrieval-1"
        second["mcp"][0]["retrieval_trace_id"] = "retrieval-1"
        second["provider"][0]["retrieval_trace_ids"] = ["retrieval-1"]
        reason = "RETRIEVAL_REPLAY"
    else:
        second["mcp"][0]["invocation_id"] = "mcp-1"
        reason = "INVOCATION_REPLAY"
    with pytest.raises(ValueError, match=reason):
        join_attempts([first, second])


def test_same_version_cannot_change_content_across_attempts() -> None:
    first, second = _facts(), _facts(2)
    for rows in [
        second["runtime"][0]["acquired_versions"],
        second["runtime"][0]["selected_versions"],
        second["provider"][0]["exposed_versions"],
    ]:
        rows[0]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="MEMORY_VERSION_CONTENT_CHANGED"):
        join_attempts([first, second])


def test_failed_request_preserves_known_cost_without_inventing_outcome_or_use() -> None:
    facts = _facts()
    facts["host"]["terminal"] = "FAILURE"
    facts["provider"][0]["status"] = "FAILURE"
    facts["lab"]["result_ref"] = None
    result = join_trace(facts)
    request = result["requests"][0]
    assert request["usage"] == {"input_tokens": 20, "output_tokens": 5}
    assert not request["unknown_usage"]
    assert request["outcome_association"] == "NONE"
    assert request["observable_use"] == "UNKNOWN"


def test_one_supported_version_does_not_credit_other_exposed_versions() -> None:
    facts = _facts()
    additional = {"memory_ref": "memory-2", "version_id": "v1", "content_sha256": "0" * 64}
    for rows in [
        facts["runtime"][0]["acquired_versions"],
        facts["runtime"][0]["selected_versions"],
        facts["provider"][0]["exposed_versions"],
    ]:
        rows.append(copy.deepcopy(additional))
    facts["lab"]["observable_support"] = [{
        "request_id": "request-1", "version": facts["provider"][0]["exposed_versions"][0],
        "kind": "EVIDENCE_ALIAS", "support_ref": "support-1",
    }]
    request = join_trace(facts)["requests"][0]
    assert request["observable_use"] == "OBSERVABLY_USED"
    assert [row["observable_use"] for row in request["version_use"]] == [
        "OBSERVABLY_USED", "UNKNOWN",
    ]
    assert request["version_use"][1]["support_refs"] == []
