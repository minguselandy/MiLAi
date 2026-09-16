from __future__ import annotations

import hashlib
from typing import Any

import pytest

from milai_client import (
    AgentRecallPolicy,
    CallableTokenCounter,
    MemoryTransportUnavailableError,
    TaskMemoryBudget,
    TaskMemoryController,
    TaskMemoryIdentity,
    TokenBudget,
)
from milai_client.models import PrepareContextEnvelope, PrepareContextRequest

DIGEST = "a" * 64


def _coverage() -> dict[str, object]:
    return {
        "version": "memory-slot-coverage-v1",
        "scope": {"project_ids": ["milai"]},
        "authority_supported": "INFORMATIONAL",
        "consistency_supported": "CANONICAL_REQUIRED",
        "claim_ids_and_head_versions": [{"claim_id": "claim-1", "claim_version_id": "version-1"}],
        "state_keys_and_head_versions": [],
        "open_issue_ids_and_revisions": [],
        "temporal_coverage": "CURRENT",
        "evidence_depth": "NONE",
        "policy_identity": DIGEST,
        "dependency_frontier": {
            "kind": "GLOBAL_CANONICAL_POSITION",
            "canonical_position": 7,
        },
    }


def _ready(token: str) -> PrepareContextEnvelope:
    return PrepareContextEnvelope.from_api(
        {
            "route": "L1",
            "status": "READY",
            "context_capsule": {
                "capsule_id": f"capsule-{token}",
                "protected_sections": {
                    "ACTIVE STATE": [
                        {
                            "claim_id": "claim-1",
                            "claim_version_id": "version-1",
                            "subject_id": "project",
                            "predicate": "project.status",
                            "payload": {"value": "ready"},
                            "authority": "INFORMATIONAL",
                            "canonical_commit_seq": 7,
                            "open_issue_ids": [],
                        }
                    ],
                    "OPEN ISSUES": [],
                    "RETRIEVED EVIDENCE": [],
                },
            },
            "context_delta": {"status": "REPLACE"},
            "relevant_open_issue_closure": [],
            "canonical_position": 7,
            "current_state_envelope": {
                "status": "HIT",
                "claims": [{"claim_id": "claim-1"}],
                "open_issues": [],
                "canonical_position": 7,
                "slot_validation_handle": "slot-handle",
                "trace_id": "trace-1",
            },
            "validation_token": token,
            "memory_slot_coverage": _coverage(),
            "trace_pointer": "trace-1",
            "usage": {
                "prepare_context_calls": 1,
                "full_recall_calls": 1,
                "delta_refreshes": 0,
                "validation_calls": 0,
            },
            "timing": {"runtime_total_ms": 4.5, "uds_roundtrip_ms": 5.0},
        }
    )


def _action_ready(token: str) -> PrepareContextEnvelope:
    value = _ready(token).raw | {"route": "ACTION_VALIDATE"}
    return PrepareContextEnvelope.from_api(value)


def _unchanged(token: str) -> PrepareContextEnvelope:
    return PrepareContextEnvelope.from_api(
        {
            "route": "CACHE",
            "status": "UNCHANGED",
            "context_capsule": None,
            "context_delta": {"status": "UNCHANGED"},
            "relevant_open_issue_closure": [],
            "canonical_position": 7,
            "validation_token": token,
            "memory_slot_coverage": _coverage(),
            "usage": {
                "prepare_context_calls": 2,
                "full_recall_calls": 1,
                "delta_refreshes": 0,
                "validation_calls": 1,
            },
            "timing": {"runtime_total_ms": 1.5, "uds_roundtrip_ms": 2.0},
        }
    )


def _integrity_mismatch(token: str) -> PrepareContextEnvelope:
    issue = {
        "issue_id": "issue-1",
        "target_claim_id": "claim-other",
        "issue_type": "CONFLICT",
        "status": "OPEN",
        "revision": 1,
        "scope_predicate": {"project_ids": ["milai"]},
        "discharge_rule": {"kind": "STEWARD_DECISION"},
        "required_authority": "INFORMATIONAL",
        "branches": [
            {"relation_type": "SUPPORT_BRANCH", "evidence_id": "evidence-1"},
            {"relation_type": "CONTRADICT_BRANCH", "evidence_id": "evidence-2"},
        ],
    }
    raw = _ready(token).raw
    raw["context_capsule"]["protected_sections"]["OPEN ISSUES"] = [issue]
    raw["relevant_open_issue_closure"] = [issue]
    raw["recall_execution_trace"] = {
        "need_signature_id": None,
        "requested_route": "L1",
        "planned_route": "L1",
        "validated_route": "L1",
        "attempted_routes": ["L1"],
        "terminal_route": "L1",
        "result": "HIT",
        "policy_override_reason": None,
        "fallback_reason": None,
        "next_route_recommended": None,
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "query_embedding_calls": 0,
        "vector_calls": 0,
        "reranker_calls": 0,
        "exact_calls": 0,
        "fts_calls": 0,
        "l0_calls": 0,
    }
    return PrepareContextEnvelope.from_api(raw)


class _CompositeClient:
    def __init__(self, responses: list[PrepareContextEnvelope]) -> None:
        self.responses = responses
        self.requests: list[PrepareContextRequest] = []

    def prepare_context(self, request: PrepareContextRequest) -> PrepareContextEnvelope:
        self.requests.append(request)
        return self.responses.pop(0)


def _identity(*, epoch: str = "task-1") -> TaskMemoryIdentity:
    return TaskMemoryIdentity("tenant-1", "session-1", "agent-1", "reader", epoch)


def _policy(*, project: str = "milai") -> AgentRecallPolicy:
    return AgentRecallPolicy(
        scope={"project_ids": [project]},
        authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
    )


def _action_policy() -> AgentRecallPolicy:
    return AgentRecallPolicy(
        scope={"project_ids": ["milai"]},
        authority="ACTION_SAFE",
        consistency_floor="CANONICAL_REQUIRED",
    )


def _counter() -> CallableTokenCounter:
    return CallableTokenCounter("test.counter.v1", lambda text: len(text.split()))


def _controller(client: Any) -> TaskMemoryController:
    return TaskMemoryController(
        client,
        compiler_digest=DIGEST,
        router_digest=DIGEST,
        policy_digest=DIGEST,
    )


def test_controller_uses_one_composite_call_and_reuses_validated_task_slot() -> None:
    client = _CompositeClient([_ready("token-1"), _unchanged("token-2")])
    controller = _controller(client)
    counter = _counter()
    budget = TokenBudget.for_class("STANDARD", counter=counter)

    first = controller.prepare_context(
        "project status",
        identity=_identity(),
        event="TASK_START",
        active_goal="finish project",
        recall_policy=_policy(),
        token_counter=counter,
        token_budget=budget,
    )
    cached = controller.prepare_context(
        "ordinary tool result",
        identity=_identity(),
        event="TOOL_RESULT",
        active_goal="finish project",
        recall_policy=_policy(),
        token_counter=counter,
        token_budget=budget,
        requested_route="CACHE",
    )

    assert first.status == "READY"
    assert first.delta is not None
    assert first.delta.delta.rendered_context is not None
    rendered = first.delta.delta.rendered_context
    assert first.outcome.status == "CONTEXT_READY_CURRENT"
    assert first.outcome.provider_execution == "ALLOWED"
    assert first.outcome.context_digest == hashlib.sha256(rendered.encode()).hexdigest()
    assert first.status == "READY"
    assert first.timing is not None
    assert first.timing["runtime_total_ms"] == 4.5
    assert first.timing["context_compile_ms"] >= 0
    assert cached.status == "UNCHANGED"
    assert cached.delta is None
    assert cached.timing == {"runtime_total_ms": 1.5, "uds_roundtrip_ms": 2.0}
    assert len(client.requests) == 2
    assert client.requests[0].previous_validation_token is None
    assert client.requests[1].previous_validation_token == "token-1"
    assert client.requests[1].requested_route == "CACHE"


def test_goal_or_scope_change_discards_old_binding_and_never_reuses_its_token() -> None:
    client = _CompositeClient([_ready("token-1"), _ready("token-2")])
    controller = _controller(client)
    counter = _counter()
    budget = TokenBudget.for_class("STANDARD", counter=counter)
    controller.prepare_context(
        "project status",
        identity=_identity(),
        event="TASK_START",
        active_goal="goal one",
        recall_policy=_policy(),
        token_counter=counter,
        token_budget=budget,
    )
    controller.prepare_context(
        "other project status",
        identity=_identity(),
        event="GOAL_CHANGED",
        active_goal="goal two",
        recall_policy=_policy(project="other"),
        token_counter=counter,
        token_budget=budget,
    )

    assert client.requests[1].previous_validation_token is None
    assert controller.invalidate(_identity()) == 1


def test_cumulative_injection_budget_fails_closed_and_drops_slot() -> None:
    client = _CompositeClient([_ready("token-1")])
    controller = _controller(client)
    counter = _counter()
    result = controller.prepare_context(
        "project status",
        identity=_identity(),
        event="TASK_START",
        active_goal="finish project",
        recall_policy=_policy(),
        token_counter=counter,
        token_budget=TokenBudget.for_class("STANDARD", counter=counter),
        task_budget=TaskMemoryBudget(max_memory_tokens_injected=1),
    )

    assert result.status == "BUDGET_EXHAUSTED"
    assert result.reason == "MEMORY_TOKEN_BUDGET_EXHAUSTED"
    assert result.delta is None
    assert result.validation_token is None
    assert controller.invalidate(_identity()) == 0


def test_context_integrity_mismatch_becomes_typed_abstention_and_drops_slot() -> None:
    client = _CompositeClient([_integrity_mismatch("token-1")])
    controller = _controller(client)
    counter = _counter()

    result = controller.prepare_context(
        "explain the conflict",
        identity=_identity(),
        event="TASK_START",
        active_goal="finish project",
        recall_policy=_policy(),
        token_counter=counter,
        token_budget=TokenBudget.for_class("STANDARD", counter=counter),
    )

    assert result.status == "ABSTAIN"
    assert result.reason == "CONTEXT_ISSUE_TARGET_MISMATCH"
    assert result.validation_token is None
    assert result.recall_execution_trace == {
        "need_signature_id": None,
        "requested_route": "L1",
        "planned_route": "L1",
        "validated_route": "L1",
        "attempted_routes": ["L1"],
        "terminal_route": "L1",
        "result": "HIT",
        "policy_override_reason": None,
        "fallback_reason": None,
        "next_route_recommended": None,
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "query_embedding_calls": 0,
        "vector_calls": 0,
        "reranker_calls": 0,
        "exact_calls": 0,
        "fts_calls": 0,
        "l0_calls": 0,
    }
    assert controller.invalidate(_identity()) == 0


def test_action_authorization_is_bound_short_lived_and_consumed_once() -> None:
    client = _CompositeClient([_action_ready("action-token")])
    controller = _controller(client)
    counter = _counter()
    action = {"tool": "deploy", "arguments": {"environment": "staging"}}

    result = controller.authorize_action(
        action,
        "deploy the current build",
        identity=_identity(),
        active_goal="deploy safely",
        recall_policy=_action_policy(),
        token_counter=counter,
        token_budget=TokenBudget.for_class("STANDARD", counter=counter),
        slot_ttl_seconds=300,
    )

    assert result.status == "READY"
    assert result.authorization is not None
    request = client.requests[0]
    assert request.event == "ACTION_PROPOSED"
    assert request.authority == "ACTION_SAFE"
    assert request.consistency == "CANONICAL_REQUIRED"
    assert request.slot_ttl_seconds == 30
    assert request.action_digest == result.authorization.action_digest
    with pytest.raises(ValueError, match="does not match"):
        result.authorization.consume({"tool": "deploy", "arguments": {"environment": "production"}})
    assert result.authorization.consumed is False
    assert result.authorization.consume(action) == "action-token"
    assert result.authorization.consumed is True
    with pytest.raises(RuntimeError, match="already consumed"):
        result.authorization.consume(action)


def test_action_authorization_rejects_informational_policy_before_network() -> None:
    client = _CompositeClient([])
    controller = _controller(client)
    counter = _counter()
    with pytest.raises(ValueError, match="ACTION_SAFE"):
        controller.authorize_action(
            {"tool": "deploy"},
            "deploy",
            identity=_identity(),
            active_goal="deploy safely",
            recall_policy=_policy(),
            token_counter=counter,
            token_budget=TokenBudget.for_class("STANDARD", counter=counter),
        )
    assert client.requests == []


def _terminal_current_state(status: str, reason: str) -> PrepareContextEnvelope:
    return PrepareContextEnvelope.from_api(
        {
            "route": "L0",
            "status": "NEEDS_RECOVERY" if status == "CANONICAL_UNAVAILABLE" else "ABSTAIN",
            "reason": reason,
            "context_capsule": None,
            "context_delta": {"status": "UNCHANGED"},
            "relevant_open_issue_closure": [],
            "canonical_position": 9,
            "trace_pointer": "trace-terminal",
            "current_state_envelope": {
                "status": status,
                "claims": [],
                "open_issues": [],
                "canonical_position": 9,
                "slot_validation_handle": None,
                "trace_id": "trace-terminal",
            },
        }
    )


@pytest.mark.parametrize(
    ("runtime_status", "outcome_status", "action"),
    [
        ("MISS", "MEMORY_INSUFFICIENT", "ASK_USER"),
        ("AMBIGUOUS", "MEMORY_INSUFFICIENT", "ASK_USER"),
        ("BLOCKED", "GOVERNANCE_BLOCKED", "ABSTAIN"),
        ("CANONICAL_UNAVAILABLE", "MEMORY_REQUIRED_BUT_UNAVAILABLE", "RETRY"),
    ],
)
def test_runtime_current_state_maps_to_typed_provider_prohibition(
    runtime_status: str, outcome_status: str, action: str
) -> None:
    client = _CompositeClient([_terminal_current_state(runtime_status, runtime_status)])
    counter = _counter()
    result = _controller(client).prepare_context(
        "current release target",
        identity=_identity(),
        event="TASK_START",
        active_goal="finish project",
        recall_policy=_policy(),
        token_counter=counter,
        token_budget=TokenBudget.for_class("STANDARD", counter=counter),
        requested_route="L0",
    )

    assert result.outcome.status == outcome_status
    assert result.outcome.execution_action == action
    assert result.outcome.provider_execution == "PROHIBITED"
    assert result.outcome.context_digest is None


def test_transport_unavailable_maps_once_to_retry_and_provider_prohibition() -> None:
    class UnavailableClient:
        def __init__(self) -> None:
            self.calls = 0

        def prepare_context(self, _request: PrepareContextRequest) -> PrepareContextEnvelope:
            self.calls += 1
            raise MemoryTransportUnavailableError("MCP_SOCKET_UNAVAILABLE")

    client = UnavailableClient()
    counter = _counter()
    result = _controller(client).prepare_context(
        "current release target",
        identity=_identity(),
        event="TASK_START",
        active_goal="finish project",
        recall_policy=_policy(),
        token_counter=counter,
        token_budget=TokenBudget.for_class("STANDARD", counter=counter),
        requested_route="L0",
    )

    assert client.calls == 1
    assert result.outcome.status == "MEMORY_REQUIRED_BUT_UNAVAILABLE"
    assert result.outcome.provider_execution == "PROHIBITED"
    assert result.outcome.reason_code == "MCP_SOCKET_UNAVAILABLE"
