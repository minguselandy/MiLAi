"""Synthetic actual SDK, tool, entry and wire checks; no semantic oracle."""

from __future__ import annotations

import copy
import json
import runpy
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode, create_react_agent
from langgraph.store.sqlite import SqliteStore
from pydantic import ValidationError

from milai_lab.baselines.langmem_agent import build_agent
from milai_lab.contracts.memory import ObservationField, ObservationProfile
from milai_lab.contracts.public_memory_contracts import capture_effect
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory import service as service_module
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.compact_exact import decode
from milai_lab.methods.grounded_memory import GroundedMemoryRecipe
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import v13_1_d0 as d0
from milai_lab.runners import v13_1_p5 as p5

LAB = Path(__file__).resolve().parents[2]
ROOT = LAB / "artifacts/v13-2-public-contract-method-engineering"
READ = runpy.run_path(str(LAB / "tests/memory/test_v13_2_read_protocol.py"))
DIRECT = runpy.run_path(str(LAB / "tests/memory/test_v13_2_direct_support.py"))
FIELDS = ("content", "scope", "basis", "kind")


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class Clock:
        @staticmethod
        def now(*args: Any, **kwargs: Any) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(service_module, "datetime", Clock)


@contextmanager
def opened(path: Path, *, guide="legacy", feedback="legacy", direct=True, observer=None):
    with SqliteStore.from_conn_string(str(path / "store.sqlite")) as store:
        yield MemoryService(
            store,
            ("synthetic", "alice"),
            "alice",
            path / "service.lock",
            mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1",
            support_contract="direct_support_v1" if direct else "legacy",
            source_backlinks="enabled",
            tool_parameter_contract=guide,
            observation_capture_feedback=feedback,
            observer=observer,
        )


@pytest.fixture(autouse=True)
def portable_frozen_sources(monkeypatch, frozen_pre_http_sources):
    monkeypatch.setitem(globals(), "ROOT", frozen_pre_http_sources)


def proof(path: Path, name: str, value: Any) -> None:
    target = path / name
    assert not target.exists()
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def projection_profile() -> ObservationProfile:
    return ObservationProfile(
        "synthetic.literal",
        "1",
        "synthetic.application",
        ("literal_tool",),
        ("object_id",),
        (
            ObservationField("color", ("color",), "string"),
            ObservationField("count", ("count",), "integer"),
        ),
        owner_path=("owner",),
        resource_version_path=("revision",),
        resource_version_type="integer",
    )


@pytest.mark.parametrize("failure", ["none", "first_fact", "second_fact", "complete_marker"])
def test_actual_projection_complete_pending_reopen_and_feedback_without_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    profile = projection_profile()
    with opened(tmp_path, feedback="typed_effect_v1") as service:
        body = {
            "object_id": "actual-object",
            "owner": "alice",
            "revision": 1,
            "color": "蓝色 / azul",
            "count": 2,
        }
        raw = service.capture_tool("s", "literal", "literal_tool", json.dumps(body), None)
        original = service.store.put
        fact_writes = 0

        def write(namespace, key, value, **kwargs):
            nonlocal fact_writes
            if namespace == service.observations_namespace:
                fact_writes += 1
                if failure == "first_fact" and fact_writes == 1:
                    raise OSError("synthetic first fact write cut")
                if failure == "second_fact" and fact_writes == 2:
                    raise OSError("synthetic second fact write cut")
            if failure == "complete_marker" and namespace == service.projections_namespace:
                if value.get("status") == "complete":
                    raise OSError("synthetic marker write cut")
            return original(namespace, key, value, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(service.store, "put", write)
            receipt = service.observe(raw["source_ref"], profile)
        assert receipt["ok"] == (failure == "none")
        assert receipt["expected_observation_count"] == 2
        with monkeypatch.context() as patch:

            def denied(*args, **kwargs):
                raise AssertionError("feedback must not access Store or observe")

            for name in ["get", "put", "search"]:
                patch.setattr(service.store, name, denied)
            patch.setattr(service, "observe", denied)
            effect = capture_effect(raw, receipt, service.observation_capture_feedback)
        typed = effect["completed_capture_effect"]
        assert typed["confirmed_observation_count"] == (2 if failure == "none" else None)
        assert typed["raw_sources_acknowledged"] == 1
        assert typed["semantic_commit"] == "not_acknowledged_by_capture"
        view = service.observations()
        assert len(view["observations"]) == (2 if failure == "none" else 0)
        assert bool(view["pending"]) == (failure != "none")
        proof(
            tmp_path,
            "projection-first.json",
            {"capture": raw, "receipt": receipt, "typed": effect, "view": view},
        )
    with opened(tmp_path, feedback="typed_effect_v1") as service:
        assert service.source(raw["source_ref"])["content"] == json.dumps(body)
        before = service.projection_receipt(raw["source_ref"], profile)
        assert before["status"] == ("projected" if failure == "none" else "pending")
        # Explicit test recovery, not feedback/runner automatic retry.
        replay = service.observe(raw["source_ref"], profile)
        assert replay["ok"] and replay["observation_count"] == 2
        if failure == "none":
            assert replay["replayed"] and replay["status"] == "no_change"
        assert len(service.observations()["observations"]) == 2
        proof(tmp_path, "projection-reopen.json", {"before": before, "explicit_replay": replay})


@pytest.mark.parametrize(
    "body,outcome",
    [
        ({"status": "ORIGINAL_CALL_OUTCOME_UNKNOWN"}, "unknown"),
        ({"color": "literal only"}, "observed"),
    ],
)
def test_zero_observations_remain_explicit(tmp_path: Path, body: dict, outcome: str) -> None:
    with opened(tmp_path, feedback="typed_effect_v1") as service:
        raw = service.capture_tool("s", "empty", "literal_tool", json.dumps(body), None)
        receipt = service.observe(raw["source_ref"], projection_profile())
        assert receipt["ok"] and receipt["outcome"] == outcome
        assert receipt["observation_count"] == 0
        typed = capture_effect(raw, receipt, "typed_effect_v1")["completed_capture_effect"]
        assert typed["confirmed_observation_count"] == 0
        assert typed["observation_status"] == receipt["status"]


def test_observer_unknown_failure_propagates_without_completed_feedback(tmp_path: Path) -> None:
    def fail(event):
        if event.get("phase") == "source_persisted":
            raise RuntimeError("synthetic observer failure")

    with opened(tmp_path, feedback="typed_effect_v1", observer=fail) as service:
        raw = service.capture_tool(
            "s",
            "literal",
            "literal_tool",
            json.dumps({"object_id": "actual", "owner": "alice", "color": "red"}),
            None,
        )
        with pytest.raises(RuntimeError, match="observer failure"):
            service.observe(raw["source_ref"], projection_profile())
        assert (
            service.projection_receipt(raw["source_ref"], projection_profile())["status"]
            == "pending"
        )


def test_real_tool_guidance_and_unchanged_outer_source_guard(tmp_path: Path) -> None:
    with opened(tmp_path, guide="explicit_shape_v1") as service:
        user = DIRECT["turn"](service)
        outside = service.capture_user("s", "old", "Actual old statement")["source_ref"]
        arguments = {
            "content": "Actual body",
            "source_refs": [user],
            "field_support": DIRECT["selected"]([outside]),
        }
        refused = DIRECT["invoke"](service, "manage_memory", arguments, "outside")
        assert not refused["ok"] and refused["reason"] == "field_support_selected_leaves_required"
        assert not service.records()
        arguments["field_support"] = DIRECT["selected"]([user])
        complete = DIRECT["invoke"](service, "manage_memory", arguments, "complete")
        assert complete["ok"] and complete["field_support"]["content"]["source_refs"] == [user]
        assert DIRECT["invoke"](service, "manage_memory", arguments, "complete")["replayed"]
        tools = create_service_tools(service)
        manage = next(t for t in tools if t.name == "manage_memory")
        assert "SUBSET of the outer selected source_refs" in manage.description
        assert "content is always a STRING" in manage.description
        with pytest.raises(ValidationError):
            DIRECT["invoke"](
                service, "manage_memory", {**arguments, "content": {"value": "actual"}}, "dict"
            )
        with pytest.raises(ValidationError):
            DIRECT["invoke"](
                service, "manage_memory", {**arguments, "object_ref": {"s": 0}}, "index"
            )
        proof(
            tmp_path,
            "tool-receipts.json",
            {
                "refused": refused,
                "complete": complete,
                "catalog": [convert_to_openai_tool(t) for t in tools],
            },
        )


@pytest.mark.parametrize("receipt_profile", ["reservation_v1", "document_publication_v1"])
def test_actual_public_schema_unchanged_guide_declares_actual_fields(
    tmp_path: Path,
    receipt_profile: str,
) -> None:
    with SqliteStore.from_conn_string(":memory:") as store:
        old_factory = runpy.run_path(
            str(ROOT / "base-source/src/milai_lab/memory/service_tools.py")
        )["create_service_tools"]

        def service(guide):
            return MemoryService(
                store,
                ("synthetic", "alice"),
                "alice",
                tmp_path / "lock",
                receipt_contract="explicit_receipt_v1",
                receipt_profile=receipt_profile,
                tool_parameter_contract=guide,
            )

        legacy = service("legacy")
        old = [convert_to_openai_tool(t) for t in old_factory(legacy)]
        default = [convert_to_openai_tool(t) for t in create_service_tools(legacy)]
        active_service = service("explicit_shape_v1")
        active = [convert_to_openai_tool(t) for t in create_service_tools(active_service)]
        assert old == default
        for original, described in zip(default, active, strict=True):
            assert original["function"]["parameters"] == described["function"]["parameters"]
            if described["function"]["name"] in {"manage_memory", "revise_memory"}:
                assert "receipt_json_v1" in described["function"]["description"]
                assert all(
                    name in described["function"]["description"]
                    for name in active_service.receipt_fields
                )
        proof(tmp_path, "catalogs.json", {"old": old, "default": default, "active": active})


@pytest.mark.parametrize("runner", [d0, p5])
def test_real_entry_profiles_start_writer_and_freeze_predispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: Any,
) -> None:
    fp, cp, settings = READ["synthetic_settings"](tmp_path)
    settings.update(
        tool_parameter_contract="explicit_shape_v1",
        observation_capture_feedback="typed_effect_v1",
        memory_material_profile="compact_exact_v1",
    )
    write_json(cp, settings)
    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if "input" in body:
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
                            "content": json.dumps({"answer": "Original final remains unchanged"}),
                        },
                    }
                ],
            },
        )

    def client(*args, **kwargs):
        return VLLMClient(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(runner, "VLLMClient", client)
    root = tmp_path / "run"
    frozen = runner.prepare(fp, cp, root)
    assert frozen["public_memory_contract_presentation"]["profiles"] == {
        "tool_parameter_contract": "explicit_shape_v1",
        "observation_capture_feedback": "typed_effect_v1",
    }
    assert frozen["config"]["memory_material_profile"] == "compact_exact_v1"
    result = runner.step(root, "synthetic-entry", 0)
    assert result["status"] == "completed", result
    assert result["final_answer"] == "Original final remains unchanged"
    assert result["semantic_maintenance"]["generation_calls"] == 1
    generation = [r for r in requests if "messages" in r]
    assert len(generation) == 2
    assert any("explicit_shape_v1" in json.dumps(r) for r in generation)
    assert any("json_dictionary_v1" in json.dumps(r) for r in generation)
    before = len(requests)
    drift = read_json(root / "input-freeze.json")
    drift["observation_capture_feedback"] = "legacy"
    write_json(root / "input-freeze.json", drift)
    with pytest.raises(ValueError, match="FROZEN_CHANGED"):
        runner._frozen(root)
    assert len(requests) == before
    proof(tmp_path, "actual-entry.json", {"freeze": frozen, "requests": requests, "result": result})


@pytest.mark.parametrize("mode", ["native", "json_action"])
@pytest.mark.parametrize("model_class", [VLLMChatModel, LangMemRecipeChatModel])
@pytest.mark.parametrize("explicit_legacy", [False, True])
def test_eight_default_memory_graph_wire_and_receipt_bytes(
    tmp_path: Path,
    mode: str,
    model_class: Any,
    explicit_legacy: bool,
) -> None:
    old_factory = runpy.run_path(str(ROOT / "base-source/src/milai_lab/memory/service_tools.py"))[
        "create_service_tools"
    ]
    old_recipe = runpy.run_path(str(ROOT / "base-source/src/milai_lab/methods/grounded_memory.py"))[
        "GroundedMemoryRecipe"
    ]
    comparisons = []
    for identity, factory, recipe_type in [
        ("base", old_factory, old_recipe),
        ("current", create_service_tools, GroundedMemoryRecipe),
    ]:
        path = tmp_path / identity
        path.mkdir()
        options = (
            {"tool_parameter_contract": "legacy", "observation_capture_feedback": "legacy"}
            if explicit_legacy
            else {}
        )
        with SqliteStore.from_conn_string(str(path / "store.sqlite")) as store:
            service = MemoryService(
                store, ("synthetic", "alice"), "alice", path / "lock", **options
            )
            source = service.capture_user("s", "u", "Actual generic statement")["source_ref"]
            recipe = recipe_type(service, lambda s: len(s.encode()) // 4)
            material = recipe.prepare_context(
                "Actual generic statement", owner="alice", session="s", turn_id="u"
            )
            tools = factory(service)
            catalog = [convert_to_openai_tool(t) for t in tools]
            wires = []

            def transport(request, wires=wires, source=source):
                number = len(wires)
                if number == 0:
                    call = {
                        "name": "manage_memory",
                        "arguments": {"content": "Actual retained body", "source_ref": source},
                    }
                    message = {"role": "assistant", "content": json.dumps({"calls": [call]})}
                    if mode == "native":
                        message.update(
                            content=None,
                            tool_calls=[
                                {
                                    "id": "actual-call",
                                    "type": "function",
                                    "function": {
                                        "name": call["name"],
                                        "arguments": json.dumps(call["arguments"]),
                                    },
                                }
                            ],
                        )
                else:
                    message = {
                        "role": "assistant",
                        "content": "Final byte string"
                        if mode == "native"
                        else json.dumps({"answer": "Final byte string"}),
                    }
                response = httpx.Response(
                    200,
                    json={
                        "id": "r" + str(number),
                        "choices": [
                            {
                                "finish_reason": "tool_calls"
                                if number == 0 and mode == "native"
                                else "stop",
                                "message": message,
                            }
                        ],
                        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                    },
                )
                wires.append(
                    {"request_hex": request.content.hex(), "response_hex": response.content.hex()}
                )
                return response

            budget = RunBudget(RunLimits(generation_requests=12), path / "budget.json")
            with VLLMClient(
                VLLMConfig("http://synthetic/v1", "synthetic", tool_mode=mode),
                budget=budget,
                transport=httpx.MockTransport(transport),
            ) as client:

                def stable_delivery(request, execute):
                    result = execute(request)
                    assert isinstance(result, ToolMessage)
                    return result.model_copy(update={"id": "synthetic-stable-delivery"})

                model = model_class(client=client)
                model.begin_public_message("u")
                agent = (
                    create_react_agent(
                        model,
                        ToolNode(tools, wrap_tool_call=stable_delivery),
                        store=store,
                        checkpointer=InMemorySaver(),
                        prompt="Synthetic Host",
                    )
                    if model_class is VLLMChatModel
                    else build_agent(
                        model,
                        business_tools=(),
                        memory_tools=tools,
                        store=store,
                        checkpointer=InMemorySaver(),
                        system_prompt="Synthetic Host",
                        business_call_wrapper=stable_delivery,
                    )
                )
                outcome = agent.invoke(
                    {"messages": [HumanMessage("Actual generic statement", id="u")]},
                    config={
                        **FoundationScope("run", "arm", "alice", "s").config(),
                        "configurable": {
                            **FoundationScope("run", "arm", "alice", "s").config()["configurable"],
                            "v13_session": "s",
                        },
                    },
                )
            assert len(wires) == 2 and outcome["messages"][-1].content == "Final byte string"
            messages = [m.model_dump(mode="json") for m in outcome["messages"]]
            # JSON-action IDs and generated memory IDs can contain runtime identifiers;
            # exact provider bodies and original receipt bytes are compared separately.
            comparisons.append(
                {"catalog": catalog, "material": material, "wire": wires, "messages": messages}
            )
    assert comparisons[0]["catalog"] == comparisons[1]["catalog"]
    stable_material = [
        {k: v for k, v in r["material"].items() if k not in {"cpu_ns", "wall_ns"}}
        for r in comparisons
    ]
    assert stable_material[0] == stable_material[1]
    assert comparisons[0]["wire"] == comparisons[1]["wire"]
    assert comparisons[0]["messages"] == comparisons[1]["messages"]
    proof(
        tmp_path,
        "default-pair.json",
        {
            "mode": mode,
            "model": model_class.__name__,
            "explicit_legacy": explicit_legacy,
            "runs": comparisons,
        },
    )


@pytest.mark.parametrize("scenario", ["sources", "history", "conflict"])
@pytest.mark.parametrize("material_profile", ["compact_v1", "compact_exact_v1"])
@pytest.mark.local_artifacts
def test_qwen_exact_dictionary_same_selected_units_budget_and_delivery_limits(
    tmp_path: Path,
    scenario: str,
    material_profile: str,
) -> None:
    capacity = HostCapacity(READ["capacity_config"]())
    request_text = (
        "same-object color azul 红色"
        if scenario == "conflict"
        else "archive evidence 演示 evidencia"
    )
    with opened(tmp_path) as service:
        if scenario == "sources":
            for i in range(8):
                service.capture_user(
                    "history",
                    "old" + str(i),
                    ("archive evidence 演示 evidencia " + str(i) + " ") * 180,
                )
        elif scenario == "history":
            refs = []
            for i in range(3):
                ref = service.capture_user(
                    "s", "old" + str(i), ("archive evidence 演示 evidencia " + str(i) + " ") * 180
                )["source_ref"]
                refs.append(ref)
            DIRECT["turn"](service, text=request_text)
            for i, ref in enumerate(refs):
                created = DIRECT["save"](
                    service,
                    [ref],
                    "record" + str(i),
                    content=("archive evidence actual body " + str(i) + " ") * 80,
                )
                assert created["ok"]
                handle = service.read(created["id"])["candidate_handle"]
                changed = DIRECT["invoke"](
                    service,
                    "revise_memory",
                    {
                        "candidate_handle": handle,
                        "semantic_patch": {
                            "content": ("archive evidence revised body " + str(i) + " ") * 80
                        },
                        "source_refs": [ref],
                        "field_support": DIRECT["selected"]([ref]),
                    },
                    "revision" + str(i),
                )
                assert changed["ok"]
        else:
            for i, color in enumerate(["azul " * 90, "红色 " * 90]):
                raw = service.capture_tool(
                    "s",
                    "obs" + str(i),
                    "literal_tool",
                    json.dumps(
                        {
                            "object_id": "same-object",
                            "owner": "alice",
                            "revision": 1,
                            "color": color,
                            "count": 2,
                        }
                    ),
                    None,
                )
                assert service.observe(raw["source_ref"], projection_profile())["ok"]
            assert any(
                field["status"] == "conflict"
                for obj in service.observations()["objects"]
                for field in obj["fields"].values()
            )
        DIRECT["turn"](service, text=request_text)
        pairs = []
        recipe = GroundedMemoryRecipe(
            service, capacity.text_tokens, material_profile=material_profile
        )
        state = recipe.prepare_context(
            request_text,
            owner="alice",
            session="s",
            turn_id="u",
            material_budget=2048,
        )
        assert state["material_tokens"] == capacity.text_tokens(state["material"]) <= 2048
        assert len(state["selected"]) <= 6
        if material_profile == "compact_exact_v1":
            frame = json.loads(state["material"][state["material"].index("{") :])
            restored = decode(frame)
            assert json.dumps(restored, ensure_ascii=False, separators=(",", ":")) == json.dumps(
                state["packet"], ensure_ascii=False, separators=(",", ":")
            )
            assert restored["packet_hash"] == state["packet_hash"]
        originals = recipe._units(state["selected"], service.observations())
        if scenario == "conflict":
            fields = [u for u in originals if u["type"] == "observation_field"]
            assert fields and any(u["status"] == "conflict" for u in fields)
            assert any(u["candidate_count"] == 2 for u in fields)
        chosen, omitted = recipe._fit(
            originals,
            state["bank_revision"],
            state["packet"].get("source_index"),
            request_ref=state["packet"].get("request_ref"),
            material_budget=2048,
            selection_count=len(state["selected"]),
        )
        metadata = copy.deepcopy(state["packet"])

        # Counterfactual non-additive measurement; not a partition of wire tokens.
        def strip_bodies(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if k in {"content", "excerpt"} and isinstance(x, str):
                        v[k] = ""
                    else:
                        strip_bodies(x)
            elif isinstance(v, list):
                for x in v:
                    strip_bodies(x)

        strip_bodies(metadata)
        from milai_lab.methods.compact_exact import encode

        metadata_text = json.dumps(
            encode(metadata) if material_profile == "compact_exact_v1" else metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        wire = []

        def transport(request):
            wire.append({"body": json.loads(request.content), "hex": request.content.hex()})
            return httpx.Response(
                200,
                json={
                    "id": "r",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "Original final"},
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                },
            )

        with VLLMClient(
            VLLMConfig("http://synthetic/v1", "synthetic"),
            budget=RunBudget(
                RunLimits(generation_requests=12), tmp_path / (material_profile + ".json")
            ),
            transport=httpx.MockTransport(transport),
        ) as client:
            client.chat(
                [
                    {"role": "system", "content": "Synthetic generic Host"},
                    {"role": "user", "content": state["material"]},
                ],
                tools=[convert_to_openai_tool(t) for t in create_service_tools(service)],
            )
        delivery = [
            {
                "unit_id": u["unit_id"],
                "type": u["type"],
                "body_codepoints": len(u.get("excerpt", u.get("record", {}).get("content", ""))),
                "truncated": u.get(
                    "content_truncated", u.get("record", {}).get("content_truncated", False)
                ),
                "range": u.get("range"),
                "read_more": u.get("read_more"),
                "candidate_count": u.get("candidate_count"),
                "shown_candidates": len(u.get("candidates", [])),
            }
            for u in chosen
        ]
        pairs.append(
            {
                "profile": material_profile,
                "state": state,
                "original_selected_units": originals,
                "unencoded_delivered_units": chosen,
                "delivery": delivery,
                "fit_omitted": omitted,
                "counterfactual_metadata_only_tokens": capacity.text_tokens(metadata_text),
                "metadata_measurement_limit": (
                    "body text replaced by empty strings; "
                    "re-encoding/tokenization non-additive; no evidence body counted as read"
                ),
                "wire": wire,
                "prompt_tokens": capacity.count_messages(
                    wire[0]["body"]["messages"], wire[0]["body"].get("tools")
                ),
                "whole_json_tokens": capacity.text_tokens(
                    json.dumps(wire[0]["body"], ensure_ascii=False)
                ),
            }
        )
        proof(
            tmp_path,
            "qwen-pressure-pair.json",
            {
                "scenario": scenario,
                "pairs": pairs,
                "limit": "cost changes allocator delivery; no model/entailment/quality claim",
            },
        )


@pytest.mark.parametrize("runner", [d0, p5])
@pytest.mark.parametrize("projection", [False, True])
def test_actual_completed_business_capture_typed_feedback_and_one_observe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: Any,
    projection: bool,
) -> None:
    fp, cp, settings = READ["synthetic_settings"](tmp_path)
    settings.update(observation_capture_feedback="typed_effect_v1")
    if projection:
        settings["memory_observation_profile"] = "reservation_v1"
    write_json(cp, settings)
    fixture = read_json(fp)
    fixture["cases"][0]["messages"][0]["application_binding"]["operations"] = [
        {
            "operation_id": "actual-read",
            "tool": "get_reservation",
            "args": {"item_key": "synthetic-object"},
            "target": {
                "item_key": "synthetic-object",
                "quantity": 1,
                "destination": "synthetic",
                "packing": "synthetic",
            },
        }
    ]
    write_json(fp, fixture)
    requests, observes = [], []
    original = MemoryService.observe

    def observe(self, source, profile):
        receipt = original(self, source, profile)
        observes.append(receipt)
        return receipt

    monkeypatch.setattr(MemoryService, "observe", observe)

    def transport(request):
        body = json.loads(request.content)
        if "input" in body:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(body["input"])
                    ]
                },
            )
        number = len(requests)
        requests.append(body)
        content = (
            {"calls": [{"name": "get_reservation", "arguments": {"item_key": "synthetic-object"}}]}
            if number == 0
            else {"answer": "Original final"}
        )
        return httpx.Response(
            200,
            json={
                "id": "r" + str(number),
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(content)},
                    }
                ],
            },
        )

    def client(*args, **kwargs):
        return VLLMClient(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(runner, "VLLMClient", client)
    root = tmp_path / "run"
    frozen = runner.prepare(fp, cp, root)
    result = runner.step(root, "synthetic-entry", 0)
    assert result["status"] == "completed", result
    assert result["final_answer"] == "Original final"
    assert result["semantic_maintenance"]["generation_calls"] == 1
    assert len(requests) == 3 and len(observes) == int(projection)
    actual = [json.loads(m["content"]) for m in requests[1]["messages"] if m["role"] == "tool"]
    assert len(actual) == 1
    typed = actual[0]["completed_capture_effect"]
    assert typed["raw_status"] == "raw_captured" and typed["raw_sources_acknowledged"] == 1
    assert typed["semantic_commit"] == "not_acknowledged_by_capture"
    assert typed["confirmed_observation_count"] == (
        observes[0]["observation_count"] if projection else None
    )
    proof(
        tmp_path,
        "actual-capture-entry.json",
        {
            "freeze": frozen,
            "requests": requests,
            "actual_receipt": actual[0],
            "actual_observations": observes,
            "result": result,
        },
    )


def test_actual_p5_profile_resume_preserves_unknown_and_frozen_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fp, cp, settings = READ["synthetic_settings"](tmp_path)
    settings.update(
        tool_parameter_contract="explicit_shape_v1",
        observation_capture_feedback="typed_effect_v1",
        memory_material_profile="compact_exact_v1",
    )
    write_json(cp, settings)
    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if "input" in body:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(body["input"])
                    ]
                },
            )
        if sum("messages" in b for b in requests) == 1:
            raise RuntimeError("synthetic transport unknown")
        return httpx.Response(
            200,
            json={
                "id": "r" + str(len(requests)),
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"answer": "Original final"}),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    def client(*args, **kwargs):
        return VLLMClient(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(p5, "VLLMClient", client)
    monkeypatch.setattr(d0, "VLLMClient", client)
    root = tmp_path / "run"
    frozen = p5.prepare(fp, cp, root)
    first = p5.step(root, "synthetic-entry", 0, attempt_id="first")
    assert first["status"] == "interrupted" and "transport unknown" in first["error"]
    before = read_json(Path(settings["budget_path"]))
    resumed = p5.step(root, "synthetic-entry", 0, phase="resume", attempt_id="resume")
    assert resumed["status"] == "completed", resumed
    assert resumed["final_answer"] == "Original final"
    assert resumed["semantic_maintenance"]["generation_calls"] == 1
    assert (
        before["generation"]["unknown_usage"]
        == resumed["budget"]["generation"]["unknown_usage"]
        == 1
    )
    altered = read_json(root / "input-freeze.json")
    altered["config"]["memory_material_profile"] = "compact_v1"
    write_json(root / "input-freeze.json", altered)
    with pytest.raises(ValueError, match="FROZEN_CHANGED"):
        p5._frozen(root)
    proof(
        tmp_path,
        "actual-resume.json",
        {"freeze": frozen, "first": first, "resumed": resumed, "requests": requests},
    )


@pytest.mark.parametrize("runner", [d0, p5])
@pytest.mark.parametrize(
    "name", ["tool_parameter_contract", "observation_capture_feedback", "memory_material_profile"]
)
def test_unknown_profile_prepare_before_client_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: Any,
    name: str,
) -> None:
    fp, cp, settings = READ["synthetic_settings"](tmp_path)
    settings[name] = "unsupported"
    write_json(cp, settings)

    def denied(*args, **kwargs):
        raise AssertionError("client construction must not occur")

    monkeypatch.setattr(runner, "VLLMClient", denied)
    with pytest.raises(ValueError):
        runner.prepare(fp, cp, tmp_path / "run")


@pytest.mark.local_artifacts
def test_exact_display_selected_page_reopen_keeps_actual_members_and_paid_range(
    tmp_path: Path,
) -> None:
    capacity = HostCapacity(READ["capacity_config"]())
    with READ["opened"](tmp_path) as service:
        READ["seeded"](service)
        config = READ["turn"](service)
        recipe = GroundedMemoryRecipe(
            service, capacity.text_tokens, material_profile="compact_exact_v1"
        )
        state = READ["packet"](recipe, budget=2048)
        token = READ["cursor"](state)
        frame = json.loads(state["material"][state["material"].index("{") :])
        assert decode(frame) == state["packet"]
        page = recipe.selected_page_tool(token, config)
        assert page["retrieval_calls"] == 0 and page["current_verified"] is False
        assert page["selection_hash"] == state["selected_snapshot_hash"]
        proof(
            tmp_path,
            "exact-selected-page.json",
            {
                "state": state,
                "page": page,
                "frame": frame,
                "paid_page_tokens": capacity.text_tokens(json.dumps(page, ensure_ascii=False)),
            },
        )
    with READ["opened"](tmp_path) as service:
        config = READ["turn"](service, phase="resume")
        recipe = GroundedMemoryRecipe(
            service, capacity.text_tokens, material_profile="compact_exact_v1"
        )
        recipe._retrieve = lambda *args: (_ for _ in ()).throw(
            AssertionError("no implicit retrieval")
        )
        resumed = recipe.selected_page_tool(token, config)
        assert resumed == page


@pytest.mark.parametrize(
    "guide,feedback", [(False, False), (True, False), (False, True), (True, True)]
)
@pytest.mark.local_artifacts
def test_four_actual_profile_wire_compositions_pay_entire_catalog_feedback_request(
    tmp_path: Path,
    guide: bool,
    feedback: bool,
) -> None:
    capacity = HostCapacity(READ["capacity_config"]())
    with opened(
        tmp_path,
        guide="explicit_shape_v1" if guide else "legacy",
        feedback="typed_effect_v1" if feedback else "legacy",
    ) as service:
        raw = service.capture_tool(
            "s",
            "literal",
            "literal_tool",
            json.dumps(
                {
                    "object_id": "actual-object",
                    "owner": "alice",
                    "revision": 1,
                    "color": "actual literal",
                    "count": 2,
                }
            ),
            None,
        )
        projected = service.observe(raw["source_ref"], projection_profile())
        content = json.dumps(
            {
                "receipt": projected,
                **capture_effect(raw, projected, service.observation_capture_feedback),
            },
            ensure_ascii=False,
        )
        wires, events = [], []

        def transport(request):
            wires.append({"body": json.loads(request.content), "hex": request.content.hex()})
            return httpx.Response(
                200,
                json={
                    "id": "r",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"answer": "Original final"}),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                },
            )

        with VLLMClient(
            VLLMConfig("http://synthetic/v1", "synthetic", tool_mode="json_action"),
            budget=RunBudget(RunLimits(generation_requests=12), tmp_path / "local-budget.json"),
            capacity=capacity,
            emit=events.append,
            transport=httpx.MockTransport(transport),
        ) as client:
            model = LangMemRecipeChatModel(client=client, max_calls_per_message=12)
            model.begin_public_message("u")
            bound = model.bind_tools(create_service_tools(service))
            final = bound.invoke(
                [
                    HumanMessage("Actual public statement", id="u"),
                    ToolMessage(
                        content=content,
                        tool_call_id="completed",
                        name="literal_tool",
                        id="actual-result",
                    ),
                ]
            )
        assert final.content == "Original final"
        assert ("explicit_shape_v1" in json.dumps(wires)) == guide
        assert ("completed_capture_effect_v1" in json.dumps(wires)) == feedback
        proof(
            tmp_path,
            "profile-whole-wire.json",
            {
                "guide": guide,
                "feedback": feedback,
                "wire": wires,
                "events": events,
                "returned": final.model_dump(mode="json"),
                "full_template_prompt_tokens": capacity.count_messages(
                    wires[0]["body"]["messages"], wires[0]["body"].get("tools")
                ),
                "full_http_json_tokens": capacity.text_tokens(
                    json.dumps(wires[0]["body"], ensure_ascii=False)
                ),
                "limit": (
                    "ordinary 2048 separate from complete catalog/protocol/feedback "
                    "request costs; script not model quality"
                ),
            },
        )


@pytest.mark.parametrize("material_profile", ["full_v1", "compact_v1"])
@pytest.mark.local_artifacts
def test_nonempty_legacy_material_catalog_and_stored_cache_bytes(
    tmp_path: Path,
    material_profile: str,
) -> None:
    old_recipe = runpy.run_path(str(ROOT / "base-source/src/milai_lab/methods/grounded_memory.py"))[
        "GroundedMemoryRecipe"
    ]
    old_factory = runpy.run_path(str(ROOT / "base-source/src/milai_lab/memory/service_tools.py"))[
        "create_service_tools"
    ]
    capacity = HostCapacity(READ["capacity_config"]())
    pairs = []
    for name, recipe_type, factory in [
        ("base", old_recipe, old_factory),
        ("current", GroundedMemoryRecipe, create_service_tools),
    ]:
        path = tmp_path / name
        path.mkdir()
        with READ["opened"](path, a=False, b=False) as service:
            for i in range(2):
                service.capture_user(
                    "history", "old" + str(i), "archive multilingual evidence " + str(i)
                )
            READ["turn"](service)
            recipe = recipe_type(service, capacity.text_tokens, material_profile=material_profile)
            state = READ["packet"](recipe, budget=2048)
            assert state["material"] and state["packet"]["items"]
            cache_key = "packet:" + service_module._hash(["s", "u"])
            cache = service.store.get(recipe.namespace, cache_key).value
            pairs.append(
                {
                    "state": state,
                    "cache": cache,
                    "catalog": [convert_to_openai_tool(t) for t in factory(service)],
                }
            )
    for key in ["material", "packet", "packet_hash", "selected", "selected_inventory"]:
        assert pairs[0]["state"][key] == pairs[1]["state"][key]
    stable_cache = [
        {k: v for k, v in item["cache"].items() if k not in {"cpu_ns", "wall_ns"}} for item in pairs
    ]
    assert stable_cache[0] == stable_cache[1]
    assert pairs[0]["catalog"] == pairs[1]["catalog"]
    proof(
        tmp_path,
        "nonempty-default-material-pair.json",
        {"profile": material_profile, "pairs": pairs},
    )
