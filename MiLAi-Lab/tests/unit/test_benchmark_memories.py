"""U2 real archive algorithms and public graph boundaries, using synthetic records."""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langgraph.store.memory import InMemoryStore
from test_unified_benchmarks import call, runtime, task

from milai_lab.baselines.benchmark_memories import (
    MEM0_POLICY,
    RAG_POLICY,
    SUMMARY_POLICY,
    archived_turns,
    raw_chunks,
    raw_index,
    raw_retrieve,
    rolling_archive,
    summary_material,
)
from milai_lab.baselines.langmem_agent import FoundationScope, invoke_public_message
from milai_lab.baselines.langmem_benchmark import merit_adapters
from milai_lab.datasets.memsyco import MemSycoTask
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import memsyco_native


def config() -> dict[str, Any]:
    return {"host": {"timeout": 180}, "embedding": {"timeout": 180, "model": "bge-m3"},
            "history": {"enabled": True, "page_max_bytes": 16384},
            "history_mode": "archive_access", "benchmark_memory": {
                "summary": SUMMARY_POLICY, "raw_rag": RAG_POLICY, "mem0": MEM0_POLICY}}


def records(count: int) -> list[dict[str, Any]]:
    return [{"event_id": f"{role}-{index}", "role": role, "content": f"{role} exact {index}"}
            for index in range(count) for role in ("user", "assistant")]


def test_real_rolling_archive_prior_summary_whole_batches_and_degraded_fallback(
    tmp_path: Path,
) -> None:
    wires: list[dict[str, Any]] = []
    source = records(5)
    replies = [{"role": "assistant", "content": json.dumps({"summary": f"Summary {index}"})}
               for index in range(3)]
    with runtime(tmp_path, replies, InMemoryStore(), wires) as rt:
        capacity = rt.model.client.capacity

        class WholeBatch:
            enable_thinking = False

            def check(self, messages: Any, output: int, tools: Any = None) -> dict[str, Any]:
                if len(json.loads(messages[-1]["content"])["new_completed_turns"]) > 1:
                    raise CapacityExceeded({"reason": "synthetic whole-turn batch boundary"})
                return capacity.check(messages, output, tools)

        rt.model.client.capacity = WholeBatch()
        built = rolling_archive(rt.model.client, source)
        assert [row["source_turn_ordinals"] for row in built["updates"]] == [[0], [1], [2]]
        assert [json.loads(wire["messages"][-1]["content"])["prior_summary"]
                for wire in wires] == ["", "Summary 0", "Summary 1"]
        assert all(wire["max_tokens"] == 2048 for wire in wires)
        assert rt.model.client.config.max_tokens == 4096
        assert rt.model.client.budget.state["generation_requests"] == 3
        assert built["covered_ordinal"] == 2 and len(built["recent_turns"]) == 2
        assert "assistant exact 4" in summary_material(built, source)
    failed_wires: list[dict[str, Any]] = []
    with runtime(tmp_path / "failed", [{"role": "assistant", "content": "invalid JSON"}],
                 InMemoryStore(), failed_wires) as rt:
        failed = rolling_archive(rt.model.client, source)
        assert failed["degraded"] and failed["covered_ordinal"] == -1
        assert "DEGRADED" in summary_material(failed, source)
        assert all(row["content"] in summary_material(failed, source) for row in source)
        assert rt.model.client.budget.state["generation_requests"] == 1


def test_archive_role_boundaries_preserve_tool_results_and_unclosed_data() -> None:
    source = [{"event_id": "u", "role": "user", "content": "Past request"},
              {"event_id": "a", "role": "assistant", "content": "proposal",
               "tool_calls": [{"id": "c", "name": "business", "args": {}}]},
              {"event_id": "t", "role": "tool", "tool_call_id": "c", "content": "partial"},
              {"event_id": "f", "role": "assistant", "content": "Actual final"},
              {"event_id": "open", "role": "user", "content": "Unclosed past request"}]
    turns, unclosed = archived_turns(source)
    assert turns[0]["messages"] == source[:4]
    assert turns[0]["source_ids"] == ["u", "a", "t", "f"]
    assert unclosed == source[4:]


def test_hybrid_real_bm25_dense_stable_ties_whole_chunks_and_incremental_embeddings() -> None:
    embedded: list[list[str]] = []

    def embed(texts: list[str]) -> list[list[float]]:
        embedded.append(texts)
        return [[1.0, 0.0] for _ in texts]

    source = [{"event_id": "first", "role": "user", "content": "Silent note"},
              {"event_id": "second", "role": "assistant", "content": "Cobalt Cobalt exact"}]
    index = raw_index(source, embed)
    selected = raw_retrieve(index, "Cobalt", embed)
    assert selected["ranked_ids"][0] == index["chunks"][1]["id"]
    assert selected == raw_retrieve(index, "Cobalt", embed) | {
        "wall_ns": selected["wall_ns"], "cpu_ns": selected["cpu_ns"]}
    updated = raw_index([*source, {"event_id": "new", "role": "user", "content": "New note"}],
                        embed, index)
    assert updated["new_embedding_chunks"] == 1 and len(embedded[-1]) == 1
    assert raw_index(source, embed, index)["new_embedding_chunks"] == 0
    chunks = raw_chunks([{"event_id": "long", "content": "x" * 21000}])
    assert (chunks[0].start, chunks[0].end, chunks[1].start) == (0, 2048, 1792)
    large = {"chunks": [asdict(row) for row in chunks], "vectors": [[1, 0] for _ in chunks]}
    limited = raw_retrieve(large, "x", embed)
    assert limited["omitted_ids"] and len(limited["material"]) <= 16000
    assert all(value["content"] == chunks[next(index for index, row in enumerate(chunks)
        if row.id == value["id"])].content for value in json.loads(limited["material"]))
    competing = raw_index([{"event_id": str(index), "content": "Cobalt " * repeat}
                           for index, repeat in enumerate((6, 2, 1))], embed)
    lexical_winner = raw_retrieve(competing, "Cobalt", embed)["ranked_ids"][0]
    competing["vectors"] = [[0.0, 1.0], [1.0, 0.0], [0.7, 0.7]]
    fused_winner = raw_retrieve(competing, "Cobalt", embed)["ranked_ids"][0]
    assert lexical_winner == competing["chunks"][0]["id"]
    assert fused_winner == competing["chunks"][1]["id"] != lexical_winner


@pytest.mark.parametrize("backend", ["full_history", "rolling_summary", "strong_raw_rag"])
def test_public_graph_current_query_no_lookahead_read_history_tool_chain_and_summary_cap(
    tmp_path: Path, backend: str,
) -> None:
    store, wires, embed_wires = InMemoryStore(), [], []
    write_json(tmp_path / "run_manifest.json", {"identity": {"run_id": "r", "arm_id": backend}})
    replies = [{"role": "assistant", "content": f"Prior final {index}"} for index in range(3)]
    if backend == "rolling_summary":
        replies.append({"role": "assistant", "content": '{"summary":"Earlier exact 0"}'})
    replies += [{"role": "assistant", "content": None, "tool_calls": [
        call("read_history", {"cursor": 0, "max_bytes": 16384}, "history-read")]},
        {"role": "assistant", "content": "Current final"}]

    def embedding(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.read())
        embed_wires.append(data)
        return httpx.Response(200, json={"data": [{"index": index, "embedding": [1.0, 0.0]}
            for index, _ in enumerate(data["input"])], "usage": {"total_tokens": 3}})

    with runtime(tmp_path, replies, store, wires) as rt, ExitStack() as stack:
        rt.embedding_client = stack.enter_context(VLLMClient(
            VLLMConfig("http://mock/v1/", "bge-m3"), budget=rt.model.client.budget,
            emit=rt.model.client.emit, transport=httpx.MockTransport(embedding)))
        factory, completed = merit_adapters(rt, tmp_path, "r", backend, config(), stack,
                                            backend=backend)
        agent = factory(rt.model, store, rt.checkpointer, (), user_id="owner",
                        environment_rules="Original native domain rules", observer=None)
        for index in range(4):
            scope = FoundationScope("r", backend, "owner", f"session-{index}")
            invoke_public_message(agent, rt.model, scope,
                f"Prior request {index}" if index < 3 else "CURRENT QUERY FULL BYTE STRING", 0)
            completed(agent, scope, 0, "COMPLETED", [])
        assert rt.model.calls_in_message == (3 if backend == "rolling_summary" else 2)
        assert all("FUTURE_QUERY_SENTINEL" not in json.dumps(wire) for wire in wires)
        last = wires[-1]
        assert {row["function"]["name"] for row in last["tools"]} == {"read_history"}
        assert [row["tool_call_id"] for row in last["messages"] if row["role"] == "tool"] == [
            "history-read"]
        assert last["messages"][-3]["content"] == "CURRENT QUERY FULL BYTE STRING"
        assert "Prior final 0" in last["messages"][-1]["content"]
        if backend == "rolling_summary":
            summary = [wire for wire in wires if wire.get("response_format")]
            assert len(summary) == 1 and summary[0]["max_tokens"] == 2048
            assert "CURRENT QUERY" not in json.dumps(summary)
        if backend == "strong_raw_rag":
            assert sum(row["input"] == ["CURRENT QUERY FULL BYTE STRING"]
                       for row in embed_wires) == 1
        assert store.search(("memories", "r", backend, "owner")) == []


def test_exact_archive_key_excludes_questions_but_never_merges_source_or_owner() -> None:
    first = task()
    changed = replace(first, question="Different query")
    owner = replace(first, user_id="foreign")
    source = replace(first, history_id="different source")
    identity = {"arm_id": "raw_dialogue", "memory_tool_catalog": [],
        "config": {"recipe_id": "r", "host": {}, "embedding": {}, "formation_instruction": "f"},
        "source_sha256": {}, "config_sha256": "config"}
    tasks = [MemSycoTask(str(index), "valid_memory_selection", row)
             for index, row in enumerate((first, changed, owner, source))]
    jobs = [{"job_id": row.case_id} for row in tasks]
    units = memsyco_native._history_inputs(tasks, identity, jobs)
    assert len(units["histories"]) == 3
    assert jobs[0]["build_history_id"] == jobs[1]["build_history_id"]
    assert "Different query" not in json.dumps(units)
    assert first.question not in json.dumps(units)
    assert len({row["build_history_id"] for row in jobs}) == 3
    assert all("question" not in row["archive"] for row in units["histories"])


def test_application_runtime_default_and_same_embedding_budget_reference() -> None:
    from milai_lab.runners.langmem_application_runtime import ApplicationRuntime

    client = SimpleNamespace(budget=object())
    model = SimpleNamespace(client=client)
    assert ApplicationRuntime(model, None, None, None).embedding_client is None
    shared = ApplicationRuntime(model, None, None, None, client)
    assert shared.embedding_client is shared.model.client


def test_u2_configuration_is_explicit_and_does_not_accept_old_capacity_expansion() -> None:
    from milai_lab.baselines.benchmark_memories import validate_u2

    validate_u2(config())
    wrong = config()
    wrong["benchmark_memory"] = {**wrong["benchmark_memory"], "summary": {
        **SUMMARY_POLICY, "max_tokens": 4096}}
    with pytest.raises(ValueError, match="CONFIG_INVALID"):
        validate_u2(wrong)


@pytest.mark.parametrize("backend", ["raw_dialogue", "rolling_summary", "strong_raw_rag",
                                     "ordinary_milai"])
def test_memsyco_u2_frozen_history_build_fresh_query_gold_free_and_once_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    from milai_lab.baselines.langmem_benchmark import FORMATION_INSTRUCTION

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
        '    return "EMPTY" if not memories else "\\n".join(m["content"] for m in memories)\n')
    source = external / "source.jsonl"
    source.write_text(json.dumps({"id": "synthetic", "task": "valid_memory_selection",
        "dialogue": [{"role": row["role"], "content": row["content"]} for row in records(4)],
        "question": "CURRENT_QUESTION_SENTINEL", "memory": "FORBIDDEN_GOLD",
        "evaluation": {"answer": "FORBIDDEN_GOLD"}, "metadata": "FORBIDDEN_GOLD"}) + "\n")
    selection = tmp_path / "selection.json"
    write_json(selection, {"external_root": str(external), "source_commit": "synthetic",
        "source_files": [{"task": "valid_memory_selection", "relative_path": source.name,
                          "sha256": memsyco_native.sha(source)}],
        "groups": {"smoke": {"cases": [{"task": "valid_memory_selection",
                                         "case_id": "synthetic"}]}}})
    settings = {**config(), "recipe_id": "u2-synthetic", "memory_contract": "strict",
        "memory_transport": "mcp_http", "host": {"tool_mode": "native", "max_tokens": 4096,
        "max_calls": 12, "temperature": 0, "enable_thinking": False, "model": "synthetic-native",
        "timeout": 180}, "capacity": {"enable_thinking": False},
        "budget_path": str(tmp_path / "budget.json"),
        "formation_instruction": FORMATION_INSTRUCTION,
        "reader": {"current_date": "2025-06-01", "extra_instruction": ""},
        "retrieval": {"limit": 10, "material_max_chars": 16000},
        "agent_query": {"system_prompt": "Read-only query"}}
    path = tmp_path / "config.json"
    write_json(path, settings)
    args = SimpleNamespace(config=path, selection=selection, arm=backend, group="smoke", run="r",
        runtime_root=tmp_path / "runtime", formation_root=None, job="synthetic",
        output=tmp_path / "prepared.json", prepared=tmp_path / "prepared.json")
    monkeypatch.setattr(memsyco_native, "source_identity", lambda _root: {"source_sha256": {}})
    memsyco_native.prepare(args, lab_root=tmp_path)
    units = read_json(args.runtime_root / "runtime-histories.json")
    args.history = units["histories"][0]["history_id"]
    assert "CURRENT_QUESTION" not in json.dumps(units) and "FORBIDDEN_GOLD" not in json.dumps(units)
    replies: list[dict[str, Any]] = []
    if backend == "rolling_summary":
        replies.append({"role": "assistant", "content": '{"summary":"Earlier exact note"}'})
    if backend == "ordinary_milai":
        replies.extend([{"role": "assistant", "content": None, "tool_calls": [
            call("manage_memory", {"action": "create", "content": "Exact persisted note"}, "c")]},
            {"role": "assistant", "content": "Real acknowledgement"}])
    replies.append({"role": "assistant", "content": "Official reader final"})
    store, wires, embed_wires = InMemoryStore(), [], []

    def embedding(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.read())
        embed_wires.append(data)
        return httpx.Response(200, json={"data": [{"index": index, "embedding": [1.0, 0.0]}
            for index, _ in enumerate(data["input"])], "usage": {"total_tokens": 3}})

    @contextmanager
    def local_runtime(_config: Any, _run: str, _arm: str, root: Path) -> Any:
        with runtime(root, replies, store, wires) as rt, VLLMClient(VLLMConfig(
            "http://mock/v1/", "bge-m3"), budget=rt.model.client.budget,
            emit=rt.model.client.emit, transport=httpx.MockTransport(embedding)) as embed:
            rt.embedding_client = embed
            yield rt

    def reject_original_parse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("execution cannot parse gold-bearing source rows")

    monkeypatch.setattr(memsyco_native, "_runtime", local_runtime)
    monkeypatch.setattr(memsyco_native, "load_memsyco_tasks", reject_original_parse)
    args.output = tmp_path / "formed.json"
    formed = memsyco_native.run_history(args, lab_root=tmp_path)
    assert formed["status"] == "COMPLETED"
    assert "CURRENT_QUESTION" not in json.dumps(wires)
    with pytest.raises(ValueError, match="HISTORY_ALREADY_ATTEMPTED"):
        memsyco_native.run_history(args, lab_root=tmp_path)
    args.output = tmp_path / "queried.json"
    result = memsyco_native.run(args, lab_root=tmp_path)
    assert result["answer"] == "Official reader final"
    assert wires[-1]["messages"][1]["content"] == "CURRENT_QUESTION_SENTINEL"
    assert "FORBIDDEN_GOLD" not in json.dumps(wires)
    if backend == "strong_raw_rag":
        assert embed_wires[-1]["input"] == ["CURRENT_QUESTION_SENTINEL"]
        assert formed["costs"]["roles"]["embedding:raw_index_build"]["requests"] == 1
    if backend == "ordinary_milai":
        assert result["records_before"] == result["records_after"]
        assert formed["costs"]["roles"]["formation"]["requests"] == 2
    assert result["costs"]["roles"]["reader"]["requests"] == 1
    with pytest.raises(ValueError, match="JOB_ALREADY_ATTEMPTED"):
        memsyco_native.run(args, lab_root=tmp_path)
