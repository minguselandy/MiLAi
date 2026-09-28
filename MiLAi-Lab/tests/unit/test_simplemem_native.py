"""Actual pinned core/LanceDB/Tantivy with metered MockHTTP, no shared services."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.memory import InMemoryStore
from test_benchmark_memories import config
from test_unified_benchmarks import call, runtime

from milai_lab.baselines.benchmark_memories import GenerationAdmission
from milai_lab.baselines.langmem_agent import FoundationScope, invoke_public_message
from milai_lab.baselines.langmem_benchmark import merit_adapters
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, write_json
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.simplemem_native import POLICY, SimpleMemTextRuntime, validate_simplemem


def policy() -> dict[str, Any]:
    # CI prepares this exact source. Missing dependencies/assets fail, never skip.
    source = os.environ.get("SIMPLEMEM_TEXT_SOURCE", "artifacts/simplemem-text/source")
    return {**POLICY, "source_root": str(Path(source).resolve())}


def entry() -> list[dict[str, Any]]:
    return [
        {
            "lossless_restatement": "Cobalt meeting in Lab with Alice",
            "keywords": ["Cobalt", "meeting"],
            "persons": ["Alice"],
            "location": "Lab",
            "entities": ["Cobalt"],
            "topic": "meeting",
        }
    ]


def plans(*, reflection: bool = False) -> list[dict[str, Any]]:
    rows = [
        {"required_info": [{"description": "meeting"}], "minimal_queries_needed": 1},
        {"queries": ["Cobalt"]},
        {"keywords": ["Cobalt"], "persons": ["Alice"], "location": "Lab"},
        {"assessment": "incomplete" if reflection else "complete"},
    ]
    if reflection:
        rows += [{"targeted_queries": ["Alice Lab"]}, {"assessment": "complete"}]
    return rows


@contextmanager
def sdk(tmp_path: Path, responses: list[Any], *, admission: Any = None) -> Any:
    wires: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")

    def send(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        wires.append(body)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [3.0, 4.0, *([0.0] * 1022)]}
                        for index, _ in enumerate(body["input"])
                    ],
                    "usage": {"total_tokens": 3},
                },
            )
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return httpx.Response(
            200,
            json={
                "id": "mock-" + str(len(wires)),
                "created": 1,
                "object": "chat.completion",
                "model": "synthetic-native",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(value)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
        )

    with (
        VLLMClient(
            VLLMConfig(
                "http://mock/v1/", "synthetic-native", max_tokens=4096, enable_thinking=False
            ),
            budget=budget,
            emit=events.append,
            transport=httpx.MockTransport(send),
        ) as host,
        VLLMClient(
            VLLMConfig("http://mock/v1/", "bge-m3"),
            budget=budget,
            emit=events.append,
            transport=httpx.MockTransport(send),
        ) as embed,
    ):
        native = SimpleMemTextRuntime(
            tmp_path / "native",
            "r",
            "simplemem_text",
            "owner",
            host,
            embed,
            policy(),
            admit_generation=admission or GenerationAdmission(),
        )
        try:
            yield native, host, embed, wires, events
        finally:
            native.close()


@pytest.fixture(autouse=True)
def retry_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    # Native finite retry counts remain; avoid sleeping in the MockHTTP harness.
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


def test_native_writer_40_overlap2_tail_flush_real_ids_reopen_and_owner(tmp_path: Path) -> None:
    source = [
        {"role": "user", "content": f"Archived {index}", "event_id": str(index)}
        for index in range(41)
    ]
    with sdk(tmp_path, [entry(), []]) as (native, host, embed, wires, _events):
        written = native.add_archive("owner", source)
        assert written["status"] == "COMPLETED" and len(written["records_after"]) == 1
        assert native.builder.window_size == 40 and native.builder.overlap_size == 2
        assert len(native.builder.previous_entries) == 1 and native.builder.dialogue_buffer == []
        assert host.budget is embed.budget and host.budget.state["generation_requests"] == 2
        generation = [row for row in wires if "messages" in row]
        assert [row["temperature"] for row in generation] == [0.1, 0.1]
        assert "Archived 40" not in generation[0]["messages"][-1]["content"]
        assert "Archived 38" in generation[1]["messages"][-1]["content"]
        saved = native.snapshot("owner")
        reopened = SimpleMemTextRuntime(
            tmp_path / "native",
            "r",
            "simplemem_text",
            "owner",
            host,
            embed,
            policy(),
            admit_generation=GenerationAdmission(),
        )
        assert reopened.snapshot("owner") == saved
        assert reopened.builder.previous_entries == []  # No invented builder persistence.
        with pytest.raises(ValueError, match="OWNER_SCOPE"):
            reopened.snapshot("foreign")
        with pytest.raises(ValueError, match="SCOPE_CHANGED"):
            SimpleMemTextRuntime(
                tmp_path / "native",
                "r",
                "simplemem_text",
                "foreign",
                host,
                embed,
                policy(),
                admit_generation=GenerationAdmission(),
            )


def test_native_retrieval_real_three_channels_reflection_normalization_and_read_only(
    tmp_path: Path,
) -> None:
    with sdk(tmp_path, [entry(), *plans(reflection=True), *plans()]) as (
        native,
        host,
        _embed,
        wires,
        _events,
    ):
        formed = native.add_archive("owner", [{"role": "user", "content": "Archived meeting"}])
        assert native.vector.backend._fts_initialized  # Genuine pinned Tantivy index.
        assert native.builder.previous_entries == []  # Actual short-flush behavior.
        before = native.snapshot("owner")
        result = native.search_archive("owner", "Cobalt meeting")
        assert result["status"] == "COMPLETED" and result["results"] == before
        kinds = {row["kind"] for row in result["observations"]}
        assert {
            "semantic_search",
            "keyword_search",
            "structured_search",
            "_generate_missing_info_queries",
        } <= kinds
        assert host.budget.state["generation_requests"] == 7
        assert [row["temperature"] for row in wires if "messages" in row] == [
            0.1,
            0.2,
            0.3,
            0.1,
            0.1,
            0.3,
            0.1,
        ]
        assert native.snapshot("owner") == formed["records_after"]
        rows = native.vector.backend.table.to_arrow().to_pylist()
        assert rows[0]["vector"][:2] == pytest.approx([0.6, 0.8])
        tool = native.archive_tools(FoundationScope("r", "simplemem_text", "owner", "s"))[0]
        assert tool.name == "search_memory" and "owner" not in tool.args_schema["properties"]
        with pytest.raises(ValueError, match="OWNER_SCOPE"):
            tool.invoke(
                {"query": "x"}, FoundationScope("r", "simplemem_text", "foreign", "s").config()
            )
        builder = StateGraph(MessagesState)
        builder.add_node("tools", ToolNode([tool]))
        builder.set_entry_point("tools")
        builder.add_edge("tools", END)
        returned = builder.compile().invoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "actual-explicit-search",
                                "name": "search_memory",
                                "args": {"query": "Cobalt meeting"},
                            }
                        ],
                    )
                ]
            },
            FoundationScope("r", "simplemem_text", "owner", "s").config(),
        )["messages"][-1]
        visible = json.loads(returned.content)
        assert returned.tool_call_id == "actual-explicit-search"
        assert set(visible) == {"query", "status", "results"}
        assert visible == {
            "query": "Cobalt meeting",
            "status": "COMPLETED",
            "results": before,
        }
        assert host.budget.state["generation_requests"] == 11
        assert native.snapshot("owner") == before
        private = next(
            event
            for event in reversed(native.events)
            if event["kind"] == "operation_result" and event["operation"] == "retrieval"
        )
        assert {"native_fallbacks", "recovered_retries", "admission_rejections"} <= private.keys()


@pytest.mark.parametrize(
    "mode", ["valid_empty", "recovered", "parse_recovered", "exhausted", "admission"]
)
def test_native_empty_recovered_exhausted_and_swallowed_admission_are_distinct(
    tmp_path: Path,
    mode: str,
) -> None:
    error = httpx.ReadTimeout("synthetic transport failure")
    replies = {
        "valid_empty": [[]],
        "recovered": [error, entry()],
        "parse_recovered": ["bad JSON", entry()],
        "exhausted": ["bad JSON"] * 3,
        "admission": [],
    }[mode]

    def reject() -> None:
        raise ValueError("PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED")

    with sdk(tmp_path, replies, admission=reject if mode == "admission" else None) as (
        native,
        host,
        _embed,
        _wires,
        _events,
    ):
        result = native.add_archive("owner", [{"role": "user", "content": "Archived"}])
        assert (
            result["status"]
            == {
                "valid_empty": "COMPLETED",
                "recovered": "COMPLETED",
                "parse_recovered": "COMPLETED",
                "exhausted": "DEGRADED_NATIVE",
                "admission": "INCOMPLETE",
            }[mode]
        )
        assert bool(result["records_after"]) == (mode in {"recovered", "parse_recovered"})
        assert (
            host.budget.state["generation_requests"]
            == {
                "valid_empty": 1,
                "recovered": 2,
                "parse_recovered": 2,
                "exhausted": 3,
                "admission": 0,
            }[mode]
        )
        if mode == "recovered":
            assert result["recovered_retries"]
            assert host.budget.state["generation"]["unknown_usage"] == 1
        if mode == "parse_recovered":
            assert result["recovered_retries"]
        if mode == "exhausted":
            assert result["native_fallbacks"][0]["outcome"] == "empty_due_to_error"
        if mode == "admission":
            assert result["admission_rejections"]


def test_native_swallowed_channel_error_is_degraded_but_store_insert_error_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with sdk(tmp_path, [entry(), *plans()]) as (native, _host, _embed, _wires, _events):
        native.add_archive("owner", [{"role": "user", "content": "Past"}])

        def broken(*args: Any, **kwargs: Any) -> Any:
            raise OSError("synthetic local store error")

        monkeypatch.setattr(native.vector.backend.table, "search", broken)
        result = native.search_archive("owner", "Cobalt")
        assert result["status"] == "DEGRADED_NATIVE"
        assert any(
            row["kind"] in {"keyword_search", "semantic_search"}
            for row in result["native_fallbacks"]
        )
    with sdk(tmp_path / "insert", [entry()]) as (native, _host, _embed, _wires, _events):
        monkeypatch.setattr(native.vector.backend.table, "add", broken)
        with pytest.raises(OSError, match="local store"):
            native.add_archive("owner", [{"role": "user", "content": "Past"}])


@pytest.mark.parametrize("exhaust_capacity", [False, True])
def test_merit_actual_graph_query_once_current_human_closed_turn_and_shared_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exhaust_capacity: bool,
) -> None:
    # MCP is already frozen/verified. No shared or loopback MCP service is started here.
    class Peer:
        def __init__(self, *args: Any, history_tool: Any, **kwargs: Any) -> None:
            self.tools = [history_tool]

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def records(self, scope: Any) -> list[Any]:
            return []

    monkeypatch.setattr("milai_lab.baselines.langmem_benchmark.MemoryMCP", Peer)
    settings = {
        **config(),
        "embedding_dimension": 1024,
        "second_external": {"simplemem_text": policy()},
    }
    queries = plans()[:3]  # Empty bank skips native completeness; no forced READ.
    messages = [{"role": "assistant", "content": json.dumps(row)} for row in queries]
    count = 8 if exhaust_capacity else 1
    messages += [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [call("business", {}, f"actual-business-{index}")],
        }
        for index in range(count)
    ] + [
        {"role": "assistant", "content": "Final"},
        {"role": "assistant", "content": json.dumps(entry())},
    ]
    store, wires = InMemoryStore(), []
    write_json(
        tmp_path / "run_manifest.json", {"identity": {"run_id": "r", "arm_id": "simplemem_text"}}
    )
    from langchain_core.tools import StructuredTool

    business_calls: list[str] = []

    def business() -> str:
        business_calls.append("executed")
        return "Actual partial effect"

    with runtime(tmp_path, messages, store, wires) as rt, ExitStack() as stack:

        def embedding(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.read())
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [1.0, *([0.0] * 1023)]}
                        for index, _ in enumerate(body["input"])
                    ],
                    "usage": {"total_tokens": 3},
                },
            )

        rt.embedding_client = stack.enter_context(
            VLLMClient(
                VLLMConfig("http://mock/v1/", "bge-m3"),
                budget=rt.model.client.budget,
                transport=httpx.MockTransport(embedding),
            )
        )
        factory, completed = merit_adapters(
            rt, tmp_path, "r", "simplemem_text", settings, stack, backend="simplemem_text"
        )
        agent = factory(
            rt.model,
            store,
            rt.checkpointer,
            [
                StructuredTool.from_function(
                    business, name="business", description="Synthetic native business tool"
                )
            ],
            user_id="owner",
            environment_rules="Original domain rules",
        )
        scope = FoundationScope("r", "simplemem_text", "owner", "episode:0")
        invoke_public_message(agent, rt.model, scope, "CURRENT HUMAN EXACT", 0)
        assert business_calls == ["executed"] * count
        assert rt.model.calls_in_message == count + 4
        assert len([wire for wire in wires if wire["temperature"] == 0.2]) == 1
        assert all("FUTURE USER SENTINEL" not in json.dumps(wire) for wire in wires)
        completed(agent, scope, 0, "COMPLETED", [])
        if exhaust_capacity:
            assert rt.model.calls_in_message == 12
            files = list((tmp_path / "turns").glob("*.json"))
            saved = json.loads(files[0].read_text())
            assert saved["maintenance"]["status"] == "INCOMPLETE"
            assert saved["messages"][-1]["content"] == "Final"
        else:
            assert rt.model.calls_in_message == 6
            writer = wires[-1]["messages"][-1]["content"]
            assert (
                "CURRENT HUMAN EXACT" in writer
                and "actual-business" in writer
                and "Final" in writer
            )
        assert business_calls == ["executed"] * count
        last_host = wires[-1] if exhaust_capacity else wires[-2]
        assert {row["function"]["name"] for row in last_host["tools"]} == {
            "business",
            "search_memory",
            "read_history",
        }
        assert agent.get_state(scope.config()).values["messages"][0] == HumanMessage(
            content="CURRENT HUMAN EXACT",
            id=agent.get_state(scope.config()).values["messages"][0].id,
        )


def test_simplemem_configuration_rejects_method_drift() -> None:
    settings = {
        "second_external": {"simplemem_text": policy()},
        "embedding_dimension": 1024,
        "embedding": {"model": "bge-m3"},
    }
    assert validate_simplemem(settings) == policy()
    settings["second_external"]["simplemem_text"] = {**policy(), "window_size": 10}
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        validate_simplemem(settings)


def test_memsyco_gold_free_history_degraded_order_shared_query_reader_and_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.baselines.langmem_benchmark import FORMATION_INSTRUCTION
    from milai_lab.harness.contextual_artifacts import read_json
    from milai_lab.runners import memsyco_native

    external = tmp_path / "external"
    (external / "evaluation").mkdir(parents=True)
    (external / "baselines").mkdir()
    (external / "evaluation/task_valid_memory_selection.py").write_text(
        'ANSWER_SYSTEM_PROMPT_BASE="{model_name}/{current_date}"\n'
        "def answer_system_prompt(model_name,current_date,prior_dialogue,context_label):\n"
        "    return ANSWER_SYSTEM_PROMPT_BASE.format(model_name=model_name, "
        'current_date=current_date)+"\\n"+context_label+"\\n"+prior_dialogue\n'
    )
    (external / "baselines/common.py").write_text(
        "def format_retrieved_memories(memories):\n"
        '    return "EMPTY" if not memories else "\\n".join(m["content"] for m in memories)\n'
    )
    source = external / "source.jsonl"
    rows = [
        {
            "id": key,
            "task": "valid_memory_selection",
            "dialogue": [
                {"role": "user", "content": "Archived fact " + key},
                {"role": "assistant", "content": "Past final"},
            ],
            "question": "CURRENT QUESTION " + key,
            "memory": "FORBIDDEN_GOLD",
            "evaluation": {"answer": "FORBIDDEN_GOLD"},
        }
        for key in ("first", "second")
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    selection = tmp_path / "selection.json"
    write_json(
        selection,
        {
            "external_root": str(external),
            "source_commit": "synthetic",
            "source_files": [
                {
                    "task": "valid_memory_selection",
                    "relative_path": source.name,
                    "sha256": memsyco_native.sha(source),
                }
            ],
            "groups": {
                "smoke": {
                    "cases": [
                        {"task": "valid_memory_selection", "case_id": key}
                        for key in ("first", "second")
                    ]
                }
            },
        },
    )
    settings = {
        **config(),
        "recipe_id": "simplemem-synthetic",
        "memory_contract": "strict",
        "memory_transport": "mcp_http",
        "host": {
            "tool_mode": "native",
            "max_tokens": 4096,
            "max_calls": 12,
            "temperature": 0,
            "enable_thinking": False,
            "model": "synthetic-native",
            "timeout": 180,
        },
        "capacity": {"enable_thinking": False},
        "embedding_dimension": 1024,
        "budget_path": str(tmp_path / "budget.json"),
        "formation_instruction": FORMATION_INSTRUCTION,
        "reader": {"current_date": "2025-06-01", "extra_instruction": ""},
        "retrieval": {"limit": 10, "material_max_chars": 16000},
        "agent_query": {"system_prompt": "Read-only query"},
        "second_external": {"simplemem_text": policy()},
    }
    path = tmp_path / "config.json"
    write_json(path, settings)
    args = SimpleNamespace(
        config=path,
        selection=selection,
        arm="simplemem_text",
        group="smoke",
        run="r",
        runtime_root=tmp_path / "runtime",
        formation_root=None,
        job="first",
        output=tmp_path / "prepared.json",
        prepared=tmp_path / "prepared.json",
    )
    monkeypatch.setattr(memsyco_native, "source_identity", lambda _root: {"source_sha256": {}})
    memsyco_native.prepare(args, lab_root=tmp_path)
    prepared = read_json(args.runtime_root / "run_manifest.json")
    assert prepared["identity"]["memory_tool_catalog"] == []
    assert "native 40 dialogues/overlap2" in prepared["identity"]["archive_batch_rule"]
    histories = read_json(args.runtime_root / "runtime-histories.json")["histories"]
    assert "CURRENT QUESTION" not in json.dumps(histories) and "FORBIDDEN_GOLD" not in json.dumps(
        histories
    )
    replies = [{"role": "assistant", "content": '"bad JSON"'}] * 3
    replies += [{"role": "assistant", "content": json.dumps(entry())}]
    replies += [{"role": "assistant", "content": json.dumps(row)} for row in plans()[:3]]
    replies += [{"role": "assistant", "content": "Official reader final"}]
    wires: list[dict[str, Any]] = []

    @contextmanager
    def local_runtime(_settings: Any, _run: str, _arm: str, root: Path) -> Any:
        def embedding(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.read())
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [1.0, *([0.0] * 1023)]}
                        for index, _ in enumerate(body["input"])
                    ],
                    "usage": {"total_tokens": 3},
                },
            )

        with (
            runtime(root, replies, InMemoryStore(), wires) as rt,
            VLLMClient(
                VLLMConfig("http://mock/v1/", "bge-m3"),
                budget=rt.model.client.budget,
                transport=httpx.MockTransport(embedding),
            ) as embed,
        ):
            rt.embedding_client = embed
            yield rt

    def forbidden_parse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("runtime parsed original gold-bearing rows")

    monkeypatch.setattr(memsyco_native, "_runtime", local_runtime)
    monkeypatch.setattr(memsyco_native, "load_memsyco_tasks", forbidden_parse)
    args.history = histories[0]["history_id"]
    args.output = tmp_path / "formed-first.json"
    first = memsyco_native.run_history(args, lab_root=tmp_path)
    assert first["status"] == "DEGRADED_NATIVE" and first["built"]["records_after"] == []
    args.history = histories[1]["history_id"]
    args.output = tmp_path / "formed-second.json"
    assert memsyco_native.run_history(args, lab_root=tmp_path)["status"] == "COMPLETED"
    assert "CURRENT QUESTION" not in json.dumps(wires)
    args.output = tmp_path / "result.json"
    result = memsyco_native.run(args, lab_root=tmp_path)
    assert (
        result["answer"] == "Official reader final"
        and result["formation_status"] == "DEGRADED_NATIVE"
    )
    assert result["records_before"] == result["records_after"] == []
    assert "FORBIDDEN_GOLD" not in json.dumps(wires)
    assert result["costs"]["roles"]["simplemem_retrieval"]["requests"] == 3
    assert result["costs"]["roles"]["reader"]["requests"] == 1
    with pytest.raises(ValueError, match="ALREADY_ATTEMPTED"):
        memsyco_native.run(args, lab_root=tmp_path)
