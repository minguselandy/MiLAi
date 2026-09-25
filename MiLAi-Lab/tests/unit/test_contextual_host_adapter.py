from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
from jsonschema import ValidationError, validate

from milai_lab.methods.contextual_memory.deletion import DeletionLedger
from milai_lab.methods.contextual_memory.material_view import VIEW_PROTOCOL
from milai_lab.methods.contextual_memory.operations import TaskEnvelope
from milai_lab.methods.contextual_user_memory import TOOLS as MEMORY_TOOLS
from milai_lab.methods.contextual_user_memory import ContextualMemory, Observation
from milai_lab.runners.contextual_session import HostSession

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
adapter = importlib.import_module("contextual_host_adapter")
ContextualHost = adapter.ContextualHost
VLLMClient = adapter.VLLMClient
VLLMConfig = adapter.VLLMConfig


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search memory",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }
]


def _tool_call(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


def _two_tool_calls() -> dict[str, Any]:
    message = _tool_call("call-1", "memory_search", '{"query":"tea"}')
    message["tool_calls"].append(
        {
            "id": "call-2",
            "type": "function",
            "function": {"name": "memory_search", "arguments": '{"query":"coffee"}'},
        }
    )
    return message


def _provider(
    responses: list[dict[str, Any]],
) -> tuple[VLLMClient, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode="native"),
        transport=httpx.MockTransport(respond),
    )
    return client, requests


def _receipt(message: dict[str, Any], usage: dict[str, int] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"choices": [{"message": message}]}
    if usage is not None:
        result["usage"] = usage
    return result


def test_delta_save_resolves_only_delivered_target_relations_and_new_body() -> None:
    memory = ContextualMemory("owner", host_id="test-host",
                              embed=lambda texts: [[1.0, 0.0] for _ in texts],
                              embedding_dimension=2)
    memory.start_task("session", "Update exact matter")
    session = HostSession("session", memory)
    view = session.material_view
    assert view is not None
    old_source = memory.publish(Observation("old", "Plan pending", "user", "fixture"))
    memory.save(op="RETAIN_SOURCE", source_ref=old_source, persistence="durable")
    saved = memory.save(op="CREATE", content="Plan pending", about_ref="unresolved",
                        source_refs=[old_source], certainty="explicit")
    target = saved["record"]["ref"]
    projected_target = view.project(memory.read(target, include_sources=False,
                                                _visible=False), max_bytes=6000)
    session.append_material(projected_target)
    row = next(item for item in projected_target["materials"]
               if item.get("kind") == "interpretation")
    assert row["body_delivery"] == "full"
    old_alias = row["source_refs"][0]
    new_source = memory.publish(Observation("new", "Plan complete", "tool", "fixture"))
    memory.save(op="RETAIN_SOURCE", source_ref=new_source, persistence="durable")
    projected_source = view.project(memory.read(new_source, include_sources=False,
                                                _visible=False), max_bytes=6000)
    session.append_material(projected_source)
    new_alias = projected_source["materials"][0]["ref"]
    delta = {"op": "REVISE", "basis_mode": "delta", "target_ref": row["ref"],
             "content_patch": [{"old": "pending", "new": "complete"}],
             "source_delta": {"add": [new_alias], "remove": [old_alias]}}
    client, _ = _provider([
        _receipt(_tool_call("delta", "memory_save", json.dumps(delta))),
        _receipt({"role": "assistant", "content": "Done."}),
    ])
    result = ContextualHost(client, memory.dispatch, MEMORY_TOOLS, "Update",
                            memory=memory).run([], session=session, max_calls=2)
    assert result.status == "complete" and result.calls[0]["ok"]
    current = memory.workspace.cards[memory._handle(target)]
    assert current.text == "Plan complete"
    assert current.source_refs == [new_source]
    client.close()


class _CountingCapacity:
    identity: ClassVar[dict[str, str]] = {"tokenizer": "fixed-test"}
    enable_thinking = False

    @staticmethod
    def text_tokens(text: str) -> int:
        return len(text)

    @staticmethod
    def check(
        _messages: Any,
        _output_tokens: int,
        _tools: Any,
    ) -> dict[str, int]:
        return {"prompt_tokens": 1, "output_reserve_tokens": 1, "safety_tokens": 0}


def test_native_loop_dispatches_and_pairs_real_tool_result() -> None:
    client, requests = _provider(
        [
            _receipt(
                _tool_call("call-1", "memory_search", '{"query":"tea"}'),
                {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            ),
            _receipt(
                {"role": "assistant", "content": "You prefer tea."},
                {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
            ),
        ]
    )
    dispatch_calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        dispatch_calls.append((name, arguments))
        return {"records": ["Tea is preferred"]}

    result = ContextualHost(client, dispatch, TOOLS, "Use memory tools.", memory=None).run(
        [{"role": "user", "content": "What drink do I prefer?"}]
    )

    assert result.answer == "You prefer tea."
    assert result.status == "complete"
    assert result.calls[0]["result"] == {"records": ["Tea is preferred"]}
    assert dispatch_calls == [("memory_search", {"query": "tea"})]
    assert result.transcript[-1]["role"] == "assistant"
    assert result.transcript[-2]["tool_call_id"] == "call-1"
    assert json.loads(result.transcript[-2]["content"])["result"] == {
        "records": ["Tea is preferred"]
    }
    assert json.loads(result.transcript[-2]["content"])["remaining_model_calls"] == 11
    assert result.usage["total_tokens"] == 18
    assert len(requests) == 2
    assert all("response_format" not in request for request in requests)
    client.close()


def test_delta_host_receipts_keep_status_after_overlapping_queries() -> None:
    client, requests = _provider(
        [
            _receipt(_tool_call("one", "memory_search", '{"query":"tea"}')),
            _receipt(_tool_call("two", "memory_search", '{"query":"drink"}')),
            _receipt({"role": "assistant", "content": "Tea, only at home."}),
        ]
    )
    client.capacity = _CountingCapacity()  # type: ignore[assignment]
    events: list[dict[str, Any]] = []
    result = ContextualHost(
        client,
        lambda name, args: {
            "materials": [
                {
                    "kind": "interpretation",
                    "ref": "u/card:1@1",
                    "text": "Tea at home. " * 100,
                    "status": "CURRENT",
                    "context": "home only",
                    "associated_materials": [
                        {
                            "kind": "interpretation",
                            "ref": "u/card:2@1",
                            "text": "Correction: home only.",
                            "status": "CURRENT",
                        }
                    ],
                }
            ]
        },
        TOOLS,
        "Use memory tools.",
        emit=events.append,
        delivery_mode="delta",
        memory=None,
    ).run([{"role": "user", "content": "What drink?"}])
    assert "text" in result.calls[0]["result"]["materials"][0]
    repeated = result.calls[1]["result"]["materials"][0]
    assert "text" not in repeated
    assert repeated["delivered_spans"] == []
    assert repeated["context"] == "home only"
    assert json.loads(requests[-1]["messages"][-1]["content"])["result"]["materials"][0] == repeated
    deliveries = [event for event in events if event["event"] == "material_delivery"]
    assert len(deliveries) == 2
    assert deliveries[0]["tokenizer_identity"] == _CountingCapacity.identity
    assert deliveries[0]["body_tokens"] == len("Tea at home. " * 100)
    assert deliveries[0]["associated_material_tokens"] > 0
    assert deliveries[1]["body_tokens"] == 0
    assert deliveries[1]["reference_status_tokens"] > 0
    assert deliveries[1]["associated_material_tokens"] > 0
    assert deliveries[1]["original_total_tokens"] > deliveries[1]["delivered_total_tokens"]
    assert deliveries[1]["token_sections_additive"] is False
    assert "body_tokens" not in repeated
    client.close()


def test_real_memory_host_projects_read_and_write_refs_without_exposing_internal_ids() -> None:
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="off",
    )
    source_ref = memory.publish(
        Observation("source", "Tea at home", "user", "fixture", actor_ref="current_user")
    )
    old_ref = memory.save(content="Prefers tea", source_ref=source_ref)["record"]["ref"]
    memory.start_task("answer", "What drink?")
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        requests.append(wire)
        if len(requests) == 1:
            message = _tool_call("search", "memory_search", '{"query":"tea"}')
        elif len(requests) == 2:
            receipt = json.loads(
                next(
                    msg["content"]
                    for msg in wire["messages"]
                    if msg.get("tool_call_id") == "search"
                )
            )
            source = next(row for row in receipt["result"]["materials"] if row["kind"] == "source")
            assert list(source).index("role") < list(source).index("content")
            card = next(
                row for row in receipt["result"]["materials"] if row["kind"] == "interpretation"
            )
            message = _tool_call("read", "memory_read", json.dumps({"ref": card["ref"]}))
        elif len(requests) == 3:
            receipt = json.loads(
                next(
                    msg["content"] for msg in wire["messages"] if msg.get("tool_call_id") == "read"
                )
            )
            card = receipt["result"]["materials"][0]
            message = _tool_call(
                "save",
                "memory_save",
                json.dumps(
                    {
                        "certainty": "explicit",
                        "op": "REVISE",
                        "target_ref": card["ref"],
                        "content": "Prefers tea only at home",
                        "about_ref": "u0",
                        "source_refs": [
                            next(
                                row["ref"]
                                for row in json.loads(
                                    next(
                                        msg["content"]
                                        for msg in wire["messages"]
                                        if msg.get("tool_call_id") == "search"
                                    )
                                )["result"]["materials"]
                                if row["kind"] == "source"
                            )
                        ],
                        "dependencies": [],
                    }
                ),
            )
        else:
            message = {"role": "assistant", "content": "Tea at home."}
        return httpx.Response(200, json=_receipt(message))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode="native"),
        transport=httpx.MockTransport(respond),
    )
    client.capacity = _CountingCapacity()  # type: ignore[assignment]
    events: list[dict[str, Any]] = []
    result = ContextualHost(
        client, memory.dispatch, MEMORY_TOOLS, "Use memory.", emit=events.append, memory=memory
    ).run([{"role": "user", "content": "What drink?"}], max_calls=4)
    assert result.status == "complete" and result.answer == "Tea at home."
    assert [call["ok"] for call in result.calls] == [True, True, True]
    assert memory.resolve(old_ref) != old_ref
    assert memory.workspace.cards[memory._handle(old_ref)].text == "Prefers tea only at home"
    for call in result.calls:
        if "result" in call:
            assert old_ref not in json.dumps(call["result"])
            assert source_ref not in json.dumps(call["result"])
            assert old_ref not in json.dumps(call["operation_receipt"])
    new_ref = memory.resolve(old_ref)
    assert new_ref not in json.dumps(result.calls[-1]["result"])
    assert result.calls[-1]["result"]["record"]["ref"].startswith("m")
    deliveries = [event for event in events if event["event"] == "material_delivery"]
    assert len(deliveries) == 2
    assert all(
        event["internal_material_bytes"] > event["projected_material_bytes"] for event in deliveries
    )
    assert all(
        event["material_view_protocol"] == VIEW_PROTOCOL for event in deliveries
    )
    client.close()


def test_insufficient_material_budget_does_not_authorize_internal_search_result() -> None:
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="off",
    )
    source_ref = memory.publish(
        Observation("source", "Tea at home", "user", "fixture", actor_ref="current_user")
    )
    old_ref = memory.save(content="Prefers tea", source_ref=source_ref)["record"]["ref"]
    memory.start_task("answer", "What drink?")
    client, _ = _provider(
        [
            _receipt(_tool_call("search", "memory_search", '{"query":"tea","max_bytes":1}')),
            _receipt(
                _tool_call(
                    "save",
                    "memory_save",
                    json.dumps(
                        {
                            "certainty": "explicit",
                            "op": "REVISE",
                            "target_ref": "m0",
                            "content": "Unauthorized change",
                            "about_ref": "u0",
                            "source_refs": [],
                            "dependencies": [],
                        }
                    ),
                )
            ),
            _receipt({"role": "assistant", "content": "Insufficient material."}),
        ]
    )
    result = ContextualHost(
        client, memory.dispatch, MEMORY_TOOLS, "Use memory.", memory=memory
    ).run([{"role": "user", "content": "What drink?"}], max_calls=3)
    assert result.calls[0]["result"]["status"] == "INSUFFICIENT_MATERIAL_BUDGET"
    assert result.calls[1]["ok"] is False
    assert "MATERIAL_REF_NOT_DELIVERED" in result.calls[1]["error"]
    assert memory.seen == set()
    assert memory.visible_source_ranges == {}
    assert memory.resolve(old_ref) == old_ref
    client.close()


@pytest.mark.parametrize("include_sources", [True, False, None])
def test_read_explicit_sources_projects_only_their_delivered_body_ranges(
    include_sources: bool | None,
) -> None:
    memory = ContextualMemory(
        "user", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, state_policy="off",
    )
    first = memory.publish(Observation("first", "Original customer request", "user", "fixture"))
    second = memory.publish(Observation("second", "Confirmed revised amount", "user", "fixture"))
    card = memory.save(
        content="The current agreed amount is revised", source_refs=[first, second],
    )["record"]["ref"]
    memory.start_task("answer", "What amount applies?")
    session = HostSession("answer", memory)
    assert session.material_view is not None
    initial = session.material_view.project(memory.read(card, False, _visible=False))
    session.append_material(initial)
    alias = initial["materials"][0]["ref"]
    source_alias = initial["materials"][0]["source_refs"][0]
    arguments: dict[str, Any] = {"ref": alias}
    if include_sources is not None:
        arguments["include_sources"] = include_sources
    responses = [_receipt(_tool_call("read", "memory_read", json.dumps(arguments)))]
    if include_sources is False:
        responses.append(_receipt(_tool_call("save", "memory_save", json.dumps({
            "op": "CREATE", "content": "Cannot use unseen source body", "certainty": "explicit",
            "about_ref": "unknown", "source_refs": [source_alias],
        }))))
    responses.append(_receipt({"role": "assistant", "content": "Done."}))
    client, _ = _provider(responses)
    result = ContextualHost(
        client, memory.dispatch, MEMORY_TOOLS, "Use memory.", memory=memory,
        initial_context_bytes=0,
    ).run([{"role": "user", "content": "What amount applies?"}], session=session, max_calls=3)
    assert result.status == "complete"
    rows = [row for row in result.calls[0]["result"]["materials"]
            if row["kind"] == "source"]
    assert bool(rows) is (include_sources is not False)
    if rows:
        assert {row["content"] for row in rows} == {
            "Original customer request", "Confirmed revised amount",
        }
        assert {session.visible_bindings[row["ref"]].exact_ref for row in rows} == {first, second}
        assert all(session.visible_bindings[row["ref"]].spans for row in rows)
    else:
        assert not {binding.exact_ref for binding in session.visible_bindings.values()
                    if binding.kind == "source" and binding.spans}
        assert result.calls[1]["ok"] is False
        assert f"source_refs[0]={source_alias}" in result.calls[1]["error"]
    client.close()


def test_short_source_basis_resolves_only_after_its_text_was_delivered() -> None:
    save_tool = next(tool for tool in MEMORY_TOOLS if tool["function"]["name"] == "memory_save")
    setting_description = save_tool["function"]["parameters"]["properties"]["conditions"][
        "properties"
    ]["setting"]["description"]
    assert "Environment in which the claim applies" in setting_description
    assert "Comparison: exact" in setting_description
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="off",
    )
    source_ref = memory.publish(
        Observation("source", "Tea at home", "user", "fixture", actor_ref="current_user")
    )
    memory.save(
        content="Tea preference at home", source_ref=source_ref, conditions={"setting": "home"}
    )
    memory.start_task("answer", "Where does tea apply?")
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        requests.append(wire)
        if len(requests) == 1:
            message = _tool_call("search", "memory_search", '{"query":"tea home"}')
        elif len(requests) == 2:
            receipt = json.loads(
                next(
                    msg["content"]
                    for msg in wire["messages"]
                    if msg.get("tool_call_id") == "search"
                )
            )
            source = next(
                row
                for row in receipt["result"]["materials"]
                if row["kind"] == "source" and "Tea at home" in row.get("content", "")
            )
            message = _tool_call(
                "read",
                "memory_read",
                json.dumps(
                    {
                        "ref": source["ref"],
                        "condition_evidence": [
                            {
                                "key": "setting",
                                "value": "home",
                                "basis": "visible_source",
                                "basis_ref": source["ref"],
                                "quote": "Tea at home",
                            }
                        ],
                    }
                ),
            )
        else:
            message = {"role": "assistant", "content": "At home."}
        return httpx.Response(200, json=_receipt(message))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode="native"),
        transport=httpx.MockTransport(respond),
    )
    result = ContextualHost(
        client, memory.dispatch, MEMORY_TOOLS, "Use memory.", memory=memory
    ).run(
        [{"role": "user", "content": "Where?"}],
        max_calls=3,
    )
    assert result.status == "complete" and all(call["ok"] for call in result.calls)
    evidence = memory.state.query_context["condition_evidence"][-1]
    assert evidence["basis_ref"] == source_ref
    assert evidence["basis"] == "visible_source"
    assert source_ref not in json.dumps(result.calls[1]["result"])
    client.close()


def test_model_forget_call_is_rejected_without_dispatch_or_context_reset() -> None:
    client, requests = _provider(
        [
            _receipt(_tool_call("one", "memory_search", '{"query":"preference"}')),
            _receipt(_tool_call("two", "memory_save", '{"forget_refs":["u/source:a"]}')),
            _receipt({"role": "assistant", "content": "The memory was forgotten."}),
        ]
    )
    result = ContextualHost(
        client,
        lambda name, args: (
            {
                "materials": [
                    {"kind": "source", "ref": "u/source:a", "content": "Private observation body"}
                ]
            }
            if name == "memory_search"
            else {"status": "FORGOTTEN", "refs": ["u/source:a"]}
        ),
        MEMORY_TOOLS,
        "Use memory tools.",
        delivery_mode="delta",
        memory=None,
    ).run([{"role": "user", "content": "Read then forget the old preference."}])
    assert "Private observation body" in json.dumps(requests[1]["messages"])
    assert "Private observation body" in json.dumps(requests[2]["messages"])
    assert result.calls[1]["ok"] is False
    assert "trusted lifecycle executor" in result.calls[1]["error"]
    rejected = result.calls[1]["operation_receipt"]
    assert rejected["decision"] == "REJECTED"
    assert rejected["completion"] == "failed"
    assert rejected["operation_id"].startswith("save:")
    assert result.calls[1]["result"]["operation_id"] == rejected["operation_id"]
    assert not any(call.get("result", {}).get("status") == "FORGOTTEN" for call in result.calls)
    client.close()


@pytest.mark.parametrize("mode", ["native", "json_action"])
def test_unparsed_save_arguments_get_program_bound_rejected_receipt(mode: str) -> None:
    malformed = (
        _tool_call("bad-save", "memory_save", "{bad")
        if mode == "native"
        else {"role": "assistant", "content": '{"tool":"memory_save","arguments":[]}'}
    )
    final = (
        {"role": "assistant", "content": "Done."}
        if mode == "native"
        else {"role": "assistant", "content": '{"answer":"Done."}'}
    )
    responses = [_receipt(malformed), _receipt(final)]
    dispatched: list[str] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode=mode),
        transport=httpx.MockTransport(respond),
    )
    result = ContextualHost(
        client,
        lambda name, _args: dispatched.append(name) or {},
        MEMORY_TOOLS,
        "Use memory.",
        memory=None,
    ).run([], max_calls=2)
    assert dispatched == []
    assert result.calls[0]["ok"] is False
    rejected = result.calls[0]["operation_receipt"]
    assert rejected["decision"] == "REJECTED"
    assert rejected["completion"] == "failed"
    assert rejected["operation_id"].startswith("save:")
    assert result.calls[0]["result"]["operation_id"] == rejected["operation_id"]
    client.close()


def test_lifecycle_continuation_waits_for_cleanup_and_uses_retained_input(
    tmp_path: Path,
) -> None:
    ledger = DeletionLedger(tmp_path / "deletions.json", "user")
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [],
        deletion_ledger=ledger,
    )
    ref = memory.publish(
        Observation("one", "private body", "user", "archive", actor_ref="current_user")
    )
    memory.save(source_ref=ref)
    memory.start_task("lifecycle", "")
    envelope = TaskEnvelope(
        "user",
        "lifecycle",
        "lifecycle",
        frozenset({"delete"}),
        (ref,),
        "operation-1",
        "delete_then_answer",
        "Answer the public question.",
        str(ledger.path.parent.resolve()),
    )
    memory.bind_envelope(envelope)
    memory.forget([ref], envelope=envelope, cleanup_effects=("answer_artifacts",))
    client, requests = _provider([_receipt({"role": "assistant", "content": "Public answer"})])
    host = ContextualHost(client, memory.dispatch, MEMORY_TOOLS, "Use memory tools.", memory=memory)
    pending = host.run([{"role": "user", "content": "private body"}], envelope=envelope)
    assert pending.status == "cleanup_pending"
    assert requests == []
    ledger.complete_effect("operation-1", "answer_artifacts")
    continued = host.run([{"role": "user", "content": "private body"}], envelope=envelope)
    assert continued.answer == "Public answer"
    assert "private body" not in json.dumps(requests)
    assert "Answer the public question." in json.dumps(requests)
    client.close()


def test_json_action_schema_error_is_returned_for_correction() -> None:
    responses = [
        _receipt({"role": "assistant", "content": '{"tool":"memory_search","arguments":{}}'}),
        _receipt(
            {
                "role": "assistant",
                "content": '{"tool":"memory_search","arguments":{"query":"tea"}}',
            }
        ),
        _receipt({"role": "assistant", "content": '{"answer":"Tea is preferred."}'}),
    ]
    wire_requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire_requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    client = VLLMClient(
        VLLMConfig(
            "http://vllm.test/v1",
            "test-host",
            tool_mode="json_action",
            response_format={"type": "json_object"},
        ),
        transport=httpx.MockTransport(respond),
    )
    result = ContextualHost(
        client,
        lambda name, args: {"matched": args["query"]},
        TOOLS,
        "Use memory tools.",
        memory=None,
    ).run([{"role": "user", "content": "Find my drink preference."}], max_calls=3)

    assert result.answer == "Tea is preferred."
    assert result.calls[0]["ok"] is False
    assert "query" in result.calls[0]["error"]
    assert result.calls[1]["result"] == {"matched": "tea"}
    assert "configured json_action mode" in wire_requests[0]["messages"][0]["content"]
    assert '"required": ["query"]' in wire_requests[0]["messages"][0]["content"]
    assert "Search memory" in wire_requests[0]["messages"][0]["content"]
    assert "tools" not in wire_requests[0]
    assert "json_action tool result" in wire_requests[1]["messages"][-1]["content"]
    assert all(
        request["response_format"]["json_schema"]["name"] == "host_action"
        for request in wire_requests[:-1]
    )
    action_schema = wire_requests[0]["response_format"]["json_schema"]["schema"]
    validate({"answer": "Tea is preferred."}, action_schema)
    validate({"tool": "memory_search", "arguments": {"query": "tea"}}, action_schema)
    with pytest.raises(ValidationError):
        validate({"tool": "memory_search", "arguments": {}}, action_schema)
    assert wire_requests[-1]["response_format"] == adapter.FINAL_ANSWER_RESPONSE_FORMAT
    first_receipt = json.loads(wire_requests[1]["messages"][-1]["content"].split(": ", 1)[1])
    second_receipt = json.loads(wire_requests[2]["messages"][-2]["content"].split(": ", 1)[1])
    assert first_receipt["remaining_model_calls"] == 2
    assert second_receipt["remaining_model_calls"] == 1
    client.close()


@pytest.mark.parametrize("mode", ["native", "json_action"])
def test_dispatch_error_reaches_next_request_and_trace(mode: str) -> None:
    partial_result = {
        "status": "ERROR",
        "error": "DEPENDENCY_REQUIRES_READ_VERSION",
        "source": {"status": "RETAINED", "ref": "source:kept"},
    }
    arguments = {"source_ref": "source:kept", "content": "An interpretation"}
    if mode == "native":
        first = _tool_call("call-1", "memory_save", json.dumps(arguments))
        last = {"role": "assistant", "content": "Done."}
    else:
        first = {
            "role": "assistant",
            "content": json.dumps({"tool": "memory_save", "arguments": arguments}),
        }
        last = {"role": "assistant", "content": '{"answer":"Done."}'}
    responses = [_receipt(first), _receipt(last)]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode=mode),
        transport=httpx.MockTransport(respond),
    )
    events: list[dict[str, Any]] = []
    result = ContextualHost(
        client,
        lambda _name, _arguments: partial_result,
        MEMORY_TOOLS,
        "Use memory.",
        events.append,
        memory=None,
    ).run([], max_calls=2)

    assert result.answer == "Done."
    assert result.calls[0]["ok"] is False
    assert result.calls[0]["result"] == partial_result
    assert result.calls[0]["remaining_model_calls"] == 1
    assert [event for event in events if event["event"] == "host_tool_call"] == [
        {"event": "host_tool_call", "call": result.calls[0]}
    ]
    dispatch_events = [event for event in events if event["event"] == "host_dispatch"]
    assert len(dispatch_events) == 1
    assert dispatch_events[0]["tool"] == "memory_save"
    assert dispatch_events[0]["elapsed_seconds"] >= 0
    messages = requests[1]["messages"]
    if mode == "native":
        receipt = json.loads(next(msg["content"] for msg in messages if msg["role"] == "tool"))
    else:
        receipt = json.loads(messages[-2]["content"].split(": ", 1)[1])
    assert receipt["ok"] is False
    assert receipt["result"] == partial_result
    assert receipt["remaining_model_calls"] == 1
    client.close()


@pytest.mark.parametrize("mode", ["native", "json_action"])
def test_repeated_read_is_compact_and_write_invalidates_cache(mode: str) -> None:
    actions = ["memory_search", "memory_search", "memory_save", "memory_search"]
    arguments = [
        {"query": "tea"},
        {"query": "tea"},
        {"source_ref": "source:kept"},
        {"query": "tea"},
    ]
    responses = []
    for index, (name, args) in enumerate(zip(actions, arguments, strict=True)):
        if mode == "native":
            message = _tool_call(f"call-{index}", name, json.dumps(args))
        else:
            message = {
                "role": "assistant",
                "content": json.dumps({"tool": name, "arguments": args}),
            }
        responses.append(_receipt(message))
    responses.append(
        _receipt(
            {"role": "assistant", "content": "Done."}
            if mode == "native"
            else {"role": "assistant", "content": '{"answer":"Done."}'}
        )
    )
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode=mode),
        transport=httpx.MockTransport(respond),
    )
    dispatched: list[str] = []

    def dispatch(name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        dispatched.append(name)
        if name == "memory_save":
            return {
                "status": "ERROR",
                "error": "INVALID_VERSION",
                "source": {"status": "RETAINED", "ref": "source:kept"},
            }
        return {"materials": [{"content": "large search result " * 100}], "search": len(dispatched)}

    result = ContextualHost(client, dispatch, MEMORY_TOOLS, "Use memory.", memory=None).run(
        [], max_calls=5
    )

    assert result.status == "complete"
    assert result.answer == "Done."
    assert dispatched == ["memory_search", "memory_save", "memory_search"]
    assert result.calls[1]["reused"] is True
    assert result.calls[1]["reused_from_call"] == 0
    assert "result" not in result.calls[1]
    assert result.calls[2]["ok"] is False
    assert result.calls[2]["result"]["source"]["status"] == "RETAINED"
    assert result.calls[3]["result"]["search"] == 3
    if mode == "native":
        repeated_receipt = json.loads(
            next(
                msg["content"]
                for msg in requests[2]["messages"]
                if msg.get("tool_call_id") == "call-1"
            )
        )
    else:
        action_schema = requests[0]["response_format"]["json_schema"]["schema"]
        validate({"tool": "memory_read", "arguments": {"ref": "source:known"}}, action_schema)
        with pytest.raises(ValidationError):
            validate({"tool": "memory_read", "arguments": {}}, action_schema)
        repeated_receipt = json.loads(requests[2]["messages"][-1]["content"].split(": ", 1)[1])
    assert repeated_receipt["reused"] is True
    assert "large search result" not in json.dumps(repeated_receipt)
    client.close()


def test_condition_evidence_invalidates_earlier_read_cache() -> None:
    evidence = [{"key": "setting", "value": "home", "basis": "inference"}]
    old = {"ref": "u/card:old@1"}
    new = {"ref": "u/card:new@1", "condition_evidence": evidence}
    arguments = [old, new, new, old, old]
    client, _ = _provider(
        [
            *[
                _receipt(_tool_call(f"call-{index}", "memory_read", json.dumps(args)))
                for index, args in enumerate(arguments)
            ],
            _receipt({"role": "assistant", "content": "Done."}),
        ]
    )
    dispatched: list[str] = []
    current_condition = "unknown"

    def dispatch(_name: str, args: dict[str, Any]) -> dict[str, Any]:
        nonlocal current_condition
        if args.get("condition_evidence"):
            current_condition = args["condition_evidence"][0]["value"]
        dispatched.append(args["ref"])
        return {
            "kind": "interpretation",
            "ref": args["ref"],
            "status": "CURRENT",
            "text": "Stored material",
            "condition": current_condition,
        }

    result = ContextualHost(client, dispatch, MEMORY_TOOLS, "Use memory.", memory=None).run(
        [],
        max_calls=6,
    )

    assert result.status == "complete"
    assert dispatched == [old["ref"], new["ref"], old["ref"]]
    assert [call.get("reused", False) for call in result.calls] == [
        False,
        False,
        True,
        False,
        True,
    ]
    assert result.calls[0]["result"]["condition"] == "unknown"
    assert result.calls[3]["result"]["condition"] == "home"
    client.close()


@pytest.mark.parametrize("mode", ["native", "json_action"])
def test_repeated_read_ends_with_no_progress(mode: str) -> None:
    responses = [
        _receipt(
            _tool_call(f"call-{index}", "memory_search", '{"query":"tea"}')
            if mode == "native"
            else {
                "role": "assistant",
                "content": '{"tool":"memory_search","arguments":{"query":"tea"}}',
            }
        )
        for index in range(4)
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode=mode),
        transport=httpx.MockTransport(respond),
    )
    dispatched: list[str] = []
    events: list[dict[str, Any]] = []
    result = ContextualHost(
        client,
        lambda name, _args: dispatched.append(name) or {"materials": ["tea"]},
        TOOLS,
        "Use memory.",
        events.append,
        memory=None,
    ).run([], max_calls=7)

    assert result.status == "no_progress"
    assert result.answer == ""
    assert len(requests) == 4
    assert dispatched == ["memory_search"]
    assert [call.get("reused", False) for call in result.calls] == [False, True, True, True]
    assert events[-1] == {
        "event": "host_no_progress",
        "consecutive_calls": 3,
        "model_calls": 4,
    }
    client.close()


def test_zero_model_call_budget_never_requests_or_dispatches() -> None:
    client, requests = _provider([])
    result = ContextualHost(
        client, lambda _name, _args: {"records": []}, TOOLS, "Use memory tools.", memory=None
    ).run([], max_calls=0)

    assert result.status == "budget_exhausted"
    assert result.answer == ""
    assert result.calls == []
    assert requests == []
    assert result.usage == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }
    client.close()


def test_native_multi_call_response_pairs_every_tool_receipt() -> None:
    client, requests = _provider(
        [
            _receipt(_two_tool_calls()),
            _receipt({"role": "assistant", "content": "Tea and coffee."}),
        ]
    )
    result = ContextualHost(
        client, lambda _name, args: {"matched": args["query"]}, TOOLS, "Use tools.", memory=None
    ).run([], max_calls=2)

    assert result.status == "complete"
    assert [call["result"]["matched"] for call in result.calls] == ["tea", "coffee"]
    assert [message["tool_call_id"] for message in requests[1]["messages"][-3:-1]] == [
        "call-1",
        "call-2",
    ]
    assert [
        json.loads(message["content"])["remaining_model_calls"]
        for message in requests[1]["messages"][-3:-1]
    ] == [1, 1]
    assert requests[1]["tool_choice"] == "none"
    assert requests[1]["tools"] == TOOLS
    client.close()


def test_model_call_budget_does_not_turn_intermediate_text_into_answer() -> None:
    responses = [
        _receipt(
            {
                "role": "assistant",
                "content": '{"tool":"memory_search","arguments":{"query":"tea"}}',
            }
        ),
        _receipt({"role": "assistant", "content": "Let me think about the result."}),
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode="json_action"),
        transport=httpx.MockTransport(respond),
    )
    result = ContextualHost(
        client, lambda _name, _args: {"records": []}, TOOLS, "Use tools.", memory=None
    ).run([], max_calls=2)

    assert result.status == "budget_exhausted"
    assert result.answer == ""
    assert len(requests) == 2
    assert len(result.calls) == 2
    last_receipt = requests[1]["messages"][-2]["content"]
    assert json.loads(last_receipt.split(": ", 1)[1])["remaining_model_calls"] == 1
    assert (
        json.loads(result.transcript[-1]["content"].split(": ", 1)[1])["remaining_model_calls"] == 0
    )
    client.close()


def test_missing_usage_in_one_receipt_keeps_total_unknown() -> None:
    client, _ = _provider(
        [
            _receipt(
                _tool_call("call-1", "memory_search", '{"query":"tea"}'),
                {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            ),
            _receipt({"role": "assistant", "content": "Tea."}),
        ]
    )
    result = ContextualHost(
        client, lambda _name, _args: {"records": []}, TOOLS, "Use tools.", memory=None
    ).run([])

    assert result.status == "complete"
    assert result.usage == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }
    client.close()


def test_length_finish_reason_is_incomplete_even_with_answer_text() -> None:
    client, requests = _provider(
        [
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "An apparent answer."},
                        "finish_reason": "length",
                    }
                ]
            }
        ]
    )
    result = ContextualHost(client, lambda _name, _args: {}, TOOLS, "Use tools.", memory=None).run(
        [], max_calls=1
    )

    assert result.status == "incomplete"
    assert result.answer == ""
    assert result.calls[0]["remaining_model_calls"] == 0
    assert len(requests) == 1
    client.close()


def test_truncated_json_action_is_not_executed_and_can_be_corrected() -> None:
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"tool":"memory_search","arguments":{"query":"too long"}}',
                    },
                    "finish_reason": "length",
                }
            ]
        },
        _receipt(
            {
                "role": "assistant",
                "content": '{"tool":"memory_search","arguments":{"query":"short"}}',
            }
        ),
        _receipt({"role": "assistant", "content": '{"answer":"Done."}'}),
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    client = VLLMClient(
        VLLMConfig(
            "http://vllm.test/v1",
            "test-host",
            response_format={"type": "json_object"},
        ),
        transport=httpx.MockTransport(respond),
    )
    dispatched: list[str] = []

    def dispatch(_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        dispatched.append(arguments["query"])
        return {"matched": arguments["query"]}

    result = ContextualHost(client, dispatch, TOOLS, "Use tools.", memory=None).run([], max_calls=3)
    assert result.status == "complete"
    assert result.answer == "Done."
    assert dispatched == ["short"]
    assert len(requests) == 3
    assert requests[1]["messages"][-2]["content"].endswith('"too long"}}')
    error = json.loads(requests[1]["messages"][-1]["content"].split(": ", 1)[1])
    assert error["ok"] is False
    assert "truncated" in error["error"]
    assert error["remaining_model_calls"] == 2
    assert requests[-1]["response_format"] == adapter.FINAL_ANSWER_RESPONSE_FORMAT
    assert "last permitted model response" in requests[-1]["messages"][-1]["content"]
    client.close()


def test_final_native_request_rejects_tool_even_if_provider_returns_one() -> None:
    client, requests = _provider(
        [_receipt(_tool_call("last-tool", "memory_search", '{"query":"x"}'))]
    )
    dispatched: list[str] = []
    result = ContextualHost(
        client, lambda name, _args: dispatched.append(name) or {}, TOOLS, "Use tools.", memory=None
    ).run([], max_calls=1)

    assert result.status == "incomplete"
    assert dispatched == []
    assert requests[0]["tool_choice"] == "none"
    assert requests[0]["tools"] == TOOLS
    assert result.calls[0]["ok"] is False
    assert result.calls[0]["remaining_model_calls"] == 0
    assert result.transcript[-1]["tool_call_id"] == "last-tool"
    client.close()


@pytest.mark.parametrize("mode", ["native", "json_action"])
def test_state_profile_seeds_state_then_search_consumes_it(mode: str) -> None:
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="forced_legacy",
    )
    source_ref = memory.publish(
        Observation(
            "source",
            "The user enjoys film discussions",
            "user",
            "fixture",
            actor_ref="current_user",
        )
    )
    memory.save(source_ref=source_ref, persistence="durable")
    memory.start_task("answer", "What kind of film discussion?")
    requests: list[dict[str, Any]] = []
    actions = [
        ("memory_state", {"context": "Find the user's current film preference"}),
        ("memory_search", {"query": "film discussion"}),
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        requests.append(wire)
        turn = len(requests) - 1
        if turn < len(actions):
            name, arguments = actions[turn]
            message = (
                _tool_call(f"call-{turn}", name, json.dumps(arguments))
                if mode == "native"
                else {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "tool": name,
                            "arguments": arguments,
                        }
                    ),
                }
            )
        else:
            message = (
                {"role": "assistant", "content": "Film discussions."}
                if mode == "native"
                else {"role": "assistant", "content": '{"answer":"Film discussions."}'}
            )
        return httpx.Response(200, json=_receipt(message))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "test-host", tool_mode=mode),
        transport=httpx.MockTransport(respond),
    )
    events: list[dict[str, Any]] = []
    result = ContextualHost(
        client, memory.dispatch, MEMORY_TOOLS, "Use memory.", emit=events.append, memory=memory
    ).run([{"role": "user", "content": "What kind of film discussion?"}], max_calls=4)

    assert result.status == "complete"
    assert [call["name"] for call in result.calls] == ["memory_state", "memory_search"]
    assert all(call["ok"] for call in result.calls)
    assert memory.state.context == "Find the user's current film preference"
    search = next(event for event in events if event["event"] == "state_attention_search")
    assert search["effective_query"] == "film discussion"
    assert search["state_sha256"]
    assert source_ref in search["selected_refs"]
    assert search["delivered_materials"]
    assert search["delivered_materials"][0]["exact_ref"] == source_ref
    assert search["delivered_materials"][0]["spans"]
    if mode == "native":
        assert [request["tool_choice"] for request in requests] == [
            "required",
            "required",
            "auto",
        ]
        assert [
            [tool["function"]["name"] for tool in request["tools"]] for request in requests[:2]
        ] == [["memory_state"], ["memory_search"]]
        initial_schema = requests[0]["tools"][0]["function"]["parameters"]
        later_state = next(
            tool for tool in requests[2]["tools"] if tool["function"]["name"] == "memory_state"
        )
        assert "intentions" in later_state["function"]["parameters"]["properties"]
    else:
        assert [
            request["response_format"]["json_schema"]["schema"]["properties"]["tool"]["const"]
            for request in requests[:2]
        ] == [
            "memory_state",
            "memory_search",
        ]
        initial_schema = requests[0]["response_format"]["json_schema"]["schema"]["properties"][
            "arguments"
        ]
        later_branches = requests[2]["response_format"]["json_schema"]["schema"]["oneOf"]
        later_state = next(
            branch
            for branch in later_branches
            if branch.get("properties", {}).get("tool", {}).get("const") == "memory_state"
        )
        assert "intentions" in later_state["properties"]["arguments"]["properties"]
    for branch in initial_schema["anyOf"]:
        assert set(branch["properties"]) == {"context", "subject", "uncertainty"}
        assert branch["additionalProperties"] is False
    validate({"context": "Find the user's current film preference"}, initial_schema)
    validate(
        {"context": "Find preferences", "subject": "user", "uncertainty": "history"}, initial_schema
    )
    with pytest.raises(ValidationError):
        validate({}, initial_schema)
    with pytest.raises(ValidationError):
        validate({"intentions": ["not-delivered"]}, initial_schema)
    with pytest.raises(ValidationError):
        validate({"context": ""}, initial_schema)
    client.close()


def test_state_profile_rejects_undelivered_refs_before_dispatch() -> None:
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="forced_legacy",
    )
    memory.start_task("answer", "What matters?")
    client, requests = _provider(
        [
            _receipt(
                _tool_call(
                    "invalid",
                    "memory_state",
                    '{"intentions":["not-delivered"]}',
                )
            ),
            _receipt(_tool_call("valid", "memory_state", '{"uncertainty":"Need history"}')),
            _receipt(_tool_call("search", "memory_search", '{"query":"history"}')),
            _receipt({"role": "assistant", "content": "No recorded history."}),
        ]
    )
    result = ContextualHost(
        client, memory.dispatch, MEMORY_TOOLS, "Use memory.", memory=memory
    ).run(
        [{"role": "user", "content": "What matters?"}],
        max_calls=4,
    )
    assert result.status == "complete"
    assert result.calls[0]["ok"] is False
    assert "not valid under any of the given schemas" in result.calls[0]["error"]
    assert "MATERIAL_REF_NOT_DELIVERED" not in result.calls[0]["error"]
    assert memory.state.uncertainty == "Need history"
    assert [request["tools"][0]["function"]["name"] for request in requests[:3]] == [
        "memory_state",
        "memory_state",
        "memory_search",
    ]
    client.close()


def test_state_profile_stops_before_final_answer_if_search_did_not_consume_state() -> None:
    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="forced_legacy",
    )
    memory.start_task("answer", "What matters?")
    client, requests = _provider(
        [
            _receipt(_tool_call("state", "memory_state", '{"context":"Find relevant history"}')),
            _receipt(_tool_call("wrong", "memory_read", '{"ref":"m0"}')),
        ]
    )
    result = ContextualHost(
        client, memory.dispatch, MEMORY_TOOLS, "Use memory.", memory=memory
    ).run(
        [{"role": "user", "content": "What matters?"}],
        max_calls=3,
    )
    assert result.status == "state_unconsumed"
    assert len(requests) == 2
    assert result.calls[1]["ok"] is False
    assert "memory_search must complete" in result.calls[1]["error"]
    client.close()


@pytest.mark.parametrize("mode", ["native", "json_action"])
def test_host_binds_only_delivered_subjects_without_changing_speaker_identity(mode: str) -> None:
    from milai_lab.runners.contextual import memory_tools

    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="off",
    )
    source_ref = memory.publish(Observation("map", "I edit maps.", "assistant", "fixture"))
    memory.save(op="RETAIN_SOURCE", source_ref=source_ref)
    memory.start_task("answer", "What did the speaker describe?")
    requests: list[dict[str, Any]] = []
    speaker_handles: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        requests.append(wire)
        if len(requests) == 1:
            assert '"u0"' not in wire["messages"][0]["content"]
            name, args = "memory_search", {"query": "maps"}
        elif len(requests) == 2:
            receipt_message = wire["messages"][-1]["content"]
            if mode == "json_action":
                receipt_message = receipt_message.split(": ", 1)[1]
            receipt = json.loads(receipt_message)
            source = next(row for row in receipt["result"]["materials"] if row["kind"] == "source")
            speaker_handles.append(source["speaker_ref"])
            assert source["role"] == "assistant"
            schema = wire.get("response_format", {}).get("json_schema", {}).get("schema")
            functions = (
                wire.get("tools", [])
                if mode == "native"
                else [
                    {
                        "function": {
                            "name": branch["properties"]["tool"]["const"],
                            "parameters": branch["properties"]["arguments"],
                        }
                    }
                    for branch in schema["oneOf"]
                    if "tool" in branch["properties"]
                ]
            )
            save = next(
                tool["function"]["parameters"]
                for tool in functions
                if tool["function"]["name"] == "memory_save"
            )
            create = next(
                branch
                for branch in save["oneOf"]
                if branch["properties"]["op"]["const"] == "CREATE"
            )
            assert set(create["properties"]["about_ref"]["enum"]) == {
                "unknown",
                source["speaker_ref"],
            }
            name, args = (
                "memory_save",
                {
                    "certainty": "explicit",
                    "op": "CREATE",
                    "content": "The source speaker edits maps.",
                    "about_ref": source["speaker_ref"],
                    "source_refs": [source["ref"]],
                },
            )
        else:
            message = {"role": "assistant", "content": "The speaker edits maps."}
            if mode == "json_action":
                message["content"] = json.dumps({"answer": message["content"]})
            return httpx.Response(200, json=_receipt(message))
        message = (
            _tool_call(str(len(requests)), name, json.dumps(args))
            if mode == "native"
            else {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "tool": name,
                        "arguments": args,
                    }
                ),
            }
        )
        return httpx.Response(200, json=_receipt(message))

    client = VLLMClient(
        VLLMConfig("http://vllm.test/v1", "host", tool_mode=mode),
        transport=httpx.MockTransport(respond),
    )
    result = ContextualHost(
        client, memory.dispatch, memory_tools("ordinary"), "Use memory.", memory=memory
    ).run(
        [{"role": "user", "content": "What did the speaker describe?"}],
        max_calls=3,
    )
    assert result.status == "complete" and all(call["ok"] for call in result.calls)
    metadata = next(iter(memory.details.values()))
    assert metadata.about_ref == "speaker:" + source_ref
    assert metadata.author == "host"
    assert memory.sources[source_ref].role == "assistant"
    assert source_ref not in json.dumps(result.calls[-1]["result"])
    client.close()


def test_answer_rejects_unsourced_durable_user_claim_but_preserves_author_note() -> None:
    from milai_lab.runners.contextual import memory_tools

    memory = ContextualMemory(
        "user",
        host_id="host",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
        state_policy="off",
    )
    memory.start_task("answer", "Consider a working hypothesis.")
    client, _ = _provider(
        [
            _receipt(
                _tool_call(
                    "user",
                    "memory_save",
                    json.dumps(
                        {
                            "certainty": "explicit",
                            "op": "CREATE",
                            "content": "The user adopted my suggestion.",
                            "about_ref": "u0",
                            "source_refs": [],
                            "persistence": "durable",
                        }
                    ),
                )
            ),
            _receipt(
                _tool_call(
                    "note",
                    "memory_save",
                    json.dumps(
                        {
                            "op": "CREATE",
                            "content": "Working hypothesis: compare the options later.",
                            "about_ref": "unknown",
                            "source_refs": [],
                            "certainty": "uncertain",
                        }
                    ),
                )
            ),
            _receipt({"role": "assistant", "content": "A hypothesis remains unconfirmed."}),
        ]
    )
    result = ContextualHost(
        client, memory.dispatch, memory_tools("ordinary"), "Use memory.", memory=memory
    ).run(
        [{"role": "user", "content": "Consider a working hypothesis."}],
        max_calls=3,
    )
    assert result.status == "complete"
    assert [call["ok"] for call in result.calls] == [False, True]
    assert len(memory.workspace.cards) == 1
    assert next(iter(memory.details.values())).about_ref == "unresolved"
    assert not next(iter(memory.workspace.cards.values())).source_refs
    client.close()
