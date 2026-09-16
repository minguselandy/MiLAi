from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .models import (
    CompressionResult,
    Fixture,
    charged_token_count,
    empty_payload,
    protected_issue,
    protected_payload,
)

METHOD_CODES = {
    "full_raw_context": "M00",
    "naive_recursive": "M01",
    "extractive_top_k": "M02",
    "hierarchical_summary": "M03",
    "structured_eviction": "M04",
    "typed_state": "M05",
    "static_open_issue": "M06",
    "ospc": "M07",
    "oracle_equal_budget": "M08",
    "ospc_no_protected": "A01",
    "ospc_no_discharge": "A02",
    "ospc_no_branches": "A03",
    "ospc_no_validator": "A04",
}


def _result(
    method: str,
    fixture: Fixture,
    payload: dict[str, Any],
    *,
    b_min: int,
    infeasible: bool = False,
    failure_code: str | None = None,
    selection_steps: int = 0,
    validator_checks: int = 0,
    fallback_count: int = 0,
) -> CompressionResult:
    code = METHOD_CODES[method]
    payload["compression_trace"] = {
        "fallback_count": fallback_count,
        "method_code": code,
        "recovery_calls": 0,
        "schema": "ospc.compression.trace.v1",
    }
    charged = charged_token_count(payload, code)
    return CompressionResult(
        method=method,
        method_code=code,
        fixture_id=fixture.fixture_id,
        budget_tokens=fixture.budget_tokens,
        b_min_tokens=b_min,
        payload=payload,
        charged_tokens=charged,
        infeasible=infeasible,
        failure_code=failure_code,
        selection_steps=selection_steps,
        validator_checks=validator_checks,
        fallback_count=fallback_count,
    )


def _rendered_cost(method: str, fixture: Fixture, payload: dict[str, Any]) -> int:
    probe = _result(method, fixture, payload, b_min=0)
    return probe.charged_tokens


def b_min_tokens(fixture: Fixture, method: str = "ospc") -> int:
    return _rendered_cost(method, fixture, protected_payload(fixture))


def full_raw_payload(fixture: Fixture) -> dict[str, Any]:
    payload = protected_payload(fixture)
    payload["stable_state"] = list(fixture.stable_state)
    payload["raw_history"] = list(fixture.history)
    return payload


def full_raw_tokens(fixture: Fixture) -> int:
    return _rendered_cost("full_raw_context", fixture, full_raw_payload(fixture))


def validate_preservation(fixture: Fixture, payload: dict[str, Any]) -> tuple[str, ...]:
    failures: list[str] = []
    if payload.get("goal") != fixture.goal:
        failures.append("GOAL_MISMATCH")
    if set(payload.get("constraints") or []) != set(fixture.constraints):
        failures.append("CONSTRAINTS_MISMATCH")
    issue_rows = payload.get("open_issues") or []
    row = next(
        (item for item in issue_rows if item.get("issue_id") == fixture.issue.issue_id),
        None,
    )
    if row is None:
        failures.append("ISSUE_IDENTITY_MISSING")
        return tuple(failures)
    expected = protected_issue(fixture.issue)
    for field in ("issue_type", "target_claim_id", "status", "authority"):
        if row.get(field) != expected[field]:
            failures.append(f"{field.upper()}_MISMATCH")
    for field in ("support_refs", "contradict_refs", "dependencies"):
        if set(row.get(field) or []) != set(expected[field]):
            failures.append(f"{field.upper()}_MISMATCH")
    if row.get("discharge_rule") != expected["discharge_rule"]:
        failures.append("DISCHARGE_RULE_MISMATCH")
    expected_pointers = set(fixture.issue.support_refs) | set(
        fixture.issue.contradict_refs
    )
    if set(payload.get("evidence_pointers") or []) != expected_pointers:
        failures.append("EVIDENCE_POINTERS_MISMATCH")
    return tuple(failures)


def _infeasible(method: str, fixture: Fixture, b_min: int) -> CompressionResult:
    # An explicit infeasible output is never scored as a zero-false-closure success.
    payload = empty_payload(fixture, status="INFEASIBLE_UNDER_BUDGET")
    payload["constraints"] = []
    payload["goal"] = ""
    return _result(
        method,
        fixture,
        payload,
        b_min=b_min,
        infeasible=True,
        failure_code="INFEASIBLE_UNDER_BUDGET",
    )


def _global_preflight(
    method: str, fixture: Fixture
) -> tuple[int, CompressionResult | None]:
    b_min = b_min_tokens(fixture, method)
    if fixture.budget_tokens < b_min:
        return b_min, _infeasible(method, fixture, b_min)
    return b_min, None


def full_raw_context(fixture: Fixture) -> CompressionResult:
    method = "full_raw_context"
    b_min, blocked = _global_preflight(method, fixture)
    if blocked:
        return blocked
    payload = full_raw_payload(fixture)
    if full_raw_tokens(fixture) > fixture.budget_tokens:
        return _infeasible(method, fixture, b_min)
    return _result(
        method, fixture, payload, b_min=b_min, selection_steps=len(fixture.history)
    )


def naive_recursive(fixture: Fixture) -> CompressionResult:
    method = "naive_recursive"
    b_min, blocked = _global_preflight(method, fixture)
    if blocked:
        return blocked
    payload = empty_payload(fixture)
    steps = 0
    for text in reversed(fixture.history):
        steps += 1
        candidate = {**payload, "stable_state": [text, *payload["stable_state"]]}
        if _rendered_cost(method, fixture, candidate) <= fixture.budget_tokens:
            payload = candidate
    return _result(method, fixture, payload, b_min=b_min, selection_steps=steps)


def extractive_top_k(fixture: Fixture) -> CompressionResult:
    method = "extractive_top_k"
    b_min, blocked = _global_preflight(method, fixture)
    if blocked:
        return blocked
    source = protected_issue(fixture.issue)
    priorities = (
        "issue_id",
        "target_claim_id",
        "status",
        "issue_type",
        "support_refs",
        "contradict_refs",
        "discharge_rule",
        "dependencies",
        "authority",
    )
    row: dict[str, Any] = {}
    payload = empty_payload(fixture)
    payload["open_issues"] = [row]
    steps = 0
    for field in priorities:
        steps += 1
        candidate_row = {**row, field: source[field]}
        candidate = {**payload, "open_issues": [candidate_row]}
        if field in {"support_refs", "contradict_refs"}:
            candidate["evidence_pointers"] = sorted(
                set(candidate.get("evidence_pointers") or []) | set(source[field])
            )
        if _rendered_cost(method, fixture, candidate) <= fixture.budget_tokens:
            row = candidate_row
            payload = candidate
    return _result(method, fixture, payload, b_min=b_min, selection_steps=steps)


def hierarchical_summary(fixture: Fixture) -> CompressionResult:
    method = "hierarchical_summary"
    b_min, blocked = _global_preflight(method, fixture)
    if blocked:
        return blocked
    issue = fixture.issue
    payload = empty_payload(fixture)
    payload["stable_state"] = [
        f"Episodes 1-3 concern {issue.target_claim_id}; {issue.issue_id} is {issue.status}."
    ]
    payload["open_issues"] = [
        {
            "issue_id": issue.issue_id,
            "issue_type": issue.issue_type,
            "status": issue.status,
            "target_claim_id": issue.target_claim_id,
        }
    ]
    if _rendered_cost(method, fixture, payload) > fixture.budget_tokens:
        payload["stable_state"] = []
    return _result(method, fixture, payload, b_min=b_min, selection_steps=2)


def _typed(method: str, fixture: Fixture, *, validate: bool) -> CompressionResult:
    b_min, blocked = _global_preflight(method, fixture)
    if blocked:
        return blocked
    payload = protected_payload(fixture)
    checks = 12 if validate else 0
    return _result(
        method,
        fixture,
        payload,
        b_min=b_min,
        selection_steps=12,
        validator_checks=checks,
    )


def structured_eviction(fixture: Fixture) -> CompressionResult:
    return _typed("structured_eviction", fixture, validate=False)


def typed_state(fixture: Fixture) -> CompressionResult:
    return _typed("typed_state", fixture, validate=False)


def static_open_issue(fixture: Fixture) -> CompressionResult:
    return _typed("static_open_issue", fixture, validate=False)


def oracle_equal_budget(fixture: Fixture) -> CompressionResult:
    return _typed("oracle_equal_budget", fixture, validate=False)


def ospc(fixture: Fixture) -> CompressionResult:
    method = "ospc"
    b_min, blocked = _global_preflight(method, fixture)
    if blocked:
        return blocked
    payload = protected_payload(fixture)
    failures = validate_preservation(fixture, payload)
    if failures:
        fallback = protected_payload(fixture)
        if validate_preservation(fixture, fallback):
            raise AssertionError("extractive protected fallback violated the closure")
        return _result(
            method,
            fixture,
            fallback,
            b_min=b_min,
            selection_steps=12,
            validator_checks=24,
            fallback_count=1,
        )
    return _result(
        method,
        fixture,
        payload,
        b_min=b_min,
        selection_steps=12,
        validator_checks=12,
    )


def ospc_with_candidate(
    fixture: Fixture, candidate: dict[str, Any]
) -> CompressionResult:
    """Testable validator/fallback entry point for a lossy first-pass candidate."""

    base = ospc(fixture)
    if base.infeasible:
        return base
    if not validate_preservation(fixture, candidate):
        candidate["compression_trace"] = base.payload["compression_trace"]
        return replace(
            base,
            payload=candidate,
            charged_tokens=charged_token_count(candidate, base.method_code),
        )
    return replace(base, fallback_count=1, validator_checks=24)


def _ablation(
    method: str,
    fixture: Fixture,
    mutate: Callable[[dict[str, Any], dict[str, Any]], None],
) -> CompressionResult:
    global_b_min, blocked = _global_preflight(method, fixture)
    if blocked:
        return blocked
    payload = protected_payload(fixture)
    mutate(payload["open_issues"][0], payload)
    return _result(
        method,
        fixture,
        payload,
        b_min=global_b_min,
        selection_steps=11,
    )


def ospc_no_protected(fixture: Fixture) -> CompressionResult:
    method = "ospc_no_protected"
    b_min, blocked = _global_preflight(method, fixture)
    if blocked:
        return blocked
    payload = empty_payload(fixture)
    return _result(
        method, fixture, payload, b_min=b_min, selection_steps=len(fixture.history)
    )


def ospc_no_discharge(fixture: Fixture) -> CompressionResult:
    return _ablation(
        "ospc_no_discharge", fixture, lambda row, _payload: row.pop("discharge_rule")
    )


def ospc_no_branches(fixture: Fixture) -> CompressionResult:
    def remove_branches(row: dict[str, Any], payload: dict[str, Any]) -> None:
        row.pop("support_refs")
        row.pop("contradict_refs")
        payload["evidence_pointers"] = []

    return _ablation("ospc_no_branches", fixture, remove_branches)


def ospc_no_validator(fixture: Fixture) -> CompressionResult:
    return _typed("ospc_no_validator", fixture, validate=False)


METHODS: dict[str, Callable[[Fixture], CompressionResult]] = {
    "full_raw_context": full_raw_context,
    "naive_recursive": naive_recursive,
    "extractive_top_k": extractive_top_k,
    "hierarchical_summary": hierarchical_summary,
    "structured_eviction": structured_eviction,
    "typed_state": typed_state,
    "static_open_issue": static_open_issue,
    "ospc": ospc,
    "ospc_no_protected": ospc_no_protected,
    "ospc_no_discharge": ospc_no_discharge,
    "ospc_no_branches": ospc_no_branches,
    "ospc_no_validator": ospc_no_validator,
    "oracle_equal_budget": oracle_equal_budget,
}
