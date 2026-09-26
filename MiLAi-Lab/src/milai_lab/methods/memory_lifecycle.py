"""Fixed, independent prospective-retention cue for the Formation arm."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from milai_lab.runners.langmem_foundation import BusinessActionJournal

FORMATION_PROTOCOL_ID = "prospective_retention_duty_v2"
FORMATION_CUE = (
    "When the user establishes a future use for a commitment, constraint, unfinished "
    "obligation, or reusable result, call manage_memory before the final reply to save "
    "or update the smallest accurate, scoped durable note, including relevant identifiers "
    "from completed tool results. Do not substitute an oral acknowledgement for the memory "
    "operation. If no future use is established, do not write memory."
)
FORMATION_CUE_SHA256 = hashlib.sha256(FORMATION_CUE.encode("utf-8")).hexdigest()

OBSERVATION_PROTOCOL_ID = "prospective_retention_observation_v3"
OBSERVATION_REMINDER = (
    "A business-tool observation has just returned. Apply the future-use rule now to this "
    "turn's information, including the actual returned observation. If the rule calls for "
    "retention, use manage_memory before answering; otherwise finish without writing. "
    "A tool returning does not by itself establish business success."
)
OBSERVATION_REMINDER_SHA256 = hashlib.sha256(
    OBSERVATION_REMINDER.encode("utf-8")).hexdigest()


class BusinessObservationRequestView:
    """Append the fixed reminder only after a journal-bound business tool response."""

    def __init__(self, journal: BusinessActionJournal,
                 emit: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.journal = journal
        self.emit = emit

    def project(self, wire: list[dict[str, Any]], graph: list[BaseMessage],
                message_key: str | None, request_index: int,
                ) -> tuple[list[dict[str, Any]], list[BaseMessage]]:
        cpu_started, wall_started = time.process_time_ns(), time.perf_counter_ns()
        projected, matched = self._project(wire, graph, message_key)
        cpu_ns = time.process_time_ns() - cpu_started
        wall_ns = time.perf_counter_ns() - wall_started
        if self.emit is not None:
            self.emit({"event": "formation_observation_projection",
                       "status": "projected" if matched else "unchanged",
                       "message_key": message_key, "request_index": request_index,
                       "matched_business_call_ids": matched,
                       "cpu_ns": cpu_ns, "wall_ns": wall_ns,
                       "provider_request": False})
        return projected, graph

    def _project(self, wire: list[dict[str, Any]], graph: list[BaseMessage],
                 message_key: str | None,
                 ) -> tuple[list[dict[str, Any]], list[str]]:
        if (message_key is None or len(wire) != len(graph) or not graph
                or not isinstance(graph[-1], ToolMessage) or not wire
                or wire[0].get("role") != "system"):
            return wire, []
        thread_id, separator, _ = message_key.rpartition(":")
        if not separator:
            return wire, []
        first_tool = len(graph) - 1
        while first_tool >= 0 and isinstance(graph[first_tool], ToolMessage):
            first_tool -= 1
        generating = graph[first_tool] if first_tool >= 0 else None
        if not isinstance(generating, AIMessage) or not generating.id:
            return wire, []
        calls = {call["id"]: call for call in generating.tool_calls}
        matched = []
        for original, rendered in zip(graph[first_tool + 1:], wire[first_tool + 1:], strict=True):
            if not isinstance(original, ToolMessage) or rendered.get("role") != "tool":
                continue
            call = calls.get(original.tool_call_id)
            if (call is None or original.name not in self.journal.business_names
                    or rendered.get("tool_call_id") != original.tool_call_id
                    or rendered.get("name") != original.name
                    or rendered.get("content") != original.content):
                continue
            entry = self.journal.entry_for_call(
                thread_id, generating.id, original.tool_call_id)
            if (entry is None or entry.get("status") != "complete"
                    or entry.get("name") != original.name
                    or entry.get("args") != call["args"]):
                continue
            result = entry["result"]
            if (result.get("tool_call_id") != original.tool_call_id
                    or result.get("name") != original.name
                    or result.get("content") != original.content
                    or result.get("status") != original.status):
                continue
            matched.append(original.tool_call_id)
        if not matched:
            return wire, []
        first = dict(wire[0])
        first["content"] = first["content"] + "\n" + OBSERVATION_REMINDER
        return [first, *wire[1:]], matched
