"""Read already visited owner history from public checkpoints, without an archive copy."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from milai_lab.harness.contextual_artifacts import read_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope

VISITED_STATUSES = {"COMPLETED", "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"}
HISTORY_TOOL_DESCRIPTION = (
    "Read this user's already visited conversation history in chronological public-turn "
    "order. This is read-only and may include explicitly incomplete prior turns. Use cursor "
    "and max_bytes for mechanical whole-record pagination; no future messages are available."
)


@dataclass(frozen=True)
class WindowSnapshot:
    full_messages: list[BaseMessage]
    window_messages: list[BaseMessage]
    incomplete: list[dict[str, Any]]
    newly_covered: list[dict[str, Any]]
    target_ordinal: int
    suppressed: bool


def source_id(thread_id: str, position: int, message: BaseMessage) -> str:
    """Use the same stable provenance key for checkpoint and State source checks."""
    if isinstance(message, ToolMessage) and message.tool_call_id:
        return "tool:" + hashlib.sha256(json.dumps(
            [thread_id, message.tool_call_id], ensure_ascii=False).encode()).hexdigest()
    if message.id:
        return "message:" + message.id
    return "message:" + hashlib.sha256(json.dumps(
        [thread_id, position, message.type, message.content],
        ensure_ascii=False, default=str).encode()).hexdigest()


def _wire(message: BaseMessage) -> dict[str, Any]:
    fields: dict[str, Any] = {"role": message.type, "id": message.id,
                              "content": message.content}
    if isinstance(message, AIMessage):
        fields["tool_calls"] = message.tool_calls
    if isinstance(message, ToolMessage):
        fields.update({"tool_call_id": message.tool_call_id,
                       "name": message.name, "status": message.status})
    return fields


def _turn(messages: list[BaseMessage], public_index: int) -> list[BaseMessage]:
    starts = [index for index, message in enumerate(messages)
              if isinstance(message, HumanMessage)]
    if public_index >= len(starts):
        return []
    end = starts[public_index + 1] if public_index + 1 < len(starts) else len(messages)
    return messages[starts[public_index]:end]


def _complete(turn: list[BaseMessage]) -> bool:
    if not turn or not isinstance(turn[-1], AIMessage) or turn[-1].tool_calls:
        return False
    outstanding: set[str] = set()
    seen_calls: set[str] = set()
    for message in turn:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                call_id = call.get("id")
                if not isinstance(call_id, str) or not call_id or call_id in seen_calls:
                    return False
                outstanding.add(call_id)
                seen_calls.add(call_id)
        elif isinstance(message, ToolMessage):
            if message.tool_call_id not in outstanding:
                return False
            outstanding.remove(message.tool_call_id)
    return not outstanding


class HistoryAccess:
    """One owner-scoped view over the runner's visited ledger and checkpoints."""

    def __init__(self, root: Path, scope: StateScope, bank: LocalStateBank,
                 get_state: Callable[[str], Any],
                 thread_id_for_session: Callable[[str], str],
                 *, page_max_bytes: int, emit: Callable[[dict[str, Any]], None] | None = None,
                 ) -> None:
        if type(page_max_bytes) is not int or page_max_bytes <= 0:
            raise ValueError("HISTORY_PAGE_BUDGET_INVALID")
        identity = read_json(root / "run_manifest.json")["identity"]
        if ((identity.get("run_id"), identity.get("arm_id")) != (
                scope.run_id, scope.arm_id) or scope.workspace_id != "default"):
            raise ValueError("HISTORY_OWNER_SCOPE_MISMATCH")
        self.root, self.scope, self.bank = root, scope, bank
        self.get_state = get_state
        self.thread_id_for_session = thread_id_for_session
        self.page_max_bytes = page_max_bytes
        self.emit = emit

    def _visited(self) -> list[dict[str, Any]]:
        path = self.root / "phase-progress.json"
        progress = read_json(path) if path.exists() else {"messages": {}}
        rows = [row for row in progress["messages"].values()
                if row.get("user_id") == self.scope.user_id
                and row.get("status") in VISITED_STATUSES]
        ordinals = [row.get("visited_ordinal") for row in rows]
        if (all(type(value) is int for value in ordinals)
                and len(set(ordinals)) == len(ordinals)):
            rows.sort(key=lambda row: row["visited_ordinal"])
        return rows

    def _snapshot(self, session: str) -> list[BaseMessage]:
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        logical_bytes = 0
        try:
            state = self.get_state(session)
            messages: list[BaseMessage] = list(state.values.get("messages", []))
            logical_bytes = len(json.dumps([_wire(message) for message in messages],
                                           ensure_ascii=False, default=str).encode("utf-8"))
            return messages
        finally:
            if self.emit is not None:
                self.emit({"event": "lsa_history_checkpoint_read", "calls": 1,
                           "session": session,
                           "logical_bytes": logical_bytes,
                           "cpu_ns": time.process_time_ns() - start_cpu,
                           "wall_ns": time.perf_counter_ns() - start_wall})

    def _records(self, current_thread: str | None = None,
                 current_messages: list[BaseMessage] | None = None,
                 ) -> list[tuple[dict[str, Any], list[BaseMessage]]]:
        snapshots: dict[str, list[BaseMessage]] = {}
        prior_calls: dict[str, set[tuple[str, str]]] = {}
        records = []
        for ordinal, row in enumerate(self._visited()):
            session = row["session_id"]
            if session not in snapshots:
                snapshots[session] = (
                    current_messages if current_messages is not None
                    and self.thread_id_for_session(session) == current_thread else
                    self._snapshot(session))
            turn = _turn(snapshots[session], row["public_index"])
            status = row["status"]
            if status == "COMPLETED" and not _complete(turn):
                raise ValueError("HISTORY_COMPLETED_CHECKPOINT_INCOMPLETE")
            seen = prior_calls.setdefault(session, set())
            delta = []
            for call in row.get("business_calls", []):
                key = (str(call.get("generation_id")), str(call.get("call_id")))
                if key not in seen:
                    delta.append(call)
                    seen.add(key)
            record = {"ordinal": ordinal, "message_id": row["message_id"],
                      "session_id": session, "public_index": row["public_index"],
                      "status": status, "messages": [_wire(message) for message in turn]}
            if status != "COMPLETED":
                record["business_journal_delta"] = delta
            records.append((record, turn))
        return records

    def _suppressed(self) -> bool:
        return self.bank.has_forgotten_sources(self.scope)

    def page(self, cursor: int = 0, max_bytes: int | None = None) -> dict[str, Any]:
        if type(cursor) is not int or cursor < 0:
            raise ValueError("HISTORY_CURSOR_INVALID")
        limit = self.page_max_bytes if max_bytes is None else max_bytes
        if type(limit) is not int or not 0 < limit <= self.page_max_bytes:
            raise ValueError("HISTORY_PAGE_BUDGET_INVALID")
        if self._suppressed():
            return {"status": "SUPPRESSED_OWNER_TOMBSTONE", "records": [],
                    "next_cursor": cursor, "has_more": False, "payload_bytes": 0}
        records = [record for record, _ in self._records()]
        if cursor > len(records):
            raise ValueError("HISTORY_CURSOR_OUT_OF_RANGE")
        chosen: list[dict[str, Any]] = []
        used = 0
        for record in records[cursor:]:
            size = len(json.dumps(record, ensure_ascii=False,
                                  separators=(",", ":"), default=str).encode("utf-8"))
            if used + size > limit:
                if not chosen:
                    return {"status": "RECORD_OVER_PAGE_BUDGET", "records": [],
                            "next_cursor": cursor, "has_more": True,
                            "record_bytes": size, "payload_bytes": 0}
                break
            chosen.append(record)
            used += size
        next_cursor = cursor + len(chosen)
        return {"status": "OK", "records": chosen, "next_cursor": next_cursor,
                "has_more": next_cursor < len(records), "payload_bytes": used}

    def project(self, current_thread: str, current_messages: list[BaseMessage],
                ) -> tuple[list[BaseMessage], list[dict[str, Any]], bool]:
        """Native-replay completed turns; surface incomplete prefixes as labeled data."""
        current = _turn(current_messages, sum(isinstance(message, HumanMessage)
                                              for message in current_messages) - 1)
        if self._suppressed():
            return current, [], True
        native: list[BaseMessage] = []
        incomplete: list[dict[str, Any]] = []
        completed_turns = 0
        for record, turn in self._records(current_thread, current_messages):
            if record["status"] == "COMPLETED":
                native.extend(turn)
                completed_turns += 1
            else:
                incomplete.append({**record, "completed_before": completed_turns})
        native.extend(current)
        if self.emit is not None:
            self.emit({"event": "lsa_history_projection", "completed_messages":
                       len(native) - len(current), "incomplete_turns": len(incomplete),
                       "history_bytes": len(json.dumps([_wire(message) for message in native],
                                                        ensure_ascii=False,
                                                        default=str).encode("utf-8"))})
        return native, incomplete, False

    def window(self, current_thread: str, current_messages: list[BaseMessage],
               keep_completed: int, covered_ordinal: int) -> WindowSnapshot:
        """Partition visited turns without altering checkpoint or source order."""
        if type(keep_completed) is not int or keep_completed < 0:
            raise ValueError("HISTORY_WINDOW_INVALID")
        current = _turn(current_messages, sum(isinstance(message, HumanMessage)
                                              for message in current_messages) - 1)
        if self._suppressed():
            return WindowSnapshot(current, current, [], [], covered_ordinal, True)
        records = self._records(current_thread, current_messages)
        if covered_ordinal < -1 or covered_ordinal >= len(records):
            raise ValueError("HISTORY_SUMMARY_CURSOR_INVALID")
        completed = [(record, turn) for record, turn in records
                     if record["status"] == "COMPLETED"]
        older = completed[:-keep_completed] if keep_completed else completed
        recent = completed[-keep_completed:] if keep_completed else []
        newly = [record for record, _ in older
                 if record["ordinal"] > covered_ordinal]
        target = newly[-1]["ordinal"] if newly else covered_ordinal
        full = [message for _, turn in completed for message in turn]
        window = [message for _, turn in recent for message in turn]
        incomplete: list[dict[str, Any]] = []
        completed_before = 0
        for record, _turn_messages in records:
            if record["status"] == "COMPLETED":
                completed_before += 1
            else:
                incomplete.append({**record, "completed_before": completed_before})
        return WindowSnapshot([*full, *current], [*window, *current], incomplete,
                              newly, target, False)
