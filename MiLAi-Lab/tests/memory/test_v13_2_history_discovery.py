"""Bounded actual history discovery; public SQLite/decoder, no model network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from test_v13_2_packet import Embeddings, bound, controls

from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.grounded_memory import HEADER, GroundedMemoryRecipe
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


def history(
    service: MemoryService, count: int = 2, *, keep_source: bool = False, large: bool = False
) -> tuple[str, str]:
    source = bound.user(service, "r1", "PINE_TOKEN first actual request")
    service.bind_source_boundary("s1", "r1", [source])
    first = bound.save(
        service,
        "first actual PINE_TOKEN value",
        "save",
        scope={"metadata": "large " * 4000} if large else {},
    )
    assert first["ok"], first
    for revision in range(2, count + 1):
        current = bound.user(service, "r" + str(revision), "replacement " + str(revision))
        service.bind_source_boundary("s1", "r" + str(revision), [current])
        row = service.read(first["id"])
        receipt = service.revise(
            "s1",
            "change" + str(revision),
            row["candidate_handle"],
            {"content": "replacement value " + str(revision)},
            [current, source] if keep_source else [current],
        )
        assert receipt["ok"], receipt
    return first["id"], source


def public_turn(service: MemoryService) -> dict[str, Any]:
    source = bound.user(service, "query", "PINE_TOKEN")
    service.bind_source_boundary("s1", "query", [source])
    return {"configurable": {"user_id": "alice", "v13_session": "s1", "v13_turn_id": "query"}}


def test_history_pages_public_tool_actual_revisions_owner_cursor_and_stale_cas(
    tmp_path: Path,
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, source = history(service, 8, keep_source=True)
        first = bound.invoke(service, "read_memory", {"id": memory_id, "view": "history"}, "menu")
        assert first["revision_count"] == 8 and first["revisions"] == list(range(1, 7))
        assert first["omitted_count"] == 2 and first["next_cursor"]
        second = bound.invoke(
            service,
            "read_memory",
            {"id": memory_id, "view": "history", "cursor": first["next_cursor"]},
            "more",
        )
        assert second["revisions"] == [7, 8] and second["next_cursor"] is None
        old = bound.invoke(service, "read_memory", {"id": memory_id, "revision": 1}, "exact")
        assert old["value"]["content"] == "first actual PINE_TOKEN value"
        assert old["read_view"] == "exact_revision"
        rejected = service.revise("s1", "stale", old["candidate_handle"], {"content": "guess"})
        assert not rejected["ok"] and rejected["reason"] == "revision_conflict"
        assert service.read(memory_id)["value"]["revision"] == 8
        matches = service.backlink_candidates([source])[0]["source_matches"][0]
        assert matches["matched_revisions"] == list(range(1, 7))
        assert matches["matched_revision_count"] == 8
        assert matches["omitted_matched_revision_count"] == 2
        assert len(matches["matched_revision_set_hash"]) == 64
        all_matches = service.backlink_candidates([row["event_id"] for row in service.sources()])[0]
        assert len(all_matches["source_matches"]) == 6
        assert all_matches["source_match_count"] == 8
        assert all_matches["omitted_source_match_count"] == 2
        assert len(all_matches["source_match_set_hash"]) == 64
        filtered = bound.invoke(
            service,
            "read_memory",
            {key: value for key, value in matches["read_more"].items() if key != "tool"},
            "filtered",
        )
        assert filtered["index_kind"] == "source_citations" and filtered["revision_count"] == 8
        assert service.history_index("missing")["status"] == "not_found"
        with pytest.raises(ValueError, match="LIMIT"):
            service.history_index(memory_id, limit=7)
        bob = MemoryService(
            service.store,
            ("bound", "bob"),
            "bob",
            tmp_path / "bob.lock",
            mutation_contract="event_bound_v1",
        )
        assert bob.history_index(memory_id)["status"] == "not_found"
        current = bound.user(service, "r9", "new observation")
        service.bind_source_boundary("s1", "r9", [current])
        assert service.revise(
            "s1", "r9", service.read(memory_id)["candidate_handle"], {"content": "ninth"}
        )["ok"]
        with pytest.raises(ValueError, match="CURSOR"):
            service.history_index(memory_id, cursor=first["next_cursor"])
        service.store.put(service.namespace, "legacy", {"content": "old unknown"}, index=False)
        unknown = service.history_index("legacy")
        assert unknown["status"] == "history_unavailable" and unknown["revision_count"] is None
        persisted_index = service.history_index(memory_id)
    with bound.opened(tmp_path) as reopened:
        assert reopened.history_index(memory_id) == persisted_index
        assert reopened.read(memory_id, 1)["value"]["source_ref"] == source


def test_selected_source_delivers_actual_old_revision_and_separates_current_citation(
    tmp_path: Path,
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, source = history(service)
        public_turn(service)
        recipe = GroundedMemoryRecipe(service, lambda text: len(text) // 4)
        result = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        units = recipe._units(result["selected"], service.observations())
        current = next(row["record"] for row in units if row["type"] == "record")
        old = next(row for row in units if row["type"] == "historical_record")
        assert current["id"] == old["record"]["id"] == memory_id
        assert current["revision"] == 2 and old["record"]["revision"] == 1
        assert current["history_index"]["revisions"] == [1, 2]
        assert current["matched_revisions"] == [1]
        assert current["source_matches"][0]["source_ref"] == source
        assert current["source_matches"][0]["current_version_cites_source"] is False
        assert old["record"]["content"] == "first actual PINE_TOKEN value"
        assert old["source_bindings"] == service.read(memory_id, 1)["value"]["source_bindings"]
        assert result["material_tokens"] <= 2048 and result["packet"]["candidate_count"] <= 6
        assert result["packet"]["coverage"]["bank_exhaustive"] is False
        # The retrieval document remains the original current DTO, with no history metadata.
        documents, _, _ = recipe._snapshot(service.event_id("s1", "query", "user"))
        document = next(row for row in documents if row.get("record_id") == memory_id)
        assert (
            "history_index" not in document["content"]
            and "source_matches" not in document["content"]
        )


def test_budget_omissions_are_visible_explicit_page_is_full_and_does_not_retrieve(
    tmp_path: Path,
) -> None:
    capacity = HostCapacity(controls.settings(tmp_path)["capacity"])
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, _ = history(service, large=True)
        config = public_turn(service)
        embeddings = Embeddings()
        recipe = GroundedMemoryRecipe(service, capacity.text_tokens, embeddings=embeddings)
        tools = {
            tool.name: tool
            for tool in create_service_tools(
                service,
                recall_provider=recipe.recall_tool,
                selected_page_provider=recipe.selected_page_tool,
            )
        }
        ordinary = tools["recall_context"].invoke(
            {"type": "tool_call", "name": "recall_context", "id": "ordinary", "args": {}},
            config=config,
        )
        packet = json.loads(ordinary.content)
        coverage = packet["coverage"]
        assert coverage["omitted_unit_count"] >= 2
        assert coverage["delivery_status"] == "partial" and coverage["read_more"]["cursor"]
        page = tools["recall_context"].invoke(
            {
                "type": "tool_call",
                "name": "recall_context",
                "id": "page",
                "args": {"cursor": coverage["read_more"]["cursor"]},
            },
            config=config,
        )
        body = json.loads(page.content)
        assert body["query_kind"] == "explicit_selected_page" and body["retrieval_calls"] == 0
        assert body["total_unit_count"] == coverage["omitted_unit_count"]
        assert capacity.text_tokens(page.content) <= 2048 and len(embeddings.queries) == 1
        records = [row for row in body["items"] if row.get("id") == memory_id]
        assert records and all(row["revision"] in {1, 2} for row in records)
        assert all(
            row["view_at_snapshot"] in {"historical", "current_at_snapshot"} for row in records
        )
        messages = [
            HumanMessage("PINE_TOKEN", id="query"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "recall_context", "args": {}, "id": "ordinary", "type": "tool_call"}
                ],
            ),
            ordinary,
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "recall_context",
                        "args": {"cursor": coverage["read_more"]["cursor"]},
                        "id": "page",
                        "type": "tool_call",
                    }
                ],
            ),
            page,
        ]
        projected = recipe.hook("base", prefetch=False)({"messages": messages}, config)[
            "llm_input_messages"
        ]
        actual_page = next(row for row in projected if getattr(row, "tool_call_id", None) == "page")
        assert actual_page.content == page.content
        ordinary_refs = [
            row for row in projected if getattr(row, "tool_call_id", None) == "ordinary"
        ]
        assert len(ordinary_refs) == 1 and "presented_packet_hash" in ordinary_refs[0].content
        system_material = projected[0].content.split(HEADER)[1]
        assert (
            capacity.text_tokens(HEADER + system_material)
            + capacity.text_tokens(ordinary_refs[0].content)
            <= 2048
        )
        assert len(embeddings.queries) == 1
        with pytest.raises(ValueError, match="OWNER"):
            recipe.selected_page_tool(
                coverage["read_more"]["cursor"],
                {"configurable": {**config["configurable"], "user_id": "bob"}},
            )


def test_cached_selected_missing_is_not_no_matches_and_does_not_reretrieve(tmp_path: Path) -> None:
    with bound.opened(tmp_path) as service:
        source = bound.user(service, "past", "PINE_TOKEN")
        public_turn(service)
        embeddings = Embeddings()
        recipe = GroundedMemoryRecipe(
            service, lambda text: len(text) // 4, representation="raw", embeddings=embeddings
        )
        first = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        assert first["packet"]["coverage"]["selection_status"] == "selected"
        service.store.delete(service.sources_namespace, source)
        second = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        assert second["packet"]["coverage"]["selection_status"] == "selected_unavailable"
        assert second["packet"]["coverage"]["unavailable_unit_count"] == 1
        assert second["retrieval_calls"] == 0 and len(embeddings.queries) == 1
        assert second["selected"] == first["selected"]
        empty = bound.user(service, "empty", "zzqnotpresent")
        service.bind_source_boundary("s1", "empty", [empty])
        result = recipe.prepare_context(
            "zzqnotpresent", owner="alice", session="s1", turn_id="empty"
        )
        assert result["packet"]["coverage"]["selection_status"] == "no_matches"


def test_actual_decoder_prompt_history_schema_and_old_body_in_same_packet(tmp_path: Path) -> None:
    capacity = HostCapacity(controls.settings(tmp_path)["capacity"])
    wires = []
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, _ = history(service)
        config = public_turn(service)
        recipe = GroundedMemoryRecipe(service, capacity.text_tokens)
        tools = create_service_tools(
            service,
            recall_provider=recipe.recall_tool,
            selected_page_provider=recipe.selected_page_tool,
        )
        schema = convert_to_openai_tool(next(tool for tool in tools if tool.name == "read_memory"))
        assert schema["function"]["parameters"]["properties"]["view"]["enum"] == [
            "version",
            "history",
        ]

        def respond(request: httpx.Request) -> httpx.Response:
            wire = json.loads(request.read())
            wires.append(wire)
            system = wire["messages"][0]["content"]
            assert "history" in system and "source_ref" in system
            material = system.split(HEADER)[1]
            packet = json.loads(material)
            assert packet["coverage"]["selected_unit_count"] >= 3
            old = [row for row in packet["items"] if row["type"] == "historical_record"]
            assert old and old[0]["record"]["content"] == "first actual PINE_TOKEN value"
            assert capacity.text_tokens(HEADER + material) <= 2048
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(
                                    {
                                        "calls": [
                                            {
                                                "name": "read_memory",
                                                "arguments": {"id": memory_id, "view": "history"},
                                            }
                                        ]
                                    }
                                ),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                },
            )

        client = VLLMClient(
            VLLMConfig("http://mock/v1", "same-model", max_tokens=64),
            transport=httpx.MockTransport(respond),
            capacity=capacity,
        )
        model = LangMemRecipeChatModel(client=client).bind_tools(tools)
        messages = recipe.hook("base")(
            {"messages": [HumanMessage("PINE_TOKEN", id="query")]}, config
        )["llm_input_messages"]
        response = model.invoke(messages)
        call = response.tool_calls[0]
        assert call["name"] == "read_memory" and call["args"]["view"] == "history"
        result = next(tool for tool in tools if tool.name == "read_memory").invoke(
            call, config=config
        )
        assert json.loads(result.content)["revisions"] == [1, 2] and len(wires) == 1
        client.close()


def test_single_write_only_boundary_receives_only_the_paid_selected_packet(tmp_path: Path) -> None:
    capacity = HostCapacity(controls.settings(tmp_path)["capacity"])
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        history(service)
        public_turn(service)
        recipe = GroundedMemoryRecipe(service, capacity.text_tokens)
        packet = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            wire = json.loads(request.read())
            requests.append(wire)
            actual = json.loads(wire["messages"][1]["content"])
            assert actual["candidate_packet"] == packet["packet"]
            assert set(actual) == {"candidate_packet", "actual_events"}
            old = [
                row
                for row in actual["candidate_packet"]["items"]
                if row["type"] == "historical_record"
            ]
            assert old and old[0]["record"]["content"] == "first actual PINE_TOKEN value"
            assert "read_memory" not in wire["messages"][0]["content"]
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

        client = VLLMClient(
            VLLMConfig("http://mock/v1", "same-model", max_tokens=64),
            capacity=capacity,
            transport=httpx.MockTransport(respond),
        )
        result = recipe.maintain(
            LangMemRecipeChatModel(client=client),
            session="s1",
            turn_id="query",
            config={
                "configurable": {"user_id": "alice", "v13_session": "s1", "v13_turn_id": "query"}
            },
            source_refs=[service.event_id("s1", "query", "user")],
            instruction="Retain explicit preferences",
            repairs=0,
        )
        assert result["status"] == "no_change" and result["generation_calls"] == 1
        assert len(requests) == 1 and packet["material_tokens"] <= 2048
        client.close()


def test_history_filtered_source_owner_and_integrity_fail_closed(tmp_path: Path) -> None:
    with bound.opened(tmp_path) as service:
        memory_id, source = history(service)
        filtered = service.history_index(memory_id, source_ref=source)
        assert filtered["revisions"] == [1] and filtered["source_ref"] == source
        assert filtered["source_hash"] == service.source(source)["content_sha256"]
        with pytest.raises(ValueError, match="SOURCE_NOT_FOUND"):
            service.history_index(memory_id, source_ref="foreign-or-invented")
        actual = service.store.get(service.sources_namespace, source).value
        service.store.put(
            service.sources_namespace, source, {**actual, "content": "changed"}, index=False
        )
        with pytest.raises(ValueError, match="INTEGRITY"):
            service.history_index(memory_id, source_ref=source)


def test_dirty_revision_metadata_keeps_match_snapshot_and_current_read_separate(
    tmp_path: Path,
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, _ = history(service)
        public_turn(service)
        recipe = GroundedMemoryRecipe(service, lambda text: len(text) // 4)
        first = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        third = bound.user(service, "third", "Another actual update request")
        service.bind_source_boundary("s1", "third", [third])
        assert service.revise(
            "s1",
            "third",
            service.read(memory_id)["candidate_handle"],
            {"content": "third replacement"},
        )["ok"]
        second = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        record = next(
            row["record"]
            for row in recipe._units(second["selected"], service.observations())
            if row["type"] == "record"
        )
        match = record["source_matches"][0]
        assert record["revision"] == match["current_revision_at_read"] == 3
        assert match["current_revision_at_match_snapshot"] == 2
        assert match["matched_revisions"] == [1] and not match["current_version_cites_source"]
        assert second["selected"] == first["selected"] and second["retrieval_calls"] == 0
        service.store.delete(service.namespace, memory_id)
        missing = recipe.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        assert missing["packet"]["coverage"]["selection_status"] == "partial_unavailable"
        assert missing["packet"]["coverage"]["unavailable_unit_count"] == 2
        assert missing["retrieval_calls"] == 0
