"""Bounded actual wire delivery and semantic-boundary mechanics; zero network."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.contracts.memory import ObservationField, ObservationProfile
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.grounded_memory import GroundedMemoryRecipe
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners import v13_1_d0 as runner


def helper(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bound = helper("packet_source_helpers", Path(__file__).with_name("test_v13_2_service.py"))
old = helper("packet_d0_helpers", Path(__file__).with_name("test_v13_1_d0.py"))
controls = helper(
    "packet_tokenizer_helpers", Path(__file__).parents[1] / "unit/test_v13_1_controls.py"
)


class Embeddings:
    def __init__(self) -> None:
        self.documents: list[list[str]] = []
        self.queries: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.append(texts)
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [0.0, 1.0]


def service(store: SqliteStore, path: Path, **options: Any) -> MemoryService:
    return MemoryService(
        store,
        ("packet", "alice"),
        "alice",
        path / "lock",
        mutation_contract="event_bound_v1",
        **options,
    )


def test_selected_late_original_json_range_and_true_empty_reuse_reopen(tmp_path: Path) -> None:
    embeddings = Embeddings()
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        memory = service(store, tmp_path)
        ref = bound.user(memory, "past", "filler " * 1100 + "LATE_TOKEN end")
        bound.user(memory, "q", "LATE_TOKEN")
        recipe = GroundedMemoryRecipe(
            memory, lambda text: len(text) // 4, embeddings=embeddings, representation="raw"
        )
        packet = recipe.prepare_context("LATE_TOKEN", owner="alice", session="s1", turn_id="q")
        leaf = next(row for row in packet["packet"]["items"] if row["source_ref"] == ref)
        assert "LATE_TOKEN" in leaf["excerpt"] and leaf["range"][0] > 0
        serialized = json.dumps(memory.source(ref), ensure_ascii=False)
        assert leaf["excerpt"] == serialized[slice(*leaf["range"])]
        assert leaf["range_basis"] == "serialized_original_event_json"
        assert leaf["source_hash"] == memory.source(ref)["content_sha256"]
        assert (
            len(embeddings.queries) == 1
            and recipe.prepare_context("LATE_TOKEN", owner="alice", session="s1", turn_id="q")[
                "retrieval_calls"
            ]
            == 0
        )
        bound.user(memory, "empty", "zqxv-unrelated")
        empty = recipe.prepare_context(
            "zqxv-unrelated", owner="alice", session="s1", turn_id="empty"
        )
        assert empty["material"] == "" and empty["packet"]["items"] == []
        with pytest.raises(ValueError, match="OWNER"):
            recipe.prepare_context("LATE_TOKEN", owner="bob", session="s1", turn_id="q")
        with pytest.raises(ValueError, match="ACTUAL_PUBLIC"):
            recipe.prepare_context("FUTURE_USER_MESSAGE", owner="alice", session="s1", turn_id="q")
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        recipe = GroundedMemoryRecipe(
            service(store, tmp_path),
            lambda text: len(text) // 4,
            embeddings=embeddings,
            representation="raw",
        )
        reopened = recipe.prepare_context("LATE_TOKEN", owner="alice", session="s1", turn_id="q")
        # An unrelated new source dirties the snapshot; frozen selections refresh without a query.
        assert reopened["retrieval_calls"] == 0 and reopened["selected"] == packet["selected"]
        assert len(embeddings.queries) == 2


def test_dirty_refresh_updates_same_record_and_never_adds_new_backlinks(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        memory = service(store, tmp_path, source_backlinks="enabled")
        source = bound.user(memory, "past", "松林偏好")
        first = bound.save(
            memory, "Pine concise preference", "one", source_ref=source, scope={"project": "Pine"}
        )
        bound.user(memory, "q", "松林")
        embeddings = Embeddings()
        recipe = GroundedMemoryRecipe(memory, lambda text: len(text) // 4, embeddings=embeddings)
        packet = recipe.prepare_context("松林", owner="alice", session="s1", turn_id="q")
        record = next(row["record"] for row in packet["packet"]["items"] if row["type"] == "record")
        assert record["id"] == first["id"] and record["revision"] == 1
        newer = bound.user(memory, "correction", "Use detail")
        memory.bind_source_boundary("s1", "correction", [newer])
        assert memory.revise(
            "s1",
            "patch",
            record["candidate_handle"],
            {"content": "Pine detailed preference"},
            [newer],
        )["ok"]
        added = bound.save(memory, "Unrelated card sharing past source", "two", source_ref=source)
        refreshed = recipe.prepare_context("松林", owner="alice", session="s1", turn_id="q")
        delivered = [
            row["record"] for row in refreshed["packet"]["items"] if row["type"] == "record"
        ]
        assert [row["id"] for row in delivered] == [first["id"]]
        assert delivered[0]["revision"] == 2 and added["id"] not in str(delivered)
        assert refreshed["retrieval_calls"] == 0 and len(embeddings.queries) == 1
        assert delivered[0]["scope"] == {"project": "Pine"}


def test_bounded_multi_field_conflicts_retain_status_and_explicit_omissions(tmp_path: Path) -> None:
    settings = controls.settings(tmp_path)
    capacity = HostCapacity(settings["capacity"])
    profile = ObservationProfile(
        "third",
        "1",
        "catalog",
        ("inspect",),
        ("id",),
        tuple(
            ObservationField("field" + str(index), ("field" + str(index),), "string")
            for index in range(8)
        ),
    )
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        memory = service(store, tmp_path)
        for event in range(4):
            body = {
                "id": "catalog",
                **{
                    "field" + str(index): "catalog " + str(event) + " x " * 900
                    for index in range(8)
                },
            }
            ref = memory.capture_tool("s1", "tool" + str(event), "inspect", json.dumps(body), None)[
                "source_ref"
            ]
            assert memory.observe(ref, profile)["ok"]
        bound.user(memory, "q", "catalog")
        recipe = GroundedMemoryRecipe(memory, capacity.text_tokens, representation="receipt")
        packet = recipe.prepare_context("catalog", owner="alice", session="s1", turn_id="q")
        assert packet["material"] and capacity.text_tokens(packet["material"]) <= 2048
        fields = [row for row in packet["packet"]["items"] if row["type"] == "observation_field"]
        assert fields and all(
            row["status"] == "conflict" and row["candidate_count"] == 4 for row in fields
        )
        clipped = next(row for row in fields if row.get("omitted_candidate_count"))
        assert clipped["omitted_candidate_count"] == 4 and clipped["candidates"] == []
        assert clipped["read_more"]["tool"] == "read_observations"
        assert not packet["packet"]["current_verified"]
        assert len({row["unit_id"] for row in fields}) == len(fields)


@pytest.mark.parametrize(
    "contract,backlinks",
    [
        ("legacy_query_v1", "disabled"),
        ("legacy_query_v1", "enabled"),
        ("read_handle_v1", "enabled"),
    ],
)
def test_ablation_interface_keeps_same_source_contract_and_separates_handles(
    tmp_path: Path, contract: str, backlinks: str
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        memory = service(store, tmp_path, candidate_contract=contract, source_backlinks=backlinks)
        ref = bound.user(memory, "past", "松林偏好")
        first = bound.save(memory, "Pine preference", "save", source_ref=ref)
        found = bound.invoke(memory, "search_memory", {"query": "松林"}, "search")
        records = found["records"]
        assert bool(records) == (backlinks == "enabled")
        if records:
            assert ("candidate_handle" in records[0]) == (contract == "read_handle_v1")
        assert memory.read(first["id"])["value"]["source_bindings"][0]["role"] == "user"
        tools = {tool.name: tool for tool in create_service_tools(memory)}
        assert ("revise_memory" in tools) == (contract == "read_handle_v1")
        props = tools["manage_memory"].args_schema.model_json_schema()["properties"]
        assert ("candidate_handle" in props) == (contract == "read_handle_v1")


@pytest.mark.parametrize("host_commit", [False, True])
def test_actual_runner_wire_once_after_final_writer_and_host_commit_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host_commit: bool
) -> None:
    settings = controls.settings(tmp_path)
    settings["host"]["tool_mode"] = "json_action"
    settings.update(
        memory_mutation_contract="event_bound_v1",
        memory_reader_policy="bounded_evidence_v1",
        memory_formation_policy="after_host_final_v1",
        memory_source_backlinks="enabled",
        writer_system_prompt="Retain expressed preference",
    )
    root = old.prepared(tmp_path)
    write_json(tmp_path / "config.json", settings)
    fixture = read_json(tmp_path / "public.json")
    fixture["cases"][0]["messages"][0]["content"] = "I prefer concise Pine replies"
    write_json(tmp_path / "public.json", fixture)
    root = tmp_path / "actual-wire"
    frozen = runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    assert frozen["memory_reader_policy"]["dense_min_cosine"] == 0.2
    wires: list[dict[str, Any]] = []
    original = runner.VLLMClient

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append(wire)
        if request.url.path.endswith("embeddings"):
            raise AssertionError("Empty historical bank must not embed the current request")
        if host_commit and len(wires) == 1:
            action = {
                "calls": [
                    {"name": "manage_memory", "arguments": {"content": "Concise Pine replies"}}
                ]
            }
        elif len(wires) == (2 if host_commit else 1):
            action = {"answer": "HOST_FINAL_LITERAL"}
        else:
            body = json.loads(wire["messages"][-1]["content"])
            assert all(row["role"] in {"user", "assistant"} for row in body["actual_events"])
            user_ref = next(
                row["event_id"] for row in body["actual_events"] if row["role"] == "user"
            )
            action = {
                "calls": [
                    {
                        "name": "manage_memory",
                        "arguments": {"content": "Concise Pine replies", "source_refs": [user_ref]},
                    },
                    {
                        "name": "manage_memory",
                        "arguments": {
                            "content": "Pine project scope",
                            "source_refs": [user_ref],
                            "scope": {"project": "Pine"},
                        },
                    },
                ]
            }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(action)},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
            },
        )

    monkeypatch.setattr(
        runner,
        "VLLMClient",
        lambda *args, **kwargs: original(*args, transport=httpx.MockTransport(respond), **kwargs),
    )
    first = runner.step(root, "mechanical", 0)
    assert first["status"] == "completed", first
    assert first["final_answer"] == "HOST_FINAL_LITERAL"
    assert len(wires) == 2  # final+single writer, or Host commit+final and zero writer
    maintenance = first["semantic_maintenance"]
    assert maintenance["generation_calls"] == (0 if host_commit else 1)
    assert maintenance["status"] == ("skipped_host_committed" if host_commit else "committed")
    assert len(first["records"]) == (1 if host_commit else 2)
    assert [row["role"] for row in first["sources"]] == ["user", "assistant"]
    assert all(row["content"] != "Retain expressed preference" for row in first["sources"])
    assert "FUTURE_USER_MESSAGE" not in json.dumps(wires)
    assert "case_id" not in json.dumps(wires) and "initial_world" not in json.dumps(wires)


def test_tool_only_policy_has_no_semantic_mutation_capability(tmp_path: Path) -> None:
    settings = controls.settings(tmp_path)
    settings.update(
        memory_mutation_contract="event_bound_v1",
        memory_reader_policy="bounded_evidence_v1",
        memory_formation_policy="tool_only_v1",
        memory_representation="receipt",
        memory_observation_profile="reservation_v1",
    )
    assert runner._recipe_settings(settings)["writer_max_generations"] == 0
    with SqliteStore.from_conn_string(":memory:") as store:
        tools = runner._memory_tools(service(store, tmp_path), settings)
        assert not {"manage_memory", "revise_memory"} & {tool.name for tool in tools}
    del settings["memory_reader_policy"]
    del settings["embedding"]
    assert runner._recipe_settings(settings)["prefetch_enabled"] is False
    catalog = runner._catalog(
        tmp_path, "field_grounded", mutation_contract="event_bound_v1", settings=settings
    )
    assert not {"manage_memory", "revise_memory"} & {row["function"]["name"] for row in catalog}


def test_actual_new_user_patch_binds_current_singleton_and_receives_fixed_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = controls.settings(tmp_path)
    settings["host"]["tool_mode"] = "json_action"
    settings.update(
        memory_mutation_contract="event_bound_v1",
        memory_reader_policy="bounded_evidence_v1",
        memory_source_backlinks="enabled",
    )
    old.prepared(tmp_path)
    fixture = read_json(tmp_path / "public.json")
    fixture["cases"][0]["messages"][0]["content"] = "Pine concise preference"
    fixture["cases"][0]["messages"][1]["content"] = "Pine now detailed preference"
    write_json(tmp_path / "public.json", fixture)
    write_json(tmp_path / "config.json", settings)
    root = tmp_path / "patch-wire"
    runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    wires: list[dict[str, Any]] = []
    packets: list[str] = []
    original = runner.VLLMClient

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [1.0, 0.0]}
                        for index, _ in enumerate(wire["input"])
                    ],
                    "usage": {"total_tokens": 3},
                },
            )
        wires.append(wire)
        if len(wires) == 1:
            action = {
                "calls": [
                    {
                        "name": "manage_memory",
                        "arguments": {
                            "content": "Pine concise preference",
                            "scope": {"project": "Pine"},
                        },
                    }
                ]
            }
        elif len(wires) == 3:
            system = wire["messages"][0]["content"]
            material = system.split(
                "[Archived evidence; observations are historical and prose is unchecked]\n"
            )[1]
            packets.append(material)
            records = [
                row["record"] for row in json.loads(material)["items"] if row["type"] == "record"
            ]
            action = {
                "calls": [
                    {
                        "name": "revise_memory",
                        "arguments": {
                            "candidate_handle": records[0]["candidate_handle"],
                            "semantic_patch": {"content": "Pine detailed preference"},
                        },
                    }
                ]
            }
        else:
            if len(wires) == 4:
                packets.append(
                    wire["messages"][0]["content"].split(
                        "[Archived evidence; observations are historical and prose is unchecked]\n"
                    )[1]
                )
            action = {"answer": "Final original answer"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(action)},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
            },
        )

    monkeypatch.setattr(
        runner,
        "VLLMClient",
        lambda *args, **kwargs: original(*args, transport=httpx.MockTransport(respond), **kwargs),
    )
    first = runner.step(root, "mechanical", 0)
    second = runner.step(root, "mechanical", 1)
    assert first["status"] == second["status"] == "completed", second
    assert len(second["records"]) == 1 and second["records"][0]["value"]["revision"] == 2
    value = second["records"][0]["value"]
    current = next(
        row
        for row in second["sources"]
        if row["role"] == "user" and row["content"] == "Pine now detailed preference"
    )
    assert value["source_ref"] == current["event_id"]
    assert value["scope"] == {"project": "Pine"}
    assert packets[0] != packets[1]  # selected card dirty refreshes its read revision
    assert all(HostCapacity(settings["capacity"]).text_tokens(packet) <= 2048 for packet in packets)
    trace_path = (
        root / next(path.name for path in root.iterdir() if path.is_dir()) / "message-1.jsonl"
    )
    traces = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert (
        sum(
            row.get("retrieval_calls", 0)
            for row in traces
            if row.get("event") == "v13_evidence_packet"
        )
        == 1
    )


def test_batch_partial_repair_cap_and_repeated_rejection_fingerprint(tmp_path: Path) -> None:
    from langchain_core.messages import AIMessage

    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        memory = service(store, tmp_path)
        ref = bound.user(memory, "q", "Two independently scoped preferences")
        recipe = GroundedMemoryRecipe(memory, lambda text: len(text) // 4)
        bad = {
            "name": "manage_memory",
            "args": {"content": "wrong role", "basis": "tool_observation", "source_refs": [ref]},
            "id": "bad",
        }
        good = {
            "name": "manage_memory",
            "args": {"content": "One preference", "source_refs": [ref]},
            "id": "good",
        }

        class Model:
            calls = 0

            def bind_tools(self, tools: Any) -> Any:
                return self

            def invoke(self, messages: Any, config: Any) -> Any:
                self.calls += 1
                return AIMessage(
                    content="",
                    tool_calls=[good, bad]
                    if self.calls == 1
                    else [bad, {**good, "args": {**good["args"], "content": "Second preference"}}],
                )

        model = Model()
        receipt = recipe.maintain(
            model,
            session="s1",
            turn_id="q",
            source_refs=[ref],
            config={"configurable": {"user_id": "alice", "v13_session": "s1"}},
            instruction="Retain explicit preferences",
            repairs=1,
        )
        assert model.calls == receipt["generation_calls"] == 2
        assert receipt["status"] == "partial" and receipt["batch_atomic"] is False
        assert receipt["committed_actions"] == 2 and len(memory.records()) == 2
        assert any(
            row["receipt"].get("reason") == "repeated_rejection" for row in receipt["receipts"]
        )
        assert recipe.maintain(
            model,
            session="s1",
            turn_id="q",
            source_refs=[ref],
            config={"configurable": {"user_id": "alice", "v13_session": "s1"}},
            instruction="Retain explicit preferences",
            repairs=1,
        )["replayed"]
        assert model.calls == 2


def test_autonomous_recall_calls_same_public_query_once_with_no_prefetch(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        memory = service(store, tmp_path)
        bound.user(memory, "past", "Past actual Pine evidence")
        bound.user(memory, "q", "Pine public full question")
        embeddings = Embeddings()
        recipe = GroundedMemoryRecipe(
            memory, lambda text: len(text) // 4, embeddings=embeddings, representation="raw"
        )
        settings = {"memory_reader_policy": "bounded_evidence_v1", "memory_prefetch": "disabled"}
        tools = {tool.name: tool for tool in runner._memory_tools(memory, settings, recipe=recipe)}
        assert embeddings.queries == []
        config = {"configurable": {"user_id": "alice", "v13_session": "s1", "v13_turn_id": "q"}}

        def recall(call_id: str) -> Any:
            return tools["recall_context"].invoke(
                {
                    "type": "tool_call",
                    "name": "recall_context",
                    "args": {},
                    "id": call_id,
                },
                config=config,
            )

        first, second = recall("first"), recall("second")
        assert first.content == second.content
        assert json.loads(first.content)["items"] and len(first.content) // 4 <= 2048
        assert embeddings.queries == ["Pine public full question"]
        for call_id in ("extra-one", "extra-two"):
            tools["search_memory"].invoke(
                {
                    "type": "tool_call",
                    "name": "search_memory",
                    "args": {"query": "An explicit additional actual query"},
                    "id": call_id,
                },
                config=config,
            )
        assert embeddings.queries == [
            "Pine public full question",
            "An explicit additional actual query",
            "An explicit additional actual query",
        ]
        assert set(tools["search_memory"].tool_call_schema.model_json_schema()["properties"]) == {
            "query"
        }
