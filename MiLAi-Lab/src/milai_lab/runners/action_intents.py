"""Capture-only tool catalogs for external action-intent evaluation."""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field


def json_parameter_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate the release's Python type spellings at schema nodes only.

    Descriptions, property names, defaults, enums and example values are data;
    they remain literal even when they contain a key or value named `type`.
    Unknown type names are not guessed or replaced by a permissive schema.
    """
    aliases = {"dict": "object", "int": "integer", "float": "number"}
    result = copy.deepcopy(schema)

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if "type" in node:
            value = node["type"]
            node["type"] = ([aliases.get(item, item) for item in value]
                            if isinstance(value, list) else aliases.get(value, value))
        for key in ("properties", "patternProperties", "$defs", "definitions",
                    "dependentSchemas", "dependencies"):
            for child in node.get(key, {}).values():
                visit(child)
        for key in ("items", "additionalItems", "additionalProperties", "contains",
                    "propertyNames", "not", "if", "then", "else", "contentSchema"):
            value = node.get(key)
            if isinstance(value, list):
                for child in value:
                    visit(child)
            else:
                visit(value)
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            for child in node.get(key, []):
                visit(child)

    visit(result)
    return result


class RecordingTool(BaseTool):
    """Keep model argument names separate from framework execution options."""

    record: Callable[[dict[str, Any]], None] = Field(exclude=True, repr=False)

    def _run(self, /, **arguments: Any) -> str:
        self.record({"name": self.name, "arguments": copy.deepcopy(arguments)})
        return json.dumps({"status": "intent_recorded", "business_executed": False})


def recording_tools(
    schemas: list[dict[str, Any]], record: Callable[[dict[str, Any]], None],
) -> tuple[BaseTool, ...]:
    """Translate only schema type spellings; record arguments without effects."""
    return tuple(RecordingTool(name=schema["name"], description=schema["description"],
                 args_schema=json_parameter_schema(schema["parameters"]), record=record)
                 for schema in schemas)


def proposed_business_calls(
    messages: list[dict[str, Any]], *, memory_tool_names: set[str],
) -> list[dict[str, Any]]:
    """All current-task proposals, including invalid/rejected/unknown business calls.

    Input is the runner's public message records. A caller never selects the best
    successful tool receipt as the prediction. Malformed arguments remain literal.
    """
    return [{"name": call["name"], "arguments": copy.deepcopy(call["args"])}
            for message in messages if message["type"] == "ai"
            for call in [*message.get("tool_calls", []), *message.get("invalid_tool_calls", [])]
            if call["name"] not in memory_tool_names]
