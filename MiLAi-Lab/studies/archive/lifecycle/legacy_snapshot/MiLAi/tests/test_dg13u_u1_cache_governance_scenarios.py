from __future__ import annotations

import copy
import dataclasses
import hashlib
import json

import pytest

from scripts import dg13u_u1_cache_governance_scenarios as scenarios


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _step_row(
    case_id: str, index: int, expected: scenarios.StepExpectation
) -> dict[str, object]:
    session = (
        _hash(f"session:{expected.session_role}")
        if expected.session_role != "NONE"
        else None
    )
    task = (
        _hash(f"task:{expected.session_role}")
        if expected.session_role != "NONE"
        else None
    )
    return {
        "step_id": expected.step_id,
        "boundary": expected.boundary,
        "operation_sha256": _hash(f"operation:{case_id}:{index}"),
        "session_sha256": session,
        "task_sha256": task,
        "requested_route": expected.requested_route,
        "attempted_routes": list(expected.attempted_routes),
        "terminal_route": expected.terminal_route,
        "route_result": expected.route_result,
        "fallback_reason": expected.fallback_reason,
        "prepare_status": expected.prepare_status,
        "reason_code": expected.reason_code,
        "access_status": expected.access_status,
        "execution_action": expected.execution_action,
        "provider_execution": expected.provider_execution,
        "mcp_calls": expected.mcp_calls,
        "provider_calls": expected.provider_calls,
        "automatic_retries": 0,
        "l0_calls": expected.l0_calls,
        "exact_calls": expected.exact_calls,
        "query_embedding_calls": 0,
        "vector_calls": 0,
        "fts_calls": 0,
        "reranker_calls": 0,
        "receipt_sha256": _hash(f"receipt:{case_id}:{index}"),
    }


def _invariants(case_id: str) -> dict[str, object]:
    session_a = _hash("session:A")
    task_a = _hash("task:A")
    if case_id == "U1-CACHE-FALLBACK":
        context = _hash("context:unchanged")
        return {
            "session_sha256": session_a,
            "task_sha256": task_a,
            "warm_context_sha256": context,
            "fallback_context_sha256": context,
            "canonical_before_sha256": _hash("canonical:before"),
            "canonical_after_sha256": _hash("canonical:after"),
            "requested_state_key_sha256": _hash("state-key:database"),
            "mutated_state_key_sha256": _hash("state-key:target"),
            "mutation_receipt_sha256": _hash("mutation:unrelated"),
            "mutation_applied_post_warm": True,
            "seeded_snapshot_unchanged": True,
            "mutation_cleanup_complete": True,
            "cache_miss_same_call_fallback": True,
        }
    if case_id == "U1-WRONG-TASK":
        return {
            "session_a_sha256": session_a,
            "session_b_sha256": _hash("session:B"),
            "task_a_sha256": task_a,
            "task_b_sha256": _hash("task:B"),
            "cross_task_slot_reused": False,
        }
    if case_id == "U1-WRONG-SCOPE":
        scope = _hash("scope:broker-candidate")
        return {
            "effective_scope_sha256": scope,
            "broker_scope_sha256": scope,
            "candidate_scope_sha256": scope,
            "canonical_item_sha256": _hash("item:canonical"),
            "outside_scope_item_sha256": _hash("item:outside"),
            "effective_scope_bound": True,
            "outside_scope_in_context": False,
            "outside_scope_in_provider_output": False,
        }
    if case_id == "U1-STALE-CURRENT":
        return {
            "session_sha256": session_a,
            "task_sha256": task_a,
            "warm_context_sha256": _hash("context:old"),
            "refreshed_context_sha256": _hash("context:new"),
            "canonical_before_sha256": _hash("canonical:old"),
            "canonical_after_sha256": _hash("canonical:new"),
            "requested_state_key_sha256": _hash("state-key:target"),
            "mutated_state_key_sha256": _hash("state-key:target"),
            "mutation_receipt_sha256": _hash("mutation:receipt"),
            "mutation_applied_post_warm": True,
            "seeded_snapshot_unchanged": True,
            "mutation_cleanup_complete": True,
            "same_composite_reprepare": True,
            "stale_slot_accepted": False,
        }
    if case_id == "U1-REVOKE-REENTRY":
        return {
            "revoked_evidence_sha256": _hash("evidence:revoked"),
            "canonical_block_receipt_sha256": _hash("canonical:block"),
            "canonical_block_applied": True,
            "revoked_claim_accepted": False,
        }
    if case_id == "U1-AUTHORITY-ESCALATION":
        return {
            "requested_authority_sha256": _hash("authority:elevated"),
            "effective_authority_sha256": _hash("authority:informational"),
            "policy_receipt_sha256": _hash("policy:receipt"),
            "startup_rejected": True,
            "authority_widened": False,
        }
    if case_id == "U1-ALIAS-COLLISION":
        return {
            "normalized_alias_sha256": _hash("alias:normalized"),
            "owner_set_sha256": _hash("owners:two"),
            "owner_count": 2,
            "alias_tie_broken": False,
        }
    if case_id == "U1-OPEN-ISSUE":
        return {
            "open_issue_sha256": _hash("issue:live"),
            "head_sha256": _hash("claim:head"),
            "canonical_open_issue_present": True,
            "runtime_issue_closure_present": False,
            "unsafe_branch_selected": False,
            "provider_called": False,
        }
    raise AssertionError(case_id)


def _measurement(case_id: str) -> dict[str, object]:
    scenario = scenarios.scenario_for_case(case_id)
    return {
        "schema": scenarios.MEASUREMENT_SCHEMA,
        "case_id": case_id,
        "execution_class": scenario.execution_class,
        "steps": [
            _step_row(case_id, index, step) for index, step in enumerate(scenario.steps)
        ],
        "mcp_calls": scenario.expected_mcp_calls,
        "provider_calls": scenario.expected_provider_calls,
        "automatic_retries": 0,
        "vllm_lifecycle_attempts": 0,
        "invariants": _invariants(case_id),
        "cleanup": {
            "status": "PASS",
            "attempts": 1,
            "run_owned_resources_absent": True,
            "receipt_sha256": _hash(f"cleanup:{case_id}"),
        },
    }


def _assert_error(case_id: str, measurement: dict[str, object], expected: str) -> None:
    with pytest.raises(scenarios.ScenarioContractError, match=f"^{expected}$"):
        scenarios.reduce_measurement(case_id, measurement)


def test_exact_eight_existing_matrix_cases_and_real_call_counts_are_frozen() -> None:
    expected = {
        "U1-CACHE-FALLBACK": (2, 2),
        "U1-WRONG-TASK": (2, 2),
        "U1-WRONG-SCOPE": (1, 1),
        "U1-STALE-CURRENT": (2, 2),
        "U1-REVOKE-REENTRY": (1, 0),
        "U1-AUTHORITY-ESCALATION": (0, 0),
        "U1-ALIAS-COLLISION": (0, 0),
        "U1-OPEN-ISSUE": (1, 0),
    }

    assert set(scenarios.SCENARIOS) == set(expected)
    for case_id, calls in expected.items():
        scenario = scenarios.scenario_for_case(case_id)
        assert (scenario.expected_mcp_calls, scenario.expected_provider_calls) == calls
        assert scenario.automatic_retries == 0
        assert scenario.vllm_lifecycle_attempts == 0
        expected_class = (
            "ADJACENT_PRODUCT_NEGATIVE"
            if case_id in {"U1-AUTHORITY-ESCALATION", "U1-ALIAS-COLLISION"}
            else "OPENWORKER_E2E"
        )
        assert scenario.execution_class == expected_class
        with pytest.raises(dataclasses.FrozenInstanceError):
            scenario.case_id = "U1-NONE-EN"  # type: ignore[misc]


def test_cache_case_uses_reachable_post_warm_unrelated_mutation() -> None:
    scenario = scenarios.SCENARIOS["U1-CACHE-FALLBACK"]
    assert (scenario.requested_state_key, scenario.mutation_state_key) == (
        "release.database",
        "release.target",
    )
    assert [step.step_id for step in scenario.steps] == [
        "WARM_CURRENT_SLOT",
        "APPLY_UNRELATED_CANONICAL_MUTATION",
        "VALIDATE_CACHE_MISS_SAME_CALL_FALLBACK",
    ]
    assert scenario.steps[1].boundary == "FIXTURE_APPLY_U1_STATE_CHANGE_API"
    miss = scenario.steps[2]
    assert (miss.requested_route, miss.attempted_routes, miss.terminal_route) == (
        "CACHE",
        ("CACHE", "L0"),
        "L0",
    )
    assert miss.fallback_reason == "CACHE_CANONICAL_POSITION_CHANGED"
    assert scenario.expected_mcp_calls == 2
    assert scenario.expected_provider_calls == 2


def test_stale_case_warms_mutates_then_reprepares_same_composite() -> None:
    scenario = scenarios.SCENARIOS["U1-STALE-CURRENT"]
    assert (scenario.requested_state_key, scenario.mutation_state_key) == (
        "release.target",
        "release.target",
    )
    assert [step.boundary for step in scenario.steps] == [
        "HOST_NATIVE_COMPLETION",
        "FIXTURE_APPLY_U1_STATE_CHANGE_API",
        "HOST_NATIVE_COMPLETION",
    ]
    refresh = scenario.steps[-1]
    assert refresh.requested_route == "CACHE"
    assert refresh.attempted_routes == ("CACHE", "L0")
    assert refresh.terminal_route == "L0"
    assert refresh.fallback_reason == "CACHE_CANONICAL_POSITION_CHANGED"
    assert refresh.access_status == "CONTEXT_READY_CURRENT"
    assert refresh.provider_calls == 1


def test_wrong_task_uses_two_real_native_sessions_with_two_full_turns() -> None:
    scenario = scenarios.SCENARIOS["U1-WRONG-TASK"]
    assert [step.session_role for step in scenario.steps] == ["A", "B"]
    assert all(step.boundary == "HOST_NATIVE_COMPLETION" for step in scenario.steps)
    assert sum(step.mcp_calls for step in scenario.steps) == 2
    assert sum(step.provider_calls for step in scenario.steps) == 2


def test_wrong_scope_is_real_openworker_e2e_with_filtered_twin() -> None:
    scenario = scenarios.SCENARIOS["U1-WRONG-SCOPE"]
    assert scenario.execution_class == "OPENWORKER_E2E"
    assert scenario.fixture_setup == "wrong_scope"
    assert scenario.requested_state_key == "release.target"
    assert scenario.product_boundary == "HOST_NATIVE_EXACT_WITH_SCOPE_FILTERED_TWIN"
    assert scenario.steps[0].boundary == "HOST_NATIVE_COMPLETION"
    assert (scenario.expected_mcp_calls, scenario.expected_provider_calls) == (1, 1)


@pytest.mark.parametrize(
    ("case_id", "probe_boundary", "reason"),
    [
        (
            "U1-ALIAS-COLLISION",
            "HOST_RESOLVER_PROCESS_FIXTURE",
            "STATE_KEY_ALIAS_AMBIGUOUS",
        ),
        (
            "U1-AUTHORITY-ESCALATION",
            "INDEPENDENT_NEGATIVE_HOST_STARTUP",
            "HOST_STARTUP_POLICY_INVALID",
        ),
    ],
)
def test_adjacent_negatives_are_bracketed_by_main_readiness(
    case_id: str, probe_boundary: str, reason: str
) -> None:
    scenario = scenarios.SCENARIOS[case_id]
    assert scenario.execution_class == "ADJACENT_PRODUCT_NEGATIVE"
    assert [step.boundary for step in scenario.steps] == [
        "MAIN_COMPOSITION_READINESS",
        probe_boundary,
        "MAIN_COMPOSITION_READINESS",
    ]
    assert scenario.steps[1].reason_code == reason
    assert scenario.expected_mcp_calls == 0
    assert scenario.expected_provider_calls == 0


def test_revoke_and_open_issue_both_stop_at_canonical_gate() -> None:
    revoked = scenarios.SCENARIOS["U1-REVOKE-REENTRY"].steps[0]
    issue = scenarios.SCENARIOS["U1-OPEN-ISSUE"].steps[0]

    assert (
        revoked.route_result,
        revoked.access_status,
        revoked.provider_execution,
    ) == (
        "ABSTAINED",
        "GOVERNANCE_BLOCKED",
        "PROHIBITED",
    )
    assert revoked.provider_calls == 0
    assert (issue.route_result, issue.access_status, issue.provider_execution) == (
        "ABSTAINED",
        "GOVERNANCE_BLOCKED",
        "PROHIBITED",
    )
    assert issue.reason_code == "CANONICAL_GATE_REJECTED"
    assert issue.provider_calls == 0


@pytest.mark.parametrize("case_id", tuple(scenarios.SCENARIOS))
def test_valid_measurement_reduces_without_mutation_or_raw_identity(
    case_id: str,
) -> None:
    measurement = _measurement(case_id)
    original = copy.deepcopy(measurement)

    evidence = scenarios.reduce_measurement(case_id, measurement)

    scenario = scenarios.SCENARIOS[case_id]
    assert evidence["status"] == "PASS"
    assert evidence["execution_class"] == scenario.execution_class
    assert evidence["observed_mcp_calls"] == scenario.expected_mcp_calls
    assert evidence["observed_provider_calls"] == scenario.expected_provider_calls
    assert measurement == original
    encoded = json.dumps(evidence, sort_keys=True)
    for forbidden in (
        '"session_id"',
        '"task_id"',
        '"prompt"',
        '"output"',
        '"payload"',
        "private-session",
        "private-task",
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mcp_calls", 4),
        ("provider_calls", 4),
        ("automatic_retries", 1),
        ("vllm_lifecycle_attempts", 1),
    ],
)
def test_extra_call_retry_or_vllm_lifecycle_fails(field: str, value: int) -> None:
    measurement = _measurement("U1-CACHE-FALLBACK")
    measurement[field] = value
    _assert_error(
        "U1-CACHE-FALLBACK",
        measurement,
        "CALL_OR_LIFECYCLE_ACCOUNTING_INVALID",
    )


@pytest.mark.parametrize(
    ("case_id", "false_class"),
    [
        ("U1-CACHE-FALLBACK", "ADJACENT_PRODUCT_NEGATIVE"),
        ("U1-ALIAS-COLLISION", "OPENWORKER_E2E"),
        ("U1-AUTHORITY-ESCALATION", "OPENWORKER_E2E"),
    ],
)
def test_reducer_rejects_execution_class_masquerade(
    case_id: str, false_class: str
) -> None:
    measurement = _measurement(case_id)
    measurement["execution_class"] = false_class
    _assert_error(case_id, measurement, "MEASUREMENT_IDENTITY_INVALID")


def test_adjacent_probe_cannot_be_labeled_as_native_or_omit_main_readiness() -> None:
    native_fake = _measurement("U1-ALIAS-COLLISION")
    steps = native_fake["steps"]
    assert isinstance(steps, list)
    steps[1]["boundary"] = "HOST_NATIVE_COMPLETION"
    _assert_error("U1-ALIAS-COLLISION", native_fake, "STEP_OBSERVATION_INVALID")

    no_readiness = _measurement("U1-AUTHORITY-ESCALATION")
    steps = no_readiness["steps"]
    assert isinstance(steps, list)
    steps.pop(0)
    _assert_error("U1-AUTHORITY-ESCALATION", no_readiness, "STEP_COUNT_INVALID")


def test_cache_negative_twins_reject_terminal_miss_or_target_mutation() -> None:
    terminal_miss = _measurement("U1-CACHE-FALLBACK")
    steps = terminal_miss["steps"]
    assert isinstance(steps, list)
    steps[2]["attempted_routes"] = ["CACHE"]
    _assert_error("U1-CACHE-FALLBACK", terminal_miss, "STEP_OBSERVATION_INVALID")

    target_mutation = _measurement("U1-CACHE-FALLBACK")
    invariants = target_mutation["invariants"]
    assert isinstance(invariants, dict)
    invariants["mutated_state_key_sha256"] = invariants["requested_state_key_sha256"]
    _assert_error("U1-CACHE-FALLBACK", target_mutation, "CACHE_INVARIANT_FAILED")

    changed_context = _measurement("U1-CACHE-FALLBACK")
    invariants = changed_context["invariants"]
    assert isinstance(invariants, dict)
    invariants["fallback_context_sha256"] = _hash("unexpected:changed-context")
    _assert_error("U1-CACHE-FALLBACK", changed_context, "CACHE_INVARIANT_FAILED")

    no_mutation = _measurement("U1-CACHE-FALLBACK")
    invariants = no_mutation["invariants"]
    assert isinstance(invariants, dict)
    invariants["canonical_after_sha256"] = invariants["canonical_before_sha256"]
    _assert_error("U1-CACHE-FALLBACK", no_mutation, "CACHE_INVARIANT_FAILED")


def test_stale_negative_twins_reject_no_mutation_or_stale_acceptance() -> None:
    same_head = _measurement("U1-STALE-CURRENT")
    invariants = same_head["invariants"]
    assert isinstance(invariants, dict)
    invariants["canonical_after_sha256"] = invariants["canonical_before_sha256"]
    _assert_error("U1-STALE-CURRENT", same_head, "STALE_CURRENT_INVARIANT_FAILED")

    accepted = _measurement("U1-STALE-CURRENT")
    invariants = accepted["invariants"]
    assert isinstance(invariants, dict)
    invariants["stale_slot_accepted"] = True
    _assert_error("U1-STALE-CURRENT", accepted, "STALE_CURRENT_INVARIANT_FAILED")

    no_fallback = _measurement("U1-STALE-CURRENT")
    steps = no_fallback["steps"]
    assert isinstance(steps, list)
    steps[2]["fallback_reason"] = None
    _assert_error("U1-STALE-CURRENT", no_fallback, "STEP_OBSERVATION_INVALID")

    unrelated = _measurement("U1-STALE-CURRENT")
    invariants = unrelated["invariants"]
    assert isinstance(invariants, dict)
    invariants["mutated_state_key_sha256"] = _hash("state-key:database")
    _assert_error("U1-STALE-CURRENT", unrelated, "STALE_CURRENT_INVARIANT_FAILED")

    incomplete_receipt = _measurement("U1-STALE-CURRENT")
    invariants = incomplete_receipt["invariants"]
    assert isinstance(invariants, dict)
    invariants["mutation_cleanup_complete"] = False
    _assert_error(
        "U1-STALE-CURRENT", incomplete_receipt, "STALE_CURRENT_INVARIANT_FAILED"
    )


def test_wrong_task_negative_twins_reject_same_session_task_or_slot_reuse() -> None:
    for field_a, field_b in (
        ("session_a_sha256", "session_b_sha256"),
        ("task_a_sha256", "task_b_sha256"),
    ):
        measurement = _measurement("U1-WRONG-TASK")
        invariants = measurement["invariants"]
        assert isinstance(invariants, dict)
        invariants[field_b] = invariants[field_a]
        _assert_error("U1-WRONG-TASK", measurement, "WRONG_TASK_INVARIANT_FAILED")

    reused = _measurement("U1-WRONG-TASK")
    invariants = reused["invariants"]
    assert isinstance(invariants, dict)
    invariants["cross_task_slot_reused"] = True
    _assert_error("U1-WRONG-TASK", reused, "WRONG_TASK_INVARIANT_FAILED")


@pytest.mark.parametrize(
    ("case_id", "field", "value", "error"),
    [
        (
            "U1-WRONG-SCOPE",
            "outside_scope_in_context",
            True,
            "WRONG_SCOPE_INVARIANT_FAILED",
        ),
        (
            "U1-WRONG-SCOPE",
            "outside_scope_in_provider_output",
            True,
            "WRONG_SCOPE_INVARIANT_FAILED",
        ),
        ("U1-ALIAS-COLLISION", "owner_count", 1, "ALIAS_INVARIANT_FAILED"),
        ("U1-ALIAS-COLLISION", "alias_tie_broken", True, "ALIAS_INVARIANT_FAILED"),
        (
            "U1-AUTHORITY-ESCALATION",
            "startup_rejected",
            False,
            "AUTHORITY_INVARIANT_FAILED",
        ),
        (
            "U1-AUTHORITY-ESCALATION",
            "authority_widened",
            True,
            "AUTHORITY_INVARIANT_FAILED",
        ),
    ],
)
def test_injection_boundary_negative_twins_fail(
    case_id: str, field: str, value: object, error: str
) -> None:
    measurement = _measurement(case_id)
    invariants = measurement["invariants"]
    assert isinstance(invariants, dict)
    invariants[field] = value
    _assert_error(case_id, measurement, error)


def test_revoke_and_open_issue_negative_twins_fail() -> None:
    revoked = _measurement("U1-REVOKE-REENTRY")
    invariants = revoked["invariants"]
    assert isinstance(invariants, dict)
    invariants["revoked_claim_accepted"] = True
    _assert_error("U1-REVOKE-REENTRY", revoked, "REVOKE_INVARIANT_FAILED")

    issue = _measurement("U1-OPEN-ISSUE")
    invariants = issue["invariants"]
    assert isinstance(invariants, dict)
    invariants["unsafe_branch_selected"] = True
    _assert_error("U1-OPEN-ISSUE", issue, "OPEN_ISSUE_INVARIANT_FAILED")

    provider_called = _measurement("U1-OPEN-ISSUE")
    invariants = provider_called["invariants"]
    assert isinstance(invariants, dict)
    invariants["provider_called"] = True
    _assert_error("U1-OPEN-ISSUE", provider_called, "OPEN_ISSUE_INVARIANT_FAILED")


def test_missing_cleanup_extra_attempt_and_duplicate_operation_fail_closed() -> None:
    missing = _measurement("U1-WRONG-SCOPE")
    del missing["cleanup"]
    _assert_error("U1-WRONG-SCOPE", missing, "MEASUREMENT_FIELDS_INVALID")

    extra_attempt = _measurement("U1-WRONG-SCOPE")
    cleanup = extra_attempt["cleanup"]
    assert isinstance(cleanup, dict)
    cleanup["attempts"] = 2
    _assert_error("U1-WRONG-SCOPE", extra_attempt, "CLEANUP_INCOMPLETE")

    duplicate = _measurement("U1-WRONG-TASK")
    steps = duplicate["steps"]
    assert isinstance(steps, list)
    steps[1]["operation_sha256"] = steps[0]["operation_sha256"]
    _assert_error("U1-WRONG-TASK", duplicate, "STEP_OPERATION_IDENTITY_INVALID")


def test_raw_or_extra_fields_and_non_integer_counter_fail_closed() -> None:
    raw = _measurement("U1-OPEN-ISSUE")
    invariants = raw["invariants"]
    assert isinstance(invariants, dict)
    invariants["raw_issue_id"] = "private-id"
    _assert_error("U1-OPEN-ISSUE", raw, "INVARIANT_FIELDS_INVALID")

    boolean_counter = _measurement("U1-WRONG-SCOPE")
    steps = boolean_counter["steps"]
    assert isinstance(steps, list)
    steps[0]["mcp_calls"] = True
    _assert_error("U1-WRONG-SCOPE", boolean_counter, "STEP_COUNTER_INVALID")


def test_unknown_case_is_rejected() -> None:
    with pytest.raises(scenarios.ScenarioContractError, match="^UNSUPPORTED_CASE$"):
        scenarios.scenario_for_case("U1-CACHE-HIT")
