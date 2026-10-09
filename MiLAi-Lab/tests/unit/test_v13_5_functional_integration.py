"""Mechanical unified-entry checks: scripted wire replies, real SDK/state/accounting.

These finite provider responses test integration, never semantic acceptance.
All ledgers and tokenizer inputs are isolated under pytest's temporary path.
"""

from __future__ import annotations

import importlib.util
import json
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_from_dict
from langgraph.store.sqlite import SqliteStore
from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast

from milai_lab.application.tools import BUSINESS_SCHEMAS
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
    inline_fragments: bool = False,
    reference_mode_declaration: bool = False,
    receipt_units: bool = False,
    failure_receipts: bool = False,
    business_feedback: bool = False,
    format_allowance: int = 1,
    current_delivery: bool = False,
    fresh_completion: bool = False,
    independent_capabilities: bool = False,
    operation_completion: bool = False,
    phase_thinking: bool = False,
    stage_enable_thinking: dict[str, bool] | None = None,
    reasoning_history: bool = False,
    direct_response: bool = False,
    actual_capabilities: bool = False,
    replacement_evidence: bool = False,
    withdrawal_evidence: bool = False,
    reviewed_evidence: bool = False,
    anchored_evidence: bool = False,
    distinct_withdrawal: bool = False,
    optional_withdrawal: bool = False,
    format_failure_receipts: bool = False,
    required_completion: bool = False,
    receipt_completion: bool = False,
    existing_confirmation: bool = False,
    support_review: bool = False,
    formation_review: bool = False,
    support_comparison: bool = False,
    catalog_feedback: bool = False,
    explicit_reads: bool = False,
    memory_continuation: bool = False,
    complete_requests: bool = False,
    scope_requests: bool = False,
    json_scope_requests: bool = False,
    declaration_thinking: str | None = None,
    declaration_tool_choice: str | None = None,
    declaration_sampling: str | None = None,
    memory_method: str = "functional_v1",
    edit_interface_version: str = "v1",
    edit_features: dict[str, bool] | None = None,
    maintenance_recipe: str | None = None,
    result_maintenance_mode: str = "legacy",
    read_exhaustion: str | None = None,
    memory_profile: str = "ordinary",
    memory_view_mode: str = "legacy",
    support_contract: str = "legacy",
    support_input: bool = False,
    bounded_reproposal: bool = False,
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
                      temperature=1.0 if direct_response else 0,
                      max_tokens=4096, max_calls=24, enable_thinking=phase_thinking,
                      tool_mode="native" if native else "json_action")
    budget_path = tmp_path / "isolated-mechanical-budget.json"
    budget = RunBudget(RunLimits(1, 1, 100, 2_000_000, 0), budget_path)
    write_json(budget_path, budget.state)
    settings = {
        "profile": "functional_v1", "host": asdict(host),
        "memory_method": memory_method,
        **({"stage_enable_thinking": stage_enable_thinking}
           if stage_enable_thinking is not None else {}),
        "memory_profile": memory_profile,
        "memory_view_mode": memory_view_mode,
        "result_maintenance_mode": result_maintenance_mode,
        "source_selection": "inline_receipt_units_v2" if receipt_units else
        "inline_fragments_v1" if inline_fragments else "index_v1",
        "failure_delivery": "receipt_status_v4" if format_failure_receipts else
        "receipt_status_v3" if fresh_completion else
        "receipt_status_v2" if current_delivery else
        "receipt_status_v1" if failure_receipts else "unavailable_v1",
        "declaration_tool_choice": declaration_tool_choice if declaration_tool_choice is not None
                                   else "required" if current_delivery else "auto",
        "completion_tool_choice": "required_until_attempt_v1" if receipt_completion else
        "required_once" if required_completion else "auto",
        "existing_confirmation": "explicit_no_change_v1" if existing_confirmation else "disabled",
        "revision_support_review": "selected_originals_v1" if support_review else "disabled",
        "formation_support_review": "selected_originals_v1" if formation_review else "disabled",
        "support_review_comparison": "explicit_dimensions_v1" if support_comparison else "disabled",
        "support_review_contract": support_contract,
        "support_input": "selected_sources_v1" if support_input else "disabled",
        "semantic_reproposal_policy": "maintenance_two_proposals_v1" if bounded_reproposal
        else "message_limit_only",
        "tool_catalog_errors": "bounded_feedback_v1" if catalog_feedback else "legacy",
        "read_interface": "explicit_selectors_v1" if explicit_reads else "combined_selectors_v1",
        "declaration_thinking": declaration_thinking if declaration_thinking is not None else
                                "disabled" if phase_thinking and not json_scope_requests
                                else "inherit",
        "declaration_sampling": declaration_sampling if declaration_sampling is not None
                                else "greedy_v1" if direct_response else "inherit",
        "capability_delivery": "actual_catalog_v1" if actual_capabilities else "legacy",
        "reasoning_history": "current_turn_native_v1" if reasoning_history else "discard",
        "recent_context": "bank_recent_v2" if operation_completion else
        "session_events_v1" if current_delivery else "disabled",
        "business_completion": "observed_continuation_v1" if business_feedback else "disabled",
        "capacity": {"model": host.model, "tokenizer_path": str(directory),
            "capacity_version": "synthetic-integration-v1",
            "context_tokens": 32768, "output_tokens": 4096, "batch_source_tokens": 8192,
            "enable_thinking": phase_thinking},
        "budget_path": str(budget_path), "max_calls_per_message": 24,
        "ordinary_material_tokens": 8192, "additional_reads": 3,
        "format_reproposals": format_allowance,
        "queue_limits": {"requests": queue_requests, "reserved_tokens": 2_000_000},
        "http_ownership_profile": "serialized_ledger_owner_v1",
        "http_ownership_domain": {"deployment_id": "mechanical-local-test",
                                   "clients": [asdict(host)]},
        "system_prompt": "Mechanical integration probe. Use issued evidence and actual receipts.",
        "request_mode": "current_request_json_v9" if json_scope_requests else
        "current_request_native_v9" if scope_requests else
        "current_request_native_v8" if complete_requests else
        "current_request_native_v7" if memory_continuation else
        "current_request_native_v6" if independent_capabilities else
        "current_request_native_v5" if reference_mode_declaration else
        "current_request_native_v4" if operation_mode_declaration else
        "current_request_native_v3" if action_mode_declaration else
        "current_request_native_v2" if write_mode_declaration else
        "current_request_native_v1" if request_interpretation else "disabled",
        "finalization": "receipt_or_agent_response_v1" if direct_response else
        "receipt_business_response_v3" if operation_completion else
        "receipt_business_response_v2" if current_delivery else
        "receipt_business_response_v1" if receipt_response else
        "readonly_response_v1" if readonly_finalization else "agent_final_v1",
        "read_exhaustion": "stop_execution_v1" if receipt_response else "legacy",
        "memory_completion": "declared_operations_v3" if operation_completion else
        "declared_writes_v2" if fresh_completion else
        "declared_writes_v1" if declared_writes else "explicit_only_v1",
        "formation_interface": "anchored_assertion_v3" if optional_withdrawal else
        "anchored_assertion_v2" if distinct_withdrawal else
        "anchored_assertion_v1" if anchored_evidence else
        "reviewed_assertion_v1" if reviewed_evidence else
        "unified_assertion_v3" if withdrawal_evidence else
        "unified_assertion_v2" if replacement_evidence else
        "unified_assertion_v1" if readonly_finalization
        else "content_and_scope_v1",
    }
    if edit_interface_version != "v1":
        settings["edit_interface_version"] = edit_interface_version
    if edit_features is not None:
        settings["edit_features"] = edit_features
    if maintenance_recipe is not None:
        settings["maintenance_recipe"] = maintenance_recipe
    if read_exhaustion is not None:
        settings["read_exhaustion"] = read_exhaustion
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


@pytest.mark.parametrize(
    "scope_requests,declaration_choice,json_scope_requests,json_declaration_disabled", [
    pytest.param(False, "required", False, False, id="False"),
    pytest.param(True, "required", False, False, id="True"),
    pytest.param(True, "auto", False, False, id="True-auto"),
    pytest.param(True, "auto", True, False, id="True-json"),
    pytest.param(True, "auto", True, True, id="True-json-disabled-T1"),
])
def test_state_view_pure_save_continues_in_current_session_and_readonly_reopens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope_requests: bool, declaration_choice: str,
    json_scope_requests: bool,
    json_declaration_disabled: bool,
) -> None:
    root = prepared(tmp_path, native=True, complete_requests=True, scope_requests=scope_requests,
        json_scope_requests=json_scope_requests,
        declaration_thinking="disabled" if json_declaration_disabled else None,
        declaration_tool_choice=declaration_choice,
        declaration_sampling="inherit" if declaration_choice == "auto" else None,
        direct_response=True, phase_thinking=True, current_delivery=True,
        memory_profile="unified_v1", memory_view_mode="state_driven",
        memory_method="milai_edit_m_v1", edit_interface_version="I2",
        maintenance_recipe="extract_then_edit", edit_features={name: True for name in (
            "matter_organization", "semantic_operations", "bound_references",
            "single_record_changes", "source_metadata", "temporal_scope")})
    original_text = "Remember that I use a teal marker for the calendar."
    continue_text = "Continue only the unfinished saving of my earlier calendar preference."
    read_text = "Only inspect the saved preference; do not save or perform business."
    correction_text = "Change my earlier calendar marker preference to green and save it."
    seen = {"extract": 0, "edit": 0, "resolve": 0}
    scope_marker = (
        "\nCurrent maintenance scope (instructions for this attempt, not fact evidence):\n"
    )
    continuation_scopes = []
    empty_current_plan = json_scope_requests and not json_declaration_disabled
    current_plans = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        names = {t["function"]["name"] for t in wire.get("tools", [])}
        json_scope = wire.get("response_format", {}).get("json_schema", {}).get(
            "name") == "milai_request_scope"
        if (json_scope or names in (
                {"classify_current_request"}, {"resolve_continuation_operations"})):
            if not json_scope:
                assert wire["tool_choice"] == declaration_choice
            assert wire["chat_template_kwargs"] == {"enable_thinking":
                json_scope_requests and not json_declaration_disabled}
            assert wire["temperature"] == (1.0 if declaration_choice == "auto" else 0.0)
            assert "[shape_feedback_v1]" not in json.dumps(wire, ensure_ascii=False)
        elif declaration_choice == "auto":
            assert wire["chat_template_kwargs"] == {"enable_thinking": True}
            assert wire["temperature"] == 1.0
        if json_scope or names == {"classify_current_request"}:
            text = wire["messages"][-1]["content"]
            if json_scope:
                assert json_scope_requests and not names
                assert "tools" not in wire and "tool_choice" not in wire
                assert "classify_current_request once" not in wire["messages"][0]["content"]
                schema = wire["response_format"]["json_schema"]["schema"]
            else:
                schema = wire["tools"][0]["function"]["parameters"]
            if text == continue_text:
                references = json.loads(wire["messages"][0]["content"].split(
                    "VISIBLE ORIGINAL REQUEST REFERENCES (not current instructions):\n", 1)[1])
                assert references["requests"][0]["kind"] == "memory_maintenance"
                assert "requirements" not in references["requests"][0]
                part = references["requests"][0]["user_fragments"][0]
                assert part["content"] == original_text and part["role"] == "user"
                assert part["source_ref"] and part["source_revision"] == 1
                assert part["observed_at"] and (part["start"], part["end"]) == (
                    0, len(original_text))
                assert not {"namespace", "bank", "owner", "fragment_handle"}.intersection(part)
            assert set(schema["required"]) == {
                "memory_requests", "allow_forgetting", "business_action_request",
                "application_continuation_request", *(
                    [] if scope_requests else ["application_requests"])}
            assert "business_operations" not in schema["properties"]
            assert ("application_requests" in schema["properties"]) is not scope_requests
            if scope_requests:
                catalog = json.loads(wire["messages"][0]["content"].split(
                    "APPLICATION OPERATIONS:\n", 1)[1].split("\n", 1)[0])
                assert catalog == [{"name": entry["function"]["name"],
                    "description": entry["function"]["description"]}
                    for entry in BUSINESS_SCHEMAS]
            decision = {
                "memory_requests": (["explicit"] if text in {original_text, correction_text}
                                    else [])
                + (["continue_prior"] if text in {continue_text, correction_text} else []),
                "allow_forgetting": False,
                "business_action_request": "perform"
                    if empty_current_plan and text == continue_text else "none",
                "application_continuation_request": "none",
                **({} if scope_requests else {"application_requests": []})}
            if json_scope:
                return {"role": "assistant", "content": json.dumps(decision)}
            return native_call("classify_current_request", "mode-" + str(ordinal), **decision)
        if names == {"resolve_continuation_operations"}:
            schema = wire["tools"][0]["function"]["parameters"]
            if set(schema["properties"]) == {"application_requests"}:
                assert empty_current_plan and wire["messages"][-1]["content"] == continue_text
                current_plans.append(continue_text)
                return native_call("resolve_continuation_operations", "current-empty",
                                   application_requests=[])
            seen["resolve"] += 1
            material = json.loads(wire["messages"][-1]["content"])["archived_reference_material"]
            assert len(material["pending_maintenance"]) == (1 if seen["resolve"] == 1 else 0)
            part = next(row for row in material["items"] if row.get("content") == original_text)
            return native_call("resolve_continuation_operations", "resolve",
                business_operations=[], prior_request_ids=[],
                prior_memory_request_fragments=[part["fragment_handle"]])
        if not names:
            if "Extract brief candidate propositions" in wire["messages"][0]["content"]:
                seen["extract"] += 1
                return {"role": "assistant", "content": json.dumps({"changes": []})}
            seen["edit"] += 1
            frame = json.loads(wire["messages"][-1]["content"])
            if "directory" in frame:
                seen["edit"] -= 1
                return {"role": "assistant", "content": json.dumps({
                    "record_ids": [frame["directory"][0]["record_id"]],
                    "done": True})}
            assert "continuation_request" not in frame
            system = wire["messages"][0]["content"]
            if scope_marker not in system:
                return {"role": "assistant", "content": "{}"}
            assert sum(row["role"] == "system" for row in wire["messages"]) == 1
            scope = json.loads(system.rsplit(scope_marker, 1)[1])
            if scope in {original_text, correction_text}:
                return {"role": "assistant", "content": "{}"}
            assert scope == continue_text
            continuation_scopes.append(scope)
            packet = frame["delivery"]
            assert continue_text not in json.dumps(packet, ensure_ascii=False)
            evidence = next(row for row in packet["evidence"] if row["text"] == original_text)
            source = next(row for row in packet["source_table"] if row["id"] == evidence["source"])
            assert source["role"] == "user"
            return {"role": "assistant", "content": json.dumps({"creates": [{
                "action": "create", "matter": "User's calendar marker", "clauses": [{
                    "text": "User uses a teal calendar marker.", "evidence": [evidence["id"]],
                    "conditions": [], "assertion": {"source": evidence["id"], "kind": "reported"},
                }]}], "records": {}})}
        return {"role": "assistant", "content": "Report the actual saved result."}

    wires = scripted(monkeypatch, reply, native=True)
    common = {"bank": "pure-save", "owner": "alice"}
    first = functional.message(root, **common, session="original", message_id="save",
                               content=original_text)
    assert first["status"] == "COMPLETED", first.get("error")
    assert first["records"] == [] and len(first["maintenance"]) == 1
    continued = functional.message(root, **common, session="current", message_id="continue",
                                   content=continue_text)
    assert continued["status"] == "COMPLETED", continued.get("error")
    assert len(continued["records"]) == 1 and seen == {"extract": 1, "edit": 2, "resolve": 1}
    assert continuation_scopes == [continue_text]
    assert continued["records"][0]["value"]["source_refs"] == [first["capture"]["source_ref"]]
    assert continued["capture"]["source_ref"] not in \
        continued["records"][0]["value"]["source_refs"]
    assert continued["request_mode"]["prior_maintenance_requests"]
    assert continued["request_mode"]["business_operations"] == []
    assert continued["request_mode"]["application_requests"] == []
    current_paths = list((root / "banks").glob("*/*-current-operations.json"))
    assert len(current_paths) == int(empty_current_plan)
    assert current_plans == ([continue_text] if empty_current_plan else [])
    assert not continued["request_mode"]["allow_business_mutation"]
    if current_paths:
        assert json.loads(current_paths[0].read_text())["decision"] == {"application_requests": []}
    assert len(continued["maintenance"]) == 1
    assert continued["operation_status"]["semantic_memory"]["status"] == "committed"
    assert continued["operation_status"]["business"]["operations"] == []
    count = len(wires)
    readonly = functional.message(root, **common, session="reopened", message_id="read",
                                  content=read_text)
    assert readonly["status"] == "COMPLETED", readonly.get("error")
    assert readonly["maintenance"] == [] and readonly["records"] == continued["records"]
    assert readonly["operation_status"]["business"]["operations"] == []
    assert seen == {"extract": 1, "edit": 2, "resolve": 1}
    assert len(wires) - count == 2  # Current declaration and normal Host answer.
    count = len(wires)
    replay = functional.message(root, **common, session="current", message_id="continue",
                                content=continue_text, resume=True)
    assert replay["records"] == continued["records"] and len(wires) == count
    corrected = functional.message(root, **common, session="correction", message_id="change",
                                   content=correction_text)
    assert corrected["status"] == "COMPLETED", corrected.get("error")
    assert corrected["request_mode"]["resumed_memory_request"]["fragment_handles"]
    assert corrected["request_mode"]["prior_maintenance_requests"] == []
    assert corrected["request_mode"]["current_memory_write_request"] == "explicit"
    assert corrected["request_mode"]["memory_requests"] == ["explicit", "continue_prior"]
    assert seen == {"extract": 2, "edit": 3, "resolve": 2}
    if json_scope_requests:
        scope_events = [event for path in (root / "banks").glob("*/*-trace-*.jsonl")
                        for line in path.read_text().splitlines()
                        if (event := json.loads(line)).get("event") == "vllm_response"
                        and event["request"].get("response_format", {}).get("json_schema", {}).get(
                            "name") == "milai_request_scope"]
        assert len(scope_events) == 4
        assert all(event["capacity"]["identity"]["enable_thinking"]
                   is (not json_declaration_disabled) for event in scope_events)


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


@pytest.mark.parametrize("arm,memory_profile,memory_view_mode", [
    ("B0", "ordinary", "legacy"), ("B1", "ordinary", "legacy"),
    ("B2", "ordinary", "legacy"), ("M", "ordinary", "legacy"),
    ("M", "unified_v1", "legacy"), ("M", "unified_v1", "state_driven"),
])
def test_next_edit_contract_reaches_normal_host_wire_and_statement_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str, memory_profile: str,
    memory_view_mode: str,
) -> None:
    root = prepared(
        tmp_path, native=True, request_interpretation=True,
        memory_profile=memory_profile,
        memory_view_mode=memory_view_mode,
        memory_method="milai_edit_" + arm.lower() + "_v1", edit_interface_version="I2",
        edit_features={name: True for name in (
            "matter_organization", "semantic_operations", "bound_references",
            "single_record_changes", "source_metadata",
        )},
    )

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return intent_reply(memory=True, business=False)
        if ordinal == 2:
            packet = materials(wire)["writer_packet"]
            evidence = packet["evidence"][0]["id"]
            schemas = {t["function"]["name"]: t["function"]["parameters"] for t in wire["tools"]}
            assert "update_memory" not in schemas
            proposal_schema = schemas["save_memory"]["properties"]["proposal"]
            clause_schema = proposal_schema["properties"]["clauses"]["items"]
            variants = clause_schema["oneOf"] if arm in {"B2", "M"} else [clause_schema]
            for variant in variants:
                assert variant["properties"]["evidence"]["items"]["enum"] == [
                    e["id"] for e in packet["evidence"]
                ]
            assert "matter" in schemas["save_memory"]["properties"]["proposal"]["required"]
            source = next(s for s in packet["source_table"]
                          if s["id"] == packet["evidence"][0]["source"])
            assert source["role"] == "user" and source["occurred_at"] == "2030-02-04T09:00:00Z"
            return native_call("save_memory", "next-save", proposal={
                "action": "create", "matter": "User's local marker",
                "clauses": [{"text": "User reports the local marker is blue.",
                             "evidence": [evidence],
                             "assertion": {"source_evidence": evidence, "kind": "reported"},
                             **({"conditions": []} if arm in {"B2", "M"} else {})}],
            })
        assert ordinal == 3
        assert actual_tool_receipt(wire)["status"] == "committed"
        if memory_view_mode != "legacy":
            assert any(ref["kind"] == "record" and ref["revision"] == 1
                       for ref in materials(wire)["memory_view"]["resident_refs"])
        return {"role": "assistant", "content": "Saved your reported marker."}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root, occurred_at="2030-02-04T09:00:00Z")
    assert result["status"] == "COMPLETED", result.get("error")
    assert len(wires) == 3
    state = next(r["value"]["edit_state"] for r in result["records"]
                 if r["value"].get("method_arm") == arm)
    assert state["matter_description"] == "User's local marker"
    assert state["units"][0]["assertion"]["role"] == "user"
    assert state["units"][0]["assertion"]["occurred_at"] == "2030-02-04T09:00:00Z"
    assert message(root, occurred_at="2030-02-04T09:00:00Z") == result
    assert len(wires) == 3


def intent_reply(*, memory: bool = False, required: bool = False, forgetting: bool = False,
                 business: bool = False) -> dict[str, Any]:
    return native_call("classify_current_request", "interpret",
        allow_memory_maintenance=memory, allow_forgetting=forgetting,
        allow_business_mutation=business, requires_memory_result=required)


def test_normal_host_keeps_statement_calendar_separate_from_reader_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(
        tmp_path, native=True, request_interpretation=True,
        memory_method="milai_edit_m_v1", edit_interface_version="I2",
        maintenance_recipe="single_pass", edit_features={name: True for name in (
            "matter_organization", "semantic_operations", "bound_references",
            "single_record_changes", "source_metadata", "temporal_scope",
        )},
    )
    text = "The marker is blue from February 4 inclusive to February 6 exclusive."

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return intent_reply(memory=True)
        if ordinal == 2:
            packet = json.loads(wire["messages"][-1]["content"])["delivery"]
            source = packet["source_table"][0]
            assert source["occurred_at"] == "Feb 04, 2030, 09:00:00"
            assert source["calendar_context"] == "marker-calendar"
            return {"role": "assistant", "content": json.dumps({"creates": [{
                "action": "create", "matter": "Marker color",
                "clauses": [{"text": text, "evidence": ["e1"], "conditions": [],
                             "assertion": {"source": "e1", "kind": "reported",
                                 "applicability": {"effective_from": "2030-02-04",
                                                   "effective_until": "2030-02-06"}}}],
            }], "records": {}})}
        assert ordinal == 3
        items = materials(wire)["items"]
        view = next(row["revision_view"] for row in items if row.get("revision_view"))
        assert view["query_time"] == "Feb 05, 2030, 10:00:00"
        assert view["query_calendar_context"] == "marker-calendar"
        assert view["time_values"]["query_time"]["timezone_known"] is False
        assert view["units"][0]["temporal"]["status"] == "within_explicit_limits"
        return {"role": "assistant", "content": "Saved the stated period."}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank="calendar-bank", owner="alice", session="session", message_id="dated",
                content=text, occurred_at="Feb 04, 2030, 09:00:00",
                calendar_context="marker-calendar", query_time="Feb 05, 2030, 10:00:00",
                query_calendar_context="marker-calendar")
    result = functional.message(root, **args)
    assert result["status"] == "COMPLETED", result.get("error")
    assert len(wires) == 3
    unit = result["records"][0]["value"]["edit_state"]["units"][0]
    assert unit["assertion"]["occurred_at"] == args["occurred_at"]
    assert unit["assertion"]["calendar_context"] == args["calendar_context"]
    assert functional.message(root, **args) == result
    assert len(wires) == 3


@pytest.mark.parametrize("lost_memory_response", [False, True])
def test_unified_public_resume_discovers_effects_obeys_readonly_and_saves_actual_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_memory_response: bool,
) -> None:
    from milai_lab.application.functional import FunctionalApplication
    from milai_lab.application.recovery import UnknownSemanticCommit
    from milai_lab.runners import memory_operations

    root = prepared(
        tmp_path, native=True, request_interpretation=True, memory_profile="unified_v1",
        memory_method="milai_edit_m_v1", edit_interface_version="I2",
        maintenance_recipe="single_pass", edit_features={name: True for name in (
            "matter_organization", "semantic_operations", "bound_references",
            "single_record_changes", "source_metadata", "temporal_scope",
        )},
    )
    arguments = {"item_key": "paper pack", "quantity": 1,
                 "destination": "local", "packing": "box"}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return intent_reply(business=True)
        if ordinal == 2:
            return native_call("reserve_and_label", "reserve", **arguments)
        if ordinal == 3:
            assert actual_tool_receipt(wire)["business_outcome"] == "partial"
            return {"role": "assistant", "content": "Reserved; the label is still unavailable."}
        assert not wire.get("tools")
        packet = json.loads(wire["messages"][-1]["content"])["delivery"]
        if ordinal == 4:
            tool_source = [source["id"] for source in packet["source_table"]
                           if source["role"] == "tool"][-1]
            evidence = next(row["id"] for row in packet["evidence"]
                            if row["source"] == tool_source)
            assert "created" in json.dumps(packet)
            clause = {"text": "The paper pack is reserved and its label was created.",
                      "evidence": [evidence], "conditions": [],
                      "assertion": {"source": evidence, "kind": "observed"}}
            envelope = {"creates": [{"action": "create", "matter": "Paper pack outcome",
                                     "clauses": [clause]}], "records": {}}
        else:
            assert ordinal == 5
            envelope = {"creates": [], "records": {}}
        return {"role": "assistant", "content": json.dumps(envelope)}

    wires = scripted(monkeypatch, reply, native=True)
    monkeypatch.setattr(memory_operations, "FunctionalVLLMClient", functional.FunctionalVLLMClient)
    first = message(root, initial_world={"initial_label_available": False})
    assert first["status"] == "COMPLETED", first.get("error")
    assert len(first["world"]["world"]["attempts"]) == 1
    requirements = {
        "target": {"item_key": arguments["item_key"]},
        "steps": [
            {"id": "reserve", "operation": "reserve_and_label", "arguments": arguments,
             "completed": arguments},
            {"id": "label", "operation": "complete_label", "arguments": {},
             "arguments_from_state": {"reservation_id": "reservation_id"},
             "completed": {"label_status": "created"}},
        ], "save_result": True, "feedback": True,
    }
    common = {"bank": "mechanical-bank", "owner": "alice", "session": "session",
              "operation": "resume", "resume_request_id": "original-request"}
    readonly = memory_operations.run(
        root, **common, request_id="check-only", text="Only inspect the pending result.",
        requirements=requirements, readonly=True,
    )
    assert readonly["business"]["status"] == "partial"
    assert readonly["business"]["execution"]["status"] == "observed_only"
    assert not readonly["business"]["execution"]["can_execute"]
    assert readonly["memory"]["current_permission"] == "not_authorized_current_request"
    assert len(readonly["application_snapshot"]["attempts"]) == 1 and len(wires) == 3
    freeze = functional.frozen(root)
    bank_root = root / "banks" / functional._bank_reference(
        root, freeze["run_id"], "mechanical-bank", "alice"
    )
    with FunctionalApplication.open(bank_root / "applications" / "reservation",
                                    "reservation", "alice") as app:
        app.world.set_label_available("restore-label-service", True)
    maintain_delivery = functional.FunctionalEditMemory.maintain_delivery
    interrupted = []

    def lose_committed_reply(memory: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        outcome = maintain_delivery(memory, *args, **kwargs)
        if (lost_memory_response and not interrupted and kwargs.get("execute", True)
                and kwargs["request_id"].startswith("original-request:memory:")):
            interrupted.append(outcome)
            raise UnknownSemanticCommit("Actual semantic commit completed; callback reply lost")
        return outcome

    monkeypatch.setattr(functional.FunctionalEditMemory, "maintain_delivery", lose_committed_reply)
    completed = memory_operations.run(
        root, **common, request_id="finish", text="Finish the label and save the actual outcome.",
        allowed_operations=["complete_label"],
    )
    if lost_memory_response:
        assert not completed["complete"] and completed["memory"]["status"] == "semantic_unknown"
        original_attempt = completed["memory"]["attempts"][0]
        assert original_attempt["binding"]["session"] == "session"
        assert original_attempt["binding"]["turn_id"] == "finish"
        assert interrupted[0]["semantic_write_performed"]
        completed = memory_operations.run(
            root, **{**common, "session": "later-session"}, request_id="reconcile-only",
            text="Only inspect the earlier committed save; no save or business actions.",
            readonly=True, allow_memory=False,
        )
        assert completed["memory"]["attempts"] == [original_attempt]
        assert completed["memory"]["reconciliation"]["status"] == "committed"
    assert completed["complete"], completed
    assert completed["memory"]["status"] == "committed"
    assert completed["feedback"]["attempts"][-1]["receipt"]["host_seen"] is False
    assert len(completed["application_snapshot"]["attempts"]) == 2 and len(wires) == 4
    repeated = memory_operations.run(
        root, **common, request_id="finish", text="Finish the label and save the actual outcome.",
        allowed_operations=["complete_label"],
    )
    assert repeated["complete"] and repeated["repeated_command_observation_only"]
    assert len(repeated["application_snapshot"]["attempts"]) == 2 and len(wires) == 4
    exported = functional.memory_data(root, bank="mechanical-bank", owner="alice",
                                      operation="export")
    episode_ids = [row["episode_id"] for row in exported["episodes"]]
    consolidation_outcomes = []

    def lose_consolidation_reply(memory: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        outcome = maintain_delivery(memory, *args, **kwargs)
        if (not consolidation_outcomes and kwargs.get("execute", True)
                and kwargs["request_id"] == "organize"):
            consolidation_outcomes.append(outcome)
            raise RuntimeError("Maintenance completed before consolidation result was saved")
        return outcome

    monkeypatch.setattr(
        functional.FunctionalEditMemory, "maintain_delivery", lose_consolidation_reply,
    )
    organize = {
        "bank": "mechanical-bank", "owner": "alice", "session": "session",
        "request_id": "organize", "text": "Organize the selected visible history.",
        "episode_ids": episode_ids,
    }
    with pytest.raises(RuntimeError, match="before consolidation result was saved"):
        memory_operations.run(root, **organize)
    assert consolidation_outcomes[0]["status"] == "completed" and len(wires) == 5
    after_interruption = functional.memory_data(
        root, bank="mechanical-bank", owner="alice", operation="export",
    )
    consolidated = memory_operations.run(root, **organize)
    assert consolidated["status"] == "completed", consolidated
    assert consolidated["replayed"]
    assert consolidated["business_operations_executed"] == 0 and len(wires) == 5
    after = functional.memory_data(root, bank="mechanical-bank", owner="alice", operation="export")
    assert len(after["records"]) == 1
    assert after["records"] == after_interruption["records"]
    assert {source["event_id"] for source in after["sources"]} == {
        source["event_id"] for source in after_interruption["sources"]
    }
    assert {source["event_id"] for source in exported["sources"]} < {
        source["event_id"] for source in after["sources"]
    }


def native_call(name: str, call_id: str, **args: Any) -> dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": [{
        "type": "function", "id": call_id, "function": {
            "name": name, "arguments": json.dumps(args)}}]}


@pytest.mark.parametrize("label_available", [True, False])
@pytest.mark.parametrize("edit_interface_version", ["v1", "I2"])
@pytest.mark.parametrize("arm,method,representation", [
    ("M", "milai_edit_m_v1", "conditioned_v1"),
    ("B1", "milai_edit_b1_v1", "plain_v1"),
    ("B0", "milai_edit_b0_v1", "plain_v1"),
    ("B2", "milai_edit_b2_v1", "conditioned_v1"),
])
def test_edit_uses_actual_business_delivery_on_the_normal_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label_available: bool,
    arm: str, method: str, representation: str, edit_interface_version: str,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True,
                    memory_method=method, edit_interface_version=edit_interface_version)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return intent_reply(memory=True, business=True)
        if ordinal == 2:
            schema = next(t["function"]["parameters"] for t in wire["tools"]
                          if t["function"]["name"] == "save_memory")
            field = "proposal" if edit_interface_version == "I2" else "units"
            assert field in schema["properties"]
            return native_call("reserve_and_label", "reserve", item_key="edit receipt item",
                               quantity=1, destination="local", packing="box")
        if ordinal == 3:
            observed = actual_tool_receipt(wire)
            assert observed["business_outcome"] == ("confirmed" if label_available else "partial")
            handles = [r["fragment_handle"] for r in observed["source_fragment_index"]]
            claim = ("The item is reserved and labeled." if label_available
                     else "The item is reserved; labeling failed.")
            if edit_interface_version == "I2":
                packet = materials(wire)["writer_packet"]
                tool_sources = {s["id"] for s in packet["source_table"] if s["role"] == "tool"}
                aliases = [e["id"] for e in packet["evidence"] if e["source"] in tool_sources]
                assert aliases
                return native_call("save_memory", "save", proposal={"action": "create", "units": [
                    {"text": claim, "role": "content", "evidence": aliases}]})
            return native_call("save_memory", "save", units=[
                {"text": claim, "role": "content", "evidence": handles}])
        assert ordinal == 4
        assert actual_tool_receipt(wire)["status"] == "committed"
        return {"role": "assistant", "content": "Saved the actual business result."}

    wires = scripted(monkeypatch, reply, native=True)
    kwargs = {"initial_world": {"label_available": label_available}}
    result = message(root, **kwargs)
    assert result["status"] == "COMPLETED", result
    assert len(wires) == 4 and len(result["world"]["world"]["attempts"]) == 1
    semantic = [r for r in result["records"] if r["value"].get("method_arm") == arm]
    assert len(semantic) == 1
    value = semantic[0]["value"]
    assert value["basis"] == "tool_observation"
    assert value["edit_state"]["representation"] == representation
    assert all(ref["source_ref"] in value["source_refs"]
               for unit in value["edit_state"]["units"] for ref in unit["evidence_refs"])
    assert message(root, **kwargs) == result and len(wires) == 4


@pytest.mark.parametrize("boundary,happened", [
    ("after_journal_intent_before_native", False),
    ("after_native_before_journal_complete", True),
])
@pytest.mark.parametrize("arm,method", [
    ("M", "milai_edit_m_v1"), ("B1", "milai_edit_b1_v1"),
    ("B0", "milai_edit_b0_v1"), ("B2", "milai_edit_b2_v1"),
])
def test_edit_recovery_supports_only_the_actual_discovery_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str, happened: bool,
    arm: str, method: str,
) -> None:
    root = prepared(tmp_path, memory_method=method)
    control = {"one_shot_fault": {"message_index": 0, "boundary": boundary,
                                  "target_operation": "reserve_and_label", "occurrence": 1}}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return tool("reserve_and_label", item_key="edit recovery item", quantity=1,
                        destination="local", packing="box")
        if ordinal == 2:
            receipt = actual_tool_receipt(wire)
            assert receipt["status"] == "ORIGINAL_CALL_OUTCOME_UNKNOWN"
            assert receipt["original_receipt"] is None
            assert receipt["observed_effect"] == ("confirmed" if happened else "none")
            query = receipt["query_source"]
            return tool("save_memory", units=[{
                "text": ("The item is reserved and labeled." if happened
                         else "Lookup found no reservation for the item."),
                "role": "content",
                "evidence": [r["fragment_handle"] for r in query["source_fragment_index"]],
            }])
        assert ordinal == 3 and actual_tool_receipt(wire)["status"] == "committed"
        return {"answer": "Saved the observed state."}

    wires = scripted(monkeypatch, reply)
    first = message(root, evaluator_control=control)
    assert first["status"] == "UNKNOWN", first
    final = message(root, evaluator_control=control, resume=True)
    assert final["status"] == "COMPLETED", final
    assert len(wires) == 3
    assert len(final["world"]["world"]["attempts"]) == int(happened)
    value = next(r["value"] for r in final["records"] if r["value"].get("method_arm") == arm)
    discoveries = {s["event_id"] for s in final["sources"] if s["origin"] == "get_reservation"}
    assert set(value["source_refs"]) == discoveries
    pending = [r for r in final["world"]["journal"].values()
               if r.get("name") == "reserve_and_label"]
    assert len(pending) == 1 and pending[0]["status"] == "pending"
    assert "result" not in pending[0]


@pytest.mark.parametrize("arm,method", [
    ("M", "milai_edit_m_v1"), ("B1", "milai_edit_b1_v1"),
])
def test_edit_normal_host_replaces_on_same_id_and_preserves_other_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str, method: str,
) -> None:
    root = prepared(tmp_path, native=True, memory_method=method)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 3}:
            packet = materials(wire)
            current = [u["fragment_handle"] for u in packet["items"]
                       if u["type"] == "fragment" and u["input_relation"] == "current_request"]
            if ordinal == 1:
                return native_call("save_memory", "save", units=[
                    {"text": "Use unit A.", "role": "content", "evidence": current},
                    {"text": "Retain the weekly review.", "role": "content", "evidence": current},
                ], scope={"project": "local sample"})
            target = next(u for u in packet["items"]
                          if u["type"] == "record" and u["content"] == "Use unit A.")
            assert target["method_arm"] == arm
            return native_call("update_memory", "replace", read_handle=target["read_handle"],
                               edits=[{"operation": "replace",
                                       "target_unit": target["edit_unit"]["unit_id"],
                                       "text": "Use unit B.", "evidence": current}])
        assert ordinal in {2, 4} and actual_tool_receipt(wire)["status"] == "committed"
        return {"role": "assistant", "content": "The requested memory change is saved."}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank="b", owner="alice", session="s")
    saved = functional.message(root, **common, message_id="initial",
        content="Remember: for the local sample use unit A and retain the weekly review.")
    args = dict(message_id="replacement",
                content="For that same local sample use unit B instead; keep the weekly review.")
    updated = functional.message(root, **common, **args)
    assert saved["status"] == updated["status"] == "COMPLETED", updated
    assert len(wires) == 4 and len(updated["records"]) == 1
    original = saved["records"][0]
    current = updated["records"][0]
    assert current["id"] == original["id"]
    assert current["value"]["revision"] == 2
    assert current["value"]["scope"] == original["value"]["scope"]
    old_units = original["value"]["edit_state"]["units"]
    units = current["value"]["edit_state"]["units"]
    assert units[0]["unit_id"] == old_units[0]["unit_id"]
    assert units[0]["text"] == "Use unit B." and units[1:] == old_units[1:]
    assert {ref["source_ref"] for ref in units[0]["evidence_refs"]} == {
        updated["capture"]["source_ref"]}
    assert functional.message(root, **common, **args) == updated and len(wires) == 4


@pytest.mark.parametrize("arm,method", [
    ("B0", "milai_edit_b0_v1"), ("B2", "milai_edit_b2_v1"),
])
def test_rewrite_normal_host_replaces_complete_state_then_confirms_without_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str, method: str,
) -> None:
    root = prepared(tmp_path, native=True, memory_method=method)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 3, 5}:
            packet = materials(wire)
            handles = [u["fragment_handle"] for u in packet["items"]
                       if u["type"] == "fragment" and u["input_relation"] == "current_request"]
            version = "A" if ordinal == 1 else "B"
            units = [
                {"text": f"Use unit {version}." if arm == "B2" else
                         f"Use unit {version} only on weekdays.",
                 "role": "content", "evidence": handles},
                {"text": "Retain the weekly review.", "role": "content", "evidence": handles},
            ]
            relations: list[dict[str, Any]] = []
            if arm == "B2":
                units.append({"text": "Only on weekdays.", "role": "condition",
                              "evidence": handles})
                relations.append({"source": 2, "relation_type": "modifies", "target": 0,
                                  "evidence": handles})
            if ordinal == 1:
                return native_call("save_memory", "save", units=units, relations=relations,
                                   scope={"project": "local rewrite sample"})
            target = next(u for u in packet["items"]
                          if u["type"] == "record" and u["content"].startswith("Use unit"))
            assert target["method_arm"] == arm
            schema = next(t["function"]["parameters"] for t in wire["tools"]
                          if t["function"]["name"] == "update_memory")
            assert "units" in schema["properties"] and "edits" not in schema["properties"]
            if ordinal == 5:
                return native_call("update_memory", "confirm", read_handle=target["read_handle"])
            return native_call("update_memory", "rewrite", read_handle=target["read_handle"],
                               units=units, relations=relations)
        assert ordinal in {2, 4, 6}
        assert actual_tool_receipt(wire)["status"] == (
            "no_change" if ordinal == 6 else "committed")
        return {"role": "assistant", "content": "The actual memory operation is confirmed."}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank="b", owner="alice", session="s")
    saved = functional.message(root, **common, message_id="initial",
        content="Remember: for the local rewrite sample use unit A only on weekdays; "
                "retain the weekly review.")
    updated = functional.message(root, **common, message_id="rewrite",
        content="For that same local rewrite sample use unit B only on weekdays instead; "
                "retain the weekly review.")
    unchanged = functional.message(root, **common, message_id="confirm",
        content="Confirm that the existing arrangement remains unchanged.")
    assert saved["status"] == updated["status"] == unchanged["status"] == "COMPLETED"
    assert len(wires) == 6 and len(unchanged["records"]) == 1
    old = saved["records"][0]
    current = updated["records"][0]
    assert current["id"] == old["id"]
    assert unchanged["records"] == updated["records"]
    value = current["value"]
    assert value["revision"] == 2 and value["scope"] == old["value"]["scope"]
    state = value["edit_state"]
    assert state["representation"] == ("conditioned_v1" if arm == "B2" else "plain_v1")
    assert len(state["units"]) == (3 if arm == "B2" else 2)
    assert len(state["relations"]) == int(arm == "B2")
    assert state["units"][1]["text"] == old["value"]["edit_state"]["units"][1]["text"]
    assert {u["unit_id"] for u in state["units"]}.isdisjoint(
        u["unit_id"] for u in old["value"]["edit_state"]["units"])
    assert {ref["source_ref"] for u in state["units"] for ref in u["evidence_refs"]} == {
        updated["capture"]["source_ref"]}
    if arm == "B2":
        relation = state["relations"][0]
        assert relation["source_unit"] == state["units"][2]["unit_id"]
        assert relation["target_unit"] == state["units"][0]["unit_id"]


@pytest.mark.parametrize("method", [
    "milai_edit_m_v1", "milai_edit_b1_v1", "milai_edit_b0_v1", "milai_edit_b2_v1",
])
@pytest.mark.parametrize("business", [False, True])
def test_current_host_outputs_reach_existing_offline_evaluator_without_digest_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, business: bool,
) -> None:
    root = prepared(tmp_path, native=True, memory_method=method,
                    direct_response=True, phase_thinking=True, current_delivery=True)
    content = ("Reserve the local box and save the actual result." if business else
               "Remember: the local marker is blue.")
    freeze = read_json(root / "input-freeze.json")
    freeze["fixture"] = {"cases": [{"case_id": "b", "owner": "alice",
        "messages": [{"session_id": "s", "message_id": "save", "content": content}]}]}
    freeze["fixture_version"] = "mechanical-evaluator-integration-v1"
    write_json(root / "input-freeze.json", freeze)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if business and ordinal == 1:
            return native_call("reserve_and_label", "reserve", item_key="evaluator box",
                               quantity=1, destination="local", packing="box")
        if ordinal == (2 if business else 1):
            handles = ([r["fragment_handle"]
                        for r in actual_tool_receipt(wire)["source_fragment_index"]] if business
                       else [u["fragment_handle"] for u in materials(wire)["items"]
                             if u["type"] == "fragment"])
            return native_call("save_memory", "save", units=[{
                "text": "The box is reserved and labeled." if business else "The marker is blue.",
                "role": "content", "evidence": handles}])
        assert ordinal == (3 if business else 2)
        assert actual_tool_receipt(wire)["status"] == "committed"
        return {"role": "assistant", "content": "The actual result is saved."}

    wires = scripted(monkeypatch, reply, native=True)
    executed = functional.step(root, "b", 0)
    assert executed["status"] == "COMPLETED", executed
    assert executed["finalization"]["protocol"] == (
        "receipt_business_response_v1" if business else "agent_response_v1")
    specification = importlib.util.spec_from_file_location(
        "current_functional_evaluator", Path(__file__).parents[2] / "tools/v13_5_evaluate.py")
    assert specification is not None and specification.loader is not None
    evaluator = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(evaluator)
    result = evaluator.evaluate(root, cohort="L2")
    pack = result["case_packs"][0]
    assert pack["execution_status"] == "COMPLETED" and pack["acceptance_evidence_complete"]
    assert pack["semantic_verdict"] == "UNREVIEWED"
    attempt = pack["messages"][0]["attempts"][0]
    assert attempt["actual_http_linkage"]["status"] == "PASS"
    assert attempt["quote_check"]["status"] == "PASS"
    assert result["attempt_ledger_delta_sum"]["generation.known_tokens"] == 12 * len(wires)
    assert "sha256" not in json.dumps(result)


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


def test_complete_request_mode_reuses_saved_legacy_decision_without_reclassification(
    tmp_path: Path,
) -> None:
    class UnusedModel:
        def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
            pytest.fail("A saved current-request decision must not invoke the model.")

    path = tmp_path / "request-mode.json"
    binding = {"source_ref": "original-source", "session": "original", "turn_id": "save"}
    decision = {"memory_write_request": "none", "memory_continuation_request":
        "resolve_prior_explicit", "allow_forgetting": False, "business_action_request": "none",
        "business_operations": [], "application_requests": [],
        "application_continuation_request": "resolve_prior_request"}
    write_json(path, {"binding": binding, "attempts": 1, "decision": decision})
    before = path.read_bytes()
    result = functional.request_mode(
        cast(functional.LangMemRecipeChatModel, UnusedModel()), path, binding,
        "Only finish saving the earlier actual result.", 1, lambda event: None,
        native_declaration=True, write_mode_declaration=True, action_mode_declaration=True,
        operation_mode_declaration=True, reference_mode_declaration=True,
        independent_capabilities=True, memory_continuation=True,
        application_workflow="reservation_v1",
        referenced_requests=[{"request_id": "new-reference-not-used-for-cached-decision"}])
    assert path.read_bytes() == before
    assert result["protocol"] == "native_complete_requests_v8"
    assert result["memory_write_request"] == "none"
    assert result["memory_continuation_request"] == "resolve_prior_explicit"
    assert result["application_continuation_request"] == "resolve_prior_request"
    assert not result["allow_memory_maintenance"] and not result["requires_memory_result"]
    assert "memory_requests" not in result
    scoped_cache = functional.request_mode(
        cast(functional.LangMemRecipeChatModel, UnusedModel()), path, binding,
        "Only finish saving the earlier actual result.", 1, lambda event: None,
        native_declaration=True, write_mode_declaration=True, action_mode_declaration=True,
        operation_mode_declaration=True, reference_mode_declaration=True,
        independent_capabilities=True, memory_continuation=True,
        application_workflow="reservation_v1", scope_only=True)
    assert scoped_cache == result and path.read_bytes() == before

    current = "Reserve and label the teal and blue packs; do not save anything."
    current_decision = {"memory_requests": [], "allow_forgetting": False,
        "business_action_request": "perform", "application_continuation_request": "none",
        "application_requests": [{"target": {"item_key": color + " pack"}, "actions": [{
            "operation": "reserve_and_label", "arguments": {
                "quantity": 1, "destination": "local", "packing": "box"}}]}
            for color in ("teal", "blue")]}
    calls = []

    class DeclaredModel:
        def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:
            from jsonschema import validate

            calls.append(messages)
            schema = kwargs["tools"][0]["function"]["parameters"]
            assert "business_operations" not in schema["properties"]
            assert "business_operations" not in schema["required"]
            validate(current_decision, schema)
            return AIMessage(content="", tool_calls=[{
                "name": "classify_current_request", "id": "current-mode",
                "args": current_decision}])

    arguments = {"native_declaration": True, "write_mode_declaration": True,
        "action_mode_declaration": True, "operation_mode_declaration": True,
        "reference_mode_declaration": True, "independent_capabilities": True,
        "memory_continuation": True, "application_workflow": "reservation_v1"}
    current_path = tmp_path / "current-mode.json"
    actual = functional.request_mode(
        cast(functional.LangMemRecipeChatModel, DeclaredModel()), current_path, binding,
        current, 1, lambda event: None, **arguments)
    assert actual["business_operations"] == ["reserve_and_label"]
    assert actual["allow_business_mutation"] and not actual["allow_memory_maintenance"]
    assert actual["application_requests"] == current_decision["application_requests"]
    plans = functional.compile_application_requests(
        "reservation_v1", actual["application_requests"], save_result=False)
    assert all([step["operation"] for step in plan["steps"]]
               == ["reserve_and_label", "complete_label"] for plan in plans)
    assert "business_operations" not in current_decision
    saved = read_json(current_path)
    assert saved["decision"] == {**current_decision, "business_operations": ["reserve_and_label"]}
    before = current_path.read_bytes()
    replay = functional.request_mode(
        cast(functional.LangMemRecipeChatModel, UnusedModel()), current_path, binding,
        current, 1, lambda event: None, **arguments)
    assert replay == actual and current_path.read_bytes() == before and len(calls) == 1
    scoped_cache = functional.request_mode(
        cast(functional.LangMemRecipeChatModel, UnusedModel()), current_path, binding,
        current, 1, lambda event: None, scope_only=True, **arguments)
    assert scoped_cache == actual and current_path.read_bytes() == before and len(calls) == 1

    conflicting = {**current_decision, "business_operations": ["create_or_update_draft"]}

    class ConflictingModel:
        def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
            return AIMessage(content="", tool_calls=[{
                "name": "classify_current_request", "id": "old-conflict",
                "args": conflicting}])

    conflict_path = tmp_path / "conflict-mode.json"
    with pytest.raises(functional.IncompleteChatResponse,
                       match="FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID"):
        functional.request_mode(
            cast(functional.LangMemRecipeChatModel, ConflictingModel()), conflict_path, binding,
            current, 1, lambda event: None, **arguments)
    assert read_json(conflict_path) == {"binding": binding, "attempts": 1}
    write_json(conflict_path, {"binding": binding, "attempts": 1, "decision": conflicting})
    before = conflict_path.read_bytes()
    with pytest.raises(ValueError, match="FUNCTIONAL_REQUEST_MODE_DECISION_CHANGED"):
        functional.request_mode(
            cast(functional.LangMemRecipeChatModel, UnusedModel()), conflict_path, binding,
            current, 1, lambda event: None, **arguments)
    assert conflict_path.read_bytes() == before
    write_json(conflict_path, {"binding": binding, "attempts": 1, "decision": current_decision})
    before = conflict_path.read_bytes()
    with pytest.raises(ValueError, match="FUNCTIONAL_REQUEST_MODE_DECISION_CHANGED"):
        functional.request_mode(
            cast(functional.LangMemRecipeChatModel, UnusedModel()), conflict_path, binding,
            current, 1, lambda event: None, **arguments)
    assert conflict_path.read_bytes() == before  # Only a new response may derive operations.


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
    archived_path = next(path for path in root.glob("banks/*/*-result.json")
                         if read_json(path).get("message_id") == "old")
    archived = read_json(archived_path)
    forgotten = functional.message(root, **common, message_id="forget",
                                   content="Forget my previous input.")
    assert forgotten["status"] == "COMPLETED", forgotten
    replay = functional.message(root, **common, **old, resume=True)
    # The actual bound input is now rejected before capture or mode admission.
    assert replay["status"] == "VISIBILITY_REVOKED", replay
    assert replay["original_status"] == failed["status"]
    assert failed["capture"]["source_ref"] in replay["revoked_source_refs"]
    assert replay.get("final_answer") is None and len(wires) == 5
    assert "MECHANICAL_MODE_SECRET" not in json.dumps(replay)
    assert replay["historical_artifact_retained"] and read_json(archived_path) == archived


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


@pytest.mark.parametrize("workflow,document_body", [("reservation", "local body"),
                        ("document", "local body"), ("document", "界" * 600)])
@pytest.mark.parametrize('inline_fragments,receipt_units', [(False, False), (True, False),
                                                          (True, True)])
def test_unified_business_receipt_exposes_real_handles_for_immediate_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workflow: str,
    inline_fragments: bool,
    receipt_units: bool,
    document_body: str,
) -> None:
    root = prepared(tmp_path, inline_fragments=inline_fragments, receipt_units=receipt_units)

    def evidence(result: dict[str, Any]) -> list[str]:
        fragments = result['source_fragment_index']
        assert all(('content' in row) == inline_fragments for row in fragments)
        if inline_fragments:
            body = ''.join(row['content'] for row in fragments)
            assert json.loads(body) == result['receipt']
            assert all(row['content'] == body[row['start']:row['end']] for row in fragments)
            assert all(row['role'] == 'tool' and row['semantic_support'] == 'unchecked'
                       for row in fragments)
            assert 'not what actually happened' in result['memory_evidence_selection']
            if receipt_units and len(body) <= 4096:
                assert len(fragments) == 1
                assert fragments[0]['start'] == 0 and fragments[0]['end'] == len(body)
            elif receipt_units:
                assert len(fragments) > 1
                assert all(len(row['content']) <= 1200 for row in fragments)
        return [row['fragment_handle'] for row in fragments]

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if workflow == "document":
            if ordinal == 1:
                return tool("create_or_update_draft", title="mechanical draft",
                            content=document_body, document_version=0)
            if ordinal in {2, 3}:
                observed = actual_tool_receipt(wire)["receipt"]
                bound = {k: observed[k] for k in ("title", "document_version")}
                if ordinal == 2:
                    return tool("approve_document_version", **bound)
                return tool("publish_approved_document", **bound, audience="local audience")
            if ordinal == 4:
                result = actual_tool_receipt(wire)
                assert result["receipt"]["publication_status"] == "published"
                return tool("save_memory", content="The draft was approved and published locally.",
                            fragment_handles=evidence(result))
            assert actual_tool_receipt(wire)["status"] == "committed"
            return {"answer": "The actual local publication is recorded."}
        if ordinal == 1:
            return tool("reserve_and_label", item_key="mechanical item", quantity=1,
                        destination="local", packing="box")
        if ordinal == 2:
            result = actual_tool_receipt(wire)
            assert result["receipt"]["label_status"] == "created"
            return tool("save_memory", content="The mechanical item was reserved and labeled.",
                        fragment_handles=evidence(result))
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


@pytest.mark.parametrize('independent', [False, True])
def test_continuation_resolves_only_missing_reference_from_bounded_material_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, independent: bool,
) -> None:
    root = prepared(tmp_path, native=True, reference_mode_declaration=True, receipt_response=True,
                    independent_capabilities=independent)
    current = 'Continue the previously requested work for prior item only if unfinished.'

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 4, 8}:
            params = wire['tools'][0]['function']['parameters']
            assert 'business_action_quote' not in params['properties']
            text = wire['messages'][-1]['content']
            if ordinal == 4:
                assert text == current and 'original place' not in text
            return native_call('classify_current_request', f'intent-{ordinal}',
                memory_write_request='none', allow_forgetting=False,
                business_action_request=('perform' if ordinal == 1 else
                                         'continue_if_unfinished' if ordinal == 4 else 'none'),
                business_operations=['reserve_and_label'] if ordinal == 1 else [])
        if ordinal == 2:
            return native_call('reserve_and_label', 'reserve', item_key='prior item', quantity=2,
                               destination='original place', packing='box')
        if ordinal == 5:
            assert len(wire['tools']) == 1
            assert wire['tools'][0]['function']['name'] == 'resolve_continuation_operations'
            frame = json.loads(wire['messages'][-1]['content'])
            assert frame['current_request'] == current
            assert not frame['accepted_current_mode']['allow_memory_maintenance']
            material = frame['archived_reference_material']
            assert 'prior item' in json.dumps(material)
            assert 'original place' in json.dumps(material)
            assert 'world' not in frame and 'checkpoint' not in frame
            return native_call('resolve_continuation_operations', 'resolve',
                business_operations=['reserve_and_label', 'complete_label'])
        if ordinal in {6, 9}:
            names = {t['function']['name'] for t in wire['tools']}
            assert 'save_memory' not in names and 'forget_memory' not in names
            if ordinal == 9:
                assert not names & functional.BUSINESS_MUTATIONS
            return native_call('get_reservation', f'query-{ordinal}', item_key='prior item')
        assert ordinal in {3, 7, 10}
        return {'role': 'assistant', 'content': 'Observed the actual status.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='reference-bank', owner='alice', workflow='reservation')
    first = functional.message(root, **args, session='s1', message_id='first',
        content='Reserve two of prior item for original place, packed in a box, with a label.')
    assert first['status'] == 'COMPLETED', first
    second_args = dict(**args, session='s2', message_id='next', content=current)
    second = functional.message(root, **second_args)
    assert second['status'] == 'COMPLETED', second
    assert second['request_mode']['reference_resolution']['attempts'] == 1
    assert second['request_mode']['business_operations'] == ['reserve_and_label', 'complete_label']
    assert second['operation_status']['business']['status'] == 'not_executed'
    resumed = functional.message(root, **second_args, resume=True)
    assert resumed['status'] == 'COMPLETED' and len(wires) == 7
    pure = functional.message(root, **args, session='s3', message_id='query-only',
                              content='Only query the current status; do not act.')
    assert pure['status'] == 'COMPLETED' and len(wires) == 10
    assert 'reference_resolution' not in pure['request_mode']
    assert len(pure['world']['world']['attempts']) == 1


@pytest.mark.parametrize('memory_continuation', [False, True])
def test_continuation_resolution_cannot_grant_other_permissions_or_reset_format_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, memory_continuation: bool,
) -> None:
    root = prepared(tmp_path, native=True, reference_mode_declaration=True, receipt_response=True,
                    memory_continuation=memory_continuation)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 2}:
            return native_call('classify_current_request', f'intent-{ordinal}',
                memory_write_request='INVALID' if ordinal == 1 else 'none',
                allow_forgetting=False, business_action_request='continue_if_unfinished',
                business_operations=[],
                **({'memory_continuation_request': 'none'} if memory_continuation else {}))
        assert ordinal == 3
        return native_call('resolve_continuation_operations', 'bad-resolution',
            business_operations=['reserve_and_label'], allow_forgetting=True,
            **({'prior_memory_request_fragments': []} if memory_continuation else {}))

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='b', owner='alice', session='s', message_id='continue',
                content='Continue the earlier work if needed.')
    first = functional.message(root, **args)
    assert first['error'] == 'FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID'
    second = functional.message(root, **args, resume=True)
    assert second['error'] == 'FUNCTIONAL_CONTINUATION_RESOLUTION_SCHEMA_INVALID'
    third = functional.message(root, **args, resume=True)
    assert third['error'] == 'FUNCTIONAL_CONTINUATION_RESOLUTION_REPROPOSAL_EXHAUSTED'
    assert len(wires) == 3
    assert not third['world']['world']['attempts'] and not third['records']


@pytest.mark.parametrize('resume_memory,continuation_scope', [
    (False, 'resume'), (True, 'resume'), (True, 'query'), (True, 'business_only')])
def test_new_message_after_w1_resumes_prior_save_without_repeating_business(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume_memory: bool, continuation_scope: str,
) -> None:
    """Keep the observed v6 gap; v7 must finish the prior explicit memory request."""
    root = prepared(tmp_path, native=True, independent_capabilities=True,
                    memory_continuation=resume_memory, receipt_response=True,
                    inline_fragments=True, existing_confirmation=True, operation_completion=True)
    prior = 'Reserve one glass cover for the optics bench in padding. Save the actual outcome.'
    current = {'resume': 'Check the glass cover and finish the authorized unfinished prior work.',
               'query': 'Only query the glass cover status. Do not save or perform any action.',
               'business_only': 'Continue only the prior glass cover business action; do not save.'}
    current = current[continuation_scope]
    memory_enabled = resume_memory and continuation_scope == 'resume'
    query_call = 4 if continuation_scope == 'query' else 5
    total_calls = query_call + 1 + int(memory_enabled)
    control = {'one_shot_fault': {'message_index': 0,
        'boundary': 'after_native_before_journal_complete',
        'target_operation': 'reserve_and_label', 'occurrence': 1}}
    query_ref: list[str] = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        assert 'one_shot_fault' not in json.dumps(wire)
        if ordinal in {1, 3}:
            assert wire['messages'][-1]['content'] == (prior if ordinal == 1 else current)
            return native_call('classify_current_request', f'intent-{ordinal}',
                memory_write_request='explicit' if ordinal == 1 else 'none',
                allow_forgetting=False,
                business_action_request='perform' if ordinal == 1 else
                'none' if continuation_scope == 'query' else 'continue_if_unfinished',
                business_operations=['reserve_and_label'] if ordinal == 1 else [],
                **({'memory_continuation_request': 'none' if ordinal == 1 or not memory_enabled
                    else 'resolve_prior_explicit'} if resume_memory else {}))
        if ordinal == 2:
            return native_call('reserve_and_label', 'reserve', item_key='glass cover', quantity=1,
                               destination='optics bench', packing='padding')
        if ordinal == 4 and continuation_scope != 'query':
            frame = json.loads(wire['messages'][-1]['content'])
            if resume_memory:
                assert frame['resolution_scope'] == {
                    'business_operations': 'resolve_from_prior_request',
                    'prior_memory_request_fragments': 'resolve_from_prior_request'
                        if memory_enabled else 'empty_required'}
                assert 'allow_memory_maintenance' not in frame['accepted_current_mode']
                assert 'allow_business_mutation' not in frame['accepted_current_mode']
            else:
                assert 'resolution_scope' not in frame
            units = frame['archived_reference_material']['items']
            handles = [row['fragment_handle'] for row in units
                       if row['type'] == 'fragment' and row['role'] == 'user'
                       and row['content'] == prior]
            assert handles and 'world' not in frame
            return native_call('resolve_continuation_operations', 'resolve',
                business_operations=['reserve_and_label'],
                **({'prior_memory_request_fragments': handles if memory_enabled else []}
                   if resume_memory else {}))
        names = {row['function']['name'] for row in wire['tools']}
        assert ('save_memory' in names) == memory_enabled
        assert 'forget_memory' not in names
        if continuation_scope == 'query':
            assert not names & functional.BUSINESS_MUTATIONS
        if ordinal == query_call:
            return native_call('get_reservation', 'query', item_key='glass cover')
        if ordinal == query_call + 1 and memory_enabled:
            receipt = actual_tool_receipt(wire)
            assert receipt['receipt']['label_status'] == 'created'
            query_ref.append(receipt['source_ref'])
            return native_call('save_memory', 'save-outcome',
                content='The glass cover is reserved and labeled for the optics bench.',
                fragment_handles=[row['fragment_handle']
                                  for row in receipt['source_fragment_index']])
        assert ordinal == total_calls
        return {'role': 'assistant', 'content': 'The queried outcome is recorded.' if memory_enabled
                else 'The actual reservation exists; semantic memory has not been committed.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='continuation-bank', owner='alice', workflow='reservation')
    first = functional.message(root, **args, session='first-session', message_id='first',
        content=prior, evaluator_control=control, message_index=0)
    assert first['status'] == 'UNKNOWN' and not first['records']
    next_args = dict(**args, session='next-session', message_id='next', content=current,
                     evaluator_control=control, message_index=1)
    final = functional.message(root, **next_args)
    assert final['status'] == 'COMPLETED', final
    assert len(final['world']['world']['attempts']) == 1
    original = [row for row in final['world']['journal'].values()
                if row.get('name') == 'reserve_and_label']
    assert len(original) == 1 and original[0]['status'] == 'pending'
    assert 'result' not in original[0]
    assert len(final['records']) == int(memory_enabled)
    assert len(wires) == total_calls
    if memory_enabled:
        value = final['records'][0]['value']
        assert value['basis'] == 'tool_observation' and value['source_ref'] == query_ref[0]
        assert value['source_ref'] != first['capture']['source_ref']
        assert final['operation_status']['semantic_memory']['status'] == 'committed'
    else:
        assert not final['request_mode']['allow_memory_maintenance']
    reopened = functional.message(root, **next_args, resume=True)
    assert reopened['status'] == 'COMPLETED' and reopened['records'] == final['records']
    assert len(wires) == total_calls


def test_document_w1_continues_memory_with_concrete_publish_permission_and_no_republish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, memory_continuation=True, operation_completion=True,
                    inline_fragments=True, existing_confirmation=True)
    prior = 'Create, approve and publish the local guide. Save its actual publication state.'
    current = ('Check the local guide; only finish publication '
               'and the remaining prior recordkeeping.')
    control = {'one_shot_fault': {'message_index': 0,
        'boundary': 'after_native_before_journal_complete',
        'target_operation': 'publish_approved_document', 'occurrence': 1}}
    observed_source: list[str] = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 5}:
            return native_call('classify_current_request', f'intent-{ordinal}',
                memory_write_request='explicit' if ordinal == 1 else 'none',
                memory_continuation_request='none' if ordinal == 1 else 'resolve_prior_explicit',
                allow_forgetting=False,
                business_action_request='perform' if ordinal == 1 else 'continue_if_unfinished',
                business_operations=['create_or_update_draft', 'approve_document_version',
                    'publish_approved_document'] if ordinal == 1 else ['publish_approved_document'])
        if ordinal == 2:
            return native_call('create_or_update_draft', 'draft', title='local guide',
                               content='Reviewed local instructions.', document_version=0)
        if ordinal in {3, 4}:
            receipt = actual_tool_receipt(wire)['receipt']
            args = {k: receipt[k] for k in ('title', 'document_version')}
            if ordinal == 4:
                args['audience'] = 'local audience'
            return native_call('approve_document_version' if ordinal == 3
                               else 'publish_approved_document', f'phase-{ordinal}', **args)
        if ordinal == 6:
            frame = json.loads(wire['messages'][-1]['content'])
            assert frame['resolution_scope'] == {
                'business_operations': 'keep_current_list',
                'prior_memory_request_fragments': 'resolve_from_prior_request'}
            assert frame['accepted_current_mode']['business_operations'] == [
                'publish_approved_document']
            handles = [row['fragment_handle']
                       for row in frame['archived_reference_material']['items']
                       if row['type'] == 'fragment' and row['role'] == 'user'
                       and row['content'] == prior]
            assert handles
            return native_call('resolve_continuation_operations', 'resolve',
                business_operations=['publish_approved_document'],
                prior_memory_request_fragments=handles)
        names = {row['function']['name'] for row in wire['tools']}
        assert 'save_memory' in names
        assert not {'create_or_update_draft', 'approve_document_version', 'forget_memory'} & names
        if ordinal == 7:
            return native_call('get_document_status', 'query', title='local guide')
        if ordinal == 8:
            receipt = actual_tool_receipt(wire)
            assert receipt['receipt']['publication_status'] == 'published'
            observed_source.append(receipt['source_ref'])
            return native_call('save_memory', 'save-observation',
                content='The local guide is published for the local audience.',
                fragment_handles=[row['fragment_handle']
                                  for row in receipt['source_fragment_index']])
        assert ordinal == 9
        return {'role': 'assistant', 'content': 'The queried publication state is recorded.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='document-continuation', owner='alice', workflow='document')
    first = functional.message(root, **args, session='initial', message_id='first',
        content=prior, evaluator_control=control, message_index=0)
    assert first['status'] == 'UNKNOWN' and not first['records']
    second = functional.message(root, **args, session='following', message_id='next',
        content=current, evaluator_control=control, message_index=1)
    assert second['status'] == 'COMPLETED', second
    assert len(wires) == 9 and len(second['records']) == 1
    assert second['world']['world'] == first['world']['world']
    document = second['world']['world']['documents'][0]
    assert len(document['publications']) == 1
    publication = [row for row in second['world']['journal'].values()
                   if row.get('name') == 'publish_approved_document']
    assert len(publication) == 1 and publication[0]['status'] == 'pending'
    assert 'result' not in publication[0]
    assert second['records'][0]['value']['source_ref'] == observed_source[0]
    assert second['operation_status']['semantic_memory']['status'] == 'committed'


@pytest.mark.parametrize('selection', ['prior', 'current', 'assistant', 'tool', 'undelivered',
    'foreign_owner', 'cached_then_forgotten', 'business_escalation', 'forget_escalation',
    'memory_exclusion'])
def test_continuation_memory_requires_visible_delivered_archived_user_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: str,
) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError('REAL_NETWORK_FORBIDDEN')

    monkeypatch.setattr(socket.socket, 'connect', denied)
    with SqliteStore.from_conn_string(str(tmp_path / 'store.sqlite')) as store:
        service = functional.MemoryService(store, ('resume-probe', 'alice'), 'alice',
            tmp_path / 'service.lock', functional_contract='functional_v1')
        memory = functional.FunctionalMemory(service, len, material_limit=100000,
                                              recent_context='bank_recent_v2')
        prior = service.capture_user('old', 'request', 'Save the prior observed outcome.')
        memory.context('old', 'request', 'a' * 64)
        assistant = service.capture_assistant('old', 'answer', 'The prior outcome needs saving.')
        tool_event = service.capture_tool('old', 'query', 'get_reservation',
                                         '{"prior":"Save this outcome"}', None)
        current = service.capture_user('new', 'continue', 'Continue the prior unfinished work.')
        material = memory.context('new', 'continue', 'a' * 64)
        refs = {'prior': prior['source_ref'], 'cached_then_forgotten': prior['source_ref'],
                'current': current['source_ref'], 'assistant': assistant['source_ref'],
                'tool': tool_event['source_ref']}
        if selection == 'foreign_owner':
            foreign = functional.MemoryService(store, ('resume-probe', 'bob'), 'bob',
                tmp_path / 'bob.lock', functional_contract='functional_v1')
            receipt = foreign.capture_user('old', 'request', 'Save the prior observed outcome.')
            fragment = foreign.source_fragments(receipt['source_ref'])[0]
            # Even a forged delivery wrapper cannot make another owner's handle valid.
            material['items'].append({'type': 'fragment', **fragment})
            selected = fragment['fragment_handle']
        elif selection == 'undelivered':
            selected = 'frag-never-delivered'
        else:
            chosen_ref = refs.get(selection, prior['source_ref'])
            selected = next(row['fragment_handle'] for row in material['items']
                if row['type'] == 'fragment' and row['source_ref'] == chosen_ref)
        mode = {'protocol': 'native_continuation_capabilities_v7',
            'business_action_request': 'none', 'business_operations': [],
            'business_declaration_status': 'none', 'allow_business_mutation': False,
            'memory_write_request': 'none', 'allow_memory_maintenance': False,
            'requires_memory_result': False, 'allow_forgetting': False,
            'memory_continuation_request': 'resolve_prior_explicit', 'format_reproposals_used': 0}
        if selection == 'memory_exclusion':
            mode.update(memory_continuation_request='none',
                        business_action_request='continue_if_unfinished')
        binding = {'source_ref': current['source_ref'], 'config_sha256': 'a' * 64}

        class Resolver:
            calls = 0

            def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
                self.calls += 1
                decision = {'business_operations': ['reserve_and_label']
                            if selection in {'business_escalation', 'memory_exclusion'} else [],
                            'prior_memory_request_fragments': [selected]}
                if selection == 'forget_escalation':
                    decision['allow_forgetting'] = True
                return AIMessage(content='', tool_calls=[{'name': 'resolve_continuation_operations',
                    'id': 'resolution', 'args': decision}])

        model = Resolver()

        def resolve() -> dict[str, Any]:
            return functional.continuation_operations(model, tmp_path / 'resolution.json', binding,
                'Continue the prior unfinished work.', mode, material, 1, lambda event: None,
                source_fragment=service.source_fragment)

        if selection in {'prior', 'cached_then_forgotten'}:
            result = resolve()
            assert result['allow_memory_maintenance'] and result['requires_memory_result']
            assert not result['allow_business_mutation'] and not result['allow_forgetting']
            assert result['resumed_memory_request']['source_refs'] == [prior['source_ref']]
            assert resolve() == result and model.calls == 1
            if selection == 'cached_then_forgotten':
                forgotten = service.forget('forget', 'revoke', fragment_handles=[selected])
                assert forgotten['ok'] and service.source(prior['source_ref']) is None
                with pytest.raises(functional.FunctionalRejection, match='SOURCE_UNAVAILABLE'):
                    resolve()
                assert model.calls == 1  # A cached interpretation cannot revive a hidden request.
        elif selection in {'business_escalation', 'forget_escalation', 'memory_exclusion'}:
            with pytest.raises(functional.IncompleteChatResponse, match='SCHEMA_INVALID'):
                resolve()
            assert model.calls == 1
        else:
            expected = ('NOT_DELIVERED' if selection == 'undelivered' else
                        'FRAGMENT_NOT_ISSUED' if selection == 'foreign_owner' else 'SOURCE_INVALID')
            with pytest.raises(functional.FunctionalRejection, match=expected):
                resolve()
            assert model.calls == 1


@pytest.mark.parametrize('remaining', ['satisfied', 'confirm_existing', 'second_item'])
def test_continuation_respects_existing_records_without_treating_one_receipt_as_full_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remaining: str,
) -> None:
    root = prepared(tmp_path, native=True, memory_continuation=True, operation_completion=True,
                    existing_confirmation=True, direct_response=True, phase_thinking=True,
                    current_delivery=True)
    prior = ('Remember alpha is blue and beta is red.' if remaining == 'second_item'
             else 'Remember alpha is blue.')
    current = 'Finish the remaining prior memory request; preserve already completed records.'
    original_handles: list[str] = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 4}:
            return native_call('classify_current_request', f'intent-{ordinal}',
                memory_write_request='explicit' if ordinal == 1 else 'none',
                memory_continuation_request='none' if ordinal == 1 else 'resolve_prior_explicit',
                business_action_request='none', business_operations=[], allow_forgetting=False)
        if ordinal == 2:
            original_handles.extend(row['fragment_handle'] for row in materials(wire)['items']
                if row['type'] == 'fragment' and row['content'] == prior)
            return native_call('save_memory', 'save-alpha', content='Alpha is blue.',
                               fragment_handles=original_handles)
        if ordinal == 3:
            return {'role': 'assistant', 'content': 'Alpha has been saved.'}
        if ordinal == 5:
            frame = json.loads(wire['messages'][-1]['content'])
            assert frame['resolution_scope'] == {
                'business_operations': 'keep_current_list',
                'prior_memory_request_fragments': 'resolve_from_prior_request'}
            assert frame['accepted_current_mode']['business_operations'] == []
            items = frame['archived_reference_material']['items']
            assert any(row['type'] == 'record' and row['content'] == 'Alpha is blue.'
                       for row in items)
            return native_call('resolve_continuation_operations', 'resolve', business_operations=[],
                prior_memory_request_fragments=[] if remaining == 'satisfied' else original_handles)
        names = {row['function']['name'] for row in wire['tools']}
        assert not names & functional.BUSINESS_MUTATIONS and 'forget_memory' not in names
        if ordinal == 6 and remaining != 'satisfied':
            if remaining == 'confirm_existing':
                record = next(row for row in materials(wire)['items'] if row['type'] == 'record')
                return native_call('confirm_existing_memory', 'confirm',
                                   read_handle=record['read_handle'])
            return native_call('save_memory', 'save-beta', content='Beta is red.',
                               fragment_handles=original_handles)
        assert ordinal == (6 if remaining == 'satisfied' else 7)
        if remaining == 'satisfied':
            assert not {'save_memory', 'update_memory', 'confirm_existing_memory'} & names
        elif remaining == 'confirm_existing':
            assert actual_tool_receipt(wire)['status'] == 'no_change'
        else:
            assert actual_tool_receipt(wire)['status'] == 'committed'
        return {'role': 'assistant', 'content': 'The remaining item is saved.'
                if remaining == 'second_item' else 'The existing record is unchanged.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='memory-continuation', owner='alice')
    first = functional.message(root, **args, session='old', message_id='first', content=prior)
    assert first['status'] == 'COMPLETED' and len(first['records']) == 1, first
    second = functional.message(root, **args, session='new', message_id='next', content=current)
    assert second['status'] == 'COMPLETED', second
    assert len(wires) == (6 if remaining == 'satisfied' else 7)
    assert len(second['records']) == (2 if remaining == 'second_item' else 1)
    alpha = next(row for row in second['records'] if row['id'] == first['records'][0]['id'])
    assert alpha['value'] == first['records'][0]['value']
    assert not second['world']['world']['attempts']
    expected = {'satisfied': 'not_committed', 'confirm_existing': 'no_change',
                'second_item': 'committed'}[remaining]
    assert second['operation_status']['semantic_memory']['status'] == expected


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
            args = {k: receipt[k] for k in ['title', 'document_version']}
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


@pytest.mark.parametrize('failed_response', [False, True])
def test_receipt_response_cannot_replay_revoked_business_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    failed_response: bool,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True, receipt_response=True,
                    failure_receipts=failed_response)
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
            if failed_response:
                return {'role': 'assistant', 'content': None}
            return {'role': 'assistant', 'content': 'Execution done.'}
        if ordinal == 4:
            record = next(row for row in materials(wire)['items'] if row['type'] == 'record')
            return native_call('forget_memory', 'forget', read_handle=record['read_handle'])
        assert ordinal in {5, 6}
        assert private_item not in json.dumps(wire)
        return {'role': 'assistant', 'content': 'Forgotten within the requested scope.'}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first['status'] == ('FAILED' if failed_response else 'COMPLETED')
    assert private_item in first['final_answer']
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
                k: receipt[k] for k in ['title', 'document_version']})
        if ordinal in {4, 9}:
            return {'role': 'assistant', 'content': 'Actual operations reported.'}
        names = {t['function']['name'] for t in wire['tools']}
        assert 'publish_approved_document' in names and 'get_document_status' in names
        assert not {'create_or_update_draft', 'approve_document_version', 'save_memory'} & names
        if ordinal == 6:
            return native_call('get_document_status', 'query', title='Stable document')
        receipt = actual_tool_receipt(wire)['receipt']
        bound = {k: receipt[k] for k in ['title', 'document_version']}
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


@pytest.mark.parametrize('quote', ['', 'do not publish', 'Only view; do not publish.'])
def test_readonly_declaration_retains_bound_negative_quote_without_granting_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quote: str,
) -> None:
    root = prepared(tmp_path, native=True, operation_mode_declaration=True, receipt_response=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'intent', memory_write_request='none',
                allow_forgetting=False, business_action_request='none', business_action_quote=quote,
                business_operations=[])
        names = {t['function']['name'] for t in wire['tools']}
        assert not names & functional.BUSINESS_MUTATIONS
        assert 'get_document_status' in names and 'save_memory' not in names
        if ordinal == 2:
            return native_call('get_document_status', 'query', title='read-only object')
        assert ordinal == 3
        return {'role': 'assistant', 'content': 'Read-only result.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='b', owner='alice', session='s', workflow='document',
                message_id='query', content='Only view; do not publish.')
    result = functional.message(root, **args)
    assert result['status'] == 'COMPLETED', result
    assert result['request_mode']['business_action_quote'] == quote
    assert result['request_mode']['business_operations'] == []
    assert not result['request_mode']['allow_business_mutation']
    assert result['operation_status']['business']['status'] == 'not_executed'
    resumed = functional.message(root, **args, resume=True)
    assert resumed['status'] == 'COMPLETED' and resumed['request_mode'] == result['request_mode']
    assert len(wires) == 3


@pytest.mark.parametrize('bad', ['null', 'truncated', 'unknown_tool'])
def test_protocol_failure_delivers_receipts_without_repair_or_repeating_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    root = prepared(tmp_path, native=True, receipt_response=True, failure_receipts=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('reserve_and_label', 'actual', item_key='receipt item',
                               quantity=2, destination='local', packing='box')
        assert ordinal == 2
        if bad == 'unknown_tool':
            return native_call('invented_tool', 'forbidden', value='MUST_NOT_EXECUTE')
        return {'role': 'assistant', 'content': None,
                '_test_finish_reason': 'length' if bad == 'truncated' else 'stop',
                'reasoning_content': 'REASONING_MUST_NOT_BECOME_FINAL'}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result['status'] == 'FAILED' and result['error_category'] == 'provider_protocol'
    assert result['final_delivery']['status'] == 'available'
    assert '回答协议失败' in result['final_answer'] and 'receipt item' in result['final_answer']
    assert '本轮语义记忆: 未提交' in result['final_answer']
    assert 'REASONING_MUST_NOT_BECOME_FINAL' not in result['final_answer']
    assert result['operation_status']['request_completion'] == 'unchecked'
    assert result['operation_status']['business']['status'] == 'completed'
    assert len(result['world']['world']['attempts']) == 1 and len(wires) == 2
    replay = message(root)
    assert replay['final_answer'] == result['final_answer'] and len(wires) == 2


@pytest.mark.parametrize('case', ['continue', 'readonly', 'condition_unmet', 'already_attempted',
                                  'already_complete', 'allowance_exhausted'])
def test_continuation_feedback_is_bounded_and_cannot_authorize_or_repeat_an_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    root = prepared(tmp_path, native=True, reference_mode_declaration=True,
                    receipt_response=True, business_feedback=True,
                    format_allowance=0 if case == 'allowance_exhausted' else 1)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 4}:
            action = 'perform' if ordinal == 1 else (
                'none' if case == 'readonly' else 'continue_if_unfinished')
            operations = ['reserve_and_label'] if ordinal == 1 else (
                [] if case == 'readonly' else ['complete_label'])
            return native_call('classify_current_request', 'mode'+str(ordinal),
                memory_write_request='none', allow_forgetting=False,
                business_action_request=action, business_operations=operations)
        if ordinal == 2:
            return native_call('reserve_and_label', 'reserve', item_key='feedback item',
                               quantity=1, destination='local', packing='box')
        if ordinal == 3:
            return {'role':'assistant', 'content':'Partial reservation.'}
        if ordinal == 5:
            return native_call('get_reservation', 'query', item_key='feedback item')
        if ordinal == 6 and case == 'already_attempted':
            receipt = actual_tool_receipt(wire)['receipt']
            return native_call('complete_label', 'once', reservation_id=receipt['reservation_id'])
        if ordinal == 6 or case == 'already_attempted':
            return {'role':'assistant', 'content':'I will continue next.'}
        assert case != 'readonly'
        assert 'observed_missing_stage_not_action_authorization' in wire['messages'][0]['content']
        names = {t['function']['name'] for t in wire['tools']}
        assert 'complete_label' in names and not names.intersection(
            {'reserve_and_label', 'save_memory', 'update_memory', 'forget_memory'})
        if ordinal == 7 and case == 'continue':
            receipt = actual_tool_receipt(wire)['receipt']
            return native_call('complete_label', 'continue-once',
                               reservation_id=receipt['reservation_id'])
        assert ordinal == (8 if case == 'continue' else 7)
        return {'role':'assistant', 'content':'Current conditions prevent completion.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = {'bank':'mechanical-bank','owner':'alice','session':'session'}
    first = functional.message(root, **common, message_id='initial',
        content='Reserve and label feedback item.',
        initial_world={'label_available':case == 'already_complete'})
    assert first['status'] == 'COMPLETED'
    second_input = ('Check the current feedback item only.' if case == 'readonly' else
                    'Check feedback item and continue its missing label if authorized.')
    second = functional.message(root, **common, message_id='followup', content=second_input)
    assert second['status'] == 'COMPLETED', second
    feedbacks = list(root.glob('banks/*/*-continuation-feedback.json'))
    assert bool(feedbacks) == (case in {'continue', 'condition_unmet'})
    if feedbacks:
        assert json.loads(feedbacks[0].read_text())['attempts'] == 1
    business = second['operation_status']['business']
    assert len(business['operations']) == int(case in {'continue','already_attempted'})
    count = len(wires)
    replay = functional.message(root, **common, message_id='followup', content=second_input,
                                resume=True)
    assert replay['final_answer'] == second['final_answer'] and len(wires) == count
    assert len(replay['world']['world']['reservations']) == 1


@pytest.mark.parametrize('mode', ['unknown_attempt', 'none_attempt', 'different_target',
                                  'unpaired_query', 'missing_approval', 'eligible'])
def test_continuation_observation_requires_current_paired_target_and_no_prior_attempt(
    mode: str,
) -> None:
    from milai_lab.runners.functional_response import unattempted_continuations

    query = {'name':'get_document_status','args':{'title':'bound title'},'id':'q'}
    messages = [AIMessage(content='',tool_calls=[query]), ToolMessage(name='get_document_status',
        tool_call_id='q', content=json.dumps({'receipt':{'status':'found','title':'bound title',
            'approval_status':'not_approved' if mode == 'missing_approval' else 'approved',
            'publication_status':'not_published'}}))]
    effects = {'business':{'operations':[], 'observations':[] if mode == 'unpaired_query' else [
        {'tool':'get_document_status','receipt_ref':'q','executed':True,
         'execution_receipt_status':'complete'}]}}
    if mode in {'unknown_attempt','none_attempt','different_target'}:
        messages.append(AIMessage(content='',tool_calls=[{'name':'publish_approved_document',
            'args':{'title':'other title' if mode == 'different_target' else 'bound title'},
            'id':'mutation'}]))
        effects['business']['operations'].append({'tool':'publish_approved_document',
            'receipt_ref':'mutation','effect':'unknown' if mode=='unknown_attempt' else 'none'})
    gaps = unattempted_continuations(messages, effects, ['publish_approved_document'])
    assert bool(gaps) == (mode in {'eligible','different_target'})
    if gaps:
        assert gaps[0]['target'] == 'bound title' and gaps[0]['query_receipt_ref'] == 'q'
    assert unattempted_continuations(messages, effects, []) == []


@pytest.mark.parametrize('section,key', [(None, 'ordinary_materal_tokens'),
                                        ('capacity', 'context_token')])
def test_prepare_rejects_unknown_configuration_before_runtime(
    tmp_path: Path, section: str | None, key: str,
) -> None:
    prepared(tmp_path)
    settings = read_json(tmp_path / 'settings.json')
    target = settings if section is None else settings[section]
    target[key] = 64
    write_json(tmp_path / 'typo.json', settings)
    with pytest.raises(ValueError, match='UNKNOWN_KEYS'):
        functional.prepare(tmp_path / 'invalid-run', tmp_path / 'typo.json')
    assert not (tmp_path / 'invalid-run' / 'input-freeze.json').exists()


def test_preagent_protocol_failure_is_delivered_and_visible_after_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, reference_mode_declaration=True,
                    current_delivery=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 2}:
            assert wire['tool_choice'] == 'required'
            assert len(wire['tools']) == 1
        if ordinal == 1:
            return {'role': 'assistant', 'content': 'Malformed declaration without a tool.'}
        if ordinal == 2:
            return native_call('classify_current_request', 'mode', memory_write_request='none',
                               allow_forgetting=False, business_action_request='none',
                               business_operations=[])
        if ordinal == 3:
            packet = materials(wire)
            assert any(u.get('role') == 'assistant' and '回答协议失败' in u.get('content', '')
                       for u in packet['items'])
            assert any(u.get('role') == 'user' and u.get('content') == 'Withdraw the special rule.'
                       for u in packet['items'])
            return {'role': 'assistant', 'content': 'The earlier request did not commit.'}
        assert ordinal == 4 and not wire.get('tools')
        return {'role': 'assistant', 'content': 'The earlier request did not commit.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='mechanical-bank', owner='alice', session='s')
    failed = functional.message(root, **common, message_id='withdraw',
                                content='Withdraw the special rule.')
    assert failed['status'] == 'FAILED' and failed['error_category'] == 'provider_protocol'
    assert failed['final_delivery']['status'] == 'available'
    assert failed['operation_status']['semantic_memory']['status'] == 'not_committed'
    assert failed['operation_status']['business']['status'] == 'not_executed'
    assert not failed.get('messages') and failed['final_capture']['ok']
    later = functional.message(root, **common, message_id='later', content='Did it succeed?')
    assert later['status'] == 'COMPLETED' and len(wires) == 4
    assert not later['records'] and not later['operation_status']['business']['operations']


def test_guessed_business_mode_without_receipts_keeps_conversational_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, reference_mode_declaration=True,
                    current_delivery=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode', memory_write_request='none',
                               allow_forgetting=False, business_action_request='perform',
                               business_operations=['create_or_update_draft'])
        if ordinal == 2:
            return {'role': 'assistant', 'content': 'Untrusted execution draft.'}
        assert ordinal == 3 and not wire.get('tools')
        assert 'Untrusted execution draft.' not in json.dumps(wire)
        return {'role': 'assistant', 'content': 'No earlier unit is available in the material.'}

    wires = scripted(monkeypatch, reply, native=True)
    result = functional.message(root, bank='b', owner='alice', session='s', message_id='m',
                                 content='What unit did I use earlier?')
    assert result['status'] == 'COMPLETED' and len(wires) == 3
    assert result['final_answer'] == 'No earlier unit is available in the material.'
    assert result['operation_status']['business']['status'] == 'not_executed'


@pytest.mark.parametrize('writes', [True, False])
def test_completion_excludes_false_draft_but_retains_checkpoint_and_truthful_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writes: bool,
) -> None:
    root = prepared(tmp_path, native=True, reference_mode_declaration=True,
                    current_delivery=True, fresh_completion=True)
    draft = 'FALSE_UNDELIVERED_CONFIRMATION'

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode', memory_write_request='explicit',
                               allow_forgetting=False, business_action_request='none',
                               business_operations=[])
        if ordinal == 2:
            return {'role': 'assistant', 'content': draft}
        assert draft not in json.dumps(wire)
        if ordinal == 3:
            names = {t['function']['name'] for t in wire['tools']}
            assert 'save_memory' in names and not names.intersection(
                {'reserve_and_label', 'complete_label', 'forget_memory'})
            if writes:
                unit = next(u for u in materials(wire)['items'] if u['type'] == 'fragment')
                return native_call('save_memory', 'actual-save', content='Prefer quiet rooms.',
                                   fragment_handles=[unit['fragment_handle']])
            return {'role': 'assistant', 'content': 'SECOND_UNDELIVERED_CONFIRMATION'}
        return {'role': 'assistant', 'content': 'Saved after the actual commit.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice', session='s', message_id='save',
                  content='Remember that I prefer quiet rooms.')
    result = functional.message(root, **common)
    assert any(m.get('content') == draft for m in result['messages'])
    assert draft not in result['final_answer']
    assert result['status'] == ('COMPLETED' if writes else 'FAILED')
    assert result['final_delivery']['status'] == 'available'
    assert result['operation_status']['semantic_memory']['status'] == (
        'committed' if writes else 'not_committed')
    assert len(result['records']) == int(writes)
    if not writes:
        assert '请求未完成' in result['final_answer']
        assert '本轮语义记忆: 未提交' in result['final_answer']
        assert 'SECOND_UNDELIVERED_CONFIRMATION' not in result['final_answer']
        assert result['final_capture']['ok']
    count = len(wires)
    replay = functional.message(root, **common)
    assert replay['final_answer'] == result['final_answer'] and len(wires) == count


@pytest.mark.parametrize('variant', ['legacy', 'memory', 'readonly', 'wrong_none', 'unknown_op'])
def test_empty_business_operations_grant_nothing_and_do_not_block_independent_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str,
) -> None:
    root = prepared(tmp_path, native=True, reference_mode_declaration=True,
                    current_delivery=True, independent_capabilities=variant != 'legacy')

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode',
                memory_write_request='none' if variant == 'readonly' else 'explicit',
                allow_forgetting=False,
                business_action_request='none' if variant == 'wrong_none' else 'perform',
                business_operations=['reserve_and_label'] if variant == 'wrong_none' else
                                    ['unavailable_operation'] if variant == 'unknown_op' else [])
        assert variant in {'memory', 'readonly'}
        if wire.get('tools'):
            names = {t['function']['name'] for t in wire['tools']}
            assert not names.intersection(functional.BUSINESS_MUTATIONS | {'forget_memory'})
            assert bool(names.intersection({'save_memory', 'update_memory'})) == (
                variant == 'memory')
        if ordinal == 2 and variant == 'memory':
            unit = next(u for u in materials(wire)['items'] if u['type'] == 'fragment')
            return native_call('save_memory', 'supported-save', content='Prefer quiet rooms.',
                               fragment_handles=[unit['fragment_handle']])
        return {'role': 'assistant', 'content': 'Only the available memory result is reported.'}

    wires = scripted(monkeypatch, reply, native=True)
    result = functional.message(root, bank='b', owner='alice', session='s', message_id='m',
                                 content='Remember that I prefer quiet rooms.')
    if variant in {'legacy', 'wrong_none', 'unknown_op'}:
        assert result['error'] == 'FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID' and len(wires) == 1
        assert not result['records']
    else:
        assert result['status'] == 'COMPLETED'
        mode = result['request_mode']
        assert not mode['allow_business_mutation'] and mode['business_operations'] == []
        assert mode['business_declaration_status'] == 'unresolved_no_business_permission'
        assert len(result['records']) == int(variant == 'memory')
    assert not result['operation_status']['business']['operations']


@pytest.mark.parametrize('visibility_stop', [False, True])
@pytest.mark.parametrize('memory_profile', ['ordinary', 'unified_v1'])
def test_declared_forget_is_maintenance_and_visibility_stop_keeps_terminal_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, visibility_stop: bool,
    memory_profile: str,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True,
        independent_capabilities=True, current_delivery=True, fresh_completion=True,
        operation_completion=True, memory_profile=memory_profile)
    secret = 'MECHANICAL_REVOKED_BODY'

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 5}:
            return native_call('classify_current_request', f'mode-{ordinal}',
                memory_write_request='explicit', allow_forgetting=ordinal == 5,
                business_action_request='none', business_operations=[])
        if ordinal == 2:
            hs = [u['fragment_handle'] for u in materials(wire)['items']
                  if u['type'] == 'fragment' and secret in u['content']]
            return native_call('save_memory', 'save', content=secret, fragment_handles=hs)
        if ordinal in {3, 4}:
            return {'role': 'assistant', 'content': 'Saved the requested marker.'}
        if ordinal == 6:
            record = next(u for u in materials(wire)['items'] if u['type'] == 'record')
            return native_call('forget_memory', 'forget', read_handle=record['read_handle'])
        assert ordinal == 7 and not visibility_stop
        assert secret not in json.dumps(wire)
        assert actual_tool_receipt(wire)['status'] == 'visibility_revoked'
        return {'role': 'assistant', 'content': 'Overbroad draft: erased every backup forever.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice')
    first = functional.message(root, **common, session='s1', message_id='save',
                               content='Remember ' + secret)
    assert first['status'] == 'COMPLETED'
    if visibility_stop:
        monkeypatch.setattr(functional, '_verified_forget_continuation', lambda *a, **kw: False)
    result = functional.message(root, **common, session='s2', message_id='forget',
                                content='Forget the previously saved marker and its sources.')
    assert not list(root.glob('banks/*/*-completion-feedback.json'))
    assert secret not in str(result.get('final_answer'))
    if visibility_stop:
        assert result['status'] == 'VISIBILITY_REVOKED'
        assert result['terminal_snapshot'] == 'visibility_redacted'
        assert result['budget_after']['generation_requests'] == len(wires) == 6
        assert result['budget_after']['generation_requests'] - (
            result['budget_before']['generation_requests']) == 2
        assert result['messages'] == [] and 'content' not in result
    else:
        assert result['status'] == 'COMPLETED', result
        assert len(wires) == 7  # No additional model generation for program confirmation.
        assert result['final_capture']['ok']
        assert '未执行物理擦除' in result['final_answer']
        assert 'erased every backup' not in result['final_answer']
        assert result['operation_status']['semantic_memory']['status'] == 'not_committed'
        assert result['operation_status']['visibility']['operations'][0][
            'status'] == 'visibility_revoked'
        exported = functional.memory_data(root, **common, operation='export')
        assert secret not in json.dumps(exported)
        assert result['final_capture']['source_ref'] not in {
            source['event_id'] for source in exported['sources']}
        if memory_profile == 'unified_v1':
            assert result['final_capture']['visibility'] == 'revoked'
            indexed = functional.memory_data(root, **common, operation='index-episodes')
            assert indexed['episode_ids'] == []
            assert functional.memory_data(root, **common, operation='episodes') == {'episodes': []}
    attempts = [json.loads(p.read_text()) for p in root.glob('banks/*/*-attempt-*.json')]
    assert len(attempts) == 2 and attempts[-1] != {}
    assert any(a['message_id'] == 'forget' and a['status'] == result['status'] for a in attempts)


@pytest.mark.parametrize("reader_thinking", [None, False])
def test_phase_thinking_uses_actual_templates_and_one_shared_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader_thinking: bool | None,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True,
        independent_capabilities=True, current_delivery=True, fresh_completion=True,
        operation_completion=True, phase_thinking=True,
        stage_enable_thinking={"reader": reader_thinking} if reader_thinking is not None else None)

    def expected_thinking(ordinal: int) -> bool:
        return ordinal != 1 and not (ordinal == 4 and reader_thinking is False)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        assert wire['chat_template_kwargs']['enable_thinking'] is expected_thinking(ordinal)
        if ordinal == 1:
            assert wire['tool_choice'] == 'required'
            return native_call('classify_current_request', 'mode',
                memory_write_request='explicit', allow_forgetting=False,
                business_action_request='none', business_operations=[])
        if ordinal == 2:
            hs = [u['fragment_handle'] for u in materials(wire)['items'] if u['type'] == 'fragment']
            return native_call('save_memory', 'save', content='The local marker is blue.',
                               fragment_handles=hs)
        assert ordinal in {3, 4}
        return {'role': 'assistant', 'content': 'Saved the local marker.'}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result['status'] == 'COMPLETED', result
    assert len(wires) == result['generation_calls'] == 4
    queue = read_json(root / 'queue-admission.json')
    assert queue['requests'] == 4
    trace = next(root.glob('banks/*/*-trace-0.jsonl'))
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    responses = [e for e in events if e.get('event') == 'vllm_response']
    assert len(responses) == 4
    for index, event in enumerate(responses):
        thinking = expected_thinking(index + 1)
        assert event['request']['chat_template_kwargs']['enable_thinking'] is thinking
        assert event['capacity']['identity']['enable_thinking'] is thinking
    assert result['budget_after']['generation_requests'] == 4
    replay = message(root)
    assert replay['final_answer'] == result['final_answer'] and len(wires) == 4


@pytest.mark.parametrize('field', ['reasoning', 'reasoning_content'])
@pytest.mark.parametrize('interrupted', [False, True])
def test_native_tool_reasoning_roundtrip_survives_reopen_and_is_removed_after_forget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, interrupted: bool,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True,
        independent_capabilities=True, current_delivery=True, fresh_completion=True,
        operation_completion=True, phase_thinking=True, reasoning_history=True)
    secret = 'MECHANICAL_REASONING_SECRET'
    thought = 'The requested current value is ' + secret

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 5}:
            return native_call('classify_current_request', f'mode-{ordinal}',
                memory_write_request='explicit', allow_forgetting=ordinal == 5,
                business_action_request='none', business_operations=[])
        if ordinal == 2:
            hs = [u['fragment_handle'] for u in materials(wire)['items']
                  if u['type'] == 'fragment' and secret in u['content']]
            return {**native_call('save_memory', 'save', content=secret, fragment_handles=hs),
                    field: thought}
        if ordinal == 3:
            assistant = next(m for m in wire['messages'] if m.get('tool_calls'))
            assert assistant['reasoning_content'] == thought
            assert actual_tool_receipt(wire)['status'] in {'committed', 'no_change'}
            return {'role': 'assistant', 'content': 'Saved the requested marker.'}
        if ordinal == 4:
            assert 'reasoning_content' not in json.dumps(wire)
            return {'role': 'assistant', 'content': 'The requested marker is saved.'}
        if ordinal == 6:
            record = next(u for u in materials(wire)['items'] if u['type'] == 'record')
            return {**native_call('forget_memory', 'forget', read_handle=record['read_handle']),
                    field: 'Forget this retrieved item: ' + secret}
        assert ordinal == 7
        assert secret not in json.dumps(wire)
        assert not any('reasoning_content' in m for m in wire['messages'])
        return {'role': 'assistant', 'content': 'Visibility revoked.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice')
    args: dict[str, Any] = dict(session='s1', message_id='save', content='Remember ' + secret)
    if interrupted:
        args.update(evaluator_control={'one_shot_fault': {'message_index': 0, 'boundary': 'W3',
            'target_operation': 'save_memory', 'occurrence': 1}}, message_index=0)
    result = functional.message(root, **common, **args)
    if interrupted:
        assert result['status'] == 'UNKNOWN' and len(wires) == 2
        result = functional.message(root, **common, **args, resume=True)
    assert result['status'] == 'COMPLETED', result
    assert len(wires) == 4 and len(result['records']) == 1
    assert 'reasoning_content' not in json.dumps(result['messages'])
    forgotten = functional.message(root, **common, session='s2', message_id='forget',
                                   content='Forget the stored marker and its sources.')
    assert forgotten['status'] == 'COMPLETED', forgotten
    assert len(wires) == 7
    visible = {key: forgotten[key] for key in ('final_answer', 'messages', 'records', 'sources')}
    assert secret not in json.dumps(visible, ensure_ascii=False)
    # The explicit evaluator sidecar is retained audit, never a Host tool/input.
    # Visibility revocation does not physically erase operation journal artifacts.
    assert secret in json.dumps(forgotten['world']['receipt_progress'])
    assert all(r.get('status') == 'visibility_revoked' for r in forgotten['records'])


@pytest.mark.parametrize('value', [None, '{'])
def test_reasoning_never_replaces_unusable_final_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: Any,
) -> None:
    root = prepared(tmp_path, native=True, reasoning_history=True)
    scripted(monkeypatch, lambda wire, ordinal: {
        'role': 'assistant', 'content': value,
        'reasoning': 'This is reasoning, not a final answer.'},
        native=True)
    result = message(root)
    assert result['status'] == 'FAILED'
    assert result.get('final_answer') != 'This is reasoning, not a final answer.'


@pytest.mark.parametrize('enabled', [False, True])
def test_native_reasoning_transport_is_current_turn_only_and_opt_in(enabled: bool) -> None:
    from milai_lab.providers.chat_bridge import VLLMChatModel
    from milai_lab.providers.contextual_vllm import VLLMClient
    wires = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        return httpx.Response(200, json={'id': 'final', 'choices': [{'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': 'Done.', 'reasoning': 'Not public.'}}]})

    def reasoning_message(identity: str, thought: str) -> AIMessage:
        return AIMessage(content='', additional_kwargs={'reasoning_content': thought},
                         tool_calls=[{'id': identity, 'name': 'lookup', 'args': {}}])

    messages = [HumanMessage(content='Old request.'), reasoning_message('old', 'OLD_THOUGHT'),
        ToolMessage(tool_call_id='old', content='Old result.'),
        HumanMessage(content='New request.'),
        reasoning_message('new', 'CURRENT_THOUGHT'),
        ToolMessage(tool_call_id='new', content='Current result.')]
    with VLLMClient(VLLMConfig(base_url='http://mechanical.invalid/v1/', model='mechanical',
        tool_mode='native'), transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client, preserve_tool_reasoning=enabled)
        answer = model.invoke(messages, tools=[], tool_choice='none')
    assert answer.content == 'Done.' and not answer.additional_kwargs
    thoughts = [m['reasoning_content'] for m in wires[0]['messages'] if 'reasoning_content' in m]
    assert thoughts == (['CURRENT_THOUGHT'] if enabled else [])
    assert messages[1].additional_kwargs['reasoning_content'] == 'OLD_THOUGHT'


@pytest.mark.parametrize('fields', [{'reasoning': ['invalid']},
                                    {'reasoning': 'one', 'reasoning_content': 'another'}])
def test_invalid_reasoning_fields_do_not_dispatch_native_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any],
) -> None:
    root = prepared(tmp_path, native=True, reasoning_history=True)
    wires = scripted(monkeypatch, lambda wire, ordinal: {
        **native_call('search_memory', 'search', query='marker'), **fields}, native=True)
    result = message(root)
    assert result['status'] == 'FAILED' and len(wires) == 1
    assert result['error'] == 'VLLM_CHAT_INVALID_REASONING_HISTORY'
    assert result['world']['receipt_progress'] == {} and result['records'] == []


def test_retained_audit_does_not_block_fresh_safe_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True,
        independent_capabilities=True, current_delivery=True, fresh_completion=True,
        operation_completion=True, phase_thinking=True, reasoning_history=True)
    secret = 'MECHANICAL_RETAINED_AUDIT_ONLY'

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 5, 8}:
            return native_call('classify_current_request', f'mode-{ordinal}',
                memory_write_request='explicit' if ordinal == 1 else 'none',
                allow_forgetting=ordinal == 5,
                business_action_request='none', business_operations=[])
        if ordinal == 2:
            hs = [u['fragment_handle'] for u in materials(wire)['items'] if u['type'] == 'fragment']
            return native_call('save_memory', 'save', content=secret, fragment_handles=hs)
        if ordinal in {3, 4}:
            return {'role': 'assistant', 'content': 'Saved the marker.'}
        if ordinal == 6:
            record = next(u for u in materials(wire)['items'] if u['type'] == 'record')
            return native_call('forget_memory', 'forget', read_handle=record['read_handle'])
        assert secret not in json.dumps(wire)
        if ordinal == 7:
            return {'role': 'assistant', 'content': 'Visibility revoked.'}
        if ordinal == 9:
            return {'role': 'assistant', 'content': 'No available evidence for that marker.'}
        assert ordinal == 10
        return {'role': 'assistant', 'content': None, '_test_finish_reason': 'length'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice')
    stored = functional.message(root, **common, session='s1', message_id='save',
                                content='Remember the marker ' + secret)
    assert stored['status'] == 'COMPLETED'
    forgotten = functional.message(root, **common, session='s2', message_id='forget',
                                    content='Forget the marker and its source.')
    assert forgotten['status'] == 'COMPLETED'
    args = dict(session='s3', message_id='query', content='What marker is available? Do not guess.')
    failed = functional.message(root, **common, **args)
    assert failed['status'] == 'FAILED' and failed['error'] == 'VLLM_CHAT_TRUNCATED'
    assert failed['final_delivery']['status'] == 'available'
    assert failed['generation_calls'] == 3 and len(wires) == 10
    visible = {k: failed[k] for k in ('final_answer', 'messages', 'sources', 'records')}
    assert secret not in json.dumps(visible)
    assert secret in json.dumps(failed['world']['receipt_progress'])
    assert functional.message(root, **common, **args) == failed
    assert len(wires) == 10
    # The original actually exposed answer is still blocked before any HTTP.
    archived = functional.message(root, **common, session='s1', message_id='save',
                                   content='Remember the marker ' + secret)
    assert archived['status'] == 'VISIBILITY_REVOKED' and archived['final_answer'] is None
    assert len(wires) == 10


def test_direct_response_preserves_agent_text_but_keeps_memory_and_business_receipt_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True,
        independent_capabilities=True, current_delivery=True, fresh_completion=True,
        operation_completion=True, phase_thinking=True, reasoning_history=True,
        direct_response=True)
    answer = 'Saved: try short sentences only for this presentation.'
    query_answer = 'The stored limit applies only here.'

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        declaration = ordinal in {1, 5, 8}
        assert wire['temperature'] == (0 if declaration else 1)
        assert wire['chat_template_kwargs']['enable_thinking'] is not declaration
        if declaration:
            return native_call('classify_current_request', f'mode-{ordinal}',
                memory_write_request='explicit' if ordinal == 1 else 'none',
                allow_forgetting=False,
                business_action_request='perform' if ordinal == 8 else 'none',
                business_operations=['reserve_and_label'] if ordinal == 8 else [])
        if ordinal == 2:
            return {'role': 'assistant', 'content': 'Saved without doing anything.'}
        if ordinal == 3:
            hs = [u['fragment_handle'] for u in materials(wire)['items'] if u['type'] == 'fragment']
            return native_call('save_memory', 'save', content='Try short sentences only here.',
                               fragment_handles=hs)
        if ordinal == 4:
            return {'role': 'assistant', 'content': answer}
        if ordinal == 6:
            assert 'save_memory' not in {t['function']['name'] for t in wire['tools']}
            return native_call('get_reservation', 'query-only', item_key='query-only-item')
        if ordinal == 7:
            observation = json.loads(next(message['content'] for message in wire['messages']
                if message.get('tool_call_id') == 'query-only'))
            assert observation['receipt']['status'] == 'not_found'
            assert observation['receipt']['item_key'] == 'query-only-item'
            return {'role': 'assistant', 'content': query_answer}
        if ordinal == 9:
            return native_call('reserve_and_label', 'reserve', item_key='direct-response-item',
                               quantity=1, destination='local', packing='box')
        assert ordinal == 10
        return {'role': 'assistant', 'content': 'DRAFT_FALSE_BUSINESS_NOT_DONE'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice')
    args = dict(session='s1', message_id='save', content='Remember: try short sentences only here.')
    saved = functional.message(root, **common, **args)
    assert saved['status'] == 'COMPLETED' and saved['final_answer'] == answer
    assert saved['operation_status']['semantic_memory']['status'] == 'committed'
    feedback = read_json(next(root.glob('banks/*/*-completion-feedback.json')))
    assert feedback['attempts'] == 1
    assert saved['finalization']['execution_candidate_delivered'] is True
    assert len(wires) == 4 and len(saved['records']) == 1
    assert sum(m.get('content') == answer for m in saved['messages']) == 1
    assert functional.message(root, **common, **args) == saved and len(wires) == 4
    query_args = dict(session='s2', message_id='query', content=(
        'Does the stored limit apply everywhere? Also query query-only-item; do not act or save.'))
    query = functional.message(root, **common, **query_args)
    assert query['status'] == 'COMPLETED' and len(wires) == 7
    assert query['operation_status']['semantic_memory']['status'] == 'not_committed'
    assert not query['operation_status']['business']['operations']
    assert len(query['operation_status']['business']['observations']) == 1
    assert not query['operation_status'].get('application_requests')
    assert query['execution_candidate_answer'] == query_answer
    assert query['final_answer'].startswith(query_answer + '\n\n')
    assert query['final_answer'].count(query_answer) == 1
    assert '未查到对象' in query['final_answer'] and 'query-only-item' in query['final_answer']
    assert '本轮语义记忆' not in query['final_answer']
    assert query['finalization']['protocol'] == 'agent_response_v1'
    assert query['finalization']['execution_candidate_delivered'] is True
    assert query['finalization']['observation_receipts_appended'] is True
    assert query['finalization']['model_generation'] is False
    assert query['records'] == saved['records']
    assert query['world']['world'] == saved['world']['world']
    query_sources = {source['event_id']: source for source in query['sources']}
    assert all(query_sources[source['event_id']] == source for source in saved['sources'])
    replay = functional.message(root, **common, **query_args, resume=True)
    assert len(wires) == 7 and replay['final_answer'] == query['final_answer']
    assert replay['records'] == query['records'] and replay['sources'] == query['sources']
    assert replay['world'] == query['world']
    operated = functional.message(root, **common, session='s3', message_id='reserve',
                                  content='Reserve and label one direct-response-item.')
    assert operated['status'] == 'COMPLETED' and len(wires) == 10
    assert operated['operation_status']['business']['status'] == 'completed'
    assert 'DRAFT_FALSE_BUSINESS_NOT_DONE' not in operated['final_answer']
    assert 'direct-response-item' in operated['final_answer']
    assert operated['finalization']['protocol'] == 'receipt_business_response_v1'


@pytest.mark.parametrize('unusable', [None, '{'])
@pytest.mark.parametrize('actual_capabilities', [False, True])
def test_direct_response_failure_and_answer_only_resume_keep_committed_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unusable: Any, actual_capabilities: bool,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True,
        independent_capabilities=True, current_delivery=True, fresh_completion=True,
        operation_completion=True, phase_thinking=True, reasoning_history=True,
        direct_response=True, actual_capabilities=actual_capabilities)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode', memory_write_request='explicit',
                allow_forgetting=False, business_action_request='none', business_operations=[])
        if ordinal == 2:
            hs = [u['fragment_handle'] for u in materials(wire)['items'] if u['type'] == 'fragment']
            return native_call('save_memory', 'save', content='The marker is blue.',
                               fragment_handles=hs)
        if ordinal == 3:
            return {'role': 'assistant', 'content': unusable, 'reasoning': 'Not an answer.'}
        assert ordinal == 4 and not wire.get('tools') and wire.get('tool_choice') != 'auto'
        if actual_capabilities:
            system = wire['messages'][0]['content']
            assert 'CURRENT EXECUTION CAPABILITIES: []' in system
            assert 'Memory saving/updating is unavailable in this phase.' in system
        return {'role': 'assistant', 'content': 'The marker was saved.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='b', owner='alice', session='s', message_id='save', content='Remember blue.')
    failed = functional.message(root, **args)
    assert failed['status'] == 'FAILED' and failed['final_delivery']['status'] == 'available'
    assert failed['operation_status']['semantic_memory']['status'] == 'committed'
    assert 'Not an answer.' not in failed['final_answer']
    recovered = functional.message(root, **args, resume=True)
    assert recovered['status'] == 'COMPLETED' and len(wires) == 4
    assert recovered['final_answer'] == 'The marker was saved.'
    assert len(recovered['records']) == 1 and recovered['records'][0]['value']['revision'] == 1


def test_actual_capability_contract_tracks_restricted_completion_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, readonly_finalization=True,
        independent_capabilities=True, current_delivery=True, fresh_completion=True,
        operation_completion=True, phase_thinking=True, reasoning_history=True,
        direct_response=True, actual_capabilities=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode', memory_write_request='explicit',
                allow_forgetting=False, business_action_request='perform',
                business_operations=['reserve_and_label'])
        system = wire['messages'][0]['content']
        encoded = system.split('CURRENT EXECUTION CAPABILITIES: ', 1)[1]
        active, _ = json.JSONDecoder().raw_decode(encoded)
        actual = sorted(t['function']['name'] for t in wire['tools'])
        assert active == actual
        assert 'Persisted current-request interpretation:' in system
        assert 'save_memory' in active and 'forget_memory' not in active
        if ordinal == 2:
            assert 'reserve_and_label' in active
            return {'role': 'assistant', 'content': 'WITHHELD_NO_WRITE'}
        assert not set(active) & functional.BUSINESS_MUTATIONS
        if ordinal == 3:
            hs = [u['fragment_handle'] for u in materials(wire)['items'] if u['type'] == 'fragment']
            return native_call('save_memory', 'save', content='Prefer blue paper.',
                               fragment_handles=hs)
        assert ordinal == 4
        return {'role': 'assistant', 'content': 'Preference saved; reservation not executed.'}

    wires = scripted(monkeypatch, reply, native=True)
    result = functional.message(root, bank='b', owner='alice', session='s', message_id='request',
                                content='Remember I prefer blue paper, and reserve one local box.')
    assert result['status'] == 'COMPLETED' and len(wires) == 4
    assert result['request_mode']['allow_business_mutation'] is True
    assert result['operation_status']['business']['status'] == 'not_executed'
    assert result['operation_status']['semantic_memory']['status'] == 'committed'
    assert 'WITHHELD_NO_WRITE' not in result['final_answer']
    assert result['world']['world']['attempts'] == []


def test_replacement_evidence_catalog_commits_new_support_on_original_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, replacement_evidence=True,
                    direct_response=True, phase_thinking=True, actual_capabilities=True,
                    current_delivery=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        packet = materials(wire)
        if ordinal in {1, 3}:
            current = [u['fragment_handle'] for u in packet['items']
                       if u['type'] == 'fragment' and u['input_relation'] == 'current_request']
            if ordinal == 1:
                return native_call('save_memory', 'save',
                                   content='Only the local sample uses unit A.',
                                   fragment_handles=current)
            record = next(u for u in packet['items'] if u['type'] == 'record')
            return native_call('update_memory', 'update',
                               read_handle=record['read_handle'], changes=[{
                'field': 'content', 'op': 'set', 'value': 'Only the local sample uses unit B.',
                'evidence_for_new_value': current}])
        assert actual_tool_receipt(wire)['status'] == 'committed'
        return {'role': 'assistant', 'content': 'The requested memory change is saved.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice', session='s')
    saved = functional.message(root, **common, message_id='initial',
                               content='Remember: only the local sample uses unit A.')
    updated = functional.message(root, **common, message_id='replacement',
                                 content='For that same local sample use unit B instead.')
    assert saved['status'] == updated['status'] == 'COMPLETED'
    assert len(wires) == 4 and len(updated['records']) == 1
    assert updated['records'][0]['id'] == saved['records'][0]['id']
    value = updated['records'][0]['value']
    assert value['revision'] == 2 and value['content'] == 'Only the local sample uses unit B.'
    support = value['functional_support']
    assert support['content']['source_refs'] == [updated['capture']['source_ref']]
    assert support['content']['semantic_support'] == 'unchecked'
    assert support['basis'] == saved['records'][0]['value']['functional_support']['basis']


def test_withdrawal_evidence_catalog_retains_original_and_cancellation_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, withdrawal_evidence=True,
                    direct_response=True, phase_thinking=True, actual_capabilities=True,
                    current_delivery=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        packet = materials(wire)
        if ordinal in {1, 3}:
            current = [u['fragment_handle'] for u in packet['items']
                       if u['type'] == 'fragment' and u['input_relation'] == 'current_request']
            if ordinal == 1:
                return native_call('save_memory', 'save', content='Local sample preference.',
                                   fragment_handles=current)
            schema = next(t['function']['parameters'] for t in wire['tools']
                          if t['function']['name'] == 'update_memory')
            assert 'evidence_for_withdrawal' in schema['properties']
            assert 'fragment_handles' not in schema['properties']
            record = next(u for u in packet['items'] if u['type'] == 'record')
            return native_call('update_memory', 'withdraw',
                               read_handle=record['read_handle'], changes=[], retract=True,
                               evidence_for_withdrawal=current)
        assert actual_tool_receipt(wire)['status'] == 'committed'
        return {'role': 'assistant', 'content': 'The requested operation is committed.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice', session='s')
    saved = functional.message(root, **common, message_id='initial',
                               content='Remember: local sample preference.')
    withdrawn = functional.message(root, **common, message_id='withdrawal',
                                   content='Withdraw that local sample preference.')
    assert saved['status'] == withdrawn['status'] == 'COMPLETED'
    assert len(wires) == 4 and len(withdrawn['records']) == 1
    assert withdrawn['records'][0]['status'] == 'retracted'
    assert not withdrawn['records'][0]['ok']
    import sqlite3

    database = next(root.glob('banks/*/memory.sqlite'))
    with sqlite3.connect(f'file:{database.resolve()}?mode=ro', uri=True) as connection:
        stored = connection.execute('SELECT value FROM store WHERE key=?',
                                    (saved['records'][0]['id'],)).fetchone()
    history = json.loads(stored[0])['_v13_1']['history']
    assert len(history) == 2
    original, version = history
    assert version['retracted'] and version['functional_support'] == original['functional_support']
    assert version['removed_field_support']['record']['source_refs'] == [
        withdrawn['capture']['source_ref']]


@pytest.mark.parametrize("withdraw", [False, True])
def test_revision_review_tool_shows_wrong_source_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, withdraw: bool,
) -> None:
    root = prepared(tmp_path, native=True, reviewed_evidence=True,
                    direct_response=True, phase_thinking=True, actual_capabilities=True,
                    current_delivery=True)
    proposal: dict[str, Any] = {}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        packet = materials(wire)
        current = [u['fragment_handle'] for u in packet['items']
                   if u['type'] == 'fragment' and u['input_relation'] == 'current_request']
        if ordinal == 1:
            return native_call('save_memory', 'save', content='Only this sample uses unit A.',
                               fragment_handles=current)
        if ordinal == 2:
            assert actual_tool_receipt(wire)['status'] == 'committed'
            return {'role': 'assistant', 'content': 'Saved the sample preference.'}
        if ordinal == 3:
            record = next(u for u in packet['items'] if u['type'] == 'record')
            old = next(u['fragment_handle'] for u in packet['items']
                       if u['type'] == 'fragment' and 'unit A' in u['content'])
            proposal.update(read_handle=record['read_handle'], changes=[] if withdraw else [{
                'field': 'content', 'op': 'set', 'value': 'Only this sample uses unit B.',
                'evidence_for_new_value': [old]}])
            if withdraw:
                proposal.update(retract=True, evidence_for_withdrawal=[old])
            return native_call('update_memory', 'wrong-preview', **proposal)
        if ordinal == 4:
            preview = actual_tool_receipt(wire)
            assert preview['status'] == 'revision_review_required'
            assert 'unit A' in preview['proposed_changes'][0]['selected_original_fragments'][0][
                'content']
            assert memory_effects(wire)['confirmed_semantic_commit_count'] == 0
            if withdraw:
                proposal['evidence_for_withdrawal'] = current
            else:
                proposal['changes'][0]['evidence_for_new_value'] = current
            return native_call('update_memory', 'corrected-preview', **proposal)
        if ordinal == 5:
            preview = actual_tool_receipt(wire)
            assert preview['status'] == 'revision_review_required'
            text = preview['proposed_changes'][0]['selected_original_fragments'][0]['content']
            assert ('Withdraw' if withdraw else 'unit B') in text
            assert memory_effects(wire)['confirmed_semantic_commit_count'] == 0
            return native_call('update_memory', 'commit', **proposal,
                               review_token=preview['review_token'])
        assert ordinal == 6 and actual_tool_receipt(wire)['status'] == 'committed'
        return {'role': 'assistant', 'content': 'Committed the requested change.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice', session='s')
    saved = functional.message(root, **common, message_id='initial',
                               content='Remember: only this sample uses unit A.')
    updated = functional.message(root, **common, message_id='correction', content=(
        'Withdraw this sample preference; keep its history.' if withdraw else
        'Change this same sample to unit B, with all limits unchanged.'))
    assert saved['status'] == updated['status'] == 'COMPLETED', updated.get('error')
    assert len(wires) == 6
    assert updated['operation_status']['semantic_memory']['status'] == 'committed'
    assert len(updated['operation_status']['semantic_memory']['operations']) == 1
    previews = updated['operation_status']['semantic_memory']['previews']
    assert len(previews) == 2 and all(p['effect'] == 'none' for p in previews)
    import sqlite3

    database = next(root.glob('banks/*/memory.sqlite'))
    with sqlite3.connect(f'file:{database.resolve()}?mode=ro', uri=True) as connection:
        value = json.loads(connection.execute('SELECT value FROM store WHERE key=?',
            (saved['records'][0]['id'],)).fetchone()[0])['_v13_1']
    assert len(value['history']) == 2 and value['current']['revision'] == 2
    support = (value['current']['removed_field_support']['record'] if withdraw else
               value['current']['functional_support']['content'])
    assert support['source_refs'] == [updated['capture']['source_ref']]
    assert value['current']['retracted'] is withdraw


@pytest.mark.parametrize("withdraw", [False, True])
@pytest.mark.parametrize("distinct", [False, True, "optional"])
def test_evidence_cue_tool_rejects_wrong_handle_without_replacing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, withdraw: bool, distinct: bool | str,
) -> None:
    root = prepared(tmp_path, native=True, anchored_evidence=True,
                    distinct_withdrawal=bool(distinct), optional_withdrawal=distinct == "optional",
                    direct_response=True, phase_thinking=True, actual_capabilities=True,
                    current_delivery=True)
    proposed: dict[str, Any] = {}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        packet = materials(wire)
        current = [u['fragment_handle'] for u in packet['items']
                   if u['type'] == 'fragment' and u['input_relation'] == 'current_request']
        if ordinal == 1:
            return native_call('save_memory', 'save', content='Only this sample uses unit A.',
                               fragment_handles=current)
        if ordinal in {2, 5}:
            assert actual_tool_receipt(wire)['status'] == 'committed'
            return {'role': 'assistant', 'content': 'The requested operation is committed.'}
        cue = 'Withdraw' if withdraw else 'unit B'
        if ordinal == 3:
            record = next(u for u in packet['items'] if u['type'] == 'record')
            old = next(u['fragment_handle'] for u in packet['items']
                       if u['type'] == 'fragment' and 'unit A' in u['content'])
            selected = [{'fragment_handle': old, 'supporting_words':
                         'unit A' if distinct and withdraw else cue}]
            proposed.update(read_handle=record['read_handle'], changes=[] if withdraw else [{
                'field': 'content', 'op': 'set', 'value': 'Only this sample uses unit B.',
                'evidence_for_new_value': selected}])
            if withdraw:
                proposed.update(retract=True, evidence_for_withdrawal=selected)
                if distinct == "optional":
                    proposed.pop('changes')
            return native_call('update_memory', 'wrong-cue', **proposed)
        assert ordinal == 4
        rejected = actual_tool_receipt(wire)
        assert rejected['status'] == 'rejected' and rejected['effect'] == 'none'
        expected_error = ('WITHDRAWAL_REUSES_ONLY_PRIOR_SUPPORT' if distinct and withdraw else
                          'EVIDENCE_CUE_NOT_IN_SELECTED_FRAGMENT')
        assert expected_error in rejected['reason']
        assert memory_effects(wire)['confirmed_semantic_commit_count'] == 0
        selected = [{'fragment_handle': current[0], 'supporting_words': cue}]
        if withdraw:
            proposed['evidence_for_withdrawal'] = selected
        else:
            proposed['changes'][0]['evidence_for_new_value'] = selected
        return native_call('update_memory', 'corrected-cue', **proposed)

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice', session='s')
    saved = functional.message(root, **common, message_id='initial',
                               content='Remember: only this sample uses unit A.')
    updated = functional.message(root, **common, message_id='correction', content=(
        'Withdraw this sample preference; keep its history.' if withdraw else
        'Change this same sample to unit B, with all limits unchanged.'))
    assert saved['status'] == updated['status'] == 'COMPLETED', updated.get('error')
    assert len(wires) == 5
    operations = updated['operation_status']['semantic_memory']['operations']
    assert [o['status'] for o in operations] == ['not_committed', 'committed']
    assert operations[0]['effect'] == 'none' and operations[1]['effect'] == 'memory_only'
    import sqlite3

    database = next(root.glob('banks/*/memory.sqlite'))
    with sqlite3.connect(f'file:{database.resolve()}?mode=ro', uri=True) as connection:
        value = json.loads(connection.execute('SELECT value FROM store WHERE key=?',
            (saved['records'][0]['id'],)).fetchone()[0])['_v13_1']
    assert len(value['history']) == 2 and value['current']['revision'] == 2
    support = (value['current']['removed_field_support']['record'] if withdraw else
               value['current']['functional_support']['content'])
    assert support['source_refs'] == [updated['capture']['source_ref']]
    assert support['semantic_support'] == 'unchecked'


@pytest.mark.parametrize('effect', ['none', 'memory', 'business'])
@pytest.mark.parametrize('new_profile', [False, True])
def test_format_exhaustion_preserves_confirmed_effects_and_delivers_failure_without_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, effect: str, new_profile: bool,
) -> None:
    root = prepared(tmp_path, native=True, fresh_completion=True,
                    format_failure_receipts=new_profile)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1 and effect == 'business':
            return native_call('reserve_and_label', 'actual', item_key='format item',
                               quantity=2, destination='local', packing='box')
        if ordinal == 1 and effect == 'memory':
            hs = [u['fragment_handle'] for u in materials(wire)['items']
                  if u['type'] == 'fragment']
            return native_call('save_memory', 'actual', content='The marker is blue.',
                               fragment_handles=hs)
        return native_call('save_memory', 'missing-content-' + str(ordinal), fragment_handles=[])

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result['status'] == 'FAILED'
    assert result['error'] == 'FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED'
    assert len(wires) == (2 if effect == 'none' else 3)
    assert len(result['records']) == (1 if effect == 'memory' else 0)
    assert len(result['world']['world']['attempts']) == (1 if effect == 'business' else 0)
    assert result['operation_status']['semantic_memory']['status'] == (
        'committed' if effect == 'memory' else 'not_committed')
    assert result['operation_status']['business']['status'] == (
        'completed' if effect == 'business' else 'not_executed')
    if new_profile:
        assert result['final_delivery']['status'] == 'available'
        assert '回答协议失败' in result['final_answer']
        assert result['failure_delivery']['additional_operations'] == 0
        assert result['failure_delivery']['model_generation'] is False
    else:
        assert result.get('final_answer') is None
    for resume in [False, True]:
        replay = message(root, resume=resume)
        assert replay['status'] == 'FAILED' and replay['error'] == result['error']
        assert replay['records'] == result['records']
        assert replay['world'] == result['world']
        assert len(wires) == (2 if effect == 'none' else 3)


def test_visibility_response_keeps_rejected_and_successful_attempts_separate() -> None:
    from milai_lab.runners.functional_response import business_response

    operations = [
        dict(status='not_committed', effect='none', phase='pre_mutation_contract'),
        dict(status='visibility_revoked', effect='visibility_only', scope='record_and_sources',
             scope_counts={'selected_records': 1, 'revoked_sources': 2}),
        dict(status='unknown', effect='unknown'),
    ]
    effects = dict(business=dict(status='not_executed', operations=[], observations=[]),
                   semantic_memory=dict(status='not_committed', operations=[]),
                   visibility=dict(operations=operations), raw_event=dict(status='stored'))
    answer = str(business_response([], effects, {}).content)
    assert '遗忘尝试 1: 未提交' in answer
    assert '遗忘尝试 2: 已按实际回执撤销所选记忆及来源的可见性' in answer
    assert '遗忘尝试 3: 未知' in answer
    assert answer.index('遗忘尝试 1:') < answer.index('遗忘尝试 2:') < answer.index('遗忘尝试 3:')
    assert '尚不能确认请求的全部内容' not in answer
    assert '未选择的独立副本不在本次确认范围内' in answer
    assert '未执行物理擦除' in answer


def test_receipt_response_reports_read_saved_content_without_a_new_write(tmp_path: Path) -> None:
    from milai_lab.memory.functional import FunctionalMemory
    from milai_lab.memory.service import MemoryService
    from milai_lab.runners.functional_response import business_response

    version = 'stored-response-example-v1'

    def config(turn: str) -> dict[str, Any]:
        return {'configurable': {'user_id': 'alice', 'v13_session': 's',
                                'v13_turn_id': turn, 'v13_config_version': version}}

    def source(memory: FunctionalMemory, turn: str, text: str) -> list[str]:
        ref = memory.service.capture_user('s', turn, text)['source_ref']
        memory.context('s', turn, version)
        return [row['fragment_handle'] for row in memory.service.source_fragments(ref)]

    db = str(tmp_path / 'stored-response.sqlite')
    body = '预订已登记; 目的地配置为工作室; 标签已创建。'
    with SqliteStore.from_conn_string(db) as store:
        service = MemoryService(store, ('stored-response', 'alice'), 'alice',
                                tmp_path / 'lock', functional_contract='functional_v1')
        memory = FunctionalMemory(service, len, retrieval_candidates=[])
        handles = source(memory, 'save', '预订已登记; 标签尚未创建。')
        saved = memory.save(config('save'), 'save', '预订已登记; 标签尚未创建。', handles)
        assert saved['ok'] and saved['revision'] == 1
        handles = source(memory, 'update', body)
        revised = memory.update(config('update'), 'update',
            service.read(saved['id'])['candidate_handle'],
            [{'field': 'content', 'op': 'set', 'value': body, 'fragment_handles': handles}])
        assert revised['ok'] and revised['revision'] == 2
        source(memory, 'read', '之前保存了什么内容?')

    with SqliteStore.from_conn_string(db) as store:
        service = MemoryService(store, ('stored-response', 'alice'), 'alice',
                                tmp_path / 'lock', functional_contract='functional_v1')
        memory = FunctionalMemory(service, len, retrieval_candidates=[])
        material = memory.context('s', 'read', version)
        call = {'name': 'read_memory', 'args': {'record_id': saved['id']},
                'id': 'read-saved', 'type': 'tool_call'}
        read_tool = next(tool for tool in memory.tools() if tool.name == 'read_memory')
        receipt = read_tool.invoke(call, config=config('read'))
        packet = json.loads(receipt.content)
        assert packet['ok'] and not packet['semantic_write_performed']
        before = service.read(saved['id'])['value']
        effects = dict(business=dict(status='not_executed', operations=[], observations=[]),
                       semantic_memory=dict(status='not_committed', operations=[]),
                       visibility=dict(operations=[]), raw_event=dict(status='stored'),
                       application_requests=[])
        messages = [AIMessage(content='模型声称已完成全部事项。', tool_calls=[call]), receipt]
        answer = str(business_response(messages, effects, material).content)
        assert '已读取的保存内容 (版本 2): ' + json.dumps(body, ensure_ascii=False) in answer
        assert '本轮语义记忆: 未提交' in answer
        assert '原请求是否已全部完成尚未核对。' in answer
        assert '模型声称' not in answer and saved['id'] not in answer
        assert 'unchecked' not in answer and 'read_memory' not in answer
        assert service.read(saved['id'])['value'] == before
        assert effects['semantic_memory']['operations'] == []
        duplicated = str(business_response(messages, effects, packet).content)
        assert duplicated.count(body) == 1
        context_only = str(business_response([], effects, packet).content)
        assert body in context_only
        unpaired = str(business_response([receipt], effects, material).content)
        assert body not in unpaired
        mismatched = ToolMessage(name='search_memory', tool_call_id='read-saved',
                                 content=receipt.content)
        assert body not in str(business_response(
            [messages[0], mismatched], effects, material).content)
        failed = ToolMessage(name='read_memory', tool_call_id='read-saved',
                            content=receipt.content, status='error')
        assert body not in str(business_response([messages[0], failed], effects, material).content)
        raw = {'items': [{'type': 'fragment', 'content': body}]}
        assert body not in str(business_response([], effects, raw).content)
        bounded = json.loads(receipt.content)
        bounded['items'][0]['content'] = '保存的说明' * 300
        excerpt = str(business_response([], effects, bounded).content)
        assert '引用已截断' in excerpt and bounded['items'][0]['content'] not in excerpt

        # Old permission metadata cannot replace this turn's actual failed attempt.
        attempted = json.loads(json.dumps(effects))
        attempted['semantic_memory']['operations'] = [
            {'tool': 'maintain_event', 'status': 'not_committed', 'effect': 'none'}]
        attempted['application_requests'] = [{
            'business': {'status': 'completed', 'execution': {'status': 'observed_only'}},
            'memory': {'status': 'failed', 'current_permission': 'not_authorized_current_request'},
            'feedback': {'status': 'delivered'},
        }]
        allowed = {'allow_memory_maintenance': True, 'requires_memory_result': True}
        failed_answer = str(business_response([], attempted, packet, current_mode=allowed).content)
        assert '本轮已尝试记忆维护' in failed_answer
        assert '实际结果保存未确认成功; 保存许可当前允许记忆维护' in failed_answer
        assert '当前未获允许' not in failed_answer
        assert '不确认全部请求或语义覆盖' in failed_answer
        assert json.dumps(body, ensure_ascii=False) in failed_answer

        attempted['semantic_memory']['operations'] = []
        unattempted = str(business_response([], attempted, packet, current_mode=allowed).content)
        assert '本轮没有可确认的记忆维护尝试回执' in unattempted
        assert '本轮已尝试记忆维护' not in unattempted
        attempted['application_requests'][0]['memory']['status'] = 'committed'
        readonly = str(business_response([], attempted, packet,
            current_mode={'allow_memory_maintenance': False}).content)
        assert '实际结果保存提交已确认; 保存许可当前未获允许' in readonly
        assert '本轮已尝试记忆维护' not in readonly
        assert service.read(saved['id'])['value'] == before


@pytest.mark.parametrize('required,interrupted', [(False, False), (True, False), (True, True)])
def test_existing_confirmation_uses_one_required_proposal_and_no_new_revision_after_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, required: bool, interrupted: bool,
) -> None:
    root = prepared(tmp_path, native=True, independent_capabilities=True,
        current_delivery=True, operation_completion=True, direct_response=True,
        phase_thinking=True, optional_withdrawal=True, format_failure_receipts=True,
        required_completion=required)
    generate = functional.LangMemRecipeChatModel._generate
    faulted = False

    def interrupt_once(self: Any, messages: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal faulted
        if (interrupted and not faulted and kwargs.get('tool_choice') == 'required'
                and len(kwargs.get('tools', [])) > 1):
            faulted = True
            raise OSError('before_first_completion_generation')
        return generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(functional.LangMemRecipeChatModel, '_generate', interrupt_once)
    confirmation_calls = 7 if required else 6

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 4, confirmation_calls + 1}:
            return native_call('classify_current_request', f'mode-{ordinal}',
                memory_write_request=('none' if ordinal == confirmation_calls + 1
                                      else 'new_assertion'), allow_forgetting=False,
                business_action_request='none', business_operations=[])
        assert wire['temperature'] == 1 and wire['chat_template_kwargs']['enable_thinking']
        if ordinal == confirmation_calls + 2:
            assert wire['tool_choice'] == 'auto'
            assert not {'save_memory', 'update_memory', 'forget_memory'}.intersection(
                t['function']['name'] for t in wire['tools'])
            return {'role': 'assistant', 'content': 'The existing order is author_title.'}
        if ordinal == 2:
            hs = [u['fragment_handle'] for u in materials(wire)['items']
                  if u['type'] == 'fragment']
            return native_call('save_memory', 'save', content='Use author_title for notes.',
                               fragment_handles=hs)
        if ordinal in {3, 5}:
            assert wire['tool_choice'] == 'auto'
            return {'role': 'assistant', 'content': 'The existing record already has that order.'}
        if ordinal == 6:
            assert wire['tool_choice'] == ('required' if required else 'auto')
            assert not functional.BUSINESS_MUTATIONS.intersection(
                t['function']['name'] for t in wire['tools'])
            assert 'forget_memory' not in {t['function']['name'] for t in wire['tools']}
            if not required:
                return {'role': 'assistant', 'content': 'Keep the existing record unchanged.'}
            record = next(u for u in materials(wire)['items'] if u['type'] == 'record')
            return native_call('update_memory', 'confirm-existing',
                               read_handle=record['read_handle'], changes=[])
        assert ordinal == 7 and wire['tool_choice'] == 'auto'
        assert actual_tool_receipt(wire)['status'] == 'no_change'
        return {'role': 'assistant',
                'content': 'Already present; original ID and version unchanged.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice')
    saved = functional.message(root, **common, session='s1', message_id='save',
                                content='Remember: use author_title for notes.')
    args = dict(session='s2', message_id='confirm',
                content='Confirm the same order; if it matches, keep the original ID and version.')
    result = functional.message(root, **common, **args)
    if interrupted:
        assert result['status'] == 'UNKNOWN' and faulted and len(wires) == 5
        assert result['error_type'] == 'OSError'
        assert result['records'] == saved['records']
        result = functional.message(root, **common, **args, resume=True)
    assert result['status'] == ('COMPLETED' if required else 'FAILED'), result.get('error')
    assert result['records'] == saved['records'] and len(wires) == (7 if required else 6)
    assert result['operation_status']['semantic_memory']['status'] == (
        'no_change' if required else 'not_committed')
    if required:
        receipt = result['operation_status']['semantic_memory']['operations'][0]
        assert receipt['revision'] == 1 and receipt['effect'] == 'none'
    feedback = read_json(next(root.glob('banks/*/*-completion-feedback.json')))
    assert feedback['attempts'] == 1 and not feedback['business_mutations_available']
    cached = functional.message(root, **common, **args)
    assert cached['final_answer'] == result['final_answer'] and len(wires) == (7 if required else 6)
    query = functional.message(root, **common, session='s3', message_id='query',
                                content='What order is currently recorded? Just read it.')
    assert query['status'] == 'COMPLETED' and query['records'] == saved['records']
    assert query['operation_status']['semantic_memory']['status'] == 'not_committed'
    assert len(wires) == confirmation_calls + 2
    import sqlite3

    database = next(root.glob('banks/*/memory.sqlite'))
    with sqlite3.connect(f'file:{database.resolve()}?mode=ro', uri=True) as connection:
        state = json.loads(connection.execute('SELECT value FROM store WHERE key=?',
            (saved['records'][0]['id'],)).fetchone()[0])['_v13_1']
    assert len(state['history']) == 1 and state['current']['revision'] == 1


def test_required_completion_cannot_repeat_business_and_exhausted_format_stays_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, independent_capabilities=True,
        current_delivery=True, operation_completion=True, direct_response=True,
        phase_thinking=True, optional_withdrawal=True, format_failure_receipts=True,
        required_completion=True)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode',
                memory_write_request='explicit', allow_forgetting=False,
                business_action_request='perform', business_operations=['reserve_and_label'])
        if ordinal == 2:
            return native_call('reserve_and_label', 'actual', item_key='bounded item',
                               quantity=1, destination='local', packing='box')
        if ordinal == 3:
            return {'role': 'assistant', 'content': 'Saved everything. FALSE_DRAFT_WITHHELD'}
        assert ordinal == 4 and wire['tool_choice'] == 'required'
        assert not functional.BUSINESS_MUTATIONS.intersection(
            t['function']['name'] for t in wire['tools'])
        assert 'FALSE_DRAFT_WITHHELD' not in json.dumps(wire)
        return native_call('save_memory', 'invalid', fragment_handles=[])

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result['status'] == 'FAILED'
    assert result['error'] == 'FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED'
    assert result['operation_status']['semantic_memory']['status'] == 'not_committed'
    assert result['operation_status']['business']['status'] == 'completed'
    assert len(result['world']['world']['attempts']) == 1
    assert 'FALSE_DRAFT_WITHHELD' not in result['final_answer']
    assert result['failure_delivery']['additional_operations'] == 0
    replay = message(root, resume=True)
    assert replay['status'] == 'FAILED' and len(wires) == 4
    assert replay['world'] == result['world']


@pytest.mark.parametrize('until_attempt,interrupted,explicit_confirmation',
                         [(False, False, False), (True, False, False), (True, True, False),
                          (True, False, True), (True, True, True)])
def test_completion_read_does_not_replace_existing_confirmation_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    until_attempt: bool, interrupted: bool,
    explicit_confirmation: bool,
) -> None:
    root = prepared(tmp_path, native=True, independent_capabilities=True,
        current_delivery=True, operation_completion=True, direct_response=True,
        phase_thinking=True, optional_withdrawal=True, format_failure_receipts=True,
        required_completion=True, receipt_completion=until_attempt,
        existing_confirmation=explicit_confirmation)
    generate = functional.LangMemRecipeChatModel._generate
    faulted = False

    def interrupt_after_read(self: Any, messages: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal faulted
        if interrupted and not faulted and len(wires) == 6:
            assert kwargs.get('tool_choice') == 'required'
            faulted = True
            raise OSError('after_prerequisite_read_before_confirmation')
        return generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(functional.LangMemRecipeChatModel, '_generate', interrupt_after_read)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if explicit_confirmation and ordinal == 9:
            return native_call('classify_current_request', 'query-mode',
                memory_write_request='none', allow_forgetting=False,
                business_action_request='none', business_operations=[])
        if explicit_confirmation and ordinal == 10:
            assert wire['tool_choice'] == 'auto'
            assert not {'save_memory', 'update_memory', 'confirm_existing_memory',
                        'forget_memory'}.intersection(t['function']['name'] for t in wire['tools'])
            return {'role': 'assistant', 'content': 'The existing order is author_title.'}
        if ordinal in {1, 4}:
            return native_call('classify_current_request', f'mode-{ordinal}',
                memory_write_request='new_assertion', allow_forgetting=False,
                business_action_request='none', business_operations=[])
        if ordinal == 2:
            hs = [u['fragment_handle'] for u in materials(wire)['items']
                  if u['type'] == 'fragment']
            return native_call('save_memory', 'save', content='Use author_title for notes.',
                               fragment_handles=hs)
        if ordinal in {3, 5}:
            assert wire['tool_choice'] == 'auto'
            return {'role': 'assistant', 'content': 'The current order is author_title.'}
        assert not functional.BUSINESS_MUTATIONS.intersection(
            t['function']['name'] for t in wire['tools'])
        assert 'forget_memory' not in {t['function']['name'] for t in wire['tools']}
        if ordinal == 6:
            assert wire['tool_choice'] == 'required'
            record = next(u for u in materials(wire)['items'] if u['type'] == 'record')
            return native_call('read_memory', 'prerequisite-read', record_id=record['record_id'])
        if ordinal == 7:
            assert wire['tool_choice'] == ('required' if until_attempt else 'auto')
            assert not memory_effects(wire)['mutation_receipts']
            if not until_attempt:
                return {'role': 'assistant', 'content': 'The record already matches.'}
            record = next(u for u in actual_tool_receipt(wire)['items']
                          if u['type'] == 'record')
            if explicit_confirmation:
                return native_call('confirm_existing_memory', 'confirm-existing',
                                   read_handle=record['read_handle'])
            return native_call('update_memory', 'confirm-existing',
                               read_handle=record['read_handle'], changes=[])
        assert ordinal == 8 and wire['tool_choice'] == 'auto'
        assert actual_tool_receipt(wire)['status'] == 'no_change'
        return {'role': 'assistant', 'content': 'Already present; ID and version unchanged.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice')
    saved = functional.message(root, **common, session='s1', message_id='save',
                                content='Remember: use author_title for notes.')
    args = dict(session='s2', message_id='confirm',
                content='Confirm the same order; keep the original ID and version if it matches.')
    result = functional.message(root, **common, **args)
    if interrupted:
        assert faulted and result['status'] == 'UNKNOWN' and len(wires) == 6
        result = functional.message(root, **common, **args, resume=True)
    assert result['status'] == ('COMPLETED' if until_attempt else 'FAILED'), result.get('error')
    assert result['records'] == saved['records']
    assert result['operation_status']['semantic_memory']['status'] == (
        'no_change' if until_attempt else 'not_committed')
    if explicit_confirmation:
        operation = result['operation_status']['semantic_memory']['operations'][0]
        assert operation['tool'] == 'confirm_existing_memory' and operation['effect'] == 'none'
        assert operation['revision'] == 1
    count = len(wires)
    assert count == (8 if until_attempt else 7)
    cached = functional.message(root, **common, **args)
    assert cached['final_answer'] == result['final_answer'] and len(wires) == count
    reads = [call for row in result['messages'] for call in row.get('tool_calls', [])
             if call['name'] == 'read_memory']
    assert len(reads) == 1
    feedback = read_json(next(root.glob('banks/*/*-completion-feedback.json')))
    assert feedback['attempts'] == 1 and not feedback['business_mutations_available']
    if explicit_confirmation:
        query = functional.message(root, **common, session='s3', message_id='query',
                                    content='Read the current order; do not maintain anything.')
        assert query['status'] == 'COMPLETED' and query['records'] == saved['records']
        assert query['operation_status']['semantic_memory']['status'] == 'not_committed'
        assert len(wires) == 10


@pytest.mark.parametrize(('exhaust_reads', 'read_tool'), [
    (False, 'search_memory'), (True, 'search_memory'), (True, 'read_page')])
def test_completion_attempt_requirement_releases_on_rejection_or_stops_at_read_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exhaust_reads: bool,
    read_tool: str,
) -> None:
    root = prepared(tmp_path, native=True, independent_capabilities=True,
        current_delivery=True, operation_completion=True, direct_response=True,
        phase_thinking=True, optional_withdrawal=True, format_failure_receipts=True,
        receipt_completion=True, receipt_response=True, explicit_reads=read_tool == "read_page")

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode',
                memory_write_request='explicit', allow_forgetting=False,
                business_action_request='perform', business_operations=['reserve_and_label'])
        if ordinal == 2:
            return native_call('reserve_and_label', 'actual', item_key='bounded item',
                               quantity=1, destination='local', packing='box')
        if ordinal == 3:
            return {'role': 'assistant', 'content': 'Saved it. WITHHELD_UNTRUE_DRAFT'}
        assert not functional.BUSINESS_MUTATIONS.intersection(
            t['function']['name'] for t in wire['tools'])
        if not exhaust_reads and ordinal == 5:
            assert wire['tool_choice'] == 'auto'
            assert memory_effects(wire)['mutation_receipts'][0]['status'] == 'rejected'
            return {'role': 'assistant', 'content': 'The update was rejected; it was not saved.'}
        assert wire['tool_choice'] == 'required'
        assert not memory_effects(wire)['mutation_receipts']
        if exhaust_reads:
            return native_call(read_tool, f'read-{ordinal}',
                **({'query': 'bounded item'} if read_tool == 'search_memory'
                   else {'cursor': 'unknown:1'}))
        return native_call('update_memory', 'rejected', read_handle='not-issued', changes=[])

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert len(result['world']['world']['attempts']) == 1
    assert result['operation_status']['business']['status'] == 'completed'
    assert not result['records'] and 'WITHHELD_UNTRUE_DRAFT' not in result['final_answer']
    if exhaust_reads:
        assert result['status'] == 'FAILED' and len(wires) == 7
        assert result['execution_stop']['reason'] == 'read_limit_exhausted'
    else:
        assert result['status'] == 'COMPLETED' and len(wires) == 5
        assert result['operation_status']['semantic_memory']['status'] == 'not_committed'
        operation = result['operation_status']['semantic_memory']['operations'][0]
        assert operation['effect'] == 'none' and operation['phase'] == 'pre_mutation_contract'
    before = len(wires)
    replay = message(root, resume=True)
    assert replay['world'] == result['world'] and len(wires) == before
    assert replay['final_answer'] == result['final_answer']


def test_read_exhaustion_answers_from_delivery_and_preserves_business_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(
        tmp_path, native=True, independent_capabilities=True,
        current_delivery=True, operation_completion=True, direct_response=True,
        phase_thinking=True, actual_capabilities=True,
        read_exhaustion="answer_from_delivered_v1",
    )

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 4}:
            return native_call(
                "classify_current_request", f"mode-{ordinal}",
                memory_write_request="none", allow_forgetting=False,
                business_action_request="perform" if ordinal == 1 else "none",
                business_operations=["reserve_and_label"] if ordinal == 1 else [],
            )
        if ordinal == 2:
            return native_call(
                "reserve_and_label", "reserve", item_key="delivered item",
                quantity=1, destination="local", packing="box",
            )
        if ordinal == 3:
            return {"role": "assistant", "content": "The reservation and label are complete."}
        if ordinal < 9:
            return native_call("search_memory", f"read-{ordinal}", query="delivered item")
        assert ordinal == 9 and wire["tool_choice"] == "auto"
        assert not {
            "search_memory", "read_memory", "read_page", "read_source", "read_history",
        }.intersection(
            tool["function"]["name"] for tool in wire.get("tools", [])
        )
        assert "already delivered" in json.dumps(wire["messages"])
        return {"role": "assistant", "content": "The prior receipt confirms the reservation. "
                "There is no evidence here for a middle name."}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank="b", owner="alice", session="s")
    first = functional.message(
        root, **common, message_id="reserve", content="Reserve and label the delivered item.",
    )
    result = functional.message(
        root, **common, message_id="read", content="Read the prior receipt and my middle name.",
    )
    assert first["status"] == result["status"] == "COMPLETED", result.get("error")
    assert len(wires) == 9 and "execution_stop" not in result
    assert result["read_completion"]["next_step"] == "answer_from_delivered_material"
    assert len(result["world"]["world"]["attempts"]) == 1
    assert result["records"] == []
    assert "no evidence" in result["final_answer"]


def test_selected_original_review_rejects_old_support_before_commit_then_uses_new_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, optional_withdrawal=True,
        direct_response=True, phase_thinking=True, actual_capabilities=True,
        current_delivery=True, support_review=True, catalog_feedback=True)
    proposal: dict[str, Any] = {}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {4, 6}:
            assert [t['function']['name'] for t in wire['tools']] == ['review_revision_support']
            assert wire['temperature'] == 0 and wire['tool_choice'] == 'required'
            assert wire['chat_template_kwargs']['enable_thinking'] is False
            evidence = json.loads(next(m['content'] for m in wire['messages']
                                       if m['role'] == 'user'))
            assert len(evidence['changes']) == 1
            change = evidence['changes'][0]
            assert change['field'] == 'content' and 'unit B' in change['after']
            assert 'unit A' in change['before']
            quotes = change['selected_original_fragments']
            assert len(quotes) == 1 and quotes[0]['source_role'] == 'user'
            assert ('unit A' if ordinal == 4 else 'unit B') in quotes[0]['content']
            if ordinal == 4:
                assert 'unit B' not in quotes[0]['content']
            return native_call('review_revision_support', f'assess-{ordinal}', field_results=[{
                'field': 'content', 'assessment': 'unsupported' if ordinal == 4 else 'supported',
                'reason': 'Old-source refusal.' if ordinal == 4 else 'Selected correction.',
            }])
        packet = materials(wire)
        current = [u for u in packet['items']
                   if u['type'] == 'fragment' and u['input_relation'] == 'current_request']
        if ordinal == 1:
            return native_call('save_memory', 'save', content='Only this sample uses unit A.',
                               fragment_handles=[u['fragment_handle'] for u in current])
        if ordinal == 3:
            old = next(u for u in packet['items']
                       if u['type'] == 'fragment' and 'unit A' in u['content'])
            record = next(u for u in packet['items'] if u['type'] == 'record')
            proposal.update(read_handle=record['read_handle'], changes=[{
                'field': 'content', 'op': 'set', 'value': 'Only this sample uses unit B.',
                'evidence_for_new_value': [{'fragment_handle': old['fragment_handle'],
                                            'supporting_words': 'unit A'}]}])
            return native_call('update_memory', 'wrong-source', **proposal)
        if ordinal == 5:
            rejected = actual_tool_receipt(wire)
            assert rejected['status'] == 'rejected' and rejected['effect'] == 'none'
            assert 'REVISION_SUPPORT_REVIEW_REJECTED' in rejected['reason']
            assert memory_effects(wire)['confirmed_semantic_commit_count'] == 0
            proposal['changes'][0]['evidence_for_new_value'] = [
                {'fragment_handle': current[0]['fragment_handle'], 'supporting_words': 'unit B'}]
            return native_call('update_memory', 'correct-source', **proposal)
        assert ordinal in {2, 7}
        assert actual_tool_receipt(wire)['status'] == 'committed'
        return {'role': 'assistant', 'content': 'The requested change is saved.'}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice', session='s')
    saved = functional.message(root, **common, message_id='initial',
                               content='Remember: only this sample uses unit A.')
    args = dict(message_id='correct', content='For that same sample use unit B instead.')
    revised = functional.message(root, **common, **args)
    assert saved['status'] == revised['status'] == 'COMPLETED'
    assert len(wires) == 7 and revised['generation_calls'] == 5
    record = revised['records'][0]
    assert len(revised['records']) == 1 and record['id'] == saved['records'][0]['id']
    assert record['value']['revision'] == 2
    assert record['value']['functional_support']['content']['source_refs'] == [
        revised['capture']['source_ref']]
    assert record['value']['functional_support']['content']['semantic_support'] == 'unchecked'
    reviews = [read_json(p) for p in root.glob('banks/*/*-revision-review-*.json')]
    assert len(reviews) == 2 and all(r['attempts'] == 1 for r in reviews)
    assert functional.message(root, **common, **args) == revised and len(wires) == 7
    ledger = read_json(tmp_path / 'isolated-mechanical-budget.json')
    assert ledger['generation_requests'] == 7


def test_fixed_proposal_probe_preserves_ledger_and_excludes_source_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    path = functional.LAB / 'tools/post_r52_review_probe.py'
    spec = importlib.util.spec_from_file_location('post_r52_review_probe', path)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    prepared(tmp_path, native=True, current_delivery=True, phase_thinking=True,
             direct_response=True, queue_requests=100)
    inputs, labels = tmp_path / 'inputs.json', tmp_path / 'labels.json'
    cases = [{'id': f'm{i}-proposal-{j}', 'matter_id': f'm{i}',
              'stage': 'formation' if i % 2 else 'revision',
              'evidence': {'binding': {'owner': 'synthetic'}, 'forget_epoch': 0,
                           'schema': 'functional_formation_evidence_v1' if i % 2
                           else 'functional_revision_evidence_v1',
                           'record_id': None if i % 2 else f'synthetic-record-{i}',
                           'changes': [{'field': 'content', 'before': None,
                               'after': f'Proposal {j}', 'selected_original_fragments': [
                                   {'source_role': 'user',
                                    'content': 'Only this synthetic trial.'}]}]}}
             for i in range(12) for j in range(2)]
    write_json(inputs, {'schema': 'post_r52_x1_inputs_v1', 'cases': cases})
    write_json(labels, {'evaluator_only': 'DO_NOT_DELIVER_SOURCE_LABELS'})

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        assert 'DO_NOT_DELIVER_SOURCE_LABELS' not in json.dumps(wire)
        assert wire['chat_template_kwargs']['enable_thinking'] is False
        assert wire['temperature'] == 0
        if ordinal == 2:
            return {'role': 'assistant', 'content': ''}
        function = wire['tools'][0]['function']
        props = function['parameters']['properties']['field_results']['items']['properties']
        row = {'field': 'content', 'assessment': 'supported', 'reason': 'Scripted structure only.',
               'unsupported_differences': []}
        if 'source_limits' in props:
            row.update(source_limits='Only this trial.', proposed_limits='Only this trial.')
        return native_call(function['name'], f'review-{ordinal}', field_results=[row])

    wires = scripted(monkeypatch, reply, native=True)
    monkeypatch.setattr(probe, 'FunctionalVLLMClient', functional.FunctionalVLLMClient)
    root = tmp_path / 'fixed-proposal-probe'
    freeze = probe.prepare_probe(root, tmp_path / 'settings.json', inputs, labels)
    assert freeze['review_conditions'] == 48 and not freeze['business_store_connected']
    assert 'sha256' not in json.dumps(freeze)
    assert len({request['request_id'] for request in freeze['review_requests']}) == 48
    results = probe.run_probe(root)
    assert len(results) == len(wires) == 48
    assert sum(r['operational_status'] == 'review_unavailable' for r in results) == 1
    assert all(r['calls_in_condition'] == 1 for r in results)
    assert not list(root.rglob('*.sqlite'))
    assert probe.run_probe(root) == results and len(wires) == 48
    assert read_json(tmp_path / 'isolated-mechanical-budget.json')['generation_requests'] == 48
    write_json(labels, {'evaluator_only': 'changed'})
    with pytest.raises(ValueError, match='SOURCE_LABELS_CHANGED'):
        probe.run_probe(root)
    assert len(wires) == 48
    cases[0]['stage'] = 'formation'
    write_json(inputs, {'schema': 'post_r52_x1_inputs_v1', 'cases': cases})
    with pytest.raises(ValueError, match='STAGE_DOES_NOT_MATCH'):
        probe.prepare_probe(tmp_path / 'invalid-stage', tmp_path / 'settings.json', inputs, labels)


def test_support_working_view_uses_actual_agent_read_then_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, current_delivery=True, explicit_reads=True,
                    support_input=True, request_interpretation=True)
    request = 'Remember: planned three visits per week; start week is unknown.'
    selected: list[str] = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode',
                allow_memory_maintenance=True, allow_forgetting=False,
                allow_business_mutation=False, requires_memory_result=True)
        if ordinal == 2:
            selected.extend(r['fragment_handle'] for r in materials(wire)['items']
                            if r['type'] == 'fragment' and r['content'] == request)
            assert len(selected) == 1
            catalog = {t['function']['name']: t['function'] for t in wire['tools']}
            assert 'read_support_context' in catalog
            assert 'read_handle' in catalog['read_support_context']['parameters']['properties']
            return native_call('read_support_context', 'working-view', fragment_handles=selected)
        if ordinal == 3:
            receipt = actual_tool_receipt(wire)
            assert receipt['operation_effect'] == 'read_only'
            assert receipt['semantic_write_performed'] is False
            assert any(r.get('content') == request for r in receipt['items'])
            assert memory_effects(wire)['confirmed_semantic_commit_count'] == 0
            return native_call('save_memory', 'save', content=request, fragment_handles=selected)
        if ordinal == 4:
            assert actual_tool_receipt(wire)['status'] == 'committed'
            assert memory_effects(wire)['confirmed_semantic_commit_count'] == 1
        else:
            assert ordinal == 5 and not wire.get('tools')
        return {'role': 'assistant', 'content': 'Saved the plan, with start week unknown.'}

    wires = scripted(monkeypatch, reply, native=True)
    final = functional.message(root, bank='view', owner='alice', session='s',
                               message_id='m', content=request)
    assert final['status'] == 'COMPLETED', final
    assert len(final['records']) == 1 and final['records'][0]['value']['content'] == request
    assert final['generation_calls'] == len(wires) == 5
    assert not final['world']['world']['attempts']


def test_bounded_reproposal_actual_agent_stops_before_third_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path, native=True, current_delivery=True, request_interpretation=True,
                    support_review=True, formation_review=True, bounded_reproposal=True,
                    support_contract='single_verdict_v1')
    request = 'Remember: only this trial uses unit A, with the start date undecided.'
    selected: list[str] = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode',
                allow_memory_maintenance=True, allow_forgetting=False,
                allow_business_mutation=False, requires_memory_result=True)
        if ordinal == 2:
            selected.extend(r['fragment_handle'] for r in materials(wire)['items']
                            if r['type'] == 'fragment' and r['content'] == request)
        if ordinal in {3, 5}:
            assert wire['tools'][0]['function']['name'] == 'review_formation_support'
            return native_call('review_formation_support', f'review-{ordinal}', field_results=[{
                'field': 'content', 'assessment': 'unsupported',
                'reason': 'Scripted objection to omitted conditions.',
                'unsupported_differences': ['Trial scope and start date are missing.']}])
        if ordinal in {2, 4, 6}:
            if ordinal != 2:
                assert actual_tool_receipt(wire)['review_status'] == 'review_declined'
            return native_call('save_memory', f'proposal-{ordinal}',
                content={2: 'Use unit A.', 4: 'Unit A is used.', 6: 'The unit is A.'}[ordinal],
                fragment_handles=selected)
        assert ordinal == 7
        receipt = actual_tool_receipt(wire)
        assert receipt['maintenance']['proposals_used'] == 2 and receipt['effect'] == 'none'
        return {'role': 'assistant', 'content': 'The semantic memory remains pending.'}

    wires = scripted(monkeypatch, reply, native=True)
    final = functional.message(root, bank='limit', owner='alice', session='s',
                               message_id='m', content=request)
    assert final['status'] == 'COMPLETED', final
    assert final['records'] == [] and final['generation_calls'] == len(wires) == 7
    reviews = {path: read_json(path) for path in root.glob('banks/*/*-formation-review-*.json')}
    assert len(reviews) == 2
    assert not final['world']['world']['attempts']
    assert final['operation_status']['semantic_memory']['status'] == 'not_committed'
    assert final['operation_status']['request_completion'] == 'unchecked'
    assert final['finalization']['status'] == 'response_rendered'
    assert not final['finalization']['model_generation']
    assert not final['finalization']['execution_candidate_delivered']
    assert '本轮语义记忆: 未提交。' in final['final_answer']
    assert '本轮已尝试记忆维护' in final['final_answer']
    assert '本轮业务结果' not in final['final_answer']
    assert [s['content'] for s in final['sources'] if s['role'] == 'user'] == [request]
    replay = functional.message(root, bank='limit', owner='alice', session='s',
                                message_id='m', content=request, resume=True)
    assert replay['records'] == [] and len(wires) == 7
    assert replay['world'] == final['world']
    assert {path: read_json(path) for path in reviews} == reviews


@pytest.mark.parametrize('kind', ['formation', 'revision'])
@pytest.mark.parametrize(('assessment', 'differences', 'expected'), [
    ('supported', [], 'review_supported'),
    ('unsupported', ['The start date remains unknown.'], 'review_declined'),
    ('uncertain', ['No selected evidence establishes the start date.'], 'review_uncertain'),
    ('supported', ['The start date remains unknown.'], 'review_inconsistent'),
    ('unsupported', [], 'review_inconsistent'),
    ('uncertain', [], 'review_inconsistent'),
])
def test_single_verdict_preserves_objections_and_reopens_without_reinterpreting(
    tmp_path: Path, kind: str, assessment: str, differences: list[str], expected: str,
) -> None:
    from milai_lab.memory.functional_state import FunctionalReviewRejection

    evidence = {'binding': {'owner': 'alice', 'message': 'm'}, 'forget_epoch': 0,
                'changes': [{'field': 'content', 'before': 'Twice weekly.',
                    'after': 'Three times weekly; start week undecided.',
                    'selected_original_fragments': [{'content': 'Start week is undecided.'}]}]}
    decision = {'field_results': [{'field': 'content', 'assessment': assessment,
        'reason': 'A scripted diagnostic, not a semantic gold judgment.',
        'unsupported_differences': differences}]}
    calls: list[Any] = []
    events: list[Any] = []

    class Model:
        def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:
            calls.append(messages)
            assert json.loads(messages[-1].content) == evidence
            fields = kwargs['tools'][0]['function']['parameters']['properties'][
                'field_results']['items']['properties']
            assert set(fields) == {'field', 'assessment', 'reason', 'unsupported_differences'}
            return AIMessage(content='', tool_calls=[{'name': f'review_{kind}_support',
                'id': 'review', 'args': decision}])

    review = getattr(functional, f'review_{kind}_support')
    path = tmp_path / 'review.json'
    for _ in range(2):
        if expected == 'review_supported':
            review(Model(), path, evidence, events.append, contract='single_verdict_v1')
        else:
            with pytest.raises(FunctionalReviewRejection) as exc:
                review(Model(), path, evidence, events.append, contract='single_verdict_v1')
            assert exc.value.review_status == expected
    assert len(calls) == 1 and len(events) == 2
    state = read_json(path)
    assert state['review_status'] == expected and state['decision'] == decision
    assert state['attempts'] == 1
    assert all(e['review_status'] == expected and e['semantic_support'] == 'unchecked'
               for e in events)
    with pytest.raises(functional.FunctionalIntegrityError, match='BINDING_CHANGED'):
        review(Model(), path, evidence, events.append, comparison=True)
    with pytest.raises(functional.FunctionalIntegrityError, match='BINDING_CHANGED'):
        review(Model(), path, {**evidence, 'forget_epoch': 1}, events.append,
               contract='single_verdict_v1')
    state['review_status'] = 'forged'
    write_json(path, state)
    with pytest.raises(functional.FunctionalIntegrityError, match='STATUS_CHANGED'):
        review(Model(), path, evidence, events.append, contract='single_verdict_v1')
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['formation', 'revision'])
@pytest.mark.parametrize('failure', ['length', 'empty', 'malformed', 'budget'])
def test_single_verdict_unavailable_is_not_a_semantic_rejection_or_automatic_retry(
    tmp_path: Path, kind: str, failure: str,
) -> None:
    from milai_lab.memory.functional_state import FunctionalReviewRejection

    evidence = {'binding': {'owner': 'alice'}, 'forget_epoch': 0,
                'changes': [{'field': 'content'}]}
    calls: list[bool] = []

    class Model:
        def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:
            calls.append(True)
            if failure == 'budget':
                raise functional.BudgetExceeded('SCRIPTED_REVIEW_ADMISSION_EXHAUSTED')
            if failure == 'length':
                raise functional.IncompleteChatResponse('VLLM_CHAT_TRUNCATED')
            if failure == 'empty':
                return AIMessage(content='')
            return AIMessage(content='', tool_calls=[{'name': f'review_{kind}_support',
                'id': 'malformed', 'args': {'field_results': [{'field': 'content',
                    'assessment': 'supported', 'reason': 'Missing differences array.'}]}}])

    path = tmp_path / 'unavailable.json'
    review = getattr(functional, f'review_{kind}_support')
    for _ in range(2):
        with pytest.raises(FunctionalReviewRejection) as exc:
            review(Model(), path, evidence, lambda event: None, contract='single_verdict_v1')
        assert exc.value.review_status == 'review_unavailable'
        if failure == 'budget':
            assert exc.value.failure_type == 'BudgetExceeded'
    state = read_json(path)
    assert state['attempts'] == 1 and state['review_status'] == 'review_unavailable'
    assert 'decision' not in state and len(calls) == 1
    assert state['failure_type'] == ('BudgetExceeded' if failure == 'budget' else
                                    'IncompleteChatResponse' if failure == 'length'
                                    else 'schema_invalid')


@pytest.mark.parametrize('outcome', ['inconsistent', 'unavailable', 'supported'])
def test_single_verdict_real_save_reports_status_and_commits_only_with_review_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    root = prepared(tmp_path, native=True, current_delivery=True, formation_review=True,
                    support_contract='single_verdict_v1', anchored_evidence=True,
                    request_interpretation=True)
    request = 'Remember: this is a planned change to three visits weekly; start week is undecided.'

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode',
                allow_memory_maintenance=True, allow_forgetting=False,
                allow_business_mutation=False, requires_memory_result=True)
        if ordinal == 2:
            handles = [r['fragment_handle'] for r in materials(wire)['items']
                       if r['type'] == 'fragment' and r['content'] == request]
            return native_call('save_memory', 'proposal', content=request,
                               fragment_handles=handles)
        if ordinal == 3:
            assert wire['tools'][0]['function']['name'] == 'review_formation_support'
            if outcome == 'unavailable':
                return {'role': 'assistant', 'content': ''}
            return native_call('review_formation_support', 'review', field_results=[{
                'field': 'content', 'assessment': 'supported', 'reason': 'Scripted review.',
                'unsupported_differences': ['A blocking objection.']
                if outcome == 'inconsistent' else []}])
        if ordinal == 5:
            assert not wire.get('tools')
            return {'role': 'assistant', 'content': 'The receipt confirms saving.'
                    if outcome == 'supported' else 'Semantic memory remains pending.'}
        assert ordinal == 4
        receipt = actual_tool_receipt(wire)
        if outcome != 'supported':
            assert receipt['status'] == 'rejected' and receipt['effect'] == 'none'
            assert receipt['formation_status'] == 'pending'
            assert receipt['phase'] == 'precommit_support_review'
            assert receipt['review_status'] == 'review_' + outcome
        else:
            assert receipt['status'] == 'committed'
        return {'role': 'assistant', 'content': 'Saved.' if outcome == 'supported'
                else 'The original event is retained; semantic memory is still pending.'}

    scripted(monkeypatch, reply, native=True)
    final = functional.message(root, bank='review-bank', owner='alice', session='s',
                               message_id='m', content=request)
    assert final['status'] == 'COMPLETED', final
    assert len(final['records']) == int(outcome == 'supported')
    assert final['capture']['ok']
    assert not final['world']['world']['attempts']


@pytest.mark.parametrize('assessment', ['supported', 'unsupported', 'uncertain'])
@pytest.mark.parametrize('review_kind', ['revision', 'formation'])
@pytest.mark.parametrize('comparison', [False, True])
def test_support_review_cache_is_bound_and_reopen_does_not_regenerate(
    tmp_path: Path, assessment: str, review_kind: str, comparison: bool,
) -> None:
    from milai_lab.memory.functional_state import FunctionalIntegrityError, FunctionalRejection

    evidence = {'proposal_id': 'synthetic-proposal-v1', 'changes': [{'field': 'content'}],
                'binding': {'owner': 'alice', 'message': 'm'},
                'forget_epoch': 0}
    calls: list[Any] = []
    events: list[Any] = []
    review = getattr(functional, f'review_{review_kind}_support')
    detail = {'source_limits': 'Only the stated occasion.',
              'proposed_limits': 'Only the stated occasion.',
              'unsupported_differences': []} if comparison else {}

    class Model:
        def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:
            calls.append(messages)
            return AIMessage(content='', tool_calls=[{'name': f'review_{review_kind}_support',
                'id': 'decision', 'args': {'field_results': [{'field': 'content',
                    'assessment': assessment, 'reason': 'Scripted assessment.', **detail}]}}])

    path = tmp_path / 'review.json'
    for _ in range(2):
        if assessment == 'supported':
            review(Model(), path, evidence, events.append, comparison=comparison)
        else:
            with pytest.raises(FunctionalRejection, match='SUPPORT_REVIEW_REJECTED'):
                review(Model(), path, evidence, events.append, comparison=comparison)
    assert len(calls) == 1 and len(events) == 2
    assert all(e['semantic_support'] == 'unchecked' for e in events)
    with pytest.raises(FunctionalIntegrityError, match='BINDING_CHANGED'):
        review(Model(), path, evidence, events.append, comparison=not comparison)
    with pytest.raises(FunctionalIntegrityError, match='BINDING_CHANGED'):
        review(Model(), path, {**evidence, 'forget_epoch': 1}, events.append, comparison=comparison)
    state = read_json(path)
    state['decision']['field_results'][0]['assessment'] = 'invalid-enum'
    write_json(path, state)
    with pytest.raises(FunctionalIntegrityError, match='DECISION_CHANGED'):
        review(Model(), path, evidence, events.append, comparison=comparison)
    assert len(calls) == 1


@pytest.mark.parametrize('review_kind', ['revision', 'formation'])
@pytest.mark.parametrize('comparison', [False, True])
def test_interrupted_support_review_reservation_is_not_silently_retried(
    tmp_path: Path, review_kind: str, comparison: bool,
) -> None:
    from milai_lab.memory.functional_state import FunctionalRejection

    calls = []
    review = getattr(functional, f'review_{review_kind}_support')

    class Interrupted:
        def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:
            calls.append(messages)
            raise OSError('review response lost before persistence')

    evidence = {'proposal_id': 'synthetic-proposal-v1', 'changes': [{'field': 'content'}],
                'binding': {'message': 'm'}}
    path = tmp_path / 'review.json'
    with pytest.raises(OSError):
        review(Interrupted(), path, evidence, lambda event: None, comparison=comparison)
    with pytest.raises(FunctionalRejection, match='OUTCOME_UNAVAILABLE_NO_COMMIT'):
        review(Interrupted(), path, evidence, lambda event: None, comparison=comparison)
    assert len(calls) == 1 and read_json(path)['attempts'] == 1


@pytest.mark.parametrize(('enabled', 'repeat', 'interrupt'), [
    (False, False, False), (True, False, False), (True, True, False), (True, False, True),
])
def test_unavailable_tool_feedback_preserves_completed_business_and_original_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool, repeat: bool, interrupt: bool,
) -> None:
    root = prepared(tmp_path, native=True, independent_capabilities=True,
        operation_completion=True, current_delivery=True, direct_response=True,
        phase_thinking=True, actual_capabilities=True, catalog_feedback=enabled,
        format_failure_receipts=True, support_review=True)
    generate = functional.LangMemRecipeChatModel._generate
    interrupted = False

    def interrupt_after_rejection(self: Any, messages: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal interrupted
        rejected = any(isinstance(m, ToolMessage) and m.name == 'update_memory'
                       for m in messages)
        if interrupt and rejected and not interrupted:
            interrupted = True
            raise OSError('interrupted after catalog rejection was checkpointed')
        return generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(functional.LangMemRecipeChatModel, '_generate', interrupt_after_rejection)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode', memory_write_request='none',
                allow_forgetting=False, business_action_request='perform',
                business_operations=['reserve_and_label'])
        if ordinal == 2:
            return native_call('reserve_and_label', 'reserve', item_key='catalog-probe',
                               quantity=1, destination='local', packing='box')
        assert 'update_memory' not in {t['function']['name'] for t in wire['tools']}
        if ordinal == 3 or repeat:
            return native_call('update_memory', f'unavailable-{ordinal}',
                               record_id='not-a-real-record', content='Never execute this.')
        assert ordinal == 4
        rejection = actual_tool_receipt(wire)
        assert rejection['origin'] == 'tool_catalog' and rejection['effect'] == 'none'
        assert rejection['operation_executed'] is False
        assert 'update_memory' not in rejection['available_tools']
        return {'role': 'assistant', 'content': 'Reservation and label completed.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='b', owner='alice', session='s', message_id='operate',
                content='Reserve and label one catalog-probe for local delivery.')
    result = functional.message(root, **args)
    if interrupt:
        assert result['status'] == 'UNKNOWN' and len(wires) == 3
        result = functional.message(root, **args, resume=True)
    assert result['status'] == ('COMPLETED' if enabled and not repeat else 'FAILED')
    if not enabled:
        assert result['error'] == 'VLLM_CHAT_UNKNOWN_TOOL' and len(wires) == 3
    elif repeat:
        assert result['error'] == 'FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED'
        assert len(wires) == 4
    else:
        assert len(wires) == 4
    assert result['records'] == []
    assert result['operation_status']['semantic_memory']['status'] == 'not_committed'
    world = result['world']['world']
    assert len(world['reservations']) == 1 and len(world['attempts']) == 1
    assert world['reservations'][0]['label_status'] == 'created'
    assert all(p['identity']['name'] != 'update_memory'
               for p in result['world']['receipt_progress'].values())
    assert functional.message(root, **args) == result
    assert len(wires) == (3 if not enabled else 4)


@pytest.mark.parametrize('decision', [
    {'field_results': []},
    {'field_results': [{'field': 'content', 'assessment': [], 'reason': 'Invalid scalar.'}]},
    {'field_results': [{'field': 'scope.unknown', 'assessment': 'supported', 'reason': 'Wrong.'}]},
])
@pytest.mark.parametrize('review_kind', ['revision', 'formation'])
def test_invalid_support_review_never_marks_delivery_or_retries(
    tmp_path: Path, decision: dict[str, Any], review_kind: str,
) -> None:
    from milai_lab.memory.functional_state import FunctionalRejection
    from milai_lab.providers.chat_bridge import IncompleteChatResponse

    calls, deliveries = [], []
    review = getattr(functional, f'review_{review_kind}_support')

    class Malformed:
        def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:
            calls.append(messages)
            return AIMessage(content='', tool_calls=[{'name': f'review_{review_kind}_support',
                                                     'id': 'invalid', 'args': decision}])

    evidence = {'proposal_id': 'synthetic-proposal-v1', 'changes': [{'field': 'content'}],
                'binding': {'message': 'm'}}
    path = tmp_path / 'review.json'
    with pytest.raises(IncompleteChatResponse,
                       match=f'{review_kind.upper()}_REVIEW_SCHEMA_INVALID'):
        review(Malformed(), path, evidence, lambda event: None,
               on_delivery=lambda: deliveries.append(True))
    with pytest.raises(FunctionalRejection, match='OUTCOME_UNAVAILABLE_NO_COMMIT'):
        review(Malformed(), path, evidence, lambda event: None,
               on_delivery=lambda: deliveries.append(True))
    assert len(calls) == 1 and deliveries == []


@pytest.mark.parametrize('comparison', [False, True])
def test_new_formation_review_rejects_scope_loss_before_commit_and_shares_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, comparison: bool,
) -> None:
    root = prepared(tmp_path, native=True, independent_capabilities=True,
        operation_completion=True, current_delivery=True, direct_response=True,
        phase_thinking=True, actual_capabilities=True, optional_withdrawal=True,
        formation_review=True, support_review=True, support_comparison=comparison,
        catalog_feedback=True)
    original = 'Only this workshop: try short sentences; supplier labels are excluded.'
    selected: list[str] = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode',
                memory_write_request='new_assertion', allow_forgetting=False,
                business_action_request='none', business_operations=[])
        if ordinal in {3, 5}:
            assert [t['function']['name'] for t in wire['tools']] == ['review_formation_support']
            assert wire['tool_choice'] == 'required' and wire['temperature'] == 0
            assert wire['chat_template_kwargs']['enable_thinking'] is False
            evidence = json.loads(next(m['content'] for m in wire['messages']
                                       if m['role'] == 'user'))
            assert evidence['record_id'] is None and evidence['basis'] == 'user_statement'
            assert len(evidence['changes']) == 1
            change = evidence['changes'][0]
            assert not change['before_present'] and change['after_present']
            assert change['field'] == 'content'
            assert change['after'] == ('Always use short sentences.' if ordinal == 3 else original)
            assert change['selected_original_fragments'][0]['source_role'] == 'user'
            assert original in change['selected_original_fragments'][0]['content']
            detail = {}
            if comparison:
                fields = wire['tools'][0]['function']['parameters']['properties'][
                    'field_results']['items']['properties']
                assert list(fields).index('source_limits') < list(fields).index('assessment')
                detail = {'source_limits': 'This workshop only; best effort; excludes suppliers.',
                    'proposed_limits': 'Always, with no exclusions.' if ordinal == 3 else original,
                    'unsupported_differences': ['Only this workshop and try were dropped.']
                        if ordinal == 3 else []}
            return native_call('review_formation_support', f'assess-{ordinal}', field_results=[{
                'field': 'content',
                'assessment': 'unsupported' if ordinal == 3 and not comparison else 'supported',
                'reason': 'Temporary scope and try were omitted.' if ordinal == 3
                          else 'Original scope and modality preserved.', **detail}])
        if ordinal == 2:
            selected.extend(u['fragment_handle'] for u in materials(wire)['items']
                            if u['type'] == 'fragment' and u['input_relation'] == 'current_request')
            return native_call('save_memory', 'broad', content='Always use short sentences.',
                               fragment_handles=selected)
        if ordinal == 4:
            receipt = actual_tool_receipt(wire)
            assert receipt['status'] == 'rejected' and receipt['effect'] == 'none'
            assert 'FORMATION_SUPPORT_REVIEW_REJECTED' in receipt['reason']
            if comparison:
                assert 'Only this workshop and try were dropped.' in receipt['reason']
            assert memory_effects(wire)['confirmed_semantic_commit_count'] == 0
            assert not any(u['type'] == 'record' for u in materials(wire)['items'])
            return native_call('save_memory', 'limited', content=original,
                               fragment_handles=selected)
        assert ordinal == 6 and actual_tool_receipt(wire)['status'] == 'committed'
        return {'role': 'assistant', 'content': 'Saved the temporary best-effort requirement.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='b', owner='alice', session='s', message_id='remember',
                content='Remember: ' + original)
    result = functional.message(root, **args)
    assert result['status'] == 'COMPLETED', result.get('error')
    assert result['generation_calls'] == len(wires) == 6
    assert len(result['records']) == 1
    value = result['records'][0]['value']
    assert value['revision'] == 1 and value['content'] == original
    assert value['functional_support']['content']['semantic_support'] == 'unchecked'
    assert result['operation_status']['business']['status'] == 'not_executed'
    assessments = [read_json(p) for p in root.glob('banks/*/*-formation-review-*.json')]
    assert len(assessments) == 2 and all(a['attempts'] == 1 for a in assessments)
    assert not list(root.glob('banks/*/*-revision-review-*.json'))
    assert functional.message(root, **args) == result and len(wires) == 6
    assert read_json(tmp_path / 'isolated-mechanical-budget.json')['generation_requests'] == 6


@pytest.mark.parametrize('lost_review', [False, True])
@pytest.mark.parametrize('comparison', [False, True])
def test_formation_review_after_business_preserves_effects_and_requires_outcome_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_review: bool, comparison: bool,
) -> None:
    root = prepared(tmp_path, native=True, independent_capabilities=True,
        operation_completion=True, current_delivery=True, direct_response=True,
        phase_thinking=True, actual_capabilities=True, optional_withdrawal=True,
        receipt_units=True, formation_review=True, support_review=True,
        support_comparison=comparison, catalog_feedback=True, format_failure_receipts=True)
    selected: dict[str, list[str]] = {}

    def reply(wire: dict[str, Any], ordinal: int) -> Any:
        if ordinal == 1:
            return native_call('classify_current_request', 'mode', memory_write_request='explicit',
                allow_forgetting=False, business_action_request='perform',
                business_operations=['reserve_and_label'])
        if ordinal == 2:
            selected['request'] = [u['fragment_handle'] for u in materials(wire)['items']
                if u['type'] == 'fragment' and u['input_relation'] == 'current_request']
            return native_call('reserve_and_label', 'reserve', item_key='formation item',
                               quantity=1, destination='local', packing='box')
        if ordinal == 3:
            receipt = actual_tool_receipt(wire)
            assert receipt['receipt']['label_status'] == 'created'
            selected['outcome'] = [u['fragment_handle'] for u in receipt['source_fragment_index']]
            return native_call('save_memory', 'request-is-not-result',
                content='The formation item was reserved and labeled.',
                fragment_handles=selected['request'])
        if ordinal in {4, 6}:
            assert [t['function']['name'] for t in wire['tools']] == ['review_formation_support']
            evidence = json.loads(next(m['content'] for m in wire['messages']
                                       if m['role'] == 'user'))
            assert evidence['basis'] == ('user_statement' if ordinal == 4 else 'tool_observation')
            quotes = evidence['changes'][0]['selected_original_fragments']
            assert {q['source_role'] for q in quotes} == ({'user'} if ordinal == 4 else {'tool'})
            if lost_review:
                return OSError('formation assessment response unavailable')
            detail = {'source_limits': 'Requested action only.' if ordinal == 4
                       else 'Confirmed native reserve and label.',
                      'proposed_limits': 'Claims a completed reserve and label.',
                      'unsupported_differences': ['Request became a completed outcome.']
                       if ordinal == 4 else []} if comparison else {}
            return native_call('review_formation_support', f'assess-{ordinal}', field_results=[{
                'field': 'content', 'assessment': 'unsupported' if ordinal == 4 else 'supported',
                'reason': 'A request is not a result.' if ordinal == 4
                          else 'Actual native outcome.', **detail}])
        if ordinal == 5:
            receipt = actual_tool_receipt(wire)
            if lost_review:
                assert receipt['status'] == 'outcome_unknown' and receipt['effect'] == 'unconfirmed'
                return {'role': 'assistant',
                        'content': 'Business completed; memory is unconfirmed.'}
            assert receipt['status'] == 'rejected' and receipt['effect'] == 'none'
            return native_call('save_memory', 'actual-outcome',
                content='The formation item was reserved and labeled.',
                fragment_handles=selected['outcome'])
        assert ordinal == 7 and actual_tool_receipt(wire)['status'] == 'committed'
        return {'role': 'assistant', 'content': 'Completed the business and recorded its outcome.'}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank='b', owner='alice', session='s', message_id='operate',
                content='Reserve and label one formation item for local delivery in a box. '
                        'Save the actual outcome.')
    result = functional.message(root, **args)
    assert result['status'] == 'COMPLETED', result.get('error')
    assert len(result['world']['world']['attempts']) == 1
    assert result['world']['world']['reservations'][0]['label_status'] == 'created'
    assert result['operation_status']['business']['status'] == 'completed'
    assert len(result['records']) == (0 if lost_review else 1)
    if lost_review:
        assert result['operation_status']['semantic_memory']['status'] == 'unknown'
        assert '未知' in result['final_answer']
        reviews = [read_json(p) for p in root.glob('banks/*/*-formation-review-*.json')]
        assert len(reviews) == 1 and reviews[0]['attempts'] == 1 and 'decision' not in reviews[0]
    else:
        assert result['records'][0]['value']['basis'] == 'tool_observation'
        status = result['operation_status']['semantic_memory']
        assert status['status'] == 'partial'  # The first rejected attempt remains in the aggregate.
        assert [r['status'] for r in status['operations']] == ['not_committed', 'committed']
    assert len(wires) == (5 if lost_review else 7)
    assert functional.message(root, **args) == result
    resumed = functional.message(root, **args, resume=True)
    for key in ['status', 'records', 'world', 'operation_status',
                'final_answer', 'generation_calls']:
        assert resumed[key] == result[key]
    assert resumed['usage'] == [] and resumed['attempt'] == result['attempt'] + 1
    assert resumed['budget_before'] == resumed['budget_after'] == result['budget_after']
    assert len(wires) == (5 if lost_review else 7)
    ledger = read_json(tmp_path / 'isolated-mechanical-budget.json')
    assert ledger['generation_requests'] == len(wires)
    assert ledger['generation']['unknown_usage'] == int(lost_review)


@pytest.mark.parametrize('changed', [
    {'source_limits': ''}, {'proposed_limits': ' '}, {'source_limits': 'x' * 1001},
    {'unsupported_differences': {}}, {'unsupported_differences': [False]},
    {'unsupported_differences': ['']}, {'unsupported_differences': ['x'] * 17},
    {'extra': 'Not declared'},
])
def test_support_comparison_invalid_detail_never_commits_or_retries(
    tmp_path: Path, changed: dict[str, Any],
) -> None:
    from milai_lab.memory.functional_state import FunctionalRejection
    from milai_lab.providers.chat_bridge import IncompleteChatResponse

    calls, deliveries = [], []

    class Model:
        def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:
            calls.append(messages)
            return AIMessage(content='', tool_calls=[{'name': 'review_formation_support',
                'id': 'comparison', 'args': {'field_results': [{'field': 'content',
                    'source_limits': 'Only the stated occasion.',
                    'proposed_limits': 'Only the stated occasion.',
                    'unsupported_differences': [], 'reason': 'Matches.',
                    'assessment': 'supported', **changed}]}}])

    evidence = {'proposal_id': 'synthetic-proposal-v1', 'changes': [{'field': 'content'}],
                'binding': {'message': 'm'}}
    path = tmp_path / 'comparison.json'
    with pytest.raises(IncompleteChatResponse, match='FORMATION_REVIEW_SCHEMA_INVALID'):
        functional.review_formation_support(Model(), path, evidence, lambda event: None,
            on_delivery=lambda: deliveries.append(True), comparison=True)
    with pytest.raises(FunctionalRejection, match='OUTCOME_UNAVAILABLE_NO_COMMIT'):
        functional.review_formation_support(Model(), path, evidence, lambda event: None,
            on_delivery=lambda: deliveries.append(True), comparison=True)
    assert len(calls) == 1 and deliveries == []
    assert read_json(path)['binding']['comparison'] == 'explicit_dimensions_v1'


@pytest.mark.parametrize('malformed', [False, True])
def test_explicit_history_tool_delivers_withdrawn_versions_without_new_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: bool,
) -> None:
    root = prepared(tmp_path, native=True, independent_capabilities=True,
        operation_completion=True, current_delivery=True, direct_response=True,
        phase_thinking=True, actual_capabilities=True, optional_withdrawal=True,
        explicit_reads=True, receipt_response=True, format_failure_receipts=True)
    seen: dict[str, Any] = {}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal in {1, 4, 7}:
            return native_call('classify_current_request', f'mode-{ordinal}',
                memory_write_request='explicit' if ordinal < 7 else 'none',
                allow_forgetting=False, business_action_request='none', business_operations=[])
        catalog = {t['function']['name']: t['function'] for t in wire['tools']}
        assert set(catalog['read_memory']['parameters']['properties']) == {'record_id'}
        assert set(catalog['read_memory_history']['parameters']['properties']) == {'record_id'}
        if ordinal in {2, 5}:
            packet = materials(wire)
            current = [u['fragment_handle'] for u in packet['items']
                       if u['type'] == 'fragment' and u['input_relation'] == 'current_request']
            if ordinal == 2:
                return native_call('save_memory', 'save',
                    content='Only this workshop: try quiet seats.', fragment_handles=current)
            record = next(u for u in packet['items'] if u['type'] == 'record')
            return native_call('update_memory', 'withdraw', read_handle=record['read_handle'],
                retract=True, evidence_for_withdrawal=[{'fragment_handle': current[0],
                                                       'supporting_words': 'Withdraw'}])
        if ordinal in {3, 6}:
            receipt = actual_tool_receipt(wire)
            assert receipt['status'] == 'committed'
            seen['id'] = receipt['id']
            return {'role': 'assistant', 'content': 'The requested memory operation is committed.'}
        assert 'save_memory' not in catalog and 'update_memory' not in catalog
        if ordinal == 8 or (malformed and ordinal == 9):
            if ordinal == 9:
                assert actual_tool_receipt(wire)['status'] == 'error'
            return native_call('read_memory_history', f'history-{ordinal}', record_id=seen['id'],
                               **({'revision': 'None'} if malformed and ordinal == 8 else {}))
        assert ordinal == (10 if malformed else 9)
        receipt = actual_tool_receipt(wire)
        assert {u['revision'] for u in receipt['items']} == {1, 2}
        assert all(u['content'] == 'Only this workshop: try quiet seats.'
                   for u in receipt['items'])
        assert {u['revision'] for u in receipt['items'] if u['retracted']} == {2}
        assert all(u['version_view'] == 'historical_exact_revision' for u in receipt['items'])
        assert not memory_effects(wire)['mutation_receipts']
        return {'role': 'assistant', 'content': (
            'That temporary preference was withdrawn; its original text is preserved.')}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank='b', owner='alice')
    saved = functional.message(root, **common, session='s1', message_id='save',
        content='Remember: Only this workshop: try quiet seats.')
    withdrawn = functional.message(root, **common, session='s2', message_id='withdraw',
        content='Withdraw the workshop seating preference.')
    args = dict(session='s3', message_id='history',
                content='Is that still current? What was the original history?')
    result = functional.message(root, **common, **args)
    assert saved['status'] == withdrawn['status'] == result['status'] == 'COMPLETED', result
    assert result['records'] == withdrawn['records']
    assert result['records'][0]['status'] == 'retracted'
    assert result['operation_status']['semantic_memory']['status'] == 'not_committed'
    reads = [m for m in result['messages'] if m.get('type') == 'tool'
             and m.get('name') == 'read_memory_history']
    assert len(reads) == (2 if malformed else 1)
    assert len(wires) == (10 if malformed else 9)
    count = len(wires)
    assert functional.message(root, **common, **args) == result
    assert len(wires) == count


@pytest.mark.parametrize("recipe", ["single_pass", "extract_then_edit"])
@pytest.mark.parametrize("memory_method", ["milai_edit_m_v1", "milai_fact_append_v1"])
def test_shared_maintenance_saves_then_reopens_without_host_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recipe: str, memory_method: str,
) -> None:
    root = prepared(tmp_path, native=True, request_interpretation=True,
                    memory_method=memory_method, edit_interface_version="I2",
                    edit_features={name: True for name in (
                        "matter_organization", "semantic_operations", "bound_references",
                        "single_record_changes", "source_metadata")},
                    maintenance_recipe=recipe, memory_view_mode="staged",
                    stage_enable_thinking={"extract": True, "edit": True})
    stages = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            assert "response_format" not in wire
            return intent_reply(memory=True, business=False)
        system = wire["messages"][0]["content"]
        if "Extract brief candidate propositions" in system:
            stages.append("extract")
            assert wire["chat_template_kwargs"]["enable_thinking"] is True
            assert wire["response_format"]["type"] == "json_schema"
            formal = wire["response_format"]["json_schema"]
            assert formal["name"] == "milai_extract"
            assert formal["schema"]["required"] == ["changes"]
            # Empty hints must still allow the editor to use original evidence.
            return {"role": "assistant", "content": json.dumps({"changes": []})}
        if not wire.get("tools"):
            stages.append("edit")
            assert wire["chat_template_kwargs"]["enable_thinking"] is True
            assert wire["response_format"]["type"] == "json_schema"
            formal = wire["response_format"]["json_schema"]
            assert formal["name"] == "milai_edit"
            assert formal["schema"]["required"] == ["creates", "records"]
            assert formal["schema"]["properties"]["creates"].get("minItems", 0) == 0
            assert formal["schema"]["properties"]["records"].get("minProperties", 0) == 0
            packet = json.loads(wire["messages"][-1]["content"])["delivery"]
            assert "Remember the local marker is blue." in json.dumps(packet)
            evidence = packet["evidence"][0]["id"]
            clause = {
                "text": "User reports the local marker is blue.", "evidence": [evidence],
                "assertion": {"source": evidence, "kind": "reported"},
            }
            if memory_method == "milai_edit_m_v1":
                clause["conditions"] = []
            return {"role": "assistant", "content": json.dumps({"creates": [{
                "action": "create", "matter": "User's marker", "clauses": [clause],
            }], "records": {}})}
        assert "response_format" not in wire
        assert not {"save_memory", "update_memory", "confirm_existing_memory"}.intersection(
            t["function"]["name"] for t in wire.get("tools", []))
        feedback = memory_effects(wire)["maintenance"][0]
        assert feedback["semantic_write_performed"]
        assert feedback["receipts"][0]["status"] == "committed"
        assert feedback["batches"][0]["receipts"] == [
            {"receipt_ref": "#/maintenance/0/receipts/0"}]
        assert feedback["batches"][0]["status"] == "completed"
        assert feedback["batches"][0]["unprocessed"] == []
        current_records = [item for item in materials(wire)["items"] if item["type"] == "record"]
        assert current_records and "User reports the local marker is blue." in json.dumps(
            current_records)
        return {"role": "assistant", "content": "Saved the local marker."}

    wires = scripted(monkeypatch, reply, native=True)
    first = message(root)
    assert first["status"] == "COMPLETED", first
    assert stages == (["extract", "edit"] if recipe == "extract_then_edit" else ["edit"])
    assert len(first["records"]) == 1
    if memory_method == "milai_fact_append_v1":
        assert first["records"][0]["value"]["method_version"] == memory_method
        assert first["records"][0]["value"]["method_arm"] == "Append-only"
    assert first["operation_status"]["semantic_memory"]["status"] == "committed"
    full = first["maintenance"][0]
    assert full["batches"][0]["receipts"] == full["receipts"]
    # A child-only result is still delivered in full, not replaced by a missing parent.
    child_only = {**full, "receipts": []}
    projected = functional._model_memory_effects({"maintenance": [child_only]})
    assert projected["maintenance"][0]["batches"][0]["receipts"] == full["receipts"]
    trace_path = next(root.glob("banks/*/*-trace-0.jsonl"))
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    for event in (item for item in events if item.get("event") == "vllm_response"):
        wire = event["request"]
        stage = wire.get("response_format", {}).get("json_schema", {}).get("name")
        expected = stage in {"milai_extract", "milai_edit"}
        assert wire["chat_template_kwargs"]["enable_thinking"] is expected
        assert event["capacity"]["identity"]["enable_thinking"] is expected
    calls = len(wires)
    again = message(root, resume=True)
    assert again["status"] == "COMPLETED", again
    assert again["records"] == first["records"] and len(wires) == calls
    assert again["operation_status"]["semantic_memory"]["status"] == "committed"


@pytest.mark.parametrize("memory_method", ["milai_edit_b1_v1", "milai_fact_append_v1"])
def test_shared_maintenance_obeys_readonly_request_mode(tmp_path, monkeypatch, memory_method):
    root = prepared(tmp_path, native=True, request_interpretation=True,
                    memory_method=memory_method, edit_interface_version="I2",
                    maintenance_recipe="extract_then_edit")

    def reply(wire, ordinal):
        if ordinal == 1:
            return intent_reply(memory=False, business=False)
        assert not {"save_memory", "update_memory"}.intersection(
            t["function"]["name"] for t in wire.get("tools", []))
        return {"role": "assistant", "content": "I do not have a saved marker."}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root)
    assert result["status"] == "COMPLETED", result
    assert result["records"] == [] and result["maintenance"] == [] and len(wires) == 2


@pytest.mark.parametrize("recipe", ["single_pass", "extract_then_edit"])
@pytest.mark.parametrize("no_save", [False, True])
def test_shared_host_delivers_selected_prior_request_beyond_recent_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recipe: str, no_save: bool,
) -> None:
    root = prepared(tmp_path, native=True, memory_continuation=True, operation_completion=True,
                    inline_fragments=True, memory_method="milai_edit_m_v1",
                    edit_interface_version="I2", maintenance_recipe=recipe,
                    edit_features={name: True for name in (
                        "matter_organization", "semantic_operations", "bound_references",
                        "single_record_changes", "source_metadata", "temporal_scope")})
    prior = "Save the actual outcome of the earlier reservation when it can be observed."
    imported = [{"role": "user", "session_id": "old-session", "event_key": "old-request",
                 "content": prior, "occurred_at": "2030-02-01T09:00:00Z"}]
    imported.extend({"role": "user", "session_id": "old-session", "event_key": f"later-{n}",
                     "content": f"Unrelated later user event {n}.",
                     "occurred_at": f"2030-02-02T09:00:0{n}Z"} for n in range(6))
    selected: list[dict[str, Any]] = []
    stages: list[str] = []

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return native_call("classify_current_request", "intent",
                memory_write_request="none", allow_forgetting=False,
                business_action_request="none", business_operations=[],
                memory_continuation_request="none" if no_save else "resolve_prior_explicit")
        if ordinal == 2 and not no_save:
            frame = json.loads(wire["messages"][-1]["content"])
            selected.extend(row for row in frame["archived_reference_material"]["items"]
                            if row.get("type") == "fragment" and row["content"] == prior)
            assert selected
            return native_call("resolve_continuation_operations", "resolve",
                business_operations=[], prior_memory_request_fragments=[
                    row["fragment_handle"] for row in selected])
        if not wire.get("tools") and any("response_schema" in row["content"]
                                         for row in wire["messages"]):
            assert not no_save
            packet = json.loads(wire["messages"][-1]["content"])
            delivery = packet["delivery"]
            context = packet["prior_context"]
            original = next(row for row in context if row["text"] == prior)
            assert original["role"] == selected[0]["role"] == "user"
            assert original["occurred_at"] == "2030-02-01T09:00:00Z"
            assert prior not in json.dumps(delivery)
            if "Extract brief candidate propositions" in wire["messages"][0]["content"]:
                stages.append("extract")
                return {"role": "assistant", "content": json.dumps({"changes": []})}
            stages.append("edit")
            return {"role": "assistant", "content": json.dumps({"creates": [], "records": {}})}
        return {"role": "assistant", "content": "No observed outcome has been saved."}

    wires = scripted(monkeypatch, reply, native=True)
    args = dict(bank="resume-context", owner="alice", workflow="reservation",
                session="current-session", message_id="continue",
                content="Only read; do not save." if no_save else
                        "Continue saving the actual outcome requested earlier.",
                initial_sources=imported, occurred_at="2030-02-03T09:00:00Z")
    result = functional.message(root, **args)
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["records"] == []  # Context delivery and empty proposals do not prove a save.
    # This continuation carries only control and has no pending checkpoint or
    # delivered Tool result. Its words are not a new source to be maintained.
    assert stages == []
    if no_save:
        assert result["maintenance"] == [] and len(wires) == 3
    else:
        assert result["request_mode"]["resumed_memory_request"]["completion"] == (
            "not_proven_by_resolution")
        assert not any(row["semantic_write_performed"] for row in result["maintenance"])
    calls = len(wires)
    repeated = functional.message(root, **args, resume=True)
    assert repeated["status"] == "COMPLETED" and repeated["records"] == []
    assert len(wires) == calls


@pytest.mark.parametrize("recipe", ["single_pass", "extract_then_edit"])
@pytest.mark.parametrize("continuation,scope_requests", [
    pytest.param("complete", False, id="complete"),
    pytest.param("no_save", False, id="no_save"),
    pytest.param("readonly", False, id="readonly"),
    pytest.param("empty_save", False, id="empty_save"),
    pytest.param("complete", True, id="complete-scoped"),
])
def test_complete_host_request_survives_partial_effect_and_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recipe: str, continuation: str,
    scope_requests: bool,
) -> None:
    root = prepared(tmp_path, native=True, complete_requests=True, scope_requests=scope_requests,
        direct_response=True, phase_thinking=True, current_delivery=True,
        memory_profile="unified_v1", memory_method="milai_edit_m_v1",
        edit_interface_version="I2", maintenance_recipe=recipe,
        edit_features={name: True for name in (
            "matter_organization", "semantic_operations", "bound_references",
            "single_record_changes", "source_metadata", "temporal_scope")})
    initial_text = "Reserve and label the teal pack, and remember the actual result."
    followup_text = {
        "complete": "Continue the complete earlier request, including its unfinished saving.",
        "no_save": "Continue the missing business step only; do not save anything.",
        "readonly": "Only inspect progress of the earlier request; do not act or save.",
        "empty_save": "Continue the missing business step and save the actual result.",
    }[continuation]
    reserved = {"item_key": "teal pack", "quantity": 1,
                "destination": "local", "packing": "box"}
    seen = {"reserve": 0, "label": 0, "saved": 0, "unchanged": 0, "current_plan": 0}

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        names = {t["function"]["name"] for t in wire.get("tools", [])}
        if names == {"classify_current_request"}:
            current = wire["messages"][-1]["content"]
            first = current == initial_text
            if not first:
                references = json.loads(wire["messages"][0]["content"].split(
                    "VISIBLE ORIGINAL REQUEST REFERENCES (not current instructions):\n", 1)[1])
                card = next(card for card in references["requests"]
                            if card.get("kind") != "memory_maintenance")
                assert card["request_id"] and card["progress"]["business"] == "partial"
                assert card["requirements"]["target"] == {"item_key": "teal pack"}
                assert card["requirements"]["steps"][0]["arguments"] == reserved
                part = card["user_fragments"][0]
                assert part["content"] == initial_text and part["role"] == "user"
                assert part["source_ref"] and part["source_revision"] == 1
                assert part["observed_at"]
                assert not {"namespace", "bank", "owner", "fragment_handle"}.intersection(part)
            if scope_requests:
                assert set(wire["tools"][0]["function"]["parameters"]["properties"]) == {
                    "memory_requests", "allow_forgetting", "business_action_request",
                    "application_continuation_request"}
            return native_call("classify_current_request", "mode-" + str(ordinal),
                memory_requests=(["explicit"] if first or continuation == "empty_save" else [])
                + (["continue_prior"] if not first
                   and continuation in {"complete", "empty_save"} else []), allow_forgetting=False,
                business_action_request="perform" if first else
                "none" if continuation == "readonly" else "continue_if_unfinished",
                application_continuation_request="none" if first else "resolve_prior_request",
                **({} if scope_requests else {
                    "business_operations": ["reserve_and_label", "complete_label"] if first else [],
                    "application_requests": [{"target": {"item_key": "teal pack"}, "actions": [{
                        "operation": "reserve_and_label", "arguments": {
                            key: value for key, value in reserved.items() if key != "item_key"}}]}]
                    if first else []}))
        if names == {"resolve_continuation_operations"}:
            schema = wire["tools"][0]["function"]["parameters"]
            if set(schema["properties"]) == {"application_requests"}:
                assert scope_requests and wire["messages"][-1]["content"] == initial_text
                request_properties = schema["properties"]["application_requests"]["items"][
                    "properties"]
                public = {entry["function"]["name"]: entry["function"]
                          for entry in BUSINESS_SCHEMAS}
                assert request_properties["target"]["description"] == public[
                    "get_reservation"]["description"]
                actions = request_properties["actions"]["items"]["oneOf"]
                assert {action["properties"]["operation"]["const"]: action["description"]
                        for action in actions} == {
                    name: entry["description"] for name, entry in public.items()
                    if name != "get_reservation"}
                seen["current_plan"] += 1
                return native_call("resolve_continuation_operations", "current-plan",
                    application_requests=[{"target": {"item_key": "teal pack"}, "actions": [{
                        "operation": "reserve_and_label", "arguments": {
                            key: value for key, value in reserved.items() if key != "item_key"}}]}])
            frame = json.loads(wire["messages"][-1]["content"])
            cards = frame["archived_reference_material"]["registered_application_requests"]
            assert len(cards) == 1
            card = cards[0]
            assert len(card["requirements"]["steps"]) == 2
            assert card["requirements"]["save_result"]
            return native_call("resolve_continuation_operations", "resolve-" + str(ordinal),
                business_operations=[] if continuation == "readonly" else ["complete_label"],
                prior_request_ids=[card["request_id"]],
                prior_memory_request_fragments=[p["fragment_handle"]
                    for p in card["user_fragments"]]
                if continuation in {"complete", "empty_save"} else [])
        if not names:
            system = wire["messages"][0]["content"]
            if "Extract brief candidate propositions" in system:
                return {"role": "assistant", "content": json.dumps({"changes": []})}
            packet = json.loads(wire["messages"][-1]["content"])["delivery"]
            tool_sources = {s["id"] for s in packet["source_table"] if s["role"] == "tool"}
            completed_evidence = [e for e in packet["evidence"] if e["source"] in tool_sources
                                  and '"label_status": "created"' in e["text"]]
            envelope: dict[str, Any] = {"creates": [], "records": {}}
            if continuation == "complete" and completed_evidence:
                evidence = completed_evidence[0]["id"]
                outcome = "The teal pack was reserved and its label created."
                existing = next((row for row in packet["records"]
                    if row.get("matter") == "Teal pack outcome"
                    and any(clause["text"] == outcome for clause in row["clauses"])), None)
                if existing is not None:
                    envelope["records"][existing["id"]] = {"action": "no_change"}
                    seen["unchanged"] += 1
                else:
                    envelope["creates"] = [{"action": "create", "matter": "Teal pack outcome",
                        "clauses": [{"text": outcome, "evidence": [evidence], "conditions": [],
                                     "assertion": {"source": evidence, "kind": "observed"}}]}]
                    seen["saved"] += 1
            return {"role": "assistant", "content": json.dumps(envelope)}
        current = next(m["content"] for m in wire["messages"] if m["role"] == "user")
        tools = [m for m in wire["messages"] if m["role"] == "tool"]
        if not tools:
            if current == initial_text:
                seen["reserve"] += 1
                return native_call("reserve_and_label", "reserve", **reserved)
            return native_call("get_reservation", "query", item_key="teal pack")
        last = tools[-1]
        if last["name"] == "get_reservation" and continuation != "readonly":
            seen["label"] += 1
            actual = json.loads(last["content"])["receipt"]
            return native_call("complete_label", "label", reservation_id=actual["reservation_id"])
        return {"role": "assistant", "content": "Reported the actual request progress."}

    wires = scripted(monkeypatch, reply, native=True)
    first_args = dict(bank="request-bank", owner="alice", session="first", message_id="start",
                      content=initial_text, initial_world={"label_available": False})
    first = functional.message(root, **first_args)
    assert first["status"] == "COMPLETED", first.get("error")
    assert seen["current_plan"] == int(scope_requests)
    original = first["application_requests"][0]
    assert not original["complete"] and original["memory"]["status"] == "pending"
    assert original["business"]["status"] == "partial"
    assert [s["status"] for s in original["business"]["steps"]] == ["completed", "incomplete"]
    assert original["feedback"]["status"] == "delivered"
    assert len(first["world"]["world"]["attempts"]) == 1
    original_rows = [r for r in first["world"]["receipt_progress"].values()
                     if r["identity"]["name"] == "resume_request"]
    assert len(original_rows) == 1 and original_rows[0]["binding"]["session"] == "first"
    followup_args = dict(bank="request-bank", owner="alice", session="second",
        message_id="continue",
        content=followup_text, message_index=1, evaluator_control={"before_message_events": [{
            "event_id": "label-restored", "before_message_index": 1,
            "operation": "reservation.set_label_available", "available": True}]})
    second = functional.message(root, **followup_args)
    assert second["status"] == "COMPLETED", second.get("error")
    progress = second["application_requests"][0]
    assert progress["request_id"] == original["request_id"]
    assert seen["current_plan"] == int(scope_requests)
    assert seen["reserve"] == 1 and seen["label"] == int(continuation != "readonly")
    assert len(second["world"]["world"]["attempts"]) == 1 + int(continuation != "readonly")
    assert progress["feedback"]["status"] == "delivered"
    assert progress["business"]["status"] == (
        "partial" if continuation == "readonly" else "completed")
    if continuation == "readonly":
        assert progress["business"]["execution"]["status"] == "observed_only"
        assert not progress["business"]["execution"]["can_execute"]
        assert "业务部分完成; 本次执行只查询" in second["final_answer"]
    if continuation == "complete":
        assert progress["complete"] and progress["memory"]["status"] == "committed"
        assert seen["saved"] == 1 and len(second["records"]) == 1
        assert seen["unchanged"] >= 1
        assert second["records"][0]["value"]["edit_state"]["units"][0]["text"] == (
            "The teal pack was reserved and its label created.")
        assert progress["semantic_coverage"] == "unchecked"
    else:
        assert not progress["complete"] and second["records"] == []
        if continuation == "empty_save":
            assert progress["memory"]["status"] == "failed"
            assert len(progress["memory"]["attempts"]) == 1
            assert second["operation_status"]["semantic_memory"]["status"] == "not_committed"
            assert "本轮语义记忆: 未提交。" in second["final_answer"]
            assert "已有记录, 无需变更" not in second["final_answer"]
        else:
            assert progress["memory"]["current_permission"] == "not_authorized_current_request"
    calls = len(wires)
    replay = functional.message(root, **followup_args, resume=True)
    assert replay["status"] == "COMPLETED" and len(wires) == calls
    assert replay["records"] == second["records"]


@pytest.mark.parametrize("recipe", ["single_pass", "extract_then_edit"])
def test_host_request_reconciles_original_shared_commit_after_response_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recipe: str,
) -> None:
    from milai_lab.memory.service import MemoryService
    from milai_lab.methods.functional_edit_memory import FunctionalEditMemory

    root = prepared(tmp_path, native=True, complete_requests=True,
        memory_profile="unified_v1", memory_method="milai_edit_m_v1",
        edit_interface_version="I2", maintenance_recipe=recipe,
        edit_features={name: True for name in (
            "matter_organization", "semantic_operations", "bound_references",
            "single_record_changes", "source_metadata", "temporal_scope")})
    apply = FunctionalEditMemory.apply_writer_proposal
    operation_receipt = MemoryService.operation_receipt
    lost = []
    lookup_available = False
    maintenance_calls = []

    def receipt_lookup(self, session, operation_id):
        if operation_id in lost and not lookup_available:
            return None
        return operation_receipt(self, session, operation_id)

    def commit_then_lose(self, config, operation_id, proposal):
        progress = read_json(next(root.glob(
            "banks/*/applications/reservation/receipt-progress.json")))
        request = next(r for r in progress.values() if r["identity"]["name"] == "resume_request")
        pending = request["request_progress"]["memory"]
        assert pending["status"] == "semantic_unknown" and len(pending["attempts"]) == 1
        assert pending["attempts"][0]["binding"]["maintenance"]
        receipt = apply(self, config, operation_id, proposal)
        if receipt.get("status") == "committed" and not lost:
            lost.append(operation_id)
            raise RuntimeError("ACTUAL_COMMIT_RESPONSE_LOST")
        return receipt

    monkeypatch.setattr(FunctionalEditMemory, "apply_writer_proposal", commit_then_lose)
    monkeypatch.setattr(MemoryService, "operation_receipt", receipt_lookup)

    def reply(wire, ordinal):
        names = {t["function"]["name"] for t in wire.get("tools", [])}
        if names == {"classify_current_request"}:
            first = "Reserve" in wire["messages"][-1]["content"]
            return native_call("classify_current_request", "mode-" + str(ordinal),
                memory_requests=["explicit"] if first else [], allow_forgetting=False,
                business_action_request="perform" if first else "none",
                business_operations=["reserve_and_label"] if first else [],
                application_continuation_request="none" if first else "resolve_prior_request",
                application_requests=[{"target": {"item_key": "violet pack"}, "actions": [{
                    "operation": "reserve_and_label", "arguments": {
                        "quantity": 1, "destination": "local", "packing": "box"}}]}]
                if first else [])
        if names == {"resolve_continuation_operations"}:
            frame = json.loads(wire["messages"][-1]["content"])
            card = frame["archived_reference_material"]["registered_application_requests"][0]
            return native_call("resolve_continuation_operations", "resolve",
                business_operations=[], prior_memory_request_fragments=[],
                prior_request_ids=[card["request_id"]])
        if not names:
            maintenance_calls.append(ordinal)
            if "Extract brief candidate propositions" in wire["messages"][0]["content"]:
                return {"role": "assistant", "content": json.dumps({"changes": []})}
            packet = json.loads(wire["messages"][-1]["content"])["delivery"]
            tools = {s["id"] for s in packet["source_table"] if s["role"] == "tool"}
            envelope = {"creates": [], "records": {}}
            if tools:
                evidence = next(e["id"] for e in packet["evidence"] if e["source"] in tools)
                envelope["creates"] = [{"action": "create", "matter": "Violet pack result",
                    "clauses": [{"text": "Violet pack was reserved and labeled.",
                        "evidence": [evidence], "conditions": [],
                        "assertion": {"source": evidence, "kind": "observed"}}]}]
            return {"role": "assistant", "content": json.dumps(envelope)}
        if not [m for m in wire["messages"] if m["role"] == "tool"] and not lost:
            return native_call("reserve_and_label", "reserve", item_key="violet pack",
                               quantity=1, destination="local", packing="box")
        return {"role": "assistant", "content": "Report actual progress and its memory status."}

    wires = scripted(monkeypatch, reply, native=True)
    first = functional.message(root, bank="loss-bank", owner="alice", session="original",
        message_id="request", content="Reserve and label violet pack; save its actual result.")
    assert first["status"] == "COMPLETED", first.get("error")
    assert len(lost) == 1 and len(first["records"]) == 1
    old = first["application_requests"][0]
    assert old["memory"]["status"] == "semantic_unknown" and not old["complete"]
    assert old["memory"]["attempts"][0]["error"] == "ACTUAL_COMMIT_RESPONSE_LOST"
    assert len(first["world"]["world"]["attempts"]) == 1
    count = len(wires)
    writer_count = len(maintenance_calls)
    lookup_available = True
    second = functional.message(root, bank="loss-bank", owner="alice", session="readonly",
        message_id="inspect", content="Only inspect progress of the original request; do not save.")
    assert second["status"] == "COMPLETED", second.get("error")
    current = second["application_requests"][0]
    assert current["request_id"] == old["request_id"]
    assert current["memory"]["status"] == "committed"
    assert current["memory"]["attempts"] == old["memory"]["attempts"]
    assert second["records"] == first["records"] and second["maintenance"] == []
    assert len(second["world"]["world"]["attempts"]) == 1
    assert len(maintenance_calls) == writer_count
    assert len(wires) - count == 3  # declaration, bounded reference, actual Host response
    freeze = functional.frozen(root)
    bank_root = next(root.glob("banks/*"))
    with SqliteStore.from_conn_string(str(bank_root / "memory.sqlite")) as store:
        service = MemoryService(store,
            ("functional", freeze["run_id"], "loss-bank", "alice"), "alice",
            bank_root / "memory.lock", functional_contract="functional_v1",
            memory_profile="unified_v1")
        receipt = operation_receipt(service, "original", lost[0])
        assert receipt["ok"] and receipt["status"] == "committed"
        assert receipt in current["memory"]["reconciliation"]["receipts"]
        batches = old["memory"]["attempts"][0]["binding"]["maintenance"]
        states = {batch["request_id"]: store.get(
            (*service.namespace, "edit_maintenance"), json.dumps(
                ["original", batch["request_id"]], ensure_ascii=False)) for batch in batches}
        pending = [batch for batch in batches if states[batch["request_id"]] is None]
        assert len(pending) == 1 and pending[0]["phase"] == "start"
        assert pending[0]["receipts"] == []
        assert all(item.value["phase"] == "complete" for item in states.values()
                   if item is not None)


def test_host_save_continuation_registers_actual_tool_batch_after_unconfirmed_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.application.functional import FunctionalApplication
    from milai_lab.application.recovery import resume_request
    from milai_lab.contracts.memory import VerifiedObjectRef

    root = prepared(tmp_path, native=True, complete_requests=True,
        direct_response=True, phase_thinking=True, current_delivery=True,
        memory_profile="unified_v1",
        memory_method="milai_edit_m_v1", edit_interface_version="I2",
        maintenance_recipe="single_pass", result_maintenance_mode="literal_observations_v1",
        edit_features={name: True for name in (
            "matter_organization", "semantic_operations", "bound_references",
            "single_record_changes", "source_metadata", "temporal_scope")})
    freeze = functional.frozen(root)
    bank_root = root / "banks" / functional._bank_reference(
        root, freeze["run_id"], "save-bank", "alice")
    bank_root.mkdir(parents=True)
    arguments = {"item_key": "amber pack", "quantity": 1,
                 "destination": "local", "packing": "box"}
    requirements = functional.compile_application_requests("reservation_v1", [{
        "target": {"item_key": "amber pack"}, "actions": [{
            "operation": "reserve_and_label", "arguments": {
                key: value for key, value in arguments.items() if key != "item_key"}}],
    }], save_result=True)[0]
    with SqliteStore.from_conn_string(str(bank_root / "memory.sqlite")) as store:
        service = functional.MemoryService(store,
            ("functional", freeze["run_id"], "save-bank", "alice"), "alice",
            bank_root / "memory.lock", functional_contract="functional_v1",
            memory_profile="unified_v1")
        captured = service.capture_user("original", "request",
            "Reserve and label the amber pack, and save the actual outcome.")
        original_id = captured["source_ref"] + ":application:0"
        binding = {"session": "original", "turn_id": "request",
                   "source_ref": captured["source_ref"], "config_version": freeze["config_version"]}
        service.bind_public_turn("original", "request", captured["source_ref"],
                                config_version=freeze["config_version"], phase="start")
        with FunctionalApplication.open(bank_root / "applications" / "reservation",
            "reservation", "alice", initial_label_available=False) as app:
            app.progress.request_state("alice", original_id, requirements,
                binding={**binding, "workflow": app.workflow})
            adapter = app.adapter(service, "original", "request",
                                  allowed_operations=["reserve_and_label", "complete_label"])
            reserved = adapter.execute("reserve_and_label", arguments, attempt_id="reserve-once")
            assert reserved["business_effect"] == "partial"
            app.world.set_label_available("restore-label", True)
            observed = adapter.discover(requirements["target"], attempt_id="before-label")
            labeled = adapter.execute("complete_label", {}, attempt_id="label-once",
                                      ref=VerifiedObjectRef(**observed["object_ref"]))
            assert labeled["receipt"]["label_status"] == "created"
            failed = []

            def unconfirmed_save(operation_id, result):
                assert operation_id == original_id + ":memory:1"
                assert result["business"]["status"] == "completed"
                return {"ok": False, "status": "result_save_unconfirmed", "effect": "none"}

            progress = resume_request(app, adapter, original_id,
                current={"readonly": False, "allow_memory": True}, execute_business=False,
                save_result=unconfirmed_save,
                semantic_attempt_binding={**binding, "maintenance": []})
            assert progress["business"]["status"] == "completed"
            assert progress["memory"]["status"] == "failed"
            assert len(progress["memory"]["attempts"]) == 1
            attempt = progress["memory"]["attempts"][0]
            assert attempt["binding"] == {**binding, "maintenance": []}
            assert attempt["receipt"]["status"] == "result_save_unconfirmed"
            failed.append(json.loads(json.dumps(attempt)))
            original_world = app.world.snapshot()
    save_text = "Only continue saving the earlier actual result. Query, but do not redo business."
    read_text = "Only inspect the original request and saved state. Do not act or save."
    editor_roles: list[str] = []
    commit_attempts: list[str] = []
    apply = functional.FunctionalEditMemory.apply_writer_proposal

    def request_row() -> dict[str, Any]:
        return next(row for row in read_json(
            bank_root / "applications/reservation/receipt-progress.json").values()
            if row["identity"].get("call_id") == original_id)

    def commit_after_registration(memory, config, operation_id, proposal):
        attempts = request_row()["request_progress"]["memory"]["attempts"]
        assert [a["status"] for a in attempts] == ["failed", "semantic_unknown"]
        assert attempts[0] == failed[0]
        bound = attempts[1]["binding"]
        assert bound["source_ref"] == memory._binding(config)["source_ref"]
        assert bound["session"] == "save-only" and bound["turn_id"] == "save"
        assert bound["source_ref"] != attempts[0]["binding"]["source_ref"]
        assert len(bound["maintenance"]) == 1
        batch = bound["maintenance"][0]
        assert len(batch["source_refs"]) == 1
        source = memory.service.source(batch["source_refs"][0])
        assert source is not None and source["origin"] == "get_reservation"
        assert source["object_ref"]["external_id"] == observed["object_ref"]["external_id"]
        assert batch["request_id"] not in {
            b["request_id"] for b in attempts[0]["binding"]["maintenance"]}
        commit_attempts.append(attempts[1]["operation_id"])
        return apply(memory, config, operation_id, proposal)

    monkeypatch.setattr(functional.FunctionalEditMemory, "apply_writer_proposal",
                        commit_after_registration)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        names = {tool["function"]["name"] for tool in wire.get("tools", [])}
        if names == {"classify_current_request"}:
            readonly = wire["messages"][-1]["content"] == read_text
            references = json.loads(wire["messages"][0]["content"].split(
                "VISIBLE ORIGINAL REQUEST REFERENCES (not current instructions):\n", 1)[1])[
                    "requests"]
            assert len(references) == 1 and references[0]["request_id"] == original_id
            assert references[0]["requirements"]["save_result"]
            assert references[0]["progress"]["business"] == "completed"
            assert references[0]["progress"]["memory"] in {"pending", "failed", "committed"}
            assert [row["content"] for row in wire["messages"] if row["role"] == "user"] == [
                read_text if readonly else save_text]
            assert any("save the actual outcome" in part["content"]
                       for part in references[0]["user_fragments"])
            return native_call("classify_current_request", "mode-" + str(ordinal),
                memory_requests=[] if readonly else ["continue_prior"], allow_forgetting=False,
                business_action_request="none", business_operations=[], application_requests=[],
                application_continuation_request="resolve_prior_request")
        if names == {"resolve_continuation_operations"}:
            frame = json.loads(wire["messages"][-1]["content"])
            card = frame["archived_reference_material"]["registered_application_requests"][0]
            assert card["request_id"] == original_id
            return native_call("resolve_continuation_operations", "resolve-" + str(ordinal),
                business_operations=[], prior_request_ids=[original_id],
                prior_memory_request_fragments=[p["fragment_handle"]
                                                for p in card["user_fragments"]]
                if frame["current_request"] == save_text else [])
        if not names:
            payload = json.loads(wire["messages"][-1]["content"])
            packet = payload["delivery"]
            role = packet["source_table"][0]["role"]
            editor_roles.append(role)
            assert role == "tool" and editor_roles == ["tool"]
            assert save_text not in json.dumps(packet)
            assert "Current maintenance scope" in wire["messages"][0]["content"]
            candidates = {row["field"]: row for row in payload["change_candidates"]}
            assert all(row["basis"] == "actual_source_literal"
                       for row in candidates.values())
            evidence = [alias for field in ("status", "label_status")
                        for alias in candidates[field]["evidence"]]
            return {"role": "assistant", "content": json.dumps({"creates": [{
                "action": "create", "matter": "Amber pack outcome", "clauses": [{
                    "text": "The amber pack was reserved and its label created.",
                    "evidence": evidence, "conditions": [],
                    "assertion": {"source": evidence[-1], "kind": "observed"}}]}], "records": {}})}
        assert not {"reserve_and_label", "complete_label"}.intersection(names)
        tools = [m for m in wire["messages"] if m["role"] == "tool"]
        if not tools:
            current = next(m["content"] for m in wire["messages"] if m["role"] == "user")
            if current == save_text:
                progress = request_row()["request_progress"]
                assert progress["memory"]["attempts"][0] == failed[0]
                assert progress["memory"]["attempts"][1]["status"] == "committed"
                observation = progress["business"]["observation"]
                delivered = json.loads(observation["delivery_response"]["content"])
                assert delivered["source_ref"] == observation["source_ref"]
                assert delivered["source_fragment_index"]
                return {"role": "assistant", "content": "Reported the actually saved result."}
            return native_call("get_reservation", "query-" + str(ordinal), item_key="amber pack")
        return {"role": "assistant", "content": "Reported actual business and memory receipts."}

    wires = scripted(monkeypatch, reply, native=True)
    common = dict(bank="save-bank", owner="alice")
    saved = functional.message(root, **common, session="save-only", message_id="save",
                               content=save_text)
    assert saved["status"] == "COMPLETED", saved.get("error")
    result = saved["application_requests"][0]
    assert result["request_id"] == original_id and result["complete"]
    assert [a["status"] for a in result["memory"]["attempts"]] == ["failed", "committed"]
    assert result["memory"]["attempts"][0] == failed[0]
    assert commit_attempts == [original_id + ":memory:2"]
    assert result["semantic_coverage"] == "unchecked"
    assert len(saved["records"]) == 1 and saved["records"][0]["value"]["revision"] == 1
    assert saved["world"]["world"] == original_world
    count = len(wires)
    readonly = functional.message(root, **common, session="inspect-only", message_id="inspect",
                                  content=read_text)
    assert readonly["status"] == "COMPLETED", readonly.get("error")
    assert not readonly["request_mode"]["allow_memory_maintenance"]
    assert not readonly["request_mode"]["allow_business_mutation"]
    assert readonly["maintenance"] == [] and editor_roles == ["tool"]
    assert readonly["application_requests"][0]["memory"]["attempts"] == (
        result["memory"]["attempts"])
    assert readonly["records"] == saved["records"] and readonly["world"]["world"] == original_world
    assert len(wires) - count == 4  # declaration, reference, query and response; no Writer
