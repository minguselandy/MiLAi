"""Synthetic structural communication controls; no Source/semantic oracle."""

from __future__ import annotations

import copy
import hashlib
import json
import socket
from typing import Literal

import pytest
from jsonschema import ValidationError, validate
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from milai_lab.contracts.tool_schema_communication import (
    check_frozen,
    feedback_text,
    freeze_fields,
    jsonschema_feedback,
    present_catalog,
    presentation_metadata,
    profile,
    pydantic_feedback,
    shape_guidance,
)
from milai_lab.providers.chat_bridge import _action_prompt, _action_schema


@pytest.fixture(autouse=True)
def no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("SOCKET_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def catalog() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo actual x.",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                    "additionalProperties": False,
                },
            },
        }
    ]


@pytest.mark.parametrize("invalid", [None, True, 1, [], "unknown"])
def test_explicit_profiles_reject_unknown(invalid: object) -> None:
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        profile(invalid)


def test_legacy_byte_and_generic_baseline_copy_free_grammar() -> None:
    original = catalog()
    before = copy.deepcopy(original)
    assert present_catalog(original) is original
    assert shape_guidance(original) == ""
    assert freeze_fields(original, "legacy") == {}
    assert _action_prompt(original) == _action_prompt(original, tool_schema_communication="legacy")
    display = present_catalog(original, "shape_feedback_v1")
    assert original == before
    assert display[0]["function"]["parameters"] == original[0]["function"]["parameters"]
    assert "field_support" not in json.dumps(display)
    assert "candidate_handle" not in shape_guidance(original, "shape_feedback_v1")
    assert _action_schema(display, generation_only=True) == _action_schema(
        original, generation_only=True
    )
    frozen = {
        "config": {"tool_schema_communication": "shape_feedback_v1"},
        "tool_catalog": original,
        **freeze_fields(original, "shape_feedback_v1"),
    }
    assert check_frozen(frozen) == "shape_feedback_v1"
    assert frozen["tool_schema_communication_catalog"] == display
    frozen["tool_schema_communication_catalog"][0]["function"]["description"] += " changed"
    with pytest.raises(ValueError, match="FREEZE_CHANGED"):
        check_frozen(frozen)


def test_real_validator_enum_position_expected_and_no_instance_leak() -> None:
    schema = {
        "type": "object",
        "properties": {"basis": {"type": "string", "enum": ["plan", "inference"]}},
    }
    with pytest.raises(ValidationError) as caught:
        validate({"basis": {"source_refs": ["PRIVATE_BUSINESS_VALUE"]}}, schema)
    result = jsonschema_feedback(caught.value, schema)
    assert result["origin"] == "jsonschema"
    assert result["error"]["path"]["segments"] == list(caught.value.absolute_path) == ["basis"]
    assert result["error"]["schema_path"]["segments"] == list(caught.value.absolute_schema_path)
    assert result["error"]["keyword"] == caught.value.validator
    assert result["error"]["expected"] == caught.value.validator_value
    assert "PRIVATE_BUSINESS_VALUE" not in feedback_text(result)
    assert "message" not in result["error"] and "instance" not in result["error"]


def test_real_nested_context_local_ref_bounds_and_path_identity() -> None:
    schema = {
        "$defs": {"choice": {"oneOf": [{"type": "string", "enum": [f"v{i}"]} for i in range(12)]}},
        "type": "object",
        "properties": {"位置/~": {"$ref": "#/$defs/choice"}},
    }
    with pytest.raises(ValidationError) as caught:
        validate({"位置/~": "UNSELECTED_PRIVATE_VALUE"}, schema)
    result = jsonschema_feedback(caught.value, schema)
    node = result["error"]
    assert node["path"]["segments"] == ["位置/~"]
    assert len(node["context"]) == 7 and node["omitted_context_children"] == 5
    assert node["context"][0]["schema_path"]["segments"] == list(
        caught.value.context[0].absolute_schema_path
    )
    assert "UNSELECTED_PRIVATE_VALUE" not in feedback_text(result)
    assert "PRIVATE" not in json.dumps(result)


def test_unpublished_expected_and_hostile_long_path_never_echo_input() -> None:
    key = "不可信/~\n" * 500
    error = ValidationError(
        "PRIVATE_MESSAGE",
        validator="const",
        validator_value="PRIVATE_CONST",
        instance="PRIVATE_INSTANCE",
        schema={"const": "PRIVATE_CONST"},
        path=[key] * 20,
        schema_path=["const"],
    )
    result = jsonschema_feedback(error, {"type": "object"})
    node = result["error"]
    assert "expected" not in node
    assert node["path"]["omitted_segments"] == 4
    assert node["path"]["segments"][0]["omitted"]
    raw = json.dumps([key] * 20, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert node["path"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert all(
        value not in feedback_text(result)
        for value in ("PRIVATE_MESSAGE", "PRIVATE_CONST", "PRIVATE_INSTANCE", key)
    )


def test_actual_pydantic_origin_loc_type_only() -> None:
    class Input(BaseModel):
        basis: Literal["plan", "inference"]

    with pytest.raises(PydanticValidationError) as caught:
        Input(basis={"source_refs": ["PRIVATE_VALUE"]})  # type: ignore[arg-type]
    result = pydantic_feedback(caught.value)
    actual = caught.value.errors(include_input=False, include_context=False, include_url=False)
    assert result["origin"] == "pydantic"
    assert result["errors"][0]["loc"]["segments"] == list(actual[0]["loc"])
    assert result["errors"][0]["type"] == actual[0]["type"]
    assert "schema_path" not in feedback_text(result)
    assert "PRIVATE_VALUE" not in feedback_text(result)


def test_freeze_flag_and_original_schema_hash_are_separate() -> None:
    original = catalog()
    metadata = presentation_metadata(original, "shape_feedback_v1")
    raw = json.dumps(
        original[0]["function"]["parameters"],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert metadata["original_parameter_schema_sha256"]["echo"] == hashlib.sha256(raw).hexdigest()
    frozen = {
        "config": {"tool_schema_communication": "shape_feedback_v1"},
        "tool_catalog": original,
    }
    with pytest.raises(ValueError, match="FREEZE_CHANGED"):
        check_frozen(frozen)
    frozen.update(freeze_fields(original, "shape_feedback_v1"))
    frozen["config"]["tool_schema_communication"] = "legacy"
    with pytest.raises(ValueError, match="FREEZE_CHANGED"):
        check_frozen(frozen)


@pytest.mark.parametrize("private,public", [(True, 1), (1, 1.0), (1.0, 1)])
def test_expected_requires_exact_public_json_identity(private: object, public: object) -> None:
    private_schema = {"enum": [private]}
    error = ValidationError(
        "PRIVATE_MESSAGE",
        validator="enum",
        validator_value=[private],
        schema=private_schema,
        instance="PRIVATE_INSTANCE",
        schema_path=["enum"],
    )
    result = jsonschema_feedback(error, {"enum": [public]})
    assert "expected" not in result["error"]
    assert jsonschema_feedback(error, private_schema)["error"]["expected"] == [private]
    error.validator_value = [public]
    assert "expected" not in jsonschema_feedback(error, private_schema)["error"]


def test_composed_real_errors_have_one_aggregate_utf8_budget_and_truthful_omissions() -> None:
    from jsonschema import Draft202012Validator
    from pydantic import create_model

    key = "long-public-path-" + "段" * 120
    instance: object = "PRIVATE_INSTANCE"
    for _ in range(16):
        instance = {key: instance}
    branches = []
    for index in range(10):
        schema = {"type": "integer", "minimum": index}
        for _ in range(16):
            schema = {"type": "object", "properties": {key: schema}, "required": [key]}
        branches.append(schema)
    public = {"oneOf": branches}
    original = next(Draft202012Validator(public).iter_errors(instance))
    projected = jsonschema_feedback(original, public)
    assert len(feedback_text(projected).encode()) <= 4096
    assert projected["feedback_utf8_limit"] == 4096
    root = projected["error"]
    assert len(root["context"]) + root["omitted_context_children"] == len(original.context)
    for node, actual in zip(root["context"], original.context, strict=False):
        for name, path in [
            ("path", actual.absolute_path),
            ("schema_path", actual.absolute_schema_path),
        ]:
            full = list(path)
            shown = node[name]["segments"]
            assert shown == full[: len(shown)]
            assert len(shown) + node[name]["omitted_segments"] == len(full)
            raw = json.dumps(
                full, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
            assert node[name]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert "PRIVATE_INSTANCE" not in feedback_text(projected)

    nested = create_model("Leaf", value=(int, ...))
    body: object = {"value": "PRIVATE_INPUT"}
    for index in range(16):
        nested = create_model(f"Nested{index}", **{key: (nested, ...)})
        body = {key: body}
    many = create_model("Many", **{f"branch{i}": (nested, ...) for i in range(10)})
    with pytest.raises(PydanticValidationError) as caught:
        many.model_validate({f"branch{i}": body for i in range(10)})
    original_rows = caught.value.errors(
        include_input=False, include_context=False, include_url=False
    )
    result = pydantic_feedback(caught.value)
    assert len(feedback_text(result).encode()) <= 4096
    assert len(result["errors"]) + result["omitted_errors"] == len(original_rows)
    for node, row in zip(result["errors"], original_rows, strict=False):
        full = list(row["loc"])
        shown = node["loc"]["segments"]
        assert shown == full[: len(shown)]
        assert len(shown) + node["loc"]["omitted_segments"] == len(full)
        assert node["type"] == row["type"]
    assert "PRIVATE_INPUT" not in feedback_text(result)


@pytest.mark.parametrize("mode", ["json_action", "native"])
@pytest.mark.parametrize("communication", ["legacy", "shape_feedback_v1"])
def test_actual_mock_model_wire_catalog_profile_and_paid_budget(
    tmp_path, mode: str, communication: str
) -> None:
    import httpx
    from langchain_core.messages import HumanMessage

    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

    original = catalog()
    wires = []

    def respond(request):
        wires.append(json.loads(request.content))
        content = (
            json.dumps({"answer": "Synthetic answer"})
            if mode == "json_action"
            else "Synthetic answer"
        )
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
        )

    budget = RunBudget(RunLimits(1, 1, 4, 10000, 0), tmp_path / "local-ledger.json")
    model = LangMemRecipeChatModel(
        client=VLLMClient(
            VLLMConfig("http://mock/v1", "mock", tool_mode=mode, max_tokens=64),
            budget=budget,
            transport=httpx.MockTransport(respond),
        ),
        tool_schema_communication=communication,
    )
    model.begin_public_message("synthetic")
    model.bind_tools(original).invoke([HumanMessage(content="Ordinary synthetic request")])
    assert len(wires) == model.calls_in_message == 1
    assert original == catalog()
    wire = wires[0]
    if mode == "native":
        assert wire["tools"] == present_catalog(original, communication)
        assert wire["tools"][0]["function"]["parameters"] == original[0]["function"]["parameters"]
        assert "response_format" not in wire
    else:
        generated = wire["response_format"]["json_schema"]["schema"]
        assert generated == _action_schema(original, generation_only=True)
    assert ("[shape_feedback_v1]" in wire["messages"][0]["content"]) == (communication != "legacy")
    saved = json.loads((tmp_path / "local-ledger.json").read_text())
    assert saved["generation_requests"] == 1 and saved["generation"]["charged_tokens"] == 9
