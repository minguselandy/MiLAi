"""Durable business-call receipts and opt-in trusted application contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from milai_lab.harness.contextual_artifacts import read_json, write_json


class UnknownBusinessAction(RuntimeError):
    """A prior call entered native execution but has no durable result."""


class BusinessActionJournal:
    def __init__(self, path: Path, business_names: Sequence[str], *,
                 application_protection: bool = False,
                 response_hook: Callable[[dict[str, Any], ToolMessage], None] | None = None,
                 ) -> None:
        self.path = path
        self.business_names = frozenset(business_names)
        self.application_protection = application_protection
        self.response_hook = response_hook
        self.binding: dict[str, Any] | None = None
        if response_hook is not None and not application_protection:
            raise ValueError("APPLICATION_RESPONSE_HOOK_REQUIRES_PROTECTION")

    def _entries(self) -> dict[str, Any]:
        return read_json(self.path) if self.path.exists() else {}

    def __call__(
        self,
        request: ToolCallRequest,
        execute: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        if call["name"] not in self.business_names:
            return execute(request)
        if self.application_protection:
            return self._protected_call(request, execute)
        messages = request.state["messages"]
        generating_message = messages[-1]
        if not isinstance(generating_message, AIMessage) or not generating_message.id:
            raise ValueError("BUSINESS_CALL_GENERATION_ID_MISSING")
        thread_id = request.runtime.config["configurable"]["thread_id"]
        identity = [thread_id, generating_message.id, call["id"]]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        entries = self._entries()
        prior = entries.get(key)
        if prior is not None:
            if prior["status"] != "complete":
                raise UnknownBusinessAction(f"BUSINESS_CALL_OUTCOME_UNKNOWN:{key}")
            return ToolMessage.model_validate(prior["result"])
        entries[key] = {
            "status": "pending",
            "thread_id": thread_id,
            "generation_id": generating_message.id,
            "call_id": call["id"],
            "name": call["name"],
            "args": call["args"],
        }
        write_json(self.path, entries)
        response = execute(request)
        if not isinstance(response, ToolMessage):
            raise TypeError("BUSINESS_CALL_EXPECTED_TOOL_MESSAGE")
        entries[key]["result"] = response.model_dump(mode="json")
        entries[key]["status"] = "complete"
        write_json(self.path, entries)
        return response

    def calls_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        return [entry for entry in self._entries().values() if entry.get("thread_id") == thread_id]

    def entry_for_call(self, thread_id: str, generation_id: str,
                       call_id: str) -> dict[str, Any] | None:
        identity = [thread_id, generation_id, call_id]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        return self._entries().get(key)

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False)

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value).encode()).hexdigest()

    @staticmethod
    def _application(entries: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], entries.setdefault(
            "_application", {"bindings": {}, "operations": {}, "resolved": {}, "recoveries": {}}))

    def bind_request(self, binding: Mapping[str, Any]) -> None:
        """Bind a trusted application request; this never interprets public text."""
        if not self.application_protection:
            raise ValueError("APPLICATION_PROTECTION_DISABLED")
        frozen = json.loads(self._canonical(binding))
        for field in ("run_id", "arm_id", "owner", "thread_id", "message_id", "task_id"):
            if type(frozen.get(field)) is not str or not frozen[field]:
                raise ValueError("APPLICATION_BINDING_IDENTITY_INVALID")
        if type(frozen.get("public_index")) is not int or frozen["public_index"] < 0:
            raise ValueError("APPLICATION_BINDING_PUBLIC_INDEX_INVALID")
        operations = frozen.get("operations")
        if not isinstance(operations, list):
            raise ValueError("APPLICATION_BINDING_OPERATIONS_INVALID")
        ids: set[str] = set()
        for op in operations:
            if (not isinstance(op, dict) or type(op.get("operation_id")) is not str
                    or not op["operation_id"] or op["operation_id"] in ids
                    or op.get("tool") not in self.business_names
                    or not isinstance(op.get("args"), dict)
                    or not isinstance(op.get("target"), dict)
                    or op.get("retry", "never") not in {"never", "no_effect"}
                    or not isinstance(op.get("depends_on", []), list)
                    or not all(type(dep) is str for dep in op.get("depends_on", []))):
                raise ValueError("APPLICATION_OPERATION_INVALID")
            precondition = op.get("precondition", {})
            if (not isinstance(precondition, dict)
                    or not set(precondition).issubset({
                        "query_operation_id", "status", "label_status"})
                    or (precondition and type(precondition.get("query_operation_id")) is not str)):
                raise ValueError("APPLICATION_PRECONDITION_INVALID")
            if op.get("reservation_from") is not None and (
                op["tool"] != "complete_label" or op["args"] != {}
                or type(op["reservation_from"]) is not str
            ):
                raise ValueError("APPLICATION_RESERVATION_BINDING_INVALID")
            if op["tool"] in {"reserve_and_label", "get_reservation", "complete_label"}:
                if "effect_contract" in op:
                    raise ValueError("APPLICATION_NATIVE_EFFECT_CONTRACT_FIXED")
                if not all(field in op["target"] for field in (
                    "item_key", "quantity", "destination", "packing"
                )):
                    raise ValueError("APPLICATION_TARGET_INCOMPLETE")
                if (type(op["target"]["quantity"]) is not int or op["target"]["quantity"] < 1
                        or any(type(op["target"][field]) is not str or not op["target"][field]
                               for field in ("item_key", "destination", "packing"))):
                    raise ValueError("APPLICATION_TARGET_TYPE_INVALID")
                fields = (("item_key", "quantity", "destination", "packing")
                          if op["tool"] == "reserve_and_label" else ("item_key",))
                if op["tool"] != "complete_label" and any(
                    self._canonical(op["args"].get(field)) != self._canonical(op["target"][field])
                    for field in fields
                ):
                    raise ValueError("APPLICATION_ARGUMENT_TARGET_MISMATCH")
                if op["tool"] == "complete_label" and op.get("reservation_from") is None:
                    raise ValueError("APPLICATION_LABEL_REQUIRES_QUERY_BINDING")
            elif (not isinstance(op.get("effect_contract"), dict)
                  or not op["effect_contract"]
                  or any(effect not in {"confirmed", "partial", "none", "observed", "unknown"}
                         for effect in op["effect_contract"].values())):
                raise ValueError("APPLICATION_EFFECT_CONTRACT_REQUIRED")
            ids.add(op["operation_id"])
        for op in operations:
            if (not set(op.get("depends_on", [])).issubset(ids)
                    or op["operation_id"] in op.get("depends_on", [])
                    or (op.get("reservation_from") is not None
                        and not any(query["operation_id"] == op["reservation_from"]
                                    and query["tool"] == "get_reservation"
                                    and query["target"] == op["target"] for query in operations))):
                raise ValueError("APPLICATION_OPERATION_DEPENDENCY_INVALID")
            if op.get("precondition") and not any(
                query["operation_id"] == op["precondition"]["query_operation_id"]
                and query["tool"] == "get_reservation" and query["target"] == op["target"]
                for query in operations
            ):
                raise ValueError("APPLICATION_PRECONDITION_QUERY_INVALID")
        entries = self._entries()
        app = self._application(entries)
        identity = {field: frozen[field] for field in (
            "run_id", "arm_id", "owner", "thread_id", "public_index", "message_id")}
        binding_key, binding_hash = self._hash(identity), self._hash(frozen)
        prior = app["bindings"].get(binding_key)
        if prior is not None and prior["hash"] != binding_hash:
            raise ValueError("APPLICATION_BINDING_CHANGED")
        for op in operations:
            key = self.operation_key(frozen, op["operation_id"])
            if key in app["operations"] and self._canonical(app["operations"][key]) != (
                self._canonical(op)
            ):
                raise ValueError("APPLICATION_OPERATION_CHANGED")
        app["bindings"][binding_key] = {"hash": binding_hash, "binding": frozen}
        for op in operations:
            app["operations"][self.operation_key(frozen, op["operation_id"])] = op
        write_json(self.path, entries)
        self.binding = frozen

    @classmethod
    def operation_key(cls, binding: Mapping[str, Any], operation_id: str) -> str:
        return cls._hash([binding[field] for field in (
            "run_id", "arm_id", "owner", "task_id")] + [operation_id])

    def _op_entries(self, entries: dict[str, Any], operation_key: str) -> list[dict[str, Any]]:
        return [row for row in entries.values() if row.get("operation_key") == operation_key]

    def _effects(self, entries: dict[str, Any], operation_key: str) -> list[str]:
        recoveries = self._application(entries)["recoveries"]
        return [recoveries.get(row["journal_key"], {}).get("effect", row.get("effect", "unknown"))
                for row in self._op_entries(entries, operation_key) if row.get("executed")]

    def _args_for(self, entries: dict[str, Any], op: dict[str, Any]) -> dict[str, Any] | None:
        if op.get("reservation_from") is None:
            return cast(dict[str, Any], op["args"])
        assert self.binding is not None
        key = self.operation_key(self.binding, op["operation_id"])
        return cast(dict[str, Any] | None, self._application(entries)["resolved"].get(key))

    def _select_operation(self, entries: dict[str, Any], name: str,
                          args: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if self.binding is None:
            return None, "AUTHORIZATION_UNDETERMINED"
        matched = [op for op in self.binding["operations"] if op["tool"] == name
                   and self._canonical(self._args_for(entries, op)) == self._canonical(args)]
        reason = "APPLICATION_OPERATION_NOT_AUTHORIZED"
        for op in matched:
            key = self.operation_key(self.binding, op["operation_id"])
            effects = self._effects(entries, key)
            if any(effect in {"confirmed", "partial"} for effect in effects):
                reason = "APPLICATION_OPERATION_EFFECT_ALREADY_CONFIRMED"
                continue
            if "unknown" in effects:
                reason = "APPLICATION_OPERATION_OUTCOME_UNKNOWN"
                continue
            if effects and name != "get_reservation" and op.get("retry", "never") != "no_effect":
                reason = "APPLICATION_OPERATION_RETRY_NOT_ALLOWED"
                continue
            if effects and name == "complete_label":
                prior = [row for row in self._op_entries(entries, key) if row.get("executed")][-1]
                status = (json.loads(prior["result"]["content"]).get("status")
                          if prior.get("result") else None)
                if status != "label_service_unavailable":
                    reason = "APPLICATION_OPERATION_RETRY_NOT_ALLOWED"
                    continue
            if any(not any(effect in {"confirmed", "partial", "observed"}
                           for effect in self._effects(
                               entries, self.operation_key(self.binding, dep)))
                   for dep in op.get("depends_on", [])):
                reason = "APPLICATION_OPERATION_DEPENDENCY_UNMET"
                continue
            if op["target"].get("resolved") is False:
                reason = "AUTHORIZATION_UNDETERMINED"
                continue
            if precondition := op.get("precondition"):
                rows = self._op_entries(entries, self.operation_key(
                    self.binding, precondition["query_operation_id"]))
                reads = [row for row in rows if row["status"] == "complete" and row.get("executed")]
                observation = json.loads(reads[-1]["result"]["content"]) if reads else {}
                if (not isinstance(observation, dict) or any(
                    observation.get(field) != expected for field, expected in precondition.items()
                    if field != "query_operation_id"
                )):
                    reason = "APPLICATION_OPERATION_PRECONDITION_UNMET"
                    continue
            return op, "APPLICATION_OPERATION_AUTHORIZED"
        return None, reason

    @staticmethod
    def _receipt_effect(op: dict[str, Any], response: ToolMessage) -> str:
        try:
            status = json.loads(str(response.content)).get("status")
        except (ValueError, AttributeError):
            return "unknown"
        contracts = {
            "reserve_and_label": {"label_created": "confirmed", "reserved_label_failed": "partial",
                                  "duplicate_reservation_attempt": "none",
                                  "invalid_arguments": "none"},
            "complete_label": {"label_created": "confirmed", "label_service_unavailable": "none",
                               "already_labeled": "none", "not_found": "none"},
            "get_reservation": {"found": "observed", "not_found": "observed"},
        }
        return str(contracts.get(op["tool"], op.get("effect_contract", {})).get(status, "unknown"))

    def _bind_reservation(self, entries: dict[str, Any], query_op: dict[str, Any],
                          response: ToolMessage) -> bool:
        assert self.binding is not None
        binding = self.binding
        resolved_bindings = self._application(entries)["resolved"]
        label_ops = [op for op in self.binding["operations"]
                     if op.get("reservation_from") == query_op["operation_id"]]

        def invalidate() -> bool:
            for op in label_ops:
                resolved_bindings.pop(self.operation_key(binding, op["operation_id"]), None)
            return False

        try:
            result = json.loads(str(response.content))
        except ValueError:
            return invalidate()
        target = query_op["target"]
        if (not isinstance(result, dict) or result.get("status") != "found"
                or type(result.get("reservation_id")) is not str
                or result.get("label_status") not in {"created", "not_created"}
                or not result["reservation_id"] or any(self._canonical(result.get(field)) !=
                    self._canonical(target[field]) for field in (
                        "item_key", "quantity", "destination", "packing"))):
            return invalidate()
        for op in label_ops:
            key = self.operation_key(self.binding, op["operation_id"])
            resolved = {"reservation_id": result["reservation_id"]}
            prior = resolved_bindings.get(key)
            if prior is not None and prior != resolved:
                raise ValueError("APPLICATION_RESERVATION_ID_CHANGED")
            resolved_bindings[key] = resolved
        return True

    def _protected_call(self, request: ToolCallRequest,
                        execute: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
                        ) -> ToolMessage | Command[Any]:
        call, messages = request.tool_call, request.state["messages"]
        generated = messages[-1]
        if not isinstance(generated, AIMessage) or not generated.id:
            raise ValueError("BUSINESS_CALL_GENERATION_ID_MISSING")
        config = request.runtime.config["configurable"]
        thread_id = config["thread_id"]
        key = hashlib.sha256(json.dumps([thread_id, generated.id, call["id"]],
                                       ensure_ascii=False).encode()).hexdigest()
        if self.binding is not None and (
            any(config.get(field) != self.binding[bfield] for field, bfield in (
                ("thread_id", "thread_id"), ("foundation_run_id", "run_id"),
                ("arm_id", "arm_id"), ("user_id", "owner")))
            or sum(isinstance(row, HumanMessage) for row in messages) - 1 !=
                self.binding["public_index"]
        ):
            raise ValueError("APPLICATION_CALL_SCOPE_CHANGED")
        entries = self._entries()
        binding_hash = self._hash(self.binding) if self.binding is not None else None
        prior = entries.get(key)
        if prior is not None:
            if (prior["name"] != call["name"] or self._canonical(prior["args"]) !=
                    self._canonical(call["args"]) or prior.get("binding_hash") != binding_hash):
                raise ValueError("APPLICATION_CALL_IDENTITY_CHANGED")
            if prior["status"] != "complete":
                raise UnknownBusinessAction(f"BUSINESS_CALL_OUTCOME_UNKNOWN:{key}")
            return ToolMessage.model_validate(prior["result"])
        op, reason = self._select_operation(entries, call["name"], call["args"])
        origin = ("application_recovery" if generated.response_metadata.get("application_recovery")
                  else "host")
        row: dict[str, Any] = {"status": "pending", "thread_id": thread_id,
               "generation_id": generated.id,
               "call_id": call["id"], "name": call["name"], "args": call["args"],
               "journal_key": key, "binding_hash": binding_hash, "origin": origin,
               "decision": "authorized" if op is not None else "blocked", "reason": reason,
               "executed": False, "effect": "none"}
        if op is not None:
            assert self.binding is not None
            row.update(operation_key=self.operation_key(self.binding, op["operation_id"]),
                       operation_id=op["operation_id"], task_id=self.binding["task_id"],
                       owner=self.binding["owner"], target=op["target"])
        entries[key] = row
        if op is None:
            response = ToolMessage(content=json.dumps({"status": reason, "executed": False}),
                                   tool_call_id=call["id"], name=call["name"], status="error")
        else:
            row.update(executed=True, effect="unknown")
            write_json(self.path, entries)
            try:
                executed_response = execute(request)
                if not isinstance(executed_response, ToolMessage):
                    raise TypeError("BUSINESS_CALL_EXPECTED_TOOL_MESSAGE")
                response = executed_response
                if self.response_hook is not None:
                    row["response_hook_point"] = "after_execute_before_journal_complete"
                    write_json(self.path, entries)
                    self.response_hook(dict(row), response)
            except BaseException as error:
                row["error"] = {"type": type(error).__name__, "message": str(error)}
                write_json(self.path, entries)
                raise
            row["effect"] = self._receipt_effect(op, response)
            if op["tool"] == "get_reservation":
                row["target_matched"] = self._bind_reservation(entries, op, response)
        row.update(result=response.model_dump(mode="json"), status="complete")
        write_json(self.path, entries)
        return response

    def record_recovery(self, original_key: str, recovery: dict[str, Any]) -> None:
        entries = self._entries()
        prior = entries[original_key]
        if prior["status"] != "pending" or not prior.get("executed"):
            raise ValueError("APPLICATION_RECOVERY_ORIGINAL_NOT_PENDING")
        self._application(entries)["recoveries"][original_key] = recovery
        write_json(self.path, entries)

    def recovery_for_call(self, original_key: str) -> dict[str, Any] | None:
        return cast(dict[str, Any] | None,
                    self._application(self._entries())["recoveries"].get(original_key))
