"""LSA control orchestration; model-visible contracts live in protocol.py."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from jsonschema import ValidationError, validate  # type: ignore[import-untyped]

from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.protocol import (
    ControlResponseError as ControlResponseError,
)
from milai_lab.methods.local_state_attention.protocol import (
    control_prompt,
    event_view,
    parse_control_response,
    parse_json_response,
    selected_ids,
    selection_schema,
    state_directory,
    state_view,
)
from milai_lab.methods.local_state_attention.protocol import (
    control_schema as control_schema,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
    from milai_lab.methods.local_state_attention.writers import WriterProposalContext
    from milai_lab.providers.contextual_vllm import VLLMClient

REQUEST_ROLE: ContextVar[str] = ContextVar("lsa_request_role", default="task_host")
CONTROL_STAGE: ContextVar[str | None] = ContextVar("lsa_control_stage", default=None)


@contextmanager
def request_role(value: str) -> Iterator[None]:
    token = REQUEST_ROLE.set(value)
    try:
        yield
    finally:
        REQUEST_ROLE.reset(token)


class LocalStateController:
    def __init__(self, bank: LocalStateBank, client: VLLMClient,
                 emit: Callable[[dict[str, Any]], None] | None = None,
                 max_pending_batch: int = 24,
                 capacity_path: Path | None = None,
                 max_calls_per_message: int = 13,
                 representation: str = "local",
                 local_granularity: bool = False,
                 update_policy: str = "all",
                 maintenance_only: bool = False) -> None:
        if representation not in {"local", "global_note"}:
            raise ValueError("LSA_REPRESENTATION_UNKNOWN")
        if update_policy not in {"all", "lr", "lru"}:
            raise ValueError("LSA_UPDATE_POLICY_UNKNOWN")
        self.bank = bank
        self.client = client
        self.emit = emit
        self.max_pending_batch = max_pending_batch
        self.capacity_path = capacity_path
        self.max_calls_per_message = max_calls_per_message
        self.representation = representation
        self.local_granularity = local_granularity
        self.update_policy = update_policy
        self.maintenance_only = maintenance_only

    def prepare(self, scope: StateScope, query_id: str, query: str,
                message_key: str = "", *, close_only: bool = False,
                ) -> dict[str, Any]:
        if close_only and self.update_policy != "all":
            raise ValueError("LSA_TURN_END_UPDATE_POLICY_UNSUPPORTED")
        pending = self.bank.pending(scope)
        if close_only and not pending:
            return {"focus": [], "receipts": [], "degraded": False,
                    "reused": True, "pending_event_ids": []}
        previous = self.bank.focus(scope, query_id)
        if not close_only and not pending and previous is not None:
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
        prompt = control_prompt(self.representation, self.local_granularity)
        if self.update_policy in {"lr", "lru"}:
            return self._prepare_independent_read(scope, query_id, query, message_key,
                                                  pending, states, events)
        if close_only or self.maintenance_only:
            return self._prepare_all_maintenance(scope, query_id, message_key,
                                                 pending, states, events)

        payload = {"current_task": query,
                   "new_observations": [self._event_view(row) for row in pending],
                   "states": [state_view(row) for row in states],
                   "source_ids_available": [row["id"] for row in events]}
        schema = control_schema([row["id"] for row in states], self.bank.max_states,
                                single_note=self.representation == "global_note")
        if not self._reserve_call(message_key):
            return {"focus": [], "receipts": [], "degraded": True,
                    "reused": False, "reason": "control_capacity",
                    "pending_event_ids": [row["id"] for row in pending]}
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
        receipts, invalid = self.bank.apply(scope, plan["edits"], event_ids,
                                            query_source_id=query_id)
        current_ids = {row["id"] for row in self.bank.states(scope)}
        new_ids = {index: row["id"] for index, row in enumerate(receipts)
                   if row["status"] == "created" or
                   (row.get("replayed") and row.get("operation") == "create")}
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

    def close_turn(self, scope: StateScope, query_source_id: str,
                   message_key: str) -> dict[str, Any]:
        """Apply pending observations once at the public-turn boundary; never select A."""
        return self.prepare(scope, query_source_id, "", message_key,
                            close_only=True)

    def _reserve_call(self, message_key: str) -> bool:
        """Reserve once before sending; rejected/corrupt capacities are not hidden."""
        if self.capacity_path is None:
            return True
        counts = read_json(self.capacity_path) if self.capacity_path.exists() else {}
        if counts.get(message_key, 0) >= self.max_calls_per_message:
            return False
        counts[message_key] = counts.get(message_key, 0) + 1
        write_json(self.capacity_path, counts)
        return True

    def _stage_call(self, stage: str, message_key: str, prompt: str,
                    payload: dict[str, Any], schema: dict[str, Any],
                    receipt_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._reserve_call(message_key):
            raise ControlResponseError("LSA_CONTROL_CAPACITY")
        if self.emit is not None:
            self.emit({"event": ("lsa_lru_call" if self.update_policy == "lru"
                                 else "lsa_control_stage_call"), "stage": stage,
                       "message_key": message_key,
                       "payload_bytes": len(json.dumps(
                           payload, ensure_ascii=False).encode("utf-8"))})
        token = CONTROL_STAGE.set(stage)
        try:
            with request_role("state_control"):
                receipt = self.client.chat(
                    [{"role": "system", "content": prompt},
                     {"role": "user", "content": json.dumps(
                         payload, ensure_ascii=False)}],
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "local_state_" + stage + "_v1", "strict": True,
                        "schema": schema}})
            if receipt_meta is not None:
                receipt_meta["generation_id"] = receipt.get("id")
            return self._parse_json(receipt)
        finally:
            CONTROL_STAGE.reset(token)

    def propose_writes(self, context: WriterProposalContext,
                       allowed_tools: Sequence[BaseTool]) -> dict[str, Any]:
        """Generate a tool proposal from actual scoped observations; execute nothing."""
        from langchain_core.utils.function_calling import convert_to_openai_tool

        if not context.message_key or not allowed_tools:
            raise ValueError("LSA_WRITER_PROPOSAL_CONTEXT_INVALID")
        catalog = [convert_to_openai_tool(tool)["function"] for tool in allowed_tools]
        names = [entry["name"] for entry in catalog]
        if len(names) != len(set(names)):
            raise ValueError("LSA_WRITER_DUPLICATE_TOOL")
        pending = self.bank.pending(context.scope)
        if len(pending) > self.max_pending_batch:
            raise ControlResponseError("LSA_WRITER_PENDING_BATCH_LIMIT")
        events = self.bank.events(context.scope)
        states = self.bank.states(context.scope)
        payload = {
            "current_task": context.current_task,
            "new_observations": [self._event_view(row) for row in pending],
            "states": [state_view(row) for row in states],
            "source_ids_available": [row["id"] for row in events],
        }
        branches = [{"type": "object", "properties": {
            "name": {"const": entry["name"]},
            "arguments": entry["parameters"]},
            "required": ["name", "arguments"], "additionalProperties": False}
            for entry in catalog]
        schema = {"type": "object", "properties": {
            "calls": {"type": "array", "items": {"oneOf": branches}}},
            "required": ["calls"], "additionalProperties": False}
        metadata: dict[str, Any] = {}
        try:
            response = self._stage_call(
                "writer_proposal", context.message_key,
                "Propose only calls justified by the provided observations and scoped records. "
                "Return calls in their intended order; an empty calls array is valid. "
                "A proposal is not an executed result. Available tools:\n"
                + json.dumps(catalog, ensure_ascii=False),
                payload, schema, receipt_meta=metadata)
            validate(response, schema)
            generation_id = metadata.get("generation_id")
            if not isinstance(generation_id, str) or not generation_id:
                raise ControlResponseError("LSA_WRITER_GENERATION_ID_MISSING")
        except (ControlResponseError, httpx.TimeoutException, ValidationError) as error:
            reason = ("LSA_WRITER_PROPOSAL_INVALID" if isinstance(error, ValidationError)
                      else self._control_reason(error))
            if self.emit is not None:
                self.emit({"event": "lsa_control_degraded", "stage": "writer_proposal",
                           "reason": reason, "user_id": context.scope.user_id,
                           "pending": len(pending)})
            if isinstance(error, ValidationError):
                raise ControlResponseError(reason) from error
            raise
        # The caller must reuse this returned identity when replaying the same proposal.
        batch_id = hashlib.sha256(json.dumps(
            ["lsa_writer_batch_v1", context.message_key, generation_id,
             uuid.uuid4().hex],
            ensure_ascii=False).encode()).hexdigest()
        if self.emit is not None:
            self.emit({"event": "lsa_writer_proposal_result", "stage": "writer_proposal",
                       "message_key": context.message_key,
                       "generation_id": generation_id, "batch_id": batch_id,
                       "call_count": len(response["calls"])})
        return {"batch_id": batch_id, "generation_id": generation_id,
                "calls": response["calls"],
                "event_ids": [row["id"] for row in pending]}

    def _maintenance_payload(self, pending: list[dict[str, Any]],
                             states: list[dict[str, Any]],
                             events: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "new_observations": [self._event_view(row) for row in pending],
            "states": [state_view(row) for row in states],
            "source_ids_available": [row["id"] for row in events],
        }

    def _maintenance_schema(self, state_ids: list[str]) -> dict[str, Any]:
        edits = control_schema(state_ids, self.bank.max_states,
                               single_note=self.representation == "global_note")[
                                   "properties"]["edits"]
        return {"type": "object", "properties": {"edits": edits},
                "required": ["edits"], "additionalProperties": False}

    def _prepare_all_maintenance(self, scope: StateScope, query_id: str,
                                 message_key: str, pending: list[dict[str, Any]],
                                 states: list[dict[str, Any]],
                                 events: list[dict[str, Any]]) -> dict[str, Any]:
        if not pending:
            self.bank.set_focus(scope, query_id, [])
            return {"focus": [], "receipts": [], "degraded": False,
                    "reused": True, "pending_event_ids": []}
        try:
            plan = self._stage_call(
                "maintenance", message_key,
                control_prompt(self.representation, self.local_granularity,
                               maintenance=True),
                self._maintenance_payload(pending, states, events),
                self._maintenance_schema([row["id"] for row in states]))
        except (ControlResponseError, httpx.TimeoutException) as error:
            reason = self._control_reason(error)
            if self.emit is not None:
                self.emit({"event": "lsa_control_degraded", "stage": "maintenance",
                           "reason": reason, "user_id": scope.user_id,
                           "pending": len(pending)})
            return {"focus": [], "receipts": [], "degraded": True,
                    "reused": False, "reason": reason,
                    "pending_event_ids": [row["id"] for row in pending]}
        edits = plan.get("edits")
        if set(plan) != {"edits"} or not isinstance(edits, list):
            return {"focus": [], "receipts": [], "degraded": True,
                    "reused": False, "reason": "LSA_MAINTENANCE_INVALID_SHAPE",
                    "pending_event_ids": [row["id"] for row in pending]}
        receipts, invalid = self.bank.apply(
            scope, edits, {row["id"] for row in pending}, query_source_id=query_id)
        if not invalid:
            self.bank.set_focus(scope, query_id, [])
        remaining = [row["id"] for row in self.bank.pending(scope)]
        if self.emit is not None:
            self.emit({"event": "lsa_control_result", "stage": "maintenance",
                       "user_id": scope.user_id, "focus": [], "edits": receipts,
                       "degraded": invalid, "pending_event_ids": remaining})
        return {"focus": [], "receipts": receipts, "degraded": invalid,
                "reused": False, "pending_event_ids": remaining}

    def _prepare_independent_read(self, scope: StateScope, query_id: str, query: str,
                                  message_key: str, pending: list[dict[str, Any]],
                                  states: list[dict[str, Any]],
                                  events: list[dict[str, Any]]) -> dict[str, Any]:
        selective_update = self.update_policy == "lru"
        event_prefix = "lsa_lru" if selective_update else "lsa_lr"
        directory = state_directory(states) if selective_update else []
        state_ids = {row["id"] for row in states}
        observations = [self._event_view(row) for row in pending]
        base = {"current_task": query, "new_observations": observations,
                "directory": directory}
        stats = {"directory_bytes": (len(json.dumps(
            directory, ensure_ascii=False).encode("utf-8")) if selective_update else 0),
            "full_bank_content_chars": sum(len(row["content"]) for row in states)}
        update_schema = selection_schema("update_ids", state_ids)
        selected_update_ids: list[str] = []

        def degraded(stage: str, reason: str, receipts: list[dict[str, Any]] | None = None,
                     ) -> dict[str, Any]:
            if stage == "read_selector":
                self.bank.clear_focus(scope)
            result = {"focus": [], "receipts": receipts or [], "degraded": True,
                      "reused": False, "reason": reason,
                      "pending_event_ids": [row["id"] for row in self.bank.pending(scope)]}
            if self.emit is not None:
                self.emit({"event": event_prefix + "_result", "stage": stage,
                           "user_id": scope.user_id, "degraded": True,
                           "reason": reason, "update_ids": selected_update_ids,
                           "read_ids": [],
                           "edits": result["receipts"], **stats})
            return result
        if not selective_update:
            route = {"update_ids": ([row["id"] for row in states] if pending else [])}
        elif pending and states:
            try:
                route = self._stage_call(
                    "update_selector", message_key,
                    "From source-identified new observations and the short State directory, "
                    "select every existing State that may need an update. Selection is about "
                    "event impact, not the current reading task. Return update_ids only; "
                    "creation is decided by the shared maintainer.", base, update_schema)
            except (ControlResponseError, httpx.TimeoutException) as error:
                return degraded("update_selector", self._control_reason(error))
        else:
            route = {"update_ids": []}
        update_ids = selected_ids(route, "update_ids", state_ids)
        if update_ids is None:
            return degraded("update_selector", "LSA_UPDATE_SELECTION_INVALID")
        selected_update_ids = update_ids
        # Construct once, not once per State; preserve bank order in the payload.
        update_id_set = set(update_ids)
        candidates = [state_view(row) for row in states if row["id"] in update_id_set]
        candidate_bytes = len(json.dumps(
            candidates, ensure_ascii=False).encode("utf-8"))
        stats["candidate_body_bytes"] = candidate_bytes
        if self.emit is not None:
            self.emit({"event": event_prefix + "_selection",
                       "stage": "update_selector" if selective_update else "update_candidates",
                       "user_id": scope.user_id, "update_ids": update_ids,
                       "selector_skipped_reason": (
                           "full_bank_policy" if not selective_update else
                           "no_pending" if not pending else
                           "empty_bank" if not states else None), **stats})
        event_ids = {row["id"] for row in pending}
        receipts: list[dict[str, Any]] = []
        if pending:
            try:
                plan = self._stage_call(
                    "maintenance", message_key,
                    control_prompt(self.representation, self.local_granularity,
                                   maintenance=True, candidate_only=selective_update),
                    self._maintenance_payload(pending, candidates, events),
                    self._maintenance_schema(update_ids))
            except (ControlResponseError, httpx.TimeoutException) as error:
                return degraded("maintenance", self._control_reason(error))
            edits = plan.get("edits")
            if set(plan) != {"edits"} or not isinstance(edits, list):
                return degraded("maintenance", "LSA_MAINTENANCE_INVALID_SHAPE")
            receipts, invalid = self.bank.apply(scope, edits, event_ids,
                                                query_source_id=query_id,
                                                allowed_existing_ids=update_id_set)
            if invalid:
                return degraded("maintenance", "LSA_MAINTENANCE_INVALID", receipts)
        updated = self.bank.states(scope)
        updated_ids = {row["id"] for row in updated}
        read_directory = state_directory(updated)
        stats["updated_directory_bytes"] = len(json.dumps(
            read_directory, ensure_ascii=False).encode("utf-8"))
        read_schema = selection_schema("read_ids", updated_ids)
        if updated:
            try:
                choice = self._stage_call(
                    "read_selector", message_key,
                    "From the updated State directory and current task, select the State "
                    "ids needed for the current answer or action. Empty and multiple "
                    "selections are valid. Return read_ids only.",
                    {"current_task": query, "new_observations": observations,
                     "directory": read_directory}, read_schema)
            except (ControlResponseError, httpx.TimeoutException) as error:
                return degraded("read_selector", self._control_reason(error), receipts)
            read_ids = selected_ids(choice, "read_ids", updated_ids)
            if read_ids is None:
                return degraded("read_selector", "LSA_READ_SELECTION_INVALID", receipts)
        else:
            read_ids = []
        self.bank.set_focus(scope, query_id, read_ids)
        result = {"focus": read_ids, "receipts": receipts, "degraded": False,
                  "reused": False, "pending_event_ids": []}
        if self.emit is not None:
            self.emit({"event": event_prefix + "_result", "user_id": scope.user_id,
                       "degraded": False, "update_ids": update_ids,
                       "read_ids": read_ids, "edits": receipts, **stats})
        return result

    @staticmethod
    def _control_reason(error: ControlResponseError | httpx.TimeoutException) -> str:
        return str(error) if isinstance(error, ControlResponseError) else type(error).__name__

    # Compatibility aliases for existing callers; parsing has one owner.
    _parse_json = staticmethod(parse_json_response)
    _parse = staticmethod(parse_control_response)
    _event_view = staticmethod(event_view)
