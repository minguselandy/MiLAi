from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Any, Literal, TypedDict, cast

Authority = Literal["INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"]
Consistency = Literal["EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"]


def _input() -> dict[str, Any]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict):
        raise TypeError("adapter input must be an object")
    return value


def _client() -> Any:
    from milai_client import MilaiClient

    return MilaiClient(
        base_url=os.environ["MILAI_BASE_URL"], token=os.environ["MILAI_AGENT_TOKEN"]
    )


def _scope(payload: dict[str, Any]) -> dict[str, Any]:
    if "scope" in payload:
        return dict(payload["scope"])
    value = json.loads(os.environ.get("MILAI_AGENT_SCOPE_JSON", "{}"))
    if not isinstance(value, dict):
        raise TypeError("MILAI_AGENT_SCOPE_JSON must be an object")
    return value


def _host_scope() -> dict[str, Any]:
    value = json.loads(os.environ.get("MILAI_AGENT_SCOPE_JSON", "{}"))
    if not isinstance(value, dict):
        raise TypeError("MILAI_AGENT_SCOPE_JSON must be an object")
    return value


def _host_authority() -> Authority:
    value = os.environ.get("MILAI_AGENT_REQUIRED_AUTHORITY", "INFORMATIONAL")
    if value not in {"INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"}:
        raise ValueError("unsupported host authority")
    return cast(Authority, value)


def _host_consistency() -> Consistency:
    value = os.environ.get("MILAI_AGENT_CONSISTENCY_FLOOR", "CANONICAL_REQUIRED")
    if value not in {"EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"}:
        raise ValueError("unsupported host consistency")
    return cast(Consistency, value)


def _host_limit() -> int:
    return int(os.environ.get("MILAI_AGENT_MAX_LIMIT", "5"))


def _authority(payload: dict[str, Any]) -> Authority:
    value = str(
        payload.get(
            "authority",
            os.environ.get("MILAI_AGENT_REQUIRED_AUTHORITY", "INFORMATIONAL"),
        )
    )
    if value not in {"INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"}:
        raise ValueError("unsupported authority")
    return cast(Authority, value)


def _consistency(payload: dict[str, Any]) -> Consistency:
    value = str(payload.get("consistency", "CANONICAL_REQUIRED"))
    if value not in {"EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"}:
        raise ValueError("unsupported consistency")
    return cast(Consistency, value)


def _recall_result(envelope: Any) -> dict[str, Any]:
    return {
        "status": envelope.status,
        "items": envelope.items,
        "open_issue_ids": envelope.issues,
        "trace_id": envelope.trace_id,
        "abstention_reason": envelope.abstention_reason,
        "degraded_components": envelope.degraded_components,
        "fallback_used": envelope.fallback_used,
    }


def _generic(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    from milai_client import (
        ContextRequest,
        ExactRecallRequest,
        ProposalDraft,
        RecallRequest,
    )

    client = _client()
    try:
        if action == "recall":
            if payload.get("claim_id"):
                envelope = client.recall_exact(
                    ExactRecallRequest(
                        claim_id=str(payload["claim_id"]),
                        scope=_scope(payload),
                        authority=_authority(payload),
                        consistency=_consistency(payload),
                    )
                )
            else:
                envelope = client.recall(
                    RecallRequest(
                        query=str(payload["query"]),
                        scope=_scope(payload),
                        authority=_authority(payload),
                        consistency=_consistency(payload),
                        limit=int(payload.get("limit", 5)),
                        causal_token=(
                            str(payload["causal_token"])
                            if payload.get("causal_token")
                            else None
                        ),
                    )
                )
            result = _recall_result(envelope)
            if envelope.trace_id and payload.get("include_trace", True):
                result["trace"] = client.get_trace(envelope.trace_id).raw
            if envelope.trace_id and payload.get("build_context"):
                context = client.build_context(
                    ContextRequest(
                        retrieval_trace_id=envelope.trace_id,
                        active_goal=str(payload.get("active_goal", "governed recall")),
                        constraints=tuple(
                            str(item) for item in payload.get("constraints", [])
                        ),
                    )
                )
                result["context"] = context.raw
            return result
        if action == "capture":
            return client.capture_evidence(
                dict(payload["evidence"]), operation_id=str(payload["operation_id"])
            ).raw
        if action == "proposal":
            draft = ProposalDraft.model_validate(payload["proposal"])
            if draft.target_claim_id is not None:
                draft.validate_current_head(
                    client.get_claim(draft.target_claim_id).claim_version_id
                )
            return client.create_proposal(
                draft,
                operation_id=str(payload["operation_id"]),
            ).raw
        if action == "causal":
            return client.issue_causal_token(
                [str(value) for value in payload["outbox_ids"]]
            ).raw
        raise ValueError(f"unknown generic action: {action}")
    finally:
        client.close()


class _GraphState(TypedDict, total=False):
    memory_query: str
    active_goal: str
    constraints: list[str]
    context_byte_budget: int
    thread_checkpoint: dict[str, Any]
    milai_recall_status: str
    milai_prompt_block: str
    milai_trace_id: str
    milai_open_issue_ids: list[str]
    milai_checkpoint_boundary: str
    milai_context_status: str
    milai_context_capsule_id: str
    milai_context_protected_sections: dict[str, Any]


def _langgraph(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    from langgraph.graph import END, START, StateGraph
    from milai_client import AgentMemory, AgentRecallPolicy, CapturePolicy
    from milai_langgraph import capture_node, context_node, recall_node

    client = _client()
    try:
        memory = AgentMemory(
            client,
            CapturePolicy(
                mode="ALLOWLISTED",
                allowed_tool_sources=frozenset({"ci", "runtime"}),
            ),
        )
        if action == "recall":
            graph = StateGraph(_GraphState)
            policy = AgentRecallPolicy(
                scope=_host_scope(),
                authority=_host_authority(),
                consistency_floor=_host_consistency(),
                max_limit=_host_limit(),
            )
            graph.add_node("recall", cast(Any, recall_node(memory, policy)))
            graph.add_node("context", cast(Any, context_node(memory)))
            graph.add_edge(START, "recall")
            graph.add_edge("recall", "context")
            graph.add_edge("context", END)
            checkpoint = {"framework_owned": True, "turn": payload.get("turn", 0)}
            result = graph.compile().invoke(
                {
                    "memory_query": str(payload["query"]),
                    "active_goal": str(payload.get("active_goal", "governed recall")),
                    "constraints": [
                        str(item) for item in payload.get("constraints", [])
                    ],
                    "thread_checkpoint": checkpoint,
                }
            )
            trace_id = str(result.get("milai_trace_id", ""))
            return {
                "status": result.get("milai_recall_status"),
                "trace_id": trace_id,
                "open_issue_ids": result.get("milai_open_issue_ids", []),
                "context_capsule_id": result.get("milai_context_capsule_id"),
                "protected_sections": result.get(
                    "milai_context_protected_sections", {}
                ),
                "checkpoint_boundary": result.get("milai_checkpoint_boundary"),
                "checkpoint_preserved": result.get("thread_checkpoint") == checkpoint,
                "trace": client.get_trace(trace_id).raw if trace_id else None,
            }
        if action == "capture":
            state = {
                "session_id": str(payload["session_id"]),
                "call_id": str(payload["turn_id"]),
                "tool_name": str(payload["tool_name"]),
                "subject_id": str(payload["subject_id"]),
                "observed_at": str(payload["observed_at"]),
                "verified_tool_observation": str(payload["content"]),
                "evidence_source_type": "RUNTIME_OBSERVATION",
                "capture_confirmed": True,
            }
            result = capture_node(memory)(state)
            capture = result.get("milai_capture")
            return {
                "milai_capture": (
                    asdict(cast(Any, capture)) if is_dataclass(capture) else capture
                ),
            }
        raise ValueError(f"unknown LangGraph action: {action}")
    finally:
        client.close()


async def _autogen_async(payload: dict[str, Any]) -> dict[str, Any]:
    from milai_autogen import MilaiMemory
    from milai_client import AgentRecallPolicy, AsyncMilaiClient

    client = AsyncMilaiClient(
        base_url=os.environ["MILAI_BASE_URL"], token=os.environ["MILAI_AGENT_TOKEN"]
    )
    memory = MilaiMemory(
        client,
        recall_policy=AgentRecallPolicy(
            scope=_host_scope(),
            authority=_host_authority(),
            consistency_floor=_host_consistency(),
            max_limit=_host_limit(),
        ),
    )
    try:
        result = await memory.query(str(payload["query"]))
        item = result.results[0]
        metadata = item.metadata or {}
        return {
            "content": item.content,
            "metadata": metadata,
            "data_only": metadata.get("trust") == "data-only",
        }
    finally:
        await memory.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--adapter", choices=("generic", "langgraph", "autogen"), required=True
    )
    parser.add_argument("--action", required=True)
    args = parser.parse_args()
    payload = _input()
    if args.adapter == "generic":
        result = _generic(args.action, payload)
    elif args.adapter == "langgraph":
        result = _langgraph(args.action, payload)
    else:
        if args.action != "recall":
            raise ValueError("AutoGen probe only exposes governed recall")
        result = asyncio.run(_autogen_async(payload))
    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
