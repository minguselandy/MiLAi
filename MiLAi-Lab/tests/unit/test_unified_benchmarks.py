"""Synthetic benchmark permissions/real MCP/graph tests, with no evaluator inputs."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore
from mcp.shared.exceptions import MCPError

from milai_lab.baselines.langmem_agent import FoundationScope
from milai_lab.baselines.langmem_benchmark import (
    FORMATION_INSTRUCTION,
    agent_query,
    archive_input,
    form,
    formation_input,
    formation_key,
    merit_adapters,
    raw_dialogue,
    reader_functions,
    retrieved_material,
)
from milai_lab.baselines.langmem_mcp import MemoryMCP
from milai_lab.datasets.contextual import HistoryMessage, TaskInput
from milai_lab.datasets.memsyco import TRACKS, load_memsyco_tasks
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, Trace, write_json
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners import memsyco_native
from milai_lab.runners.merit_native import finish_job, prepare_manifest, start_job


@contextmanager
def runtime(tmp_path: Path, responses: list[dict[str, Any]], store: Any,
            wires: list[dict[str, Any]]) -> Any:
    def send(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        message = responses.pop(0)
        return httpx.Response(200, json={"id": "real-mock-receipt-" + str(len(wires)),
            "model": "synthetic-native", "object": "chat.completion", "created": 1,
            "choices": [{"index": 0, "message": message, "finish_reason": (
                "tool_calls" if message.get("tool_calls") else "stop")}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}})

    budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
        generation_tokens=None, embedding_tokens=None), tmp_path / "budget.json")
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="synthetic-native",
        tool_mode="native", max_tokens=4096, enable_thinking=False), budget=budget,
        emit=Trace(tmp_path / "trace.jsonl", "synthetic-benchmark"),
        transport=httpx.MockTransport(send)) as client, SqliteSaver.from_conn_string(
            str(tmp_path / "checkpoint.sqlite")) as saver:
        class Capacity:
            enable_thinking = False

            def text_tokens(self, text: str) -> int:
                return len(text)

            def check(self, messages: Any, output: int, tools: Any = None) -> dict[str, Any]:
                prompt = len(json.dumps(messages)) + len(json.dumps(tools))
                return {"prompt_tokens": prompt, "output_reserve_tokens": output,
                        "total_reserved_tokens": prompt + output + 512}

        client.capacity = Capacity()
        model = VLLMChatModel(client=client)
        yield SimpleNamespace(model=model, store=store, checkpointer=saver, observer=None)


def call(name: str, args: dict[str, Any], key: str) -> dict[str, Any]:
    return {"id": key, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args)}}


def task() -> TaskInput:
    return TaskInput("owner", "archive", (HistoryMessage("source", "user", "Past note"),),
                     "QUESTION_MUST_NOT_BE_IN_FORMATION")


def test_formation_actual_agent_mcp_then_read_only_query_no_ownership_leak(tmp_path: Path) -> None:
    store, wires, events = InMemoryStore(), [], []
    responses = [
        {"role": "assistant", "content": "proposal", "tool_calls": [
            call("manage_memory", {"action": "create", "content": "Exact durable note"}, "c1")]},
        {"role": "assistant", "content": "Actual note saved."},
        {"role": "assistant", "content": None, "tool_calls": [
            call("search_memory", {"query": "Exact", "limit": 10}, "s1")]},
        {"role": "assistant", "content": "Answer using actual retrieval."},
    ]
    with runtime(tmp_path, responses, store, wires) as rt:
        with MemoryMCP(store, "run", "milai", "owner", emit=events.append) as peer:
            formed = form(rt, peer, archive_input(task()), "run", "milai", FORMATION_INSTRUCTION)
        assert formed["records_before"] == []
        assert formed["records_after"][0]["value"]["content"] == "Exact durable note"
        assert "QUESTION_MUST_NOT" not in json.dumps(wires[:2])
        assert "source" in wires[0]["messages"][-1]["content"]
        assert formed["messages"][2]["type"] == "tool"
        with MemoryMCP(store, "run", "milai", "owner", read_only=True,
                       emit=events.append) as peer:
            assert {row["function"]["name"] for row in peer.catalog} == {
                "search_memory", "read_memory"}
            result = agent_query(rt, peer, task(), "run", "milai", "Read only.")
            assert result["records_before"] == result["records_after"]
            with pytest.raises(MCPError):
                peer.call("manage_memory", {"content": "forbidden"}, "bad", origin="host",
                          config=FoundationScope("run", "milai", "owner", "x").config())
            with pytest.raises(ValueError, match="SCOPE_CHANGED"):
                peer.records(FoundationScope("run", "milai", "foreign", "x").config())
        assert rt.model.client.budget.state["generation_requests"] == 4
        assert rt.model.client.budget.state["generation"]["known_tokens"] == 36
    assert [row["tool_call_id"] for row in wires[1]["messages"] if row["role"] == "tool"] == ["c1"]
    assert [row["tool_call_id"] for row in wires[3]["messages"] if row["role"] == "tool"] == ["s1"]
    assert any(row.get("kind") == "http" and '"tools/call"' in row["request_body"]
               for row in events)


def test_formation_cache_excludes_question_answer_and_keeps_owner_source() -> None:
    original = task()
    changed_query = TaskInput(original.user_id, original.history_id, original.history, "different")
    changed_owner = TaskInput("foreign", original.history_id, original.history, original.question)
    assert formation_key(archive_input(original), {"tool": "strict"}) == formation_key(
        archive_input(changed_query), {"tool": "strict"})
    assert formation_key(archive_input(original), {}) != formation_key(
        archive_input(changed_owner), {})
    assert original.question not in formation_input(original.history, FORMATION_INSTRUCTION)


@pytest.mark.parametrize("track", sorted(TRACKS))
def test_task_loader_three_tracks_declared_group_and_runtime_gold_isolation(
    tmp_path: Path, track: str,
) -> None:
    source = tmp_path / "data.jsonl"
    # Gold fields deliberately have unusable shapes. Runtime must never access them.
    source.write_text(json.dumps({"id": "selected", "task": track,
        "dialogue": [{"role": "assistant", "content": "Past"}], "question": "Current",
        "evaluation": "GOLD", "memory": "GOLD", "metadata": "GOLD"}) + "\n")
    selection = tmp_path / "selection.json"
    write_json(selection, {"source_commit": "synthetic", "external_root": str(tmp_path),
        "source_files": [{"task": track, "relative_path": source.name}],
        "groups": {"development": {"cases": [{"task": track, "case_id": "selected"}]}}})
    (row,) = load_memsyco_tasks(selection, group="development")
    assert row.track == track and row.task.question == "Current"
    assert "GOLD" not in json.dumps(asdict(row))
    with pytest.raises(ValueError, match="outside development"):
        load_memsyco_tasks(selection, group="development", case_ids=["unselected"])


def test_reader_native_pure_functions_labels_whole_record_budget_and_no_gold(
    tmp_path: Path,
) -> None:
    (tmp_path / "evaluation").mkdir()
    (tmp_path / "baselines").mkdir()
    (tmp_path / "evaluation/task_valid_memory_selection.py").write_text(
        'raise RuntimeError("EVALUATOR_MUST_NOT_LOAD")\n'
        'ANSWER_SYSTEM_PROMPT_BASE="{model_name}/{current_date}"\n'
        'def answer_system_prompt(model_name,current_date,prior_dialogue,context_label):\n'
        '    return ANSWER_SYSTEM_PROMPT_BASE.format(model_name=model_name, '
        'current_date=current_date)+"\\n"+context_label+"\\n"+prior_dialogue\n')
    (tmp_path / "baselines/common.py").write_text(
        'raise RuntimeError("REGISTRY_MUST_NOT_LOAD")\n'
        'def format_retrieved_memories(memories):\n'
        '    return "[NO RETRIEVED MEMORIES]" if not memories else "\\n\\n".join('
        'f"### Memory {i}:\\n{m[\'content\'].strip()}" '
        'for i,m in enumerate(memories,1))\n')
    prompt, formatter = reader_functions(tmp_path, "valid_memory_selection")
    material, ids, omitted = retrieved_material([
        {"id": "one", "value": {"content": "Small"}},
        {"id": "large", "value": {"content": "X" * 100}}], formatter, 30)
    assert material == "### Memory 1:\nSmall" and ids == ["one"] and omitted == ["large"]
    assert prompt("model", "2025-06-01", material,
                  "Retrieved memories from earlier conversation").endswith(material)
    assert raw_dialogue(task()) == "User: Past note"


def test_merit_actual_graph_archive_final_and_current_prefix_once(tmp_path: Path) -> None:
    from contextlib import ExitStack

    from milai_lab.baselines.langmem_agent import invoke_public_message

    store, wires = InMemoryStore(), []
    write_json(tmp_path / "run_manifest.json", {"identity": {"run_id": "r", "arm_id": "milai"}})
    config = {"host": {"timeout": 180}, "embedding": {"timeout": 180},
        "history": {"page_max_bytes": 16384},
        "memory_boundaries": {"enabled": True, "memory_placement": "current_request",
                              "model_view": "compact_v6"}}
    with runtime(tmp_path, [{"role": "assistant", "content": "Previous final"},
                           {"role": "assistant", "content": "Current final"}], store, wires) as rt:
        with ExitStack() as stack:
            factory, completed = merit_adapters(rt, tmp_path, "r", "milai", config, stack)
            agent = factory(rt.model, store, rt.checkpointer, (), user_id="owner",
                            environment_rules="Native domain instructions", observer=None)
            first = FoundationScope("r", "milai", "owner", "episode:0")
            invoke_public_message(agent, rt.model, first, "Earlier request", 0)
            completed(agent, first, 0, "COMPLETED", [])
            second = FoundationScope("r", "milai", "owner", "episode:1")
            invoke_public_message(agent, rt.model, second, "Current request", 0)
            completed(agent, second, 0, "COMPLETED", [])
    content = json.dumps(wires[1]["messages"])
    assert content.count("Earlier request") >= 1 and "Previous final" in content
    assert sum(row["role"] == "user" and row["content"].endswith("Current request")
               for row in wires[1]["messages"]) == 1
    assert {row["function"]["name"] for row in wires[1]["tools"]} == {
        "manage_memory", "search_memory", "read_memory", "read_history"}


def test_order_once_attempt_failure_and_prepared_identity_guard(tmp_path: Path) -> None:
    args = SimpleNamespace(runtime_root=tmp_path / "run", output=tmp_path / "prepared.json",
                           prepared=tmp_path / "prepared.json", job="second")
    identity = {"run_id": "r"}
    jobs = [{"job_id": "first"}, {"job_id": "second"}]
    prepare_manifest(args, identity, jobs)
    with pytest.raises(ValueError, match="JOB_ORDER"):
        start_job(args, identity=identity, jobs=jobs)
    args.job = "first"
    manifest, _, root = start_job(args, identity=identity, jobs=jobs)
    assert root.is_dir()
    finish_job(args, manifest, "FAILED", error=TimeoutError())
    with pytest.raises(ValueError, match="ALREADY_ATTEMPTED"):
        start_job(args, identity=identity, jobs=jobs)
    args.job = "second"
    start_job(args, identity=identity, jobs=jobs)
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        prepare_manifest(args, {"run_id": "other"}, jobs)


def test_native_reader_rejects_incomplete_after_accounted_http(tmp_path: Path) -> None:
    wires = []
    with runtime(tmp_path, [{"role": "assistant", "content": None}], InMemoryStore(), wires) as rt:
        with pytest.raises(ValueError, match="READER_RESPONSE_INCOMPLETE"):
            memsyco_native._answer(rt.model.client, "Official system", "Current question")
        assert rt.model.client.budget.state["generation_requests"] == 1
        assert rt.model.client.budget.state["generation"]["known_tokens"] == 9
    assert len(wires) == 1


def test_read_only_agent_allows_zero_tools_and_does_not_mutate_records(tmp_path: Path) -> None:
    store, wires = InMemoryStore(), []
    with runtime(tmp_path, [{"role": "assistant", "content": "Natural zero-tool answer"}],
                 store, wires) as rt, MemoryMCP(store, "r", "a", "owner", read_only=True) as peer:
        result = agent_query(rt, peer, task(), "r", "a", "Read-only system")
        assert result["records_before"] == result["records_after"] == []
    assert len(wires) == 1 and wires[0]["tool_choice"] == "auto"
    assert "manage_memory" not in json.dumps(wires[0]["tools"])


@pytest.mark.parametrize("arm", ["raw_dialogue", "milai"])
def test_prepare_sanitizes_gold_and_run_reads_only_frozen_runtime_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str,
) -> None:
    # Public synthetic reader source, not a downloaded benchmark/evaluator fixture.
    external = tmp_path / "external"
    (external / "evaluation").mkdir(parents=True)
    (external / "baselines").mkdir()
    (external / "evaluation/task_valid_memory_selection.py").write_text(
        'ANSWER_SYSTEM_PROMPT_BASE="{model_name}/{current_date}"\n'
        'def answer_system_prompt(model_name,current_date,prior_dialogue,context_label):\n'
        '    return ANSWER_SYSTEM_PROMPT_BASE.format(model_name=model_name, '
        'current_date=current_date)+"\\n"+context_label+"\\n"+prior_dialogue\n')
    (external / "baselines/common.py").write_text(
        'def format_retrieved_memories(memories):\n'
        '    return "[NO RETRIEVED MEMORIES]" if not memories else "\\n".join('
        'm["content"] for m in memories)\n')
    source = external / "data.jsonl"
    source.write_text(json.dumps({"id": "synthetic", "task": "valid_memory_selection",
        "dialogue": [{"role": "user", "content": "Original past note"}],
        "question": "Fresh current question", "memory": "SECRET_GOLD",
        "evaluation": {"reference_answer": "SECRET_GOLD"}, "metadata": "SECRET_GOLD"}) + "\n")
    selection = tmp_path / "selection.json"
    write_json(selection, {"external_root": str(external), "source_commit": "synthetic",
        "source_files": [{"task": "valid_memory_selection", "relative_path": "data.jsonl",
                          "sha256": memsyco_native.sha(source)}],
        "groups": {"smoke": {"cases": [{"task": "valid_memory_selection",
                                         "case_id": "synthetic"}]}}})
    config_path = tmp_path / "config.json"
    write_json(config_path, {"recipe_id": "synthetic", "memory_contract": "strict",
        "memory_transport": "mcp_http",
        "host": {"tool_mode": "native", "max_tokens": 4096, "max_calls": 12,
                 "temperature": 0, "enable_thinking": False, "model": "synthetic-native",
                 "timeout": 180}, "capacity": {"enable_thinking": False},
        "budget_path": str(tmp_path / "budget.json"), "embedding": {"timeout": 180},
        "formation_instruction": FORMATION_INSTRUCTION,
        "reader": {"current_date": "2025-06-01", "extra_instruction": ""},
        "retrieval": {"limit": 10, "material_max_chars": 16000},
        "agent_query": {"system_prompt": "Read only."}})
    args = SimpleNamespace(config=config_path, selection=selection, arm=arm, run="r",
        group="smoke", runtime_root=tmp_path / "jobroot", formation_root=None,
        output=tmp_path / "prepared.json", prepared=tmp_path / "prepared.json", job="synthetic")
    monkeypatch.setattr(memsyco_native, "source_identity", lambda _root: {"source_sha256": {}})
    memsyco_native.prepare(args, lab_root=tmp_path)
    assert "SECRET_GOLD" not in (args.runtime_root / "runtime-tasks.json").read_text()

    def no_source_parse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("runtime must not parse original evaluation rows")

    monkeypatch.setattr(memsyco_native, "load_memsyco_tasks", no_source_parse)
    wires, store = [], InMemoryStore()
    responses = ([{"role": "assistant", "content": None, "tool_calls": [
        call("manage_memory", {"action": "create", "content": "Original past note"}, "c")]},
        {"role": "assistant", "content": "Real write acknowledgement"}] if arm == "milai" else [])
    responses.append({"role": "assistant", "content": "Reader final answer"})
    monkeypatch.setattr(memsyco_native, "_runtime", lambda _cfg, _run, _arm, root: runtime(
        root, responses, store, wires))
    args.output = tmp_path / "executed.json"
    result = memsyco_native.run(args, lab_root=tmp_path)
    assert result["answer"] == "Reader final answer"
    assert "SECRET_GOLD" not in json.dumps(wires)
    assert all("Fresh current question" not in json.dumps(wire)
               for wire in wires[:-1])
    assert wires[-1]["messages"][1]["content"] == "Fresh current question"
    expected_roles = {"reader": {"requests": 1, "known_tokens": 9, "unknown_usage": 0}}
    if arm == "milai":
        expected_roles["formation"] = {"requests": 2, "known_tokens": 18, "unknown_usage": 0}
    assert result["costs"]["roles"] == expected_roles
    assert result["costs"]["physical_io"] is None
    assert "Retrieved memories from earlier conversation" in wires[-1]["messages"][0][
        "content"] if arm == "milai" else "Earlier conversation" in wires[-1]["messages"][0][
        "content"]
    with pytest.raises(ValueError, match="ALREADY_ATTEMPTED"):
        memsyco_native.run(args, lab_root=tmp_path)
