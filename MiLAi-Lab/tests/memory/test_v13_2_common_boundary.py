"""Actual public Store, recipe/Host paths and shared synthetic transport; no quality claim."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from milai_lab.contracts.common_boundary import profiles
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory.service import MemoryService
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import MeteredEmbeddings
from milai_lab.runners import v13_1_p5 as p5
from milai_lab.runners import v13_1_p5_compare as compare


def helper(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


shared = helper("common_control_helpers", "unit/test_v13_1_controls.py")
old = helper("common_p5_helpers", "memory/test_v13_1_p5.py")


def settings(tmp_path: Path, *, fallback: bool = False, arm: str = "B2") -> dict[str, Any]:
    cfg = shared.settings(tmp_path)
    cfg.update(
        cadence="matched_observation_v1",
        system_prompt="Same generic Host.",
        generation_admission_profile="durable_shared_v1",
        memory_mutation_contract="event_bound_v1",
        common_read_profile="bounded_public_v1",
        common_formation_profile="closed_host_v1",
        common_host_profile="read_only_v1",
        memory_writer_repairs=0,
    )
    cfg["controls"]["material_max_tokens"] = 2048
    cfg["controls"]["raw_rag"]["top_k"] = 6
    if arm == "B6":
        cfg["memory_observation_profile"] = "reservation_v1"
    if arm == "field_grounded":
        cfg.update(
            memory_reader_policy="bounded_evidence_v1",
            memory_source_backlinks="enabled",
            memory_candidate_contract="read_handle_v1",
            memory_material_profile="compact_v1",
        )
    if fallback:
        cfg["common_semantic_fallback"] = "single_summary_v1"
    return cfg


def transport(
    wires: list[Any], replies: list[dict[str, Any]], *, unknown: bool = False
) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        wires.append((request.url.path, body, request.read().hex()))
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(body["input"])
                    ],
                    "usage": {"total_tokens": 4},
                },
            )
        if unknown:
            raise httpx.ReadTimeout("scripted unknown", request=request)
        content = json.dumps(replies.pop(0) if replies else {"answer": "Actual final."})
        return httpx.Response(
            200,
            json={
                "id": "mock-" + str(len(wires)),
                "object": "chat.completion",
                "created": 0,
                "model": "same-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    return httpx.MockTransport(respond)


def model_at(
    cfg: dict[str, Any],
    root: Path,
    budget: RunBudget,
    trace: Any,
    wires: list[Any],
    replies: list[dict[str, Any]],
    unknown: bool = False,
) -> LangMemRecipeChatModel:
    return LangMemRecipeChatModel(
        client=VLLMClient(
            VLLMConfig(**cfg["host"]),
            capacity=HostCapacity(cfg["capacity"]),
            budget=budget,
            emit=trace,
            transport=transport(wires, replies, unknown=unknown),
        ),
        capacity_path=root / "host-capacity.json",
        max_calls_per_message=cfg["max_calls_per_message"],
        generation_admission_profile=cfg.get("generation_admission_profile", "legacy"),
    )


def local_runtime(
    tmp_path: Path, stack: ExitStack, arm: str = "B2", fallback: bool = False, unknown: bool = False
) -> tuple[Any, Any, list[Any], dict[str, Any]]:
    cfg = settings(tmp_path, arm=arm, fallback=fallback)
    wires: list[Any] = []
    budget = RunBudget(RunLimits(1, 1, 100, 1000000, 1000000), Path(cfg["budget_path"]))
    store = stack.enter_context(SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")))
    saver = stack.enter_context(SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")))
    service = MemoryService(
        store,
        ("common", "alice"),
        "alice",
        tmp_path / "memory.lock",
        mutation_contract="event_bound_v1",
    )
    source = service.capture_user("s", "u", "Actual Human body \u03b1")
    scope = FoundationScope("r", arm, "alice", "s")
    config = scope.config()
    config["configurable"].update(v13_session="s", v13_turn_id="u")
    model = model_at(
        cfg,
        tmp_path,
        budget,
        lambda row: None,
        wires,
        [{"summary": "Earlier actual data."}],
        unknown=unknown,
    )
    stack.callback(model.client.close)
    public = service.source(source["source_ref"])
    assert public is not None
    model.begin_public_message(
        "u",
        admission_phase="start",
        admission_scope={
            "owner": "alice",
            "bank": list(service.namespace),
            "session": "s",
            "request_ref": public["event_id"],
            "request_sha256": public["content_sha256"],
            "config_sha256": "c" * 64,
        },
    )
    # Constructor receives actual already-frozen method-only context.
    embedding = stack.enter_context(
        VLLMClient(VLLMConfig(**cfg["embedding"]), budget=budget, transport=transport(wires, []))
    )
    embed = MeteredEmbeddings(
        embedding, cfg["embedding"]["model"], cfg["embedding_capacity"], dimension=2, batch_size=2
    )
    frozen = {
        "config": cfg,
        "config_sha256": "c" * 64,
        "comparison_parameters": {
            "arm": arm,
            "cadence": "matched_observation_v1",
            "common_boundary": {k: v for k, v in profiles(cfg).items() if v != "legacy"},
        },
    }
    runtime = compare.ComparisonRuntime.__new__(compare.ComparisonRuntime)
    runtime.__dict__.update(
        frozen=frozen,
        settings=cfg,
        parameters=frozen["comparison_parameters"],
        service=service,
        store=store,
        saver=saver,
        scope=scope,
        model=model,
        budget=budget,
        trace=lambda event: None,
        stack=stack,
        resource_root=tmp_path,
        arm=arm,
        common=frozen["comparison_parameters"]["common_boundary"],
        common_profiles=profiles(cfg),
        pending=[],
        last_material={},
        recipe=None,
        formation_namespace=(*service.namespace, "p5_compare_formation"),
    )
    runtime.backend = compare.ObservedControls(store, saver, "r", arm, "alice", cfg, model, embed)
    return runtime, config, wires, cfg


@pytest.mark.parametrize("arm,fallback", [("B2", False), ("B6", False), ("B6", True)])
def test_closed_boundary_one_effect_and_continuation_no_recall(
    tmp_path: Path, arm: str, fallback: bool
) -> None:
    with ExitStack() as stack:
        runtime, cfg, wires, _ = local_runtime(tmp_path, stack, arm, fallback)
        human = HumanMessage(id="u", content="Actual Human body \u03b1")
        state = {"messages": [human]}
        assert not runtime.backend.snapshot("alice")["archive"]
        first = runtime.hook(state, cfg)
        before = len(wires)
        runtime.hook(
            {
                "messages": [
                    human,
                    AIMessage(
                        content="", tool_calls=[{"name": "get_reservation", "args": {}, "id": "t"}]
                    ),
                ]
            },
            cfg,
        )
        assert len(wires) == before and runtime.last_material["reused"]
        assert not runtime.backend.snapshot("alice")["archive"]
        with pytest.raises(ValueError, match="HOST_NOT_CLOSED"):
            runtime.completed(state["messages"], cfg)
        final = AIMessage(id="actual-final", content="Real final before formation")
        runtime.service.capture_assistant("s", final.id, final.content)
        result = runtime.completed([human, final], cfg)
        assert result["status"] == "COMPLETED"
        before = len(wires)
        again = runtime.completed([human, final], cfg)
        assert again["replayed"] and len(wires) == before
        generations = [body for path, body, _ in wires if path.endswith("chat/completions")]
        assert len(generations) == int(fallback)
        if fallback:
            assert runtime.model.calls_in_message == 1
            assert "Real final before formation" in generations[0]["messages"][1]["content"]
            assert runtime.backend.snapshot("alice")["closed_summary"] == "Earlier actual data."
        assert first["llm_input_messages"][-1].id == "u"


def test_summary_unknown_no_retry_or_refund(tmp_path: Path) -> None:
    with ExitStack() as stack:
        runtime, cfg, wires, _ = local_runtime(tmp_path, stack, "B6", True, True)
        human = HumanMessage(id="u", content="Actual Human body \u03b1")
        final = AIMessage(id="f", content="Actual final")
        runtime.service.capture_assistant("s", "f", final.content)
        with pytest.raises(httpx.ReadTimeout):
            runtime.completed([human, final], cfg)
        assert runtime.model.calls_in_message == 1
        before = len(wires)
        with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
            runtime.completed([human, final], cfg)
        assert len(wires) == before and runtime.model.calls_in_message == 1
        assert runtime.budget.state["generation_requests"] == 1
        # Semantic pending is independent of already completed raw/literal index formation.
        raw = runtime.backend.recall("alice", "Actual")
        assert raw["delivered_ids"] == []  # existing B6 indexes tool events only
        assert runtime.backend.snapshot("alice")["archive"]


@pytest.mark.parametrize("change", ["owner", "human", "hash", "missing"])
def test_actual_public_binding_rejects_drift(tmp_path: Path, change: str) -> None:
    with ExitStack() as stack:
        runtime, cfg, wires, _ = local_runtime(tmp_path, stack)
        runtime.hook({"messages": [HumanMessage(id="u", content="Actual Human body \u03b1")]}, cfg)
        before = len(wires)
        if change == "owner":
            cfg["configurable"]["user_id"] = "bob"
        elif change == "human":
            with pytest.raises(ValueError, match="ACTUAL_HUMAN"):
                runtime.hook({"messages": [HumanMessage(id="u", content="Changed")]}, cfg)
            return
        else:
            public = runtime.service.source(runtime.service.event_id("s", "u", "user"))
            assert public is not None
            if change == "hash":
                public["content"] = "Changed"
                runtime.store.put(
                    runtime.service.sources_namespace, public["event_id"], public, index=False
                )
            else:
                runtime.store.delete(runtime.service.sources_namespace, public["event_id"])
        with pytest.raises(ValueError):
            runtime._common_recall("Actual Human body \u03b1", cfg, ordinary=True)
        assert len(wires) == before


@pytest.mark.parametrize("arm", ["B2", "B6", "field_grounded"])
def test_actual_compare_prepare_step_catalog_and_closed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str
) -> None:
    old.prepared(tmp_path)
    cfg = settings(tmp_path, arm=arm, fallback=arm == "B6")
    write_json(tmp_path / "common-config.json", cfg)
    root = tmp_path / "common"
    frozen = compare.prepare(tmp_path / "public.json", tmp_path / "common-config.json", root, arm)
    names = [row["function"]["name"] for row in frozen["tool_catalog"]]
    assert "manage_memory" not in names and "revise_memory" not in names
    wires: list[Any] = []

    def make_model(settings: Any, budget: Any, trace: Any, resource: Any) -> Any:
        return model_at(
            settings,
            resource,
            budget,
            trace,
            wires,
            [
                {"answer": "Host final unchanged."},
                {"summary": "Actual earlier sources."},
                {"answer": "Decline all mutations."},
            ],
        )

    monkeypatch.setattr(p5, "make_model", make_model)
    original = compare.VLLMClient

    def client(config: Any, **kwargs: Any) -> Any:
        return original(config, transport=transport(wires, []), **kwargs)

    monkeypatch.setattr(compare, "VLLMClient", client)
    # M existing recipe opens the same central provider, no API or SDK substitution.
    monkeypatch.setattr(compare.d0, "VLLMClient", client)
    result = compare.step(root, "mechanical", 0, attempt_id="initial")
    assert result["status"] == "completed", result
    assert result["final_answer"] == "Host final unchanged."
    assert result["common_closed_formation"]
    assert len([p for p, _, _ in wires if p.endswith("chat/completions")]) == (
        1 if arm == "B2" else 2
    )
    admissions = result["generation_admissions"]
    row = next(iter(admissions["messages"].values()))
    assert row["count"] == (1 if arm == "B2" else 2)
    assert frozen["comparison_parameters"]["common_boundary"]


@pytest.mark.parametrize("arm", ["B2", "B6", "field_grounded"])
def test_actual_toolnode_two_observations_only_one_closed_formation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str
) -> None:
    from milai_lab.methods.grounded_memory import GroundedMemoryRecipe

    prepares = []
    original_prepare = GroundedMemoryRecipe.prepare_context

    def prepare_once(self: Any, *args: Any, **kwargs: Any) -> Any:
        prepares.append((args, kwargs))
        return original_prepare(self, *args, **kwargs)

    monkeypatch.setattr(GroundedMemoryRecipe, "prepare_context", prepare_once)
    old.prepared(tmp_path)
    cfg = settings(tmp_path, arm=arm, fallback=arm == "B6")
    write_json(tmp_path / "common-config.json", cfg)
    root = tmp_path / "common"
    compare.prepare(tmp_path / "public.json", tmp_path / "common-config.json", root, arm)
    wires: list[Any] = []
    script = [
        {"calls": [{"name": "reserve_and_label", "arguments": old.TARGET}]},
        {"calls": [{"name": "get_reservation", "arguments": {"item_key": "parcel"}}]},
        {"answer": "Exactly the actual Host final."},
        {"summary": "An actual reservation was observed."}
        if arm == "B6"
        else {"answer": "Decline all writes."},
    ]

    def make_model(settings: Any, budget: Any, trace: Any, resource: Any) -> Any:
        return model_at(settings, resource, budget, trace, wires, script)

    monkeypatch.setattr(p5, "make_model", make_model)
    original = compare.VLLMClient

    def client(config: Any, **kwargs: Any) -> Any:
        return original(config, transport=transport(wires, []), **kwargs)

    monkeypatch.setattr(compare, "VLLMClient", client)
    monkeypatch.setattr(compare.d0, "VLLMClient", client)
    result = compare.step(root, "mechanical", 0, attempt_id="tool-boundary")
    assert result["status"] == "completed", result
    assert result["final_answer"] == "Exactly the actual Host final."
    assert len([row for row in result["sources"] if row["role"] == "tool"]) == 2
    assert len([row for row in result["sources"] if row["role"] == "assistant"]) == 1
    events = [
        json.loads(line) for line in Path(result["material_trace_path"]).read_text().splitlines()
    ]
    closed = [row for row in events if row["event"] == "common_host_closed_before_formation"]
    assert len(closed) == 1 and len(closed[0]["requested"]["source_refs"]) == 4
    if arm != "field_grounded":
        assert len([e for e in events if e["event"] == "common_memory_material"]) == 1
        assert len([e for e in events if e["event"] == "common_memory_material_reused"]) == 2
    assert len([path for path, _, _ in wires if path.endswith("chat/completions")]) == (
        3 if arm == "B2" else 4
    )
    assert len(result["business_calls"]) == 2
    if arm == "field_grounded":
        assert len(prepares) == 1
    projection = [e for e in events if e["event"] == "v13_observation_capture"]
    assert len(projection) == (2 if arm == "B6" else 0)


def test_b6_summary_capacity_refusal_before_dispatch_retains_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old.prepared(tmp_path)
    cfg = settings(tmp_path, arm="B6", fallback=True)
    cfg["max_calls_per_message"] = 1
    write_json(tmp_path / "common-config.json", cfg)
    root = tmp_path / "common"
    compare.prepare(tmp_path / "public.json", tmp_path / "common-config.json", root, "B6")
    wires: list[Any] = []
    monkeypatch.setattr(
        p5,
        "make_model",
        lambda settings, budget, trace, resource: model_at(
            settings, resource, budget, trace, wires, [{"answer": "Host final."}]
        ),
    )
    original = compare.VLLMClient
    monkeypatch.setattr(
        compare,
        "VLLMClient",
        lambda config, **kwargs: original(config, transport=transport(wires, []), **kwargs),
    )
    result = compare.step(root, "mechanical", 0, attempt_id="summary-cap")
    assert result["status"] == "interrupted"
    assert result["error"] == "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"
    assert result["final_answer"] == "Host final."
    assert len([p for p, _, _ in wires if p.endswith("chat/completions")]) == 1
    assert next(iter(result["generation_admissions"]["messages"].values()))["count"] == 1


@pytest.mark.parametrize("failure", ["host_unknown", "summary_unknown"])
def test_actual_crossprocess_p5_resume_shared_cache_and_no_unknown_retry(
    tmp_path: Path, failure: str
) -> None:
    import subprocess

    old.prepared(tmp_path)
    cfg = settings(tmp_path, arm="B6", fallback=True)
    write_json(tmp_path / "common-config.json", cfg)
    root = tmp_path / "common"
    compare.prepare(tmp_path / "public.json", tmp_path / "common-config.json", root, "B6")
    results = []
    for phase in ["start", "resume"]:
        process = subprocess.run(  # noqa: S603 - fixed interpreter and local synthetic paths
            [sys.executable, str(Path(__file__)), str(root), phase, failure],
            capture_output=True,
            text=True,
            timeout=50,
        )
        assert process.returncode == 0, process.stderr
        results.append(read_json(p5.case_path(root, "mechanical") / f"attempt-{phase}.json"))
    before, after = results
    assert before["process_id"] != after["process_id"]
    assert before["status"] == "interrupted" and before["error_type"] == "ReadTimeout"
    count_before = next(iter(before["generation_admissions"]["messages"].values()))["count"]
    count_after = next(iter(after["generation_admissions"]["messages"].values()))["count"]
    if failure == "host_unknown":
        assert after["status"] == "completed", after
        assert count_before == 1 and count_after == 3
        assert after["comparison"]["material"]["reused"]
    else:
        assert after["status"] == "interrupted" and "OUTCOME_UNKNOWN" in after["error"]
        assert count_before == count_after == 2
    assert read_json(p5.case_path(root, "mechanical") / "first-error.json") == before["first_error"]
    if after["status"] == "interrupted":
        assert after["first_error"] == before["first_error"]


def _run_resume() -> None:
    root, phase, failure = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

    def make_model(cfg: Any, budget: Any, trace: Any, resource: Any) -> Any:
        count = 0

        def response(request: httpx.Request) -> httpx.Response:
            nonlocal count
            body = json.loads(request.read())
            if request.url.path.endswith("embeddings"):
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {"index": i, "embedding": [1.0, 0.0]}
                            for i, _ in enumerate(body["input"])
                        ],
                        "usage": {"total_tokens": 4},
                    },
                )
            count += 1
            if phase == "start" and count == (1 if failure == "host_unknown" else 2):
                raise httpx.ReadTimeout("scripted process unknown", request=request)
            content = (
                {"summary": "Actual closed data."}
                if body.get("response_format", {}).get("json_schema", {}).get("name")
                == "history_summary_v1"
                else {"answer": "Actual final."}
            )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": json.dumps(content)},
                        }
                    ],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                },
            )

        return LangMemRecipeChatModel(
            client=VLLMClient(
                VLLMConfig(**cfg["host"]),
                capacity=HostCapacity(cfg["capacity"]),
                budget=budget,
                emit=trace,
                transport=httpx.MockTransport(response),
            ),
            capacity_path=resource / "host-capacity.json",
            max_calls_per_message=cfg["max_calls_per_message"],
            generation_admission_profile=cfg["generation_admission_profile"],
        )

    p5.make_model = make_model
    original = compare.VLLMClient
    compare.VLLMClient = lambda config, **kwargs: original(
        config, transport=transport([], []), **kwargs
    )
    result = compare.step(root, "mechanical", 0, phase=phase, attempt_id=phase)
    print(json.dumps({"status": result["status"], "phase": phase}))


def test_actual_native_sdk_infer_empty_result_and_public_get_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mem0")
    import threading
    import uuid

    from mem0 import Memory
    from mem0.configs.embeddings.base import BaseEmbedderConfig
    from mem0.embeddings.openai import OpenAIEmbedding
    from mem0.llms.vllm import VllmLLM
    from mem0.memory.storage import SQLiteManager
    from qdrant_client import QdrantClient, models

    from milai_lab.integrations.memory.mem0 import Mem0NativeRuntime, _ChatCompletions, _Embeddings

    monkeypatch.setenv("MEM0_TELEMETRY", "false")
    with ExitStack() as stack:
        runtime, cfg, _wires, settings_ = local_runtime(tmp_path, stack, "B2")
        runtime.arm = "mem0_trace_equal"
        runtime.scope = FoundationScope("r", "mem0_trace_equal", "alice", "s")
        cfg = runtime.scope.config()
        cfg["configurable"].update(v13_session="s", v13_turn_id="u")
        embedding = runtime.backend.embeddings
        runtime.model.client._client.close()
        native_inputs: list[Any] = []

        def response(request: httpx.Request) -> httpx.Response:
            wire = json.loads(request.read())
            native_inputs.append(wire)
            return httpx.Response(
                200,
                json={
                    "id": "native",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "same-model",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"memory":[]}'},
                        }
                    ],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                },
            )

        runtime.model.client._client = httpx.Client(
            base_url=settings_["host"]["base_url"], transport=httpx.MockTransport(response)
        )
        embedder = OpenAIEmbedding(BaseEmbedderConfig(model="bge-m3", api_key="local"))
        embedder.client.close()
        lock = threading.Lock()
        embedder.client = SimpleNamespace(
            embeddings=_Embeddings(compare._EmbeddingBridge(embedding), lock)
        )
        llm = VllmLLM(
            {
                "model": "same-model",
                "temperature": runtime.model.client.config.temperature,
                "max_tokens": runtime.model.client.config.max_tokens,
                "api_key": "local",
                "top_p": 1.0,
            }
        )
        llm.client.close()
        rejected: list[str] = []
        llm.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=_ChatCompletions(
                    runtime.model.client, lock, runtime.model._reserve_request, rejected
                )
            )
        )
        client = QdrantClient(path=str(tmp_path / "native-qdrant"))
        client.create_collection(
            "carrier", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE)
        )
        native = Mem0NativeRuntime.__new__(Mem0NativeRuntime)
        memory = native.memory = Memory.__new__(Memory)
        memory.db = SQLiteManager(str(tmp_path / "native-history.sqlite"))
        memory.config = SimpleNamespace(llm=SimpleNamespace(config={}))
        memory.api_version = "v1.1"
        memory.embedding_model, memory.llm = embedder, llm
        memory._entity_store, memory.custom_instructions = None, None

        def filtered(**kwargs: Any) -> list[Any]:
            filters = kwargs.get("filters", {})
            return client.scroll(
                "carrier",
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(key=key, match=models.MatchValue(value=value))
                        for key, value in filters.items()
                    ]
                ),
            )[0]

        def get(vector_id: str) -> Any:
            found = client.retrieve("carrier", ids=[vector_id])
            return found[0] if found else None

        memory.vector_store = SimpleNamespace(
            client=client,
            search=lambda **kwargs: [],
            list=lambda **kwargs: (filtered(**kwargs), None),
            get=get,
        )
        native.run_id, native.arm_id = "r", "mem0_trace_equal"
        native.host, native.admission_rejections = runtime.model.client, rejected
        stack.callback(native.close)
        runtime.backend = native
        # SDK infer=True remains real. The finite vector facade with empty facts
        # exercises actual SDK preprocessing/extraction/storage. Native ranking is not covered.
        original_add = memory.add
        calls: list[Any] = []

        def add(messages: Any, **kwargs: Any) -> Any:
            calls.append((json.loads(json.dumps(messages)), kwargs))
            return original_add(messages, **kwargs)

        memory.add = add
        human = HumanMessage(id="u", content="Actual Human body \u03b1")
        final = AIMessage(id="f", content="Original Host final")
        runtime.service.capture_assistant("s", "f", final.content)
        result = runtime.completed([human, final], cfg)
        assert result["status"] == "COMPLETED"
        assert calls[0][1] == {"user_id": native._user_id("alice"), "infer": True}
        original_rows = json.loads(calls[0][0][0]["content"].split("\n", 1)[1])
        assert [row["role"] for row in original_rows] == ["user", "assistant"]
        assert runtime.model.calls_in_message == 1 and len(native_inputs) == 1
        assert runtime.completed([human, final], cfg)["replayed"] and len(calls) == 1
        # Actual public Qdrant records + native get/get_all/history use real IDs and owners.
        target = str(uuid.uuid4())
        text = "Actual native stored note"
        client.upsert(
            "carrier",
            points=[
                models.PointStruct(
                    id=target,
                    vector=[1.0, 0.0],
                    payload={
                        "data": text,
                        "hash": hashlib.md5(text.encode(), usedforsecurity=False).hexdigest(),
                        "user_id": native._user_id("alice"),
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                    },
                )
            ],
        )
        memory.db.add_history(target, None, text, "ADD")
        # This finite carrier tests the binding/get/history adapter, not native search.
        native.search_archive = lambda owner, query: {"results": [memory.get(target)]}
        view = runtime._common_recall("Actual Human body \u03b1", cfg, ordinary=True)
        assert view["packet"]["selected"][0]["id"] == target
        assert view["snapshot_rows"][0]["user_id"] == native._user_id("alice")
        page = runtime.native_read(target, cfg)
        explicit = runtime._common_recall("An actual explicit query", cfg)
        explicit_page = runtime.native_read(
            target, cfg, snapshot_sha256=explicit["packet"]["snapshot_sha256"]
        )
        assert explicit_page["actual"]["record"] == page["actual"]["record"]
        assert page["actual"]["valid"] and page["actual"]["history"][0]["event"] == "ADD"
        assert page["actual"]["record"]["memory"] == text
        assert "candidate_handle" not in json.dumps(page)
        assert "no M revision" in page["protection"]
        with pytest.raises(ValueError, match="SELECTED_ID"):
            runtime.native_read(str(uuid.uuid4()), cfg)
        client.set_payload("carrier", payload={"user_id": "other-owner"}, points=[target])
        with pytest.raises(ValueError, match="OWNER_OR_READBACK"):
            runtime.native_read(target, cfg)


@pytest.mark.parametrize("failure", ["cache_missing", "cache_corrupt", "metadata_changed"])
def test_resume_packet_fail_closed_before_any_transport(tmp_path: Path, failure: str) -> None:
    with ExitStack() as stack:
        runtime, cfg, wires, _ = local_runtime(tmp_path, stack)
        runtime.hook({"messages": [HumanMessage(id="u", content="Actual Human body \u03b1")]}, cfg)
        namespace = (*runtime.service.namespace, "common_reader_v1")
        key = "ordinary:" + compare.digest(["s", "u"])
        cached = runtime.store.get(namespace, key)
        assert cached is not None
        if failure == "cache_missing":
            runtime.store.delete(namespace, key)
        elif failure == "cache_corrupt":
            value = cached.value
            value["packet"]["returned_count"] = 999
            runtime.store.put(namespace, key, value, index=False)
        else:
            value = cached.value
            value["result_metadata"]["semantic_evidence"] = True
            runtime.store.put(namespace, key, value, index=False)
        before = len(wires)
        with pytest.raises(ValueError, match=r"(RESUMED_PACKET_MISSING|CACHED_PACKET_CHANGED)"):
            runtime.resume_context(cfg)
        assert len(wires) == before


def test_actual_native_public_constructor_close_and_process_reopen(tmp_path: Path) -> None:
    pytest.importorskip("mem0")
    import subprocess

    driver = Path(__file__).resolve()
    results = []
    for phase in ["start", "resume"]:
        process = subprocess.run(  # noqa: S603 - fixed interpreter and local synthetic paths
            [sys.executable, str(driver), "native-lifecycle", str(tmp_path), phase],
            capture_output=True,
            text=True,
            timeout=60,
        )
        (tmp_path / (phase + ".stdout.log")).write_text(process.stdout)
        (tmp_path / (phase + ".stderr.log")).write_text(process.stderr)
        assert process.returncode == 0, process.stderr
        results.append(read_json(tmp_path / ("result-" + phase + ".json")))
    before, after = results
    assert before["process_id"] != after["process_id"]
    assert before["snapshot_before_close"] == after["snapshot_before_close"]
    assert before["record"] == after["record"] and before["history"] == after["history"]
    assert before["actual_close_returned"] and after["actual_close_returned"]
    assert before["calls_in_message"] == after["calls_in_message"] == 1
    assert not any(row["path"].endswith("chat/completions") for row in after["wires"])


def test_actual_native_compare_entry_closed_formation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mem0")
    old.prepared(tmp_path)
    cfg = settings(tmp_path, arm="mem0_trace_equal")
    cfg["embedding_dimension"] = 1024
    write_json(tmp_path / "native-config.json", cfg)
    root = tmp_path / "native-compare"
    frozen = compare.prepare(
        tmp_path / "public.json", tmp_path / "native-config.json", root, "mem0_trace_equal"
    )
    assert "read_native_memory" in [row["function"]["name"] for row in frozen["tool_catalog"]]
    wires = []

    def response(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append({"path": request.url.path, "body": wire, "raw_hex": request.read().hex()})
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0] + [0.0] * 1023}
                        for i, _ in enumerate(wire["input"])
                    ],
                    "usage": {"total_tokens": 4},
                },
            )
        content = (
            {"memory": []}
            if len([row for row in wires if row["path"].endswith("chat/completions")]) > 1
            else {"answer": "Native Host final unchanged."}
        )
        return httpx.Response(
            200,
            json={
                "id": "native-entry-" + str(len(wires)),
                "object": "chat.completion",
                "created": 0,
                "model": "same-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(content)},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    def make_model(cfg: Any, budget: Any, trace: Any, resource: Any) -> Any:
        return LangMemRecipeChatModel(
            client=VLLMClient(
                VLLMConfig(**cfg["host"]),
                capacity=HostCapacity(cfg["capacity"]),
                budget=budget,
                emit=trace,
                transport=httpx.MockTransport(response),
            ),
            capacity_path=resource / "host-capacity.json",
            max_calls_per_message=cfg["max_calls_per_message"],
            generation_admission_profile=cfg["generation_admission_profile"],
        )

    monkeypatch.setattr(p5, "make_model", make_model)
    original = compare.VLLMClient
    monkeypatch.setattr(
        compare,
        "VLLMClient",
        lambda config, **kwargs: original(
            config, transport=httpx.MockTransport(response), **kwargs
        ),
    )
    result = compare.step(root, "mechanical", 0, attempt_id="native-real-entry")
    assert result["status"] == "completed", result
    assert result["final_answer"] == "Native Host final unchanged."
    assert result["common_closed_formation"]["archive_input_profile"] == "observed_events_v1"
    assert len([row for row in wires if row["path"].endswith("chat/completions")]) == 2
    assert next(iter(result["generation_admissions"]["messages"].values()))["count"] == 2
    write_json(tmp_path / "native-entry-wires.json", wires)


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_actual_closed_m_writer_source_role_and_truthful_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    old.prepared(tmp_path)
    cfg = settings(tmp_path, arm="field_grounded")
    write_json(tmp_path / "writer-config.json", cfg)
    root = tmp_path / "writer"
    freeze = compare.prepare(
        tmp_path / "public.json", tmp_path / "writer-config.json", root, "field_grounded"
    )
    assert "manage_memory" not in [row["function"]["name"] for row in freeze["tool_catalog"]]
    wires = []

    def response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        wires.append({"path": request.url.path, "body": body})
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(body["input"])
                    ],
                    "usage": {"total_tokens": 4},
                },
            )
        if len([row for row in wires if row["path"].endswith("chat/completions")]) == 1:
            content = {"answer": "Host final precedes writer."}
        else:
            actual = json.loads(body["messages"][-1]["content"])["actual_events"]
            chosen = next(row for row in actual if row["role"] == role)
            content = {
                "calls": [
                    {
                        "name": "manage_memory",
                        "arguments": {
                            "content": "Scripted generic note; entailment remains unchecked.",
                            "source_refs": [chosen["event_id"]],
                        },
                    }
                ]
            }
        return httpx.Response(
            200,
            json={
                "id": "writer-" + str(len(wires)),
                "object": "chat.completion",
                "created": 0,
                "model": "same-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(content)},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    def make_model(cfg: Any, budget: Any, trace: Any, resource: Any) -> Any:
        return LangMemRecipeChatModel(
            client=VLLMClient(
                VLLMConfig(**cfg["host"]),
                capacity=HostCapacity(cfg["capacity"]),
                budget=budget,
                emit=trace,
                transport=httpx.MockTransport(response),
            ),
            capacity_path=resource / "host-capacity.json",
            max_calls_per_message=cfg["max_calls_per_message"],
            generation_admission_profile=cfg["generation_admission_profile"],
        )

    monkeypatch.setattr(p5, "make_model", make_model)
    original = compare.d0.VLLMClient
    monkeypatch.setattr(
        compare.d0,
        "VLLMClient",
        lambda config, **kwargs: original(
            config, transport=httpx.MockTransport(response), **kwargs
        ),
    )
    result = compare.step(root, "mechanical", 0, attempt_id="source-role")
    assert result["status"] == "completed", result
    assert result["final_answer"] == "Host final precedes writer."
    receipt = result["common_closed_formation"]
    assert receipt["generation_calls"] == 1
    assert len([row for row in wires if row["path"].endswith("chat/completions")]) == 2
    assert next(iter(result["generation_admissions"]["messages"].values()))["count"] == 2
    if role == "user":
        assert result["records"] and receipt["status"] == "committed", receipt
        assert receipt["receipts"][0]["receipt"]["source_bindings"][0]["role"] == "user"
    else:
        assert not result["records"] and receipt["status"] == "pending", receipt
        assert receipt["receipts"][0]["receipt"]["ok"] is False
        before = len(wires)
        resumed = compare.step(root, "mechanical", 0, phase="resume", attempt_id="pending-resume")
        assert resumed["status"] == "interrupted"
        assert "FORMATION_OUTCOME_UNKNOWN" in resumed["error"]
        assert len(wires) == before
        assert next(iter(resumed["generation_admissions"]["messages"].values()))["count"] == 2
    write_json(tmp_path / "actual-writer-wires-and-result.json", {"wires": wires, "result": result})


def _native_lifecycle(root: Path, phase: str) -> None:
    import os

    from milai_lab.integrations.memory.mem0 import Mem0NativeRuntime, mem0_dependency_identity

    root.mkdir(parents=True, exist_ok=True)
    cfg = shared.settings(root)
    cfg["embedding_dimension"] = 1024
    wires = []

    def response(request):
        wire = json.loads(request.read())
        wires.append({"path": request.url.path, "body": wire, "raw_hex": request.read().hex()})
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0] + [0.0] * 1023}
                        for i, _ in enumerate(wire["input"])
                    ],
                    "usage": {"total_tokens": 4},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "native-lifecycle",
                "object": "chat.completion",
                "created": 0,
                "model": "same-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"memory":[]}'},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    budget = RunBudget(RunLimits(1, 1, 100, 1000000, 1000000), root / "synthetic-budget.json")
    events = []
    with ExitStack() as stack:
        host = stack.enter_context(
            VLLMClient(
                VLLMConfig(**cfg["host"]),
                capacity=HostCapacity(cfg["capacity"]),
                budget=budget,
                transport=httpx.MockTransport(response),
                emit=events.append,
            )
        )
        embed = stack.enter_context(
            VLLMClient(
                VLLMConfig(**cfg["embedding"]),
                budget=budget,
                transport=httpx.MockTransport(response),
            )
        )
        metered = MeteredEmbeddings(
            embed,
            cfg["embedding"]["model"],
            cfg["embedding_capacity"],
            dimension=1024,
            batch_size=2,
        )
        model = LangMemRecipeChatModel(
            client=host,
            capacity_path=root / "admission.json",
            max_calls_per_message=12,
            generation_admission_profile="durable_shared_v1",
        )
        model.begin_public_message(
            "native-turn",
            admission_phase="start" if phase == "start" else "resume",
            admission_scope={
                "owner": "alice",
                "bank": ["native"],
                "session": "s",
                "request_ref": "actual-source",
                "request_sha256": "a" * 64,
                "config_sha256": "c" * 64,
            },
        )
        native = Mem0NativeRuntime(
            root / "native",
            "run",
            "arm",
            host,
            compare._EmbeddingBridge(metered),
            admit_generation=model._reserve_request,
        )
        snapshot_before_close = None
        try:
            if phase == "start":
                # Synthetic fixture seeding is explicit infer=False; formation remains infer=True.
                native.memory.add(
                    "Literal seed note", user_id=native._user_id("alice"), infer=False
                )
                native.memory.add("Other owner note", user_id=native._user_id("bob"), infer=False)
                rows = native.snapshot("alice")
                assert len(rows) == 1, rows
                target = rows[0]["id"]
                write_json(root / "selected-id.json", {"id": target})
                receipt = native.add_archive(
                    "alice",
                    [
                        {
                            "event_id": "actual-source",
                            "owner": "alice",
                            "role": "user",
                            "content": "Actual public Human",
                        },
                        {
                            "event_id": "actual-final",
                            "owner": "alice",
                            "role": "assistant",
                            "content": "Actual final",
                        },
                    ],
                    archive_input_profile="observed_events_v1",
                )
                assert receipt["status"] == "COMPLETED" and model.calls_in_message == 1, receipt
            else:
                target = read_json(root / "selected-id.json")["id"]
                receipt = None
                assert model.calls_in_message == 1
            snapshot_before_close = native.snapshot("alice")
            record = native.memory.get(target)
            history = native.memory.history(target)
            assert (
                record["user_id"] == native._user_id("alice")
                and record["memory"] == "Literal seed note"
            )
            assert history and history[0]["event"] == "ADD"
            assert len(snapshot_before_close) == 1 and len(native.snapshot("bob")) == 1
            # Actual native search preserves SDK query/preprocessing/filter/rank/threshold.
            search = native.search_archive("alice", "Literal seed note")
            assert all(row["user_id"] == native._user_id("alice") for row in search["results"])
            result = {
                "process_id": os.getpid(),
                "phase": phase,
                "sdk": mem0_dependency_identity(),
                "snapshot_before_close": snapshot_before_close,
                "record": record,
                "history": history,
                "search": search,
                "receipt": receipt,
                "calls_in_message": model.calls_in_message,
                "wires": wires,
                "events": events,
                "limits": (
                    "get_all default limit=100; native search returned subset top_k20 "
                    "threshold0.1; no full corpus/history/CAS claim"
                ),
            }
        finally:
            native.close()
        result["actual_close_returned"] = True
        result["qdrant_client_closed"] = native.memory.vector_store.client._client.closed
    write_json(root / ("result-" + phase + ".json"), result)
    print(
        json.dumps(
            {
                "phase": phase,
                "actual_constructor": True,
                "snapshot_before_close": len(snapshot_before_close),
                "closed": result["actual_close_returned"],
                "generations": model.calls_in_message,
            }
        )
    )


if __name__ == "__main__":
    if sys.argv[1] == "native-lifecycle":
        _native_lifecycle(Path(sys.argv[2]), sys.argv[3])
    else:
        _run_resume()
