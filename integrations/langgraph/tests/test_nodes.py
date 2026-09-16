from __future__ import annotations

from types import SimpleNamespace
from typing import Any, TypedDict, cast

import pytest
from langgraph.graph import END, START, StateGraph
from milai_client import AgentRecallPolicy

from milai_langgraph import (
    context_node,
    human_review_interrupt,
    prepare_proposal_node,
    recall_node,
)


class _Client:
    def build_context(self, request: Any) -> Any:
        return SimpleNamespace(
            capsule_id="capsule-1",
            protected_sections={"active_goal": request.active_goal, "open_issues": []},
        )


class _Memory:
    client = _Client()

    def prepare_context(self, query: str, **options: Any) -> Any:
        assert options["recall_policy"] == AgentRecallPolicy(scope={"project_ids": ["milai"]})
        assert options["session_id"] == "langgraph-default"
        assert options["active_goal"] == "test governed recall"
        rendered = f'<milai-memory-data trust="data-only">{query}</milai-memory-data>'
        slot = SimpleNamespace(
            content_hash="slot-hash",
            canonical_position=7,
            live_issue_revision_digest="issue-digest",
        )
        return SimpleNamespace(
            routing=SimpleNamespace(route="L1", reason_code="SAFE_DEFAULT_RECALL"),
            recall_envelope=SimpleNamespace(
                status="OK",
                trace_id="trace-1",
                issues=["issue-1"],
                context_capsule_id=None,
            ),
            compiled=SimpleNamespace(
                delta=SimpleNamespace(
                    status="REPLACE", snapshot_id="snapshot-1", rendered_context=rendered
                ),
                slot=slot,
                metrics=SimpleNamespace(
                    actual_tokens=None,
                    actual_bytes=len(rendered.encode()),
                    token_budget_verified=False,
                ),
            ),
        )


class _TestState(TypedDict, total=False):
    memory_query: str
    active_goal: str
    thread_checkpoint: dict[str, bool]
    milai_recall_status: str
    milai_prompt_block: str
    milai_trace_id: str
    milai_open_issue_ids: list[str]
    milai_checkpoint_boundary: str
    milai_context_status: str
    milai_context_capsule_id: str
    milai_context_protected_sections: dict[str, Any]
    milai_recall_route: str
    milai_context_delta_status: str
    milai_snapshot_id: str
    milai_slot_hash: str
    milai_canonical_position_seen: int
    milai_live_issue_revision_digest: str
    milai_active_goal_fingerprint: str
    milai_memory_bytes: int
    milai_token_budget_verified: bool


def test_real_langgraph_runs_recall_then_context_without_mixing_checkpoint_store() -> None:
    graph = StateGraph(_TestState)
    graph.add_node(
        "recall",
        cast(
            Any,
            recall_node(  # type: ignore[arg-type]
                _Memory(), AgentRecallPolicy(scope={"project_ids": ["milai"]})
            ),
        ),
    )
    graph.add_node("context", cast(Any, context_node(_Memory())))  # type: ignore[arg-type]
    graph.add_edge(START, "recall")
    graph.add_edge("recall", "context")
    graph.add_edge("context", END)
    app = graph.compile()
    result = app.invoke(
        {
            "memory_query": "synthetic query",
            "active_goal": "test governed recall",
            "thread_checkpoint": {"framework_owned": True},
        }
    )
    assert result["milai_trace_id"] == "trace-1"
    assert result["milai_context_capsule_id"] == "capsule-1"
    assert result["milai_checkpoint_boundary"] == "REFERENCES_ONLY"
    assert result["milai_recall_route"] == "L1"
    assert result["milai_context_delta_status"] == "REPLACE"
    assert result["milai_snapshot_id"] == "snapshot-1"
    assert result["milai_slot_hash"] == "slot-hash"
    assert result["thread_checkpoint"] == {"framework_owned": True}


def test_model_state_cannot_override_host_recall_policy() -> None:
    node = recall_node(  # type: ignore[arg-type]
        _Memory(),
        AgentRecallPolicy(
            scope={"project_ids": ["milai"]},
            authority="ACTION_SAFE",
            consistency_floor="CANONICAL_REQUIRED",
            max_limit=5,
        ),
    )
    with pytest.raises(PermissionError, match="cannot override"):
        node(
            {
                "memory_query": "synthetic",
                "memory_scope": {"project_ids": ["all"]},
                "memory_authority": "USER_CONFIRMED",
                "memory_consistency": "EVENTUAL",
                "memory_limit": 20,
            }
        )


def test_model_proposal_state_is_validated_before_client_call() -> None:
    memory = SimpleNamespace(create_proposal=lambda *_args, **_kwargs: pytest.fail("HTTP called"))
    node = prepare_proposal_node(memory)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        node(
            {
                "proposal_candidate": {"operation": "CREATE"},
                "session_id": "session",
                "candidate_id": "candidate",
            }
        )


def test_human_interrupt_never_reviews_proposal() -> None:
    assert human_review_interrupt({"human_review_required": True}) == {
        "workflow_status": "INTERRUPT_FOR_INDEPENDENT_STEWARD"
    }
