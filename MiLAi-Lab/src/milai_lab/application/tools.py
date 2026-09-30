"""Native schema adapters and owner-bound reservation tools."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from milai_lab.application.world import ApplicationWorld


def native_business_tools(
    world: Any,
    schemas: Sequence[Mapping[str, Any]],
    functions: Mapping[str, Callable[..., str]],
) -> list[BaseTool]:
    """Keep each upstream MERIT schema and exact JSON tool output."""
    result: list[BaseTool] = []
    for schema in schemas:
        definition = schema["function"]
        name = definition["name"]
        function = functions[name]

        def execute(*, _function: Callable[..., str] = function, **arguments: Any) -> str:
            try:
                return _function(world, **arguments)
            except TypeError as error:
                return json.dumps({"error": f"invalid arguments: {error}"})

        result.append(StructuredTool.from_function(
            func=execute,
            name=name,
            description=definition["description"],
            args_schema=definition["parameters"],
            infer_schema=False,
        ))
    return result


BUSINESS_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "reserve_and_label",
        "description": (
            "Reserve an item for the current user and attempt its label. "
            "A failed label may leave a real reservation. One call is one attempt."),
        "parameters": {"type": "object", "properties": {
            "item_key": {"type": "string", "description": (
                "Copy the complete item reference including qualifiers; use this same exact "
                "key for later reads.")},
            "quantity": {"type": "integer", "minimum": 1},
            "destination": {"type": "string"}, "packing": {"type": "string"}},
            "required": ["item_key", "quantity", "destination", "packing"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "get_reservation",
        "description": "Read the current user's actual reservation and label state for an item.",
        "parameters": {"type": "object", "properties": {
            "item_key": {"type": "string", "description": (
                "Copy the complete item reference including qualifiers; use the exact "
                "key used for the reservation.")}}, "required": ["item_key"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "complete_label",
        "description": (
            "Create the label for the current user's existing reservation. "
            "This does not reserve again or dispatch anything."),
        "parameters": {"type": "object", "properties": {
            "reservation_id": {"type": "string"}}, "required": ["reservation_id"],
            "additionalProperties": False}}},
]
BUSINESS_NAMES = [entry["function"]["name"] for entry in BUSINESS_SCHEMAS]


def _business_tools(world: ApplicationWorld, user_id: str) -> list[Any]:
    def invoke(method: Callable[..., str], **arguments: Any) -> str:
        with world.tool_lock:
            return method(user_id, **arguments)

    functions = {
        "reserve_and_label": lambda _world, **args: invoke(world.reserve_and_label, **args),
        "get_reservation": lambda _world, **args: invoke(world.get_reservation, **args),
        "complete_label": lambda _world, **args: invoke(world.complete_label, **args),
    }
    return native_business_tools(None, BUSINESS_SCHEMAS, functions)


def document_business_tools(world: Any, user_id: str) -> list[BaseTool]:
    from milai_lab.application.document_publication import DOCUMENT_NAMES, document_schemas

    def execute(name: str, **arguments: Any) -> str:
        with world.tool_lock:
            return str(getattr(world, name)(user_id, **arguments))

    functions = {
        name: (lambda _world, _name=name, **args: execute(_name, **args)) for name in DOCUMENT_NAMES
    }
    return native_business_tools(None, document_schemas(), functions)
