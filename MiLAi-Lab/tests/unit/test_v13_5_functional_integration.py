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


def prepared(tmp_path: Path, *, queue_requests: int = 100, native: bool = False) -> Path:
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
