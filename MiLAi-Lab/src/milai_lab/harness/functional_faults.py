"""Evaluator-only backend controls, never prompt material or memory evidence.

The two W1 branches expose the same interruption. Actual hidden backend state
can be learned by the assistant only through its ordinary public tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


class InjectedInterruption(RuntimeError):
    pass


class FunctionalFaults:
    def __init__(self, path: Path, control: dict[str, Any], message_index: int) -> None:
        self.path, self.control, self.message_index = path, control, message_index
        self.state = read_json(path) if path.exists() else {"events": {}, "fault": None}

    def before_message(self, app: Any) -> None:
        for event in self.control.get("before_message_events", []):
            if event["before_message_index"] != self.message_index:
                continue
            key = event["event_id"]
            if key in self.state["events"]:
                continue
            operation, world = event["operation"], app.world
            if operation == "reservation.set_label_available":
                world.set_label_available(key, event["available"])
                receipt = {"event_id": key, "available": event["available"]}
            elif operation == "document.set_publication_available":
                world.set_publication_available(key, event["available"])
                receipt = {"event_id": key, "available": event["available"]}
            elif operation == "reservation.external_complete_existing_label":
                lookup = json.loads(world.get_reservation(app.owner, event["lookup_item_key"]))
                if lookup.get("status") != "found":
                    raise ValueError("FUNCTIONAL_EXTERNAL_EVENT_TARGET_UNAVAILABLE")
                receipt = json.loads(world.complete_label(app.owner, lookup["reservation_id"]))
            elif operation == "document.external_edit":
                receipt = world.apply_backend_event(
                    key,
                    owner=app.owner,
                    edit={"title": event["title"], "content": event["new_body"]},
                )
            else:
                raise ValueError("FUNCTIONAL_EVALUATOR_OPERATION_UNSUPPORTED")
            self.state["events"][key] = {"control": event, "actual_receipt": receipt}
            write_json(self.path, self.state)

    def _fault(self, boundary: str, tool: str) -> None:
        fault = self.control.get("one_shot_fault")
        if (
            not fault
            or self.state["fault"] is not None
            or fault["message_index"] != self.message_index
            or fault["boundary"] != boundary
            or fault["target_operation"] != tool
        ):
            return
        if fault.get("occurrence", 1) != 1:
            raise ValueError("FUNCTIONAL_FAULT_OCCURRENCE_UNSUPPORTED")
        self.state["fault"] = {
            "applied": True,
            "boundary": boundary,
            "tool": tool,
            "message_index": self.message_index,
        }
        write_json(self.path, self.state)
        raise InjectedInterruption("Operation result delivery interrupted; outcome unknown.")

    def before_native(self, request: Any) -> None:
        self._fault("after_journal_intent_before_native", request.tool_call["name"])

    def after_native(self, row: dict[str, Any], response: Any) -> None:
        self._fault("after_native_before_journal_complete", row["name"])

    def boundary(self, window: str, event: dict[str, Any]) -> None:
        self._fault(window, event.get("tool", ""))
