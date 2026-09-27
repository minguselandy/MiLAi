"""A small durable application workload over the ordinary LangMem agent."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

from langchain_core.messages import AIMessage
from langmem import create_manage_memory_tool  # type: ignore[import-untyped]

from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    FoundationScope,
    build_agent,
    invoke_or_resume_public_message,
)
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import LocalStateController
from milai_lab.methods.local_state_attention.history import HistoryAccess
from milai_lab.methods.local_state_attention.integration import collect_observations
from milai_lab.methods.local_state_attention.summary import HistorySummaryController
from milai_lab.runners.langmem_application_runtime import ApplicationRuntime
from milai_lab.runners.langmem_foundation import BusinessActionJournal, native_business_tools

BUSINESS_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "reserve_and_label",
        "description": (
            "Reserve an item for the current user and attempt its label. "
            "A failed label may leave a real reservation. One call is one attempt."),
        "parameters": {"type": "object", "properties": {
            "item_key": {"type": "string", "description": (
                "Copy the complete item reference including qualifiers; use this same exact "
                "key for later reads.")},
            "quantity": {"type": "integer", "minimum": 1},
            "destination": {"type": "string"}, "packing": {"type": "string"}},
            "required": ["item_key", "quantity", "destination", "packing"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "get_reservation",
        "description": "Read the current user's actual reservation and label state for an item.",
        "parameters": {"type": "object", "properties": {
            "item_key": {"type": "string", "description": (
                "Copy the complete item reference including qualifiers; use the exact "
                "key used for the reservation.")}}, "required": ["item_key"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "complete_label",
        "description": (
            "Create the label for the current user's existing reservation. "
            "This does not reserve again or dispatch anything."),
        "parameters": {"type": "object", "properties": {
            "reservation_id": {"type": "string"}}, "required": ["reservation_id"],
            "additionalProperties": False}}},
]
BUSINESS_NAMES = [entry["function"]["name"] for entry in BUSINESS_SCHEMAS]


class ApplicationWorld:
    """Compute receipts from committed, user-scoped SQLite state."""

    def __init__(self, path: Path, initial_label_available: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.tool_lock = threading.RLock()
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS settings "
                              "(name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            self.conn.execute("CREATE TABLE IF NOT EXISTS world_events "
                              "(event_id TEXT PRIMARY KEY, available INTEGER NOT NULL)")
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS reservations ("
                "reservation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, item_key TEXT NOT NULL, "
                "quantity INTEGER NOT NULL, destination TEXT NOT NULL, packing TEXT NOT NULL, "
                "label_status TEXT NOT NULL, UNIQUE(user_id,item_key))")
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS attempts ("
                "id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, item_key TEXT NOT NULL, "
                "operation TEXT NOT NULL, outcome TEXT NOT NULL)")
            self.conn.execute(
                "INSERT OR IGNORE INTO settings(name,value) VALUES('label_available',?)",
                (int(initial_label_available),))

    def close(self) -> None:
        self.conn.close()

    def set_label_available(self, event_id: str, available: bool) -> None:
        with self.conn:
            prior = self.conn.execute(
                "SELECT available FROM world_events WHERE event_id=?", (event_id,)).fetchone()
            if prior is not None:
                if prior["available"] != int(available):
                    raise ValueError("APPLICATION_WORLD_EVENT_CHANGED")
                return
            self.conn.execute("UPDATE settings SET value=? WHERE name='label_available'",
                              (int(available),))
            self.conn.execute("INSERT INTO world_events VALUES(?,?)",
                              (event_id, int(available)))

    def _available(self) -> bool:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE name='label_available'").fetchone()
        return bool(row["value"])

    @staticmethod
    def _receipt(**fields: Any) -> str:
        return json.dumps(fields, ensure_ascii=False)

    @staticmethod
    def _state(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in (
            "reservation_id", "item_key", "quantity", "destination", "packing",
            "label_status")}

    def reserve_and_label(self, user_id: str, item_key: str, quantity: int,
                          destination: str, packing: str) -> str:
        if quantity < 1 or not all((item_key, destination, packing)):
            return self._receipt(ok=False, status="invalid_arguments")
        with self.conn:
            prior = self.conn.execute(
                "SELECT * FROM reservations WHERE user_id=? AND item_key=?",
                (user_id, item_key)).fetchone()
            if prior is not None:
                self.conn.execute("INSERT INTO attempts(user_id,item_key,operation,outcome) "
                                  "VALUES(?,?,'reserve_and_label','duplicate')",
                                  (user_id, item_key))
                return self._receipt(ok=False, status="duplicate_reservation_attempt",
                                     **self._state(prior))
            reservation_id = "RSV-" + str(uuid.uuid4())
            self.conn.execute(
                "INSERT INTO reservations VALUES(?,?,?,?,?,?,?)",
                (reservation_id, user_id, item_key, quantity, destination, packing,
                 "not_created"))
            self.conn.execute("INSERT INTO attempts(user_id,item_key,operation,outcome) "
                              "VALUES(?,?,'reserve_and_label','reserved')",
                              (user_id, item_key))
        if not self._available():
            row = self.conn.execute("SELECT * FROM reservations WHERE reservation_id=?",
                                    (reservation_id,)).fetchone()
            return self._receipt(ok=False, status="reserved_label_failed",
                                 reason="label_service_unavailable", **self._state(row))
        with self.conn:
            self.conn.execute("UPDATE reservations SET label_status='created' "
                              "WHERE reservation_id=?", (reservation_id,))
        row = self.conn.execute("SELECT * FROM reservations WHERE reservation_id=?",
                                (reservation_id,)).fetchone()
        return self._receipt(ok=True, status="label_created", **self._state(row))

    def get_reservation(self, user_id: str, item_key: str) -> str:
        row = self.conn.execute(
            "SELECT * FROM reservations WHERE user_id=? AND item_key=?",
            (user_id, item_key)).fetchone()
        return (self._receipt(ok=True, status="found", **self._state(row)) if row
                else self._receipt(ok=False, status="not_found", item_key=item_key))

    def complete_label(self, user_id: str, reservation_id: str) -> str:
        row = self.conn.execute(
            "SELECT * FROM reservations WHERE user_id=? AND reservation_id=?",
            (user_id, reservation_id)).fetchone()
        if row is None:
            return self._receipt(ok=False, status="not_found", reservation_id=reservation_id)
        if row["label_status"] == "created":
            return self._receipt(ok=False, status="already_labeled", **self._state(row))
        if not self._available():
            return self._receipt(ok=False, status="label_service_unavailable",
                                 **self._state(row))
        with self.conn:
            self.conn.execute("UPDATE reservations SET label_status='created' "
                              "WHERE reservation_id=?", (reservation_id,))
            self.conn.execute("INSERT INTO attempts(user_id,item_key,operation,outcome) "
                              "VALUES(?,?,'complete_label','created')",
                              (user_id, row["item_key"]))
        updated = self.conn.execute("SELECT * FROM reservations WHERE reservation_id=?",
                                    (reservation_id,)).fetchone()
        return self._receipt(ok=True, status="label_created", **self._state(updated))

    def snapshot(self) -> dict[str, Any]:
        return {
            "label_available": self._available(),
            "reservations": [dict(row) for row in self.conn.execute(
                "SELECT * FROM reservations ORDER BY user_id,item_key")],
            "attempts": [dict(row) for row in self.conn.execute(
                "SELECT * FROM attempts ORDER BY id")],
        }


def _business_tools(world: ApplicationWorld, user_id: str) -> list[Any]:
    def invoke(method: Callable[..., str], **arguments: Any) -> str:
        with world.tool_lock:
            return method(user_id, **arguments)

    functions = {
        "reserve_and_label": lambda _world, **args: invoke(world.reserve_and_label, **args),
        "get_reservation": lambda _world, **args: invoke(world.get_reservation, **args),
        "complete_label": lambda _world, **args: invoke(world.complete_label, **args),
    }
    return native_business_tools(None, BUSINESS_SCHEMAS, functions)


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
    if (history_mode == "window") != (history_summary_controller is not None):
        raise ValueError("APPLICATION_HISTORY_SUMMARY_MISMATCH")
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
        journal = BusinessActionJournal(root / "business-journal.json", BUSINESS_NAMES)
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
            agent = agents.get(user_id)
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
                messages = invoke_or_resume_public_message(
                    agent, runtime.model, scope, message["text"], public_index, pending)
            except ValueError as error:
                if str(error) != "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED":
                    if local_state_update_epoch == "turn_end":
                        assert local_state_controller is not None
                        _collect_turn_tail(agent, scope, local_state_controller,
                                           public_index, close=False)
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
                if history_mode is not None:
                    progress["messages"][message_id]["visited_ordinal"] = len(
                        progress["messages"]) - 1
                progress["blocked_sessions"].append(session_key)
                progress["next_indices"][session_key] = public_index + 1
                progress["pending_message"] = None
                write_json(progress_path, progress)
                continue
            except BaseException:
                if local_state_update_epoch == "turn_end":
                    assert local_state_controller is not None
                    _collect_turn_tail(agent, scope, local_state_controller,
                                       public_index, close=False)
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
            if history_mode is not None:
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
