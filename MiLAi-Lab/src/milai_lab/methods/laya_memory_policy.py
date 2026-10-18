"""One operation projection for native Laya, generation and training exports."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from milai_lab.methods.memory_control import MemoryAction, MemoryControlState

INSTRUCTIONS = (
    "Choose the next memory operation for the original task using actual observations. "
    "Candidate excerpts are navigation, not delivered evidence. USE_VIEW opens an existing "
    "source-bound interpretation without generation; REFRESH_VIEW generates an interpretation "
    "from the specified actual sources. Consider subject, report/effective time, scope and "
    "new exceptions. HANDOFF sends only opened material to the Reader; it cannot fill missing "
    "facts. Read necessary available evidence before handoff, and avoid repeating work when "
    "the delivered material already supports the task. A tool receipt is not semantic proof."
)


def operation_payload(state: MemoryControlState, actions: list[MemoryAction]) -> dict[str, Any]:
    return {"state": state.project(), "questions": {"next": {
        "type": "choice", "instructions": INSTRUCTIONS,
        "criteria": {action.id: f"{action.kind} {action.target} "
                     + json.dumps(action.parameters, ensure_ascii=False, separators=(",", ":"))
                     for action in actions},
    }}}


@dataclass
class LayaMemoryPolicy:
    predict: Callable[[dict[str, Any]], dict[str, Any]]

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        result = self.predict(operation_payload(state, actions))
        return str(result["choice"])


@dataclass
class GenerativeMemoryPolicy:
    call: Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        payload = operation_payload(state, actions)
        schema = {"type": "object", "properties": {"choice": {
            "type": "string", "enum": [a.id for a in actions]}},
            "required": ["choice"], "additionalProperties": False}
        result = self.call("memory_control", [{"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], schema)
        return str(result["choice"])
