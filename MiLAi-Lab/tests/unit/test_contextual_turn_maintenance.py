from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from milai_lab.methods.contextual_memory.models import Observation, receipt_outcome
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.contextual import memory_tools
from milai_lab.runners.contextual_agent_tasks import (
    BusinessTool,
    BusinessToolResult,
    TaskTurn,
    accept_observation,
    run_task_session,
)
from milai_lab.runners.contextual_host import ContextualHost
from milai_lab.runners.contextual_maintenance import (
    SEMANTIC_MAINTENANCE_PROTOCOL,
    committed,
    finish,
    pending_materials,
    semantic_finish,
    semantic_frontier,
)
from milai_lab.runners.contextual_session import HostSession


def bank() -> ContextualMemory:
    memory = ContextualMemory(
        "owner",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
    )
    memory.start_task("session", "Work")
    return memory


def decision(sources: list[str], records: list[str] | None = None) -> dict[str, Any]:
    return {
        "sources": sources,
        "decision": "saved" if records else "no_change",
        "record_refs": records or [],
        "reason": "Supported current record"
        if records
        else "Routine observation with no change to future work",
    }


def test_first_write_cannot_settle_later_business_result_and_revision_can() -> None:
    memory = bank()
    session = HostSession("session", memory)
    first = accept_observation(
        memory, session, Observation("plan", "Document needs review", "user", "fixture")
    )
    saved = memory.save(
        op="CREATE",
        content="Document awaiting review",
        about_ref="unresolved",
        source_refs=[first["source_ref"]],
        certainty="explicit",
    )
    committed(session, receipt_outcome("memory_save", saved), saved)
    assert session.material_view is not None
    projected = session.material_view.project_write(saved)
    session.append_material(projected)
    record_alias = projected["record"]["ref"]
    initial_alias = first["material"]["materials"][0]["ref"]
    assert pending_materials(session)[0]["committed_record_refs"] == [record_alias]
    finish(session, [decision([initial_alias], [record_alias])])
    later = accept_observation(
        memory, session, Observation("result", "Review passed", "tool", "fixture")
    )
    later_alias = later["material"]["materials"][0]["ref"]
    assert pending_materials(session)[0]["committed_record_refs"] == []
    with pytest.raises(ValueError, match="SAVED_WITHOUT_SOURCE_SUPPORT") as error:
        finish(session, [decision([later_alias], [record_alias])])
    assert later_alias in str(error.value) and record_alias in str(error.value)
    revised = memory.save(
        op="REVISE",
        target_ref=saved["record"]["ref"],
        content="Document review passed",
        about_ref="unresolved",
        source_refs=[first["source_ref"], later["source_ref"]],
        dependencies=[],
        certainty="explicit",
    )
    committed(session, receipt_outcome("memory_save", revised), revised)
    projected = session.material_view.project_write(revised)
    session.append_material(projected)
    assert pending_materials(session)[0]["committed_record_refs"] == [projected["record"]["ref"]]
    assert (
        finish(session, [decision([later_alias], [projected["record"]["ref"]])])["status"]
        == "complete"
    )
    assert len(memory.workspace.cards) == 1


@pytest.mark.parametrize("reviewed", [True, False])
def test_one_response_zero_write_or_explicit_pending_never_budget_bypass(reviewed: bool) -> None:
    memory = bank()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        action = {"answer": "Hello"}
        if reviewed:
            action["memory_review"] = [decision(["m0"])]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": json.dumps(action)}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    with VLLMClient(
        VLLMConfig("http://fixture/v1", "host", max_calls=1), transport=httpx.MockTransport(respond)
    ) as client:
        host = ContextualHost(
            client,
            memory.dispatch,
            memory_tools("ordinary"),
            "Work",
            memory=memory,
            maintenance_policy="required",
        )
        session, results = run_task_session(
            [TaskTurn("greet", "Hello")], memory=memory, host=host, session_id="session"
        )
    assert len(requests) == 1 and not memory.workspace.cards
    assert results[0].status == ("complete" if reviewed else "maintenance_pending")
    assert session.closed is reviewed


def test_native_finish_cannot_claim_to_review_simultaneous_business_result() -> None:
    memory = bank()
    executions = []
    schema = {
        "type": "function",
        "function": {
            "name": "work",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }

    def execute(arguments: dict[str, Any], call_id: str) -> BusinessToolResult:
        executions.append(call_id)
        return BusinessToolResult(call_id, "succeeded", {})

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "a",
                                    "type": "function",
                                    "function": {"name": "work", "arguments": "{}"},
                                },
                                {
                                    "id": "b",
                                    "type": "function",
                                    "function": {
                                        "name": "finish_turn",
                                        "arguments": json.dumps(
                                            {"answer": "Done", "memory_review": [decision(["m1"])]}
                                        ),
                                    },
                                },
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    with VLLMClient(
        VLLMConfig("http://fixture/v1", "host", max_calls=1, tool_mode="native"),
        transport=httpx.MockTransport(respond),
    ) as client:
        host = ContextualHost(
            client,
            memory.dispatch,
            memory_tools("ordinary"),
            "Work",
            memory=memory,
            maintenance_policy="required",
            business_tools={"work": BusinessTool(schema, execute)},
        )
        result = host.run([{"role": "user", "content": "Work"}])
    assert result.status == "maintenance_pending" and not executions


def test_partial_operation_and_hidden_material_cannot_be_no_change_away() -> None:
    memory = bank()
    session = HostSession("session", memory)
    acquired = accept_observation(
        memory, session, Observation("hidden", "body" * 1000, "tool", "fixture"), max_bytes=1
    )
    alias = session.maintenance["pending"][acquired["source_ref"]]["ref"]
    with pytest.raises(ValueError, match="NOT_FULLY_DELIVERED"):
        finish(session, [decision([alias])])
    review = {**decision([alias]), "decision": "pending"}
    assert finish(session, [review])["status"] == "pending"
    committed(
        session,
        receipt_outcome(
            "memory_save",
            {
                "status": "PENDING",
                "operation_id": "unresolved-op",
            },
        ),
        {},
    )
    assert finish(session, [review])["unsettled_operations"]


def test_existing_context_precedes_new_input_without_new_maintenance_or_model_requests() -> None:
    memory = bank()
    source = memory.publish(Observation("old", "A lasting project requirement", "user", "fixture"))
    old = memory.save(content="Existing requirement", source_ref=source)["record"]["ref"]
    events: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": '{"answer":"Received"}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    with VLLMClient(
        VLLMConfig("http://fixture/v1", "host", max_calls=1), transport=httpx.MockTransport(respond)
    ) as client:
        host = ContextualHost(
            client,
            memory.dispatch,
            memory_tools("ordinary"),
            "Work",
            memory=memory,
            emit=events.append,
            initial_context_bytes=6000,
        )
        session, _ = run_task_session(
            [
                TaskTurn(
                    "one",
                    "Update requirement",
                    (Observation("new", "Update requirement", "user", "fixture"),),
                )
            ],
            memory=memory,
            host=host,
            session_id="new-session",
            close=False,
        )
        pending_refs = set(session.maintenance["pending"])
        run_task_session(
            [TaskTurn("two", "Thanks")],
            memory=memory,
            host=host,
            session_id="new-session",
            session=session,
        )
    primed = [event for event in events if event["event"] == "initial_memory_context"]
    assert [event["turn_id"] for event in primed] == ["one", "two"]
    assert len(requests) == 2
    assert old in {binding["exact_ref"] for binding in primed[0]["bindings"].values()}
    assert not pending_refs & {old, source}
    content = [message["content"] for message in requests[0]["messages"]]
    assert next(
        index for index, text in enumerate(content) if text.startswith("Relevant current memory:")
    ) < next(
        index for index, text in enumerate(content) if text.startswith("Current user request:")
    )


def test_turn_prefetch_reuses_only_unchanged_resident_material() -> None:
    memory = bank()
    source = memory.publish(Observation("old", "A lasting project requirement", "user", "fixture"))
    memory.save(content="Existing requirement", source_ref=source)
    session = HostSession("session", memory)
    events: list[dict[str, Any]] = []
    with VLLMClient(VLLMConfig("http://fixture/v1", "host")) as client:
        host = ContextualHost(client, memory.dispatch, memory_tools("ordinary"), "Work",
                              memory=memory, emit=events.append, initial_context_bytes=6000)
        session.begin_turn("one")
        host.prime_session(session, "project requirement")
        first = session.transcript[-1]
        host.prime_session(session, "project requirement")
        assert len(events) == 1
        session.begin_turn("two")
        host.prime_session(session, "project requirement")
        assert session.transcript[-1] is first
        assert events[-1]["reused_resident_message"]
        session.transcript.remove(first)
        session.begin_turn("three")
        assert source not in memory.seen
        host.prime_session(session, "project requirement")
        assert not events[-1]["reused_resident_message"]
        assert source in memory.seen
        assert "A lasting project requirement" in session.transcript[-1]["content"]


def test_prefetch_cache_hit_restores_only_delivered_visibility_under_tiny_budget() -> None:
    memory = bank()
    source = memory.publish(Observation(
        "long", "project-key " + "x" * 7000, "user", "fixture",
    ))
    memory.save(content="project-key " + "y" * 5000, source_ref=source)
    session = HostSession("session", memory)
    events: list[dict[str, Any]] = []
    with VLLMClient(VLLMConfig("http://fixture/v1", "host")) as client:
        host = ContextualHost(client, memory.dispatch, memory_tools("ordinary"), "Work",
                              memory=memory, emit=events.append, initial_context_bytes=400)
        session.begin_turn("one")
        host.prime_session(session, "project-key")
        session.begin_turn("two")
        host.prime_session(session, "project-key")
    assert events[-1]["reused_resident_message"] is True
    assert events[-1]["materials"]["status"] == "INSUFFICIENT_MATERIAL_BUDGET"
    delivered = {binding.exact_ref for binding in session.visible_bindings.values()
                 if binding.spans}
    assert delivered == set()
    assert memory.seen == delivered
    assert memory.visible_source_ranges == {
        binding.exact_ref: set(binding.spans)
        for binding in session.visible_bindings.values()
        if binding.kind == "source" and binding.spans
    }


def test_semantic_maintenance_checks_trusted_ranges_and_actual_durable_support() -> None:
    memory = bank()
    session = HostSession("session", memory)
    session.maintenance["protocol"] = SEMANTIC_MAINTENANCE_PROTOCOL
    session.begin_turn("one")
    source = accept_observation(
        memory, session, Observation("requirement", "Keep this requirement", "user", "fixture"),
        required_review_ranges=((0, 21),), persistence_required=True,
    )["source_ref"]
    alias = session.maintenance["pending"][source]["ref"]
    session.transcript.pop()
    session.refresh_visibility()
    with pytest.raises(ValueError, match="REQUIRED_REVIEW_MISSING"):
        semantic_finish(session, {"decision": "processed", "remaining": []})
    memory.read(source, include_sources=False, _visible=False)
    assert semantic_frontier(session)["review_coverage"][0][
        "unreviewed_required_ranges"] == [[0, 21]]
    view = session.material_view
    assert view is not None
    session.append_material(view.project(memory.read(source, include_sources=False,
                                                      _visible=False), max_bytes=4000))
    with pytest.raises(ValueError, match="REQUIRED_PERSISTENCE_MISSING"):
        semantic_finish(session, {"decision": "processed", "remaining": []})
    created = memory.save(op="CREATE", content="Keep this requirement", about_ref="unresolved",
                          source_refs=[source], certainty="explicit")
    committed(session, receipt_outcome("memory_save", created), created)
    assert semantic_frontier(session)["committed_changes"][0]["delivery"] == "not_delivered"
    with pytest.raises(ValueError, match="NOT_SELECTED_AFTER_COMMITTED_WRITE"):
        semantic_finish(session, {"decision": "not_selected", "remaining": []})
    current = memory.workspace.cards[memory._handle(created["record"]["ref"])]
    current.retired = True
    with pytest.raises(ValueError, match="REQUIRED_PERSISTENCE_MISSING"):
        semantic_finish(session, {"decision": "processed", "remaining": []})
    current.retired = False
    result = semantic_finish(session, {"decision": "processed", "remaining": []})
    assert result["status"] == "complete"
    session.begin_turn("two")
    assert semantic_frontier(session)["committed_changes"] == []
    assert alias not in {item["ref"] for item in semantic_frontier(session)["review_coverage"]}


def test_semantic_maintenance_optional_partial_is_reported_without_full_review_claim() -> None:
    memory = bank()
    session = HostSession("session", memory)
    session.maintenance["protocol"] = SEMANTIC_MAINTENANCE_PROTOCOL
    session.begin_turn("one")
    acquired = accept_observation(memory, session, Observation(
        "tool", "abcdef", "tool", "fixture"), deliver=False,
    )
    source = acquired["source_ref"]
    view = session.material_view
    assert view is not None
    partial = view.project(memory.read(source, start=0, length=3,
                                       include_sources=False, _visible=False), max_bytes=1200)
    session.append_material(partial)
    frontier = semantic_frontier(session)
    assert "persistence_required" not in frontier["review_coverage"][0]
    assert frontier["review_coverage"][0]["unreviewed_required_ranges"] == []
    assert frontier["review_coverage"][0]["delivered_ranges"] == [
        [0, 3]]
    assert frontier["review_coverage"][0]["unreviewed_ranges"] == [[3, 6]]
    assert semantic_finish(session, {"decision": "not_selected", "remaining": []})[
        "status"] == "complete"
    optional = HostSession("session-optional", memory)
    optional.maintenance["protocol"] = SEMANTIC_MAINTENANCE_PROTOCOL
    optional.begin_turn("two")
    accept_observation(memory, optional, Observation(
        "unseen", "optional context", "tool", "fixture"), deliver=False)
    unseen = semantic_frontier(optional)
    assert unseen["committed_changes"] == []
    assert unseen["review_coverage"][0]["ref"] == "undelivered"
    assert unseen["review_coverage"][0]["unreviewed_ranges"] == [
        [0, len("optional context")]]
    assert semantic_finish(optional, {"decision": "processed", "remaining": []})[
        "status"] == "complete"


def test_semantic_finish_tool_uses_short_receipt_and_program_frontier() -> None:
    memory = bank()
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        action = {"tool": "finish_turn", "arguments": {
            "maintenance": {"decision": "not_selected", "remaining": []}, "answer": "Done",
        }}
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    with VLLMClient(VLLMConfig("http://fixture/v1", "host", max_calls=1),
                    transport=httpx.MockTransport(respond)) as client:
        host = ContextualHost(
            client, memory.dispatch, memory_tools("ordinary"), "Work", memory=memory,
            maintenance_policy="required", maintenance_protocol=SEMANTIC_MAINTENANCE_PROTOCOL,
        )
        _, results = run_task_session([TaskTurn("one", "Hello")], memory=memory,
                                      host=host, session_id="session")
    assert results[0].status == "complete"
    assert results[0].maintenance["protocol"] == SEMANTIC_MAINTENANCE_PROTOCOL
    schema = requests[0]["response_format"]["json_schema"]["schema"]
    assert "maintenance" in schema["properties"]["arguments"]["properties"]
    assert "memory_review" not in schema["properties"]["arguments"]["properties"]
    frontier = next(message["content"] for message in requests[0]["messages"]
                    if message.get("role") == "user"
                    and message["content"].startswith("Maintenance frontier"))
    assert "unreviewed_required_ranges" in frontier
    assert '"persistence_required": false' not in frontier
    assert "Only explicit application requirements" in requests[0]["messages"][0]["content"]


def test_trusted_task_turn_persistence_requirement_cannot_be_not_selected() -> None:
    memory = bank()
    responses = [{"choices": [{"message": {"role": "assistant", "content": json.dumps({
        "tool": "finish_turn", "arguments": {
            "maintenance": {"decision": "not_selected", "remaining": []}, "answer": "Done",
        },
    })}}]}]

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig("http://fixture/v1", "host", max_calls=1),
                    transport=httpx.MockTransport(respond)) as client:
        host = ContextualHost(
            client, memory.dispatch, memory_tools("ordinary"), "Work", memory=memory,
            maintenance_policy="required", maintenance_protocol=SEMANTIC_MAINTENANCE_PROTOCOL,
        )
        _, results = run_task_session([
            TaskTurn("one", "Summarize", (Observation("attachment", "retain me", "tool",
                                                      "fixture"),),
                     required_review_ranges={"attachment": ((0, 9),)},
                     persistence_required=("attachment",)),
        ], memory=memory, host=host, session_id="session")
    assert results[0].status == "maintenance_pending"
    assert results[0].maintenance["review_coverage"][0]["persistence_required"]
