"""Legacy adapters; all models share the neutral observation projection."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from milai_lab.methods.control_observation import (
    ACTION_BINDING_INSTRUCTIONS as ACTION_BINDING_INSTRUCTIONS,
)
from milai_lab.methods.control_observation import (
    ACTION_BOUND_PROJECTIONS as ACTION_BOUND_PROJECTIONS,
)
from milai_lab.methods.control_observation import (
    COMPACT_ACTION_PROJECTIONS as COMPACT_ACTION_PROJECTIONS,
)
from milai_lab.methods.control_observation import (
    INSTRUCTIONS as INSTRUCTIONS,
)
from milai_lab.methods.control_observation import (
    RETRIEVAL_INSTRUCTIONS as RETRIEVAL_INSTRUCTIONS,
)
from milai_lab.methods.control_observation import (
    complete_action_payload as complete_action_payload,
)
from milai_lab.methods.control_observation import (
    operation_payload as operation_payload,
)
from milai_lab.methods.control_observation import (
    payload_actions as payload_actions,
)
from milai_lab.methods.control_observation import (
    project_operation_payload as project_operation_payload,
)
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState


@dataclass
class LayaMemoryPolicy:
    predict: Callable[[dict[str, Any]], dict[str, Any]]
    projection: str = "full"

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        result = self.predict(operation_payload(state, actions, self.projection))
        return str(result["choice"])


@dataclass
class GenerativeMemoryPolicy:
    call: Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]
    projection: str = "full"

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        payload = operation_payload(state, actions, self.projection)
        schema = {"type": "object", "properties": {"choice": {
            "type": "string", "enum": [a.id for a in actions]}},
            "required": ["choice"], "additionalProperties": False}
        result = self.call("memory_control", [{"role": "system",
            "content": payload["questions"]["next"]["instructions"]},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], schema)
        return str(result["choice"])
