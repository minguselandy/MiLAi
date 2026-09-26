"""Exposed MERIT arc on the fixed LangMem baseline, with native world and checker."""

from __future__ import annotations

import copy
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from milai_lab.baselines.langmem_agent import (
    RECIPE_ID,
    FoundationScope,
    build_agent,
    invoke_or_resume_public_message,
)
from milai_lab.baselines.langmem_instrumentation import (
    InstrumentationIncomplete,
    ProvenanceObserver,
)
from milai_lab.datasets.merit import load_exposed_arc
from milai_lab.harness.contextual_artifacts import digest, read_json, write_json
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_foundation import BusinessActionJournal, native_business_tools


def _world_for_run(arc: Any, path: Path) -> Any:
    world = arc.make_world()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with sqlite3.connect(path) as disk:
            world.conn.backup(disk)
    world.conn.close()
    # ToolNode dispatches even a single call on a worker thread. The graph's
    # max_concurrency=1 keeps this one connection sequential.
    world.conn = sqlite3.connect(path, check_same_thread=False)
    return world


def run_exposed_merit_arc(
    selection_path: Path,
    output: Path,
    run_id: str,
    model: VLLMChatModel,
    store: BaseStore,
    checkpointer: BaseCheckpointSaver[str],
    config_identity: dict[str, Any],
    arm_id: str = "b0",
    observer: ProvenanceObserver | None = None,
) -> dict[str, Any]:
    selection, arc, native_tools, metrics, native_runner = load_exposed_arc(selection_path)
    output.mkdir(parents=True, exist_ok=True)
    identity = {
        "recipe_id": model.m1.recipe_id if model.m1 is not None else RECIPE_ID,
        "run_id": run_id,
        "arc_id": arc.arc_id,
        "selection_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "config_sha256": digest(config_identity),
        "arc_sha256": selection["private_artifacts"]["arc_sha256"],
    }
    if arm_id != "b0":
        identity["arm_id"] = arm_id
    identity_path = output / "run-identity.json"
    if identity_path.exists():
        if read_json(identity_path) != identity:
            raise ValueError("MERIT_RUN_IDENTITY_CHANGED")
    else:
        write_json(identity_path, identity)
    world = _world_for_run(arc, output / "world.sqlite")
    business_tools = native_business_tools(world, native_tools.TOOL_SCHEMAS,
                                           native_tools.TOOL_FUNCS)
    journal = BusinessActionJournal(output / "business-journal.json",
                                    [item.name for item in business_tools])
    environment_rules = native_runner.SYSTEM_PROMPT.split("{memory_block}", 1)[0].strip()
    agent = build_agent(model, store, checkpointer, business_tools,
                        business_call_wrapper=journal, environment_rules=environment_rules,
                        observer=observer)
    rows: list[dict[str, Any]] = []
    try:
        for episode in arc.episodes:
            task = episode.task
            checker = getattr(metrics, task.checker)
            progress_path = output / "episodes" / f"episode-{episode.index}.progress.json"
            row_path = output / "episodes" / f"episode-{episode.index}.json"
            if row_path.exists():
                rows.append(read_json(row_path))
                continue
            if progress_path.exists():
                progress = read_json(progress_path)
            else:
                before = world.snapshot()
                progress = {
                    "before_world": before,
                    "pre_satisfied": bool(checker(before, **task.checker_args)),
                    "next_message": 0,
                    "pending_message": None,
                    "budget_before": copy.deepcopy(model.client.budget.state)
                    if model.client.budget else None,
                }
                write_json(progress_path, progress)
            scope = FoundationScope(run_id, arm_id, f"merit:{arc.arc_id}",
                                    f"episode:{episode.index}")
            messages: list[Any] = []
            for index in range(progress["next_message"], len(task.user_messages)):
                pending = progress["pending_message"] == index
                progress["pending_message"] = index
                write_json(progress_path, progress)
                messages = invoke_or_resume_public_message(
                    agent, model, scope, task.user_messages[index], index, pending,
                    task_id=task.task_id,
                )
                progress["next_message"] = index + 1
                progress["pending_message"] = None
                write_json(progress_path, progress)
            if not messages:
                messages = agent.get_state(scope.config()).values["messages"]
            after = world.snapshot()
            post_satisfied = bool(checker(after, **task.checker_args))
            calls = journal.calls_for_thread(scope.config()["configurable"]["thread_id"])
            native_calls = [
                {"name": entry["name"], "args": entry["args"],
                 "out": entry["result"]["content"], "call_id": entry["call_id"]}
                for entry in calls if entry["status"] == "complete"
            ]
            memory_text = "\n".join(str(message.content) for message in messages
                                    if isinstance(message, ToolMessage)
                                    and message.name == "search_memory")
            golds = task.golds()
            memory_had_fact = bool(task.dependent and golds and
                                   all(gold in memory_text for gold in golds))
            argument_value_match = bool(golds and metrics.memory_utilized(native_calls, golds))
            namespace = ("langmem", run_id, arm_id, f"merit:{arc.arc_id}")
            memories = [item.dict() for item in store.search(namespace, limit=1000)]
            row = {
                "episode_index": episode.index,
                "task_id": task.task_id,
                "kind": task.kind,
                "dependent": task.dependent,
                "public_message_count": len(task.user_messages),
                "before_world": progress["before_world"],
                "after_world": after,
                "messages": [item.model_dump(mode="json") for item in messages],
                "business_calls": calls,
                "memories": memories,
                "native_score": {
                    "pre_satisfied": progress["pre_satisfied"],
                    "checker_after": post_satisfied,
                    "success": not progress["pre_satisfied"] and post_satisfied,
                    "memory_had_fact": memory_had_fact,
                    "argument_value_match": argument_value_match,
                    "memory_utilized": memory_had_fact and argument_value_match,
                },
                "budget_before": progress["budget_before"],
                "budget_after": copy.deepcopy(model.client.budget.state)
                if model.client.budget else None,
            }
            if model.m1 is not None:
                row["decision_basis"] = model.m1.store.get(
                    (run_id, arm_id, scope.user_id, task.task_id))
            write_json(row_path, row)
            rows.append(row)
            if observer is not None:
                observer.assert_healthy()
        result = {
            "arc_id": arc.arc_id,
            "native_denominator": selection["episode_count"],
            "dependent_denominator": selection["dependent_episode_count"],
            "native_successes": sum(row["native_score"]["success"] for row in rows),
            "dependent_successes": sum(row["native_score"]["success"]
                                       for row in rows if row["dependent"]),
            "episodes": [{"episode_index": row["episode_index"],
                          "success": row["native_score"]["success"],
                          "dependent": row["dependent"]} for row in rows],
            "final_budget": copy.deepcopy(model.client.budget.state)
            if model.client.budget else None,
        }
        write_json(output / "result.json", result)
        return result
    except Exception as error:
        write_json(output / "interruption.json", {
            "status": ("INSTRUMENTATION_INCOMPLETE"
                       if isinstance(error, InstrumentationIncomplete)
                       else "INTERRUPTED_UNSCORED"),
            "episode_index": episode.index,
            "public_message_index": progress.get("pending_message"),
            "error_type": type(error).__name__,
            "error": str(error),
            "completed_episodes": len(rows),
            "original_denominator": selection["episode_count"],
            "budget": copy.deepcopy(model.client.budget.state)
            if model.client.budget else None,
        })
        raise
    finally:
        world.conn.close()
