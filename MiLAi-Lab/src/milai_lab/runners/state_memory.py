"""Shared policy assembly for STATE tasks and their frozen retrieval branches."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.embeddings import Embeddings

from milai_lab.harness.contextual_artifacts import RunBudget
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    FixedMemoryPolicy,
    MemoryPolicy,
    PursuitMemoryPolicy,
)
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.runners.memory_control import memory_policy


def dependency_generator(
    host: VLLMChatModel, settings: dict[str, Any], record: Callable[[dict[str, Any]], None],
) -> Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]:
    """Use the same generation wire, capacity and public-message gate in both runners."""
    def generate(stage: str, messages: list[dict[str, str]],
                 schema: dict[str, Any]) -> dict[str, Any]:
        response = host.invoke(messages, tools=[], tool_choice="none",
            response_format={"type": "json_schema", "json_schema": {
                "name": "dependency_reads", "schema": schema}},
            **({"enable_thinking": settings["stage_enable_thinking"][stage]}
               if stage in settings.get("stage_enable_thinking", {}) else {}))
        if not isinstance(response.content, str):
            raise ValueError("STATE_DEPENDENCY_RESPONSE_MISSING")
        value = parse_object(response.content, reject_duplicate_keys=True)
        record({"event": "state_dependency_read_envelope", "generation_stage": stage,
                "envelope": value})
        return value

    return generate


def policy_and_pool(control: dict[str, Any], policy_name: str, budget: RunBudget,
                    record: Callable[[dict[str, Any]], None], embeddings: Embeddings | None,
                    call: Callable[[str, list[dict[str, str]], dict[str, Any]],
                                   dict[str, Any]] | None,
                    admit: Callable[[], None]) -> tuple[
                        MemoryPolicy,
                        Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]] | None]:
    """One policy factory for dynamic and prebuilt read-only artifacts."""
    reads = control.get("reads", 4)
    rank_pool = None
    policy: MemoryPolicy
    if policy_name == "mempursuit":
        from milai_lab.baselines.mempursuit import MemPursuitPool

        if embeddings is None:
            raise ValueError("STATE_MEMPURSUIT_REQUIRES_METERED_EMBEDDINGS")
        rank_pool = MemPursuitPool(embeddings, budget, selected_limit=reads,
            adaptive=control.get("pursuit_adaptive", True), record=record)
        policy = PursuitMemoryPolicy()
    elif policy_name in {"fixed_context", "fixed"}:
        factories: dict[str, Callable[[int], MemoryPolicy]] = {
            "fixed_context": FixedContextMemoryPolicy, "fixed": FixedMemoryPolicy}
        policy = factories[policy_name](reads)
    else:
        assert call is not None
        policy = memory_policy({**control, "policy": policy_name}, budget,
                               call=call, admit=admit, record=record)
    return policy, rank_pool


def build_retrieval(service: MemoryService, token_count: Callable[[str], int],
                    settings: dict[str, Any], policy_name: str, budget: RunBudget,
                    record: Callable[[dict[str, Any]], None], *,
                    embeddings: Embeddings | None = None,
                    call: Callable[[str, list[dict[str, str]], dict[str, Any]],
                                   dict[str, Any]] | None = None,
                    admit: Callable[[], None] = lambda: None,
                    available: Callable[[], bool] = lambda: True) -> IntentRetrievalMemory:
    """Use existing policies, View generation and metering in the local dynamic hook."""
    control = settings.get("memory_control", {})
    policy, rank_pool = policy_and_pool(
        control, policy_name, budget, record, embeddings, call, admit)
    return IntentRetrievalMemory(service, token_count,
        material_limit=settings["ordinary_material_tokens"],
        read_limit=settings["additional_reads"], source_access="independent_v1",
        source_tokenization="unicode_v1", evidence_policy="question_pack_v1",
        source_top_k=settings["source_top_k"], semantic_top_k=settings["semantic_top_k"],
        control_policy=policy, control_steps=control.get("max_control_steps", 8),
        control_rank_pool=rank_pool, control_delivery_selection=True, control_record=record,
        dependency_read_call=call, control_available=available,
        control_source_observation_tokens=control.get("source_observation_tokens"),
        control_view_capacity=control.get("view_capacity", 1),
        control_view_policy=control.get("view_policy", "incremental"),
        control_view_builder=control.get("view_builder", "generated"),
        control_internal_views=control.get("internal_views", True))

