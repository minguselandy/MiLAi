"""Link normal Host calls to already registered request stages.

The Root dispatcher supplies the current tool permissions. This adapter owns no
query, model, memory maintenance or additional database; actual dispatch still
uses the ordinary application adapter and its native journal.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import AIMessage, ToolMessage

from milai_lab.application.recovery import _resume_result
from milai_lab.application.request_plans import project_stage_receipt

if TYPE_CHECKING:
    from milai_lab.application.adapters import SandboxApplicationAdapter
    from milai_lab.application.functional import FunctionalApplication


def _visible_request(app: FunctionalApplication, service: Any, row: dict[str, Any]) -> bool:
    binding = row.get("binding") or {}
    source = service.source(binding.get("source_ref")) if binding.get("source_ref") else None
    return bool(
        row["identity"].get("name") == "resume_request"
        and row["identity"].get("owner") == app.owner
        and binding.get("workflow") == app.workflow
        and source is not None
        and source.get("role") == "user"
    )


def visible_cards(
    app: FunctionalApplication | None,
    service: Any,
    current_source_ref: str,
    *,
    pending_maintenance: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Issue bounded application and existing explicit-save references, without rights."""
    cards = []
    if app is not None:
        for row in app.progress.snapshot().values():
            if not _visible_request(app, service, row):
                continue
            binding = row["binding"]
            if binding["source_ref"] == current_source_ref:
                continue
            request_id = row["identity"]["call_id"]
            cards.append(
                {
                    "request_id": request_id,
                    "requirements": deepcopy(row["requirements"]),
                    "binding": deepcopy(binding),
                    "progress": _resume_result(
                        request_id, row["request_progress"],
                        lambda ref: service.source(ref) is not None,
                    ),
                    "user_fragments": service.source_fragments(binding["source_ref"]),
                }
            )
    for pending in pending_maintenance or []:
        refs = pending["source_refs"]
        sources = [service.source(ref) for ref in refs]
        if not refs or current_source_ref in refs or any(source is None for source in sources):
            continue
        cards.append({
            **deepcopy(pending), "kind": "memory_maintenance",
            "user_fragments": [part for ref, source in zip(refs, sources, strict=True)
                               if source["role"] == "user"
                               for part in service.source_fragments(ref)],
        })
    return cards[-12:]


class HostRequestProgress:
    """Persist original intent and link actual Host calls without executing a plan."""

    def __init__(
        self,
        app: FunctionalApplication,
        adapter: SandboxApplicationAdapter,
        service: Any,
        binding: Mapping[str, Any],
        mode: Mapping[str, Any],
        requirements: list[dict[str, Any]],
        prior_request_ids: list[str],
    ) -> None:
        self.app, self.adapter, self.service = app, adapter, service
        self.binding, self.mode = deepcopy(dict(binding)), deepcopy(dict(mode))
        self.request_ids: list[str] = []
        original_plans = []
        for request_id in prior_request_ids:
            _, row = self.app.progress.request_state(app.owner, request_id, None)
            if not _visible_request(app, service, row):
                raise ValueError("HOST_PRIOR_APPLICATION_REQUEST_UNAVAILABLE")
            if request_id not in self.request_ids:
                self.request_ids.append(request_id)
                original_plans.append(row["requirements"])
        for index, plan in enumerate(requirements):
            prior_plans = [old for old in original_plans if old["target"] == plan["target"]]
            if prior_plans and (
                self.mode.get("business_action_request") != "perform"
                or any(all(step in old["steps"] for step in plan["steps"]) for old in prior_plans)
            ):
                # Continuation keeps the complete original request. An explicit
                # new action with changed arguments has its own current binding.
                continue
            request_id = str(binding["source_ref"]) + ":application:" + str(index)
            self.app.progress.request_state(
                app.owner,
                request_id,
                plan,
                binding={**self.binding, "workflow": app.workflow},
            )
            self.request_ids.append(request_id)
        self.dirty = bool(prior_request_ids)

    def rows(self) -> list[tuple[str, dict[str, Any]]]:
        """Read current selected progress and recheck original input visibility."""
        rows = []
        for request_id in self.request_ids:
            key, row = self.app.progress.request_state(self.app.owner, request_id, None)
            if _visible_request(self.app, self.service, row):
                rows.append((key, row))
        return rows

    def snapshot(self) -> list[dict[str, Any]]:
        """A current visible frame with no application discovery or maintenance."""
        return [
            _resume_result(
                row["identity"]["call_id"], row["request_progress"], self.adapter.source_visible
            )
            for _, row in self.rows()
        ]

    def _target(self, request: Any) -> dict[str, Any] | None:
        name, arguments = request.tool_call["name"], request.tool_call["args"]
        if name != "complete_label":
            field = "title" if self.app.workflow == "document_publication_v1" else "item_key"
            return {field: arguments[field]}
        for message in reversed(request.state["messages"]):
            if not isinstance(message, ToolMessage) or message.name not in self.app.tool_names:
                continue
            try:
                payload = json.loads(str(message.content))
            except json.JSONDecodeError:
                continue
            source_ref = payload.get("source_ref") or payload.get("query_source", {}).get(
                "source_ref"
            )
            source = self.service.source(source_ref) if source_ref else None
            if (
                source is None
                or source.get("role") != "tool"
                or source.get("origin")
                not in {
                    "get_reservation",
                    "reserve_and_label",
                    "complete_label",
                }
            ):
                continue
            receipt = json.loads(source["content"])
            if receipt.get("reservation_id") == arguments["reservation_id"]:
                return {"item_key": receipt["item_key"]}
        return None

    @staticmethod
    def _identity(request: Any) -> dict[str, Any]:
        generated, call = request.state["messages"][-1], request.tool_call
        if not isinstance(generated, AIMessage) or not generated.id or not call.get("id"):
            raise ValueError("HOST_APPLICATION_CALL_IDENTITY_REQUIRED")
        return {
            "thread_id": request.runtime.config["configurable"]["thread_id"],
            "generation_id": generated.id,
            "call_id": call["id"],
            "name": call["name"],
            "args": deepcopy(call["args"]),
        }

    @staticmethod
    def _attempt(progress: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any] | None:
        for attempt in progress["attempts"]:
            old = attempt.get("call_identity")
            if old and all(
                old[field] == identity[field] for field in ("thread_id", "generation_id", "call_id")
            ):
                if old != identity:
                    raise ValueError("HOST_APPLICATION_CALL_IDENTITY_CHANGED")
                return cast(dict[str, Any], attempt)
        return None

    def _unresolved(self, progress: dict[str, Any]) -> bool:
        for attempt in progress["attempts"]:
            if attempt["status"] != "unknown":
                continue
            identity = attempt["call_identity"]
            entry = self.app.journal.entry_for_call(
                identity["thread_id"],
                identity["generation_id"],
                identity["call_id"],
            )
            if entry is None:
                return True
            if entry["status"] != "complete":
                recovery = self.app.journal.recovery_for_call(entry["journal_key"])
                if recovery is None or recovery["effect"] == "unknown":
                    return True
        return False

    def wrap_call(self, request: Any, execute: Callable[[Any], Any]) -> ToolMessage:
        """Dispatch only a registered, currently authorized actual Host call."""
        try:
            return self._wrap_call(request, execute)
        finally:
            self.dirty = True

    def _wrap_call(self, request: Any, execute: Callable[[Any], Any]) -> ToolMessage:
        name, arguments = request.tool_call["name"], request.tool_call["args"]
        if name in {"get_reservation", "get_document_status"}:
            return self.adapter.wrap_tool_call(request, execute)
        if not self.adapter.can_read or name not in self.adapter.allowed_operations:
            return self.adapter.wrap_tool_call(request, execute)
        identity, target = self._identity(request), self._target(request)
        selected: dict[str, dict[str, Any]] = {}
        matched: list[tuple[str, int]] = []
        rows = self.rows()
        current_targets = [
            row["requirements"]["target"]
            for _, row in rows
            if row["binding"]["source_ref"] == self.binding["source_ref"]
        ]
        for key, row in rows:
            plan = row["requirements"]
            if plan["target"] != target:
                continue
            if (
                self.mode.get("business_action_request") == "perform"
                and target in current_targets
                and row["binding"]["source_ref"] != self.binding["source_ref"]
            ):
                continue
            for index, step in enumerate(plan["steps"]):
                if step["operation"] != name or not all(
                    arguments.get(field) == value
                    for field, value in step.get("arguments", {}).items()
                    if field not in step.get("arguments_from_state", {})
                ):
                    continue
                selected[key] = row
                matched.append((key, index))
                if name == "reserve_and_label":
                    matched.extend(
                        (key, other)
                        for other, stage in enumerate(plan["steps"])
                        if stage["operation"] == "complete_label"
                    )
        if not matched:
            return self._denied(request, "request_plan_not_registered")
        for key, index in matched:
            progress = selected[key]["request_progress"]["business"]["steps"][index]
            original = self._attempt(progress, identity)
            if original is None and self._unresolved(progress):
                return self._denied(request, "request_step_outcome_unknown_query_required")
            if original is None and (
                progress["status"] in {"completed", "superseded"}
                or any(
                    attempt.get("result", {}).get("business_effect") in {"confirmed", "partial"}
                    for attempt in progress["attempts"]
                )
            ):
                return self._denied(request, "request_step_already_completed")
        attempt_id = json.dumps(
            [identity[field] for field in ("thread_id", "generation_id", "call_id")],
            ensure_ascii=False,
        )
        for key, index in matched:
            progress = selected[key]["request_progress"]["business"]["steps"][index]
            if self._attempt(progress, identity) is None:
                progress["attempts"].append(
                    {
                        "attempt_id": attempt_id,
                        "status": "unknown",
                        "call_identity": deepcopy(identity),
                        "binding": deepcopy(self.binding),
                    }
                )
                progress["status"] = "unknown"
        for key, row in selected.items():
            self.app.progress.save_request_state(key, row["request_progress"])
        try:
            response = self.adapter.wrap_tool_call(request, execute)
        except BaseException as error:
            for key, index in matched:
                progress = selected[key]["request_progress"]["business"]["steps"][index]
                attempt = self._attempt(progress, identity)
                assert attempt is not None
                if attempt["status"] != "complete":
                    attempt.setdefault(
                        "error", {"type": type(error).__name__, "message": str(error)}
                    )
                    progress["status"] = "unknown"
                    selected[key]["request_progress"]["business"]["status"] = "business_unknown"
            for key, row in selected.items():
                self.app.progress.save_request_state(key, row["request_progress"])
            raise
        entry = self.app.journal.entry_for_call(
            identity["thread_id"],
            identity["generation_id"],
            identity["call_id"],
        )
        payload = json.loads(str(response.content))
        receipt = payload.get("receipt", payload)
        source_ref = payload.get("source_ref")
        source = self.service.source(source_ref) if source_ref else None
        result = {
            "status": receipt.get("status"),
            "executed": bool(entry and entry.get("executed")),
            "operation": name,
            "attempt_id": attempt_id,
            "receipt": receipt,
            "source_ref": source_ref,
            "object_ref": source.get("object_ref") if source else None,
            "current_state": receipt,
            "business_effect": entry["effect"] if entry else "none",
            "call_identity": identity,
            "journal_key": entry["journal_key"] if entry else None,
            "delivery_response": response.model_dump(mode="json"),
        }
        for key, index in matched:
            row = selected[key]
            progress = row["request_progress"]["business"]["steps"][index]
            attempt = self._attempt(progress, identity)
            assert attempt is not None
            projected = project_stage_receipt(row["requirements"]["steps"][index], result)
            if attempt["status"] == "complete":
                # Replaying an original call retains its first durable stage
                # result even when today's permissions or object state differ.
                continue
            attempt.update(status="complete", result=projected)
            progress["status"] = "completed" if projected["stage_satisfied"] else "incomplete"
            if projected["stage_satisfied"]:
                progress["completion_source"] = source_ref
        for key, row in selected.items():
            business = row["request_progress"]["business"]
            business["status"] = (
                "completed"
                if all(stage["status"] == "completed" for stage in business["steps"])
                else "partial"
                if any(stage["status"] == "completed" for stage in business["steps"])
                else "incomplete"
            )
            self.app.progress.save_request_state(key, row["request_progress"])
        return response

    @staticmethod
    def _denied(request: Any, status: str) -> ToolMessage:
        return ToolMessage(
            name=request.tool_call["name"],
            tool_call_id=request.tool_call["id"],
            status="error",
            content=json.dumps(
                {"ok": False, "status": status, "effect": "none", "executed": False}
            ),
        )
