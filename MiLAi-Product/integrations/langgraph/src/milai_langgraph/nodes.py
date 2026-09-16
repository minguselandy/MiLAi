from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, cast

from milai_client import (
    AgentMemory,
    AgentRecallPolicy,
    ContextRequest,
    ProposalDraft,
    TokenBudget,
    TokenCounter,
    goal_fingerprint,
)

State = Mapping[str, Any]
StateUpdate = dict[str, Any]
_MODEL_POLICY_KEYS = {
    "memory_scope",
    "memory_authority",
    "memory_consistency",
    "memory_limit",
    "memory_token_budget",
    "memory_tokenizer",
    "memory_cache_validated",
    "memory_tool_profile",
}


def recall_node(
    memory: AgentMemory,
    policy: AgentRecallPolicy,
    *,
    token_counter: TokenCounter | None = None,
    token_budget: TokenBudget | None = None,
) -> Callable[[State], StateUpdate]:
    def run(state: State) -> StateUpdate:
        injected = sorted(_MODEL_POLICY_KEYS.intersection(state))
        if injected:
            raise PermissionError(
                "LangGraph state cannot override host recall policy: " + ", ".join(injected)
            )
        constraints = state.get("constraints", [])
        if not isinstance(constraints, list) or not all(
            isinstance(item, str) for item in constraints
        ):
            raise ValueError("constraints must be a list of strings")
        active_goal = state.get("active_goal")
        if active_goal is not None and not isinstance(active_goal, str):
            raise ValueError("active_goal must be a string")
        known_claim_ids = state.get("known_milai_claim_ids", [])
        if not isinstance(known_claim_ids, list) or not all(
            isinstance(item, str) for item in known_claim_ids
        ):
            raise ValueError("known_milai_claim_ids must be a list of strings")
        prepared = memory.prepare_context(
            str(state.get("memory_query", "")),
            session_id=str(state.get("session_id", state.get("thread_id", "langgraph-default"))),
            recall_policy=policy,
            active_goal=active_goal,
            previous_goal_fingerprint=(
                str(state["milai_active_goal_fingerprint"])
                if state.get("milai_active_goal_fingerprint") is not None
                else None
            ),
            context_constraints=tuple(constraints),
            known_claim_ids=tuple(known_claim_ids),
            token_counter=token_counter,
            token_budget=token_budget,
        )
        envelope = prepared.recall_envelope
        compiled = prepared.compiled
        result: StateUpdate = {
            "milai_recall_route": prepared.routing.route,
            "milai_recall_reason": prepared.routing.reason_code,
            "milai_recall_status": envelope.status if envelope is not None else "SKIPPED",
            "milai_trace_id": envelope.trace_id if envelope is not None else None,
            "milai_open_issue_ids": envelope.issues if envelope is not None else [],
            "milai_checkpoint_boundary": "REFERENCES_ONLY",
            "milai_context_delta_status": compiled.delta.status,
            "milai_snapshot_id": compiled.delta.snapshot_id,
            "milai_slot_hash": compiled.slot.content_hash if compiled.slot is not None else None,
            "milai_canonical_position_seen": (
                compiled.slot.canonical_position if compiled.slot is not None else None
            ),
            "milai_live_issue_revision_digest": (
                compiled.slot.live_issue_revision_digest if compiled.slot is not None else None
            ),
            "milai_active_goal_fingerprint": goal_fingerprint(active_goal),
            "milai_memory_tokens": compiled.metrics.actual_tokens,
            "milai_memory_bytes": compiled.metrics.actual_bytes,
            "milai_token_budget_verified": compiled.metrics.token_budget_verified,
        }
        if envelope is not None and envelope.context_capsule_id is not None:
            result["milai_context_capsule_id"] = envelope.context_capsule_id
            result["milai_context_status"] = "CREATED"
        if compiled.delta.status == "REPLACE":
            result["milai_prompt_block"] = compiled.delta.rendered_context or ""
        elif compiled.delta.status == "REMOVE":
            result["milai_prompt_block"] = ""
        return result

    return run


def context_node(memory: AgentMemory) -> Callable[[State], StateUpdate]:
    def run(state: State) -> StateUpdate:
        trace_id = state.get("milai_trace_id")
        active_goal = state.get("active_goal")
        if not isinstance(trace_id, str) or not trace_id:
            return {"milai_context_status": "SKIPPED_NO_TRACE"}
        if not isinstance(active_goal, str) or not active_goal:
            return {"milai_context_status": "SKIPPED_NO_ACTIVE_GOAL"}
        constraints = state.get("constraints", [])
        if not isinstance(constraints, list) or not all(
            isinstance(item, str) for item in constraints
        ):
            raise ValueError("constraints must be a list of strings")
        context = memory.client.build_context(
            ContextRequest(
                retrieval_trace_id=trace_id,
                active_goal=active_goal,
                constraints=tuple(constraints),
                byte_budget=int(state.get("context_byte_budget", 16_384)),
            )
        )
        return {
            "milai_context_status": "CREATED",
            "milai_context_capsule_id": context.capsule_id,
            "milai_context_protected_sections": context.protected_sections,
        }

    return run


def capture_node(memory: AgentMemory) -> Callable[[State], StateUpdate]:
    def run(state: State) -> StateUpdate:
        tool_observation = state.get("verified_tool_observation")
        if isinstance(tool_observation, str) and tool_observation:
            source_type = str(state.get("evidence_source_type", "TOOL_OBSERVATION"))
            if source_type not in {"TOOL_OBSERVATION", "RUNTIME_OBSERVATION"}:
                raise ValueError("evidence_source_type is not enabled for a tool observation")
            outcome = memory.after_tool_observation(
                session_id=str(state["session_id"]),
                call_id=str(state["call_id"]),
                tool_name=str(state["tool_name"]),
                subject_id=str(state["subject_id"]),
                content=tool_observation,
                observed_at=(str(state["observed_at"]) if state.get("observed_at") else None),
                capture_confirmed=state.get("capture_confirmed") is True,
                contains_credentials=state.get("contains_credentials") is True,
                is_raw_log=state.get("is_raw_log") is True,
                source_type=cast(Literal["TOOL_OBSERVATION", "RUNTIME_OBSERVATION"], source_type),
                source_context=(
                    cast(Mapping[str, Any], state["evidence_source_context"])
                    if isinstance(state.get("evidence_source_context"), Mapping)
                    else None
                ),
            )
            return {"milai_capture": outcome}
        observation = state.get("verified_user_observation")
        if not isinstance(observation, str) or not observation:
            return {"milai_capture": "SKIPPED"}
        outcome = memory.after_user_observation(
            session_id=str(state["session_id"]),
            turn_id=str(state["turn_id"]),
            subject_id=str(state["subject_id"]),
            content=observation,
            observed_at=(str(state["observed_at"]) if state.get("observed_at") else None),
            capture_confirmed=state.get("capture_confirmed") is True,
            contains_credentials=state.get("contains_credentials") is True,
            is_full_prompt=state.get("is_full_prompt") is True,
            source_context=(
                cast(Mapping[str, Any], state["evidence_source_context"])
                if isinstance(state.get("evidence_source_context"), Mapping)
                else None
            ),
        )
        return {"milai_capture": outcome}

    return run


def prepare_proposal_node(memory: AgentMemory) -> Callable[[State], StateUpdate]:
    def run(state: State) -> StateUpdate:
        candidate = state.get("proposal_candidate")
        if not isinstance(candidate, dict):
            return {"milai_proposal": "SKIPPED"}
        draft = ProposalDraft.model_validate(candidate)
        result = memory.create_proposal(
            draft,
            session_id=str(state["session_id"]),
            candidate_id=str(state["candidate_id"]),
        )
        return {"milai_proposal": result, "human_review_required": True}

    return run


def human_review_interrupt(state: State) -> StateUpdate:
    """Checkpoint boundary: host must interrupt; this node never reviews a Proposal."""
    if state.get("human_review_required"):
        return {"workflow_status": "INTERRUPT_FOR_INDEPENDENT_STEWARD"}
    return {"workflow_status": "NO_REVIEW_PENDING"}
