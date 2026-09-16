from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Any

from milai_client import (
    AgentMemory,
    AgentRecallPolicy,
    CapturePolicy,
    MemorySlot,
    MilaiClient,
    TokenBudget,
)

_HOST_POLICY_KEYS = frozenset(
    {
        "recall_scope",
        "required_authority",
        "consistency_floor",
        "max_limit",
        "budget_class",
        "context_byte_budget",
        "slot_ttl_seconds",
    }
)


def _input() -> dict[str, Any]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict):
        raise SystemExit("hook input must be a JSON object")
    return value


def _policy(payload: dict[str, Any]) -> AgentRecallPolicy:
    injected = sorted(_HOST_POLICY_KEYS.intersection(payload))
    if injected:
        raise PermissionError(
            "hook payload cannot override host recall/budget policy: " + ", ".join(injected)
        )
    try:
        raw_scope: object = json.loads(os.environ.get("MILAI_AGENT_SCOPE_JSON", "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError("MILAI_AGENT_SCOPE_JSON must be valid JSON") from exc
    if not isinstance(raw_scope, dict):
        raise ValueError("MILAI_AGENT_SCOPE_JSON must be a JSON object")
    authority = os.environ.get("MILAI_AGENT_REQUIRED_AUTHORITY", "ACTION_SAFE")
    consistency = os.environ.get("MILAI_AGENT_CONSISTENCY_FLOOR", "CANONICAL_REQUIRED")
    limit_value = os.environ.get("MILAI_AGENT_MAX_LIMIT", "3")
    return AgentRecallPolicy(
        scope=raw_scope,
        authority=authority,  # type: ignore[arg-type]
        consistency_floor=consistency,  # type: ignore[arg-type]
        max_limit=min(3, int(str(limit_value))),
    )


def _restore_slot(memory: AgentMemory, payload: dict[str, Any], session_id: str) -> None:
    raw = payload.get("memory_slot")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError("memory_slot must be a JSON object")
    memory.slot_registry.restore(session_id, MemorySlot.from_state(raw))


def _optimized_context(
    memory: AgentMemory,
    payload: dict[str, Any],
    *,
    active_goal_default: str | None = None,
) -> dict[str, Any]:
    injected = sorted(_HOST_POLICY_KEYS.intersection(payload))
    if injected:
        raise PermissionError(
            "hook payload cannot override host recall/budget policy: " + ", ".join(injected)
        )
    session_id = str(payload["session_id"])
    _restore_slot(memory, payload, session_id)
    constraints_value = payload.get("context_constraints", [])
    known_ids_value = payload.get("known_claim_ids", [])
    if not isinstance(constraints_value, list) or not all(
        isinstance(value, str) for value in constraints_value
    ):
        raise ValueError("context_constraints must be an array of strings")
    if not isinstance(known_ids_value, list) or not all(
        isinstance(value, str) for value in known_ids_value
    ):
        raise ValueError("known_claim_ids must be an array of strings")
    budget_class = os.environ.get("MILAI_AGENT_BUDGET_CLASS", "STANDARD")
    byte_budget = int(os.environ.get("MILAI_AGENT_CONTEXT_BYTE_BUDGET", "16384"))
    slot_ttl_seconds = int(os.environ.get("MILAI_AGENT_SLOT_TTL_SECONDS", "300"))
    prepared = memory.prepare_context(
        str(payload["query"]),
        session_id=session_id,
        recall_policy=_policy(payload),
        active_goal=(
            str(payload["active_goal"])
            if payload.get("active_goal") is not None
            else active_goal_default
        ),
        previous_goal_fingerprint=(
            str(payload["previous_goal_fingerprint"])
            if payload.get("previous_goal_fingerprint") is not None
            else None
        ),
        context_constraints=tuple(constraints_value),
        known_claim_ids=tuple(known_ids_value),
        token_budget=TokenBudget.for_class(
            budget_class,  # type: ignore[arg-type]
            max_bytes=byte_budget,
        ),
        context_byte_budget=byte_budget,
        slot_ttl_seconds=slot_ttl_seconds,
    )
    slot = prepared.compiled.slot
    return {
        "status": prepared.recall_envelope.status if prepared.recall_envelope else "SKIPPED",
        "route": prepared.routing.route,
        "reason_code": prepared.routing.reason_code,
        "delta": asdict(prepared.compiled.delta),
        "context": prepared.compiled.delta.rendered_context,
        "memory_slot": slot.to_state() if slot is not None else None,
        "metrics": asdict(prepared.compiled.metrics),
        "trace_id": (
            prepared.recall_envelope.trace_id if prepared.recall_envelope is not None else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="MiLAi coding-agent lifecycle hook")
    parser.add_argument(
        "event",
        choices=("SessionStart", "UserPrompt", "PostToolUse", "PreCompact", "Stop"),
    )
    args = parser.parse_args()
    payload = _input()
    client = MilaiClient()
    memory = AgentMemory(
        client,
        CapturePolicy(
            mode=str(payload.get("capture_mode", "OFF")),  # type: ignore[arg-type]
            allowed_user_sources=frozenset(payload.get("allowed_user_sources", [])),
            allowed_tool_sources=frozenset(payload.get("allowed_tools", [])),
        ),
    )
    try:
        if args.event == "SessionStart":
            result: object = memory.on_session_start(str(payload["session_id"]))
        elif args.event == "UserPrompt":
            result = _optimized_context(memory, payload)
        elif args.event == "PostToolUse":
            result = memory.after_tool_observation(
                session_id=str(payload["session_id"]),
                call_id=str(payload["call_id"]),
                tool_name=str(payload["tool_name"]),
                subject_id=str(payload["subject_id"]),
                content=str(payload["verified_observation"]),
                capture_confirmed=payload.get("capture_confirmed") is True,
                contains_credentials=payload.get("contains_credentials") is True,
                is_raw_log=payload.get("is_raw_log") is True,
                observed_at=(str(payload["observed_at"]) if payload.get("observed_at") else None),
            )
        elif args.event == "PreCompact":
            result = _optimized_context(
                memory,
                payload,
                active_goal_default="preserve governed memory before compaction",
            )
        else:
            result = memory.on_session_end(
                str(payload["session_id"]), subject_id=str(payload["subject_id"])
            )
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                default=lambda value: (
                    asdict(value)
                    if is_dataclass(value) and not isinstance(value, type)
                    else str(value)
                ),
            )
        )
    finally:
        client.close()
