"""Explicit LangMem research recipe hooks over the generic accounted chat bridge."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, cast

from milai_lab.methods.freshness_projection.projection import SOURCE_AUTHORITY, ProjectedRequest
from milai_lab.methods.memory_boundaries import MemoryBoundaryView
from milai_lab.methods.memory_result import (
    CORRECTION_TOOLS,
    RESULT_PROTOCOL,
    correction_marker,
    result_schema,
    turn_receipts,
    verify_result,
)
from milai_lab.methods.milai_m1.controller import M1_PROTOCOL, m1_action_schema
from milai_lab.methods.on_demand_reconstruction.schema import (
    ODR_PROTOCOL,
    ReconstructionError,
    odr_action_schema,
)
from milai_lab.providers.chat_bridge import (
    IncompleteChatResponse,
    VLLMChatModel,
    _action_prompt,
    _action_schema,
    _json_action_history,
    _protocol_messages,
)
from milai_lab.providers.request_pipeline import ChatRequest, PreparedRequest, ResponseEvent


def _recipe_action_schema(
    tools: list[dict[str, Any]], *, generation_only: bool = False, memory_result: bool = False
) -> dict[str, Any]:
    schema = _action_schema(tools, generation_only=generation_only)
    if memory_result:
        final = schema["oneOf"][0]
        final["properties"]["memory_result"] = result_schema()
        final["required"].append("memory_result")
    return schema


def _recipe_action_prompt(
    tools: list[dict[str, Any]],
    *,
    memory_result: bool = False,
    tool_schema_communication: str = "legacy",
    tool_save_communication: str = "legacy",
) -> str:
    prompt = _action_prompt(tools, tool_schema_communication=tool_schema_communication,
                            tool_save_communication=tool_save_communication)
    if memory_result:
        prompt = prompt.replace(
            'For a final reply use {"answer":"..."}. ',
            "For a final reply include answer and memory_result. ",
        )
        prompt += "\n" + RESULT_PROTOCOL
    return prompt


@dataclass
class _RecipeAttachment:
    memory_receipts: list[dict[str, Any]]
    m1_context: str | None = None
    odr_freshness: str = ""
    projected: ProjectedRequest | None = None
    delivered_snapshot: tuple[list[dict[str, Any]], int] | None = None


class LangMemRecipeChatModel(VLLMChatModel):
    """Own live method state and assemble hooks; generation stays in the generic base."""

    observer: Any = None
    m1: Any = None
    odr: Any = None
    projection: Any = None
    request_view: Any = None
    memory_protocol: str | None = None
    memory_turn: dict[str, str] | None = None
    research_profile: str | None = None

    def model_post_init(self, context: Any) -> None:
        super().model_post_init(context)
        self.request_transform = _RecipeRequestTransform(self)
        self.delivery_observer = _RecipeDeliveryObserver(self)
        self.response_hook = _RecipeResponseHook(self)


class _RecipeRequestTransform:
    def __init__(self, model: LangMemRecipeChatModel) -> None:
        self.model = model

    def validate(self, request: ChatRequest) -> None:
        model = self.model
        boundary = isinstance(model.request_view, MemoryBoundaryView)
        if request.native and (
            model.memory_protocol == "C"
            or model.m1 is not None
            or model.odr is not None
            or model.projection is not None
            or (model.request_view is not None and not boundary)
        ):
            raise ValueError("NATIVE_CHAT_RECIPE_UNSUPPORTED")

    def project(self, request: ChatRequest) -> PreparedRequest:
        model = self.model
        wire_messages, messages, tools = request.messages, request.graph_messages, request.tools
        boundary = isinstance(model.request_view, MemoryBoundaryView)
        original_messages = (
            [row.model_dump(mode="json") for row in messages]
            if model.memory_protocol is not None
            else []
        )
        memory_receipts = (
            turn_receipts(original_messages, model.memory_turn)
            if model.memory_protocol is not None and model.memory_turn
            else []
        )
        correcting = (
            correction_marker(original_messages, model.active_message_key or "")
            if model.memory_protocol == "C"
            else None
        )
        if correcting is not None:
            tools = [row for row in tools if row["function"]["name"] in CORRECTION_TOOLS]
        if boundary:
            try:
                wire_messages, _ = model.request_view.project(
                    wire_messages, messages, model.active_message_key, model.calls_in_message + 1
                )
            except ValueError as exc:
                if str(exc) in {
                    "JSON_ACTION_HISTORY_INVALID_ARGUMENTS",
                    "JSON_ACTION_HISTORY_ARGUMENTS_NOT_OBJECT",
                }:
                    raise IncompleteChatResponse(str(exc)) from exc
                raise
        if model.client.config.tool_mode == "json_action":
            wire_messages = _json_action_history(wire_messages)
            if model.memory_protocol is not None:
                refs = {row["ref"]: row for row in memory_receipts}
                wire_messages = [
                    dict(
                        row,
                        content=(
                            "[Actual current-turn tool receipt: "
                            + json.dumps(
                                {
                                    "receipt_ref": row["tool_call_id"],
                                    "tool_name": refs[row["tool_call_id"]]["name"],
                                    "transport_status": refs[row["tool_call_id"]][
                                        "transport_status"
                                    ],
                                },
                                ensure_ascii=False,
                            )
                            + "]\n"
                            + str(row["content"])
                        ),
                    )
                    if row["role"] == "tool" and row.get("tool_call_id") in refs
                    else row
                    for row in wire_messages
                ]
            lineage_messages = messages
            if model.request_view is not None and not boundary:
                wire_messages, lineage_messages = model.request_view.project(
                    wire_messages, messages, model.active_message_key, model.calls_in_message + 1
                )
            generation_schema = _recipe_action_schema(
                tools, generation_only=True, memory_result=model.memory_protocol == "C"
            )
            protocol = _recipe_action_prompt(
                tools,
                memory_result=model.memory_protocol == "C",
                tool_schema_communication=model.tool_schema_communication,
                tool_save_communication=model.tool_save_communication,
            )
            m1_context = None
            odr_freshness = ""
            projected = None
            if model.m1 is not None:
                generation_schema = m1_action_schema(generation_schema)
                m1_context = model.m1.prompt_context(wire_messages)
                protocol += "\n" + M1_PROTOCOL + "\n" + m1_context
            if model.odr is not None:
                odr_freshness, odr_evidence = model.odr.project(wire_messages)
                if model.odr.arm == "odr":
                    generation_schema = odr_action_schema(generation_schema)
                    protocol += "\n" + ODR_PROTOCOL + "\n" + odr_evidence
                if odr_freshness:
                    protocol += "\n" + odr_freshness
            if model.projection is not None:
                projected = model.projection.project(
                    wire_messages,
                    model.active_message_key,
                    model.calls_in_message + 1,
                    lineage_messages,
                )
                wire_messages = projected.messages
                if model.projection.stage != "v21" or projected.items or projected.derived_rebases:
                    protocol += "\n" + SOURCE_AUTHORITY
            if isinstance(model.request_view, MemoryBoundaryView):
                action_messages = model.request_view.fit_final_request(
                    model.request_view.final_request_context(protocol)
                )
            else:
                action_messages = _protocol_messages(wire_messages, protocol)
            attachment = _RecipeAttachment(memory_receipts, m1_context, odr_freshness, projected)
            return PreparedRequest(action_messages, tools, generation_schema, attachment)
        if boundary:
            wire_messages = model.request_view.fit_final_request(
                model.request_view.final_request_context(None, native=True), tools=tools
            )
        return PreparedRequest(wire_messages, tools, attachment=_RecipeAttachment(memory_receipts))


class _RecipeDeliveryObserver:
    def __init__(self, model: LangMemRecipeChatModel) -> None:
        self.model = model

    def request_scope(
        self, request: PreparedRequest, request_index: int
    ) -> AbstractContextManager[Any]:
        model = self.model
        if model.observer is None:
            return nullcontext()
        attachment = cast(_RecipeAttachment, request.attachment)
        if model.client.config.tool_mode == "json_action":
            return cast(
                AbstractContextManager[Any],
                model.observer.request_scope(
                    model.active_message_key,
                    request_index,
                    attachment.projected.materials if attachment.projected is not None else None,
                ),
            )
        return cast(
            AbstractContextManager[Any],
            model.observer.request_scope(model.active_message_key, request_index),
        )

    def record_delivery(
        self, request: PreparedRequest, receipt: dict[str, Any], request_index: int
    ) -> None:
        model = self.model
        attachment = cast(_RecipeAttachment, request.attachment)
        if attachment.projected is not None:
            attachment.delivered_snapshot = model.projection.record_delivery(
                model.active_message_key, request_index, attachment.projected, request.messages
            )
        if model.request_view is not None and hasattr(model.request_view, "record_delivery"):
            model.request_view.record_delivery(receipt)

    def after_delivery(self, request: PreparedRequest, request_index: int) -> None:
        model = self.model
        attachment = cast(_RecipeAttachment, request.attachment)
        if model.client.config.tool_mode != "json_action":
            return
        if model.m1 is not None and model.client.emit is not None:
            model.client.emit(
                {
                    "event": "m1_decision_context",
                    "status": "delivered",
                    "request_id": model.m1.request_id(request_index),
                    "text": attachment.m1_context,
                }
            )
        if model.odr is not None and model.client.emit is not None:
            model.client.emit(
                {
                    "event": "odr_request_projection",
                    "arm": model.odr.arm,
                    "request_id": model.odr.request_id(request_index),
                    "dynamic_freshness": attachment.odr_freshness,
                }
            )


class _RecipeResponseHook:
    def __init__(self, model: LangMemRecipeChatModel) -> None:
        self.model = model

    def on_response(self, event: ResponseEvent) -> None:
        model = self.model
        attachment = cast(_RecipeAttachment, event.request.attachment)
        action, message_id = event.action, event.message_id
        if event.stage == "schema_outcome" and event.schema_error is not None:
            recognizable_final = (
                model.memory_protocol == "C"
                and isinstance(action, dict)
                and isinstance(action.get("answer"), str)
                and "calls" not in action
            )
            if recognizable_final:
                event.completion_metadata["memory_result_envelope_invalid"] = True
            if model.m1 is not None:
                model.m1.record_error(
                    model.calls_in_message,
                    message_id,
                    action.get("decision_delta") if isinstance(action, dict) else action,
                    "DECISION_ENVELOPE_SCHEMA_INVALID",
                )
            if model.odr is not None and model.odr.arm == "odr":
                raw = action.get("reconstruction") if isinstance(action, dict) else action
                model.odr.reject(
                    model.calls_in_message, message_id, "ODR_ENVELOPE_SCHEMA_INVALID", raw
                )
            event.accept_schema_failure = recognizable_final
        elif event.stage == "validated_action":
            if model.m1 is not None:
                model.m1.commit(
                    model.calls_in_message,
                    message_id,
                    action["decision_delta"],
                    action.get("calls"),
                )
            if model.odr is not None and model.odr.arm == "odr":
                business_names = {item["function"]["name"] for item in event.request.tools}
                business_names -= {"manage_memory", "search_memory"}
                try:
                    model.odr.accept(
                        model.calls_in_message,
                        message_id,
                        action["reconstruction"],
                        action,
                        business_names,
                    )
                except ReconstructionError as exc:
                    model.odr.reject(
                        model.calls_in_message, message_id, str(exc), action.get("reconstruction")
                    )
                    raise IncompleteChatResponse(str(exc)) from exc
        elif event.stage == "final_action" and model.memory_protocol == "C":
            verification = verify_result(
                action.get("memory_result"), attachment.memory_receipts, model.memory_turn or {}
            )
            if event.completion_metadata.get("memory_result_envelope_invalid"):
                verification["reasons"].append("MEMORY_RESULT_ENVELOPE_INVALID")
                verification["declaration_supported"] = False
                verification["needs_correction"] = True
            event.completion_metadata.update(
                {
                    "memory_result": action.get("memory_result"),
                    "memory_result_action": action,
                    "memory_result_verification": verification,
                }
            )
        elif event.stage == "message_metadata":
            if model.memory_protocol is not None and model.memory_turn is not None:
                event.response_metadata["memory_turn"] = dict(model.memory_turn)
        elif event.stage == "decoded_message":
            message = event.message
            if (
                model.projection is not None
                and attachment.delivered_snapshot is not None
                and not message.tool_calls
                and isinstance(message.content, str)
            ):
                exact_snapshot, unknown_items = attachment.delivered_snapshot
                model.projection.record_output(
                    model.active_message_key,
                    model.calls_in_message,
                    message_id,
                    message.content,
                    exact_snapshot,
                    unknown_items,
                )
