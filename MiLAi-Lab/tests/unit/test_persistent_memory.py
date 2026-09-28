"""Actual graph/ToolNode and local SQLite evidence for the v3 opt-in recipe."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import FoundationScope, VLLMEmbeddings, invoke_public_message
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import ControlResponseError
from milai_lab.methods.memory_boundaries import event_reference, operation_audit
from milai_lab.methods.memory_result import RESPONSIBILITY_PROMPT
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import IncompleteChatResponse, VLLMChatModel
from milai_lab.runners import persistent_memory as runner
from milai_lab.runners.langmem_application import BUSINESS_NAMES, ApplicationWorld, _business_tools
from milai_lab.runners.langmem_application_runtime import ApplicationRuntime
from milai_lab.runners.langmem_foundation import BusinessActionJournal

LAB = Path(__file__).resolve().parents[2]


class _MockCapacity:
    enable_thinking = False

    def __init__(self, max_characters: int = 65536) -> None:
        self.max_characters = max_characters

    def text_tokens(self, text: str) -> int:
        return len(text)

    def check(self, messages: Any, output_tokens: int, _tools: Any = None) -> dict[str, Any]:
        prompt = sum(len(row["content"]) for row in messages)
        receipt = {"prompt_tokens": prompt, "total_reserved_tokens": prompt + output_tokens + 512,
                   "output_reserve_tokens": output_tokens, "safety_tokens": 512,
                   "context_tokens": self.max_characters, "identity": "mechanical-character-count"}
        if receipt["total_reserved_tokens"] > self.max_characters:
            raise CapacityExceeded(receipt)
        return receipt


def _config(root: Path, history: str = "retained") -> dict[str, Any]:
    return {
        "recipe_id": "synthetic-v3",
        "memory_contract": "strict",
        "history_mode": history,
        "memory_result": {"correction_entries": 1},
        "host": {
            "base_url": "http://mock/v1/",
            "model": "mock",
            "temperature": 0,
            "max_tokens": 4096,
            "tool_mode": "json_action",
            "max_calls": 12,
            "enable_thinking": False,
        },
        "embedding": {"base_url": "http://mock/v1/", "model": "mock"},
        "history": {"enabled": history == "archive", "page_max_bytes": 16384},
        "capacity": {"enable_thinking": False},
        "budget_path": str(root / "budget.json"),
    }


@contextmanager
def _runtime(
    root: Path,
    store: InMemoryStore,
    wires: list[dict[str, Any]],
    respond: Any,
    *,
    max_calls: int = 12,
    capacity: Any = None,
    budget: RunBudget | None = None,
    tool_mode: str = "json_action",
) -> Any:
    def transport(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append(wire)
        answer = respond(wire, len(wires))
        message = (answer if tool_mode == "native" else {
            "role": "assistant", "content": json.dumps(answer)})
        return httpx.Response(
            200,
            json={
                "id": f"generation-{len(wires)}",
                "choices": [
                    {
                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                        "message": message,
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
            },
        )

    if budget is None:
        budget = RunBudget(RunLimits(1, 3, None, None, None), root / "budget.json")
    with VLLMClient(
        VLLMConfig(**{**_config(root)["host"], "tool_mode": tool_mode}),
        transport=httpx.MockTransport(transport),
        emit=Trace(root / "trace.jsonl", "mock"),
        budget=budget,
        capacity=capacity if capacity is not None else _MockCapacity(),
    ) as client:
        with SqliteSaver.from_conn_string(str(root / "checkpoints.sqlite")) as saver:
            observer = SimpleNamespace(
                assert_healthy=lambda: None,
                run_tool=lambda request, execute, _wrapper: execute(request),
            )
            yield ApplicationRuntime(
                VLLMChatModel(
                    client=client,
                    capacity_path=root / "message-capacity.json",
                    max_calls_per_message=max_calls,
                ),
                store,
                saver,
                observer,
            )


def _agent(
    runtime: ApplicationRuntime,
    root: Path,
    arm: str = "C",
    *,
    history: str = "retained",
    business: Any = (),
    wrapper: Any = None,
    boundaries: bool = False,
    boundary_options: dict[str, Any] | None = None,
    selector_client: VLLMClient | None = None,
    research_profile: str | None = None,
) -> Any:
    write_json(root / "run_manifest.json", {"identity": {"run_id": "run", "arm_id": arm}})
    config = _config(root, history)
    config["host"]["tool_mode"] = runtime.model.client.config.tool_mode
    if research_profile is not None:
        config["research_profile"] = research_profile
    if boundaries:
        config["memory_boundaries"] = {"enabled": True, **(boundary_options or {})}
        config["memory_result"] = {"correction_entries": 0}
    factory, _ = runner._adapters(
        runtime, LocalStateBank(runtime.store), root, "run", arm, config,
        selector_client=selector_client)
    return factory(
        runtime.model,
        runtime.store,
        runtime.checkpointer,
        business,
        user_id="alice",
        business_call_wrapper=wrapper,
    )


def _final(status: str, refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "answer": "actual final",
        "memory_result": {"status": status, "receipt_refs": refs or []},
    }


def _scope(arm: str = "C", session: str = "one") -> FoundationScope:
    return FoundationScope("run", arm, "alice", "application:" + session)


def _protocol_reply(action: dict, mode: str, index: int) -> dict:
    if mode == "json_action":
        return action
    if "calls" not in action:
        return {"role": "assistant", "content": action["answer"],
                "reasoning_content": "private reasoning is not the answer"}
    return {"role": "assistant", "content": "These are proposed operations.", "tool_calls": [
        {"id": f"native-{index}-{position}", "type": "function", "function": {
            "name": call["name"], "arguments": json.dumps(call["arguments"])}}
        for position, call in enumerate(action["calls"])]}


@pytest.mark.parametrize("mode", ["json_action", "native"])
def test_v7_shared_profile_actual_toolnode_crud_partial_and_no_tool(
    tmp_path: Path, mode: str,
) -> None:
    from langchain_core.tools import tool

    owner_scope = _scope("B0")
    namespace = ("langmem", "run", "B0", "alice")
    foreign = str(uuid.uuid4())
    store = InMemoryStore()
    store.put(("langmem", "run", "B0", "bob"), foreign, {"content": "PRIVATE_BOB"})
    side_effects = []
    @tool
    def partial_action() -> str:
        """Execute a synthetic action with an actual partial result."""
        side_effects.append("reserved")
        return json.dumps({"ok": False, "status": "reserved_label_failed",
                           "reservation_id": "actual-reservation"})
    ids = []
    actions = [
        lambda: {"calls": [
            {"name": "manage_memory", "arguments": {"action": "create", "content": "PLAN_A"}},
            {"name": "manage_memory", "arguments": {"action": "create", "content": "PLAN_B"}},
            {"name": "manage_memory", "arguments": {"action": "create", "content": None}},
            {"name": "read_memory", "arguments": {"id": "not-a-uuid"}},
            {"name": "partial_action", "arguments": {}}]},
        lambda: {"answer": "Actual partial result retained."},
        lambda: {"calls": [
            {"name": "manage_memory", "arguments": {"action": "update", "id": ids[0],
                                                      "content": "PLAN_A_CURRENT"}},
            {"name": "manage_memory", "arguments": {"action": "update", "id": ids[0],
                                                      "content": "PLAN_A_CURRENT"}},
            {"name": "read_memory", "arguments": {"id": foreign}}]},
        lambda: {"answer": "Updated the same record."},
        lambda: {"calls": [
            {"name": "manage_memory", "arguments": {"action": "delete", "id": ids[0]}},
            {"name": "read_memory", "arguments": {"id": ids[0]}}]},
        lambda: {"answer": "Deleted the record; exact read is absent."},
        lambda: {"answer": "A legal read-only final reply."},
    ]
    wires = []
    def respond(_wire, index):
        return _protocol_reply(actions[index - 1](), mode, index)
    with _runtime(tmp_path, store, wires, respond, tool_mode=mode) as runtime:
        agent = _agent(runtime, tmp_path, "B0", business=[partial_action], boundaries=True,
            boundary_options={"memory_placement": "current_request", "model_view": "compact_v6"},
            research_profile="protocol_calibration_v7")
        first = invoke_public_message(
            agent, runtime.model, owner_scope, "Keep two independent plans.")
        receipts = [row for row in first if isinstance(row, ToolMessage)]
        assert [row.name for row in receipts] == ["manage_memory"] * 3 + [
            "read_memory", "partial_action"]
        assert [row.status for row in receipts] == [
            "success", "success", "error", "error", "success"]
        ids.extend(json.loads(row.content)["id"] for row in receipts[:2])
        assert len(set(ids)) == 2 and [store.get(namespace, key).value for key in ids] == [
            {"content": "PLAN_A"}, {"content": "PLAN_B"}]
        assert side_effects == ["reserved"]
        audit = operation_audit([row.model_dump(mode="json") for row in first],
                               runtime.model.memory_turn,
                               owner_scope.config()["configurable"]["thread_id"],
                               runtime.model.request_view.receipt_metadata)
        assert audit["operations"][-1]["status"] == "reserved_label_failed"
        assert len(audit["actual_memory_change_refs"]) == 2
        updated = invoke_public_message(
            agent, runtime.model, owner_scope, "Update only the first plan.")
        assert [json.loads(row.content)["status"] for row in
                [row for row in updated if isinstance(row, ToolMessage)][-3:]] == [
            "updated", "no_change", "not_found"]
        assert store.get(namespace, ids[0]).value == {"content": "PLAN_A_CURRENT"}
        deleted = invoke_public_message(
            agent, runtime.model, owner_scope, "Delete only the first plan.")
        assert [json.loads(row.content)["status"] for row in
                [row for row in deleted if isinstance(row, ToolMessage)][-2:]] == [
            "deleted", "not_found"]
        final = invoke_public_message(
            agent, runtime.model, owner_scope, "Just reply without writing.")
        assert final[-1].content == "A legal read-only final reply."
        assert store.get(namespace, ids[0]) is None
        assert store.get(namespace, ids[1]).value == {"content": "PLAN_B"}
        assert side_effects == ["reserved"] and len(wires) == 7
        assert all("PRIVATE_BOB" not in json.dumps(wire) for wire in wires)
        assert all(sum("[DURABLE MEMORY]" in row["content"] for row in wire["messages"]) == 1
                   for wire in wires)
        assert all("Keep two independent plans." in json.dumps(wire) for wire in wires)
        assert all("[CURRENT USER REQUEST]" in json.dumps(wire) for wire in wires)
        assert runtime.model.calls_in_message == 1
        if mode == "native":
            assert all("tools" in wire and wire["tool_choice"] == "auto" and
                       "response_format" not in wire for wire in wires)
            assert all("JSON object" not in wire["messages"][0]["content"] and
                       "transport envelope" not in wire["messages"][0]["content"] for wire in wires)
            proposed = next(row for row in first if isinstance(row, AIMessage) and row.tool_calls)
            assert proposed.content == "These are proposed operations."
            assert proposed.response_metadata["tool_narrative_status"] == "proposal_not_execution"
            assert [row.tool_call_id for row in receipts] == [
                call["id"] for call in proposed.tool_calls]
            history_call = next(row for row in wires[1]["messages"] if row["role"] == "assistant")
            assert len(history_call["tool_calls"]) == 5
        else:
            assert all("tools" not in wire and wire["response_format"]["type"] == "json_schema"
                       for wire in wires)


def test_v7_profile_is_explicit_and_preserves_old_restrictions(tmp_path: Path) -> None:
    import copy

    old = read_json(LAB / "data/diagnostics/next-development-v6-compact/config.json")
    runner._validate(old, "B0")
    for name in ("json-action-config.json", "native-config.json"):
        current = read_json(LAB / "data/diagnostics/development-experiment-v7-e1" / name)
        runner._validate(current, "B0")
        for changed in ({"research_profile": "anything"}, {"research_profile": None}):
            invalid = {**current, **changed}
            if changed["research_profile"] is not None or current["host"]["tool_mode"] == "native":
                with pytest.raises(ValueError):
                    runner._validate(invalid, "B0")
        for key, value in (("model_view", "full"), ("memory_placement", "system"),
                           ("attention_enabled", True)):
            invalid = copy.deepcopy(current)
            invalid["memory_boundaries"][key] = value
            with pytest.raises(ValueError):
                runner._validate(invalid, "B0")
        with pytest.raises(ValueError):
            runner._validate(current, "C")


def test_v7_native_actual_template_counts_tools_and_rejects_before_delivery(tmp_path: Path) -> None:
    config = read_json(LAB / "data/diagnostics/development-experiment-v7-e1/native-config.json")
    capacity = HostCapacity(config["capacity"])
    store, wires = InMemoryStore(), []
    key = str(uuid.uuid4())
    store.put(("langmem", "run", "B0", "alice"), key, {"content": "OWN_CURRENT_BODY"})
    store.put(("langmem", "run", "B0", "bob"), key, {"content": "PRIVATE_OTHER_BODY"})
    with _runtime(tmp_path, store, wires,
                  lambda *_: {"role": "assistant", "content": "A legal final."},
                  tool_mode="native", capacity=capacity) as runtime:
        agent = _agent(runtime, tmp_path, "B0", boundaries=True,
            boundary_options={"memory_placement": "current_request", "model_view": "compact_v6"},
            research_profile="protocol_calibration_v7")
        invoke_public_message(agent, runtime.model, _scope("B0"), "Read my current plan.")
        wire = wires[0]
        with_tools = capacity.check(wire["messages"], wire["max_tokens"], wire["tools"])
        without_tools = capacity.check(wire["messages"], wire["max_tokens"])
        assert with_tools["prompt_tokens"] > without_tools["prompt_tokens"]
        template = capacity.tokenizer.apply_chat_template(
            wire["messages"], tools=wire["tools"], tokenize=False,
            add_generation_prompt=True, enable_thinking=False)
        assert "read_memory" in template and "OWN_CURRENT_BODY" in template
        assert "PRIVATE_OTHER_BODY" not in template and "Read my current plan." in template
        events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
        route = next(row for row in events if row["event"] == "memory_boundary_route")
        delivery = next(row for row in events if row["event"] == "memory_boundary_delivery")
        assert route["final_capacity"] == with_tools
        assert delivery["final_capacity"] == with_tools and delivery["generation_id"]
        assert runtime.model.calls_in_message == 1

        # A catalog-aware capacity failure is pre-HTTP, so no delivery or generation is claimed.
        capacity.context_tokens = 1
        with pytest.raises(CapacityExceeded):
            invoke_public_message(agent, runtime.model, _scope("B0", "too-small"),
                                  "Read my current plan.")
        assert len(wires) == 1 and runtime.model.calls_in_message == 0
        final_events = [json.loads(line) for line in
                        (tmp_path / "trace.jsonl").read_text().splitlines()]
        assert sum(row["event"] == "memory_boundary_delivery" for row in final_events) == 1


@pytest.mark.parametrize("memory_placement", ["system", "current_request"])
@pytest.mark.parametrize("model_view", ["full", "compact_v6"])
def test_boundary_roles_reach_actual_wire_after_call_serialization_and_reset(
    tmp_path: Path, memory_placement: str, model_view: str,
) -> None:
    store, wires = InMemoryStore(), []
    memory_id = str(uuid.uuid4())
    namespace = ("langmem", "run", "B0", "alice")
    store.put(namespace, memory_id, {"content": "actual durable 4"})
    other_namespace = ("langmem", "run", "B0", "bob")
    store.put(other_namespace, memory_id, {"content": "PRIVATE OTHER OWNER"})
    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return {"calls": [{"name": "read_memory", "arguments": {"id": memory_id}}]}
        if call == 2:
            return {"calls": [{"name": "manage_memory", "arguments": {
                "action": "update", "id": memory_id, "content": "updated durable 4"}}]}
        if call == 3:
            return {"calls": [{"name": "manage_memory", "arguments": {
                "action": "delete", "id": memory_id}}]}
        return {"answer": "saved in final prose without proving a write"}
    with _runtime(tmp_path, store, wires, respond) as runtime:
        agent = _agent(runtime, tmp_path, "B0", boundaries=True,
                       boundary_options={"memory_placement": memory_placement,
                                         "model_view": model_view})
        scope = _scope("B0")
        agent.update_state(scope.config(), {"messages": [
            HumanMessage(id="old-user", content="earlier request"),
            AIMessage(id="old-answer", content="prior assistant 3"),
        ]}, as_node="agent")
        result = invoke_public_message(agent, runtime.model, scope, "TEMP current task bytes")
        originals = agent.get_state(scope.config()).values["messages"]
        assert len(wires) == 4 and runtime.model.calls_in_message == 4
        assert result[-1].content.startswith("saved")
        assert "memory_result" not in json.dumps(
            wires[0]["response_format"]["json_schema"]["schema"])
        for wire in wires:
            users = [row for row in wire["messages"] if row["role"] == "user"]
            current = users[-1]["content"]
            if memory_placement == "current_request":
                assert current.startswith("[DURABLE MEMORY]\n")
                assert "[DURABLE MEMORY]" not in wire["messages"][0]["content"]
                current = current.split("\n[/DURABLE MEMORY]\n", 1)[1]
            else:
                assert "[DURABLE MEMORY]" in wire["messages"][0]["content"]
            assert current == (
                "[CURRENT USER REQUEST]\n[CURRENT TASK]\nTEMP current task bytes")
            assert users[0]["content"] == "[USER HISTORY]\nearlier request"
            assert sum(row["content"].count("[DURABLE MEMORY]\n")
                       for row in wire["messages"]) == 1
            assert all(row["role"] != "system" for row in wire["messages"][1:])
            assert any(row["content"] == (
                           "[ASSISTANT HISTORY - prior model output]\nprior assistant 3")
                       for row in wire["messages"])
        proposals = [row for row in wires[-1]["messages"] if row["role"] == "assistant"
                     and row["content"].startswith("[WORKING HYPOTHESIS]")]
        assert len(proposals) == 3
        assert json.loads(proposals[0]["content"].split("\n", 1)[1])["calls"][0]["arguments"][
            "id"] == memory_id
        material_message = (wires[2]["messages"][0] if memory_placement == "system" else
                            next(row for row in reversed(wires[2]["messages"])
                                 if row["role"] == "user"))
        assert "updated durable 4" in material_message["content"]
        assert ('"active_refs": []' in wires[-1]["messages"][0]["content"]) == (
            model_view == "full")
        assert '"active_refs": [{"record_id":' in wires[1]["messages"][0]["content"]
        inputs = agent.get_state(scope.config()).values["llm_input_messages"]
        assert "[DURABLE MEMORY]\n[]\n[/DURABLE MEMORY]" in inputs[0].content
        for original in originals:
            assert "[CURRENT TASK]" not in original.content
            assert "[TOOL OBSERVATION]" not in original.content
            if isinstance(original, ToolMessage):
                projected = next(row for row in wires[-1]["messages"]
                                 if row.get("tool_call_id") == original.tool_call_id)
                assert projected["content"].startswith("[TOOL OBSERVATION]")
                assert projected["content"].endswith(original.content)
                received = runtime.model.request_view.receipt_metadata[event_reference(
                    str(scope.config()["configurable"]["thread_id"]), 0,
                    original.model_dump(mode="json"))]
                label = json.loads(projected["content"].split("\n", 1)[0].split(" ", 2)[2])
                assert label["observation_received_at"] == received["observation_received_at"]
                if model_view == "full":
                    assert label["content_sha256"] == received["content_sha256"]
                else:
                    assert "content_sha256" not in label
                assert received["user_id"] == "alice"
                assert received["message_key"] == runtime.model.active_message_key
                assert received["tool_call_id"] == original.tool_call_id
                assert received["content_sha256"] == hashlib.sha256(json.dumps(
                    original.content, ensure_ascii=False).encode()).hexdigest()
        if capture := os.environ.get("MILAI_V4_WIRE_CAPTURE"):
            write_json(Path(capture), {"requests": wires,
                "original_checkpoint_messages": [row.model_dump(mode="json") for row in originals],
                "receipt_metadata": runtime.model.request_view.receipt_metadata})
        assert store.search(namespace) == []
        assert store.get(other_namespace, memory_id).value == {"content": "PRIVATE OTHER OWNER"}
        assert "PRIVATE OTHER OWNER" not in json.dumps(wires)
        invoke_public_message(agent, runtime.model, _scope("B0", "new"), "NEXT TASK")
        assert "TEMP current task bytes" not in json.dumps(wires[-1])
        assert ('"active_refs": []' in wires[-1]["messages"][0]["content"]) == (
            model_view == "full")


def test_boundary_config_defaults_zero_correction_and_preserves_legacy_c(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config["memory_boundaries"] = {"enabled": True}
    config.pop("memory_result")
    runner._validate(config, "B0")
    with pytest.raises(ValueError, match="PERSISTENT_MEMORY_CONFIG_INVALID"):
        runner._validate(config, "C")
    runner._validate(_config(tmp_path), "C")


@pytest.mark.parametrize("memory_placement", ["system", "current_request"])
@pytest.mark.parametrize("model_view", ["full", "compact_v6"])
def test_boundary_query_uses_complete_query_actual_index_and_continuous_embedding_cost(
    tmp_path: Path, memory_placement: str, model_view: str,
) -> None:
    from langgraph.store.base import PutOp

    embedding_wires = []
    def embeddings(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        embedding_wires.append(wire)
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [1.0, 0.0] if "needle" in text else [0.0, 1.0]}
            for i, text in enumerate(wire["input"])],
            "usage": {"prompt_tokens": 3, "total_tokens": 3}})
    budget = RunBudget(RunLimits(1, 3, None, None, None), tmp_path / "budget.json")
    namespace = ("langmem", "run", "B0", "alice")
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock-embedding"),
                    budget=budget, emit=Trace(tmp_path / "trace.jsonl", "embedding"),
                    transport=httpx.MockTransport(embeddings)) as embed_client:
        store = InMemoryStore(index={"dims": 2, "embed": VLLMEmbeddings(embed_client, "mock"),
                                     "fields": ["content"]})
        own_ids = [str(uuid.uuid4()) for _ in range(33)]
        store.batch([PutOp(namespace, key, {"content": "needle" if i == 0 else f"other-{i}"})
                     for i, key in enumerate(own_ids)])
        before = {row.key: row.value for row in store.search(namespace, limit=64)}
        query = "Original complete needle query\nKeep exact entity X-7 and conditions."
        wires = []
        with _runtime(tmp_path, store, wires, lambda *_: {"answer": "read-only"},
                      budget=budget) as runtime:
            invoke_public_message(_agent(runtime, tmp_path, "B0", boundaries=True,
                boundary_options={"memory_placement": memory_placement,
                                  "model_view": model_view}), runtime.model,
                                  _scope("B0"), query)
        assert len(embedding_wires) == 2 and embedding_wires[-1]["input"] == [query]
        assert len(wires) == 1
        containing = next(row for row in wires[0]["messages"] if "[DURABLE MEMORY]\n"
                          in row["content"])
        assert containing["role"] == ("system" if memory_placement == "system" else "user")
        material = json.loads(containing["content"].split("[DURABLE MEMORY]\n", 1)[1].split(
            "\n[/DURABLE MEMORY]", 1)[0])
        assert len(material) == 10
        assert all(set(row) == ({"id", "value"} if model_view == "full" else {"id", "content"})
                   for row in material)
        assert read_json(tmp_path / "budget.json")["embedding"]["charged_tokens"] == 6
        after = {row.key: row.value for row in store.search(namespace, limit=64)}
        assert before == after
        events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
        route = next(row for row in events if row["event"] == "memory_boundary_route")
        assert route["route"] == "query" and route["query"] == query
        assert len(route["retrieved_record_ids"]) == 10
        assert own_ids[0] in route["retrieved_record_ids"]
        delivered = next(row for row in events if row["event"] == "memory_boundary_delivery")
        assert delivered["delivered_record_ids"] == route["selected_record_ids"]


class _OneRecordCapacity(_MockCapacity):
    def check(self, messages: Any, output_tokens: int, tools: Any = None) -> dict[str, Any]:
        receipt = super().check(messages, output_tokens, tools)
        containing = next((row["content"] for row in messages if "[DURABLE MEMORY]\n" in
                           row["content"]), None)
        if containing is not None:
            rows = json.loads(containing.split("[DURABLE MEMORY]\n", 1)[1].split(
                "\n[/DURABLE MEMORY]", 1)[0])
            if len(rows) > 1:
                raise CapacityExceeded(receipt)
        return receipt


@pytest.mark.parametrize("memory_placement", ["system", "current_request"])
@pytest.mark.parametrize("model_view", ["full", "compact_v6"])
def test_boundary_one_paid_selector_reuses_only_ids_and_resolves_updated_body(
    tmp_path: Path, memory_placement: str, model_view: str,
) -> None:
    store, wires, control_wires = InMemoryStore(), [], []
    namespace = ("langmem", "run", "B0", "alice")
    chosen = str(uuid.uuid4())
    for key in [chosen, str(uuid.uuid4())]:
        store.put(namespace, key, {"content": "old body"})
    def control(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        control_wires.append(wire)
        return httpx.Response(200, json={"id": "selector-generation", "choices": [{
            "finish_reason": "stop", "message": {"role": "assistant", "content":
                json.dumps({"record_ids": [chosen]})}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}})
    def respond(_wire: Any, call: int) -> Any:
        return ({"calls": [{"name": "manage_memory", "arguments": {
            "action": "update", "id": chosen, "content": "current updated body"}}]}
            if call == 1 else {"answer": "done"})
    with _runtime(tmp_path, store, wires, respond, capacity=_OneRecordCapacity()) as runtime:
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock", max_tokens=2048),
            emit=lambda row: Trace(tmp_path / "trace.jsonl", "selector")({
                **row, "role": "state_control", "control_stage": "memory_read_selection"}),
            budget=runtime.model.client.budget, capacity=runtime.model.client.capacity,
            transport=httpx.MockTransport(control)) as selector:
            agent = _agent(runtime, tmp_path, "B0", boundaries=True,
                           boundary_options={"attention_enabled": True,
                                             "memory_placement": memory_placement,
                                             "model_view": model_view},
                           selector_client=selector)
            invoke_public_message(agent, runtime.model, _scope("B0"), "original task")
            checkpoint = agent.get_state(_scope("B0").config()).values["messages"]
        assert len(control_wires) == 1 and len(wires) == 2 and runtime.model.calls_in_message == 2
        candidates = json.loads(control_wires[0]["messages"][-1]["content"])["candidates"]
        assert all(set(row) == {"id", "value"} and set(row["value"]) == {"content"}
                   for row in candidates)
        containing = next(row for row in wires[-1]["messages"] if "[DURABLE MEMORY]\n"
                          in row["content"])
        assert containing["role"] == ("system" if memory_placement == "system" else "user")
        assert "current updated body" in containing["content"]
        assert "old body" not in containing["content"]
        assert read_json(tmp_path / "control-capacity.json")[
            f"{_scope('B0').config()['configurable']['thread_id']}:0"] == 1
        assert read_json(tmp_path / "budget.json")["generation_requests"] == 3
        assert all("[WORKING HYPOTHESIS]" not in row.content for row in checkpoint)
        events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
        routes = [row for row in events if row["event"] == "memory_boundary_route"]
        assert routes[-1]["selection_reused"] and routes[-1]["route"] == "attention"
        accounting = runner._accounting(tmp_path, tmp_path / "budget.json")
        assert accounting["by_role"]["state_control"]["requests"] == 1
        assert accounting["by_role"]["task_host"]["requests"] == 2
        assert len(accounting["boundary_deliveries"]) == 2
        assert accounting["boundary_observation_costs"]["retrieval"]["calls"] == 2
        assert accounting["boundary_route_timing"]["cpu_ns"] > 0


@pytest.mark.parametrize("used", [1, 13])
def test_boundary_persisted_selector_capacity_refuses_without_another_http(
    tmp_path: Path, used: int,
) -> None:
    store, wires, control_wires = InMemoryStore(), [], []
    namespace = ("langmem", "run", "B0", "alice")
    for _ in range(2):
        store.put(namespace, str(uuid.uuid4()), {"content": "actual body"})
    with _runtime(tmp_path, store, wires, lambda *_: {"answer": "unused"},
                  capacity=_OneRecordCapacity()) as runtime:
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock", max_tokens=2048),
            transport=httpx.MockTransport(lambda request: control_wires.append(request))
        ) as selector:
            agent = _agent(runtime, tmp_path, "B0", boundaries=True,
                boundary_options={"attention_enabled": True}, selector_client=selector)
            message_key = f"{_scope('B0').config()['configurable']['thread_id']}:0"
            write_json(tmp_path / "control-capacity.json", {message_key: used})
            expected = "LSA_CONTROL_CAPACITY" if used == 13 else "ALREADY_ATTEMPTED"
            with pytest.raises((ValueError, ControlResponseError), match=expected):
                invoke_public_message(agent, runtime.model, _scope("B0"), "actual query")
            assert wires == control_wires == []
            assert runtime.model.calls_in_message == 0
            assert read_json(tmp_path / "control-capacity.json")[message_key] == used


@pytest.mark.parametrize("mode", ["json_action", "native"])
def test_boundary_host_twelve_call_capacity_does_not_replay_or_add_control(
    tmp_path: Path, mode: str,
) -> None:
    store, wires = InMemoryStore(), []
    record_id = str(uuid.uuid4())
    store.put(("langmem", "run", "B0", "alice"), record_id, {"content": "actual content"})
    with _runtime(tmp_path, store, wires, lambda _wire, index: _protocol_reply({
        "calls": [{"name": "read_memory", "arguments": {"id": record_id}}]}, mode, index),
        tool_mode=mode) as runtime:
        agent = _agent(runtime, tmp_path, "B0", boundaries=True)
        with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
            invoke_public_message(agent, runtime.model, _scope("B0"), "read actual content")
        assert len(wires) == runtime.model.calls_in_message == 12
        checkpoint = agent.get_state(_scope("B0").config()).values["messages"]
        assert sum(isinstance(row, ToolMessage) for row in checkpoint) == 12
        assert not (tmp_path / "control-capacity.json").exists()


@pytest.mark.parametrize(("unknown", "audit_failure", "invalid_next"), [
    (False, False, False), (True, False, False), (True, True, False), (False, False, True)])
def test_boundary_run_phase_preserves_partial_and_unknown_effects_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unknown: bool, audit_failure: bool,
    invalid_next: bool,
) -> None:
    from milai_lab.runners import langmem_application as application

    args = SimpleNamespace(config=tmp_path / "config.json", inputs=tmp_path / "inputs.json",
                           runtime_root=tmp_path / "runtime", output=tmp_path / "prepared.json",
                           prepared=tmp_path / "prepared.json", run="run", arm="B0", phase=0,
                           stage="synthetic-boundaries")
    config = _config(args.runtime_root)
    config["memory_boundaries"] = {"enabled": True}
    config["memory_result"] = {"correction_entries": 0}
    write_json(args.config, config)
    write_json(args.inputs, {"kind": "MILAI_PERSISTENT_MEMORY_INPUTS", "workload": "application",
        "script": {"users": ["alice"], "initial_label_available": False, "phases": [{
            "id": 0, "operator_memory": [], "world_events": [], "messages": [{
                "message_id": "one", "session_id": "one", "user_id": "alice",
                "public_index": 0, "text": "perform an action and maintain memory"}]}]}})
    original_tools = application._business_tools
    def business_tools(world: Any, user: str) -> Any:
        tools = original_tools(world, user)
        if unknown:
            actual = tools[0].func
            def uncertain(**kwargs: Any) -> Any:
                actual(**kwargs)
                raise httpx.ReadTimeout("synthetic unknown after actual side effect")
            tools[0].func = uncertain
        return tools
    monkeypatch.setattr(application, "_business_tools", business_tools)
    store, wires = InMemoryStore(), []
    def respond(_wire: Any, call: int) -> Any:
        if invalid_next and call == 2:
            return []
        return ({"calls": [
            {"name": "manage_memory", "arguments": {"action": "update",
                "id": str(uuid.UUID(int=2)), "content": "proposed body"}},
            {"name": "reserve_and_label", "arguments": {"item_key": "parcel", "quantity": 2,
                "destination": "bay", "packing": "box"}},
        ]} if call == 1 else {"answer": "actual results only"})
    @contextmanager
    def open_runtime(_config: Any, _run: str, _arm: str, root: Path, _stage: str,
                     **_kwargs: Any) -> Any:
        with _runtime(root, store, wires, respond) as runtime:
            yield runtime
    monkeypatch.setattr(runner, "open_application_runtime", open_runtime)
    if audit_failure:
        original_adapters = runner._adapters
        def adapters(*positional: Any, **kwargs: Any) -> Any:
            factory, completed = original_adapters(*positional, **kwargs)
            def fail_after_audit(*call_args: Any) -> None:
                completed(*call_args)
                raise ValueError("synthetic audit failure")
            return factory, fail_after_audit
        monkeypatch.setattr(runner, "_adapters", adapters)
    runner.prepare(args, lab_root=LAB)
    if unknown:
        with pytest.raises(httpx.ReadTimeout) as failure:
            runner.run(args, lab_root=LAB)
        if audit_failure:
            assert any("audit failed: ValueError" in note for note in failure.value.__notes__)
        with pytest.raises(ValueError, match="PERSISTENT_MEMORY_ATTEMPT_ALREADY_STARTED"):
            runner.run(args, lab_root=LAB)
    elif invalid_next:
        with pytest.raises(IncompleteChatResponse):
            runner.run(args, lab_root=LAB)
    else:
        runner.run(args, lab_root=LAB)
    world = ApplicationWorld(args.runtime_root / "business-world.sqlite", False)
    try:
        assert len(world.snapshot()["attempts"]) == len(world.snapshot()["reservations"]) == 1
    finally:
        world.close()
    turns = list((args.runtime_root / "turns").glob("*.json"))
    assert len(turns) == 1
    audit = read_json(turns[0])["operation_audit"]
    operations = audit["operations"]
    assert len(operations) == 2 and audit["semantic_completion"] is None
    if unknown:
        assert len(wires) == 1 and all(row["status"] == "unknown" for row in operations)
        assert all(row["receipt"] is None for row in operations)
    else:
        assert len(wires) == 2 and operations[0]["status"] == "failed"
        assert operations[1]["status"] == "reserved_label_failed"
        assert operations[1]["receipt"]["parsed"]["ok"] is False
        assert operations[1]["side_effects"] == "not_inferred"
        assert operations[1]["receipt"]["observation_received_at"] is not None
    assert not audit["observed_write"]
    accounting = read_json(args.runtime_root / "run_manifest.json")["accounting"]
    assert accounting["boundary_observation_costs"]["operation_audit"]["calls"] == 1
    assert accounting["boundary_observation_costs"]["operation_audit"]["logical_bytes"] > 0


def test_same_graph_correction_uses_visible_refs_preserves_originals_and_capacity(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []

    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return _final("committed")
        if call == 2:
            return {
                "calls": [
                    {
                        "name": "manage_memory",
                        "arguments": {"action": "create", "content": "actual retained content"},
                    }
                ]
            }
        return _final("committed", ["generation-2:tool:0"])

    with _runtime(tmp_path, store, wires, respond) as runtime:
        agent = _agent(runtime, tmp_path)
        result = invoke_public_message(agent, runtime.model, _scope(), "keep this for later")
        checkpoint = agent.get_state(_scope().config()).values["messages"]
        assert runtime.model.calls_in_message == 3
        assert sum(isinstance(row, HumanMessage) for row in checkpoint) == 1
        assert (
            len([row for row in checkpoint if isinstance(row, AIMessage) and not row.tool_calls])
            == 2
        )
        assert checkpoint[1].id == "generation-1" and checkpoint[1].content == "actual final"
        assert checkpoint[1].response_metadata["memory_result"]["receipt_refs"] == []
        assert result[-1].response_metadata["memory_result_verification"]["declaration_supported"]
        original_tool = next(row for row in checkpoint if isinstance(row, ToolMessage))
        assert "receipt_ref" not in original_tool.content
        assert json.loads(original_tool.content)["status"] == "created"
        actual_copy = next(row for row in wires[-1]["messages"] if row["role"] == "tool")
        assert '"receipt_ref": "generation-2:tool:0"' in actual_copy["content"]
        assert actual_copy["content"].endswith(original_tool.content)
        assert all(row["role"] != "system" for row in wires[1]["messages"][1:])
        assert "reserve_and_label" not in wires[1]["messages"][0]["content"]
        assert len(store.search(("langmem", "run", "C", "alice"))) == 1
        capture = os.environ.get("MILAI_P1_WIRE_CAPTURE")
        if capture:
            write_json(
                Path(capture),
                {"wires": wires, "original_tool": original_tool.model_dump(mode="json")},
            )


def test_existing_record_read_nochange_never_forces_create_or_reads_foreign_owner(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []
    own_id, other_id = str(uuid.uuid4()), str(uuid.uuid4())
    store.put(("langmem", "run", "C", "alice"), own_id, {"content": "existing content"})
    store.put(("langmem", "run", "C", "bob"), other_id, {"content": "PRIVATE_OTHER"})

    def respond(_wire: Any, call: int) -> Any:
        return (
            {"calls": [{"name": "read_memory", "arguments": {"id": own_id}}]}
            if call == 1
            else _final("no_change", ["generation-1:tool:0"])
        )

    with _runtime(tmp_path, store, wires, respond) as runtime:
        result = invoke_public_message(
            _agent(runtime, tmp_path), runtime.model, _scope(), "read it"
        )
        assert len(wires) == 2
        assert (
            result[-1].response_metadata["memory_result_verification"]["successful_change_refs"]
            == []
        )
        assert store.get(("langmem", "run", "C", "alice"), own_id).value == {
            "content": "existing content"
        }
        assert "PRIVATE_OTHER" not in json.dumps(wires)


def test_partial_operations_keep_real_commits_errors_and_no_semantic_certification(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []

    def respond(_wire: Any, call: int) -> Any:
        return (
            {
                "calls": [
                    {"name": "manage_memory", "arguments": {"action": "create", "content": "kept"}},
                    {
                        "name": "manage_memory",
                        "arguments": {
                            "action": "update",
                            "content": "x",
                            "id": str(uuid.UUID(int=2)),
                        },
                    },
                ]
            }
            if call == 1
            else _final("committed", ["generation-1:tool:0"])
        )

    with _runtime(tmp_path, store, wires, respond) as runtime:
        result = invoke_public_message(_agent(runtime, tmp_path), runtime.model, _scope(), "save")
        verdict = result[-1].response_metadata["memory_result_verification"]
        assert len(wires) == 2 and verdict["declaration_supported"]
        assert verdict["partial_operations_observed"] and verdict["semantic_completion"] is None
        assert verdict["failed_operation_refs"] == ["generation-1:tool:1"]
        assert len(store.search(("langmem", "run", "C", "alice"))) == 1


def test_nochange_contradiction_gets_only_one_entry_and_invalid_second_final_is_preserved(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []

    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return {"calls": [{"name": "manage_memory", "arguments": {"content": "actual"}}]}
        return _final("no_change") if call == 2 else {"answer": "raw invalid second final"}

    with _runtime(tmp_path, store, wires, respond) as runtime:
        result = invoke_public_message(_agent(runtime, tmp_path), runtime.model, _scope(), "save")
        assert len(wires) == 3
        assert result[-1].content == "raw invalid second final"
        assert not result[-1].response_metadata["memory_result_verification"][
            "declaration_supported"
        ]
        assert len(store.search(("langmem", "run", "C", "alice"))) == 1


def test_semantically_wrong_nochange_is_not_auto_corrected_and_cap_is_not_extended(
    tmp_path: Path,
) -> None:
    for status in ("no_change", "unresolved"):
        root = tmp_path / status
        root.mkdir()
        wires: list[dict[str, Any]] = []
        store = InMemoryStore()
        with _runtime(
            root, store, wires, lambda _wire, _call, value=status: _final(value), max_calls=1
        ) as runtime:
            result = invoke_public_message(_agent(runtime, root), runtime.model, _scope(), "save")
            assert len(wires) == 1 and runtime.model.calls_in_message == 1
            assert (
                result[-1].response_metadata["memory_result_verification"]["semantic_completion"]
                is None
            )
            assert store.search(("langmem", "run", "C", "alice")) == []


def test_business_partial_effect_is_never_replayed_by_memory_correction(tmp_path: Path) -> None:
    store, wires = InMemoryStore(), []
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    journal = BusinessActionJournal(tmp_path / "business.json", BUSINESS_NAMES)
    args = {"item_key": "parcel", "quantity": 2, "destination": "bay", "packing": "box"}

    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return {
                "calls": [
                    {"name": "reserve_and_label", "arguments": args},
                    {
                        "name": "manage_memory",
                        "arguments": {
                            "action": "update",
                            "id": str(uuid.UUID(int=2)),
                            "content": "proposal that cannot be saved",
                        },
                    },
                ]
            }
        if call == 3:
            return {"calls": [{"name": "reserve_and_label", "arguments": args}]}
        return _final("unresolved")

    try:
        with _runtime(tmp_path, store, wires, respond) as runtime:
            agent = _agent(
                runtime, tmp_path, business=_business_tools(world, "alice"), wrapper=journal
            )
            with pytest.raises(IncompleteChatResponse, match="JSON_ACTION_SCHEMA_INVALID"):
                invoke_public_message(agent, runtime.model, _scope(), "reserve then maintain")
            assert len(world.snapshot()["attempts"]) == 1
            assert len(world.snapshot()["reservations"]) == 1
            tools = [
                row
                for row in agent.get_state(_scope().config()).values["messages"]
                if isinstance(row, ToolMessage)
            ]
            assert len(tools) == 2
            assert json.loads(tools[0].content)["ok"] is False
            assert tools[1].name == "manage_memory" and tools[1].status == "error"
            assert json.loads(tools[1].content)["status"] == "not_found"
            assert store.search(("langmem", "run", "C", "alice")) == []
            projected_tools = [row for row in wires[1]["messages"] if row["role"] == "tool"]
            assert all(projected["content"].endswith(original.content)
                       for projected, original in zip(projected_tools, tools, strict=True))
    finally:
        world.close()


def test_unknown_business_side_effect_propagates_without_correction_or_replay(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    tools = _business_tools(world, "alice")
    actual = tools[0].func

    def unknown(**kwargs: Any) -> Any:
        actual(**kwargs)
        raise httpx.ReadTimeout("synthetic unknown outcome")

    tools[0].func = unknown
    journal = BusinessActionJournal(tmp_path / "business.json", BUSINESS_NAMES)
    try:
        with _runtime(
            tmp_path,
            store,
            wires,
            lambda _wire, _call: {
                "calls": [
                    {
                        "name": "reserve_and_label",
                        "arguments": {
                            "item_key": "parcel",
                            "quantity": 2,
                            "destination": "bay",
                            "packing": "box",
                        },
                    }
                ]
            },
        ) as runtime:
            agent = _agent(runtime, tmp_path, business=tools, wrapper=journal)
            with pytest.raises(httpx.ReadTimeout):
                invoke_public_message(agent, runtime.model, _scope(), "act")
            assert len(wires) == 1 and len(world.snapshot()["attempts"]) == 1
            assert not any(
                isinstance(row, ToolMessage)
                for row in agent.get_state(_scope().config()).values["messages"]
            )
    finally:
        world.close()


@pytest.mark.parametrize(("history", "boundaries"), [
    ("archive", False), ("retained", False), ("archive", True), ("retained", True)])
def test_actual_history_permission_and_owner_isolation(
    tmp_path: Path, history: str, boundaries: bool,
) -> None:
    store, wires = InMemoryStore(), []
    arm = "B0" if boundaries else "B1"
    with _runtime(tmp_path, store, wires, lambda _wire, _call: {"answer": "saved"}) as runtime:
        agent = _agent(runtime, tmp_path, arm, history=history, boundaries=boundaries)
        agent.update_state(
            _scope(arm, "old").config(),
            {
                "messages": [
                    HumanMessage(id="past-user", content="PAST_ARCHIVE_ONLY"),
                    AIMessage(id="past-final", content="past final"),
                ]
            },
            as_node="agent",
        )
        write_json(
            tmp_path / "phase-progress.json",
            {
                "messages": {
                    "past": {
                        "message_id": "past",
                        "session_id": "old",
                        "user_id": "alice",
                        "public_index": 0,
                        "visited_ordinal": 0,
                        "status": "COMPLETED",
                    }
                }
            },
        )
        bank = LocalStateBank(store)
        bank.record_event(
            StateScope("run", arm, "alice"),
            {
                "id": "audit-source",
                "kind": "user",
                "actor": "alice",
                "content": "SOURCE_ARCHIVE_ONLY",
            },
        )
        store.put(("langmem", "run", arm, "alice"), str(uuid.uuid4()), {"content": "KEPT_BODY"})
        store.put(("langmem", "run", arm, "bob"), str(uuid.uuid4()), {"content": "OTHER_OWNER"})
        invoke_public_message(agent, runtime.model, _scope(arm, "new"), "CURRENT")
        text = json.dumps(wires)
        assert ("PAST_ARCHIVE_ONLY" in text) == (history == "archive")
        assert ("read_history" in text) == (history == "archive")
        assert (
            "KEPT_BODY" in text and "SOURCE_ARCHIVE_ONLY" not in text and "OTHER_OWNER" not in text
        )
        assert (RESPONSIBILITY_PROMPT in wires[0]["messages"][0]["content"]) == (not boundaries)
        if boundaries:
            checkpoint = agent.get_state(_scope(arm, "new").config()).values["messages"]
            audit = operation_audit([row.model_dump(mode="json") for row in checkpoint],
                runtime.model.memory_turn, str(_scope(arm, "new").config()[
                    "configurable"]["thread_id"]))
            assert audit["operations"] == [] and not audit["observed_write"]
            assert audit["user_intent_satisfied"] is None


def test_prepared_phase_entry_reopens_retained_records_records_costs_and_refuses_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = {
        "kind": "MILAI_PERSISTENT_MEMORY_INPUTS",
        "workload": "application",
        "rubric_path": str(tmp_path / "never-read.json"),
        "script": {
            "users": ["alice"],
            "initial_label_available": False,
            "phases": [
                {
                    "id": index,
                    "operator_memory": [],
                    "world_events": [],
                    "messages": [
                        {
                            "message_id": str(index),
                            "user_id": "alice",
                            "session_id": str(index),
                            "public_index": 0,
                            "text": text,
                        }
                    ],
                }
                for index, text in enumerate(("OLD_SESSION_USER", "CURRENT_SESSION_USER"))
            ],
        },
    }
    args = SimpleNamespace(
        config=tmp_path / "config.json",
        inputs=tmp_path / "inputs.json",
        runtime_root=tmp_path / "runtime",
        output=tmp_path / "prepared.json",
        prepared=tmp_path / "prepared.json",
        run="run",
        arm="C",
        phase=0,
        stage="synthetic",
    )
    write_json(args.config, _config(args.runtime_root))
    write_json(args.inputs, inputs)
    store, wires = InMemoryStore(), []

    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return _final("committed")
        if call == 2:
            return {"calls": [{"name": "manage_memory", "arguments": {"content": "KEPT_BODY"}}]}
        return _final("committed", ["generation-2:tool:0"]) if call == 3 else _final("no_change")

    @contextmanager
    def open_runtime(
        _config: Any, _run: str, _arm: str, root: Path, _stage: str, **kwargs: Any
    ) -> Any:
        assert kwargs == {"enable_projection": False}
        with _runtime(root, store, wires, respond) as runtime:
            yield runtime

    monkeypatch.setattr(runner, "open_application_runtime", open_runtime)
    prepared = runner.prepare(args, lab_root=LAB)
    assert prepared["public_messages"] == 2
    identity = read_json(args.runtime_root / "run_manifest.json")["identity"]
    assert identity["correction_entries"] == 1 and not identity["automatic_maintenance"]
    args.phase = 1
    with pytest.raises(ValueError, match="PERSISTENT_MEMORY_PHASE_OUT_OF_ORDER"):
        runner.run(args, lab_root=LAB)
    args.phase = 0
    runner.run(args, lab_root=LAB)
    assert read_json(args.runtime_root / "run_manifest.json")["status"] == "PHASE_COMPLETED"
    args.phase = 1
    result = runner.run(args, lab_root=LAB)
    assert result["world"]["attempts"] == []
    assert len(wires) == 4
    assert "KEPT_BODY" in json.dumps(wires[-1]) and "OLD_SESSION_USER" not in json.dumps(wires[-1])
    turns = [read_json(path) for path in (args.runtime_root / "turns").glob("*.json")]
    assert len(turns) == 2 and all(row["status"] == "COMPLETED" for row in turns)
    assert all(row["ordinary_records"][0]["value"]["content"] == "KEPT_BODY" for row in turns)
    manifest = read_json(args.runtime_root / "run_manifest.json")
    accounting = manifest["accounting"]
    assert manifest["status"] == "TERMINAL"
    assert accounting["by_role"]["task_host"]["requests"] == 4
    assert accounting["by_control_stage"] == {}
    assert accounting["v3_checkpoint_costs"]["persistent_memory_checkpoint_read"]["calls"] == 2
    assert accounting["v3_checkpoint_costs"]["correction_checkpoint_write"]["calls"] == 1
    assert accounting["v3_checkpoint_costs"]["correction_checkpoint_write"]["logical_bytes"] > 0
    assert accounting["physical_store_io"] is None
    with pytest.raises(ValueError, match="PERSISTENT_MEMORY_ATTEMPT_ALREADY_STARTED"):
        runner.run(args, lab_root=LAB)
    assert len(wires) == 4
