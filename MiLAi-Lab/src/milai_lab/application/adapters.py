"""Thin, trusted application contract over the existing two local sandboxes.

The current caller grants permissions. A verified reference identifies a real
owner object; it never grants an operation or describes its current state.
Actual calls use the same business journal, source capture and projection as Host.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol, cast

from langchain_core.messages import AIMessage, ToolMessage

from milai_lab.application.refs import visible_verified_ref
from milai_lab.contracts.memory import VerifiedObjectRef

if TYPE_CHECKING:
    from milai_lab.application.functional import FunctionalApplication


class ApplicationAdapter(Protocol):
    """A new application implements these calls without changing memory core."""

    owner: str
    can_read: bool
    allowed_operations: frozenset[str]

    def lookup(self, target: Mapping[str, Any], *, attempt_id: str) -> dict[str, Any]: ...

    def execute(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        attempt_id: str,
        ref: VerifiedObjectRef | None = None,
    ) -> dict[str, Any]: ...

    def observe(self, ref: VerifiedObjectRef, *, attempt_id: str) -> dict[str, Any]: ...

    def discover(self, target: Mapping[str, Any], *, attempt_id: str) -> dict[str, Any]: ...

    def source_visible(self, source_ref: str) -> bool: ...


class SandboxApplicationAdapter:
    """Shared contract for reservations and versioned document publication."""

    def __init__(
        self,
        app: FunctionalApplication,
        service: Any,
        session: str,
        turn_id: str,
        *,
        allowed_operations: Sequence[str] = (),
        can_read: bool = True,
        runtime_config: Mapping[str, Any] | None = None,
    ) -> None:
        self.app, self.service = app, service
        self.owner, self.session, self.turn_id = app.owner, session, turn_id
        self.can_read, self.allowed_operations = can_read, frozenset(allowed_operations)
        self.query = (
            "get_document_status"
            if app.workflow == "document_publication_v1"
            else "get_reservation"
        )
        if not self.allowed_operations <= set(app.tool_names) - {self.query}:
            raise ValueError("APPLICATION_ADAPTER_OPERATION_INVALID")
        self.runtime_config = dict(
            runtime_config
            or {
                "max_concurrency": 1,
                "configurable": {
                    "user_id": self.owner,
                    "thread_id": self.owner + ":" + session,
                },
            }
        )
        self.wrapper = app.call_wrapper(
            service, session, turn_id, runtime_config=self.runtime_config
        )

    def _denied(self, status: str) -> dict[str, Any]:
        return {
            "status": status,
            "executed": False,
            "business_effect": "none",
            "object_ref": None,
            "current_state": None,
            "permissions": {
                "can_read": self.can_read,
                "operations": sorted(self.allowed_operations),
            },
        }

    def lookup(self, target: Mapping[str, Any], *, attempt_id: str) -> dict[str, Any]:
        if not self.can_read:
            return self._denied("access_revoked")
        return self._call(self.query, target, attempt_id)

    def wrap_tool_call(
        self,
        request: Any,
        execute: Callable[[Any], Any],
    ) -> ToolMessage:
        """Normal Host call path, preserving the original call/journal identity.

        The caller may install its existing FunctionalCallWrapper as ``wrapper``
        to retain its trace, delivery settings and fault hooks. No request,
        generation ID, tool-call ID, runtime config or arguments are rewritten.
        Existing objects require a reference from an actually delivered tool
        source, rather than a correct-looking external ID in memory prose.
        """
        call = request.tool_call
        name, arguments = call["name"], call["args"]
        reason = None
        if name in self.app.tool_names:
            if not self.can_read:
                reason = "access_revoked"
            elif name != self.query and name not in self.allowed_operations:
                reason = "operation_not_authorized_current_request"
            elif name in {
                "complete_label",
                "approve_document_version",
                "publish_approved_document",
            } or (name == "create_or_update_draft" and arguments.get("document_version", 0) != 0):
                if self._delivered_ref(request.state["messages"], name, arguments) is None:
                    reason = "verified_object_reference_required"
        if reason is not None:
            denial = self._denied(reason)
            if reason == "verified_object_reference_required":
                denial["next_step"] = {
                    "tool": self.query,
                    "arguments": self._query_target(name, arguments),
                    "instruction": "Read the exact current owner object, then use its actual "
                    "returned identity and observed version for the remaining operation.",
                }
            return ToolMessage(
                name=name,
                tool_call_id=call["id"],
                status="error",
                content=json.dumps(denial, ensure_ascii=False),
            )
        return cast(ToolMessage, self.wrapper(request, execute))

    def _delivered_ref(
        self,
        messages: Sequence[Any],
        operation: str,
        arguments: Mapping[str, Any],
    ) -> VerifiedObjectRef | None:
        for message in reversed(messages):
            if not isinstance(message, ToolMessage) or message.name not in self.app.tool_names:
                continue
            try:
                delivery = json.loads(str(message.content))
            except json.JSONDecodeError:
                continue
            if not isinstance(delivery, dict):
                continue
            if delivery.get(
                "status"
            ) == "ORIGINAL_CALL_OUTCOME_UNKNOWN" and message.additional_kwargs.get(
                "application_recovery"
            ):
                source_ref = delivery.get("query_source", {}).get("source_ref")
                origin = self.query
            else:
                source_ref = delivery.get("source_ref")
                origin = message.name
            source = self.service.source(source_ref) if source_ref else None
            if (
                source is None
                or source.get("role") != "tool"
                or source.get("origin") != origin
                or not source.get("object_ref")
            ):
                continue
            resolved = self._target_for_ref(VerifiedObjectRef(**source["object_ref"]))
            if resolved is None:
                continue
            issued, target = resolved
            if operation == "complete_label":
                if arguments.get("reservation_id") == issued.external_id:
                    return issued
            elif arguments.get("title") == target["title"] and (
                arguments.get("document_version") == issued.fields["document_version"]
            ):
                return issued
        return None

    def _query_target(self, operation: str, arguments: Mapping[str, Any]) -> dict[str, Any] | None:
        if self.app.workflow == "document_publication_v1":
            return {"title": arguments["title"]}
        if operation != "complete_label":
            return {"item_key": arguments["item_key"]}
        # A query hint uses actual owner-scoped identity, not a guessed exact key.
        with self.app.world.tool_lock:
            row = self.app.world.conn.execute(
                "SELECT item_key FROM reservations WHERE user_id=? AND reservation_id=?",
                (self.owner, arguments["reservation_id"]),
            ).fetchone()
        return {"item_key": row["item_key"]} if row is not None else None

    def execute(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        attempt_id: str,
        ref: VerifiedObjectRef | None = None,
    ) -> dict[str, Any]:
        if not self.can_read:
            return self._denied("access_revoked")
        if operation not in self.allowed_operations:
            return self._denied("operation_not_authorized_current_request")
        arguments = dict(arguments)
        if ref is not None:
            resolved = self._target_for_ref(ref)
            if resolved is None:
                return self._denied("object_reference_scope_mismatch_or_missing")
            ref, target = resolved
            if self.app.workflow == "document_publication_v1":
                arguments["title"] = target["title"]
                arguments.setdefault("document_version", ref.fields["document_version"])
            elif operation == "complete_label":
                arguments["reservation_id"] = ref.external_id
        elif operation in {
            "complete_label",
            "approve_document_version",
            "publish_approved_document",
        }:
            return self._denied("verified_object_reference_required")
        return self._call(operation, arguments, attempt_id)

    def observe(self, ref: VerifiedObjectRef, *, attempt_id: str) -> dict[str, Any]:
        """Return a new actual observation without upgrading the old reference."""
        if not self.can_read:
            return self._denied("access_revoked")
        resolved = self._target_for_ref(ref)
        if resolved is None:
            return self._denied("object_reference_scope_mismatch_or_missing")
        _issued, target = resolved
        return self.lookup(target, attempt_id=attempt_id)

    def _target_for_ref(
        self,
        ref: VerifiedObjectRef,
    ) -> tuple[VerifiedObjectRef, dict[str, Any]] | None:
        if (
            ref.owner != self.owner
            or ref.application != self.app.observation_profile.application
            or not self.source_visible(ref.source_ref)
        ):
            return None
        issued = visible_verified_ref(self.service, ref)
        if issued is None:
            return None
        table, identity, selector = (
            ("documents", "document_id", "title")
            if self.app.workflow == "document_publication_v1"
            else ("reservations", "reservation_id", "item_key")
        )
        # Table/column names are fixed adapter constants; the object ID is bound.
        with self.app.world.tool_lock:
            row = self.app.world.conn.execute(
                f"SELECT {selector} FROM {table} WHERE user_id=? AND {identity}=?",  # noqa: S608
                (self.owner, ref.external_id),
            ).fetchone()
        if row is None:
            return None
        return issued, {selector: row[selector]}

    def discover(self, target: Mapping[str, Any], *, attempt_id: str) -> dict[str, Any]:
        """A real journaled read reconciles pending effects, preserving unknown calls."""
        result = self.lookup(target, attempt_id=attempt_id)
        unresolved = []
        for row in self.app.journal._entries().values():
            if (
                isinstance(row, dict)
                and row.get("owner") == self.owner
                and row.get("target") == dict(target)
                and row.get("status") == "pending"
                and row.get("effect") == "unknown"
            ):
                recovery = self.app.journal.recovery_for_call(row["journal_key"])
                if recovery is None or recovery["effect"] == "unknown":
                    unresolved.append(row["journal_key"])
        result["unknown_effects"] = unresolved
        return result

    def source_visible(self, source_ref: str) -> bool:
        return bool(self.can_read and self.service.source(source_ref) is not None)

    def _call(
        self,
        name: str,
        arguments: Mapping[str, Any],
        attempt_id: str,
    ) -> dict[str, Any]:
        call = {"name": name, "args": dict(arguments), "id": attempt_id, "type": "tool_call"}
        request = SimpleNamespace(
            tool_call=call,
            state={"messages": [AIMessage(content="", id=attempt_id)]},
            runtime=SimpleNamespace(config=self.runtime_config),
        )
        tool = next(tool for tool in self.app.tools if tool.name == name)
        result = self.wrapper(request, lambda _: tool.invoke(call))
        if not isinstance(result, ToolMessage):
            raise TypeError("APPLICATION_ADAPTER_TOOL_RECEIPT_REQUIRED")
        payload = json.loads(str(result.content))
        receipt = payload.get("receipt", payload)
        source_ref = payload.get("source_ref")
        source = self.service.source(source_ref) if source_ref else None
        ref = (
            VerifiedObjectRef(**source["object_ref"])
            if source and source.get("object_ref")
            else None
        )
        row = self.app.journal.entry_for_call(
            self.runtime_config["configurable"]["thread_id"],
            attempt_id,
            attempt_id,
        )
        return {
            "status": receipt["status"],
            "executed": bool(row and row.get("executed")),
            "operation": name,
            "attempt_id": attempt_id,
            "receipt": receipt,
            "source_ref": source_ref,
            "object_ref": asdict(ref) if ref else None,
            "current_state": receipt,
            "business_effect": row["effect"] if row else "unknown",
            "permissions": {
                "can_read": self.can_read,
                "operations": sorted(self.allowed_operations),
            },
            "raw_capture": payload.get("raw_capture"),
            "observation_projection": payload.get("observation_projection"),
            "delivery_response": result.model_dump(mode="json"),
            "semantic_maintenance": {"status": "not_requested"},
        }
