"""Executable plans and hash-only reducers for DG-13U cache/governance cases.

The helper does not start Host, MCP, Runtime, Docker, or vLLM.  It freezes the
observable product boundaries that a runner must exercise and rejects measured
rows that do not have the exact route, call, retry, isolation, and outcome
semantics of the shipped Host/Runtime implementation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

MEASUREMENT_SCHEMA = "milai.dg13u.u1-cache-governance-measurement.v1"
EVIDENCE_SCHEMA = "milai.dg13u.u1-cache-governance-evidence.v1"
_HASH = re.compile(r"[0-9a-f]{64}")

Route = Literal["CACHE", "L0"]
SessionRole = Literal["A", "B", "NONE"]
ExecutionClass = Literal["OPENWORKER_E2E", "ADJACENT_PRODUCT_NEGATIVE"]


class ScenarioContractError(ValueError):
    """A plan selector or measured receipt violated the frozen contract."""


@dataclass(frozen=True, slots=True)
class StepExpectation:
    step_id: str
    boundary: str
    action: str
    session_role: SessionRole
    requested_route: Route | None
    attempted_routes: tuple[Route, ...]
    terminal_route: Route | None
    route_result: str
    fallback_reason: str | None
    prepare_status: str
    reason_code: str | None
    access_status: str | None
    execution_action: str | None
    provider_execution: str | None
    mcp_calls: int
    provider_calls: int
    automatic_retries: Literal[0]
    l0_calls: int
    exact_calls: int


@dataclass(frozen=True, slots=True)
class Scenario:
    case_id: str
    execution_class: ExecutionClass
    product_boundary: str
    fixture_setup: str | None
    requested_state_key: str | None
    mutation_state_key: str | None
    steps: tuple[StepExpectation, ...]
    expected_mcp_calls: int
    expected_provider_calls: int
    automatic_retries: Literal[0]
    vllm_lifecycle_attempts: Literal[0]
    safety_counters: tuple[str, ...]


def _step(
    step_id: str,
    boundary: str,
    action: str,
    session_role: SessionRole,
    *,
    requested_route: Route | None = None,
    attempted_routes: tuple[Route, ...] = (),
    terminal_route: Route | None = None,
    route_result: str,
    fallback_reason: str | None = None,
    prepare_status: str,
    reason_code: str | None = None,
    access_status: str | None = None,
    execution_action: str | None = None,
    provider_execution: str | None = None,
    mcp_calls: int = 0,
    provider_calls: int = 0,
    l0_calls: int = 0,
    exact_calls: int = 0,
) -> StepExpectation:
    return StepExpectation(
        step_id=step_id,
        boundary=boundary,
        action=action,
        session_role=session_role,
        requested_route=requested_route,
        attempted_routes=attempted_routes,
        terminal_route=terminal_route,
        route_result=route_result,
        fallback_reason=fallback_reason,
        prepare_status=prepare_status,
        reason_code=reason_code,
        access_status=access_status,
        execution_action=execution_action,
        provider_execution=provider_execution,
        mcp_calls=mcp_calls,
        provider_calls=provider_calls,
        automatic_retries=0,
        l0_calls=l0_calls,
        exact_calls=exact_calls,
    )


def _ready_l0(step_id: str, session_role: Literal["A", "B"]) -> StepExpectation:
    return _step(
        step_id,
        "HOST_NATIVE_COMPLETION",
        "PREPARE_CURRENT_EXACT_THEN_ONE_PROVIDER_COMPLETION",
        session_role,
        requested_route="L0",
        attempted_routes=("L0",),
        terminal_route="L0",
        route_result="HIT",
        prepare_status="READY",
        access_status="CONTEXT_READY_CURRENT",
        execution_action="CONTINUE",
        provider_execution="ALLOWED",
        mcp_calls=1,
        provider_calls=1,
        l0_calls=1,
    )


def _composition_ready(step_id: str) -> StepExpectation:
    return _step(
        step_id,
        "MAIN_COMPOSITION_READINESS",
        "VERIFY_EXISTING_HOST_BROKER_RUNTIME_COMPOSITION_READY",
        "NONE",
        route_result="READY",
        prepare_status="COMPOSITION_READY",
    )


SCENARIOS: Mapping[str, Scenario] = MappingProxyType(
    {
        "U1-CACHE-FALLBACK": Scenario(
            case_id="U1-CACHE-FALLBACK",
            execution_class="OPENWORKER_E2E",
            product_boundary="HOST_NATIVE_SAME_SESSION_AND_RUNTIME_WRITER",
            fixture_setup=None,
            requested_state_key="release.database",
            mutation_state_key="release.target",
            steps=(
                _ready_l0("WARM_CURRENT_SLOT", "A"),
                _step(
                    "APPLY_UNRELATED_CANONICAL_MUTATION",
                    "FIXTURE_APPLY_U1_STATE_CHANGE_API",
                    "CALL_APPLY_U1_STATE_CHANGE_AFTER_WARM_FOR_DIFFERENT_STATE_KEY",
                    "NONE",
                    route_result="MUTATED",
                    prepare_status="MUTATION_APPLIED",
                ),
                _step(
                    "VALIDATE_CACHE_MISS_SAME_CALL_FALLBACK",
                    "HOST_NATIVE_COMPLETION",
                    "REPEAT_SAME_TYPED_NEED_AFTER_CANONICAL_POSITION_CHANGE",
                    "A",
                    requested_route="CACHE",
                    attempted_routes=("CACHE", "L0"),
                    terminal_route="L0",
                    route_result="HIT",
                    fallback_reason="CACHE_CANONICAL_POSITION_CHANGED",
                    prepare_status="READY",
                    access_status="CONTEXT_READY_CURRENT",
                    execution_action="CONTINUE",
                    provider_execution="ALLOWED",
                    mcp_calls=1,
                    provider_calls=1,
                    l0_calls=1,
                ),
            ),
            expected_mcp_calls=2,
            expected_provider_calls=2,
            automatic_retries=0,
            vllm_lifecycle_attempts=0,
            safety_counters=("TerminalCacheMiss", "UnaccountedProviderOrMcpCall"),
        ),
        "U1-WRONG-TASK": Scenario(
            case_id="U1-WRONG-TASK",
            execution_class="OPENWORKER_E2E",
            product_boundary="HOST_NATIVE_MULTI_SESSION_REGISTRY",
            fixture_setup=None,
            requested_state_key="release.target",
            mutation_state_key=None,
            steps=(
                _ready_l0("WARM_SESSION_A", "A"),
                _ready_l0("START_ISOLATED_SESSION_B", "B"),
            ),
            expected_mcp_calls=2,
            expected_provider_calls=2,
            automatic_retries=0,
            vllm_lifecycle_attempts=0,
            safety_counters=("WrongTaskAcceptance", "UnaccountedProviderOrMcpCall"),
        ),
        "U1-WRONG-SCOPE": Scenario(
            case_id="U1-WRONG-SCOPE",
            execution_class="OPENWORKER_E2E",
            product_boundary="HOST_NATIVE_EXACT_WITH_SCOPE_FILTERED_TWIN",
            fixture_setup="wrong_scope",
            requested_state_key="release.target",
            mutation_state_key=None,
            steps=(_ready_l0("QUERY_SCOPE_FILTERED_EXACT_TWIN", "A"),),
            expected_mcp_calls=1,
            expected_provider_calls=1,
            automatic_retries=0,
            vllm_lifecycle_attempts=0,
            safety_counters=("WrongScopeAcceptance", "UnaccountedProviderOrMcpCall"),
        ),
        "U1-STALE-CURRENT": Scenario(
            case_id="U1-STALE-CURRENT",
            execution_class="OPENWORKER_E2E",
            product_boundary="HOST_NATIVE_SAME_SESSION_AND_CANONICAL_WRITER",
            fixture_setup=None,
            requested_state_key="release.target",
            mutation_state_key="release.target",
            steps=(
                _ready_l0("WARM_PRE_MUTATION_CURRENT", "A"),
                _step(
                    "APPLY_CANONICAL_HEAD_MUTATION",
                    "FIXTURE_APPLY_U1_STATE_CHANGE_API",
                    "CALL_APPLY_U1_STATE_CHANGE_AFTER_WARM_FOR_REQUESTED_HEAD",
                    "NONE",
                    route_result="MUTATED",
                    prepare_status="MUTATION_APPLIED",
                ),
                _step(
                    "REPREPARE_SAME_COMPOSITE_AFTER_MUTATION",
                    "HOST_NATIVE_COMPLETION",
                    "REPEAT_SAME_TYPED_NEED_AND_REFRESH_CHANGED_HEAD",
                    "A",
                    requested_route="CACHE",
                    attempted_routes=("CACHE", "L0"),
                    terminal_route="L0",
                    route_result="HIT",
                    fallback_reason="CACHE_CANONICAL_POSITION_CHANGED",
                    prepare_status="READY",
                    access_status="CONTEXT_READY_CURRENT",
                    execution_action="CONTINUE",
                    provider_execution="ALLOWED",
                    mcp_calls=1,
                    provider_calls=1,
                    l0_calls=1,
                ),
            ),
            expected_mcp_calls=2,
            expected_provider_calls=2,
            automatic_retries=0,
            vllm_lifecycle_attempts=0,
            safety_counters=("StaleCurrentAcceptance", "UnaccountedProviderOrMcpCall"),
        ),
        "U1-REVOKE-REENTRY": Scenario(
            case_id="U1-REVOKE-REENTRY",
            execution_class="OPENWORKER_E2E",
            product_boundary="CANONICAL_FIXTURE_THEN_HOST_NATIVE_COMPLETION",
            fixture_setup="revoke",
            requested_state_key="release.database",
            mutation_state_key=None,
            steps=(
                _step(
                    "QUERY_CANONICALLY_BLOCKED_EVIDENCE",
                    "HOST_NATIVE_COMPLETION",
                    "PREPARE_EXACT_HEAD_AFTER_APPLIED_EVIDENCE_REVOCATION",
                    "A",
                    requested_route="L0",
                    attempted_routes=("L0",),
                    terminal_route="L0",
                    route_result="ABSTAINED",
                    prepare_status="ABSTAIN",
                    reason_code="CANONICAL_GATE_REJECTED",
                    access_status="GOVERNANCE_BLOCKED",
                    execution_action="ABSTAIN",
                    provider_execution="PROHIBITED",
                    mcp_calls=1,
                    l0_calls=1,
                ),
            ),
            expected_mcp_calls=1,
            expected_provider_calls=0,
            automatic_retries=0,
            vllm_lifecycle_attempts=0,
            safety_counters=("RevokedEvidenceReentry",),
        ),
        "U1-AUTHORITY-ESCALATION": Scenario(
            case_id="U1-AUTHORITY-ESCALATION",
            execution_class="ADJACENT_PRODUCT_NEGATIVE",
            product_boundary="MAIN_READINESS_AROUND_INDEPENDENT_HOST_POLICY_PROBE",
            fixture_setup=None,
            requested_state_key=None,
            mutation_state_key=None,
            steps=(
                _composition_ready("VERIFY_MAIN_COMPOSITION_BEFORE_AUTHORITY_PROBE"),
                _step(
                    "REJECT_ELEVATED_STARTUP_AUTHORITY",
                    "INDEPENDENT_NEGATIVE_HOST_STARTUP",
                    "LOAD_RUN_OWNED_POLICY_WITH_NON_INFORMATIONAL_AUTHORITY",
                    "NONE",
                    route_result="TYPED_FAILURE",
                    prepare_status="PRE_MCP_REJECTED",
                    reason_code="HOST_STARTUP_POLICY_INVALID",
                ),
                _composition_ready("VERIFY_MAIN_COMPOSITION_AFTER_AUTHORITY_PROBE"),
            ),
            expected_mcp_calls=0,
            expected_provider_calls=0,
            automatic_retries=0,
            vllm_lifecycle_attempts=0,
            safety_counters=("UnauthorizedAuthorityEscalation",),
        ),
        "U1-ALIAS-COLLISION": Scenario(
            case_id="U1-ALIAS-COLLISION",
            execution_class="ADJACENT_PRODUCT_NEGATIVE",
            product_boundary="MAIN_READINESS_AROUND_ISOLATED_RESOLVER_PROBE",
            fixture_setup=None,
            requested_state_key=None,
            mutation_state_key=None,
            steps=(
                _composition_ready("VERIFY_MAIN_COMPOSITION_BEFORE_ALIAS_PROBE"),
                _step(
                    "REJECT_NORMALIZED_ALIAS_COLLISION",
                    "HOST_RESOLVER_PROCESS_FIXTURE",
                    "RESOLVE_ONE_NORMALIZED_ALIAS_WITH_TWO_LIVE_OWNERS",
                    "NONE",
                    route_result="TYPED_FAILURE",
                    prepare_status="PRE_MCP_REJECTED",
                    reason_code="STATE_KEY_ALIAS_AMBIGUOUS",
                ),
                _composition_ready("VERIFY_MAIN_COMPOSITION_AFTER_ALIAS_PROBE"),
            ),
            expected_mcp_calls=0,
            expected_provider_calls=0,
            automatic_retries=0,
            vllm_lifecycle_attempts=0,
            safety_counters=("WrongScopeAcceptance", "UnaccountedProviderOrMcpCall"),
        ),
        "U1-OPEN-ISSUE": Scenario(
            case_id="U1-OPEN-ISSUE",
            execution_class="OPENWORKER_E2E",
            product_boundary="CANONICAL_FIXTURE_THEN_HOST_NATIVE_COMPLETION",
            fixture_setup="open_issue",
            requested_state_key="release.decision",
            mutation_state_key=None,
            steps=(
                _step(
                    "ANSWER_WITH_GOVERNED_OPEN_ISSUE_CONTEXT",
                    "HOST_NATIVE_COMPLETION",
                    "PREPARE_CURRENT_EXACT_AND_STOP_ON_CANONICAL_GATE_ABSTAIN",
                    "A",
                    requested_route="L0",
                    attempted_routes=("L0",),
                    terminal_route="L0",
                    route_result="ABSTAINED",
                    prepare_status="ABSTAIN",
                    reason_code="CANONICAL_GATE_REJECTED",
                    access_status="GOVERNANCE_BLOCKED",
                    execution_action="ABSTAIN",
                    provider_execution="PROHIBITED",
                    mcp_calls=1,
                    l0_calls=1,
                ),
            ),
            expected_mcp_calls=1,
            expected_provider_calls=0,
            automatic_retries=0,
            vllm_lifecycle_attempts=0,
            safety_counters=(
                "StaleCurrentAcceptance",
                "UnauthorizedAuthorityEscalation",
                "UnaccountedProviderOrMcpCall",
            ),
        ),
    }
)

_TOP_FIELDS = frozenset(
    {
        "schema",
        "case_id",
        "execution_class",
        "steps",
        "mcp_calls",
        "provider_calls",
        "automatic_retries",
        "vllm_lifecycle_attempts",
        "invariants",
        "cleanup",
    }
)
_STEP_FIELDS = frozenset(
    {
        "step_id",
        "boundary",
        "operation_sha256",
        "session_sha256",
        "task_sha256",
        "requested_route",
        "attempted_routes",
        "terminal_route",
        "route_result",
        "fallback_reason",
        "prepare_status",
        "reason_code",
        "access_status",
        "execution_action",
        "provider_execution",
        "mcp_calls",
        "provider_calls",
        "automatic_retries",
        "l0_calls",
        "exact_calls",
        "query_embedding_calls",
        "vector_calls",
        "fts_calls",
        "reranker_calls",
        "receipt_sha256",
    }
)
_CLEANUP_FIELDS = frozenset(
    {"status", "attempts", "run_owned_resources_absent", "receipt_sha256"}
)
_INVARIANT_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "U1-CACHE-FALLBACK": frozenset(
            {
                "session_sha256",
                "task_sha256",
                "warm_context_sha256",
                "fallback_context_sha256",
                "canonical_before_sha256",
                "canonical_after_sha256",
                "requested_state_key_sha256",
                "mutated_state_key_sha256",
                "mutation_receipt_sha256",
                "mutation_applied_post_warm",
                "seeded_snapshot_unchanged",
                "mutation_cleanup_complete",
                "cache_miss_same_call_fallback",
            }
        ),
        "U1-WRONG-TASK": frozenset(
            {
                "session_a_sha256",
                "session_b_sha256",
                "task_a_sha256",
                "task_b_sha256",
                "cross_task_slot_reused",
            }
        ),
        "U1-WRONG-SCOPE": frozenset(
            {
                "effective_scope_sha256",
                "broker_scope_sha256",
                "candidate_scope_sha256",
                "canonical_item_sha256",
                "outside_scope_item_sha256",
                "effective_scope_bound",
                "outside_scope_in_context",
                "outside_scope_in_provider_output",
            }
        ),
        "U1-STALE-CURRENT": frozenset(
            {
                "session_sha256",
                "task_sha256",
                "warm_context_sha256",
                "refreshed_context_sha256",
                "canonical_before_sha256",
                "canonical_after_sha256",
                "requested_state_key_sha256",
                "mutated_state_key_sha256",
                "mutation_receipt_sha256",
                "mutation_applied_post_warm",
                "seeded_snapshot_unchanged",
                "mutation_cleanup_complete",
                "same_composite_reprepare",
                "stale_slot_accepted",
            }
        ),
        "U1-REVOKE-REENTRY": frozenset(
            {
                "revoked_evidence_sha256",
                "canonical_block_receipt_sha256",
                "canonical_block_applied",
                "revoked_claim_accepted",
            }
        ),
        "U1-AUTHORITY-ESCALATION": frozenset(
            {
                "requested_authority_sha256",
                "effective_authority_sha256",
                "policy_receipt_sha256",
                "startup_rejected",
                "authority_widened",
            }
        ),
        "U1-ALIAS-COLLISION": frozenset(
            {
                "normalized_alias_sha256",
                "owner_set_sha256",
                "owner_count",
                "alias_tie_broken",
            }
        ),
        "U1-OPEN-ISSUE": frozenset(
            {
                "open_issue_sha256",
                "head_sha256",
                "canonical_open_issue_present",
                "runtime_issue_closure_present",
                "unsafe_branch_selected",
                "provider_called",
            }
        ),
    }
)


def scenario_for_case(case_id: str) -> Scenario:
    if not isinstance(case_id, str) or case_id not in SCENARIOS:
        raise ScenarioContractError("UNSUPPORTED_CASE")
    return SCENARIOS[case_id]


def reduce_measurement(
    case_id: str, measurement: Mapping[str, object]
) -> dict[str, object]:
    """Validate one measurement and return payload-free, hash-only evidence."""

    scenario = scenario_for_case(case_id)
    if not isinstance(measurement, Mapping) or set(measurement) != _TOP_FIELDS:
        raise ScenarioContractError("MEASUREMENT_FIELDS_INVALID")
    if (
        measurement.get("schema") != MEASUREMENT_SCHEMA
        or measurement.get("case_id") != case_id
        or measurement.get("execution_class") != scenario.execution_class
    ):
        raise ScenarioContractError("MEASUREMENT_IDENTITY_INVALID")
    for name, expected in (
        ("mcp_calls", scenario.expected_mcp_calls),
        ("provider_calls", scenario.expected_provider_calls),
        ("automatic_retries", 0),
        ("vllm_lifecycle_attempts", 0),
    ):
        if not _exact_int(measurement.get(name), expected):
            raise ScenarioContractError("CALL_OR_LIFECYCLE_ACCOUNTING_INVALID")
    safe_steps = _validate_steps(scenario, measurement.get("steps"))
    safe_invariants = _validate_invariants(
        case_id, measurement.get("invariants"), safe_steps
    )
    safe_cleanup = _validate_cleanup(measurement.get("cleanup"))
    return {
        "schema": EVIDENCE_SCHEMA,
        "case_id": case_id,
        "execution_class": scenario.execution_class,
        "status": "PASS",
        "steps": safe_steps,
        "observed_mcp_calls": scenario.expected_mcp_calls,
        "observed_provider_calls": scenario.expected_provider_calls,
        "automatic_retries": 0,
        "vllm_lifecycle_attempts": 0,
        "invariants": safe_invariants,
        "cleanup": safe_cleanup,
    }


def _validate_steps(scenario: Scenario, raw_steps: object) -> list[dict[str, object]]:
    if (
        not isinstance(raw_steps, Sequence)
        or isinstance(raw_steps, (str, bytes))
        or len(raw_steps) != len(scenario.steps)
    ):
        raise ScenarioContractError("STEP_COUNT_INVALID")
    safe: list[dict[str, object]] = []
    operation_hashes: set[str] = set()
    total_mcp = 0
    total_provider = 0
    for expected, raw in zip(scenario.steps, raw_steps, strict=True):
        if not isinstance(raw, Mapping) or set(raw) != _STEP_FIELDS:
            raise ScenarioContractError("STEP_FIELDS_INVALID")
        operation_hash = raw.get("operation_sha256")
        session_hash = raw.get("session_sha256")
        task_hash = raw.get("task_sha256")
        if not _is_sha256(operation_hash) or operation_hash in operation_hashes:
            raise ScenarioContractError("STEP_OPERATION_IDENTITY_INVALID")
        operation_hashes.add(operation_hash)
        if expected.session_role == "NONE":
            if session_hash is not None or task_hash is not None:
                raise ScenarioContractError("STEP_SESSION_IDENTITY_INVALID")
        elif not _is_sha256(session_hash) or not _is_sha256(task_hash):
            raise ScenarioContractError("STEP_SESSION_IDENTITY_INVALID")
        exact = {
            "step_id": expected.step_id,
            "boundary": expected.boundary,
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
        }
        if any(raw.get(name) != value for name, value in exact.items()):
            raise ScenarioContractError("STEP_OBSERVATION_INVALID")
        for name in (
            "mcp_calls",
            "provider_calls",
            "automatic_retries",
            "l0_calls",
            "exact_calls",
            "query_embedding_calls",
            "vector_calls",
            "fts_calls",
            "reranker_calls",
        ):
            if not _exact_int(raw.get(name), int(exact[name])):
                raise ScenarioContractError("STEP_COUNTER_INVALID")
        if not _is_sha256(raw.get("receipt_sha256")):
            raise ScenarioContractError("STEP_RECEIPT_INVALID")
        total_mcp += expected.mcp_calls
        total_provider += expected.provider_calls
        safe.append(dict(raw))
    if (
        total_mcp != scenario.expected_mcp_calls
        or total_provider != scenario.expected_provider_calls
    ):
        raise ScenarioContractError("PLAN_CALL_ACCOUNTING_INVALID")
    return safe


def _validate_invariants(
    case_id: str,
    raw: object,
    steps: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    expected_fields = _INVARIANT_FIELDS[case_id]
    if not isinstance(raw, Mapping) or set(raw) != expected_fields:
        raise ScenarioContractError("INVARIANT_FIELDS_INVALID")
    for name, value in raw.items():
        if name.endswith("_sha256") and not _is_sha256(value):
            raise ScenarioContractError("INVARIANT_HASH_INVALID")
    if case_id == "U1-CACHE-FALLBACK":
        _require_same_session_task(steps, raw["session_sha256"], raw["task_sha256"])
        if (
            raw["warm_context_sha256"] != raw["fallback_context_sha256"]
            or raw["canonical_before_sha256"] == raw["canonical_after_sha256"]
            or raw["requested_state_key_sha256"] == raw["mutated_state_key_sha256"]
            or raw["mutation_applied_post_warm"] is not True
            or raw["seeded_snapshot_unchanged"] is not True
            or raw["mutation_cleanup_complete"] is not True
            or raw["cache_miss_same_call_fallback"] is not True
        ):
            raise ScenarioContractError("CACHE_INVARIANT_FAILED")
    elif case_id == "U1-WRONG-TASK":
        if (
            raw["session_a_sha256"] == raw["session_b_sha256"]
            or raw["task_a_sha256"] == raw["task_b_sha256"]
            or raw["cross_task_slot_reused"] is not False
            or steps[0]["session_sha256"] != raw["session_a_sha256"]
            or steps[1]["session_sha256"] != raw["session_b_sha256"]
            or steps[0]["task_sha256"] != raw["task_a_sha256"]
            or steps[1]["task_sha256"] != raw["task_b_sha256"]
        ):
            raise ScenarioContractError("WRONG_TASK_INVARIANT_FAILED")
    elif case_id == "U1-WRONG-SCOPE":
        if (
            raw["effective_scope_sha256"] != raw["broker_scope_sha256"]
            or raw["effective_scope_sha256"] != raw["candidate_scope_sha256"]
            or raw["canonical_item_sha256"] == raw["outside_scope_item_sha256"]
            or raw["effective_scope_bound"] is not True
            or raw["outside_scope_in_context"] is not False
            or raw["outside_scope_in_provider_output"] is not False
        ):
            raise ScenarioContractError("WRONG_SCOPE_INVARIANT_FAILED")
    elif case_id == "U1-STALE-CURRENT":
        session_steps = [steps[0], steps[2]]
        _require_same_session_task(
            session_steps, raw["session_sha256"], raw["task_sha256"]
        )
        if (
            raw["warm_context_sha256"] == raw["refreshed_context_sha256"]
            or raw["canonical_before_sha256"] == raw["canonical_after_sha256"]
            or raw["requested_state_key_sha256"] != raw["mutated_state_key_sha256"]
            or raw["mutation_applied_post_warm"] is not True
            or raw["seeded_snapshot_unchanged"] is not True
            or raw["mutation_cleanup_complete"] is not True
            or raw["same_composite_reprepare"] is not True
            or raw["stale_slot_accepted"] is not False
        ):
            raise ScenarioContractError("STALE_CURRENT_INVARIANT_FAILED")
    elif case_id == "U1-REVOKE-REENTRY":
        if (
            raw["canonical_block_applied"] is not True
            or raw["revoked_claim_accepted"] is not False
        ):
            raise ScenarioContractError("REVOKE_INVARIANT_FAILED")
    elif case_id == "U1-AUTHORITY-ESCALATION":
        if (
            raw["requested_authority_sha256"] == raw["effective_authority_sha256"]
            or raw["startup_rejected"] is not True
            or raw["authority_widened"] is not False
        ):
            raise ScenarioContractError("AUTHORITY_INVARIANT_FAILED")
    elif case_id == "U1-ALIAS-COLLISION":
        if (
            not _exact_int(raw["owner_count"], 2)
            or raw["alias_tie_broken"] is not False
        ):
            raise ScenarioContractError("ALIAS_INVARIANT_FAILED")
    elif case_id == "U1-OPEN-ISSUE":
        if (
            raw["canonical_open_issue_present"] is not True
            or raw["runtime_issue_closure_present"] is not False
            or raw["unsafe_branch_selected"] is not False
            or raw["provider_called"] is not False
        ):
            raise ScenarioContractError("OPEN_ISSUE_INVARIANT_FAILED")
    return dict(raw)


def _require_same_session_task(
    steps: Sequence[Mapping[str, object]], session_hash: object, task_hash: object
) -> None:
    if not _is_sha256(session_hash) or not _is_sha256(task_hash):
        raise ScenarioContractError("SESSION_TASK_HASH_INVALID")
    if any(
        step["session_sha256"] != session_hash or step["task_sha256"] != task_hash
        for step in steps
        if step["session_sha256"] is not None
    ):
        raise ScenarioContractError("SESSION_TASK_CONTINUITY_INVALID")


def _validate_cleanup(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != _CLEANUP_FIELDS:
        raise ScenarioContractError("CLEANUP_FIELDS_INVALID")
    if (
        raw.get("status") != "PASS"
        or not _exact_int(raw.get("attempts"), 1)
        or raw.get("run_owned_resources_absent") is not True
        or not _is_sha256(raw.get("receipt_sha256"))
    ):
        raise ScenarioContractError("CLEANUP_INCOMPLETE")
    return dict(raw)


def _exact_int(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


__all__ = [
    "EVIDENCE_SCHEMA",
    "MEASUREMENT_SCHEMA",
    "SCENARIOS",
    "Scenario",
    "ScenarioContractError",
    "StepExpectation",
    "reduce_measurement",
    "scenario_for_case",
]
