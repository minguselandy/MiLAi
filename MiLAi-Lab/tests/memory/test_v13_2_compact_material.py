"""Actual selected evidence, reversible metadata and paid wire budgets; no sockets."""

from __future__ import annotations

import hashlib
import json
import socket
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from test_v13_2_history_discovery import history, public_turn
from test_v13_2_observation import capture, item, synthetic_profile
from test_v13_2_packet import Embeddings, bound

from milai_lab.baselines.benchmark_memories import raw_chunks
from milai_lab.memory import service as service_module
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.grounded_memory import HEADER, GroundedMemoryRecipe, _hash
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.v13_1_d0 import _recipe_settings


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> Any:
    attempts: list[int] = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        attempts.append(1)
        raise AssertionError("compact engineering provider sockets forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    yield
    assert attempts == []


@pytest.fixture(autouse=True)
def synthetic_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class Clock(datetime):
        calls = 0

        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            cls.calls += 1
            return datetime(2000, 1, 1, tzinfo=UTC) + timedelta(microseconds=cls.calls)

    monkeypatch.setattr(service_module, "datetime", Clock)


@pytest.fixture(scope="module")
def capacity() -> HostCapacity:
    return HostCapacity(json.loads(Path("configs/v13-2-e0-normal.json").read_text())["capacity"])


def compact(service: MemoryService, capacity: HostCapacity, **kwargs: Any) -> GroundedMemoryRecipe:
    return GroundedMemoryRecipe(
        service, capacity.text_tokens, material_profile="compact_v1", **kwargs
    )


def expand(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Independent interpretation of the explicit compact references."""
    units = json.loads(json.dumps(packet["items"], ensure_ascii=False))
    table = packet["source_binding_table"]
    defaults = packet.get("shared_defaults", {})

    def pointer(value: Any) -> None:
        if not isinstance(value, dict):
            return
        if "record_id_index" in value:
            value["id"] = packet["record_id_table"][value.pop("record_id_index")]
        if "source_binding_index" in value:
            value["source_ref"] = table[value.pop("source_binding_index")]["source_ref"]

    for unit in units:
        record = unit.get("record", {})
        if record:
            record.update({**defaults.get("record", {}), **record})
        if "history_index" in record:
            index = record["history_index"]
            index.update({**defaults.get("history_index", {}), **index})
        for match in record.get("source_matches", []):
            match.update({**defaults.get("source_match", {}), **match})
        if "record_id_index" in record:
            record["id"] = packet["record_id_table"][record.pop("record_id_index")]
        if "scope_index" in record:
            record["scope"] = packet["scope_table"][record.pop("scope_index")]
        if unit["type"] in {"record", "historical_record"} and "unit_id" not in unit:
            unit["unit_id"] = (
                "record:" + record["id"]
                if unit["type"] == "record"
                else "history:" + record["id"] + ":" + str(record["revision"])
            )
        for target in (unit, record):
            if "source_binding_indices" not in target:
                continue
            bindings = [table[index] for index in target.pop("source_binding_indices")]
            target["source_bindings"] = bindings
            if record.pop("source_refs_from_bindings", False):
                record["source_refs"] = [binding["source_ref"] for binding in bindings]
        if unit["type"] == "source":
            binding = table[unit.pop("source_binding_index")]
            unit.update(
                source_ref=binding["source_ref"],
                role=binding["role"],
                source_hash=binding["content_sha256"],
            )
        for match in record.get("source_matches", []):
            if "source_binding_index" in match:
                binding = table[match.pop("source_binding_index")]
                match.update(
                    source_ref=binding["source_ref"], source_hash=binding["content_sha256"]
                )
            pointer(match.get("read_more"))
        for value in (
            unit.get("read_more"),
            record.get("read_more"),
            record.get("history_index", {}).get("read_more"),
            record.get("source_matches_read_more"),
        ):
            pointer(value)
    return units


def state_clear(service: MemoryService, recipe: GroundedMemoryRecipe) -> None:
    # Disposable derived state only; authoritative records and sources are not reset.
    for stored in service.store.search(recipe.namespace, limit=100):
        if stored.namespace == recipe.namespace and stored.key != "raw_index":
            service.store.delete(stored.namespace, stored.key)


def selected_units(
    service: MemoryService, recipe: GroundedMemoryRecipe, sources: list[str]
) -> list[dict[str, Any]]:
    documents = [service.source(ref) for ref in sources]
    ranked = [vars(row) for row in raw_chunks(documents)]
    return recipe._units(recipe._select(ranked, service.observations()), service.observations())


def fit(
    service: MemoryService, recipe: GroundedMemoryRecipe, units: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    index = recipe._source_index("s1", request_ref="synthetic-request")
    chosen, _ = recipe._fit(
        units, "synthetic-bank-snapshot", index, request_ref="synthetic-request", selection_count=2
    )
    coverage, _ = recipe._coverage(
        units, chosen, request_ref="synthetic-request", selection_count=2
    )
    packet, material = recipe._packet(
        chosen, "synthetic-bank-snapshot", index, request_ref="synthetic-request", coverage=coverage
    )
    print(
        json.dumps(
            {
                "fit_counts": delivery_counts(units, chosen),
                "material_tokens": recipe.token_count(material),
            }
        )
    )
    return packet, chosen, material


def delivery_counts(units: list[dict[str, Any]], chosen: list[dict[str, Any]]) -> dict[str, Any]:
    units = list({unit["unit_id"]: unit for unit in units}.values())
    chosen = list({unit["unit_id"]: unit for unit in chosen}.values())
    return {
        kind: {
            "selected": sum(unit["type"] == kind for unit in units),
            "delivered": sum(unit["type"] == kind for unit in chosen),
            "omitted": sum(unit["type"] == kind for unit in units)
            - sum(unit["type"] == kind for unit in chosen),
            "full_body": sum(
                unit["type"] == kind
                and (
                    unit.get("excerpt")
                    == next(
                        original["excerpt"]
                        for original in units
                        if original["unit_id"] == unit["unit_id"]
                    )
                    if kind == "source"
                    else not unit.get("record", {}).get("content_truncated", False)
                    if kind in {"record", "historical_record"}
                    else bool(unit.get("candidates"))
                )
                for unit in chosen
            ),
            "empty_capsule": sum(
                unit["type"] == kind
                and not (
                    unit.get("excerpt")
                    if kind == "source"
                    else unit.get("record", {}).get("content")
                    if kind in {"record", "historical_record"}
                    else unit.get("candidates")
                )
                for unit in chosen
            ),
        }
        for kind in ("record", "historical_record", "source", "observation_field")
    }


def pressure_receipt(
    root: Path,
    service: MemoryService,
    recipe: GroundedMemoryRecipe,
    units: list[dict[str, Any]],
    chosen: list[dict[str, Any]],
    packet: dict[str, Any],
    material: str,
) -> dict[str, Any]:
    records = [unit for unit in units if unit["type"] in {"record", "historical_record"}]
    costs = []
    for old_full in product(
        (False, True), repeat=sum(unit["type"] == "historical_record" for unit in records)
    ):
        values = json.loads(json.dumps(records))
        old_choices = iter(old_full)
        for value in values:
            if value["type"] == "historical_record" and next(old_choices):
                continue
            value["record"].update(content="", content_truncated=True)
        coverage = recipe._coverage(
            units, values, request_ref="synthetic-request", selection_count=2
        )[0]
        costs.append(
            recipe.token_count(
                recipe._packet(
                    values,
                    "synthetic-bank-snapshot",
                    packet["source_index"],
                    request_ref="synthetic-request",
                    coverage=coverage,
                )[1]
            )
        )
    receipt = {
        "counts": delivery_counts(units, chosen),
        "actual_tokens": recipe.token_count(material),
        "all_selected_versions_capsule_variant_costs": costs,
        "minimum_over_documented_capsule_variants": min(costs),
        "global_layout_lower_bound_claimed": False,
        "source_index": packet["source_index"],
    }
    raw = json.dumps(
        {"units": units, "chosen": chosen, "packet": packet, "receipt": receipt},
        ensure_ascii=False,
        indent=2,
    )
    (root / "pressure-receipt.json").write_text(raw)
    print(
        json.dumps(
            {
                **receipt,
                "raw_fixture_path": str(root / "pressure-receipt.json"),
                "raw_fixture_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            },
            ensure_ascii=False,
        )
    )
    return receipt


def test_actual_bindings_are_lossless_and_default_payload_is_unchanged(
    tmp_path: Path, capacity: HostCapacity
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, _ = history(service)
        public_turn(service)
        original = GroundedMemoryRecipe(service, capacity.text_tokens)
        result = original.prepare_context(
            "PINE_TOKEN", owner="alice", session="s1", turn_id="query"
        )
        units = original._units(result["selected"], service.observations())
        before = json.dumps(units, sort_keys=True)
        recipe = compact(service, capacity)
        packet, material = recipe._packet(
            units, result["bank_revision"], result["packet"]["source_index"]
        )
        assert expand(packet) == units and json.dumps(units, sort_keys=True) == before
        assert packet["source_index"] == result["packet"]["source_index"]
        assert packet["candidate_count"] == 1
        print(json.dumps({"lossless_counts": delivery_counts(units, expand(packet))}))
        assert capacity.text_tokens(material) < capacity.text_tokens(
            original._packet(units, result["bank_revision"], result["packet"]["source_index"])[1]
        )
        for binding in packet["source_binding_table"]:
            actual = service.source(binding["source_ref"])
            assert actual["role"] == binding["role"]
            assert actual["content_sha256"] == binding["content_sha256"]
        current = next(row for row in expand(packet) if row["type"] == "record")
        assert current["record"]["id"] == memory_id and current["record"]["revision"] == 2
        assert service.read(memory_id)["candidate_handle"] == current["record"]["candidate_handle"]


@pytest.mark.parametrize(
    "body", ["brief historical note", "过去的简短记录", "nota histórica breve"]
)
def test_multiple_selected_bodies_share_budget_without_scope_or_source_loss(
    tmp_path: Path, capacity: HostCapacity, body: str
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        first_sources = []
        memory_ids = []
        for index in range(2):
            key = "topic-" + str(index)
            source = bound.user(service, key, "PINE_TOKEN " + body)
            service.bind_source_boundary("s1", key, [source])
            saved = bound.save(
                service,
                body + str(index),
                "save-" + str(index),
                scope={"session_kind": "one occurrence", "excludes": ["other contexts"]},
            )
            memory_ids.append(saved["id"])
            first_sources.append(source)
            updated = bound.user(service, key + "-next", "actual continuing matter")
            service.bind_source_boundary("s1", key + "-next", [updated])
            assert service.revise(
                "s1",
                key + "-next",
                service.read(saved["id"])["candidate_handle"],
                {"content": ("large current prose " * 700) + str(index)},
            )["ok"]
        public_turn(service)
        recipe = compact(service, capacity)
        units = selected_units(service, recipe, first_sources)
        packet, chosen, material = fit(service, recipe, units)
        pressure_receipt(tmp_path, service, recipe, units, chosen, packet, material)
        assert expand(packet) == chosen
        assert capacity.text_tokens(material) <= 2048 and packet["candidate_count"] <= 6
        old = [unit for unit in expand(packet) if unit["type"] == "historical_record"]
        assert {unit["record"]["id"] for unit in old} == set(memory_ids)
        assert all(unit["record"]["content"].startswith(body) for unit in old)
        assert all(
            unit["record"]["scope"] == service.read(unit["record"]["id"], 1)["value"]["scope"]
            for unit in old
        )
        assert packet["coverage"]["truncated_unit_count"] >= 1
        assert packet["coverage"]["bank_exhaustive"] is False
        print(
            json.dumps(
                {
                    "synthetic_multilingual_body": body,
                    "compact_tokens": capacity.text_tokens(material),
                    "delivered_units": len(chosen),
                    "history_bodies": len(old),
                    "retrieval_ranking_not_measured": True,
                },
                ensure_ascii=False,
            )
        )


def test_long_history_discovery_is_bounded_and_never_adds_unselected_old_bodies(
    tmp_path: Path, capacity: HostCapacity
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, first_source = history(service, 10, keep_source=True)
        public_turn(service)
        recipe = compact(service, capacity)
        units = selected_units(service, recipe, [first_source])
        packet, chosen, material = fit(service, recipe, units)
        expanded = expand(packet)
        current = next(unit["record"] for unit in expanded if unit["type"] == "record")
        assert current["history_index"]["revision_count"] == 10
        assert current["history_index"]["omitted_count"] == 4
        assert current["source_matches"][0]["matched_revision_count"] == 10
        assert current["source_matches"][0]["omitted_matched_revision_count"] == 4
        selected_old = {
            unit["record"]["revision"] for unit in units if unit["type"] == "historical_record"
        }
        delivered_old = {
            unit["record"]["revision"] for unit in expanded if unit["type"] == "historical_record"
        }
        assert delivered_old <= selected_old == set(range(1, 7))
        assert expanded == chosen and capacity.text_tokens(material) <= 2048
        documents, _, _ = recipe._snapshot(service.event_id("s1", "query", "user"))
        current_document = next(row for row in documents if row.get("record_id") == memory_id)
        current_ranked = [vars(row) for row in raw_chunks([current_document])][:1]
        current_only = recipe._units(
            recipe._select(current_ranked, service.observations(), {memory_id: 10}),
            service.observations(),
        )
        assert not any(unit["type"] == "historical_record" for unit in current_only)


def test_oversized_scope_is_omitted_with_actual_pointer_and_source_range_is_unchanged(
    tmp_path: Path, capacity: HostCapacity
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, source = history(service, large=True)
        public_turn(service)
        recipe = compact(service, capacity)
        result = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        packet = result["packet"]
        assert packet["coverage"]["delivery_status"] == "partial"
        assert packet["coverage"]["omitted_unit_count"] >= 2
        assert any(row.get("id") == memory_id for row in result["omitted_menu"])
        for unit in expand(packet):
            if unit["type"] == "source":
                assert (
                    unit["excerpt"]
                    == json.dumps(service.source(source), ensure_ascii=False)[slice(*unit["range"])]
                )
        assert result["material_tokens"] <= 2048
        print(
            json.dumps(
                {
                    "oversized_counts": delivery_counts(
                        recipe._units(result["selected"], service.observations()), expand(packet)
                    ),
                    "ordinary_tokens": result["material_tokens"],
                }
            )
        )
        cursor = packet["coverage"]["read_more"]["cursor"]
        page = recipe.selected_page_tool(cursor, public_turn_config())
        assert page["retrieval_calls"] == 0 and page["query_kind"] == "explicit_selected_page"
        assert (
            capacity.text_tokens(
                json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            <= 2048
        )


def public_turn_config(owner: str = "alice") -> dict[str, Any]:
    return {"configurable": {"user_id": owner, "v13_session": "s1", "v13_turn_id": "query"}}


def test_same_query_equal_rank_cache_reopen_and_dirty_read_cas_are_preserved(
    tmp_path: Path, capacity: HostCapacity
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, _ = history(service)
        bound.user(service, "equal-a", "PINE_TOKEN equal words")
        bound.user(service, "equal-b", "PINE_TOKEN equal words")
        public_turn(service)
        original = GroundedMemoryRecipe(service, capacity.text_tokens, embeddings=Embeddings())
        baseline = original.prepare_context(
            "PINE_TOKEN", owner="alice", session="s1", turn_id="query"
        )
        documents = original._snapshot(service.event_id("s1", "query", "user"))[0]
        state_clear(service, original)
        embeddings = Embeddings()
        recipe = compact(service, capacity, embeddings=embeddings)
        candidate = recipe.prepare_context(
            "PINE_TOKEN", owner="alice", session="s1", turn_id="query"
        )
        assert candidate["selected"] == baseline["selected"]
        assert recipe._snapshot(service.event_id("s1", "query", "user"))[0] == documents
        stale = service.read(memory_id)["candidate_handle"]
        source = bound.user(service, "third", "actual continuing revision")
        service.bind_source_boundary("s1", "third", [source])
        assert service.revise("s1", "third", stale, {"content": "third actual value"})["ok"]
        public_turn(service)
        dirty = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        assert dirty["selected"] == candidate["selected"] and dirty["retrieval_calls"] == 0
        assert len(embeddings.queries) == 1
        assert not service.revise("s1", "stale", stale, {"content": "bad"})["ok"]
        with pytest.raises(ValueError, match="OWNER"):
            recipe.prepare_context("PINE_TOKEN", owner="bob", session="s1", turn_id="query")
        with pytest.raises(ValueError, match="ACTUAL_PUBLIC"):
            recipe.prepare_context("unseen future", owner="alice", session="s1", turn_id="query")
        saved_material = dirty["material"]
    with bound.opened(tmp_path) as reopened:
        reopened.source_backlinks = "enabled"
        public_turn(reopened)
        recipe = compact(reopened, capacity, embeddings=Embeddings())
        result = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        assert result["material"] == saved_material and result["retrieval_calls"] == 0
        bob = MemoryService(
            reopened.store,
            ("bound", "bob"),
            "bob",
            tmp_path / "bob.lock",
            mutation_contract="event_bound_v1",
        )
        assert not bob.read(memory_id)["ok"]


def test_actual_decoder_wire_counts_compact_table_and_recall_references(
    tmp_path: Path, capacity: HostCapacity
) -> None:
    requests = []
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        history(service)
        config = public_turn(service)
        recipe = compact(service, capacity)
        tools = {
            tool.name: tool
            for tool in create_service_tools(
                service,
                recall_provider=recipe.recall_tool,
                selected_page_provider=recipe.selected_page_tool,
            )
        }
        call = {"type": "tool_call", "name": "recall_context", "id": "ordinary", "args": {}}
        receipt = tools["recall_context"].invoke(call, config=config)
        messages = [
            HumanMessage("PINE_TOKEN", id="query"),
            AIMessage(content="", tool_calls=[call]),
            receipt,
        ]
        projected = recipe.hook("base")({"messages": messages}, config)["llm_input_messages"]
        material = projected[0].content.split(HEADER)[1]
        reference = projected[-1].content
        assert capacity.text_tokens(HEADER + material) + capacity.text_tokens(reference) <= 2048
        assert "source_binding_table" in material and "presented_packet_hash" in reference

        def respond(request: httpx.Request) -> httpx.Response:
            wire = json.loads(request.read())
            requests.append(wire)
            packet = json.loads(wire["messages"][0]["content"].split(HEADER)[1])
            old = [row for row in expand(packet) if row["type"] == "historical_record"]
            assert old and old[0]["record"]["content"] == "first actual PINE_TOKEN value"
            assert (
                _hash({key: value for key, value in packet.items() if key != "packet_hash"})
                == packet["packet_hash"]
            )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"answer": "fixture only"}),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                },
            )

        with VLLMClient(
            VLLMConfig("http://mock/v1", "same-model", max_tokens=64),
            capacity=capacity,
            transport=httpx.MockTransport(respond),
        ) as client:
            LangMemRecipeChatModel(client=client).bind_tools(list(tools.values())).invoke(projected)
        assert len(requests) == 1


def test_opt_in_configuration_and_incompatible_same_turn_profile_fail_closed(
    tmp_path: Path,
) -> None:
    with bound.opened(tmp_path, contract="legacy") as service:
        with pytest.raises(ValueError, match="EVENT_BOUND"):
            GroundedMemoryRecipe(service, len, material_profile="compact_v1")
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        _recipe_settings({"memory_material_profile": "unknown"})
    with pytest.raises(ValueError, match="BOUND_READER"):
        _recipe_settings({"memory_material_profile": "compact_v1"})
    settings = json.loads(Path("configs/v13-2-e0-normal.json").read_text())
    assert "material_profile" not in _recipe_settings(settings)
    assert (
        _recipe_settings({**settings, "memory_material_profile": "compact_v1"})["material_profile"]
        == "compact_v1"
    )
    with bound.opened(tmp_path) as service:
        public_turn(service)
        full = GroundedMemoryRecipe(service, lambda text: len(text) // 4)
        full.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        with pytest.raises(ValueError, match="TURN_CHANGED"):
            GroundedMemoryRecipe(
                service, lambda text: len(text) // 4, material_profile="compact_v1"
            ).prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")


def test_conflict_group_is_delivered_whole_or_omitted_with_actual_handle(
    tmp_path: Path,
    capacity: HostCapacity,
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        refs = []
        for index in range(3):
            source = capture(
                service,
                "conflict-" + str(index),
                {"objects": [item("A", 2, label="PINE_TOKEN " + str(index) + " x" * 900)]},
            )
            assert service.observe(source, synthetic_profile())["ok"]
            refs.append(source)
        public_turn(service)
        recipe = compact(service, capacity)
        units = selected_units(service, recipe, refs)
        packet, chosen, material = fit(service, recipe, units)
        fields = [unit for unit in expand(packet) if unit["type"] == "observation_field"]
        assert fields and capacity.text_tokens(material) <= 2048
        for field in fields:
            actual = next(unit for unit in units if unit["unit_id"] == field["unit_id"])
            assert field["status"] == "conflict" and field["candidate_count"] == 3
            assert field["candidates"] == [] or field["candidates"] == actual["candidates"]
            if not field["candidates"]:
                assert field["omitted_candidate_count"] == 3
                assert field["candidate_set_hash"] == _hash(actual["candidates"])
                assert field["read_more"]["object_id"] == actual["object_ref"]["id"]
        assert any(not field["candidates"] for field in fields)
        print(json.dumps({"conflict_delivery_counts": delivery_counts(units, chosen)}))


def test_exact_scope_types_and_similar_values_are_not_merged(
    tmp_path: Path,
    capacity: HostCapacity,
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        refs = []
        for index, scope in enumerate(({"session": True}, {"session": 1}, {"session": "1"})):
            source = bound.user(service, "scope-" + str(index), "PINE_TOKEN")
            service.bind_source_boundary("s1", "scope-" + str(index), [source])
            assert bound.save(service, "actual body", "save-" + str(index), scope=scope)["ok"]
            refs.append(source)
        public_turn(service)
        recipe = compact(service, capacity)
        units = selected_units(service, recipe, refs)
        packet, _ = recipe._packet(units, "actual-shape-check")
        assert expand(packet) == units and "scope_table" not in packet
        scopes = [unit["record"]["scope"] for unit in expand(packet) if unit["type"] == "record"]
        assert [type(scope["session"]) for scope in scopes] == [bool, int, str]


def test_decoded_actual_ids_execute_paid_reads_and_writer_receives_exact_packet(
    tmp_path: Path,
    capacity: HostCapacity,
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, first = history(service)
        config = public_turn(service)
        recipe = compact(service, capacity)
        result = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        decoded = expand(result["packet"])
        old = next(unit for unit in decoded if unit["type"] == "historical_record")
        tools = {tool.name: tool for tool in create_service_tools(service)}
        pointer = old["read_more"]
        assert pointer["tool"] == "read_memory" and pointer["id"] == memory_id
        call = {
            "name": pointer["tool"],
            "type": "tool_call",
            "id": "explicit-old-read",
            "args": {key: value for key, value in pointer.items() if key != "tool"},
        }
        receipt = json.loads(tools["read_memory"].invoke(call, config=config).content)
        assert receipt["ok"] and receipt["value"]["revision"] == 1
        assert receipt["value"]["content"] == old["record"]["content"]
        assert _hash(receipt["value"]) == old["version_sha256"]
        assert receipt["read_view"] == "exact_revision"
        binding = next(
            row for row in result["packet"]["source_binding_table"] if row["source_ref"] == first
        )
        source_read = json.loads(
            tools["read_source"]
            .invoke(
                {
                    "name": "read_source",
                    "type": "tool_call",
                    "id": "explicit-source-read",
                    "args": {"source_ref": binding["source_ref"]},
                },
                config=config,
            )
            .content
        )
        assert source_read["source_hash"] == binding["content_sha256"]
        assert source_read["role"] == binding["role"] == "user"
        wires = []

        def respond(request: httpx.Request) -> httpx.Response:
            wire = json.loads(request.read())
            actual = json.loads(wire["messages"][1]["content"])
            assert actual["candidate_packet"] == result["packet"]
            assert set(actual) == {"candidate_packet", "actual_events"}
            assert "read_memory" not in wire["messages"][0]["content"]
            assert expand(actual["candidate_packet"]) == decoded
            wires.append(wire)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"answer": "Decline changes"}),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                },
            )

        with VLLMClient(
            VLLMConfig("http://mock/v1", "same-model", max_tokens=64),
            capacity=capacity,
            transport=httpx.MockTransport(respond),
        ) as client:
            maintained = recipe.maintain(
                LangMemRecipeChatModel(client=client),
                session="s1",
                turn_id="query",
                config=config,
                source_refs=[service.event_id("s1", "query", "user")],
                instruction="Retain explicit preferences",
                repairs=0,
            )
        assert maintained["status"] == "no_change" and len(wires) == 1
        assert maintained["generation_calls"] == 1
        print(
            json.dumps(
                {
                    "explicit_paid_read_calls": 2,
                    "explicit_read_tokens": capacity.text_tokens(json.dumps(receipt))
                    + capacity.text_tokens(json.dumps(source_read)),
                    "writer_candidate_tokens": result["material_tokens"],
                    "separate_http_requests": 0,
                    "counts": delivery_counts(
                        recipe._units(result["selected"], service.observations()), decoded
                    ),
                }
            )
        )
