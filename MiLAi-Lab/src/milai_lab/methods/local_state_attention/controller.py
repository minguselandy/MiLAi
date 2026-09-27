"""One short, independently accounted control call for a batch of observations."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import httpx

from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.providers.contextual_vllm import VLLMClient

REQUEST_ROLE: ContextVar[str] = ContextVar("lsa_request_role", default="task_host")


@contextmanager
def request_role(value: str) -> Iterator[None]:
    token = REQUEST_ROLE.set(value)
    try:
        yield
    finally:
        REQUEST_ROLE.reset(token)


def control_schema(state_ids: list[str], max_states: int) -> dict[str, Any]:
    """Constrain new-State titles and focus to actual or request-local identifiers."""
    fields: dict[str, Any] = {
        "title": {"type": "string", "minLength": 1},
        "content": {"type": "string", "minLength": 1},
        "needs": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
    }
    new_edit = {"type": "object", "properties": {"id": {"type": "null"}, **fields},
                "required": ["id", "title", "content"], "additionalProperties": False}
    existing_edit = {
        "type": "object", "properties": {"id": {"enum": state_ids}, **fields},
        "required": ["id", "content"], "additionalProperties": False,
    }
    edits = [new_edit, existing_edit] if state_ids else [new_edit]
    focus_ids = [*state_ids, *(f"new:{index}" for index in range(max_states))]
    return {
        "type": "object", "properties": {
            "edits": {"type": "array", "items": (
                {"oneOf": edits} if len(edits) > 1 else edits[0]),
                "maxItems": max_states},
            "focus": {"type": "array", "items": {"enum": focus_ids}},
        },
        "required": ["edits", "focus"], "additionalProperties": False,
    }


class ControlResponseError(ValueError):
    pass


class LocalStateController:
    def __init__(self, bank: LocalStateBank, client: VLLMClient,
                 emit: Callable[[dict[str, Any]], None] | None = None,
                 max_pending_batch: int = 24,
                 capacity_path: Path | None = None,
                 max_calls_per_message: int = 13) -> None:
        self.bank = bank
        self.client = client
        self.emit = emit
        self.max_pending_batch = max_pending_batch
        self.capacity_path = capacity_path
        self.max_calls_per_message = max_calls_per_message

    def prepare(self, scope: StateScope, query_id: str, query: str,
                message_key: str = "") -> dict[str, Any]:
        pending = self.bank.pending(scope)
        previous = self.bank.focus(scope, query_id)
        if not pending and previous is not None:
            valid = {row["id"] for row in self.bank.states(scope)}
            return {"focus": [key for key in previous if key in valid],
                    "receipts": [], "degraded": False, "reused": True,
                    "pending_event_ids": []}
        if len(pending) > self.max_pending_batch:
            return {"focus": [], "receipts": [], "degraded": True,
                    "reused": False, "reason": "pending_batch_limit",
                    "pending_event_ids": [row["id"] for row in pending]}
        states = self.bank.states(scope)
        events = self.bank.events(scope)
        prompt = (
            "Maintain short local States for continuing matters. Update matters affected by "
            "new observations, independently choose the States useful to the current task. "
            "A tool receipt with ok=false can contain a committed partial effect: read its "
            "actual fields. Do not invent a business action, source, or State id. "
            "Return JSON with edits and focus only. A new edit requires id:null, a short "
            "nonempty title naming the continuing matter and content; cite source evidence "
            "when available. "
            "An update requires an exact existing State id and content; omitted title or "
            "needs preserves its previous value. No change needs no edit. "
            "Focus is an array of identifiers only: exact ids from states, or new:0, new:1 "
            "for a newly created edit at that zero-based edits index. Never put a title, "
            "factual summary, or answer in focus. Empty focus is valid. "
            "Update matters affected by observations even when they are not in focus; "
            "choose focus for the current_task, which is a query rather than an answer. "
            "Evidence may cite only listed source ids. Keep unresolved needs concise."
        )
        payload = {"current_task": query,
                   "new_observations": [self._event_view(row) for row in pending],
                   "states": [{key: row[key] for key in (
                       "id", "title", "content", "needs", "evidence_refs", "revision")}
                              for row in states],
                   "source_ids_available": [row["id"] for row in events]}
        schema = control_schema([row["id"] for row in states], self.bank.max_states)
        if self.capacity_path is not None:
            counts = read_json(self.capacity_path) if self.capacity_path.exists() else {}
            if counts.get(message_key, 0) >= self.max_calls_per_message:
                return {"focus": [], "receipts": [], "degraded": True,
                        "reused": False, "reason": "control_capacity",
                        "pending_event_ids": [row["id"] for row in pending]}
            counts[message_key] = counts.get(message_key, 0) + 1
            write_json(self.capacity_path, counts)
        try:
            with request_role("state_control"):
                receipt = self.client.chat(
                    [{"role": "system", "content": prompt},
                     {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "local_state_control_v1", "strict": True,
                        "schema": schema}},
                )
            plan = self._parse(receipt)
        except (ControlResponseError, httpx.TimeoutException) as error:
            if self.emit is not None:
                self.emit({"event": "lsa_control_degraded", "reason": type(error).__name__,
                           "user_id": scope.user_id, "pending": len(pending)})
            return {"focus": [], "receipts": [], "degraded": True,
                    "reused": False,
                    "pending_event_ids": [row["id"] for row in pending]}
        event_ids = {row["id"] for row in pending}
        receipts, invalid = self.bank.apply(scope, plan["edits"], event_ids)
        current_ids = {row["id"] for row in self.bank.states(scope)}
        new_ids = {index: row["id"] for index, row in enumerate(receipts)
                   if row["status"] == "created"}
        focus = []
        for key in plan["focus"]:
            if key.startswith("new:"):
                try:
                    key = new_ids[int(key[4:])]
                except (ValueError, KeyError):
                    continue
            if key in current_ids and key not in focus:
                focus.append(key)
        if not invalid:
            self.bank.set_focus(scope, query_id, focus)
        result = {"focus": focus, "receipts": receipts, "degraded": invalid,
                  "reused": False,
                  "pending_event_ids": [row["id"] for row in self.bank.pending(scope)]}
        if self.emit is not None:
            self.emit({"event": "lsa_control_result", "user_id": scope.user_id,
                       "focus": focus, "edits": receipts, "degraded": invalid,
                       "pending_event_ids": result["pending_event_ids"]})
        return result

    @staticmethod
    def _event_view(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row[key] for key in ("id", "kind", "content")}

    @staticmethod
    def _parse(receipt: dict[str, Any]) -> dict[str, Any]:
        try:
            choice = receipt["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ControlResponseError("LSA_CONTROL_INCOMPLETE")
            result = json.loads(choice["message"]["content"])
            if (not isinstance(result, dict) or set(result) != {"edits", "focus"}
                    or not isinstance(result["edits"], list)
                    or not isinstance(result["focus"], list)
                    or any(not isinstance(key, str) for key in result["focus"])):
                raise ControlResponseError("LSA_CONTROL_INVALID_SHAPE")
            return result
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ControlResponseError("LSA_CONTROL_INVALID_RESPONSE") from error
