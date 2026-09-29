"""A small durable application workload over the ordinary LangMem agent."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

from langchain_core.messages import AIMessage, ToolMessage
from langmem import create_manage_memory_tool  # type: ignore[import-untyped]

from milai_lab.application.journal import BusinessActionJournal as BusinessActionJournal
from milai_lab.application.journal import UnknownBusinessAction as UnknownBusinessAction
from milai_lab.application.recovery import (
    recover_pending_application_call as recover_pending_application_call,
)
from milai_lab.application.tools import (
    BUSINESS_NAMES as BUSINESS_NAMES,
)
from milai_lab.application.tools import (
    BUSINESS_SCHEMAS as BUSINESS_SCHEMAS,
)
from milai_lab.application.tools import (
    _business_tools as _business_tools,
)
from milai_lab.application.tools import (
    native_business_tools as native_business_tools,
)
from milai_lab.application.world import ApplicationWorld as ApplicationWorld
from milai_lab.application.world import uuid as uuid
from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    build_agent,
    invoke_or_resume_public_message,
)
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import LocalStateController
from milai_lab.methods.local_state_attention.history import HistoryAccess
from milai_lab.methods.local_state_attention.integration import collect_observations
from milai_lab.methods.local_state_attention.summary import HistorySummaryController
from milai_lab.runners.langmem_application_runtime import ApplicationRuntime
from milai_lab.runners.writer_policy import (
    WRITER_POLICY_INSTRUCTIONS as WRITER_POLICY_INSTRUCTIONS,
)
from milai_lab.runners.writer_policy import (
    WriterPolicy as WriterPolicy,
)
from milai_lab.runners.writer_policy import (
    run_writer_policy_turn as run_writer_policy_turn,
)


def _operator_memory_event(event: dict[str, Any], run_id: str, arm_id: str,
                           root: Path, runtime: ApplicationRuntime) -> None:
    path = root / "operator-memory.json"
    ledger = read_json(path) if path.exists() else {"events": {}, "aliases": {}}
    event_id, user_id, alias = event["event_id"], event["user_id"], event["alias"]
    prior = ledger["events"].get(event_id)
    if prior is not None:
        if prior["input"] != event or prior["status"] != "complete":
            raise ValueError("APPLICATION_OPERATOR_OUTCOME_UNKNOWN_OR_CHANGED")
        return
    if event["action"] not in {"create", "update", "delete"}:
        raise ValueError("APPLICATION_OPERATOR_ACTION_UNKNOWN")
    aliases = ledger["aliases"].setdefault(user_id, {})
    if event["action"] == "create":
        if alias in aliases:
            raise ValueError("APPLICATION_OPERATOR_ALIAS_EXISTS")
        arguments = {"action": "create", "content": event["content"]}
    else:
        if alias not in aliases or aliases[alias]["deleted"]:
            raise ValueError("APPLICATION_OPERATOR_ALIAS_MISSING")
        arguments = {"action": event["action"], "id": aliases[alias]["id"]}
        if event["action"] == "update":
            arguments["content"] = event["content"]
    ledger["events"][event_id] = {"input": event, "status": "pending",
                                   "arguments": arguments}
    write_json(path, ledger)
    scope = FoundationScope(run_id, arm_id, user_id, "operator")
    tool = create_manage_memory_tool(namespace=MEMORY_NAMESPACE, store=runtime.store)
    call_key = hashlib.sha256(json.dumps([run_id, arm_id, user_id, event_id],
                                        ensure_ascii=False).encode()).hexdigest()
    result = runtime.observer.run_external_memory_tool(
        call_key, scope.config()["configurable"]["thread_id"], event_id, arguments,
        lambda: str(tool.invoke(arguments, config=scope.config())), origin="operator")
    if event["action"] == "create":
        aliases[alias] = {"id": str(uuid.UUID(result.rsplit(" ", 1)[-1])),
                          "deleted": False}
    elif event["action"] == "delete":
        aliases[alias]["deleted"] = True
    ledger["events"][event_id].update({"status": "complete", "result": result})
    write_json(path, ledger)


def _collect_turn_tail(agent: Any, scope: FoundationScope,
                       controller: LocalStateController, public_index: int,
                       *, close: bool) -> dict[str, Any] | None:
    epoch_scope = StateScope(scope.run_id, scope.arm_id, scope.user_id)
    thread_id = str(scope.config()["configurable"]["thread_id"])
    message_key = f"{thread_id}:{public_index}"
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    checkpoint = agent.get_state(scope.config())
    actual = checkpoint.values.get("messages", []) if checkpoint.values else []
    elapsed = {"wall_ns": time.perf_counter_ns() - start_wall,
               "cpu_ns": time.process_time_ns() - start_cpu}
    latest, _, source_ids = collect_observations(
        controller.bank, epoch_scope, thread_id, actual)
    if controller.emit is not None:
        controller.emit({
            "event": "lsa_epoch_checkpoint_read", "message_key": message_key,
            "user_id": scope.user_id, "message_count": len(actual),
            "source_count": len(source_ids),
            "logical_bytes": controller.bank._bytes(
                [item.model_dump(mode="json") for item in actual]), **elapsed})
    if not close:
        return None
    pending = controller.bank.pending(epoch_scope) if latest is None else []
    close_source_id = (latest[0] if latest is not None else
                       pending[-1]["id"] if pending else None)
    if close_source_id is None:
        return {"status": "NO_CHECKPOINT_SOURCE", "degraded": False,
                "pending_event_ids": []}
    result = controller.close_turn(epoch_scope, close_source_id, message_key)
    if controller.emit is not None:
        controller.emit({
            "event": "lsa_turn_close", "message_key": message_key,
            "user_id": scope.user_id, "degraded": result["degraded"],
            "reason": result.get("reason"), "receipts": result["receipts"],
            "pending_event_ids": result["pending_event_ids"]})
    return {"status": "DEGRADED" if result["degraded"] else "APPLIED",
            "degraded": result["degraded"], "reason": result.get("reason"),
            "receipts": result["receipts"],
            "pending_event_ids": result["pending_event_ids"]}




def run_phase(script: dict[str, Any], root: Path, run_id: str, arm_id: str,
              phase_id: int, runtime: ApplicationRuntime,
              local_state_controller: LocalStateController | None = None,
              local_state_read_policy: str = "focus",
              source_view_max_bytes: int | None = None,
              history_mode: str | None = None,
              history_page_max_bytes: int | None = None,
              history_summary_controller: HistorySummaryController | None = None,
              local_state_update_epoch: str = "pre_model",
              memory_contract: Literal["native", "strict"] = "native",
              agent_factory: Callable[..., Any] | None = None,
              public_turn_callback: Callable[..., None] | None = None,
              capture_interrupted_turn: bool = False,
              trusted_business_contracts: dict[str, dict[str, Any]] | None = None,
              business_response_hook: Callable[[dict[str, Any], ToolMessage], None] | None = None,
              ) -> dict[str, Any]:
    """Run one frozen phase; the next invocation reopens every process-owned resource."""
    phase = script["phases"][phase_id]
    if phase["id"] != phase_id:
        raise ValueError("APPLICATION_PHASE_ID_CHANGED")
    progress_path = root / "phase-progress.json"
    progress: dict[str, Any] = (read_json(progress_path) if progress_path.exists() else
                                {"next_phase": 0, "next_indices": {},
                                 "pending_message": None, "messages": {},
                                 "blocked_sessions": []})
    result_path = root / f"phase-{phase_id}-result.json"
    if phase_id < progress["next_phase"]:
        return cast(dict[str, Any], read_json(result_path))
    if phase_id != progress["next_phase"]:
        raise ValueError("APPLICATION_PHASE_OUT_OF_ORDER")
    if history_mode not in {None, "full", "tool", "window"}:
        raise ValueError("APPLICATION_HISTORY_MODE_INVALID")
    if type(memory_contract) is not str or memory_contract not in {"native", "strict"}:
        raise ValueError("LANGMEM_MEMORY_CONTRACT_UNKNOWN")
    if business_response_hook is not None and trusted_business_contracts is None:
        raise ValueError("APPLICATION_RESPONSE_HOOK_REQUIRES_PROTECTION")
    if (history_mode == "window") != (history_summary_controller is not None):
        raise ValueError("APPLICATION_HISTORY_SUMMARY_MISMATCH")
    if agent_factory is not None and (history_mode is not None
                                     or local_state_controller is not None):
        raise ValueError("APPLICATION_AGENT_FACTORY_METHOD_CONFLICT")
    if local_state_update_epoch not in {"pre_model", "turn_end"}:
        raise ValueError("LSA_UPDATE_EPOCH_UNKNOWN")
    if local_state_update_epoch == "turn_end" and (
        local_state_controller is None or local_state_read_policy not in {"all", "all_sources"}
        or local_state_controller.update_policy != "all"
    ):
        raise ValueError("LSA_TURN_END_COMBINATION_UNSUPPORTED")
    world = ApplicationWorld(root / "business-world.sqlite",
                             script["initial_label_available"])
    history_bank = (local_state_controller.bank if local_state_controller is not None else
                    LocalStateBank(runtime.store)) if history_mode is not None else None
    try:
        for event in phase["operator_memory"]:
            _operator_memory_event(event, run_id, arm_id, root, runtime)
        for event in phase["world_events"]:
            if event["action"] != "set_label_available":
                raise ValueError("APPLICATION_WORLD_ACTION_UNKNOWN")
            world.set_label_available(event["event_id"], event["available"])
        journal = BusinessActionJournal(
            root / "business-journal.json", BUSINESS_NAMES,
            application_protection=trusted_business_contracts is not None,
            response_hook=business_response_hook)
        def capture_interruption(error: BaseException, agent: Any, scope: FoundationScope,
                                 public_index: int) -> None:
            if not capture_interrupted_turn or public_turn_callback is None:
                return
            emit = runtime.model.client.emit
            try:
                if emit is not None:
                    emit({"event": "public_turn_interrupted", "error_type": type(error).__name__,
                          "thread_id": scope.config()["configurable"]["thread_id"],
                          "public_index": public_index})
                public_turn_callback(agent, scope, public_index, "INTERRUPTED_UNKNOWN",
                                     journal.calls_for_thread(
                                         scope.config()["configurable"]["thread_id"]))
            except Exception as audit_error:
                error.add_note("Interrupted-turn audit failed: " + type(audit_error).__name__)
                if emit is not None:
                    try:
                        emit({"event": "public_turn_audit_failed",
                              "primary_error_type": type(error).__name__,
                              "audit_error_type": type(audit_error).__name__})
                    except Exception as trace_error:
                        error.add_note("Audit-error trace failed: " + type(trace_error).__name__)
        agents: dict[str, Any] = {}
        for message in phase["messages"]:
            message_id, user_id = message["message_id"], message["user_id"]
            if message_id in progress["messages"]:
                continue
            session = message["session_id"]
            session_key = user_id + ":" + session
            public_index = progress["next_indices"].get(session_key, 0)
            if message["public_index"] != public_index:
                raise ValueError("APPLICATION_PUBLIC_INDEX_CHANGED")
            if session_key in progress["blocked_sessions"]:
                progress["messages"][message_id] = {
                    "message_id": message_id, "user_id": user_id,
                    "session_id": session, "public_index": public_index,
                    "status": "SKIPPED_AFTER_LOCAL_CAPACITY"}
                progress["next_indices"][session_key] = public_index + 1
                write_json(progress_path, progress)
                continue
            if progress["pending_message"] not in (None, message_id):
                raise ValueError("APPLICATION_PENDING_MESSAGE_CHANGED")
            scope = FoundationScope(run_id, arm_id, user_id, "application:" + session)
            if trusted_business_contracts is not None:
                binding = trusted_business_contracts.get(message_id)
                journal.binding = None
                if binding is not None:
                    expected = {"run_id": run_id, "arm_id": arm_id, "owner": user_id,
                                "thread_id": scope.config()["configurable"]["thread_id"],
                                "public_index": public_index, "message_id": message_id}
                    if any(binding.get(field) != value for field, value in expected.items()):
                        raise ValueError("APPLICATION_PUBLIC_REQUEST_BINDING_CHANGED")
                    journal.bind_request(binding)
            agent = agents.get(user_id)
            if agent is None and agent_factory is not None:
                agent = agent_factory(
                    runtime.model, runtime.store, runtime.checkpointer,
                    _business_tools(world, user_id), user_id=user_id,
                    business_call_wrapper=journal, observer=runtime.observer)
                agents[user_id] = agent
            if agent is None:
                history = None
                if history_mode is not None:
                    assert history_bank is not None and history_page_max_bytes is not None

                    def checkpoint_for(old_session: str, owner: str = user_id) -> Any:
                        return agents[owner].get_state(FoundationScope(
                            run_id, arm_id, owner, "application:" + old_session).config())

                    def thread_id_for(old_session: str, owner: str = user_id) -> str:
                        return str(FoundationScope(
                            run_id, arm_id, owner, "application:" + old_session
                        ).config()["configurable"]["thread_id"])

                    history = HistoryAccess(
                        root, StateScope(run_id, arm_id, user_id), history_bank,
                        get_state=checkpoint_for,
                        thread_id_for_session=thread_id_for,
                        page_max_bytes=history_page_max_bytes,
                        emit=runtime.model.client.emit)
                agent = build_agent(runtime.model, runtime.store, runtime.checkpointer,
                                    _business_tools(world, user_id),
                                    business_call_wrapper=journal,
                                    observer=runtime.observer,
                                    local_state_controller=local_state_controller,
                                    local_state_read_policy=local_state_read_policy,
                                    source_view_max_bytes=source_view_max_bytes,
                                    local_state_update_epoch=local_state_update_epoch,
                                    history_access=history,
                                    full_history=history_mode == "full",
                                    history_summary_controller=(
                                        history_summary_controller
                                        if history_mode == "window" else None),
                                    memory_contract=memory_contract)
                agents[user_id] = agent
            pending = progress["pending_message"] == message_id
            progress["pending_message"] = message_id
            write_json(progress_path, progress)
            epoch_scope = StateScope(run_id, arm_id, user_id)
            thread_id = str(scope.config()["configurable"]["thread_id"])
            message_key = f"{thread_id}:{public_index}"
            if local_state_update_epoch == "turn_end":
                assert local_state_controller is not None
                snapshot = local_state_controller.bank.epoch_snapshot(
                    epoch_scope, thread_id, public_index, create=True)
                if local_state_controller.emit is not None:
                    local_state_controller.emit({
                        "event": "lsa_epoch_snapshot", "message_key": message_key,
                        "user_id": user_id, "reused": snapshot["reused"],
                        "state_ids": [row["id"] for row in snapshot["states"]],
                        "body_bytes": local_state_controller.bank._bytes(snapshot["states"])})

            try:
                if pending and trusted_business_contracts is not None:
                    recover_pending_application_call(agent, scope, journal, world, runtime)
                messages = invoke_or_resume_public_message(
                    agent, runtime.model, scope, message["text"], public_index, pending)
            except ValueError as error:
                if str(error) != "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED":
                    if local_state_update_epoch == "turn_end":
                        assert local_state_controller is not None
                        _collect_turn_tail(agent, scope, local_state_controller,
                                           public_index, close=False)
                    capture_interruption(error, agent, scope, public_index)
                    raise
                close_result = (_collect_turn_tail(agent, scope, local_state_controller,
                                                   public_index, close=True)
                                if local_state_controller is not None
                                and local_state_update_epoch == "turn_end" else None)
                progress["messages"][message_id] = {
                    "message_id": message_id, "user_id": user_id,
                    "session_id": session, "public_index": public_index,
                    "status": "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED",
                    "business_calls": journal.calls_for_thread(
                        scope.config()["configurable"]["thread_id"]),
                }
                if close_result is not None:
                    progress["messages"][message_id]["state_close"] = close_result
                if public_turn_callback is not None:
                    public_turn_callback(agent, scope, public_index,
                                         "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED",
                                         progress["messages"][message_id]["business_calls"])
                if history_mode is not None or agent_factory is not None:
                    progress["messages"][message_id]["visited_ordinal"] = len(
                        progress["messages"]) - 1
                progress["blocked_sessions"].append(session_key)
                progress["next_indices"][session_key] = public_index + 1
                progress["pending_message"] = None
                write_json(progress_path, progress)
                continue
            except BaseException as original_error:
                if local_state_update_epoch == "turn_end":
                    assert local_state_controller is not None
                    _collect_turn_tail(agent, scope, local_state_controller,
                                       public_index, close=False)
                capture_interruption(original_error, agent, scope, public_index)
                raise
            close_result = (_collect_turn_tail(agent, scope, local_state_controller,
                                               public_index, close=True)
                            if local_state_controller is not None
                            and local_state_update_epoch == "turn_end" else None)
            final = next((item for item in reversed(messages)
                          if isinstance(item, AIMessage)), None)
            progress["messages"][message_id] = {
                "message_id": message_id, "user_id": user_id,
                "session_id": session, "public_index": public_index,
                "status": "COMPLETED",
                "answer": str(final.content) if final is not None else "",
                "business_calls": journal.calls_for_thread(
                    scope.config()["configurable"]["thread_id"]),
            }
            if close_result is not None:
                progress["messages"][message_id]["state_close"] = close_result
            if public_turn_callback is not None:
                public_turn_callback(agent, scope, public_index, "COMPLETED",
                                     progress["messages"][message_id]["business_calls"])
            if history_mode is not None or agent_factory is not None:
                progress["messages"][message_id]["visited_ordinal"] = len(
                    progress["messages"]) - 1
            progress["next_indices"][session_key] = public_index + 1
            progress["pending_message"] = None
            write_json(progress_path, progress)
        rows = [progress["messages"][item["message_id"]]
                for item in phase["messages"]]
        result = {"status": ("TERMINAL_WITH_LOCAL_CAPACITY_FAILURE"
                             if any(row["status"] == (
                                 "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED")
                                 for row in rows) else "TERMINAL"),
                  "phase": phase_id, "messages": rows,
                  "world": world.snapshot()}
        write_json(result_path, result)
        progress["next_phase"] = phase_id + 1
        write_json(progress_path, progress)
        runtime.observer.assert_healthy()
        return result
    finally:
        world.close()
        if history_mode is not None and local_state_controller is None and history_bank is not None:
            if runtime.model.client.emit is not None:
                runtime.model.client.emit({"event": "lsa_history_store_stats",
                                           "phase": phase_id,
                                           "operations": history_bank.store_stats()})
