from __future__ import annotations

from types import SimpleNamespace
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from milai_client import AgentRecallPolicy
from milai_langgraph import context_node, recall_node


class State(TypedDict, total=False):
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


class _Client:
    def build_context(self, request: Any) -> Any:
        return SimpleNamespace(
            capsule_id="capsule-synthetic",
            protected_sections={"OPEN ISSUES": [{"issue_id": "issue-synthetic"}]},
        )

    def get_trace(self, trace_id: str) -> Any:
        return SimpleNamespace(raw={"trace_id": trace_id})


class _Memory:
    client = _Client()

    def prepare_context(self, query: str, **options: Any) -> Any:
        assert query == "please recall synthetic memory"
        assert options["recall_policy"].consistency_floor == "CANONICAL_REQUIRED"
        return SimpleNamespace(
            routing=SimpleNamespace(route="L1", reason_code="MEMORY_INTENT"),
            recall_envelope=SimpleNamespace(
                status="ABSTAINED",
                trace_id="trace-synthetic",
                issues=["issue-synthetic"],
                context_capsule_id=None,
            ),
            compiled=SimpleNamespace(
                delta=SimpleNamespace(
                    status="REPLACE",
                    snapshot_id="snapshot-synthetic",
                    rendered_context='<milai-memory-data trust="data-only" />',
                ),
                slot=SimpleNamespace(
                    content_hash="0" * 64,
                    canonical_position=1,
                    live_issue_revision_digest="1" * 64,
                ),
                metrics=SimpleNamespace(
                    actual_tokens=None,
                    actual_bytes=45,
                    token_budget_verified=False,
                ),
            ),
        )


graph = StateGraph(State)
graph.add_node(
    "recall",
    cast(
        Any,
        recall_node(
            _Memory(),  # type: ignore[arg-type]
            AgentRecallPolicy(scope={"project_ids": ["milai"]}),
        ),
    ),
)
graph.add_node("context", cast(Any, context_node(_Memory())))  # type: ignore[arg-type]
graph.add_edge(START, "recall")
graph.add_edge("recall", "context")
graph.add_edge("context", END)
result = graph.compile().invoke(
    {
        "memory_query": "please recall synthetic memory",
        "active_goal": "preserve uncertainty",
        "thread_checkpoint": {"framework_owned": True},
    }
)
assert result["thread_checkpoint"] == {"framework_owned": True}
assert result["milai_open_issue_ids"] == ["issue-synthetic"]
print("langgraph smoke: PASS")
