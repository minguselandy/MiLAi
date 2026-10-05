"""Durable business-call receipts and opt-in trusted application contracts."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from milai_lab.application.document_publication import (
    DOCUMENT_EFFECTS,
    DOCUMENT_FIELDS,
    DOCUMENT_NAMES,
    document_sources,
    publication_matches,
    validate_document_operation,
)
from milai_lab.harness.contextual_artifacts import read_json, write_json


class UnknownBusinessAction(RuntimeError):
    """A prior call entered native execution but has no durable result."""


class BusinessActionJournal:
    def __init__(
        self,
        path: Path,
        business_names: Sequence[str],
        *,
        application_protection: bool = False,
        response_hook: Callable[[dict[str, Any], ToolMessage], None] | None = None,
        application_workflow: str = "reservation_v1",
    ) -> None:
        self.path = path
        self.business_names = frozenset(business_names)
        self.application_protection = application_protection
        self.response_hook = response_hook
        if application_workflow not in {"reservation_v1", "document_publication_v1"}:
            raise ValueError("APPLICATION_WORKFLOW_INVALID")
        self.document_workflow = application_workflow == "document_publication_v1"
        self.binding: dict[str, Any] | None = None
        self.binding_id: str | None = None
        self.operation_identities: dict[str, str] = {}
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
        entries = self._entries()
        key = self.call_key(entries, thread_id, generating_message.id, call["id"])
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

    def entry_for_call(
        self, thread_id: str, generation_id: str, call_id: str
    ) -> dict[str, Any] | None:
        entries = self._entries()
        return entries.get(self.call_key(entries, thread_id, generation_id, call_id))

    @staticmethod
    def call_key(entries: dict[str, Any], thread: str, generation: str, call: str | None) -> str:
        if not isinstance(call, str) or not call:
            raise ValueError("BUSINESS_CALL_IDENTITY_REQUIRED")
        # Existing legacy keys stay ordinary strings; find by their persisted identities.
        for key, row in entries.items():
            if isinstance(row, dict) and (
                row.get("thread_id"),
                row.get("generation_id"),
                row.get("call_id"),
            ) == (thread, generation, call):
                return key
        # Caller-issued generation and call IDs already identify this operation.
        # Keep their complete identity; this also avoids conflating different
        # calls when a deterministic fixture supplies repeated UUID values.
        return "call:" + BusinessActionJournal._canonical([thread, generation, call])

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )

    @staticmethod
    def _application(entries: dict[str, Any]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            entries.setdefault(
                "_application", {"bindings": {}, "operations": {}, "resolved": {}, "recoveries": {}}
            ),
        )

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
            if (
                not isinstance(op, dict)
                or type(op.get("operation_id")) is not str
                or not op["operation_id"]
                or op["operation_id"] in ids
                or op.get("tool") not in self.business_names
                or not isinstance(op.get("args"), dict)
                or not isinstance(op.get("target"), dict)
                or op.get("retry", "never") not in {"never", "no_effect"}
                or not isinstance(op.get("depends_on", []), list)
                or not all(type(dep) is str for dep in op.get("depends_on", []))
            ):
                raise ValueError("APPLICATION_OPERATION_INVALID")
            precondition = op.get("precondition", {})
            if (
                not isinstance(precondition, dict)
                or not set(precondition).issubset(
                    {"query_operation_id", *DOCUMENT_FIELDS}
                    if self.document_workflow
                    else {"query_operation_id", "status", "label_status"}
                )
                or (precondition and type(precondition.get("query_operation_id")) is not str)
            ):
                raise ValueError("APPLICATION_PRECONDITION_INVALID")
            if op.get("reservation_from") is not None and (
                op["tool"] != "complete_label"
                or op["args"] != {}
                or type(op["reservation_from"]) is not str
            ):
                raise ValueError("APPLICATION_RESERVATION_BINDING_INVALID")
            if (
                "recovery_retry" in op
                and not self.document_workflow
                and (
                    op["recovery_retry"] != "confirmed_no_effect_v1"
                    or op["tool"] != "complete_label"
                    or op.get("retry") != "no_effect"
                    or op.get("reservation_from") is None
                    or precondition
                    != {
                        "query_operation_id": op["reservation_from"],
                        "status": "found",
                        "label_status": "not_created",
                    }
                )
            ):
                raise ValueError("APPLICATION_RECOVERY_RETRY_CONTRACT_INVALID")
            if self.document_workflow:
                validate_document_operation(op)
            elif op["tool"] in {"reserve_and_label", "get_reservation", "complete_label"}:
                if "effect_contract" in op:
                    raise ValueError("APPLICATION_NATIVE_EFFECT_CONTRACT_FIXED")
                if not all(
                    field in op["target"]
                    for field in ("item_key", "quantity", "destination", "packing")
                ):
                    raise ValueError("APPLICATION_TARGET_INCOMPLETE")
                if (
                    type(op["target"]["quantity"]) is not int
                    or op["target"]["quantity"] < 1
                    or any(
                        type(op["target"][field]) is not str or not op["target"][field]
                        for field in ("item_key", "destination", "packing")
                    )
                ):
                    raise ValueError("APPLICATION_TARGET_TYPE_INVALID")
                fields = (
                    ("item_key", "quantity", "destination", "packing")
                    if op["tool"] == "reserve_and_label"
                    else ("item_key",)
                )
                if op["tool"] != "complete_label" and any(
                    self._canonical(op["args"].get(field)) != self._canonical(op["target"][field])
                    for field in fields
                ):
                    raise ValueError("APPLICATION_ARGUMENT_TARGET_MISMATCH")
                if op["tool"] == "complete_label" and op.get("reservation_from") is None:
                    raise ValueError("APPLICATION_LABEL_REQUIRES_QUERY_BINDING")
            elif (
                not isinstance(op.get("effect_contract"), dict)
                or not op["effect_contract"]
                or any(
                    effect not in {"confirmed", "partial", "none", "observed", "unknown"}
                    for effect in op["effect_contract"].values()
                )
            ):
                raise ValueError("APPLICATION_EFFECT_CONTRACT_REQUIRED")
            ids.add(op["operation_id"])
        for op in operations:
            if self.document_workflow:
                sources = document_sources(op)
                if any(
                    not any(
                        source["operation_id"] == name
                        and source["tool"] in DOCUMENT_NAMES
                        and source["target"] == op["target"]
                        for source in operations
                    )
                    for name in sources
                ):
                    raise ValueError("DOCUMENT_OBSERVATION_DEPENDENCY_INVALID")
                if "recovery_retry" in op and not any(
                    source["operation_id"] == op["recovery_query_operation_id"]
                    and source["tool"] == "get_document_status"
                    and source["target"] == op["target"]
                    for source in operations
                ):
                    raise ValueError("DOCUMENT_RECOVERY_QUERY_INVALID")
            if (
                not set(op.get("depends_on", [])).issubset(ids)
                or op["operation_id"] in op.get("depends_on", [])
                or (
                    op.get("reservation_from") is not None
                    and not any(
                        query["operation_id"] == op["reservation_from"]
                        and query["tool"] == "get_reservation"
                        and query["target"] == op["target"]
                        for query in operations
                    )
                )
            ):
                raise ValueError("APPLICATION_OPERATION_DEPENDENCY_INVALID")
            if op.get("precondition") and not any(
                query["operation_id"] == op["precondition"]["query_operation_id"]
                and query["tool"]
                in (DOCUMENT_NAMES if self.document_workflow else ("get_reservation",))
                and query["target"] == op["target"]
                for query in operations
            ):
                raise ValueError("APPLICATION_PRECONDITION_QUERY_INVALID")
        entries = self._entries()
        app = self._application(entries)
        # Reopen old journals by persisted identity metadata. Legacy operation
        # keys remain opaque, including their original outcomes and resolutions.
        identities = dict(app.get("operation_identities", {}))
        task_fields = ("run_id", "arm_id", "owner", "task_id")
        for saved_key, saved in app["bindings"].items():
            saved_binding = saved["binding"]
            if any(saved_binding.get(k) != frozen[k] for k in task_fields):
                continue
            binding_ids = {saved_key, saved.get("binding_id"), saved.get("hash")}
            for row in entries.values():
                if not isinstance(row, dict) or (
                    row.get("binding_id", row.get("binding_hash")) not in binding_ids
                    or not isinstance(row.get("operation_id"), str)
                    or not isinstance(row.get("operation_key"), str)
                ):
                    continue
                identity_key = self._canonical(
                    [frozen[k] for k in task_fields] + [row["operation_id"]]
                )
                old_key = row["operation_key"]
                if identity_key in identities and identities[identity_key] != old_key:
                    raise ValueError("APPLICATION_OPERATION_IDENTITY_AMBIGUOUS")
                identities[identity_key] = old_key
        self.operation_identities = identities
        app["operation_identities"] = identities
        identity = {
            field: frozen[field]
            for field in ("run_id", "arm_id", "owner", "thread_id", "public_index", "message_id")
        }
        prior = next(
            (
                row
                for row in app["bindings"].values()
                if all(row["binding"].get(k) == v for k, v in identity.items())
            ),
            None,
        )
        if prior is not None and prior["binding"] != frozen:
            raise ValueError("APPLICATION_BINDING_CHANGED")
        binding_key = prior.get("binding_id", prior.get("hash")) if prior else str(uuid.uuid4())
        for op in operations:
            key = self.operation_key(frozen, op["operation_id"])
            if key in app["operations"] and self._canonical(app["operations"][key]) != (
                self._canonical(op)
            ):
                raise ValueError("APPLICATION_OPERATION_CHANGED")
        app["bindings"][binding_key] = {"binding_id": binding_key, "binding": frozen}
        for op in operations:
            app["operations"][self.operation_key(frozen, op["operation_id"])] = op
        write_json(self.path, entries)
        self.binding = frozen
        self.binding_id = binding_key

    def operation_key(self, binding: Mapping[str, Any], operation_id: str) -> str:
        identity = self._canonical(
            [binding[field] for field in ("run_id", "arm_id", "owner", "task_id")] + [operation_id]
        )
        return self.operation_identities.get(identity, identity)

    def _op_entries(self, entries: dict[str, Any], operation_key: str) -> list[dict[str, Any]]:
        return [row for row in entries.values() if row.get("operation_key") == operation_key]

    def _same_args(self, name: str, left: Any, right: Any) -> bool:
        if self.document_workflow and name == "create_or_update_draft":
            # Compare the public function's actual defaults without changing the
            # requested/journal arguments or supplying any body or permission.
            if isinstance(left, dict) and isinstance(right, dict):
                left = {"document_version": 0, **left}
                right = {"document_version": 0, **right}
        return self._canonical(left) == self._canonical(right)

    def _effects(
        self, entries: dict[str, Any], operation_key: str, args: dict[str, Any] | None = None
    ) -> list[str]:
        recoveries = self._application(entries)["recoveries"]
        return [
            recoveries.get(row["journal_key"], {}).get("effect", row.get("effect", "unknown"))
            for row in self._op_entries(entries, operation_key)
            if row.get("executed")
            and (args is None or self._same_args(row["name"], row["args"], args))
        ]

    def _args_for(self, entries: dict[str, Any], op: dict[str, Any]) -> dict[str, Any] | None:
        if op.get("reservation_from") is None and not document_sources(op):
            return cast(dict[str, Any], op["args"])
        assert self.binding is not None
        key = self.operation_key(self.binding, op["operation_id"])
        return cast(dict[str, Any] | None, self._application(entries)["resolved"].get(key))

    def _select_operation(
        self, entries: dict[str, Any], name: str, args: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        if self.binding is None:
            return None, "AUTHORIZATION_UNDETERMINED"
        matched = [
            op
            for op in self.binding["operations"]
            if op["tool"] == name and self._same_args(name, self._args_for(entries, op), args)
        ]
        reason = "APPLICATION_OPERATION_NOT_AUTHORIZED"
        for op in matched:
            key = self.operation_key(self.binding, op["operation_id"])
            effects = self._effects(
                entries,
                key,
                args if self.document_workflow and name != "get_document_status" else None,
            )
            if any(effect in {"confirmed", "partial"} for effect in effects):
                reason = "APPLICATION_OPERATION_EFFECT_ALREADY_CONFIRMED"
                continue
            if "unknown" in effects:
                reason = "APPLICATION_OPERATION_OUTCOME_UNKNOWN"
                continue
            if (
                effects
                and name
                not in {
                    "get_reservation",
                    "get_document_status" if self.document_workflow else "get_reservation",
                }
                and op.get("retry", "never") != "no_effect"
            ):
                reason = "APPLICATION_OPERATION_RETRY_NOT_ALLOWED"
                continue
            if effects and name == "complete_label":
                prior = [row for row in self._op_entries(entries, key) if row.get("executed")][-1]
                status = (
                    json.loads(prior["result"]["content"]).get("status")
                    if prior.get("result")
                    else None
                )
                if status != "label_service_unavailable" and not self._recovery_retry_allowed(
                    entries, prior, op
                ):
                    reason = "APPLICATION_OPERATION_RETRY_NOT_ALLOWED"
                    continue
            if effects and self.document_workflow and name == "publish_approved_document":
                prior = [
                    row
                    for row in self._op_entries(entries, key)
                    if row.get("executed") and self._canonical(row["args"]) == self._canonical(args)
                ][-1]
                status = (
                    json.loads(prior["result"]["content"]).get("status")
                    if prior.get("result")
                    else None
                )
                if status != "publish_service_unavailable" and not self._recovery_retry_allowed(
                    entries, prior, op
                ):
                    reason = "APPLICATION_OPERATION_RETRY_NOT_ALLOWED"
                    continue
            if any(
                not any(
                    effect in {"confirmed", "partial", "observed"}
                    for effect in self._effects(entries, self.operation_key(self.binding, dep))
                )
                for dep in op.get("depends_on", [])
            ):
                reason = "APPLICATION_OPERATION_DEPENDENCY_UNMET"
                continue
            if op["target"].get("resolved") is False:
                reason = "AUTHORIZATION_UNDETERMINED"
                continue
            if precondition := op.get("precondition"):
                rows = self._op_entries(
                    entries, self.operation_key(self.binding, precondition["query_operation_id"])
                )
                reads = [row for row in rows if row["status"] == "complete" and row.get("executed")]
                observation = json.loads(reads[-1]["result"]["content"]) if reads else {}
                if not isinstance(observation, dict) or any(
                    observation.get(field) != expected
                    for field, expected in precondition.items()
                    if field != "query_operation_id"
                ):
                    reason = "APPLICATION_OPERATION_PRECONDITION_UNMET"
                    continue
            return op, "APPLICATION_OPERATION_AUTHORIZED"
        return None, reason

    def _recovery_retry_allowed(
        self, entries: dict[str, Any], prior: dict[str, Any], op: dict[str, Any]
    ) -> bool:
        """A finite opt-in permission from a new query, never an original receipt.

        Old pending/effect=unknown rows remain untouched. Only a separately
        journaled, executed, target-matched discovery of this reservation with its
        label still absent can enable the explicit no-effect retry contract.
        """
        if op.get("recovery_retry") != "confirmed_no_effect_v1":
            return False
        recovery = self._application(entries)["recoveries"].get(prior["journal_key"], {})
        query = entries.get(recovery.get("query_journal_key"), {})
        if (
            prior.get("status") != "pending"
            or prior.get("result") is not None
            or recovery.get("original_call_status") != "UNKNOWN"
            or recovery.get("effect") != "none"
            or recovery.get("effect_source") != ("query_observation_not_original_execution_receipt")
            or query.get("status") != "complete"
            or query.get("executed") is not True
            or query.get("name")
            != ("get_document_status" if self.document_workflow else "get_reservation")
            or query.get("target_matched") is not True
            or query.get("target") != prior.get("target")
        ):
            return False
        try:
            observation = json.loads(query["result"]["content"])
        except (KeyError, ValueError, TypeError):
            return False
        if self.document_workflow:
            return (
                op.get("tool") == "publish_approved_document"
                and isinstance(observation, dict)
                and all(
                    observation.get(field) == expected
                    for field, expected in op["recovery_precondition"].items()
                )
                and all(
                    observation.get(field) == prior["args"].get(field)
                    for field in ("document_version",)
                )
                and not publication_matches(observation, prior["args"])
            )
        return (
            isinstance(observation, dict)
            and observation.get("status") == "found"
            and observation.get("label_status") == "not_created"
        )

    def _receipt_effect(self, op: dict[str, Any], response: ToolMessage) -> str:
        try:
            status = json.loads(str(response.content)).get("status")
        except (ValueError, AttributeError):
            return "unknown"
        contracts = {
            **(DOCUMENT_EFFECTS if self.document_workflow else {}),
            "reserve_and_label": {
                "label_created": "confirmed",
                "reserved_label_failed": "partial",
                "duplicate_reservation_attempt": "none",
                "invalid_arguments": "none",
            },
            "complete_label": {
                "label_created": "confirmed",
                "label_service_unavailable": "none",
                "already_labeled": "none",
                "not_found": "none",
            },
            "get_reservation": {"found": "observed", "not_found": "observed"},
        }
        return str(contracts.get(op["tool"], op.get("effect_contract", {})).get(status, "unknown"))

    def _bind_document(
        self, entries: dict[str, Any], source_op: dict[str, Any], response: ToolMessage
    ) -> bool:
        assert self.binding is not None
        body = json.loads(str(response.content))
        affected = [
            op
            for op in self.binding["operations"]
            if source_op["operation_id"] in document_sources(op)
        ]
        resolved = self._application(entries)["resolved"]
        valid = (
            isinstance(body, dict)
            and body.get("title") == source_op["target"]["title"]
            and type(body.get("document_id")) is str
            and bool(body["document_id"])
            and type(body.get("document_version")) is int
            and body["document_version"] > 0
            and type(body.get("content")) is str
        )
        for op in affected:
            key = self.operation_key(self.binding, op["operation_id"])
            if valid:
                resolved[key] = {
                    **op["args"],
                    "document_version": body["document_version"],
                }
            else:
                resolved.pop(key, None)
        return valid

    def _bind_reservation(
        self, entries: dict[str, Any], query_op: dict[str, Any], response: ToolMessage
    ) -> bool:
        assert self.binding is not None
        binding = self.binding
        resolved_bindings = self._application(entries)["resolved"]
        label_ops = [
            op
            for op in self.binding["operations"]
            if op.get("reservation_from") == query_op["operation_id"]
        ]

        def invalidate() -> bool:
            for op in label_ops:
                resolved_bindings.pop(self.operation_key(binding, op["operation_id"]), None)
            return False

        try:
            result = json.loads(str(response.content))
        except ValueError:
            return invalidate()
        target = query_op["target"]
        if (
            not isinstance(result, dict)
            or result.get("status") != "found"
            or type(result.get("reservation_id")) is not str
            or result.get("label_status") not in {"created", "not_created"}
            or not result["reservation_id"]
            or any(
                self._canonical(result.get(field)) != self._canonical(target[field])
                for field in ("item_key", "quantity", "destination", "packing")
            )
        ):
            return invalidate()
        for op in label_ops:
            key = self.operation_key(self.binding, op["operation_id"])
            resolved = {"reservation_id": result["reservation_id"]}
            prior = resolved_bindings.get(key)
            if prior is not None and prior != resolved:
                raise ValueError("APPLICATION_RESERVATION_ID_CHANGED")
            resolved_bindings[key] = resolved
        return True

    def _protected_call(
        self,
        request: ToolCallRequest,
        execute: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        call, messages = request.tool_call, request.state["messages"]
        generated = messages[-1]
        if not isinstance(generated, AIMessage) or not generated.id:
            raise ValueError("BUSINESS_CALL_GENERATION_ID_MISSING")
        config = request.runtime.config["configurable"]
        thread_id = config["thread_id"]
        if self.binding is not None and (
            any(
                config.get(field) != self.binding[bfield]
                for field, bfield in (
                    ("thread_id", "thread_id"),
                    ("foundation_run_id", "run_id"),
                    ("arm_id", "arm_id"),
                    ("user_id", "owner"),
                )
            )
            or sum(isinstance(row, HumanMessage) for row in messages) - 1
            != self.binding["public_index"]
        ):
            raise ValueError("APPLICATION_CALL_SCOPE_CHANGED")
        entries = self._entries()
        key = self.call_key(entries, thread_id, generated.id, call["id"])
        binding_hash = self.binding_id
        prior = entries.get(key)
        if prior is not None:
            if (
                prior["name"] != call["name"]
                or self._canonical(prior["args"]) != self._canonical(call["args"])
                or prior.get("binding_id", prior.get("binding_hash")) != binding_hash
            ):
                raise ValueError("APPLICATION_CALL_IDENTITY_CHANGED")
            if prior["status"] != "complete":
                raise UnknownBusinessAction(f"BUSINESS_CALL_OUTCOME_UNKNOWN:{key}")
            return ToolMessage.model_validate(prior["result"])
        op, reason = self._select_operation(entries, call["name"], call["args"])
        origin = (
            "application_recovery"
            if generated.response_metadata.get("application_recovery")
            else "host"
        )
        row: dict[str, Any] = {
            "status": "pending",
            "thread_id": thread_id,
            "generation_id": generated.id,
            "call_id": call["id"],
            "name": call["name"],
            "args": call["args"],
            "journal_key": key,
            "binding_id": binding_hash,
            "origin": origin,
            "decision": "authorized" if op is not None else "blocked",
            "reason": reason,
            "executed": False,
            "effect": "none",
        }
        if op is not None:
            assert self.binding is not None
            row.update(
                operation_key=self.operation_key(self.binding, op["operation_id"]),
                operation_id=op["operation_id"],
                task_id=self.binding["task_id"],
                owner=self.binding["owner"],
                target=op["target"],
            )
        entries[key] = row
        if op is None:
            response = ToolMessage(
                content=json.dumps({"status": reason, "executed": False}),
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
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
            elif self.document_workflow:
                row["target_matched"] = self._bind_document(entries, op, response)
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
        return cast(
            dict[str, Any] | None,
            self._application(self._entries())["recoveries"].get(original_key),
        )
