from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from test_trace_cache_join import _pair

from milai_lab.analysis.opportunity_ledger import (
    SCHEMA_VERSION,
    build_opportunity_ledger,
    freeze_opportunity,
)
from milai_lab.analysis.trace_join import SCHEMA_VERSION as TRACE_VERSION


def _version(name: str = "memory-1", revision: str = "v1") -> dict[str, Any]:
    return {
        "memory_ref": name,
        "version_id": revision,
        "content_sha256": ("a" if revision == "v1" else "b") * 64,
    }


def _facts(index: int = 1, pool: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    pool = [_version()] if pool is None else pool
    attempt, trace, request = f"attempt-{index}", f"trace-{index}", f"request-{index}"
    return {
        "schema_version": TRACE_VERSION,
        "run_id": "ledger-run",
        "product_lock_digest": "c" * 64,
        "host": {
            "host_attempt_trace_id": attempt,
            "task_identity_digest": str(index) * 64,
            "retry_of": None,
            "terminal": "SUCCESS" if pool else "NO_MEMORY",
        },
        "runtime": [
            {
                "retrieval_trace_id": trace,
                "decision_snapshot_digest": "d" * 64,
                "evidence_set_digest": "e" * 64,
                "missing_reason": None,
                "gate": "ADMITTED",
                "acquired_versions": copy.deepcopy(pool),
                "selected_versions": copy.deepcopy(pool[:1]),
            }
        ]
        if pool
        else [],
        "mcp": [
            {
                "invocation_id": f"mcp-{index}",
                "host_attempt_trace_id": attempt,
                "retrieval_trace_id": trace,
                "status": "SUCCESS",
            }
        ]
        if pool
        else [],
        "provider": [
            {
                "request_id": request,
                "host_attempt_trace_id": attempt,
                "provider_native_request_id": f"native-{index}",
                "native_id_missing_reason": None,
                "status": "SUCCESS",
                "exposure_status": "DISPATCHED",
                "reader_context_sha256": "f" * 64 if pool else None,
                "retrieval_trace_ids": [trace] if pool else [],
                "exposed_versions": copy.deepcopy(pool[:1]),
                "usage": {"input_tokens": 7, "output_tokens": 3},
            }
        ],
        "lab": {"result_ref": f"result-{index}", "observable_support": []},
    }


def _meta(facts: dict[str, Any], index: int = 1) -> dict[str, Any]:
    pool = [v for row in facts["runtime"] for v in row["acquired_versions"]]
    return {
        "host_attempt_trace_id": facts["host"]["host_attempt_trace_id"],
        "arm_id": "baseline",
        "task_id": f"task-{index}",
        "policy_version": "fixture-v1",
        "opportunity": freeze_opportunity(
            {
                "sequence": index * 10,
                "task_input_sha256": str(index) * 64,
                "available_versions": copy.deepcopy(pool),
                "meaningful_alternatives": [[copy.deepcopy(v)] for v in pool],
                "baseline_attempt_id": None,
            }
        ),
        "outcome": {
            "sequence": index * 10 + 5,
            "task_outcome": "SUCCESS",
            "result_ref": facts["lab"]["result_ref"],
        },
        "explicit_adoption": [],
        "explicit_rejection": [],
        "revision_opportunity": False,
        "revision_opportunity_ref": None,
        "costs": {
            "retrieval_calls": len(facts["runtime"]),
            "embedding_calls": 0,
            "model_generations": 0,
            "maintenance_input_tokens": 0,
            "maintenance_output_tokens": 0,
            "latency_ms": 2.5,
            "unknown_reasons": [],
        },
    }


def _observations(metadata: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "method_version": "ledger-test-v1",
        "method_sha256": "e" * 64,
        "arm_kind": "SIMULATION",
        "usage_kind": "CONTROLLED_FIXTURE",
        "attempts": metadata,
        "revisions": [],
    }


def _use(facts: dict[str, Any]) -> None:
    facts["lab"]["observable_support"] = [
        {
            "request_id": facts["provider"][0]["request_id"],
            "version": copy.deepcopy(facts["provider"][0]["exposed_versions"][0]),
            "kind": "STRUCTURED_CITATION",
            "support_ref": "citation-" + facts["provider"][0]["request_id"],
        }
    ]


def test_no_memory_single_candidate_and_multiple_alternatives_keep_denominators() -> None:
    facts = [_facts(1, []), _facts(2), _facts(3, [_version(), _version("memory-2")])]
    metadata = [_meta(value, index) for index, value in enumerate(facts, 1)]
    original = copy.deepcopy(facts)
    observations = _observations(metadata)
    output = build_opportunity_ledger(facts, observations)
    assert [row["memory_available"] for row in output["rows"]] == [False, True, True]
    assert [row["retrieved_candidate_count"] for row in output["rows"]] == [0, 1, 2]
    assert [row["meaningful_alternative_count"] for row in output["rows"]] == [0, 1, 2]
    assert output["funnel"]["mechanism_effect_denominator"] == 1
    assert output["funnel"]["without_opportunity_retained"] == 2
    assert output["funnel"]["selection_comparison_unknown"] == 3
    assert all(row["causal_attribution"] == "NOT_ESTABLISHED" for row in output["rows"])
    assert facts == original
    assert output == build_opportunity_ledger(json.loads(json.dumps(facts)), observations)
    output["rows"][2]["available_versions"].clear()
    assert len(observations["attempts"][2]["opportunity"]["available_versions"]) == 2


def test_selected_not_exposed_and_adoption_are_not_use() -> None:
    facts = _facts()
    facts["host"]["terminal"] = "FAILURE"
    facts["provider"][0].update(
        exposed_versions=[],
        exposure_status="NOT_STARTED",
        status="FAILURE",
        provider_native_request_id=None,
        native_id_missing_reason="NOT_ACCEPTED",
        usage={"input_tokens": 0, "output_tokens": 0},
    )
    meta = _meta(facts)
    meta["explicit_adoption"] = [{"sequence": 12, "version": _version(), "support_ref": "adopt-1"}]
    result = build_opportunity_ledger([facts], _observations([meta]))["rows"][0]
    assert result["selected_versions"] == [_version()]
    assert result["exposed_versions"] == []
    assert result["explicit_adoption"]
    assert result["observable_use"] == "UNKNOWN"
    assert result["failures"] == [
        {"owner": "PROVIDER", "ref": "request-1", "status": "FAILURE"},
        {"owner": "HOST", "ref": "attempt-1", "status": "FAILURE"},
    ]


def test_exposed_success_is_unknown_until_exact_supported_use() -> None:
    facts = _facts()
    unknown = build_opportunity_ledger([facts], _observations([_meta(facts)]))["rows"][0]
    assert unknown["task_outcome"] == "SUCCESS"
    assert unknown["observable_use"] == "UNKNOWN"
    _use(facts)
    used = build_opportunity_ledger([facts], _observations([_meta(facts)]))["rows"][0]
    assert used["observable_use"] == "OBSERVABLY_USED"
    assert used["exposure_sequence"][0]["version_use"][0]["support_refs"] == ["citation-request-1"]
    assert used["causal_attribution"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("output_tokens", [None, 2])
def test_failed_request_keeps_known_tokens_and_unknown_usage(output_tokens: int | None) -> None:
    facts = _facts()
    facts["host"]["terminal"] = "FAILURE"
    facts["provider"][0].update(
        status="FAILURE", usage={"input_tokens": 7, "output_tokens": output_tokens}
    )
    meta = _meta(facts)
    meta["outcome"]["task_outcome"] = "FAILURE"
    row = build_opportunity_ledger([facts], _observations([meta]))["rows"][0]
    assert row["input_tokens"] == row["known_input_tokens"] == 7
    assert row["output_tokens"] == output_tokens
    assert row["unknown_usage"] == (output_tokens is None)
    assert row["unknown_output_tokens_requests"] == (1 if output_tokens is None else 0)


def _revision_inputs(later: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    first = _facts()
    meta = _meta(first)
    meta.update(revision_opportunity=True, revision_opportunity_ref="visible-feedback-1")
    meta["costs"].update(maintenance_input_tokens=11, maintenance_output_tokens=2)
    facts, metadata = [first], [meta]
    if later:
        second = _facts(2, [_version(revision="v2")])
        _use(second)
        facts.append(second)
        metadata.append(_meta(second, 2))
    observations = _observations(metadata)
    observations["revisions"] = [
        {
            "revision_id": "revision-1",
            "source_attempt_id": "attempt-1",
            "created_sequence": 16,
            "predecessor": _version(),
            "version": _version(revision="v2"),
            "policy_version": "revision-fixture-v1",
            "kind": "CORRECTION",
            "evidence_refs": ["feedback-1"],
        }
    ]
    return facts, observations


@pytest.mark.parametrize("later", [False, True])
def test_revision_requires_later_exact_version_and_independent_task(later: bool) -> None:
    facts, observations = _revision_inputs(later)
    result = build_opportunity_ledger(facts, observations)
    row = result["rows"][0]
    assert row["maintenance_tokens"] == 13
    assert len(row["revision_created"]) == 1
    for field in ("later_retrieval", "later_exposure", "later_use"):
        assert len(row[field]) == int(later)
        if later:
            assert row[field][0]["independent_task"]
            assert row[field][0]["version"] == _version(revision="v2")
    assert result["funnel"]["stage_attempt_counts"]["later_used"] == int(later)


@pytest.mark.parametrize(
    "change,reason",
    [
        ("seal", "OPPORTUNITY_SNAPSHOT_CHANGED"),
        ("after-outcome", "OPPORTUNITY_NOT_FROZEN_BEFORE_OUTCOME"),
        ("pool", "OPPORTUNITY_POOL_NOT_OWNER_OBSERVED"),
        ("alternative", "ALTERNATIVE_NOT_IN_FROZEN_POOL"),
        ("cost", "RETRIEVAL_COST_OMITS_OBSERVED_EXECUTIONS"),
        ("unknown", "UNKNOWN_COST_REQUIRES_REASON"),
        ("outcome", "UNBOUND_TASK_OUTCOME"),
        ("adoption", "UNBOUND_EXPLICIT_MEMORY_DECISION"),
    ],
)
def test_invalid_lab_observations_fail_without_payload_echo(change: str, reason: str) -> None:
    facts = _facts()
    meta = _meta(facts)
    snapshot = {
        key: value for key, value in meta["opportunity"].items() if key != "snapshot_sha256"
    }
    if change == "seal":
        meta["opportunity"]["sequence"] = 11
    elif change == "after-outcome":
        snapshot["sequence"] = 16
    elif change == "pool":
        snapshot["available_versions"] = [_version("unobserved")]
    elif change == "alternative":
        snapshot["meaningful_alternatives"] = [[_version("unobserved")]]
    elif change == "cost":
        meta["costs"]["retrieval_calls"] = 0
    elif change == "unknown":
        meta["costs"]["embedding_calls"] = None
    elif change == "outcome":
        meta["outcome"]["result_ref"] = "other-result"
    elif change == "adoption":
        meta["explicit_adoption"] = [
            {"sequence": 12, "version": _version("unobserved"), "support_ref": "adopt-1"}
        ]
    if change in {"after-outcome", "pool", "alternative"}:
        meta["opportunity"] = freeze_opportunity(snapshot)
    with pytest.raises(ValueError, match=f"^{reason}$"):
        build_opportunity_ledger([facts], _observations([meta]))


@pytest.mark.parametrize("field", ["gold", "prompt", "answer", "credentials"])
def test_unrecognized_private_or_hidden_fields_are_not_accepted(field: str) -> None:
    facts = _facts()
    observations = _observations([_meta(facts)])
    observations["attempts"][0]["opportunity"][field] = "private-do-not-echo"
    with pytest.raises(ValueError, match=r"^INVALID_OPPORTUNITY_OBSERVATIONS$"):
        build_opportunity_ledger([facts], observations)


def test_revision_cannot_be_created_after_its_observed_reuse() -> None:
    facts, observations = _revision_inputs(True)
    observations["revisions"][0]["created_sequence"] = 22
    with pytest.raises(ValueError, match=r"^REVISION_REUSE_PRECEDES_CREATION$"):
        build_opportunity_ledger(facts, observations)


def test_selection_change_requires_a_prior_matched_pool_not_outcome_inference() -> None:
    pool = [_version(), _version("memory-2")]
    first, second = _facts(1, pool), _facts(2, pool)
    second["runtime"][0]["selected_versions"] = [copy.deepcopy(pool[1])]
    second["provider"][0]["exposed_versions"] = [copy.deepcopy(pool[1])]
    one, two = _meta(first), _meta(second, 2)
    two.update(task_id=one["task_id"], arm_id="candidate")
    snapshot = {key: value for key, value in two["opportunity"].items() if key != "snapshot_sha256"}
    snapshot["baseline_attempt_id"] = "attempt-1"
    snapshot["task_input_sha256"] = one["opportunity"]["task_input_sha256"]
    two["opportunity"] = freeze_opportunity(snapshot)
    result = build_opportunity_ledger([first, second], _observations([one, two]))
    assert result["rows"][0]["selection_changed"] is None
    assert result["rows"][1]["selection_changed"] is True
    two["task_id"] = "unmatched"
    with pytest.raises(ValueError, match=r"^UNMATCHED_SELECTION_COMPARISON$"):
        build_opportunity_ledger([first, second], _observations([one, two]))


def test_cache_counts_authorized_availability_but_not_fresh_retrieval() -> None:
    facts = _pair()
    one, two = _meta(facts[0]), _meta(facts[1], 2)
    snapshot = {key: value for key, value in two["opportunity"].items()
                if key != "snapshot_sha256"}
    snapshot["available_versions"] = facts[1]["runtime"][0]["selected_versions"]
    snapshot["meaningful_alternatives"] = [snapshot["available_versions"]]
    two["opportunity"] = freeze_opportunity(snapshot)
    two["task_id"] = one["task_id"]
    two["costs"]["retrieval_calls"] = 0
    result = build_opportunity_ledger(facts, _observations([one, two]))
    assert [r["memory_available"] for r in result["rows"]] == [True, True]
    assert [r["retrieved_candidate_count"] for r in result["rows"]] == [1, 0]
    assert [r["retrieval_calls"] for r in result["rows"]] == [1, 0]
    assert result["rows"][1]["observable_use"] == "UNKNOWN"


def test_request_exposure_order_repeats_and_partial_cost_are_preserved() -> None:
    pool = [_version(), _version("memory-2")]
    facts = _facts(1, pool)
    facts["runtime"][0]["selected_versions"] = pool
    first = facts["provider"][0]
    first["exposed_versions"] = list(reversed(pool))
    second = copy.deepcopy(first)
    second.update(request_id="request-second", provider_native_request_id="native-second",
                  exposed_versions=[pool[0]], usage={"input_tokens": None, "output_tokens": 2})
    facts["provider"].append(second)
    meta = _meta(facts)
    meta["costs"].update(embedding_calls=None, unknown_reasons=["EMBEDDING_NOT_OBSERVED"])
    row = build_opportunity_ledger([facts], _observations([meta]))["rows"][0]
    assert row["exposed_versions"] == [pool[1], pool[0], pool[0]]
    assert [r["request_id"] for r in row["exposure_sequence"]] == ["request-1", "request-second"]
    assert row["input_tokens"] is None and row["known_input_tokens"] == 7
    assert row["output_tokens"] == 5 and row["unknown_input_tokens_requests"] == 1
    assert row["unknown_cost_fields"] == ["embedding_calls"]


def test_matched_selection_requires_identical_predeclared_task_input() -> None:
    one, two = _facts(), _facts(2)
    meta_one, meta_two = _meta(one), _meta(two, 2)
    meta_two.update(task_id=meta_one["task_id"], arm_id="candidate")
    snapshot = {key: value for key, value in meta_two["opportunity"].items()
                if key != "snapshot_sha256"}
    snapshot["baseline_attempt_id"] = "attempt-1"
    meta_two["opportunity"] = freeze_opportunity(snapshot)
    with pytest.raises(ValueError, match=r"^UNMATCHED_SELECTION_COMPARISON$"):
        build_opportunity_ledger([one, two], _observations([meta_one, meta_two]))
