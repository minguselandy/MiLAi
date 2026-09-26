"""One frozen, non-benchmark M1 mechanism fixture over the normal ReAct agent."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from langmem import create_manage_memory_tool  # type: ignore[import-untyped]

from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    FoundationScope,
    build_agent,
    invoke_or_resume_public_message,
)
from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.baselines.langmem_instrumentation import (
    InstrumentationIncomplete,
    ProvenanceObserver,
)
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_foundation import BusinessActionJournal, native_business_tools


def _fixture_memory_effect(
    stage: str, arguments: dict[str, Any], scope: FoundationScope,
    store: BaseStore, observer: ProvenanceObserver, output: Path,
    model: VLLMChatModel,
) -> dict[str, Any]:
    journal_path = output / "fixture-effects.json"
    entries = read_json(journal_path) if journal_path.exists() else {}
    prior = entries.get(stage)
    if prior is not None:
        if prior["status"] != "complete":
            raise ValueError("M1_FIXTURE_EFFECT_OUTCOME_UNKNOWN:" + stage)
        if prior["arguments"] != arguments:
            raise ValueError("M1_FIXTURE_EFFECT_ARGUMENTS_CHANGED")
        return cast(dict[str, Any], prior)
    call_key = hashlib.sha256(json.dumps(
        [scope.config()["configurable"]["thread_id"], "fixture", stage],
        ensure_ascii=False,
    ).encode()).hexdigest()
    entries[stage] = {"status": "pending", "arguments": arguments,
                      "origin": ("FIXTURE_CONTROLLED_SEED" if stage == "seed" else
                                 "FIXTURE_CONTROLLED_EXTERNAL_UPDATE" if
                                 stage == "external_update" else
                                 "FIXTURE_CONTROLLED_EXTERNAL_EFFECT")}
    write_json(journal_path, entries)
    tool = create_manage_memory_tool(namespace=MEMORY_NAMESPACE, store=store)
    result = observer.run_fixture_memory_tool(
        call_key, scope.config()["configurable"]["thread_id"], stage,
        arguments, lambda: str(tool.invoke(arguments, config=scope.config())),
    )
    entries[stage].update({"status": "complete", "result": result,
                           "call_key": call_key})
    if stage == "seed":
        memory_id = result.rsplit(" ", 1)[-1]
        entries[stage]["memory_id"] = str(uuid.UUID(memory_id))
    write_json(journal_path, entries)
    if model.client.emit is not None:
        model.client.emit({
            "event": "m1_fixture_memory_effect", "origin": entries[stage]["origin"],
            "stage": stage, "call_key": call_key, "arguments": arguments,
            "result": result, "provider_request": False,
        })
    return cast(dict[str, Any], entries[stage])


def run_mechanism(
    fixture_path: Path, freeze_path: Path, output: Path,
    run_id: str, arm_id: str, model: VLLMChatModel,
    store: BaseStore, checkpointer: BaseCheckpointSaver[str],
    observer: ProvenanceObserver,
) -> dict[str, Any]:
    """Use ordinary public messages; only the frozen external Store edit is driven."""
    freeze, fixture = read_json(freeze_path), read_json(fixture_path)
    if (sha256_file(fixture_path) != freeze["fixture_sha256"]
            or fixture["case_id"] != freeze["case_id"]
            or len(fixture["public_messages"]) != freeze["public_messages"]):
        raise ValueError("M1_MECHANISM_FIXTURE_CHANGED")
    output.mkdir(parents=True, exist_ok=True)
    identity_path = output / "run-identity.json"
    identity = {"run_id": run_id, "arm_id": arm_id,
                "fixture_sha256": sha256_file(fixture_path),
                "freeze_sha256": sha256_file(freeze_path),
                "recipe_id": model.m1.recipe_id if model.m1 is not None else "b1_control"}
    if identity_path.exists():
        if read_json(identity_path) != identity:
            raise ValueError("M1_MECHANISM_RUN_IDENTITY_CHANGED")
    else:
        write_json(identity_path, identity)
    scope = FoundationScope(run_id, arm_id, fixture["user_id"],
                            "mechanism:" + fixture["case_id"])
    world_path = output / "sim-world.json"

    def simulate(_world: Any, **arguments: Any) -> str:
        world = read_json(world_path) if world_path.exists() else {"records": []}
        world["records"].append(arguments)
        write_json(world_path, world)
        return json.dumps({"status": "recorded", "arguments": arguments},
                          ensure_ascii=False)

    schema = fixture["business_tool_schema"]
    name = schema["function"]["name"]
    business_tools = native_business_tools(None, [schema], {name: simulate})
    journal = BusinessActionJournal(output / "business-journal.json", [name])
    agent = build_agent(model, store, checkpointer, business_tools,
                        business_call_wrapper=journal, observer=observer)
    progress_path = output / "progress.json"
    progress = (read_json(progress_path) if progress_path.exists()
                else {"next_turn": 0, "pending_turn": None})
    write_json(progress_path, progress)
    messages: list[Any] = []
    try:
        seed = _fixture_memory_effect(
            "seed", {"action": "create", "content": fixture["seed_memory"]["content"]},
            scope, store, observer, output, model,
        )
        memory_id = seed["memory_id"]
        for index in range(cast(int, progress["next_turn"]), len(fixture["public_messages"])):
            if index > fixture["revision_update"]["after_public_index"]:
                _fixture_memory_effect(
                    "external_update",
                    {"action": "update", "id": memory_id,
                     "content": fixture["revision_update"]["content"]},
                    scope, store, observer, output, model,
                )
            pending = progress["pending_turn"] == index
            progress["pending_turn"] = index
            write_json(progress_path, progress)
            messages = invoke_or_resume_public_message(
                agent, model, scope, fixture["public_messages"][index],
                index, pending, task_id=fixture["task_id"],
            )
            progress["next_turn"] = index + 1
            progress["pending_turn"] = None
            write_json(progress_path, progress)
        if not messages:
            messages = agent.get_state(scope.config()).values["messages"]
        namespace = ("langmem", run_id, arm_id, fixture["user_id"])
        result = {
            "status": "TERMINAL", "kind": fixture["kind"],
            "benchmark_score": False,
            "public_message_count": len(fixture["public_messages"]),
            "messages": [message.model_dump(mode="json") for message in messages],
            "business_calls": journal.calls_for_thread(
                scope.config()["configurable"]["thread_id"]),
            "sim_world": read_json(world_path) if world_path.exists() else {"records": []},
            "memories": [item.dict() for item in store.search(namespace, limit=1000)],
            "decision_basis": model.m1.store.get(
                (run_id, arm_id, fixture["user_id"], fixture["task_id"]))
            if model.m1 is not None else None,
            "budget": copy.deepcopy(model.client.budget.state)
            if model.client.budget else None,
        }
        observer.assert_healthy()
        write_json(output / "result.json", result)
        return result
    except Exception as error:
        write_json(output / "interruption.json", {
            "status": ("INSTRUMENTATION_INCOMPLETE"
                       if isinstance(error, InstrumentationIncomplete)
                       else "INTERRUPTED_UNSCORED"),
            "public_message_index": progress["pending_turn"],
            "error_type": type(error).__name__, "error": str(error),
            "completed_messages": progress["next_turn"],
            "budget": copy.deepcopy(model.client.budget.state)
            if model.client.budget else None,
        })
        raise
