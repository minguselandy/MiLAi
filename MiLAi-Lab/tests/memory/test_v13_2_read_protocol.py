"""Synthetic Store/actual ToolNode/bridge/runner controls, no semantic benchmark."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.journal import BusinessActionJournal
from milai_lab.baselines.langmem_agent import build_agent
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.contracts.read_protocol import (
    SAVE_GUIDANCE,
    ReadProtocolRejected,
    snapshot_key,
)
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory import service as service_module
from milai_lab.memory.revision_store import RevisionSidecar
from milai_lab.memory.service import MemoryService, reference_key
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.grounded_memory import GroundedMemoryRecipe
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import v13_1_d0 as d0
from milai_lab.runners import v13_1_p5 as p5

CFG_SHA = "a" * 64


@pytest.fixture(autouse=True)
def stable_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class Clock:
        @staticmethod
        def now(*args: Any, **kwargs: Any) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(service_module, "datetime", Clock)


@contextmanager
def opened(
    root: Path, *, a: bool = True, b: bool = True, c: bool = False
) -> Iterator[MemoryService]:
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        yield MemoryService(
            store,
            ("synthetic-read", "owner"),
            "owner",
            root / "memory.lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
            memory_read_protocol="selected_snapshot_v1" if a else "legacy",
            tool_read_feedback="typed_read_v1" if b else "legacy",
            tool_save_communication="completed_receipt_v1" if c else "legacy",
        )


def turn(service: MemoryService, *, phase: str = "start", message: str = "u") -> dict[str, Any]:
    source = service.capture_user("s", message, "archive multilingual evidence")["source_ref"]
    service.bind_source_boundary("s", message, [source])
    if service.memory_read_protocol != "legacy":
        service.bind_public_turn("s", message, source, config_sha256=CFG_SHA, phase=phase)
    return {
        "configurable": {
            "user_id": "owner",
            "v13_session": "s",
            "v13_turn_id": message,
            "v13_support_config_sha256": CFG_SHA,
            "thread_id": "thread",
        }
    }


def seeded(service: MemoryService) -> None:
    for index in range(8):
        service.capture_user(
            "history",
            "old" + str(index),
            ("archive multilingual evidence 演示 evidencia " + str(index) + " ") * 180,
        )


def packet(
    recipe: GroundedMemoryRecipe, *, query: str | None = None, budget: int = 1200
) -> dict[str, Any]:
    return recipe.prepare_context(
        "archive multilingual evidence",
        owner="owner",
        session="s",
        turn_id="u",
        explicit_query=query,
        material_budget=budget,
    )


def cursor(state: dict[str, Any]) -> str:
    return state["packet"]["coverage"]["read_more"]["cursor"]


def call(
    tool_: Any, name: str, args: dict[str, Any], config: dict[str, Any], key="read"
) -> ToolMessage:
    return tool_.invoke({"type": "tool_call", "name": name, "args": args, "id": key}, config=config)


def test_ordinary_and_two_explicit_snapshots_survive_overwrite_and_reopen(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        seeded(service)
        config = turn(service)
        recipe = GroundedMemoryRecipe(service, lambda s: len(s.encode()) // 4)
        ordinary = packet(recipe)
        one = packet(recipe, query="archive multilingual evidence")
        repeat = packet(recipe, query="archive multilingual evidence")
        two = packet(recipe, query="evidence 演示")
        assert repeat["retrieval_calls"] == 1 and repeat["packet_id"] != one["packet_id"]
        assert repeat["selected"] == one["selected"]
        assert len({cursor(ordinary), cursor(one), cursor(two)}) == 3
        for state in [ordinary, one, two]:
            page = recipe.selected_page_tool(cursor(state), config)
            assert page["snapshot_id"] == state["selected_snapshot_id"]
            assert page["retrieval_calls"] == 0 and page["current_verified"] is False
        changed_budget = packet(recipe, budget=1400)
        assert cursor(changed_budget) != cursor(ordinary)
        assert recipe.selected_page_tool(cursor(ordinary), config)["items"]
        preserved = cursor(one)
    with opened(tmp_path) as service:
        config = turn(service, phase="resume")
        recipe = GroundedMemoryRecipe(service, lambda s: len(s.encode()) // 4)
        # Resolver must exact-get snapshots, without retrieval/cache/bank search.
        recipe._retrieve = lambda *args: (_ for _ in ()).throw(
            AssertionError("retrieval forbidden")
        )
        assert recipe.selected_page_tool(preserved, config)["items"]


@pytest.mark.parametrize("fault", ["missing", "revoked", "id", "owner", "config", "turn"])
def test_snapshot_fail_closed_identity_and_missing(tmp_path: Path, fault: str) -> None:
    with opened(tmp_path) as service:
        seeded(service)
        config = turn(service)
        recipe = GroundedMemoryRecipe(service, lambda s: len(s.encode()) // 4)
        token = cursor(packet(recipe))
        key = snapshot_key(token.split(":")[0].removeprefix("selected-"))
        row = service.store.get(recipe.namespace, key).value
        if fault == "missing":
            service.store.delete(recipe.namespace, key)
        elif fault == "revoked":
            service.store.put(recipe.namespace, key, {**row, "status": "revoked"}, index=False)
        elif fault == "id":
            service.store.put(recipe.namespace, key, {**row, "snapshot_id": "0" * 64}, index=False)
        elif fault == "owner":
            config["configurable"]["user_id"] = "other"
        elif fault == "config":
            config["configurable"]["v13_support_config_sha256"] = "b" * 64
        else:
            turn(service, message="later")
            config["configurable"]["v13_turn_id"] = "later"
        with pytest.raises(ValueError) as caught:
            recipe.selected_page_tool(token, config)
        assert isinstance(caught.value, ReadProtocolRejected) == (fault in {"missing", "revoked"})


def test_immutable_snapshot_unknown_store_and_collision_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened(tmp_path) as service:
        seeded(service)
        config = turn(service)
        recipe = GroundedMemoryRecipe(service, lambda s: len(s.encode()) // 4)
        state = packet(recipe)
        token = cursor(state)
        key = snapshot_key(token.split(":")[0].removeprefix("selected-"))
        original = service.store.get(recipe.namespace, key).value
        corrupted = {**original, "issuing_packet_id": "b" * 64}
        service.store.put(recipe.namespace, key, corrupted, index=False)
        with pytest.raises(ValueError, match="COLLISION_OR_CHANGED"):
            recipe._persist_selection(
                {
                    k: v
                    for k, v in original.items()
                    if k not in {"issuing_packet_id", "receipt_sha256"}
                },
                state["packet_id"],
            )
        assert service.store.get(recipe.namespace, key).value == corrupted

        def unknown(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic SDK Store failure")

        monkeypatch.setattr(service.store, "get", unknown)
        with pytest.raises(RuntimeError, match="SDK Store"):
            recipe.selected_page_tool(token, config)


@pytest.mark.parametrize(
    "code,args",
    [
        ("V13_SELECTED_PAGE_NOT_READY", {"cursor": "selected-" + "0" * 24 + ":0"}),
        ("V13_HISTORY_READ_REQUIRES_EXACT_ID", {"view": "history"}),
        ("V13_HISTORY_ARGUMENTS_REQUIRE_HISTORY_VIEW", {"cursor": "bad"}),
    ],
)
def test_actual_facade_finite_typed_rejection(
    tmp_path: Path, code: str, args: dict[str, Any]
) -> None:
    with opened(tmp_path, a=False) as service:
        config = turn(service)
        recipe = GroundedMemoryRecipe(service, lambda s: len(s) // 4)
        tools = create_service_tools(
            service,
            recall_provider=recipe.recall_tool,
            selected_page_provider=recipe.selected_page_tool,
        )
        name = "recall_context" if "SELECTED" in code else "read_memory"
        result = call(next(t for t in tools if t.name == name), name, args, config)
        receipt = json.loads(result.content)
        assert result.status == "error" and result.tool_call_id == "read" and result.name == name
        assert receipt["code"] == code and receipt["semantic_effect"] == "none"


@pytest.mark.parametrize("tool_mode", ["native", "json_action"])
@pytest.mark.parametrize("model_type", [VLLMChatModel, LangMemRecipeChatModel])
def test_shared_real_invoke_receipt_copy_and_cap(
    tmp_path: Path, tool_mode: str, model_type: Any
) -> None:
    requests = []

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        final = (
            "unchanged final"
            if tool_mode == "native"
            else json.dumps({"answer": "unchanged final"})
        )
        return httpx.Response(
            200,
            json={
                "id": "response",
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": final}}
                ],
                "usage": {"total_tokens": 7},
            },
        )

    budget = RunBudget(RunLimits(), tmp_path / "local-budget.json")
    with VLLMClient(
        VLLMConfig("http://synthetic/v1", "synthetic", tool_mode=tool_mode),
        transport=httpx.MockTransport(transport),
        budget=budget,
    ) as client:
        model = model_type(client=client, tool_save_communication="completed_receipt_v1")
        model.begin_public_message("public")

        @tool
        def echo(value: str) -> str:
            """Echo an actual synthetic value."""
            return value

        bound = model.bind_tools([echo])
        for _ in range(12):
            assert bound.invoke([HumanMessage("actual user")]).content == "unchanged final"
        with pytest.raises(ValueError, match="CAPACITY_EXCEEDED"):
            bound.invoke([HumanMessage("actual user")])
    assert len(requests) == budget.state["generation_requests"] == 12
    assert SAVE_GUIDANCE in requests[0]["messages"][0]["content"]
    assert "field_support" not in json.dumps(requests)


def test_runner_flags_freeze_and_service_are_shared(tmp_path: Path) -> None:
    settings = {
        "memory_read_protocol": "selected_snapshot_v1",
        "tool_read_feedback": "typed_read_v1",
        "tool_save_communication": "completed_receipt_v1",
        "memory_mutation_contract": "event_bound_v1",
        "memory_candidate_contract": "read_handle_v1",
        "memory_reader_policy": "bounded_evidence_v1",
    }
    assert d0._service_options(settings) == p5._service_options(settings)
    for name in ["memory_read_protocol", "tool_read_feedback", "tool_save_communication"]:
        invalid = {**settings, name: "unknown"}
        with pytest.raises(ValueError, match="PROFILE_INVALID"):
            d0._service_options(invalid)


def test_actual_toolnode_observer_journal_keeps_completed_action_then_bad_read(
    tmp_path: Path,
) -> None:
    requests = []
    replies = [
        {
            "calls": [
                {"name": "business_echo", "arguments": {"value": "actual"}},
                {"name": "read_memory", "arguments": {"view": "history"}},
            ]
        },
        {"answer": "final unchanged"},
    ]

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "generation-" + str(len(requests)),
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(replies.pop(0))},
                    }
                ],
            },
        )

    @tool
    def business_echo(value: str) -> str:
        """Return an actual synthetic business receipt."""
        return json.dumps({"ok": True, "actual": value})

    with opened(tmp_path, a=False, c=True) as service:
        config = turn(service)
        journal = BusinessActionJournal(tmp_path / "journal.json", ["business_echo"])
        sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
        observer = ProvenanceObserver(sidecar, "synthetic", "arm")
        scope = FoundationScope("synthetic", "arm", "owner", "s")
        config["configurable"]["thread_id"] = scope.config()["configurable"]["thread_id"]
        observer.begin_public_message(scope, 0, "actual user")
        with VLLMClient(
            VLLMConfig("http://synthetic/v1", "synthetic"), transport=httpx.MockTransport(transport)
        ) as client:
            model = LangMemRecipeChatModel(
                client=client, tool_save_communication="completed_receipt_v1"
            )
            model.begin_public_message("u")
            agent = build_agent(
                model,
                service.store,
                InMemorySaver(),
                [business_echo],
                business_call_wrapper=journal,
                observer=observer,
                memory_tools=create_service_tools(service),
                tool_save_communication="completed_receipt_v1",
            )
            result = agent.invoke(
                {"messages": [HumanMessage("actual user", id="u")]}, config=config
            )
        receipts = [x for x in result["messages"] if isinstance(x, ToolMessage)]
        assert (
            len(receipts) == 2 and receipts[0].status == "success" and receipts[1].status == "error"
        )
        assert json.loads(receipts[1].content)["code"] == "V13_HISTORY_READ_REQUIRES_EXACT_ID"
        entries = journal.calls_for_thread(config["configurable"]["thread_id"])
        assert len(entries) == 1 and entries[0]["status"] == "complete"
        observer.assert_healthy()
        assert result["messages"][-1].content == "final unchanged"
        sidecar.close()


def capacity_config(root: Path | None = None) -> dict[str, Any]:
    if root is not None:
        # Protocol mechanics use a generated tokenizer; real Qwen cost tests
        # explicitly call the no-argument branch and retain local_artifacts.
        import runpy

        helper = Path(__file__).parents[1] / "unit/test_v13_1_controls.py"
        config = runpy.run_path(str(helper))["settings"](root)["capacity"]
        return {
            **config,
            "model": "synthetic",
            "context_tokens": 131072,
            "output_tokens": 4096,
            "safety_tokens": 64,
            "batch_source_tokens": 4096,
            "related_reserve_tokens": 0,
            "schema_reserve_tokens": 0,
            "source_message_overhead_tokens": 0,
        }
    return {
        "model": "synthetic",
        "tokenizer_path": "/cra/qwen36-35B",
        "tokenizer_files_sha256": {
            "tokenizer.json": "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42",
            "tokenizer_config.json": (
                "5186f0defcd7f232382c7f0aebcd2252d073bb921ab240e407b7ae8745d2b29b"
            ),
            "chat_template.jinja": (
                "e84f32a23fdda27689f868aa4a1a5621f41133e51a48d7f3efcbea2839574259"
            ),
        },
        "context_tokens": 131072,
        "output_tokens": 4096,
        "safety_tokens": 64,
        "batch_source_tokens": 4096,
        "related_reserve_tokens": 0,
        "schema_reserve_tokens": 0,
        "source_message_overhead_tokens": 0,
    }


def synthetic_settings(root: Path) -> tuple[Path, Path, dict[str, Any]]:
    from milai_lab.harness.contextual_artifacts import write_json

    budget_path = root / "local-budget.json"
    write_json(budget_path, RunBudget(RunLimits(generation_requests=100), budget_path).state)
    capacity = capacity_config(root)
    settings = {
        "host": {
            "base_url": "http://synthetic/v1",
            "model": "synthetic",
            "tool_mode": "json_action",
            "max_tokens": 4096,
        },
        "capacity": capacity,
        "budget_path": str(budget_path),
        "memory_mutation_contract": "event_bound_v1",
        "memory_candidate_contract": "read_handle_v1",
        "memory_reader_policy": "bounded_evidence_v1",
        "memory_formation_policy": "after_host_final_v1",
        "writer_system_prompt": "Form only proposals from actual evidence, or decline.",
        "memory_writer_repairs": 0,
        "memory_read_protocol": "selected_snapshot_v1",
        "tool_read_feedback": "typed_read_v1",
        "tool_save_communication": "completed_receipt_v1",
        "embedding": {"base_url": "http://synthetic/v1", "model": "synthetic-embedding"},
        "embedding_capacity": {
            "tokenizer_path": str(Path(capacity["tokenizer_path"]) / "tokenizer.json"),
            "tokenizer_sha256": capacity["tokenizer_files_sha256"]["tokenizer.json"],
            "context_tokens": 8192,
        },
        "embedding_dimension": 2,
        "embedding_batch": 8,
    }
    fixture = {
        "kind": "MILAI_V13_1_D0_NORMAL_USE",
        "cases": [
            {
                "case_id": "synthetic-entry",
                "owner": "owner",
                "messages": [
                    {
                        "message_id": "u",
                        "session_id": "s",
                        "content": "Actual public statement",
                        "application_binding": {"task_id": "synthetic-task", "operations": []},
                    }
                ],
                "operations": [],
            }
        ],
    }
    fp, cp = root / "public-synthetic.json", root / "synthetic-settings.json"
    write_json(fp, fixture)
    write_json(cp, settings)
    return fp, cp, settings


@pytest.mark.parametrize("runner", [d0, p5])
def test_actual_prepare_step_start_resume_freeze_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: Any
) -> None:
    from milai_lab.harness.contextual_artifacts import read_json, write_json

    fp, cp, _settings = synthetic_settings(tmp_path)
    root = tmp_path / "run"
    requests = []
    real_client = VLLMClient

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(body["input"])
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "response-" + str(len(requests)),
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"answer": "Final remains unchanged"}),
                        },
                    }
                ],
            },
        )

    def client(*args: Any, **kwargs: Any) -> VLLMClient:
        return real_client(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(d0, "VLLMClient", client)
    monkeypatch.setattr(p5, "VLLMClient", client)
    frozen = runner.prepare(fp, cp, root)
    assert frozen["memory_read_protocol"] == "selected_snapshot_v1"
    assert frozen["tool_read_feedback"] == "typed_read_v1"
    assert frozen["read_protocol_presentation"]["catalog_version"] == "public_memory_v2"
    execute = runner._execute_step if runner is d0 else runner.step
    result = execute(root, "synthetic-entry", 0)
    assert result["status"] == "completed", result
    assert result["final_answer"] == "Final remains unchanged"
    assert result["semantic_maintenance"]["generation_calls"] == 1
    generation = [r for r in requests if "messages" in r]
    assert len(generation) == 2
    assert SAVE_GUIDANCE in generation[0]["messages"][0]["content"]
    assert SAVE_GUIDANCE in generation[1]["messages"][1]["content"]
    before = len(requests)
    if runner is d0:
        assert execute(root, "synthetic-entry", 0) == result
    else:
        with pytest.raises(ValueError, match="ATTEMPT_ALREADY_RECORDED"):
            execute(root, "synthetic-entry", 0)
    assert len(requests) == before
    frozen_path = root / "input-freeze.json"
    changed = read_json(frozen_path)
    changed["config"]["tool_read_feedback"] = "unsupported-profile"
    write_json(frozen_path, changed)
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        runner._frozen(root)
    assert len(requests) == before


def test_writer_single_generation_success_then_partial_replay_no_final_rewrite(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, c=True) as service:
        config = turn(service)
        user = service.event_id("s", "u", "user")
        final = AIMessage("Original final byte string", id="final")
        assistant = service.capture_assistant("s", "final", final.content)["source_ref"]
        requests = []
        response = {
            "calls": [
                {
                    "name": "manage_memory",
                    "arguments": {"content": "Actual item", "source_refs": [user]},
                },
                {
                    "name": "manage_memory",
                    "arguments": {
                        "content": "Bad typed argument",
                        "kind": {"source_refs": [user]},
                        "source_refs": [user],
                    },
                },
            ]
        }

        def transport(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "writer",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": json.dumps(response)},
                        }
                    ],
                },
            )

        recipe = GroundedMemoryRecipe(service, lambda s: len(s) // 4)
        with VLLMClient(
            VLLMConfig("http://synthetic/v1", "synthetic"), transport=httpx.MockTransport(transport)
        ) as client:
            model = LangMemRecipeChatModel(
                client=client, tool_save_communication="completed_receipt_v1"
            )
            model.begin_public_message("u")
            args = dict(
                session="s",
                turn_id="u",
                source_refs=[user, assistant],
                config=config,
                instruction="Only propose supported facts or decline.",
                repairs=0,
            )
            receipt = recipe.maintain(model, **args)
            assert receipt["status"] == "partial" and receipt["generation_calls"] == 1
            assert receipt["committed_actions"] == 1 and len(service.records()) == 1
            replay = recipe.maintain(model, **args)
            assert replay["replayed"] and len(requests) == 1
            assert final.content.encode() == b"Original final byte string"


@pytest.mark.parametrize(
    "exception",
    [
        RuntimeError("unknown SDK"),
        ValueError("V13_SELECTED_PAGE_NOT_READY"),
        PermissionError("owner"),
        KeyError("config"),
    ],
)
def test_unknown_not_converted_by_facade(tmp_path: Path, exception: Exception) -> None:
    with opened(tmp_path, a=False) as service:
        config = turn(service)

        def provider(*args: Any) -> Any:
            raise exception

        tools = create_service_tools(
            service, selected_page_provider=provider, recall_provider=provider
        )
        recall = next(t for t in tools if t.name == "recall_context")
        with pytest.raises(type(exception)) as caught:
            call(recall, "recall_context", {"cursor": "opaque"}, config)
        assert caught.value is exception


def test_p5_actual_unknown_start_then_resume_and_bound_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fp, cp, _settings = synthetic_settings(tmp_path)
    root = tmp_path / "resume-run"
    requests = []
    real_client = VLLMClient

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(body["input"])
                    ]
                },
            )
        if sum("messages" in r for r in requests) == 1:
            raise RuntimeError("unknown scripted response")
        return httpx.Response(
            200,
            json={
                "id": "resume-response-" + str(len(requests)),
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"answer": "Resumed final unchanged"}),
                        },
                    }
                ],
            },
        )

    def client(*args: Any, **kwargs: Any) -> VLLMClient:
        return real_client(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(d0, "VLLMClient", client)
    monkeypatch.setattr(p5, "VLLMClient", client)
    frozen = p5.prepare(fp, cp, root)
    started = p5.step(root, "synthetic-entry", 0, attempt_id="first")
    assert started["status"] == "interrupted" and "unknown scripted response" in started["error"]
    resumed = p5.step(root, "synthetic-entry", 0, phase="resume", attempt_id="resumed")
    assert resumed["status"] == "completed", resumed
    assert resumed["final_answer"] == "Resumed final unchanged"
    assert sum("messages" in r for r in requests) == 3
    with SqliteStore.from_conn_string(
        str(p5.case_path(root, "synthetic-entry") / "memory.sqlite")
    ) as store:
        namespace = ("langmem", frozen["run_id"], frozen["mode"], "owner")
        service = MemoryService(
            store,
            namespace,
            "owner",
            tmp_path / "reopen.lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
            memory_read_protocol="selected_snapshot_v1",
        )
        item = store.get(
            service.turns_namespace,
            reference_key(["s", "u"]),
        )
        assert item.value["last_binding_phase"] == "resume"
        assert item.value["binding"]["config_version"] == frozen["config_sha256"]


def test_issued_id_collision_and_persistence_cut_never_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from milai_lab.methods import grounded_memory as grounded

    with opened(tmp_path) as service:
        seeded(service)
        turn(service)
        recipe = GroundedMemoryRecipe(service, lambda s: len(s.encode()) // 4)
        real_uuid4 = grounded.uuid.uuid4
        monkeypatch.setattr(grounded.uuid, "uuid4", lambda: "same-issued-snapshot-id")
        first = packet(recipe, query="archive")
        key = snapshot_key("same-issued-snapshot-id")
        original = service.store.get(recipe.namespace, key).value
        with pytest.raises(ValueError, match="COLLISION_OR_CHANGED"):
            packet(recipe, query="evidence")
        assert service.store.get(recipe.namespace, key).value == original
        assert first["retrieval_calls"] == 1
        monkeypatch.setattr(grounded.uuid, "uuid4", real_uuid4)
        real_put = service.store.put

        def interrupted(namespace: Any, key: str, value: Any, **kwargs: Any) -> None:
            if key.startswith("selected_snapshot:"):
                raise RuntimeError("snapshot persistence cut")
            real_put(namespace, key, value, **kwargs)

        monkeypatch.setattr(service.store, "put", interrupted)
        query_key = "query:" + reference_key(["s", "u", "distinct-query"])
        assert service.store.get(recipe.namespace, query_key) is None
        with pytest.raises(RuntimeError, match="persistence cut"):
            packet(recipe, query="distinct-query")
        assert service.store.get(recipe.namespace, query_key) is None


def test_record_snapshot_reads_exact_history_after_dirty_current(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        old = service.capture_user("s", "old", "archive multilingual evidence former")["source_ref"]
        service.bind_source_boundary("s", "old", [old])
        manage = next(t for t in create_service_tools(service) if t.name == "manage_memory")
        old_config = {"configurable": {"user_id": "owner", "v13_session": "s"}}
        created = json.loads(
            call(
                manage,
                "manage_memory",
                {
                    "content": "archive multilingual evidence " * 200,
                    "source_refs": [old],
                    "scope": {"project_limits": "generic explicit scope " * 400},
                },
                old_config,
                "create",
            ).content
        )
        assert created["ok"], created
        config = turn(service)
        recipe = GroundedMemoryRecipe(service, lambda s: len(s.encode()) // 4)
        state = packet(recipe, budget=750)
        token = cursor(state)
        issued = service.read(created["id"])["candidate_handle"]
        current = service.event_id("s", "u", "user")
        changed = json.loads(
            call(
                manage,
                "manage_memory",
                {
                    "action": "update",
                    "candidate_handle": issued,
                    "content": "archive multilingual evidence changed",
                    "source_refs": [current],
                },
                config,
                "change",
            ).content
        )
        assert changed["ok"] and changed["revision"] == 2, changed
        page = recipe.selected_page_tool(token, config)
        former = next(row for row in page["items"] if row.get("id") == created["id"])
        assert former["revision"] == 1 and former["view_at_snapshot"] == "current_at_snapshot"
        assert former["current_verified"] is False
        dirty = packet(recipe, budget=750)
        assert dirty["retrieval_calls"] == 0 and dirty["selected"] == state["selected"]
        assert (
            recipe.selected_page_tool(token, config)["snapshot_id"] == state["selected_snapshot_id"]
        )


def test_service_model_builder_drift_rejects_before_transport(tmp_path: Path) -> None:
    with opened(tmp_path, a=False, c=True) as service:
        with VLLMClient(
            VLLMConfig("http://synthetic/v1", "synthetic"),
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(AssertionError("no dispatch"))
            ),
        ) as client:
            model = LangMemRecipeChatModel(client=client)
            with pytest.raises(ValueError, match="SERVICE_CONFLICT"):
                build_agent(
                    model,
                    service.store,
                    InMemorySaver(),
                    memory_tools=create_service_tools(service),
                )
            with pytest.raises(ValueError, match="PROFILE_CONFLICT"):
                build_agent(
                    model,
                    service.store,
                    InMemorySaver(),
                    tool_save_communication="completed_receipt_v1",
                )


def test_toolnode_unknown_after_success_keeps_journal_and_propagates(tmp_path: Path) -> None:
    responses = [
        {
            "calls": [
                {"name": "business_echo", "arguments": {"value": "actual"}},
                {"name": "read_memory", "arguments": {"view": "history", "id": "unknown"}},
            ]
        }
    ]

    @tool
    def business_echo(value: str) -> str:
        """Actual synthetic business receipt."""
        return json.dumps({"ok": True, "value": value})

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "g",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(responses.pop(0))},
                    }
                ],
            },
        )

    with opened(tmp_path, a=False) as service:
        config = turn(service)
        journal = BusinessActionJournal(tmp_path / "unknown-journal.json", ["business_echo"])
        sidecar = RevisionSidecar(tmp_path / "unknown-sidecar.sqlite")
        observer = ProvenanceObserver(sidecar, "synthetic", "arm")
        scope = FoundationScope("synthetic", "arm", "owner", "s")
        config["configurable"]["thread_id"] = scope.config()["configurable"]["thread_id"]
        observer.begin_public_message(scope, 0, "actual user")

        def unknown(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("unknown native Store failure")

        service.history_index = unknown
        with VLLMClient(
            VLLMConfig("http://synthetic/v1", "synthetic"), transport=httpx.MockTransport(transport)
        ) as client:
            model = LangMemRecipeChatModel(client=client)
            model.begin_public_message("u")
            agent = build_agent(
                model,
                service.store,
                InMemorySaver(),
                [business_echo],
                business_call_wrapper=journal,
                observer=observer,
                memory_tools=create_service_tools(service),
            )
            with pytest.raises(RuntimeError, match="unknown native Store"):
                agent.invoke({"messages": [HumanMessage("actual user", id="u")]}, config=config)
        assert (
            journal.calls_for_thread(config["configurable"]["thread_id"])[0]["status"] == "complete"
        )
        observer.assert_healthy()
        sidecar.close()


def test_observation_snapshot_retains_exact_real_members_without_current_winner(
    tmp_path: Path,
) -> None:
    from milai_lab.contracts.memory import ObservationField, ObservationProfile, VerifiedObjectRef

    profile = ObservationProfile(
        "synthetic-observation",
        "v1",
        "synthetic.object",
        ("synthetic_lookup",),
        ("object_id",),
        (ObservationField("status", ("status",), "string"),),
    )
    with opened(tmp_path) as service:
        refs = []
        for index, status in enumerate(["ready", "pending"]):
            ref = service.event_id("history", "tool" + str(index), "tool")
            verified = VerifiedObjectRef(
                ref + ":actual-object",
                "owner",
                ref,
                "actual-object",
                "synthetic.object",
                {"status": status},
            )
            service.capture_tool(
                "history",
                "tool" + str(index),
                "synthetic_lookup",
                json.dumps({"object_id": "actual-object", "status": status}),
                verified,
            )
            result = service.observe(ref, profile)
            assert result["ok"], result
            refs.append(ref)
        config = turn(service)
        observations = service.observations()
        obj = observations["objects"][0]
        recipe = GroundedMemoryRecipe(service, lambda s: len(s.encode()) // 4)
        selected = [
            {
                "source_id": refs[0],
                "id": "actual",
                "start": 0,
                "end": 1,
                "content": "x",
                "record_ids": [],
                "object_fields": [(obj["object_ref"]["id"], "status")],
            }
        ]
        units = recipe._units(selected, observations)
        unit = next(u for u in units if u["type"] == "observation_field")
        descriptor = recipe._descriptor(unit)
        assert len(descriptor["observation_members"]) == 2
        assert {m["source_ref"] for m in descriptor["observation_members"]} == set(refs)
        assert all(m["role"] == "tool" for m in descriptor["observation_members"])
        trusted = service.public_turn("s", message_id="u")
        token = recipe._read_context.set(
            {
                "public_turn": trusted,
                "query_kind": "ordinary_public",
                "query": "archive multilingual evidence",
                "request_ref": recipe._request_ref("s", "u"),
                "material_budget": 2048,
                "bank_revision": "synthetic-exact-snapshot",
                "source_index": None,
                "source_index_snapshot_id": None,
            }
        )
        try:
            row = recipe._selection_snapshot([descriptor], [unit], [], None)
            recipe._persist_selection(row, "a" * 64)
        finally:
            recipe._read_context.reset(token)
        cursor = "selected-" + row["snapshot_id"] + ":0"

        def no_bank_view(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("continuation must exact-get selected members")

        service.observations = no_bank_view
        page = recipe.selected_page_tool(cursor, config)
        assert page["items"][0]["observation_members"] == descriptor["observation_members"]
        service.store.delete(service.sources_namespace, refs[1])
        with pytest.raises(ValueError, match="SELECTED_OBSERVATION_SOURCE_CHANGED") as caught:
            recipe.selected_page_tool(cursor, config)
        assert not isinstance(caught.value, ReadProtocolRejected)


@pytest.mark.parametrize("fault", ["role", "revision", "missing"])
def test_selected_source_integrity_is_not_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    with opened(tmp_path) as service:
        seeded(service)
        config = turn(service)
        recipe = GroundedMemoryRecipe(service, lambda s: len(s.encode()) // 4)
        state = packet(recipe)
        token = cursor(state)
        old = next(row["source_ref"] for row in state["omitted_menu"] if row["type"] == "source")
        real_source = service.source

        def changed(ref: str) -> Any:
            source = real_source(ref)
            if ref == old:
                if fault == "missing":
                    return None
                source = (
                    {**source, "role": "tool"}
                    if fault == "role"
                    else {**source, "source_revision": 2}
                )
            return source

        monkeypatch.setattr(service, "source", changed)
        with pytest.raises(ValueError, match="SELECTED_SOURCE_CHANGED") as caught:
            recipe.selected_page_tool(token, config)
        assert not isinstance(caught.value, ReadProtocolRejected)


def test_read_limits_owner_config_and_graphbubbleup_propagate(tmp_path: Path) -> None:
    from langgraph.errors import GraphBubbleUp

    with opened(tmp_path, a=False) as service:
        config = turn(service)
        tools = create_service_tools(service)
        source_tool = next(t for t in tools if t.name == "read_current_sources")
        wrong = {"configurable": {**config["configurable"], "user_id": "other"}}
        with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
            call(source_tool, "read_current_sources", {"cursor": "bad"}, wrong)
        with pytest.raises(ValueError, match="LIMIT_INVALID"):
            service.source_boundary("s", limit=0)
        error = GraphBubbleUp("actual synthetic bubble")

        def bubble(*args: Any) -> Any:
            raise error

        tool_ = next(
            t
            for t in create_service_tools(
                service, recall_provider=bubble, selected_page_provider=bubble
            )
            if t.name == "recall_context"
        )
        with pytest.raises(GraphBubbleUp) as caught:
            call(tool_, "recall_context", {"cursor": "opaque"}, config)
        assert caught.value is error


@pytest.mark.parametrize(
    "fault",
    [
        "fact_missing",
        "fact_changed",
        "marker_missing",
        "marker_changed",
        "source_missing",
        "source_changed",
        "historical_valid",
    ],
)
def test_exact_observation_member_fault_matrix(tmp_path: Path, fault: str) -> None:
    from milai_lab.contracts.memory import ObservationField, ObservationProfile, VerifiedObjectRef

    profile = ObservationProfile(
        "synthetic-versioned",
        "v1",
        "synthetic.object",
        ("synthetic_lookup",),
        ("object_id",),
        (ObservationField("status", ("status",), "string", "synthetic-sequence"),),
        resource_version_path=("version",),
        resource_version_type="integer",
    )
    with opened(tmp_path) as service:

        def observed(version: int) -> str:
            key = "actual-tool-" + str(version)
            ref = service.event_id("history", key, "tool")
            dto = VerifiedObjectRef(
                ref + ":O", "owner", ref, "O", "synthetic.object", {"status": "ready"}
            )
            service.capture_tool(
                "history",
                key,
                "synthetic_lookup",
                json.dumps({"object_id": "O", "status": "ready", "version": version}),
                dto,
            )
            result = service.observe(ref, profile)
            assert result["ok"]
            return ref

        source_ref = observed(1)
        fact = service.observations()["observations"][0]
        oid, object_id = fact["observation_id"], fact["object_ref"]["id"]
        if fault == "historical_valid":
            observed(2)
            current = service.observations()["objects"][0]["fields"]["status"]["candidates"]
            assert oid not in {row["observation_id"] for row in current}
            assert service.selected_observation_member(oid, object_id, "status") == fact
            return
        if fault == "fact_missing":
            service.store.delete(service.observations_namespace, oid)
        elif fault == "fact_changed":
            service.store.put(
                service.observations_namespace,
                oid,
                {**fact, "source_revision": 2},
                index=False,
            )
        elif fault == "marker_missing":
            service.store.delete(service.projections_namespace, fact["projection_id"])
        elif fault == "marker_changed":
            marker = service.store.get(service.projections_namespace, fact["projection_id"]).value
            service.store.put(
                service.projections_namespace,
                fact["projection_id"],
                {**marker, "status": "pending"},
                index=False,
            )
        elif fault == "source_missing":
            service.store.delete(service.sources_namespace, source_ref)
        else:
            original = service.store.get(service.sources_namespace, source_ref).value
            service.store.put(
                service.sources_namespace,
                source_ref,
                {**original, "source_revision": 2},
                index=False,
            )
        with pytest.raises(ValueError) as caught:
            service.selected_observation_member(oid, object_id, "status")
        assert not isinstance(caught.value, ReadProtocolRejected)
        if fault == "fact_missing":
            assert str(caught.value) == "V13_SELECTED_OBSERVATION_UNAVAILABLE"
        elif fault in {"fact_changed", "marker_missing", "marker_changed"}:
            assert str(caught.value) == "V13_SELECTED_OBSERVATION_COMMIT_CHANGED"
        elif fault == "source_missing":
            assert str(caught.value) == "V13_SELECTED_OBSERVATION_SOURCE_CHANGED"
        else:
            assert "SOURCE" in str(caught.value)


@pytest.mark.parametrize(
    "a,b,c", [(a, b, c) for a in [False, True] for b in [False, True] for c in [False, True]]
)
def test_actual_eight_factor_compositions_catalog_hook_invoke(
    tmp_path: Path, a: bool, b: bool, c: bool
) -> None:
    from milai_lab.contracts.read_protocol import check_frozen, freeze_fields

    with opened(tmp_path, a=a, b=b, c=c) as service:
        config = turn(service)
        service.capture_user("history", "old", "archive multilingual evidence actual old source")
        settings = {
            "memory_mutation_contract": "event_bound_v1",
            "memory_candidate_contract": "read_handle_v1",
            "memory_read_protocol": "selected_snapshot_v1" if a else "legacy",
            "tool_read_feedback": "typed_read_v1" if b else "legacy",
            "tool_save_communication": "completed_receipt_v1" if c else "legacy",
            "memory_reader_policy": "bounded_evidence_v1",
        }
        catalog = d0._catalog(
            tmp_path,
            "field_grounded",
            mutation_contract="event_bound_v1",
            service_options=d0._service_options(settings),
            settings=settings,
        )
        frozen = {"config": settings, "tool_catalog": catalog, **freeze_fields(settings, catalog)}
        check_frozen(frozen)
        recipe = GroundedMemoryRecipe(service, lambda text: len(text.encode()) // 4)
        requests = []

        def transport(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "actual-factors",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"answer": "unchanged final"}),
                            },
                        }
                    ],
                },
            )

        tools = create_service_tools(
            service,
            recall_provider=recipe.recall_tool,
            selected_page_provider=recipe.selected_page_tool,
            source_index_provider=recipe.current_sources_tool,
            context_provider=recipe.search_tool,
        )
        with VLLMClient(
            VLLMConfig("http://synthetic/v1", "synthetic"), transport=httpx.MockTransport(transport)
        ) as client:
            model = LangMemRecipeChatModel(
                client=client, tool_save_communication=settings["tool_save_communication"]
            )
            model.begin_public_message("u")
            agent = build_agent(
                model,
                service.store,
                InMemorySaver(),
                memory_tools=tools,
                tool_save_communication=settings["tool_save_communication"],
                benchmark_view_hook=recipe.hook("Generic system", prefetch=a),
            )
            result = agent.invoke(
                {"messages": [HumanMessage("archive multilingual evidence", id="u")]}, config=config
            )
            assert result["messages"][-1].content == "unchanged final" and len(requests) == 1
        recall = next(t for t in tools if t.name == "recall_context")
        actual = call(recall, "recall_context", {}, config, "ordinary")
        assert json.loads(actual.content)["ok"]
        state = recipe.prepare_context(
            "archive multilingual evidence", owner="owner", session="s", turn_id="u"
        )
        assert state["reused"] and state["retrieval_calls"] == 0
        read = next(t for t in tools if t.name == "read_memory")
        if b:
            failure = call(read, "read_memory", {"view": "history"}, config, "typed")
            assert (
                failure.status == "error"
                and json.loads(failure.content)["origin"] == "memory_tools"
            )
        else:
            with pytest.raises(ValueError) as caught:
                call(read, "read_memory", {"view": "history"}, config, "legacy")
            assert type(caught.value) is ValueError
        assert (SAVE_GUIDANCE in requests[0]["messages"][0]["content"]) == c
