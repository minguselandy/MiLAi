from __future__ import annotations

import argparse
import json
import os
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from milai_client import AgentMemory, AgentRecallPolicy, MilaiClient
from milai_langgraph import context_node, recall_node


class State(TypedDict, total=False):
    memory_query: str
    active_goal: str
    thread_checkpoint: dict[str, Any]
    milai_recall_status: str
    milai_trace_id: str
    milai_open_issue_ids: list[str]
    milai_context_protected_sections: dict[str, Any]


def run(query: str) -> State:
    memory = AgentMemory(MilaiClient())
    graph = StateGraph(State)
    raw_scope = os.environ.get("MILAI_AGENT_SCOPE_JSON", '{"project_ids":["milai"]}')
    scope = json.loads(raw_scope)
    if not isinstance(scope, dict):
        raise TypeError("MILAI_AGENT_SCOPE_JSON must be an object")
    policy = AgentRecallPolicy(scope=scope)
    # LangGraph requires a concrete TypedDict signature while MiLAi nodes are state-agnostic.
    graph.add_node("milai_recall", cast(Any, recall_node(memory, policy)))
    graph.add_node("milai_context", cast(Any, context_node(memory)))
    graph.add_edge(START, "milai_recall")
    graph.add_edge("milai_recall", "milai_context")
    graph.add_edge("milai_context", END)
    return cast(
        State,
        graph.compile().invoke(
            {
                "memory_query": query,
                "active_goal": "answer without flattening uncertainty",
                "thread_checkpoint": {"framework_owned": True},
            }
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    arguments = parser.parse_args()
    print(run(arguments.query))
