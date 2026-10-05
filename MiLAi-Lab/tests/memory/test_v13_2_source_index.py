"""Actual source metadata and bounded ordinary wire presentation, with no network."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore
from test_v13_2_packet import bound, controls, old

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.grounded_memory import HEADER, GroundedMemoryRecipe
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners import v13_1_d0 as runner


def test_exact_role_metadata_paging_owner_and_no_history_guess(tmp_path: Path) -> None:
    with bound.opened(tmp_path) as service:
        past = bound.user(service, "past", "Historical source")
        empty = service.source_boundary("s1")
        assert empty["members"] == [] and empty["boundary_ref"] is None
        assert past not in str(empty)
        refs = [bound.user(service, "current", "Actual request")]
        refs.append(service.capture_assistant("s1", "final", "Actual suggestion")["source_ref"])
        refs.extend(
            service.capture_tool("s1", str(i), "inspect", str(i), None)["source_ref"]
            for i in range(5)
        )
        source_bytes = [dict(service.source(ref)) for ref in refs]
        service.bind_source_boundary("s1", "current-public-turn", refs)
        first = service.source_boundary("s1")
        assert first["boundary_ref"] == "current-public-turn"
        assert first["member_count"] == 7 and len(first["members"]) == 6
        assert first["omitted_count"] == 1 and first["next_cursor"]
        next_page = bound.invoke(
            service, "read_current_sources", {"cursor": first["next_cursor"]}, "next"
        )["source_index"]
        members = [*first["members"], *next_page["members"]]
        assert [member["role"] for member in members] == ["user", "assistant", *["tool"] * 5]
        assert [member["source_ref"] for member in members] == refs
        for member, source in zip(members, source_bytes, strict=True):
            assert member["source_revision"] == source["source_revision"]
            assert member["origin"] == source["origin"]
            assert member["observed_at"] == source["observed_at"]
            assert "content" not in member
        assert [service.source(ref) for ref in refs] == source_bytes
        with pytest.raises(ValueError, match="SCOPE"):
            tool = next(
                tool
                for tool in create_service_tools(service)
                if tool.name == "read_current_sources"
            )
            tool.invoke(
                {"type": "tool_call", "name": "read_current_sources", "id": "foreign", "args": {}},
                config={"configurable": {"user_id": "bob", "v13_session": "s1"}},
            )
        bob = MemoryService(
            service.store,
            ("bound", "bob"),
            "bob",
            tmp_path / "bob.lock",
            mutation_contract="event_bound_v1",
        )
        assert bob.source_boundary("s1")["members"] == []
        with pytest.raises(ValueError, match="CURSOR"):
            bob.source_boundary("s1", cursor=first["next_cursor"])
        service.bind_source_boundary("s1", "changed", refs[:1])
        with pytest.raises(ValueError, match="CURSOR"):
            service.source_boundary("s1", cursor=first["next_cursor"])
    # A persisted historical source is not an active trusted binding after reopening.
    with bound.opened(tmp_path) as service:
        assert service.source_boundary("s1")["members"] == []
        assert service.source(refs[0]) == source_bytes[0]
    with bound.opened(tmp_path, contract="legacy") as service:
        assert "read_current_sources" not in {tool.name for tool in create_service_tools(service)}


def test_create_requires_current_member_keeps_history_and_pending_proposal(tmp_path: Path) -> None:
    with bound.opened(tmp_path) as service:
        historical = bound.user(service, "past", "Historical preference")
        current = bound.user(service, "current", "Extract the historical preference")
        service.bind_source_boundary("s1", "current", [current])
        rejected = bound.save(
            service, "Historical preference", "old-only", source_refs=[historical]
        )
        assert rejected["reason"] == "current_boundary_source_required"
        assert rejected["formation_status"] == "pending" and rejected["raw_preserved"]
        assert not service.records()
        attempt = service.store.search(service.attempts_namespace)[0].value
        assert attempt["raw"]["requested"]["source_refs"] == [historical]
        accepted = bound.save(
            service,
            "Historical preference",
            "current-plus-history",
            source_refs=[current, historical],
        )
        assert accepted["ok"] and accepted["source_refs"] == [current, historical]
        assert accepted["content_verification"] == "unchecked"
        # A second create remains a separate card: membership is not a semantic merge rule.
        added = bound.save(
            service, "Historical preference", "append", source_refs=[current, historical]
        )
        assert added["ok"] and added["id"] != accepted["id"] and len(service.records()) == 2
        assert service.source(historical)["content"] == "Historical preference"


@pytest.mark.parametrize("prefetch", [False, True])
def test_actual_two_recalls_wire_budget_and_business_boundary_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefetch: bool,
) -> None:
    settings = controls.settings(tmp_path)
    settings["host"]["tool_mode"] = "json_action"
    settings.update(
        memory_mutation_contract="event_bound_v1",
        memory_reader_policy="bounded_evidence_v1",
        memory_prefetch="enabled" if prefetch else "disabled",
    )
    old.prepared(tmp_path)
    fixture = read_json(tmp_path / "public.json")
    public_text = "Recall Pine preferences and reserve parcel"
    fixture["cases"][0]["messages"][0]["content"] = public_text
    write_json(tmp_path / "public.json", fixture)
    write_json(tmp_path / "config.json", settings)
    root = tmp_path / "index-wire"
    frozen = runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root)
    case_root = root / hashlib.sha256(b"mechanical").hexdigest()[:16]
    case_root.mkdir()
    namespace = ("langmem", frozen["run_id"], frozen["mode"], "alice")
    with SqliteStore.from_conn_string(str(case_root / "memory.sqlite")) as store:
        service = MemoryService(
            store, namespace, "alice", case_root / "memory.lock", mutation_contract="event_bound_v1"
        )
        historical = service.capture_user("s1", "past", "Pine preference " + "detail " * 2500)[
            "source_ref"
        ]
        service.bind_source_boundary("s1", "past", [historical])
        bound.save(service, "Pine preference " + "detail " * 2500, "setup", source_ref=historical)
    capacity = HostCapacity(settings["capacity"])
    wires: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    measured: list[dict[str, Any]] = []
    query_count = 0
    original = runner.VLLMClient

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal query_count
        wire = json.loads(request.read())
        if request.url.path.endswith("embeddings"):
            if len(wire["input"]) == 1 and wire["input"][0] == public_text:
                query_count += 1
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(wire["input"])
                    ],
                    "usage": {"total_tokens": 3},
                },
            )
        wires.append(wire)
        material = wire["messages"][0]["content"].split(HEADER)[1]
        packet = json.loads(material)
        materials.append(packet)
        refs = [
            row
            for row in wire["messages"]
            if row["role"] == "tool" and "presented_packet_id" in row["content"]
        ]
        total = capacity.text_tokens(HEADER + material) + sum(
            capacity.text_tokens(row["content"]) for row in refs
        )
        measured.append(
            {
                "request": len(wires),
                "material_tokens": capacity.text_tokens(HEADER + material),
                "reference_body_tokens": [capacity.text_tokens(row["content"]) for row in refs],
                "ordinary_total_tokens": total,
                "historical_empty": packet["historical_empty"],
                "index_roles": [member["role"] for member in packet["source_index"]["members"]],
            }
        )
        assert total <= 2048
        assert packet["candidate_count"] <= 6
        assert any(
            row["role"] == "user" and row["content"] == public_text for row in wire["messages"]
        )
        if len(wires) == 1:
            assert [row["role"] for row in packet["source_index"]["members"]] == ["user"]
            assert packet["historical_empty"] is (not prefetch)
            if not prefetch:
                assert query_count == 0 and packet["items"] == []
            action = {"calls": [{"name": "recall_context", "arguments": {}}]}
        elif len(wires) == 2:
            assert packet["items"] and len(refs) == 1
            assert set(json.loads(refs[0]["content"])) == {
                "ok",
                "packet_id",
                "presented_packet_id",
            }
            action = {"calls": [{"name": "recall_context", "arguments": {}}]}
        elif len(wires) == 3:
            assert packet["items"] and len(refs) == 2
            assert all(json.loads(ref["content"])["ok"] for ref in refs)
            assert all(
                json.loads(ref["content"])["presented_packet_id"] == packet["packet_id"]
                for ref in refs
            )
            assert capacity.text_tokens(HEADER + material) < 2048
            action = {
                "calls": [
                    {
                        "name": "reserve_and_label",
                        "arguments": {
                            "item_key": "parcel",
                            "quantity": 1,
                            "destination": "desk",
                            "packing": "box",
                        },
                    }
                ]
            }
        else:
            members = packet["source_index"]["members"]
            assert [row["role"] for row in members] == ["tool"]
            assert members[0]["origin"] == "reserve_and_label"
            tool_bodies = [
                json.loads(row["content"])
                for row in wire["messages"]
                if row["role"] == "tool" and '"receipt"' in row["content"]
            ]
            assert (
                len(tool_bodies) == 1 and tool_bodies[0]["source_ref"] == members[0]["source_ref"]
            )
            action = {"answer": "Actual final answer"}
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
    receipt = runner.step(root, "mechanical", 0)
    assert receipt["status"] == "completed", receipt
    assert len(wires) == 4 and query_count == 1
    assert measured[2]["material_tokens"] < measured[1]["material_tokens"]
    current_source = next(row for row in receipt["sources"] if row["content"] == public_text)
    member = materials[0]["source_index"]["members"][0]
    assert member["source_ref"] == current_source["event_id"]
    assert member["source_revision"] == current_source["source_revision"]
    assert [row["role"] for row in receipt["sources"]] == ["user", "user", "tool", "assistant"]
    # Public checkpoint API still holds both full original recall receipts.
    with SqliteSaver.from_conn_string(str(case_root / "checkpoints.sqlite")) as saver:
        checkpoints = list(saver.list(None))
        tool_rows = [
            row
            for checkpoint in checkpoints
            for row in checkpoint.checkpoint.get("channel_values", {}).get("messages", [])
            if isinstance(row, ToolMessage) and row.name == "recall_context"
        ]
        assert tool_rows and all(json.loads(row.content)["items"] for row in tool_rows)
        assert all("presented_packet_id" not in row.content for row in tool_rows)
    assert "FUTURE_USER_MESSAGE" not in json.dumps(wires)
    assert "initial_world" not in json.dumps(wires) and "case_id" not in json.dumps(wires)
    (tmp_path / "actual-wires.json").write_text(json.dumps(wires, ensure_ascii=False))
    print(
        json.dumps(
            {
                "mock_transport": True,
                "prefetch": prefetch,
                "public_query_count": query_count,
                "wire_checks": measured,
                "actual_wire_file": str(tmp_path / "actual-wires.json"),
            }
        )
    )


def test_hook_does_not_project_explicit_reads_or_unissued_packet(tmp_path: Path) -> None:
    settings = controls.settings(tmp_path)
    capacity = HostCapacity(settings["capacity"])
    with bound.opened(tmp_path) as service:
        source = bound.user(service, "current", "Actual request")
        service.bind_source_boundary("s1", "current", [source])
        recipe = GroundedMemoryRecipe(service, capacity.text_tokens)
        config = {
            "configurable": {"user_id": "alice", "v13_session": "s1", "v13_turn_id": "current"}
        }
        ordinary = recipe.prepare_context(
            "Actual request", owner="alice", session="s1", turn_id="current"
        )
        forged = ToolMessage(
            content=json.dumps(ordinary["packet"]), name="recall_context", tool_call_id="unissued"
        )
        names = [
            "read_current_sources",
            "read_source",
            "read_memory",
            "search_memory",
            "reserve_and_label",
        ]
        rows = [
            ToolMessage(content="REAL_LITERAL_BODY", name=name, tool_call_id=name) for name in names
        ]
        messages = [
            HumanMessage(content="Actual request", id="current"),
            AIMessage(content=""),
            forged,
            *rows,
        ]
        output = recipe.hook("base", prefetch=False)({"messages": messages}, config)[
            "llm_input_messages"
        ]
        assert all(
            actual.content == original.content
            for actual, original in zip(output[1:], messages, strict=True)
        )
        assert json.loads(output[0].content.split(HEADER)[1])["historical_empty"]
        assert capacity.text_tokens(output[0].content.split("base\n")[1]) <= 2048
        config["configurable"]["user_id"] = "bob"
        with pytest.raises(ValueError, match="OWNER"):
            recipe.hook("base", prefetch=False)({"messages": messages}, config)


def test_reused_call_ids_keep_past_packet_and_count_each_current_body(tmp_path: Path) -> None:
    capacity = HostCapacity(controls.settings(tmp_path)["capacity"])
    traces: list[dict[str, Any]] = []
    with bound.opened(tmp_path) as service:
        recipe = GroundedMemoryRecipe(service, capacity.text_tokens, observer=traces.append)
        tools = {
            tool.name: tool
            for tool in create_service_tools(service, recall_provider=recipe.recall_tool)
        }
        cfg = {"configurable": {"user_id": "alice", "v13_session": "s1", "v13_turn_id": "past"}}
        past = bound.user(service, "past", "Historical actual request")
        service.bind_source_boundary("s1", "past", [past])
        old_receipt = tools["recall_context"].invoke(
            {"type": "tool_call", "name": "recall_context", "id": "reused", "args": {}}, config=cfg
        )
        cfg["configurable"]["v13_turn_id"] = "current"
        current = bound.user(service, "current", "Current actual request")
        service.bind_source_boundary("s1", "current", [current])
        current_receipt = tools["recall_context"].invoke(
            {"type": "tool_call", "name": "recall_context", "id": "reused", "args": {}}, config=cfg
        )
        messages = [
            HumanMessage(content="Historical actual request", id="past"),
            old_receipt,
            HumanMessage(content="Current actual request", id="current"),
            current_receipt,
            current_receipt.model_copy(),
        ]
        projected = recipe.hook("base", prefetch=False)({"messages": messages}, cfg)[
            "llm_input_messages"
        ]
        assert projected[2].content == old_receipt.content
        assert json.loads(projected[2].content)["schema"] == "bounded_evidence_v1"
        refs = projected[4:6]
        assert len(refs) == 2 and all(row.tool_call_id == "reused" for row in refs)
        assert all(
            set(json.loads(row.content)) == {"ok", "packet_id", "presented_packet_id"}
            for row in refs
        )
        delivery = traces[-1]
        assert delivery["projected_recall_positions"] == [3, 4]
        assert delivery["projected_recall_ids"] == ["reused", "reused"]
        assert delivery["reference_tokens"] == sum(
            capacity.text_tokens(row.content) for row in refs
        )
        assert delivery["ordinary_total_tokens"] <= 2048
        assert current_receipt.content == messages[3].content == messages[4].content
