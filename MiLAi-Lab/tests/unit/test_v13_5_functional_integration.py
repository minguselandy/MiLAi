"""Mechanical unified-entry checks: scripted wire replies, real SDK/state/accounting.

These finite provider responses test integration, never semantic acceptance.
All ledgers and tokenizer inputs are isolated under pytest's temporary path.
"""

from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_from_dict
from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.providers.functional_queue import FunctionalVLLMClient
from milai_lab.runners import functional


def prepared(
    tmp_path: Path, *, queue_requests: int = 100, native: bool = False,
    request_interpretation: bool = False,
    readonly_finalization: bool = False,
    write_mode_declaration: bool = False,
    action_mode_declaration: bool = False,
    receipt_response: bool = False,
    declared_writes: bool = False,
    operation_mode_declaration: bool = False,
) -> Path:
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer_wrapper = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token="[UNK]")
    tokenizer_wrapper.chat_template = (
        "{% for m in messages %}{{m.role}} {{m.content}} {% endfor %}"
        "{% if tools %}{{tools|tojson}}{% endif %} assistant "
    )
    directory = tmp_path / "mechanical-tokenizer"
    tokenizer_wrapper.save_pretrained(str(directory))
    (directory / "chat_template.jinja").write_text(tokenizer_wrapper.chat_template)
    host = VLLMConfig(base_url="http://mechanical.invalid/v1/", model="mechanical-provider",
                      max_tokens=4096, max_calls=24, enable_thinking=False,
                      tool_mode="native" if native else "json_action")
    budget_path = tmp_path / "isolated-mechanical-budget.json"
    budget = RunBudget(RunLimits(1, 1, 100, 2_000_000, 0), budget_path)
    write_json(budget_path, budget.state)
    settings = {
        "profile": "functional_v1", "host": asdict(host),
        "capacity": {"model": host.model, "tokenizer_path": str(directory),
            "tokenizer_files_sha256": {
                name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")},
            "context_tokens": 32768, "output_tokens": 4096, "batch_source_tokens": 8192,
            "enable_thinking": False},
        "budget_path": str(budget_path), "max_calls_per_message": 24,
        "ordinary_material_tokens": 8192, "additional_reads": 3, "format_reproposals": 1,
        "queue_limits": {"requests": queue_requests, "reserved_tokens": 2_000_000},
        "http_ownership_profile": "serialized_ledger_owner_v1",
        "http_ownership_domain": {"deployment_id": "mechanical-local-test",
                                   "clients": [asdict(host)]},
        "system_prompt": "Mechanical integration probe. Use issued evidence and actual receipts.",
        "request_mode": "current_request_native_v4" if operation_mode_declaration else
        "current_request_native_v3" if action_mode_declaration else
        "current_request_native_v2" if write_mode_declaration else
        "current_request_native_v1" if request_interpretation else "disabled",
        "finalization": "receipt_business_response_v1" if receipt_response else
        "readonly_response_v1" if readonly_finalization else "agent_final_v1",
        "read_exhaustion": "stop_execution_v1" if receipt_response else "legacy",
        "memory_completion": "declared_writes_v1" if declared_writes else "explicit_only_v1",
        "formation_interface": "unified_assertion_v1" if readonly_finalization
        else "content_and_scope_v1",
    }
    settings_path = tmp_path / "settings.json"
    write_json(settings_path, settings)
    root = tmp_path / "run"
    functional.prepare(root, settings_path)
    return root


def scripted(
    monkeypatch: pytest.MonkeyPatch, respond: Any, *, native: bool = False,
) -> list[dict[str, Any]]:
    wires: list[dict[str, Any]] = []

    def forbid(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", forbid)

    def response(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append(wire)
        action = respond(wire, len(wires))
        if isinstance(action, Exception):
            raise action
        payload = action if native else {"role": "assistant", "content": json.dumps(action)}
        finish = payload.pop("_test_finish_reason",
                             "tool_calls" if payload.get("tool_calls") else "stop")
        return httpx.Response(200, json={"id": "mechanical-response-" + str(len(wires)),
            "choices": [{"finish_reason": finish, "message": payload}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}})

    class ScriptedClient(FunctionalVLLMClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(response))

    monkeypatch.setattr(functional, "FunctionalVLLMClient", ScriptedClient)
    return wires


def tool(action: str, **args: Any) -> dict[str, Any]:
    return {"calls": [{"name": action, "arguments": args}]}


def materials(wire: dict[str, Any]) -> dict[str, Any]:
    system = next(row["content"] for row in wire["messages"] if row["role"] == "system")
    # The actual runtime material is the final JSON line after protocol/schema text.
    return json.loads(system.splitlines()[-1])


def actual_tool_receipt(wire: dict[str, Any]) -> dict[str, Any]:
    return json.loads(next(row["content"] for row in reversed(wire["messages"])
                           if row["role"] == "tool"))


def memory_effects(wire: dict[str, Any]) -> dict[str, Any]:
    system = next(row["content"] for row in wire["messages"] if row["role"] == "system")
    summary = json.loads(system.splitlines()[-2])
    assert summary["schema"] == "functional_memory_effects_v1"
    assert summary["scope"] == "visible_checkpoint_of_current_public_message"
    return summary


def message(root: Path, **kwargs: Any) -> dict[str, Any]:
    return functional.message(root, bank="mechanical-bank", owner="alice", session="session",
                              message_id="message", content="Remember the local marker is blue.",
                              **kwargs)


def intent_reply(*, memory: bool = False, required: bool = False, forgetting: bool = False,
                 business: bool = False) -> dict[str, Any]:
    return native_call("classify_current_request", "interpret",
        allow_memory_maintenance=memory, allow_forgetting=forgetting,
        allow_business_mutation=business, requires_memory_result=required)


def native_call(name: str, call_id: str, **args: Any) -> dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": [{
        "type": "function", "id": call_id, "function": {
            "name": name, "arguments": json.dumps(args)}}]}


def test_focused_request_mode_removes_mutations_and_survives_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)
    first_text = "Remember the independent old marker is blue."
    query = "Have I said that the marker is red?"

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 4}:
            assert [t["function"]["name"] for t in wire["tools"]] == ["classify_current_request"]
            users = [m["content"] for m in wire["messages"] if m["role"] == "user"]
            assert users == [first_text if ordinal == 1 else query]
            if ordinal == 4:
                assert first_text not in json.dumps(wire)
            return intent_reply(memory=ordinal == 1)
        catalog = {t["function"]["name"] for t in wire.get("tools", [])}
        if ordinal == 2:
            assert {"save_memory", "update_memory"} <= catalog
            assert not {"forget_memory", "reserve_and_label"}.intersection(catalog)
            hs = [u["fragment_handle"] for u in materials(wire)["items"] if u["type"] == "fragment"]
            return native_call("save_memory", "save", content="The marker is blue.",
                               fragment_handles=hs)
        if ordinal == 3:
            return {"role": "assistant", "content": "Saved the blue marker."}
        assert {"read_memory", "get_reservation"} <= catalog
        assert not {"save_memory", "update_memory", "forget_memory", "reserve_and_label",
                    "complete_label"}.intersection(catalog)
        if ordinal == 5:
            # A provider can still emit a forbidden name; no dispatcher executes it.
            hs = [u["fragment_handle"] for u in materials(wire)["items"]
                  if u["type"] == "fragment" and u["input_relation"] == "current_request"]
            return native_call("save_memory", "forbidden", content="The marker is red.",
                               fragment_handles=hs)
        assert ordinal == 6
        return {"role": "assistant", "content": "You previously said the marker is blue."}

    wires = scripted(monkeypatch, reply, native=True)
    common = {"bank": "b", "owner": "alice", "session": "s"}
    saved = functional.message(root, **common, message_id="save", content=first_text)
    assert saved["status"] == "COMPLETED", saved
    denied = functional.message(root, **common, message_id="query", content=query)
    assert denied["status"] == "FAILED" and denied["error"] == "VLLM_CHAT_UNKNOWN_TOOL"
    assert denied["records"] == saved["records"]
    assert denied["operation_status"]["semantic_memory"]["operations"] == []
    restored = functional.message(root, **common, message_id="query", content=query, resume=True)
    assert restored["status"] == "COMPLETED", restored
    assert restored["records"] == saved["records"] and len(wires) == 6
    assert restored["generation_calls"] == 3  # One interpretation, two Agent requests.
    assert restored["request_mode"] == denied["request_mode"]
    assert restored["request_mode"]["semantic_correctness"] == "unchecked"


@pytest.mark.parametrize("write_request", ["none", "new_assertion", "explicit"])
def test_write_mode_declaration_derives_consistent_permissions_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_request: str,
) -> None:
    root = prepared(tmp_path, native=True, write_mode_declaration=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            schema = wire["tools"][0]["function"]["parameters"]
            assert set(schema["required"]) == {
                "memory_write_request", "allow_forgetting", "allow_business_mutation"}
            return native_call("classify_current_request", "mode",
                memory_write_request=write_request, allow_forgetting=False,
                allow_business_mutation=False)
        if ordinal == 2:
            catalog = {t["function"]["name"] for t in wire["tools"]}
            assert ("save_memory" in catalog) == (write_request != "none")
            if write_request != "none":
                hs = [u["fragment_handle"] for u in materials(wire)["items"]
                      if u["type"] == "fragment" and u["input_relation"] == "current_request"]
                return native_call("save_memory", "save", content="Mechanical preference.",
                                   fragment_handles=hs)
        return {"role": "assistant", "content": "No write requested." if write_request == "none"
                else "Actual record saved."}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first["status"] == "COMPLETED", first
    mode = first["request_mode"]
    assert mode["memory_write_request"] == write_request
    assert mode["allow_memory_maintenance"] == (write_request != "none")
    assert mode["requires_memory_result"] == (write_request == "explicit")
    assert mode["protocol"] == "native_write_declaration_v2"
    assert len(first["records"]) == (0 if write_request == "none" else 1)
    count = len(wires)
    replayed = message(root, resume=True)
    assert replayed["status"] == "COMPLETED" and replayed["request_mode"] == mode
    assert len(wires) == count


@pytest.mark.parametrize("invalid", ["read", True, None])
def test_write_mode_declaration_rejects_invalid_enum_without_permission_coercion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: Any,
) -> None:
    root = prepared(tmp_path, native=True, write_mode_declaration=True)
    wires = scripted(monkeypatch, lambda wire, ordinal: native_call(
        "classify_current_request", "invalid", memory_write_request=invalid,
        allow_forgetting=False, allow_business_mutation=False), native=True)
    for resume in [False, True]:
        result = message(root, resume=resume)
        assert result["error"] == "FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID"
        assert not result["records"]
    blocked = message(root, resume=True)
    assert blocked["error"] == "FUNCTIONAL_REQUEST_MODE_REPROPOSAL_EXHAUSTED"
    assert len(wires) == 2


def test_request_mode_invalid_output_has_one_durable_reproposal_and_no_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        assert [t["function"]["name"] for t in wire["tools"]] == ["classify_current_request"]
        return {"role": "assistant", "content": '{"allow_memory_maintenance": true}'}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    second = message(root, resume=True)
    third = message(root, resume=True)
    assert first["error"] == second["error"] == "FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID"
    assert third["error"] == "FUNCTIONAL_REQUEST_MODE_REPROPOSAL_EXHAUSTED"
    assert len(wires) == 2 and not third["records"]
    assert third["operation_status"]["semantic_memory"]["operations"] == []


@pytest.mark.parametrize("forgetting", [False, True])
def test_request_mode_separately_controls_forgetting_and_business_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forgetting: bool,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return intent_reply(forgetting=forgetting, business=not forgetting)
        catalog = {t["function"]["name"] for t in wire.get("tools", [])}
        assert ("forget_memory" in catalog) is forgetting
        assert ("reserve_and_label" in catalog) is not forgetting
        assert not {"save_memory", "update_memory"}.intersection(catalog)
        return {"role": "assistant", "content": "Scripted response with no operation."}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result["status"] == "COMPLETED" and len(wires) == 2
    assert result["operation_status"]["request_completion"] == "unchecked"


@pytest.mark.parametrize("defect", ["string_boolean", "extra_reason", "missing_flag",
                                    "inconsistent_required", "multiple_calls"])
def test_native_request_declaration_rejects_invalid_flags_before_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        flags: dict[str, Any] = {"allow_memory_maintenance": False, "allow_forgetting": False,
            "allow_business_mutation": False, "requires_memory_result": False}
        if defect == "string_boolean":
            flags["allow_memory_maintenance"] = "true"
        elif defect == "extra_reason":
            flags["reason"] = "Unrequested explanation."
        elif defect == "missing_flag":
            flags.pop("allow_forgetting")
        elif defect == "inconsistent_required":
            flags["requires_memory_result"] = True
        response = native_call("classify_current_request", "mode", **flags)
        if defect == "multiple_calls":
            response["tool_calls"].extend(
                native_call("classify_current_request", "mode-2", **flags)["tool_calls"])
        return response

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result["error"] == "FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID", result
    assert len(wires) == 1 and not result["records"]
    assert result["operation_status"]["business"]["operations"] == []


def test_request_mode_reproposal_cannot_redisclose_forgotten_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return {"role": "assistant", "content": "invalid mode"}
        if ordinal == 2:
            assert "MECHANICAL_MODE_SECRET" not in json.dumps(wire)
            return intent_reply(forgetting=True)
        if ordinal == 3:
            return native_call("search_memory", "search", query="MECHANICAL_MODE_SECRET")
        if ordinal == 4:
            hs = [u["fragment_handle"] for u in actual_tool_receipt(wire)["items"]
                  if u["type"] == "fragment" and "MECHANICAL_MODE_SECRET" in u["content"]]
            assert hs
            return native_call("forget_memory", "forget", fragment_handles=hs)
        assert ordinal == 5
        assert "MECHANICAL_MODE_SECRET" not in json.dumps(wire)
        assert actual_tool_receipt(wire)["status"] == "visibility_revoked"
        return {"role": "assistant", "content": "Forgotten."}

    wires = scripted(monkeypatch, reply, native=True)
    common = {"bank": "b", "owner": "alice", "session": "s"}
    old = {"message_id": "old", "content": "Remember MECHANICAL_MODE_SECRET."}
    failed = functional.message(root, **common, **old)
    assert failed["error"] == "FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID"
    forgotten = functional.message(root, **common, message_id="forget",
                                   content="Forget my previous input.")
    assert forgotten["status"] == "COMPLETED", forgotten
    replay = functional.message(root, **common, **old, resume=True)
    # Raw capture rejects this revoked original input even before mode admission.
    assert replay["status"] == "FAILED", replay
    assert replay["error"].startswith("FUNCTIONAL_SOURCE_CAPTURE_UNAVAILABLE:")
    assert replay["capture"]["status"] == "visibility_revoked"
    assert replay.get("final_answer") is None and len(wires) == 5


def test_request_mode_and_answer_recovery_share_one_format_reproposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return {"role": "assistant", "content": "invalid mode"}
        if ordinal == 2:
            return intent_reply(memory=True)
        if ordinal == 3:
            hs = [u["fragment_handle"] for u in materials(wire)["items"] if u["type"] == "fragment"]
            return native_call("save_memory", "save", content="The marker is blue.",
                               fragment_handles=hs)
        assert ordinal == 4
        assert actual_tool_receipt(wire)["status"] == "committed"
        return {"role": "assistant", "content": "{"}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first["error"] == "FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID"
    bad_final = message(root, resume=True)
    assert bad_final["status"] == "FAILED" and len(bad_final["records"]) == 1
    exhausted = message(root, resume=True)
    assert exhausted["error"] == "FUNCTIONAL_FINAL_ANSWER_REPAIR_BUDGET_EXHAUSTED"
    assert exhausted["records"] == bad_final["records"] and len(wires) == 4
    assert exhausted["generation_calls"] == 4
    assert exhausted["operation_status"]["semantic_memory"]["status"] == "committed"


def test_cached_request_mode_allows_committed_forget_recovery_without_reexposure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)
    control = {"one_shot_fault": {"message_index": 1, "boundary": "W3",
                                "target_operation": "forget_memory", "occurrence": 1}}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return intent_reply(memory=True)
        if ordinal == 2:
            hs = [u["fragment_handle"] for u in materials(wire)["items"] if u["type"] == "fragment"]
            return native_call("save_memory", "save", content="MECHANICAL_MODE_FORGET",
                               fragment_handles=hs)
        if ordinal == 3:
            return {"role": "assistant", "content": "Saved."}
        if ordinal == 4:
            assert "MECHANICAL_MODE_FORGET" not in json.dumps(wire)
            return intent_reply(forgetting=True)
        if ordinal == 5:
            record = next(u for u in materials(wire)["items"] if u["type"] == "record")
            return native_call("forget_memory", "forget", read_handle=record["read_handle"])
        assert ordinal == 6
        assert "MECHANICAL_MODE_FORGET" not in json.dumps(wire)
        assert actual_tool_receipt(wire)["status"] == "visibility_revoked"
        return {"role": "assistant", "content": "Forgotten."}

    wires = scripted(monkeypatch, reply, native=True)
    common: dict[str, Any] = {"bank": "b", "owner": "alice", "session": "s"}
    saved = functional.message(root, **common, message_id="save",
                               content="Remember MECHANICAL_MODE_FORGET.")
    assert saved["status"] == "COMPLETED"
    args: dict[str, Any] = {**common, "message_id": "forget", "content": "Forget the marker.",
                           "message_index": 1, "evaluator_control": control}
    interrupted = functional.message(root, **args)
    assert interrupted["status"] == "UNKNOWN" and len(wires) == 5
    resumed = functional.message(root, **args, resume=True)
    assert resumed["status"] == "COMPLETED", resumed
    assert resumed["records"][0]["status"] == "visibility_revoked" and len(wires) == 6


@pytest.mark.parametrize("interrupt_save", [False, True])
def test_required_memory_receipt_precedes_delivery_without_repeating_business(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt_save: bool,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)
    control = {"one_shot_fault": {"message_index": 0, "boundary": "W3",
                                "target_operation": "save_memory", "occurrence": 1}}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return intent_reply(memory=True, required=True, business=True)
        if ordinal == 2:
            return native_call("reserve_and_label", "reserve", item_key="mechanical item",
                               quantity=1, destination="local", packing="box")
        if ordinal == 3:
            return {"role": "assistant", "content": "Business completed and memory saved."}
        if ordinal == 4:
            catalog = {t["function"]["name"] for t in wire["tools"]}
            assert all(m["role"] != "system" for m in wire["messages"][1:])
            assert {"save_memory", "get_reservation"} <= catalog
            assert not {"reserve_and_label", "complete_label", "forget_memory"} & catalog
            assert any(m["role"] == "system" and "withheld" in m["content"]
                       for m in wire["messages"])
            receipt = actual_tool_receipt(wire)
            return native_call("save_memory", "save", content="The item was reserved and labeled.",
                basis="tool_observation", fragment_handles=[
                    u["fragment_handle"] for u in receipt["source_fragment_index"]])
        assert ordinal == 5
        assert actual_tool_receipt(wire)["status"] == "committed"
        return {"role": "assistant", "content": "The actual reservation result is now saved."}

    wires = scripted(monkeypatch, reply, native=True)
    args = {"evaluator_control": control} if interrupt_save else {}
    result = message(root, **args)
    if interrupt_save:
        assert result["status"] == "UNKNOWN" and len(result["records"]) == 1
        assert result.get("final_answer") is None and len(wires) == 4
        result = message(root, **args, resume=True)
    assert result["status"] == "COMPLETED", result
    assert result["final_answer"] == "The actual reservation result is now saved."
    assert len(wires) == result["generation_calls"] == 5
    assert len(result["world"]["world"]["attempts"]) == len(result["records"]) == 1
    assert result["operation_status"]["semantic_memory"]["status"] == "committed"
    assert result["operation_status"]["request_completion"] == "unchecked"
    answers = [s["content"] for s in result["sources"] if s.get("role") == "assistant"]
    assert "Business completed and memory saved." not in answers


def test_missing_required_memory_attempt_fails_after_one_shared_completion_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return intent_reply(memory=True, required=True)
        return {"role": "assistant", "content": "Saved."}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result["error"] == "FUNCTIONAL_REQUIRED_MEMORY_OPERATION_MISSING", result
    assert result.get("final_answer") is None and len(wires) == 3
    assert result["operation_status"]["semantic_memory"]["status"] == "not_committed"
    assert not any(s.get("role") == "assistant" for s in result["sources"])
    resumed = message(root, resume=True)
    assert resumed["error"] == result["error"] and len(wires) == 3
    assert resumed["generation_calls"] == 3 and not resumed["records"]


def test_completion_feedback_cannot_reset_consumed_interpretation_repair_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return {"role": "assistant", "content": "invalid mode"}
        if ordinal == 2:
            return intent_reply(memory=True, required=True)
        assert ordinal == 3
        return {"role": "assistant", "content": "Saved."}

    wires = scripted(monkeypatch, reply, native=True)
    assert message(root)["error"] == "FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID"
    result = message(root, resume=True)
    assert result["error"] == "FUNCTIONAL_COMPLETION_FEEDBACK_BUDGET_EXHAUSTED"
    assert result.get("final_answer") is None and len(wires) == 3
    assert not result["records"]
    assert not any(s.get("role") == "assistant" for s in result["sources"])
    assert message(root, resume=True)["error"] == result["error"] and len(wires) == 3


def test_unified_save_commits_before_final_and_same_path_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            assert memory_effects(wire)["confirmed_semantic_commit_count"] == 0
            fragments = [row["fragment_handle"] for row in materials(wire)["items"]
                         if row["type"] == "fragment"]
            return tool("save_memory", content="The local marker is blue.",
                        fragment_handles=fragments)
        receipt = actual_tool_receipt(wire)
        assert receipt["ok"] and receipt["status"] == "committed"
        summary = memory_effects(wire)
        actual_ref = next(row["tool_call_id"] for row in reversed(wire["messages"])
                          if row["role"] == "tool")
        assert summary["confirmed_semantic_commit_count"] == 1
        assert summary["confirmed_semantic_commit_receipt_refs"] == [actual_ref]
        assert "The local marker is blue." not in json.dumps(summary)
        return {"answer": "Saved the marker."}

    wires = scripted(monkeypatch, reply)
    first = message(root)
    assert first["status"] == "COMPLETED", first
    assert first["operation_status"]["semantic_memory"]["status"] == "committed"
    assert first["operation_status"]["request_completion"] == "unchecked"
    assert len(first["records"]) == 1 and first["records"][0]["value"]["revision"] == 1
    assert first["snapshot_before_close"] is True
    assert first["memory_mutation_receipts"][0]["position"] < len(first["messages"]) - 1
    assert first["budget_after"]["generation_requests"] == len(wires) == 2
    again = message(root, resume=True)
    assert again["status"] == "COMPLETED", again
    assert again["records"] == first["records"] and len(wires) == 2
    assert again["budget_before"] == first["budget_after"] == again["budget_after"]
    restored = messages_from_dict([{"type": row["type"], "data": row}
                                   for row in again["messages"]])
    assert functional.memory_effects(restored) == memory_effects(wires[-1])


def test_unified_provider_failure_resume_keeps_budget_and_one_semantic_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> Any:
        if ordinal == 1:
            assert memory_effects(wire)["confirmed_semantic_commit_count"] == 0
            handles = [row["fragment_handle"] for row in materials(wire)["items"]
                       if row["type"] == "fragment"]
            return tool("save_memory", content="The local marker is blue.",
                        fragment_handles=handles)
        if ordinal == 2:
            assert memory_effects(wire)["confirmed_semantic_commit_count"] == 1
            return httpx.ReadTimeout("mechanical response interruption")
        assert memory_effects(wire)["confirmed_semantic_commit_count"] == 1
        assert memory_effects(wire) == memory_effects(wires[1])
        return {"answer": "The existing save is confirmed."}

    wires = scripted(monkeypatch, reply)
    first = message(root)
    assert first["status"] == "PROVIDER_ERROR", first
    assert first["operation_status"]["semantic_memory"]["status"] == "committed"
    assert first["final_delivery"]["status"] == "unavailable"
    assert len(first["records"]) == 1
    resumed = message(root, resume=True)
    assert resumed["status"] == "COMPLETED", resumed
    assert resumed["records"] == first["records"]
    assert resumed["operation_status"] == first["operation_status"]
    assert resumed["budget_after"]["generation_requests"] == len(wires) == 3
    assert resumed["budget_after"]["generation"]["unknown_usage"] == 1
    bank = next((root / "banks").iterdir())
    admission = read_json(bank / "message-admission.json")
    assert next(iter(admission["messages"].values()))["count"] == 3
    assert read_json(root / "queue-admission.json")["requests"] == 3


def test_structured_outcome_does_not_turn_raw_search_or_prose_into_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return tool("search_memory", query="local marker blue")
        assert actual_tool_receipt(wire)["semantic_write_performed"] is False
        return {"answer": "Saved the marker."}  # Deliberately false free prose.

    scripted(monkeypatch, reply)
    result = message(root)
    status = result["operation_status"]
    assert result["final_delivery"]["status"] == "available"
    assert status["raw_event"]["status"] == "stored"
    assert status["semantic_memory"] == {"status": "not_committed", "operations": []}
    assert status["business"]["status"] == "not_executed"
    assert status["request_completion"] == "unchecked" and not result["records"]


def test_duplicate_host_save_has_one_effect_and_separate_no_change_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal <= 2:
            hs = [u["fragment_handle"] for u in materials(wire)["items"] if u["type"] == "fragment"]
            return tool("save_memory", content="The local marker is blue.", fragment_handles=hs)
        receipt = actual_tool_receipt(wire)
        assert receipt["status"] == "no_change" and receipt["effect"] == "none"
        assert memory_effects(wire)["confirmed_semantic_commit_count"] == 1
        return {"answer": "The preference is already saved."}

    wires = scripted(monkeypatch, reply)
    result = message(root)
    assert result["status"] == "COMPLETED", result
    assert len(wires) == 3 and len(result["records"]) == 1
    statuses = result["operation_status"]["semantic_memory"]["operations"]
    assert sorted(row["status"] for row in statuses) == ["committed", "no_change"]
    assert len({row["id"] for row in statuses}) == 1
    assert result["records"][0]["value"]["revision"] == 1


def test_one_save_does_not_certify_other_requested_parts_or_later_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            handles = [r["fragment_handle"] for r in materials(wire)["items"]
                       if r["type"] == "fragment"]
            return tool("save_memory", content="A is blue.", fragment_handles=handles)
        return {"answer": "Both A and B are saved."}  # Unproven whole-request claim.

    wires = scripted(monkeypatch, reply)
    common = {"bank": "b", "owner": "alice", "session": "s"}
    saved = functional.message(root, **common, message_id="save",
                               content="Remember A is blue and B is round.")
    status = saved["operation_status"]
    assert len(status["semantic_memory"]["operations"]) == 1
    assert status["semantic_memory"]["operations"][0]["id"] == saved["records"][0]["id"]
    assert status["status_scope"] == "listed_current_message_operations_only"
    assert status["successful_operation_proves_unattempted_request_parts"] is False
    assert status["request_completion"] == "unchecked"
    read = functional.message(root, **common, message_id="read", content="What is A's color?")
    assert read["records"] == saved["records"] and len(wires) == 3
    assert read["operation_status"]["semantic_memory"] == {
        "status": "not_committed", "operations": []}


@pytest.mark.parametrize("bad", [None, "", "{", "truncated"])
def test_native_bad_final_preserves_commit_and_resumes_without_repeating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str | None,
) -> None:
    root = prepared(tmp_path, native=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            handles = [r["fragment_handle"] for r in materials(wire)["items"]
                       if r["type"] == "fragment"]
            return {"role": "assistant", "content": None, "tool_calls": [{
                "type": "function", "id": "actual-native-save", "function": {
                    "name": "save_memory", "arguments": json.dumps({
                        "content": "The local marker is blue.", "fragment_handles": handles})}}]}
        if ordinal == 2:
            return {"role": "assistant", "content": None if bad == "truncated" else bad,
                    "_test_finish_reason": "length" if bad == "truncated" else "stop",
                    "reasoning_content": "REASONING_MUST_NOT_BECOME_FINAL"}
        assert not wire.get("tools")  # Answer-only recovery cannot execute a tool.
        return {"role": "assistant", "content": "The existing save is confirmed."}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first["status"] == "FAILED", first
    assert first["error_category"] == (
        "provider_protocol" if bad in {None, "truncated"} else "final_delivery")
    assert first["final_delivery"]["status"] == "unavailable"
    assert first.get("final_answer") != "REASONING_MUST_NOT_BECOME_FINAL"
    assert first["operation_status"]["semantic_memory"]["status"] == "committed"
    assert len(first["records"]) == 1 and first["records"][0]["value"]["revision"] == 1
    resumed = message(root, resume=True)
    assert resumed["status"] == "COMPLETED", resumed
    assert resumed["final_delivery"]["status"] == "available"
    assert resumed["records"] == first["records"] and len(wires) == 3
    assert resumed["operation_status"] == first["operation_status"]
    again = message(root, resume=True)
    assert again["final_answer"] == resumed["final_answer"] and len(wires) == 3


def test_final_text_recovery_uses_the_single_durable_format_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True)
    wires = scripted(monkeypatch, lambda wire, ordinal: {"role": "assistant", "content": "{"},
                     native=True)
    first = message(root)
    assert first["status"] == "FAILED"
    second = message(root, resume=True)
    assert second["status"] == "FAILED" and len(wires) == 2
    third = message(root, resume=True)
    assert third["status"] == "FAILED" and len(wires) == 2
    assert third["error"] == "FUNCTIONAL_FINAL_ANSWER_REPAIR_BUDGET_EXHAUSTED"
    assert third["operation_status"]["semantic_memory"]["status"] == "not_committed"


@pytest.mark.parametrize("bad", [None, "{", "truncated"])
def test_answer_recovery_preserves_real_business_and_memory_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str | None,
) -> None:
    root = prepared(tmp_path, native=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            name, args = "reserve_and_label", {
                "item_key": "local parcel", "quantity": 1, "destination": "local", "packing": "box"}
        elif ordinal == 2:
            receipt = actual_tool_receipt(wire)
            name, args = "save_memory", {
                "content": "The local parcel was reserved and labeled.",
                "fragment_handles": [r["fragment_handle"]
                                     for r in receipt["source_fragment_index"]]}
        elif ordinal == 3:
            return {"role": "assistant", "content": None if bad == "truncated" else bad,
                    "_test_finish_reason": "length" if bad == "truncated" else "stop"}
        else:
            assert ordinal == 4 and not wire.get("tools")
            return {"role": "assistant", "content": "The reservation and record are confirmed."}
        return {"role": "assistant", "content": None, "tool_calls": [{
            "type": "function", "id": "call-" + str(ordinal), "function": {
                "name": name, "arguments": json.dumps(args)}}]}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first["status"] == "FAILED", first
    assert first["operation_status"]["business"]["status"] == "completed"
    assert first["operation_status"]["semantic_memory"]["status"] == "committed"
    resumed = message(root, resume=True)
    assert resumed["status"] == "COMPLETED", resumed
    assert resumed["records"] == first["records"]
    assert resumed["world"]["world"] == first["world"]["world"]
    assert len(resumed["world"]["world"]["attempts"]) == 1
    assert resumed["operation_status"] == first["operation_status"]
    assert len(wires) == 4


@pytest.mark.parametrize("bad", ["none", "empty", "tools", "transport", "interruption"])
def test_readonly_response_is_durable_bounded_and_preserves_actual_partial_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call("reserve_and_label", "reserve", item_key="partial item",
                               quantity=1, destination="local", packing="box")
        if ordinal == 2:
            receipt = actual_tool_receipt(wire)
            return native_call("save_memory", "save", content="Reservation done, label failed.",
                fragment_handles=[r["fragment_handle"] for r in receipt["source_fragment_index"]])
        if ordinal == 3:
            return {"role": "assistant", "content": "Saved."}
        assert ordinal in {4, 5}
        assert not wire.get("tools") and wire.get("tool_choice", "none") == "none"
        assert [m["role"] for m in wire["messages"]] == ["system", "user"]
        evidence = json.loads(wire["messages"][1]["content"])
        assert evidence["delivered_material"]["schema"] == "functional_material_v1"
        assert "Saved." not in wire["messages"][1]["content"]
        assert any(e.get("name") == "reserve_and_label" for e in evidence["actual_tool_events"])
        assert '"status": "partial"' in wire["messages"][0]["content"]
        if ordinal == 4 and bad == "empty":
            return {"role": "assistant", "content": "{"}
        if ordinal == 4 and bad == "tools":
            return native_call("reserve_and_label", "forbidden", item_key="another item",
                               quantity=1, destination="local", packing="box")
        if ordinal == 4 and bad == "transport":
            return {"role": "assistant", "content": None, "_test_finish_reason": "length"}
        return {"role": "assistant", "content": "Reserved; label failed. Partial result saved."}

    wires = scripted(monkeypatch, reply, native=True)
    args = {"initial_world": {"label_available": False}}
    if bad == "interruption":
        args["evaluator_control"] = {"one_shot_fault": {
            "message_index": 0, "boundary": "W3", "target_operation": "save_memory",
            "occurrence": 1}}
    result = message(root, **args)
    if bad != "none":
        assert result["status"] != "COMPLETED" and result.get("final_answer") is None
        assert result["operation_status"]["business"]["status"] == "partial"
        result = message(root, **args, resume=True)
    assert result["status"] == "COMPLETED", result
    assert result["execution_candidate_answer"] == "Saved."
    assert result["final_answer"] == "Reserved; label failed. Partial result saved."
    assert len(result["world"]["world"]["attempts"]) == len(result["records"]) == 1
    assert all(s["content"] != "Saved." for s in result["sources"] if s["role"] == "assistant")
    calls = len(wires)
    resumed = message(root, **args, resume=True)
    assert resumed["status"] == "COMPLETED", resumed
    assert len(wires) == calls == (4 if bad in {"none", "interruption"} else 5)
    assert resumed["world"]["world"] == result["world"]["world"]


def test_readonly_response_does_not_reset_exhausted_retry_on_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True)
    wires = scripted(monkeypatch, lambda wire, ordinal: {
        "role": "assistant", "content": "Execution draft." if ordinal == 1 else "{"}, native=True)
    first = message(root)
    assert first["status"] == "FAILED" and len(wires) == 2
    second = message(root, resume=True)
    assert second["status"] == "FAILED" and len(wires) == 3
    third = message(root, resume=True)
    assert third["status"] == "FAILED" and len(wires) == 3
    assert third["error"] == "FUNCTIONAL_FINALIZATION_REPAIR_BUDGET_EXHAUSTED"


def test_memory_effects_uses_paired_current_receipts_without_promoting_reads_or_unknowns() -> None:
    secret = "MECHANICAL_BODY_MUST_NOT_APPEAR_IN_EFFECTS"
    committed = {"ok": True, "status": "committed", "effect": "memory_only",
                 "id": "actual-record", "revision": 1, "content": secret}

    def call(name: str, ref: str) -> AIMessage:
        return AIMessage(content=secret, id="generation-" + ref, tool_calls=[{
            "name": name, "id": ref, "args": {"content": secret}}])

    def receipt(name: str, ref: str, value: dict[str, Any], *, error: bool = False) -> ToolMessage:
        return ToolMessage(name=name, tool_call_id=ref, content=json.dumps(value),
                           status="error" if error else "success")

    old = [HumanMessage(content="old request"), call("save_memory", "old"),
           receipt("save_memory", "old", committed)]
    current = [HumanMessage(content="current request"),
        receipt("save_memory", "unpaired", committed),
        call("save_memory", "wrong-name"), receipt("update_memory", "wrong-name", committed),
        call("save_memory", "pending"),
        call("save_memory", "unknown"), receipt("save_memory", "unknown", {
            "ok": False, "status": "outcome_unknown", "effect": "unconfirmed", "reason": secret}),
        call("save_memory", "failed"), receipt("save_memory", "failed", committed, error=True),
        call("search_memory", "read"), receipt("search_memory", "read", committed),
        call("update_memory", "unchanged"), receipt("update_memory", "unchanged", {
            "ok": True, "status": "no_change", "effect": "none"}),
        call("forget_memory", "forget"), receipt("forget_memory", "forget", {
            "ok": True, "status": "visibility_revoked", "effect": "visibility_only"})]
    zero = functional.memory_effects([*old, *current])
    assert zero["confirmed_semantic_commit_count"] == 0
    assert zero["confirmed_semantic_commit_receipt_refs"] == []
    assert zero["pending_mutation_call_refs"] == ["pending"]
    assert {row["receipt_ref"] for row in zero["mutation_receipts"]} == {
        "unknown", "failed", "unchanged", "forget"}
    assert secret not in json.dumps(zero)
    final = functional.memory_effects([*old, *current,
        call("save_memory", "actual"), receipt("save_memory", "actual", committed),
        call("update_memory", "recovered"), receipt("update_memory", "recovered", {
            **committed, "status": "no_change", "original_status": "committed", "replayed": True})])
    assert final["confirmed_semantic_commit_count"] == 2
    assert final["confirmed_semantic_commit_receipt_refs"] == ["actual", "recovered"]
    assert final["semantic_completion"] == "unchecked"
    assert final["raw_capture_is_semantic_save"] is False
    assert final["reads_perform_semantic_writes"] is False
    assert secret not in json.dumps(final)


def test_public_agent_catalog_carries_per_field_correction_selections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        packet = materials(wire)
        if ordinal == 1:
            return tool("save_memory", content="Distance uses miles.", scope={"project": "Alpha"},
                        fragment_handles=[u["fragment_handle"] for u in packet["items"]
                                          if u["type"] == "fragment"])
        if ordinal == 3:
            record = next(u for u in packet["items"] if u["type"] == "record")
            correction = [u["fragment_handle"] for u in packet["items"]
                          if u["type"] == "fragment" and u["input_relation"] == "current_request"]
            return tool("update_memory", read_handle=record["read_handle"], changes=[{
                "field": "content", "op": "set", "value": "Distance uses kilometers.",
                "fragment_handles": correction}])
        assert actual_tool_receipt(wire)["status"] == "committed"
        return {"answer": "The actual memory change is confirmed."}

    wires = scripted(monkeypatch, reply)
    common = {"bank": "b", "owner": "alice", "session": "s"}
    saved = functional.message(root, **common, message_id="save",
                               content="Remember that project Alpha uses miles for distance.")
    assert saved["status"] == "COMPLETED", saved
    revised = functional.message(
        root, **common, message_id="correct",
        content="Change distance to kilometers; project Alpha is unchanged.")
    assert revised["status"] == "COMPLETED", revised
    assert len(wires) == 4 and len(revised["records"]) == 1
    assert revised["records"][0]["id"] == saved["records"][0]["id"]
    value = revised["records"][0]["value"]
    assert value["revision"] == 2 and value["content"] == "Distance uses kilometers."
    assert value["functional_support"]["content"]["source_refs"] == [
        revised["capture"]["source_ref"]]
    assert value["functional_support"]["scope.project"] == (
        saved["records"][0]["value"]["functional_support"]["scope.project"])


@pytest.mark.parametrize("workflow", ["reservation", "document"])
def test_unified_business_receipt_exposes_real_handles_for_immediate_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workflow: str,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if workflow == "document":
            if ordinal == 1:
                return tool("create_or_update_draft", title="mechanical draft",
                            content="local body", document_version=0, content_digest="")
            if ordinal in {2, 3}:
                observed = actual_tool_receipt(wire)["receipt"]
                bound = {k: observed[k] for k in ("title", "document_version", "content_digest")}
                if ordinal == 2:
                    return tool("approve_document_version", **bound)
                return tool("publish_approved_document", **bound, audience="local audience")
            if ordinal == 4:
                result = actual_tool_receipt(wire)
                assert result["receipt"]["publication_status"] == "published"
                return tool("save_memory", content="The draft was approved and published locally.",
                            fragment_handles=[row["fragment_handle"]
                                              for row in result["source_fragment_index"]])
            assert actual_tool_receipt(wire)["status"] == "committed"
            return {"answer": "The actual local publication is recorded."}
        if ordinal == 1:
            return tool("reserve_and_label", item_key="mechanical item", quantity=1,
                        destination="local", packing="box")
        if ordinal == 2:
            result = actual_tool_receipt(wire)
            assert result["receipt"]["label_status"] == "created"
            return tool("save_memory", content="The mechanical item was reserved and labeled.",
                        fragment_handles=[row["fragment_handle"]
                                          for row in result["source_fragment_index"]])
        assert actual_tool_receipt(wire)["status"] == "committed"
        return {"answer": "The actual reservation and label are recorded."}

    wires = scripted(monkeypatch, reply)
    actual = message(root, workflow=workflow)
    assert actual["status"] == "COMPLETED", actual
    world = actual["world"]["world"]
    if workflow == "document":
        assert len(world["documents"][0]["publications"]) == 1 and len(wires) == 5
    else:
        assert len(world["attempts"]) == 1 and len(wires) == 3
    value = actual["records"][0]["value"]
    assert value["basis"] == "tool_observation"
    assert value["source_ref"] != actual["capture"]["source_ref"]
    assert actual["operation_status"]["business"]["status"] == "completed"
    assert actual["operation_status"]["semantic_memory"]["status"] == "committed"


def test_disabled_profile_blocks_before_provider_or_budget_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)
    before = read_json(Path(functional.frozen(root)["config"]["budget_path"]))
    wires = scripted(monkeypatch, lambda wire, ordinal: {"answer": "unreachable"})
    write_json(root / "profile-state.json", {"disabled": True, "persistent_data_deleted": False})
    with pytest.raises(ValueError, match="FUNCTIONAL_PROFILE_DISABLED"):
        message(root)
    assert wires == [] and not (root / "queue-admission.json").exists()
    assert read_json(Path(functional.frozen(root)["config"]["budget_path"])) == before


def test_queue_exhaustion_preserves_committed_memory_and_does_not_reset_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, queue_requests=1)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        assert ordinal == 1
        handles = [row["fragment_handle"] for row in materials(wire)["items"]
                   if row["type"] == "fragment"]
        return tool("save_memory", content="The local marker is blue.", fragment_handles=handles)

    wires = scripted(monkeypatch, reply)
    first = message(root)
    assert first["status"] == "BUDGET_EXHAUSTED", first
    assert len(first["records"]) == 1 and len(wires) == 1
    resumed = message(root, resume=True)
    assert resumed["status"] == "BUDGET_EXHAUSTED", resumed
    assert first["records"] == resumed["records"] and len(wires) == 1
    assert resumed["budget_after"]["generation_requests"] == 1
    assert read_json(root / "queue-admission.json")["requests"] == 1


@pytest.mark.parametrize("boundary,happened", [
    ("after_journal_intent_before_native", False),
    ("after_native_before_journal_complete", True),
])
def test_unified_unknown_recovery_uses_actual_public_discovery_without_hidden_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str, happened: bool,
) -> None:
    root = prepared(tmp_path)
    control = {"one_shot_fault": {"message_index": 0, "boundary": boundary,
                                  "target_operation": "reserve_and_label", "occurrence": 1}}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        assert boundary not in json.dumps(wire)
        assert "one_shot_fault" not in json.dumps(wire)
        if ordinal == 1:
            return tool("reserve_and_label", item_key="mechanical item", quantity=1,
                        destination="local", packing="box")
        if ordinal == 3:
            assert actual_tool_receipt(wire)["status"] == "committed"
            return {"answer": "The actual discovered state is recorded."}
        observed = actual_tool_receipt(wire)
        assert observed["status"] == "ORIGINAL_CALL_OUTCOME_UNKNOWN"
        assert observed["original_receipt"] is None
        assert observed["observed_effect"] == ("confirmed" if happened else "none")
        query_source = observed["query_source"]
        assert query_source["origin"] == "get_reservation"
        assert all(row["source_ref"] == query_source["source_ref"]
                   for row in query_source["source_fragment_index"])
        return tool("save_memory", content=("The item is reserved and labeled." if happened else
                                              "Public lookup found no reservation for the item."),
                    fragment_handles=[row["fragment_handle"]
                                      for row in query_source["source_fragment_index"]])

    wires = scripted(monkeypatch, reply)
    first = message(root, evaluator_control=control)
    assert first["status"] == "UNKNOWN", first
    assert first["evaluator_control_state"]["fault"]["applied"] is True
    assert len(first["sources"]) == 1
    assert first["operation_status"]["business"]["status"] == "unknown"
    final = message(root, evaluator_control=control, resume=True)
    assert final["status"] == "COMPLETED", final
    assert len(wires) == 3
    assert len(final["records"]) == 1
    assert final["records"][0]["value"]["basis"] == "tool_observation"
    assert len(final["world"]["world"]["attempts"]) == int(happened)
    pending = [row for row in final["world"]["journal"].values()
               if row.get("name") == "reserve_and_label"]
    assert len(pending) == 1 and pending[0]["status"] == "pending"
    assert "result" not in pending[0]
    discoveries = [row for row in final["sources"] if row["origin"] == "get_reservation"]
    assert len(discoveries) == 1
    status = final["operation_status"]["business"]
    assert status["status"] == ("completed" if happened else "no_effect")
    assert len(status["operations"]) == 1 and len(status["observations"]) == 1
    assert status["operations"][0]["effect"] == "unknown"
    assert status["operations"][0]["execution_receipt_status"] == "pending"
    assert status["operations"][0]["observed_effect"] == ("confirmed" if happened else "none")


def test_multiple_forgets_remove_intervening_revoked_tool_body_from_next_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)
    seen: dict[str, Any] = {}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        packet = materials(wire)
        if ordinal in {1, 3}:
            content = "MECHANICAL_SECRET_A" if ordinal == 1 else "MECHANICAL_SECRET_B"
            if ordinal == 3:
                # B's actual user input arrived before this retrieval of A.
                # Co-exposure is not provenance: only B's own source is selected
                # for saving B, and forgetting A must retain this independent fact.
                assert "MECHANICAL_SECRET_A" in json.dumps(packet)
            current = [row for row in packet["items"] if row["type"] == "fragment"
                       and content in row["content"]]
            return tool("save_memory", content="marker " + content,
                        fragment_handles=[row["fragment_handle"] for row in current])
        if ordinal in {2, 4}:
            return {"answer": "Saved."}
        if ordinal == 5:
            records = {row["content"].split()[-1]: row for row in packet["items"]
                       if row["type"] == "record"}
            seen["second_id"] = records["MECHANICAL_SECRET_B"]["record_id"]
            return tool("forget_memory", read_handle=records["MECHANICAL_SECRET_A"]["read_handle"])
        if ordinal == 6:
            return tool("read_memory", record_id=seen["second_id"])
        if ordinal == 7:
            actual = actual_tool_receipt(wire)
            assert actual.get("ok"), "Forgetting A must preserve independently supplied B"
            record = next(row for row in actual["items"] if row["type"] == "record")
            assert record["content"] == "marker MECHANICAL_SECRET_B"
            return tool("forget_memory", read_handle=record["read_handle"])
        seen["post_forget_wire"] = json.dumps(wire, ensure_ascii=False)
        return {"answer": "Both records are forgotten."}

    wires = scripted(monkeypatch, reply)
    for index, content in enumerate(("Remember marker MECHANICAL_SECRET_A.",
                                     "Remember marker MECHANICAL_SECRET_B.",
                                     "Forget both marker records.")):
        actual = functional.message(root, bank="mechanical-bank", owner="alice", session="session",
                                    message_id="m" + str(index), content=content)
        assert actual["status"] == "COMPLETED", actual
    assert len(wires) == 8
    assert "MECHANICAL_SECRET_A" not in seen["post_forget_wire"]
    assert "MECHANICAL_SECRET_B" not in seen["post_forget_wire"]


def test_pending_public_read_resumes_with_a_distinct_real_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)
    control = {"one_shot_fault": {"message_index": 0,
        "boundary": "after_native_before_journal_complete",
        "target_operation": "get_reservation", "occurrence": 1}}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return tool("get_reservation", item_key="mechanical item")
        discovery = actual_tool_receipt(wire)
        assert discovery["status"] == "ORIGINAL_CALL_OUTCOME_UNKNOWN"
        assert discovery["original_receipt"] is None and discovery["observed_effect"] == "none"
        assert discovery["effect_source"] == "native_public_read_contract_no_business_mutation"
        assert discovery["query_receipt"]["status"] == "not_found"
        return {"answer": "The fresh public query found no item."}

    wires = scripted(monkeypatch, reply)
    first = message(root, evaluator_control=control)
    assert first["status"] == "UNKNOWN"
    final = message(root, evaluator_control=control, resume=True)
    assert final["status"] == "COMPLETED", final
    assert len(wires) == 2 and final["world"]["world"]["attempts"] == []
    calls = [row for row in final["world"]["journal"].values()
             if row.get("name") == "get_reservation"]
    assert sorted(row["status"] for row in calls) == ["complete", "pending"]


def test_forget_w3_commit_reopens_same_input_without_restoring_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)
    control = {"one_shot_fault": {"message_index": 1, "boundary": "W3",
        "target_operation": "forget_memory", "occurrence": 1}}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            fragments = [row["fragment_handle"] for row in materials(wire)["items"]
                         if row["type"] == "fragment"]
            return tool("save_memory", content="marker MECHANICAL_FORGET_RESUME",
                        fragment_handles=fragments)
        if ordinal == 2:
            return {"answer": "Saved."}
        if ordinal == 3:
            record = next(row for row in materials(wire)["items"] if row["type"] == "record")
            return tool("forget_memory", read_handle=record["read_handle"])
        assert actual_tool_receipt(wire)["status"] == "visibility_revoked"
        assert "MECHANICAL_FORGET_RESUME" not in json.dumps(wire)
        assert not any(row["type"] == "fragment" for row in materials(wire)["items"])
        return {"answer": "Forgotten."}

    wires = scripted(monkeypatch, reply)
    first = functional.message(root, bank="mechanical-bank", owner="alice", session="session",
        message_id="save", content="Remember marker MECHANICAL_FORGET_RESUME.")
    assert first["status"] == "COMPLETED"
    args = {"bank": "mechanical-bank", "owner": "alice", "session": "session",
            "message_id": "forget", "content": "Forget the marker.",
            "evaluator_control": control, "message_index": 1}
    interrupted = functional.message(root, **args)
    assert interrupted["status"] == "UNKNOWN"
    assert interrupted["error_type"] == "InjectedInterruption"
    assert len(wires) == 3
    recovered = functional.message(root, **args, resume=True)
    assert recovered["status"] == "COMPLETED", recovered
    assert len(wires) == 4
    assert len(recovered["records"]) == 1
    assert recovered["records"][0]["status"] == "visibility_revoked"


def test_forget_trims_other_arguments_from_the_same_tool_call_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)
    seen: dict[str, Any] = {}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        packet = materials(wire)
        if ordinal == 1:
            return tool("save_memory", content="marker MECHANICAL_SECRET_A", fragment_handles=[
                row["fragment_handle"] for row in packet["items"] if row["type"] == "fragment"])
        if ordinal == 2:
            return {"answer": "Saved."}
        if ordinal == 3:
            record = next(row for row in packet["items"] if row["type"] == "record")
            return {"calls": [
                {"name": "search_memory", "arguments": {"query": "MECHANICAL_SECRET_A"}},
                {"name": "forget_memory", "arguments": {"read_handle": record["read_handle"]}},
            ]}
        seen["post_forget_wire"] = json.dumps(wire, ensure_ascii=False)
        return {"answer": "Forgotten."}

    wires = scripted(monkeypatch, reply)
    for index, content in enumerate(("Remember marker MECHANICAL_SECRET_A.", "Forget the marker.")):
        actual = functional.message(root, bank="mechanical-bank", owner="alice", session="session",
                                    message_id="m" + str(index), content=content)
        assert actual["status"] == "COMPLETED", actual
    assert len(wires) == 4
    assert all(row["status"] == "visibility_revoked" and "value" not in row
               for row in actual["records"])
    assert "MECHANICAL_SECRET_A" not in seen["post_forget_wire"]


@pytest.mark.parametrize('action', ['none', 'perform', 'continue_if_unfinished'])
def test_action_declaration_binds_current_clause_and_preserves_catalog_on_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    root = prepared(tmp_path, native=True, action_mode_declaration=True, receipt_response=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            current = wire['messages'][-1]['content']
            return native_call('classify_current_request', 'intent', memory_write_request='none',
                allow_forgetting=False, business_action_request=action,
                business_action_quote='' if action == 'none' else current)
        if ordinal == 2:
            names = {t['function']['name'] for t in wire['tools']}
            assert ('complete_label' in names) == (action != 'none')
            assert 'save_memory' not in names
            return native_call('get_reservation', 'query', item_key='empty shelf')
        assert ordinal == 3
        return {'role': 'assistant', 'content': 'Fabricated reservation and memory saved.'}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result['status'] == 'COMPLETED', result
    assert result['request_mode']['business_action_request'] == action
    assert result['request_mode']['semantic_correctness'] == 'unchecked'
    assert result['finalization']['model_generation'] is False
    assert 'Fabricated' not in result['final_answer']
    assert '未查到对象' in result['final_answer']
    assert '本轮语义记忆: 未提交' in result['final_answer']
    assert not result['world']['world']['reservations'] and not result['records']
    reopened = message(root, resume=True)
    assert reopened['final_answer'] == result['final_answer'] and len(wires) == 3


@pytest.mark.parametrize('action,quote', [('continue_if_unfinished', 'not in current input'),
                                          ('none', 'unrequested permission'), ('bad', '')])
def test_action_declaration_rejects_unbound_or_invalid_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str, quote: str,
) -> None:
    root = prepared(tmp_path, native=True, action_mode_declaration=True)
    wires = scripted(monkeypatch, lambda wire, ordinal: native_call(
        'classify_current_request', 'intent', memory_write_request='none', allow_forgetting=False,
        business_action_request=action, business_action_quote=quote), native=True)
    for resume in [False, True]:
        result = message(root, resume=resume)
        assert result['error'] == 'FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID'
        assert not result['world']['world']['attempts']
    assert message(root, resume=True)['error'] == 'FUNCTIONAL_REQUEST_MODE_REPROPOSAL_EXHAUSTED'
    assert len(wires) == 2


@pytest.mark.parametrize('interrupted', [False, True])
def test_receipt_response_preserves_partial_and_save_effect_across_w3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True, receipt_response=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('reserve_and_label', 'reserve', item_key='partial item',
                               quantity=2, destination='local', packing='box')
        if ordinal == 2:
            receipt = actual_tool_receipt(wire)
            return native_call('save_memory', 'save', content='Reservation done; label failed.',
                fragment_handles=[r['fragment_handle'] for r in receipt['source_fragment_index']])
        assert ordinal == 3
        return {'role': 'assistant', 'content': 'All business phases succeeded.'}

    wires = scripted(monkeypatch, reply, native=True)
    kwargs = {'initial_world': {'label_available': False}}
    if interrupted:
        kwargs['evaluator_control'] = {'one_shot_fault': {
            'message_index': 0, 'boundary': 'W3', 'target_operation': 'save_memory',
            'occurrence': 1}}
    first = message(root, **kwargs)
    if interrupted:
        assert first['status'] == 'UNKNOWN' and not first.get('final_answer')
        first = message(root, **kwargs, resume=True)
    assert first['status'] == 'COMPLETED', first
    assert '预订成功, 标签制作失败' in first['final_answer']
    assert '本轮语义记忆: 已提交' in first['final_answer']
    assert 'All business phases succeeded' not in first['final_answer']
    assert len(first['records']) == len(first['world']['world']['attempts']) == 1
    assert message(root, **kwargs, resume=True)['final_answer'] == first['final_answer']
    assert len(wires) == 3


def test_exhausted_reads_end_execution_with_effects_and_cannot_reset_on_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, receipt_response=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('reserve_and_label', 'reserve', item_key='retained item',
                               quantity=1, destination='local', packing='box')
        assert ordinal <= 5  # Three actual additional reads; fourth is rejected.
        return native_call('search_memory', 'read-' + str(ordinal), query='retained item')

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first['status'] == 'FAILED' and first['error'] == 'FUNCTIONAL_READ_LIMIT_EXHAUSTED'
    assert first['final_delivery']['status'] == 'available'
    assert first['operation_status']['business']['status'] == 'completed'
    assert first['generation_calls'] == 5
    assert '追加读取额度已用完' in first['final_answer']
    assert first['operation_status']['semantic_memory']['status'] == 'not_committed'
    second = message(root, resume=True)
    assert second['status'] == 'FAILED' and second['final_answer'] == first['final_answer']
    assert second['world']['world'] == first['world']['world'] and len(wires) == 5


@pytest.mark.parametrize('publication_available', [True, False])
def test_document_receipt_response_reports_distinct_draft_approval_and_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publication_available: bool,
) -> None:
    from milai_lab.application.document_publication import DOCUMENT_NAMES
    from milai_lab.application.tools import BUSINESS_NAMES
    from milai_lab.runners.functional_response import _TOOLS

    assert set(_TOOLS) == set(DOCUMENT_NAMES) | set(BUSINESS_NAMES)
    root = prepared(tmp_path, native=True, receipt_response=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('create_or_update_draft', 'draft', title='Local guide',
                               content='Use the side entrance.')
        if ordinal in {2, 3}:
            receipt = actual_tool_receipt(wire)['receipt']
            args = {k: receipt[k] for k in ['title', 'document_version', 'content_digest']}
            if ordinal == 3:
                args['audience'] = 'local review team'
            return native_call('approve_document_version' if ordinal == 2
                               else 'publish_approved_document', 'phase-' + str(ordinal), **args)
        assert ordinal == 4
        return {'role': 'assistant', 'content': 'Invented global distribution.'}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root, workflow='document',
                     initial_world={'publication_available': publication_available})
    assert result['status'] == 'COMPLETED', result
    assert '草稿已创建' in result['final_answer'] and '文档已批准' in result['final_answer']
    assert ('文档已发布到本地沙箱' in result['final_answer']) == publication_available
    assert ('发布服务不可用' in result['final_answer']) != publication_available
    assert 'Invented' not in result['final_answer'] and len(wires) == 4
    assert result['operation_status']['business']['status'] == (
        'completed' if publication_available else 'partial')


def test_receipt_response_cannot_replay_revoked_business_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True, receipt_response=True)
    private_item = 'RECEIPT_PRIVATE_ITEM'

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('reserve_and_label', 'reserve', item_key=private_item,
                               quantity=1, destination='local', packing='box')
        if ordinal == 2:
            receipt = actual_tool_receipt(wire)
            return native_call('save_memory', 'save', content='Reserved ' + private_item,
                fragment_handles=[r['fragment_handle'] for r in receipt['source_fragment_index']])
        if ordinal == 3:
            return {'role': 'assistant', 'content': 'Execution done.'}
        if ordinal == 4:
            record = next(row for row in materials(wire)['items'] if row['type'] == 'record')
            return native_call('forget_memory', 'forget', read_handle=record['read_handle'])
        assert ordinal in {5, 6}
        assert private_item not in json.dumps(wire)
        return {'role': 'assistant', 'content': 'Forgotten within the requested scope.'}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first['status'] == 'COMPLETED' and private_item in first['final_answer']
    forgotten = functional.message(root, bank='mechanical-bank', owner='alice', session='session',
                                   message_id='forget', content='Forget the saved item.')
    assert forgotten['status'] == 'COMPLETED', forgotten
    reopened = message(root, resume=True)
    assert reopened['status'] == 'VISIBILITY_REVOKED' and reopened['final_answer'] is None
    assert private_item not in json.dumps(reopened) and len(wires) == 6


@pytest.mark.parametrize('write_request', ['new_assertion', 'explicit', 'none'])
def test_declared_write_completion_requires_attempt_without_business_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_request: str,
) -> None:
    root = prepared(tmp_path, native=True, action_mode_declaration=True,
                    receipt_response=True, declared_writes=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'intent',
                memory_write_request=write_request, allow_forgetting=False,
                business_action_request='perform',
                business_action_quote=wire['messages'][-1]['content'])
        if ordinal == 2:
            return native_call('reserve_and_label', 'reserve', item_key='one real item',
                               quantity=1, destination='local', packing='box')
        if ordinal == 3:
            return {'role': 'assistant', 'content': 'Execution draft omitted saving.'}
        assert write_request != 'none'
        names = {t['function']['name'] for t in wire['tools']}
        assert 'reserve_and_label' not in names and 'forget_memory' not in names
        assert 'save_memory' in names
        if ordinal == 4:
            assert 'withheld' in wire['messages'][0]['content']
            event = next(json.loads(m['content']) for m in wire['messages']
                         if m['role'] == 'tool' and 'source_fragment_index' in m['content'])
            return native_call('save_memory', 'save', content='Reservation and label completed.',
                fragment_handles=[u['fragment_handle'] for u in event['source_fragment_index']])
        assert ordinal == 5
        return {'role': 'assistant', 'content': 'Actual receipt received.'}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first['status'] == 'COMPLETED', first
    assert len(first['records']) == (0 if write_request == 'none' else 1)
    assert len(first['world']['world']['attempts']) == 1
    before = len(wires)
    second = message(root, resume=True)
    assert second['status'] == 'COMPLETED' and second['final_answer'] == first['final_answer']
    assert len(wires) == before == (3 if write_request == 'none' else 5)


def test_publish_only_permission_prevents_status_summary_from_editing_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, operation_mode_declaration=True, receipt_response=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 5}:
            return native_call('classify_current_request', 'intent', memory_write_request='none',
                allow_forgetting=False, business_action_request='perform' if ordinal == 1
                else 'continue_if_unfinished',
                business_action_quote=wire['messages'][-1]['content'],
                business_operations=['create_or_update_draft', 'approve_document_version']
                if ordinal == 1 else ['publish_approved_document'])
        if ordinal == 2:
            return native_call('create_or_update_draft', 'draft', title='Stable document',
                               content='Keep this original body.')
        if ordinal == 3:
            receipt = actual_tool_receipt(wire)['receipt']
            return native_call('approve_document_version', 'approve', **{
                k: receipt[k] for k in ['title', 'document_version', 'content_digest']})
        if ordinal in {4, 9}:
            return {'role': 'assistant', 'content': 'Actual operations reported.'}
        names = {t['function']['name'] for t in wire['tools']}
        assert 'publish_approved_document' in names and 'get_document_status' in names
        assert not {'create_or_update_draft', 'approve_document_version', 'save_memory'} & names
        if ordinal == 6:
            return native_call('get_document_status', 'query', title='Stable document')
        receipt = actual_tool_receipt(wire)['receipt']
        bound = {k: receipt[k] for k in ['title', 'document_version', 'content_digest']}
        if ordinal == 7:
            return native_call('publish_approved_document', 'publish',
                               audience='local group', **bound)
        assert ordinal == 8
        return native_call('create_or_update_draft', 'forbidden-edit',
                           content='Wrong status summary instead of document body.', **bound)

    wires = scripted(monkeypatch, reply, native=True)
    common = {'bank': 'b', 'owner': 'alice', 'session': 's', 'workflow': 'document'}
    first = functional.message(root, **common, message_id='draft', content='Create and approve.')
    assert first['status'] == 'COMPLETED', first
    second = functional.message(root, **common, message_id='publish', content='Only publish now.')
    assert second['status'] == 'FAILED' and second['error'] == 'VLLM_CHAT_UNKNOWN_TOOL'
    assert second['operation_status']['business']['status'] == 'completed'
    world = second['world']['world']
    assert len(world['documents']) == 1 and len(world['documents'][0]['versions']) == 1
    assert world['documents'][0]['content'] == 'Keep this original body.'
    assert world['documents'][0]['publication_status'] == 'published'
    recovered = functional.message(root, **common, message_id='publish',
                                   content='Only publish now.', resume=True)
    assert recovered['status'] == 'COMPLETED', recovered
    assert recovered['world']['world'] == world and len(wires) == 9
    assert 'Wrong status summary' not in recovered['final_answer']


@pytest.mark.parametrize('operations', [[], ['publish_approved_document'] * 2,
                                       ['save_memory'], ['unknown_operation']])
def test_operation_declaration_rejects_inconsistent_or_unknown_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operations: list[str],
) -> None:
    root = prepared(tmp_path, native=True, operation_mode_declaration=True)
    wires = scripted(monkeypatch, lambda wire, ordinal: native_call(
        'classify_current_request', 'intent', memory_write_request='none', allow_forgetting=False,
        business_action_request='perform', business_action_quote=wire['messages'][-1]['content'],
        business_operations=operations), native=True)
    result = message(root)
    assert result['error'] == 'FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID'
    assert not result['world']['world']['attempts'] and len(wires) == 1
