"""Public opt-in argument contracts through the actual decoder and SQLite tool calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import ValidationError, validate
from langchain_core.messages import HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.document_publication import DocumentPublicationWorld
from milai_lab.application.refs import verified_document_ref
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.chat_bridge import _action_schema
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


def invoke(service: MemoryService, name: str, args: dict[str, Any], key: str) -> dict[str, Any]:
    tool = next(tool for tool in create_service_tools(service) if tool.name == name)
    result = tool.invoke(
        {"name": name, "args": args, "id": key, "type": "tool_call"},
        config={"configurable": {"user_id": "alice", "v13_session": "s1"}},
    )
    return json.loads(result.content)


def source(service: MemoryService, key: str, text: str) -> str:
    return str(service.capture_user("s1", key, text)["source_ref"])


@pytest.mark.parametrize("profile", ["reservation_v1", "document_publication_v1"])
def test_public_closed_patch_and_profile_fields_use_existing_json_decoder_contract(
    tmp_path: Path, profile: str
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("schema", "alice"), "alice", tmp_path / "lock",
                                mutation_contract="event_bound_v1", receipt_profile=profile)
        catalog = [convert_to_openai_tool(tool) for tool in create_service_tools(service)]
        schemas = {row["function"]["name"]: row["function"]["parameters"] for row in catalog}
        patch = schemas["revise_memory"]["properties"]["semantic_patch"]
        assert patch["additionalProperties"] is False
        assert set(patch["properties"]) == {"content", "scope", "basis", "kind"}
        assert not patch.get("required")
        assert "source_refs" in schemas["revise_memory"]["properties"]
        assert "tool_call_id" not in schemas["revise_memory"]["properties"]
        fields = schemas["manage_memory"]["properties"]["fields"]["anyOf"][0]
        assert fields["additionalProperties"] is False
        assert fields["properties"] == {key: {"type": dtype}
                                        for key, dtype in service.receipt_fields.items()}
        for change in [{}, {"scope": {"format": "brief"}}, {"content": "A preference"},
                       {"basis": "inference", "kind": "episodic"}]:
            validate({"calls": [{"name": "revise_memory", "arguments": {
                "candidate_handle": "actual-read-handle", "semantic_patch": change,
                "source_refs": ["actual-source"],
            }}]}, _action_schema(catalog))
        for change in [{"source_refs": ["actual-source"]}, {"fields": {}},
                       {"expected_revision": 2}, {"id": "guessed"}, {"content": 3},
                       {"basis": "user_confirmed"}, {"kind": "fact"}]:
            with pytest.raises(ValidationError):
                validate(change, patch)
        for bad_fields in [{"format": "short"}, {"preferred_day": "Monday"}]:
            with pytest.raises(ValidationError):
                validate({"content": "A preference", "fields": bad_fields},
                         schemas["manage_memory"])
        for empty in [{"content": "A preference"}, {"content": "A preference", "fields": {}},
                      {"content": "A preference", "fields": None}]:
            validate(empty, schemas["manage_memory"])


@pytest.mark.parametrize("operation", ["manage", "revise", "supersede"])
def test_new_revision_needs_current_boundary_support_but_no_change_does_not(
    tmp_path: Path, operation: str
) -> None:
    path = tmp_path / "memory.sqlite"
    with SqliteStore.from_conn_string(str(path)) as store:
        service = MemoryService(store, ("current", "alice"), "alice", tmp_path / "lock",
                                mutation_contract="event_bound_v1")
        history = source(service, "old", "Original scoped preference")
        service.bind_source_boundary("s1", "old", [history])
        created = invoke(service, "manage_memory", {"content": "Original",
            "source_refs": [history], "scope": {"project": "A"}}, "create")
        handle = service.read(created["id"])["candidate_handle"]
        current = source(service, "new", "Revise using this request and the original evidence")
        service.bind_source_boundary("s1", "new", [current])
        source_before = service.source(current)

        def update(refs: list[str], key: str) -> dict[str, Any]:
            if operation == "manage":
                return invoke(service, "manage_memory", {"content": "Revised", "scope": {
                    "project": "A"}, "action": "update", "candidate_handle": handle,
                    "source_refs": refs}, key)
            return invoke(service, "revise_memory", {"candidate_handle": handle,
                "semantic_patch": {"content": "Revised"}, "source_refs": refs,
                "operation": operation}, key)

        rejected = update([history], "old-only")
        assert rejected["reason"] == "current_boundary_source_required"
        assert not rejected["ok"] and rejected["raw_preserved"]
        assert rejected["formation_status"] == "pending"
        assert service.read(created["id"])["value"]["revision"] == 1
        none = invoke(service, "revise_memory", {"candidate_handle": handle,
            "semantic_patch": {}, "source_refs": [history], "operation": "no_change"}, "none")
        assert none["ok"] and none["revision"] == 1 and none["effect"] == "none"
        # The first selected support may be historical; current support must still be retained.
        accepted = update([history, current], "supported")
        assert accepted["ok"] and accepted["id"] == created["id"]
        assert accepted["revision"] == 2 and accepted["source_refs"] == [history, current]
        assert [row["source_ref"] for row in accepted["source_bindings"]] == [history, current]
        assert service.source(current) == source_before
        assert service.read(created["id"])["value"]["scope"] == {"project": "A"}
        assert update([current], "stale")["reason"] == "revision_conflict"
        assert len(service.records()) == 1
        new_handle = service.read(created["id"])["candidate_handle"]
    with SqliteStore.from_conn_string(str(path)) as store:
        reopened = MemoryService(store, ("current", "alice"), "alice", tmp_path / "lock",
                                 mutation_contract="event_bound_v1")
        # Reopening cannot promote old capture history into a current trusted boundary.
        result = reopened.revise("s1", "unbound", new_handle,
                                 {"content": "Unbound revision"}, [current])
        assert result["reason"] == "current_boundary_source_required"
        reopened.bind_source_boundary("s1", "actual-request", [current])
        result = reopened.revise("s1", "bound", new_handle, {"content": "Bound"}, [current])
        assert result["revision"] == 3 and len(reopened.records()) == 1


def test_document_integer_public_field_is_callable_without_dto_conversion(tmp_path: Path) -> None:
    world = DocumentPublicationWorld(tmp_path / "world.sqlite", True)
    try:
        native = world.create_or_update_draft("alice", "Public draft", "Actual text")
        with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
            service = MemoryService(store, ("document", "alice"), "alice", tmp_path / "lock",
                mutation_contract="event_bound_v1", receipt_profile="document_publication_v1",
                receipt_contract="explicit_receipt_v1")
            ref = verified_document_ref(world, "alice", service.event_id("s1", "draft", "tool"),
                                        "create_or_update_draft", native)
            assert ref is not None
            service.capture_tool("s1", "draft", "create_or_update_draft", native, ref)
            service.bind_source_boundary("s1", "draft", [ref.source_ref])
            fields = dict(ref.fields)
            assert type(fields["document_version"]) is int
            args = {"content": json.dumps(fields), "fields": fields,
                    "content_format": "receipt_json_v1", "basis": "tool_observation"}
            tool = next(tool for tool in create_service_tools(service)
                        if tool.name == "manage_memory")
            validate(args, convert_to_openai_tool(tool)["function"]["parameters"])
            result = invoke(service, "manage_memory", args, "literal")
            assert result["ok"] and result["fields_verification"] == "receipt_matched"
            stored = service.read(result["id"])["value"]["fields"]
            assert stored == fields and type(stored["document_version"]) is int
            bad = {**args, "fields": {**fields, "document_version": "1"}}
            rejected = invoke(service, "manage_memory", bad, "wrong-type")
            assert not rejected["ok"] and rejected["reason"] == "invalid_receipt_fields"
            assert len(service.records()) == 1
    finally:
        world.close()


@pytest.mark.parametrize("candidate_contract", [
    "legacy_query_v1", "id_revision_v1", "read_handle_v1",
])
def test_direct_commit_and_all_candidate_interfaces_require_current_update_source(
    tmp_path: Path, candidate_contract: str,
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("interfaces", "alice"), "alice", tmp_path / "lock",
            mutation_contract="event_bound_v1", candidate_contract=candidate_contract)
        history = source(service, "old", "Original preference")
        service.bind_source_boundary("s1", "old", [history])
        created = invoke(service, "manage_memory", {"content": "Original",
                         "source_refs": [history]}, "create")
        read = service.read(created["id"])
        current = source(service, "new", "A current request")
        service.bind_source_boundary("s1", "new", [current])
        raw = {"action": "update", "id": created["id"], "expected_revision": 1,
               "candidate_handle": read["candidate_handle"], "source_ref": history,
               "source_refs": [history], "content": "Revised", "kind": "semantic",
               "scope": {}, "basis": "user_statement", "fields": {}, "object_ref": None}
        assert service.commit("s1", "direct-old", raw)["reason"] == (
            "current_boundary_source_required")
        args = {"action": "update", "content": "Revised", "source_refs": [history]}
        if candidate_contract == "legacy_query_v1":
            args["target_query"] = "Original"
        elif candidate_contract == "id_revision_v1":
            args.update(id=created["id"], expected_revision=1)
        else:
            args["candidate_handle"] = read["candidate_handle"]
        assert invoke(service, "manage_memory", args, "interface-old")["reason"] == (
            "current_boundary_source_required")
        # Mechanical current-source membership does not verify this proposal's meaning.
        accepted = invoke(service, "manage_memory", {**args, "source_refs": [current]}, "current")
        assert accepted["revision"] == 2 and accepted["content_verification"] == "unchecked"
        assert service.read(created["id"])["value"]["source_refs"] == [current]


def test_actual_recipe_mock_wire_delivers_schema_and_does_not_repair_bad_arguments(
    tmp_path: Path,
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("wire", "alice"), "alice", tmp_path / "lock",
                                mutation_contract="event_bound_v1")
        history = source(service, "old", "Original preference")
        service.bind_source_boundary("s1", "old", [history])
        created = invoke(service, "manage_memory", {"content": "Original",
                         "scope": {"project": "A"}, "source_refs": [history]}, "create")
        handle = service.read(created["id"])["candidate_handle"]
        current = source(service, "current", "Current preference revision")
        service.bind_source_boundary("s1", "current", [current])
        current_before = service.source(current)
        actions = [
            {"name": "revise_memory", "arguments": {"candidate_handle": handle,
                "semantic_patch": {"content": "Changed", "source_refs": [current]}}},
            {"name": "manage_memory", "arguments": {"content": "Changed",
                                                      "fields": {"format": "brief"}}},
            {"name": "manage_memory", "arguments": {"content": "Changed",
                "fields": {"preferred_day": "Monday"}, "object_ref": "guessed"}},
            {"name": "revise_memory", "arguments": {"candidate_handle": handle,
                "semantic_patch": {"content": "Changed"}, "source_refs": [current]}},
            {"name": "revise_memory", "arguments": {"candidate_handle": handle,
                "semantic_patch": {"content": "Stale"}}},
        ]
        tools = {tool.name: tool for tool in create_service_tools(service)}
        wires: list[dict[str, Any]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            wire = json.loads(request.read())
            wires.append(wire)
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps({
                    "calls": [actions[len(wires) - 1]],
                })}}], "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13}})

        with VLLMClient(VLLMConfig("http://offline.invalid/v1", "mechanical"),
                        transport=httpx.MockTransport(respond)) as client:
            model = LangMemRecipeChatModel(client=client).bind_tools(list(tools.values()))
            reasons = []
            for index in range(len(actions)):
                response = model.invoke([HumanMessage(content="Current preference revision")])
                assert len(response.tool_calls) == 1
                call = response.tool_calls[0]
                assert call["args"] == actions[index]["arguments"]
                result = tools[call["name"]].invoke({**call, "type": "tool_call"},
                    config={"configurable": {"user_id": "alice", "v13_session": "s1"}})
                receipt = json.loads(result.content)
                reasons.append(receipt.get("reason", receipt["status"]))
                assert len(service.records()) == 1
                assert service.read(created["id"])["value"]["revision"] == (1 if index < 3 else 2)
            assert reasons == [
                "invalid_semantic_patch", "operational_fields_require_object_ref",
                "object_ref_not_found_or_not_owned", "committed", "revision_conflict",
            ]
        parameters = {tool.name: convert_to_openai_tool(tool)["function"]["parameters"]
                      for tool in tools.values()}
        for wire in wires:
            prompt = wire["messages"][0]["content"]
            delivered = json.loads(prompt.split(
                "A tool result will be returned before your next reply.\n")[1])
            assert {row["name"]: row["parameters"] for row in delivered} == parameters
            # This existing decoder's grammar constrains the action envelope only.
            grammar = wire["response_format"]["json_schema"]["schema"]
            branches = grammar["oneOf"][1]["properties"]["calls"]["items"]["oneOf"]
            assert all(branch["properties"]["arguments"] == {"type": "object"}
                       for branch in branches)
        assert service.source(current) == current_before
        value = service.read(created["id"])["value"]
        assert value["content"] == "Changed" and value["fields"] == {}
        assert value["scope"] == {"project": "A"} and value["source_refs"] == [current]
