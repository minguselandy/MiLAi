"""One owner-scoped, checkpoint-grounded sliding-window summary."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import BaseMessage

from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.controller import (
    CONTROL_STAGE,
    ControlResponseError,
    request_role,
)
from milai_lab.methods.local_state_attention.history import HistoryAccess
from milai_lab.providers.contextual_vllm import VLLMClient

SUMMARY_PROMPT = (
    "Update one concise conversation summary using only the prior summary and the "
    "listed earlier completed conversation turns. Retain continuing facts, requests, "
    "exact names, identifiers, quantities, conditions, unresolved work, and actual tool "
    "outcomes, including errors or partial effects. A request alone does not establish "
    "that an action was attempted or completed. Do not infer later events, answer the "
    "current user, or add facts absent from these inputs. Return JSON with summary only."
)


@dataclass(frozen=True)
class SummaryView:
    messages: list[BaseMessage]
    incomplete: list[dict[str, Any]]
    summary: str
    covered_ordinal: int
    suppressed: bool
    degraded: bool


class HistorySummaryController:
    def __init__(self, client: VLLMClient, *, window_completed_turns: int,
                 summary_content_max_chars: int, capacity_path: Path,
                 max_calls_per_message: int,
                 emit: Callable[[dict[str, Any]], None] | None = None) -> None:
        if (type(window_completed_turns) is not int or window_completed_turns < 0
                or type(summary_content_max_chars) is not int
                or summary_content_max_chars <= 0
                or type(max_calls_per_message) is not int or max_calls_per_message <= 0):
            raise ValueError("HISTORY_SUMMARY_CONFIG_INVALID")
        self.client = client
        self.window_completed_turns = window_completed_turns
        self.summary_content_max_chars = summary_content_max_chars
        self.capacity_path = capacity_path
        self.max_calls_per_message = max_calls_per_message
        self.emit = emit

    def prepare(self, history: HistoryAccess, current_thread: str,
                current_messages: list[BaseMessage], message_key: str) -> SummaryView:
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        if history.bank.has_forgotten_sources(history.scope):
            suppressed = history.window(current_thread, current_messages,
                                        self.window_completed_turns, -1)
            return SummaryView(suppressed.window_messages, [], "", -1, True, False)
        stored = history.bank.history_summary(history.scope)
        if stored is None:
            summary, covered = "", -1
        else:
            raw_summary, raw_covered = stored.get("summary"), stored.get("covered_ordinal")
            if (not isinstance(raw_summary, str)
                    or len(raw_summary) > self.summary_content_max_chars
                    or type(raw_covered) is not int or raw_covered < 0):
                raise ValueError("HISTORY_SUMMARY_STORE_INVALID")
            summary, covered = raw_summary, raw_covered
        snapshot = history.window(current_thread, current_messages,
                                  self.window_completed_turns, covered)
        if snapshot.suppressed:
            return SummaryView(snapshot.window_messages, [], "", covered, True, False)
        if not snapshot.newly_covered:
            return SummaryView(snapshot.window_messages, snapshot.incomplete,
                               summary, covered, False, False)
        source_ids = [row["message_id"] for row in snapshot.newly_covered]
        counts = read_json(self.capacity_path) if self.capacity_path.exists() else {}
        attempt_key = "history_summary:" + message_key
        if (counts.get(attempt_key, 0) >= 1
                or counts.get(message_key, 0) >= self.max_calls_per_message):
            self._emit("fallback", message_key, source_ids, covered,
                       snapshot.target_ordinal, start_wall, start_cpu,
                       "HISTORY_SUMMARY_CAPACITY_OR_PREVIOUS_ATTEMPT")
            return SummaryView(snapshot.full_messages, snapshot.incomplete,
                               "", covered, False, True)
        payload = {"prior_summary": summary,
                   "new_completed_turns": snapshot.newly_covered}
        payload_text = json.dumps(payload, ensure_ascii=False, default=str)
        counts[message_key] = counts.get(message_key, 0) + 1
        counts[attempt_key] = 1
        write_json(self.capacity_path, counts)
        if self.emit is not None:
            self.emit({"event": "lsa_history_summary_call", "message_key": message_key,
                       "stage": "history_summary",
                       "source_message_ids": source_ids,
                       "previous_covered_ordinal": covered,
                       "target_covered_ordinal": snapshot.target_ordinal,
                       "payload_bytes": len(payload_text.encode("utf-8"))})
        token = CONTROL_STAGE.set("history_summary")
        try:
            with request_role("state_control"):
                receipt = self.client.chat(
                    [{"role": "system", "content": SUMMARY_PROMPT},
                     {"role": "user", "content": payload_text}],
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "history_summary_v1", "strict": True,
                        "schema": {"type": "object", "properties": {
                            "summary": {"type": "string", "minLength": 1,
                                        "maxLength": self.summary_content_max_chars}},
                            "required": ["summary"], "additionalProperties": False}}})
            updated = self._parse(receipt)
        except (ControlResponseError, httpx.TimeoutException) as error:
            self._emit("fallback", message_key, source_ids, covered,
                       snapshot.target_ordinal, start_wall, start_cpu,
                       str(error) if isinstance(error, ControlResponseError)
                       else type(error).__name__)
            return SummaryView(snapshot.full_messages, snapshot.incomplete,
                               "", covered, False, True)
        finally:
            CONTROL_STAGE.reset(token)
        history.bank.put_history_summary(history.scope, updated,
                                         snapshot.target_ordinal)
        self._emit("committed", message_key, source_ids, covered,
                   snapshot.target_ordinal, start_wall, start_cpu, None)
        return SummaryView(snapshot.window_messages, snapshot.incomplete,
                           updated, snapshot.target_ordinal, False, False)

    def _parse(self, receipt: dict[str, Any]) -> str:
        try:
            choice = receipt["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ControlResponseError("HISTORY_SUMMARY_INCOMPLETE")
            value = json.loads(choice["message"]["content"])
            if (not isinstance(value, dict) or set(value) != {"summary"}
                    or not isinstance(value["summary"], str)
                    or not value["summary"].strip()
                    or len(value["summary"]) > self.summary_content_max_chars):
                raise ControlResponseError("HISTORY_SUMMARY_INVALID_SHAPE")
            return value["summary"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ControlResponseError("HISTORY_SUMMARY_INVALID_RESPONSE") from error

    def _emit(self, status: str, message_key: str, source_ids: list[str],
              previous: int, target: int, start_wall: int, start_cpu: int,
              reason: str | None) -> None:
        if self.emit is not None:
            self.emit({"event": "lsa_history_summary_result", "status": status,
                       "stage": "history_summary",
                       "message_key": message_key,
                       "source_message_ids": source_ids,
                       "previous_covered_ordinal": previous,
                       "target_covered_ordinal": target,
                       "reason": reason,
                       "cpu_ns": time.process_time_ns() - start_cpu,
                       "wall_ns": time.perf_counter_ns() - start_wall})
