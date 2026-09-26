"""Run frozen public diagnostic messages; evaluation rubric stays outside this module."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
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
from milai_lab.harness.contextual_artifacts import digest, read_json, write_json
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_foundation import BusinessActionJournal, native_business_tools


def _fixture_tools(case: dict[str, Any]) -> list[Any]:
    schemas = []
    functions = {}
    for definition in case["tools"]:
        schema = definition["schema"]
        name = schema["function"]["name"]
        schemas.append(schema)

        def execute(_world: Any, *, _result: Any = definition["result"], **_: Any) -> str:
            return json.dumps(_result, ensure_ascii=False)

        functions[name] = execute
    return native_business_tools(None, schemas, functions)


def run_frozen_diagnostics(
    inputs_path: Path,
    freeze_path: Path,
    output: Path,
    run_id: str,
    model: VLLMChatModel,
    store: BaseStore,
    checkpointer: BaseCheckpointSaver[str],
    config_identity: dict[str, Any],
    selected_cases: set[str] | None = None,
    arm_id: str = "b0",
    observer: ProvenanceObserver | None = None,
) -> dict[str, Any]:
    freeze = read_json(freeze_path)
    if hashlib.sha256(inputs_path.read_bytes()).hexdigest() != freeze["inputs_file_sha256"]:
        raise ValueError("DIAGNOSTIC_INPUT_IDENTITY_CHANGED")
    inputs = read_json(inputs_path)
    if len(inputs["cases"]) != freeze["cases"]:
        raise ValueError("DIAGNOSTIC_CASE_COUNT_CHANGED")
    available = {case["id"] for case in inputs["cases"]}
    if selected_cases and not selected_cases <= available:
        raise ValueError("DIAGNOSTIC_CASE_UNKNOWN")
    cases = [case for case in inputs["cases"]
             if selected_cases is None or case["id"] in selected_cases]
    output.mkdir(parents=True, exist_ok=True)
    identity = {
        "recipe_id": (model.m1.recipe_id if model.m1 is not None else
                      model.odr.recipe_id if model.odr is not None else
                      model.projection.recipe_id if model.projection is not None else RECIPE_ID),
        "run_id": run_id,
        "inputs_sha256": hashlib.sha256(inputs_path.read_bytes()).hexdigest(),
        "config_sha256": digest(config_identity),
        "rubric_read_by_runner": False,
    }
    if arm_id != "b0":
        identity["arm_id"] = arm_id
    identity_path = output / "run-identity.json"
    if identity_path.exists():
        if read_json(identity_path) != identity:
            raise ValueError("DIAGNOSTIC_RUN_IDENTITY_CHANGED")
    else:
        write_json(identity_path, identity)
    summaries = []
    for case in cases:
        case_path = output / case["id"]
        case_path.mkdir(parents=True, exist_ok=True)
        tools = _fixture_tools(case)
        journal = BusinessActionJournal(case_path / "business-journal.json",
                                        [item.name for item in tools])
        agent = build_agent(model, store, checkpointer, tools,
                            business_call_wrapper=journal, observer=observer)
        summary: dict[str, Any] = {"id": case["id"], "status": "RUNNING", "sessions": []}
        try:
            for declared in case["sessions"]:
                session_id = declared["id"]
                session_path = case_path / f"session-{session_id}.json"
                progress_path = case_path / f"session-{session_id}.progress.json"
                if session_path.exists():
                    summary["sessions"].append(read_json(session_path))
                    continue
                progress: dict[str, Any] = (read_json(progress_path) if progress_path.exists()
                                            else {"next_turn": 0, "pending_turn": None})
                write_json(progress_path, progress)
                scope = FoundationScope(run_id, arm_id, f"diagnostic:{case['id']}",
                                        f"session:{session_id}")
                messages: list[BaseMessage] = []
                for index in range(int(progress["next_turn"]), len(declared["turns"])):
                    pending = progress["pending_turn"] == index
                    progress["pending_turn"] = index
                    write_json(progress_path, progress)
                    messages = invoke_or_resume_public_message(
                        agent, model, scope, declared["turns"][index]["text"], index, pending,
                        task_id=f"diagnostic:{case['id']}",
                    )
                    progress["next_turn"] = index + 1
                    progress["pending_turn"] = None
                    write_json(progress_path, progress)
                if not messages:
                    messages = agent.get_state(scope.config()).values["messages"]
                namespace = ("langmem", run_id, arm_id, f"diagnostic:{case['id']}")
                row = {
                    "session_id": session_id,
                    "public_turn_count": len(declared["turns"]),
                    "messages": [message.model_dump(mode="json") for message in messages],
                    "business_calls": journal.calls_for_thread(
                        scope.config()["configurable"]["thread_id"]),
                    "memories": [item.dict() for item in store.search(namespace, limit=1000)],
                    "budget": copy.deepcopy(model.client.budget.state)
                    if model.client.budget else None,
                }
                if model.m1 is not None:
                    row["decision_basis"] = model.m1.store.get(
                        (run_id, arm_id, scope.user_id, f"diagnostic:{case['id']}"))
                write_json(session_path, row)
                summary["sessions"].append(row)
                if observer is not None:
                    observer.assert_healthy()
            summary["status"] = "TERMINAL"
        except Exception as error:
            summary.update({
                "status": ("INSTRUMENTATION_INCOMPLETE"
                           if isinstance(error, InstrumentationIncomplete) else "INTERRUPTED"),
                "error_type": type(error).__name__, "error": str(error),
            })
        write_json(case_path / "result.json", summary)
        summaries.append({"id": case["id"], "status": summary["status"],
                          "completed_sessions": len(summary["sessions"]),
                          "declared_sessions": len(case["sessions"])})
    result = {
        "status": "TERMINAL" if all(item["status"] == "TERMINAL" for item in summaries)
        else "TERMINAL_WITH_INTERRUPTED_CASES",
        "cases": summaries,
        "declared_case_count": len(cases),
        "inputs_sha256": identity["inputs_sha256"],
        "rubric_read_by_runner": False,
        "final_budget": copy.deepcopy(model.client.budget.state)
        if model.client.budget else None,
    }
    write_json(output / "result.json", result)
    return result
