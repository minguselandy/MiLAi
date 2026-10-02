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
from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.providers.functional_queue import FunctionalVLLMClient
from milai_lab.runners import functional


def prepared(tmp_path: Path, *, queue_requests: int = 100) -> Path:
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    native = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token="[UNK]")
    native.chat_template = (
        "{% for m in messages %}{{m.role}} {{m.content}} {% endfor %}"
        "{% if tools %}{{tools|tojson}}{% endif %} assistant "
    )
    directory = tmp_path / "mechanical-tokenizer"
    native.save_pretrained(str(directory))
    (directory / "chat_template.jinja").write_text(native.chat_template)
    host = VLLMConfig(base_url="http://mechanical.invalid/v1/", model="mechanical-provider",
                      max_tokens=4096, max_calls=24, enable_thinking=False)
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


def scripted(monkeypatch: pytest.MonkeyPatch, respond: Any) -> list[dict[str, Any]]:
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
        return httpx.Response(200, json={"id": "mechanical-response-" + str(len(wires)),
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(action)}}],
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
            fragments = [row["fragment_handle"] for row in materials(wire)["items"]
                         if row["type"] == "fragment"]
            return tool("save_memory", content="The local marker is blue.",
                        fragment_handles=fragments)
        receipt = actual_tool_receipt(wire)
        assert receipt["ok"] and receipt["status"] == "committed"
        return {"answer": "Saved the marker."}

    wires = scripted(monkeypatch, reply)
    first = message(root)
    assert first["status"] == "COMPLETED", first
    assert len(first["records"]) == 1 and first["records"][0]["value"]["revision"] == 1
    assert first["snapshot_before_close"] is True
    assert first["memory_mutation_receipts"][0]["position"] < len(first["messages"]) - 1
    assert first["budget_after"]["generation_requests"] == len(wires) == 2
    again = message(root, resume=True)
    assert again["status"] == "COMPLETED", again
    assert again["records"] == first["records"] and len(wires) == 2
    assert again["budget_before"] == first["budget_after"] == again["budget_after"]


def test_unified_provider_failure_resume_keeps_budget_and_one_semantic_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> Any:
        if ordinal == 1:
            handles = [row["fragment_handle"] for row in materials(wire)["items"]
                       if row["type"] == "fragment"]
            return tool("save_memory", content="The local marker is blue.",
                        fragment_handles=handles)
        if ordinal == 2:
            return httpx.ReadTimeout("mechanical response interruption")
        return {"answer": "The existing save is confirmed."}

    wires = scripted(monkeypatch, reply)
    first = message(root)
    assert first["status"] == "PROVIDER_ERROR", first
    assert len(first["records"]) == 1
    resumed = message(root, resume=True)
    assert resumed["status"] == "COMPLETED", resumed
    assert resumed["records"] == first["records"]
    assert resumed["budget_after"]["generation_requests"] == len(wires) == 3
    assert resumed["budget_after"]["generation"]["unknown_usage"] == 1
    bank = next((root / "banks").iterdir())
    admission = read_json(bank / "message-admission.json")
    assert next(iter(admission["messages"].values()))["count"] == 3
    assert read_json(root / "queue-admission.json")["requests"] == 3


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
