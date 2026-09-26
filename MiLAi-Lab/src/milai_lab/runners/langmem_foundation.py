"""Narrow native business boundary and durable call receipts for the LangMem baseline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from milai_lab.harness.contextual_artifacts import read_json, write_json


class UnknownBusinessAction(RuntimeError):
    """A prior call entered native execution but has no durable result."""


class BusinessActionJournal:
    def __init__(self, path: Path, business_names: Sequence[str]) -> None:
        self.path = path
        self.business_names = frozenset(business_names)

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
        return [entry for entry in self._entries().values() if entry["thread_id"] == thread_id]

    def entry_for_call(self, thread_id: str, generation_id: str,
                       call_id: str) -> dict[str, Any] | None:
        identity = [thread_id, generation_id, call_id]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        return self._entries().get(key)


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
