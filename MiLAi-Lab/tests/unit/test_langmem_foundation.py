"""Small offline checks for the new transport, public tools and recovery boundary."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

pytest.importorskip("langmem")

from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.store.memory import InMemoryStore
from langmem import create_manage_memory_tool, create_search_memory_tool

from milai_lab.baselines.langmem_agent import (
    FoundationScope,
    build_agent,
    invoke_public_message,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import IncompleteChatResponse, VLLMChatModel
from milai_lab.runners.langmem_foundation import (
    BusinessActionJournal,
    UnknownBusinessAction,
    native_business_tools,
)


def _receipt(action: dict[str, Any], request_id: str) -> dict[str, Any]:
    return {
        "id": request_id, "model": "mock",
        "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(action),
        }}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }


def test_json_action_executes_every_upstream_call_in_order(tmp_path: Path) -> None:
    responses = [
        _receipt({"calls": [
            {"name": "manage_memory", "arguments": {
                "action": "create", "content": "likes ramen",
            }},
            {"name": "manage_memory", "arguments": {"content": "likes soba"}},
        ]}, "generation-1"),
        _receipt({"answer": "Saved both."}, "generation-2"),
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client, capacity_path=tmp_path / "capacity.json")
        store = InMemoryStore()
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver)
            messages = invoke_public_message(
                agent, model, FoundationScope("run", "b0", "user", "episode"), "Remember both.",
            )
        tool_results = [str(item.content) for item in messages if item.type == "tool"]
        assert len(tool_results) == 2
        assert all(result.startswith("created memory ") for result in tool_results)
        assert len(store.search(("langmem", "run", "b0", "user"))) == 2
        assert messages[-1].content == "Saved both."
        assert len(requests) == 2
        assert all("tools" not in request for request in requests)
        assert all([message["role"] for message in request["messages"]].count("system") == 1
                   for request in requests)
        assert all(request["messages"][0]["role"] == "system" for request in requests)
        prior_action = next(message for message in requests[1]["messages"]
                            if message["role"] == "assistant")
        assert "tool_calls" not in prior_action
        assert [call["name"] for call in json.loads(prior_action["content"])["calls"]] == [
            "manage_memory", "manage_memory",
        ]
        assert len([message for message in requests[1]["messages"]
                    if message["role"] == "tool"]) == 2
        assert all(request["response_format"]["type"] == "json_schema"
                   for request in requests)
        generation_branches = (requests[0]["response_format"]["json_schema"]["schema"]
                               ["oneOf"][1]["properties"]["calls"]["items"]["oneOf"])
        assert all(branch["properties"]["arguments"] == {"type": "object"}
                   for branch in generation_branches)
        assert list(json.loads((tmp_path / "capacity.json").read_text()).values()) == [2]


@pytest.mark.parametrize("bad_choice", [
    {"finish_reason": "length", "message": {"role": "assistant", "content": "{}"}},
    {"finish_reason": "stop", "message": {"role": "assistant", "content": "{bad"}},
    {"finish_reason": "stop", "message": {"role": "assistant", "content":
        json.dumps({"calls": [{"name": "not_a_tool", "arguments": {}}]})}},
])
def test_bad_json_action_never_executes_tool(bad_choice: dict[str, Any]) -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "bad", "choices": [bad_choice]})

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client)
        store = InMemoryStore()
        with SqliteSaver.from_conn_string(":memory:") as saver:
            with pytest.raises(IncompleteChatResponse):
                invoke_public_message(
                    build_agent(model, store, saver), model,
                    FoundationScope("run", "b0", "user", "bad"),
                    "Remember something.",
                )
        assert store.search(("langmem", "run", "b0", "user")) == []


def test_business_receipt_and_thread_checkpoint_survive_reopen(tmp_path: Path) -> None:
    actions: list[str] = []

    @tool
    def record_action(value: str) -> str:
        """Record the requested test action."""
        actions.append(value)
        return json.dumps({"done": value})

    responses = [
        _receipt({"calls": [{"name": "record_action", "arguments": {"value": "one"}}]}, "g1"),
        _receipt({"answer": "Done."}, "g2"),
        _receipt({"answer": "Still here."}, "g3"),
    ]

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    scope = FoundationScope("run", "b0", "user", "same-episode")
    checkpoint_path = tmp_path / "checkpoint.sqlite"
    capacity_path = tmp_path / "capacity.json"
    journal = BusinessActionJournal(tmp_path / "actions.json", ["record_action"])
    store = InMemoryStore()
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client, capacity_path=capacity_path)
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            agent = build_agent(model, store, saver, [record_action],
                                business_call_wrapper=journal)
            invoke_public_message(agent, model, scope, "Do the action.")
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            agent = build_agent(model, store, saver, [record_action],
                                business_call_wrapper=journal)
            messages = invoke_public_message(agent, model, scope, "What happened?")
    assert actions == ["one"]
    assert sum(isinstance(item, HumanMessage) for item in messages) == 2
    assert messages[-1].content == "Still here."
    assert len(journal.calls_for_thread(scope.config()["configurable"]["thread_id"])) == 1
    assert sorted(json.loads(capacity_path.read_text()).values()) == [1, 2]


def test_business_journal_replays_result_but_never_unknown_action(tmp_path: Path) -> None:
    path = tmp_path / "business.json"
    effects: list[str] = []

    def request(generation_id: str, call_id: str) -> ToolCallRequest:
        call = {"name": "record_action", "args": {"value": "same"}, "id": call_id}
        return ToolCallRequest(
            tool_call=call,
            tool=None,
            state={"messages": [AIMessage(content="", id=generation_id,
                                          tool_calls=[call])]},
            runtime=SimpleNamespace(config={"configurable": {"thread_id": "thread"}}),
        )

    def execute(item: ToolCallRequest) -> ToolMessage:
        effects.append(item.tool_call["id"])
        return ToolMessage(content="done", tool_call_id=item.tool_call["id"])

    first = request("generation-1", "call-1")
    assert BusinessActionJournal(path, ["record_action"])(first, execute).content == "done"
    assert BusinessActionJournal(path, ["record_action"])(first, execute).content == "done"
    assert effects == ["call-1"]
    second = request("generation-2", "call-2")
    BusinessActionJournal(path, ["record_action"])(second, execute)
    assert effects == ["call-1", "call-2"]

    def interrupted(item: ToolCallRequest) -> ToolMessage:
        effects.append(item.tool_call["id"])
        raise RuntimeError("outcome lost")

    unknown = request("generation-3", "call-3")
    with pytest.raises(RuntimeError, match="outcome lost"):
        BusinessActionJournal(path, ["record_action"])(unknown, interrupted)
    with pytest.raises(UnknownBusinessAction):
        BusinessActionJournal(path, ["record_action"])(unknown, execute)
    assert effects == ["call-1", "call-2", "call-3"]


def test_invalid_arguments_return_tool_error_then_graph_corrects(tmp_path: Path) -> None:
    effects: list[dict[str, Any]] = []

    def record_action(_world: Any, **arguments: Any) -> str:
        effects.append(arguments)
        return json.dumps({"recorded": arguments})

    business_tools = native_business_tools(None, [{
        "type": "function", "function": {
            "name": "record_action", "description": "Record a valid action.",
            "parameters": {"type": "object", "properties": {
                "value": {"type": "string"},
            }, "required": ["value"], "additionalProperties": False},
        },
    }], {"record_action": record_action})
    responses = [
        _receipt({"calls": [
            {"name": "manage_memory", "arguments": {"action": "search"}},
            {"name": "record_action", "arguments": {"wrong": "never execute"}},
            {"name": "record_action", "arguments": {"value": "execute once"}},
        ]}, "invalid-first"),
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "content": "likes ramen",
        }}]}, "corrected"),
        _receipt({"answer": "Saved."}, "final"),
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client, capacity_path=tmp_path / "capacity.json")
        store = InMemoryStore()
        journal = BusinessActionJournal(tmp_path / "business.json", ["record_action"])
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver, business_tools,
                                business_call_wrapper=journal)
            messages = invoke_public_message(
                agent, model, FoundationScope("run", "b0", "user", "episode"),
                "Record and remember correctly.",
            )
    results = [message for message in messages if isinstance(message, ToolMessage)]
    assert [result.tool_call_id for result in results] == [
        "invalid-first:tool:0", "invalid-first:tool:1", "invalid-first:tool:2",
        "corrected:tool:0",
    ]
    assert [result.status for result in results] == ["error", "error", "success", "success"]
    assert "search" in str(results[0].content)
    assert "value" in str(results[1].content)
    assert effects == [{"value": "execute once"}]
    assert len(store.search(("langmem", "run", "b0", "user"))) == 1
    assert messages[-1].content == "Saved."
    assert len(requests) == 3
    assert [message["tool_call_id"] for message in requests[1]["messages"]
            if message["role"] == "tool"] == [
                "invalid-first:tool:0", "invalid-first:tool:1", "invalid-first:tool:2",
            ]


def test_upstream_manage_search_preserves_public_null_and_id_behavior() -> None:
    class FixedEmbeddings(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] if "ramen" in text or "noodle" in text else [0.0, 1.0]
                    for text in texts]

        def embed_query(self, text: str) -> list[float]:
            return self.embed_documents([text])[0]

    namespace = ("run", "b0", "user")
    store = InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                 "fields": ["content"]})
    manage = create_manage_memory_tool(namespace=namespace, store=store)
    search = create_search_memory_tool(namespace=namespace, store=store)
    null_id = manage.invoke({"action": "create"}).split()[-1]
    assert store.get(namespace, null_id).value == {"content": None}
    saved_id = manage.invoke({"content": "likes ramen"}).split()[-1]
    hits = json.loads(search.invoke({"query": "noodle preference", "limit": 1}))
    assert hits[0]["key"] == saved_id
    unknown_id = str(uuid.uuid4())
    assert manage.invoke({"action": "update", "id": unknown_id,
                          "content": "likes soba"}) == f"updated memory {unknown_id}"
    assert store.get(namespace, unknown_id).value == {"content": "likes soba"}
    assert manage.invoke({"action": "delete", "id": unknown_id}) == (
        f"Deleted memory {unknown_id}"
    )
    assert store.get(namespace, unknown_id) is None
