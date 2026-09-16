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
    MilaiClientError,
    TokenBudget,
)

from milai_hooks.agent_event import (
    capture_host_agent_event,
    journal_sparse_host_agent_event,
    validate_host_event_binding,
)
from milai_hooks.reconciliation_orchestrator import (
    ReconciliationOrchestrationError,
    reconcile_working_state_explicit,
)
from milai_hooks.state_reconciliation import StateDeltaError

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
    authority = os.environ.get("MILAI_AGENT_REQUIRED_AUTHORITY", "ACTION_SAFE")
    consistency = os.environ.get("MILAI_AGENT_CONSISTENCY_FLOOR", "CANONICAL_REQUIRED")
    limit_value = os.environ.get("MILAI_AGENT_MAX_LIMIT", "3")
    return AgentRecallPolicy(
        scope=_host_scope(),
        authority=authority,  # type: ignore[arg-type]
        consistency_floor=consistency,  # type: ignore[arg-type]
        max_limit=min(3, int(str(limit_value))),
    )


def _host_scope() -> dict[str, Any]:
    try:
        raw_scope: object = json.loads(os.environ.get("MILAI_AGENT_SCOPE_JSON", "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError("MILAI_AGENT_SCOPE_JSON must be valid JSON") from exc
    if not isinstance(raw_scope, dict):
        raise ValueError("MILAI_AGENT_SCOPE_JSON must be a JSON object")
    return raw_scope


def _restore_slot(memory: AgentMemory, payload: dict[str, Any], session_id: str) -> None:
    raw = payload.get("memory_slot")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError("memory_slot must be a JSON object")
    memory.slot_registry.restore(session_id, MemorySlot.from_state(raw))


def _shadow_journal_binding(permission_snapshot: dict[str, Any]) -> dict[str, str] | None:
    mode = os.environ.get("MILAI_HOST_EVENT_JOURNAL", "OFF")
    if mode not in {"OFF", "SHADOW"}:
        raise ValueError("MILAI_HOST_EVENT_JOURNAL must be OFF or SHADOW")
    if mode == "OFF":
        return None
    return _host_task_binding(permission_snapshot)


def _host_task_binding(permission_snapshot: dict[str, Any]) -> dict[str, str]:
    project_id = os.environ.get("MILAI_HOST_PROJECT_ID", "")
    visible_projects = permission_snapshot.get("project_ids", [])
    if not isinstance(visible_projects, list) or project_id not in visible_projects:
        raise PermissionError("Host task project binding must be present in the Host scope")
    return validate_host_event_binding(
        principal_binding_digest=os.environ.get("MILAI_HOST_PRINCIPAL_BINDING_DIGEST", ""),
        project_id=project_id,
        task_ref=os.environ.get("MILAI_HOST_TASK_REF", ""),
    )


def _reconciliation_input(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "operation_id",
        "after_position",
        "expected_event_high_watermark",
        "event_limit",
        "delta",
    }
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise ReconciliationOrchestrationError(
            "INVALID_RECONCILIATION_REQUEST",
            "Reconciliation request contains unsupported fields: " + ", ".join(unexpected),
            "Pass only operation_id, optional after_position/event_limit, and delta; "
            "binding is Host-owned.",
        )
    delta = payload.get("delta")
    if not isinstance(delta, dict):
        raise ReconciliationOrchestrationError(
            "INVALID_DELTA",
            "Reconciliation delta must be a JSON object.",
            "Supply the complete Codex-produced StateDelta under the delta field.",
        )
    return {
        "operation_id": payload.get("operation_id"),
        "after_position": payload.get("after_position", 0),
        "expected_event_high_watermark": payload.get("expected_event_high_watermark"),
        "event_limit": payload.get("event_limit", 100),
        "raw_delta": delta,
    }


def _runtime_reconciliation_fix(error: MilaiClientError) -> str:
    if error.code == "STALE_WORKING_STATE":
        return "Reload the current TASK State and regenerate the Delta."
    if error.code == "EVIDENCE_REFERENCE_INVALID":
        return (
            "Reload the TASK State and Event Evidence, remove stale or unreadable Evidence refs, "
            "then regenerate the Delta."
        )
    if error.code == "OPERATION_CONFLICT":
        return (
            "Reuse this operation_id only for the identical reconciliation; use a new operation_id "
            "after changing its payload."
        )
    if error.retryable:
        return "Retry the identical request with the same operation_id."
    return "Correct the reported Runtime condition, then read a fresh State/Event window and retry."


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
        choices=(
            "SessionStart",
            "UserPrompt",
            "PostToolUse",
            "PreCompact",
            "Stop",
            "AgentEvent",
            "ReconcileState",
        ),
    )
    args = parser.parse_args()
    payload = _input()
    raw_max_retries = os.environ.get("MILAI_AGENT_MAX_RETRIES", "2")
    try:
        max_retries = int(raw_max_retries)
    except ValueError as exc:
        raise ValueError("MILAI_AGENT_MAX_RETRIES must be an integer") from exc
    if max_retries < 0:
        raise ValueError("MILAI_AGENT_MAX_RETRIES must be non-negative")
    client = MilaiClient(max_retries=max_retries)
    memory = AgentMemory(
        client,
        CapturePolicy(
            mode=str(payload.get("capture_mode", "OFF")),  # type: ignore[arg-type]
            allowed_user_sources=frozenset(payload.get("allowed_user_sources", [])),
            allowed_tool_sources=frozenset(payload.get("allowed_tools", [])),
        ),
    )
    result: object
    try:
        if args.event == "AgentEvent":
            if os.environ.get("MILAI_HOST_EVENT_CAPTURE") != "ON":
                raise PermissionError("Host AgentEvent capture is not enabled")
            permission_snapshot = _host_scope()
            permission_snapshot["readable"] = True
            data_classification = os.environ.get("MILAI_HOST_EVENT_DATA_CLASSIFICATION", "PERSONAL")
            if data_classification not in {"SYNTHETIC", "DEIDENTIFIED", "PERSONAL"}:
                raise ValueError("MILAI_HOST_EVENT_DATA_CLASSIFICATION is invalid")
            journal_binding = _shadow_journal_binding(permission_snapshot)
            captured = capture_host_agent_event(
                client,
                payload,
                permission_snapshot=permission_snapshot,
                data_classification=data_classification,  # type: ignore[arg-type]
            )
            if journal_binding is not None:
                raw_receipt = captured.get("receipt")
                evidence_id = (
                    raw_receipt.get("evidence_id") if isinstance(raw_receipt, dict) else None
                )
                if not isinstance(evidence_id, str) or not evidence_id:
                    captured["status"] = "PARTIAL_EVIDENCE_CAPTURED_JOURNAL_PENDING_RETRY"
                    captured["journal"] = {
                        "status": "PENDING_RETRY",
                        "reason_code": "INVALID_EVIDENCE_RECEIPT",
                        "event_retry_safe": True,
                    }
                else:
                    try:
                        captured["journal"] = journal_sparse_host_agent_event(
                            client,
                            payload,
                            evidence_id=evidence_id,
                            **journal_binding,
                        )
                    except MilaiClientError as exc:
                        captured["status"] = "PARTIAL_EVIDENCE_CAPTURED_JOURNAL_PENDING_RETRY"
                        captured["journal"] = {
                            "status": "PENDING_RETRY",
                            "reason_code": exc.code,
                            "runtime_retryable": exc.retryable,
                            "event_retry_safe": True,
                        }
            result = captured
        elif args.event == "ReconcileState":
            binding = _host_task_binding(_host_scope())
            reconciliation = _reconciliation_input(payload)
            result = reconcile_working_state_explicit(
                client,
                principal_binding_digest=binding["principal_binding_digest"],
                project_id=binding["project_id"],
                task_ref=binding["task_ref"],
                raw_delta=reconciliation["raw_delta"],
                operation_id=reconciliation["operation_id"],
                expected_event_high_watermark=reconciliation["expected_event_high_watermark"],
                after_position=reconciliation["after_position"],
                event_limit=reconciliation["event_limit"],
            )
        elif args.event == "SessionStart":
            result = memory.on_session_start(str(payload["session_id"]))
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
    except (ReconciliationOrchestrationError, StateDeltaError) as exc:
        print(
            json.dumps(
                {
                    "status": "REJECTED",
                    "error": {
                        "code": exc.code,
                        "problem": exc.problem,
                        "fix": exc.fix,
                    },
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from exc
    except MilaiClientError as exc:
        if args.event != "ReconcileState":
            raise
        print(
            json.dumps(
                {
                    "status": "REJECTED",
                    "error": {
                        "code": exc.code,
                        "problem": str(exc),
                        "fix": _runtime_reconciliation_fix(exc),
                        "runtime_retryable": exc.retryable,
                        "details": exc.details,
                    },
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from exc
    finally:
        client.close()
