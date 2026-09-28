"""Small offline checks for the new transport, public tools and recovery boundary."""

from __future__ import annotations

import asyncio
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
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.store.memory import InMemoryStore
from langmem import create_manage_memory_tool, create_search_memory_tool

from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    FoundationScope,
    build_agent,
    invoke_public_message,
)
from milai_lab.baselines.langmem_strict_tools import create_strict_manage_memory_tool
from milai_lab.harness.contextual_artifacts import write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.history import HistoryAccess
from milai_lab.methods.local_state_attention.writers import (
    create_writer_tools,
    execute_writes,
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
        assert all("read_history" not in json.dumps(request) for request in requests)
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


def test_read_history_tool_is_opt_in_and_uses_same_host_action_envelope(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    root.mkdir()
    write_json(root / "run_manifest.json", {"identity": {
        "run_id": "run", "arm_id": "history"}})
    write_json(root / "phase-progress.json", {"messages": {}})
    responses = [
        _receipt({"calls": [{"name": "read_history", "arguments": {
            "cursor": 0, "max_bytes": 1024}}]}, "read"),
        _receipt({"answer": "No prior turns."}, "final"),
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client)
        store = InMemoryStore()
        history = HistoryAccess(root, StateScope("run", "history", "user"),
                                LocalStateBank(store), lambda _session: None,
                                lambda session: session, page_max_bytes=16384)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, store, saver, history_access=history), model,
                FoundationScope("run", "history", "user", "episode"), "Read prior turns.")
    tools = [branch["properties"]["name"]["const"] for branch in requests[0][
        "response_format"]["json_schema"]["schema"]["oneOf"][1]["properties"][
            "calls"]["items"]["oneOf"]]
    assert tools == ["manage_memory", "search_memory", "read_history"]
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1 and tool_messages[0].status == "success"
    assert json.loads(str(tool_messages[0].content))["status"] == "OK"
    assert messages[-1].content == "No prior turns."


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


@pytest.mark.parametrize("contract", ["native", "strict"])
def test_native_manage_conditional_ids_return_errors_then_recover(
    tmp_path: Path, contract: str,
) -> None:
    class CountingStore(InMemoryStore):
        def __init__(self) -> None:
            super().__init__()
            self.writes: list[str] = []

        def put(self, namespace: Any, key: str, value: Any, **kwargs: Any) -> None:
            self.writes.append(key)
            super().put(namespace, key, value, **kwargs)

        def delete(self, namespace: Any, key: str) -> None:
            self.writes.append(key)
            super().delete(namespace, key)

    responses = [
        _receipt({"calls": [
            {"name": "manage_memory", "arguments": {"action": "update",
                                                     "content": "do not write"}},
            {"name": "manage_memory", "arguments": {"action": "delete"}},
            {"name": "manage_memory", "arguments": {"action": "create",
                                                     "id": str(uuid.uuid4()),
                                                     "content": "do not write"}},
        ]}, "invalid"),
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "create", "content": "saved after errors"}}]}, "valid"),
        _receipt({"answer": "Saved."}, "final"),
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client)
        store = CountingStore()
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, store, saver, memory_contract=contract), model,
                FoundationScope("run", "b0", "user", "episode"), "Remember correctly.")
    results = [message for message in messages if isinstance(message, ToolMessage)]
    assert [result.status for result in results] == ["error", "error", "error", "success"]
    assert all("validation error" in str(result.content) for result in results[:3])
    assert len(store.writes) == 1
    assert len(store.search(("langmem", "run", "b0", "user"))) == 1
    assert messages[-1].content == "Saved."
    assert len(requests) == 3
    assert len([row for row in requests[1]["messages"] if row["role"] == "tool"]) == 3


def test_external_manage_name_does_not_get_native_conditions(tmp_path: Path) -> None:
    @tool
    def manage_memory(action: str) -> str:
        """Handle an external memory action."""
        return f"external {action}"

    responses = [
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "update"}}]}, "external"),
        _receipt({"answer": "External action completed."}, "final"),
    ]

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, InMemoryStore(), saver, memory_tools=[manage_memory]),
                model, FoundationScope("run", "b0", "user", "episode"), "Call external.")
    results = [message for message in messages if isinstance(message, ToolMessage)]
    assert len(results) == 1 and results[0].status == "success"
    assert results[0].content == "external update"


@pytest.mark.parametrize("contract", ["native", "strict"])
def test_native_manage_store_value_error_is_not_converted(
    tmp_path: Path, contract: str,
) -> None:
    class BrokenStore(InMemoryStore):
        def put(self, *_args: Any, **_kwargs: Any) -> None:
            raise ValueError("store write failed")

    responses = [_receipt({"calls": [{"name": "manage_memory", "arguments": {
        "action": "create", "content": "will fail"}}]}, "broken")]

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            with pytest.raises(ValueError, match="store write failed"):
                invoke_public_message(
                    build_agent(model, BrokenStore(), saver,
                                memory_contract=contract), model,
                    FoundationScope("run", "b0", "user", "episode"), "Remember this.")


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


def test_agent_native_unknown_update_still_upserts(tmp_path: Path) -> None:
    unknown_id = str(uuid.uuid4())
    responses = [
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "update", "id": unknown_id, "content": "proposed memory"}}]}, "update"),
        _receipt({"answer": "Done."}, "final"),
    ]

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client)
        store = InMemoryStore()
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, store, saver), model,
                FoundationScope("run", "native", "user", "episode"), "Update memory.")
    namespace = ("langmem", "run", "native", "user")
    assert store.get(namespace, unknown_id).value == {"content": "proposed memory"}
    receipts = [row for row in messages if isinstance(row, ToolMessage)]
    assert len(receipts) == 1
    assert receipts[0].status == "success"
    assert receipts[0].content == f"updated memory {unknown_id}"


def test_agent_strict_rejects_unknown_update_then_accepts_create(tmp_path: Path) -> None:
    unknown_id = str(uuid.uuid4())
    namespace = ("langmem", "run", "strict", "user")
    store = InMemoryStore()
    store.put(("langmem", "run", "strict", "other"), unknown_id,
              {"content": "other user's memory"})
    responses = [
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "update", "id": unknown_id, "content": "proposed memory"}}]}, "update"),
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "create", "content": "valid memory"}}]}, "create"),
        _receipt({"answer": "Done."}, "final"),
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        if len(requests) == 2:
            assert store.search(namespace) == []
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, store, saver, memory_contract="strict"), model,
                FoundationScope("run", "strict", "user", "episode"), "Update memory.")
    receipts = [row for row in messages if isinstance(row, ToolMessage)]
    assert [row.status for row in receipts] == ["error", "success"]
    assert [json.loads(str(row.content))["status"] for row in receipts] == [
        "not_found", "created"]
    assert store.get(namespace, unknown_id) is None
    assert store.get(("langmem", "run", "strict", "other"), unknown_id).value == {
        "content": "other user's memory"}
    assert len(store.search(namespace)) == 1
    assert len(requests) == 3
    assert [row["tool_call_id"] for row in requests[1]["messages"]
            if row["role"] == "tool"] == ["update:tool:0"]


def test_agent_strict_content_required_rejects_real_toolnode_then_recovers(
    tmp_path: Path,
) -> None:
    memory_id = str(uuid.uuid4())
    namespace = ("langmem", "run", "strict", "user")
    store = InMemoryStore()
    store.put(namespace, memory_id, {"content": "original"})
    responses = [
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "update", "id": memory_id}}]}, "update-omitted"),
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "update", "id": memory_id, "content": None}}]}, "update-null"),
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "create"}}]}, "create-omitted"),
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "create", "content": None}}]}, "create-null"),
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "update", "id": memory_id, "content": "corrected"}}]}, "valid"),
        _receipt({"answer": "Actual receipt observed."}, "final"),
    ]
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        if 2 <= len(requests) <= 5:
            assert store.get(namespace, memory_id).value == {"content": "original"}
            assert len(store.search(namespace)) == 1
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, store, saver, memory_contract="strict"), model,
                FoundationScope("run", "strict", "user", "episode"), "Update memory.")
    receipts = [row for row in messages if isinstance(row, ToolMessage)]
    assert len(requests) == 6 and len(receipts) == 5
    assert [row.status for row in receipts] == ["error"] * 4 + ["success"]
    assert [json.loads(str(row.content)).get("reason") for row in receipts[:4]] == [
        "content_required"] * 4
    assert json.loads(str(receipts[-1].content))["status"] == "updated"
    assert [(row.key, row.value) for row in store.search(namespace)] == [
        (memory_id, {"content": "corrected"})]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_strict_crud_scope_noop_and_native_parameters(asynchronous: bool) -> None:
    class CountingStore(InMemoryStore):
        writes = 0
        deletes = 0

        def put(self, *args: Any, **kwargs: Any) -> None:
            self.writes += 1
            super().put(*args, **kwargs)

        async def aput(self, *args: Any, **kwargs: Any) -> None:
            self.writes += 1
            await super().aput(*args, **kwargs)

        def delete(self, *args: Any, **kwargs: Any) -> None:
            self.deletes += 1
            super().delete(*args, **kwargs)

        async def adelete(self, *args: Any, **kwargs: Any) -> None:
            self.deletes += 1
            await super().adelete(*args, **kwargs)

    store = CountingStore()
    native = create_manage_memory_tool(namespace=("langmem", "{user_id}"))
    strict = create_strict_manage_memory_tool(("langmem", "{user_id}"), store)
    assert (convert_to_openai_tool(native)["function"]["parameters"] ==
            convert_to_openai_tool(strict)["function"]["parameters"])
    assert "Create and update require non-null content." in strict.description

    def call(arguments: dict[str, Any], user: str, ordinal: int) -> ToolMessage:
        payload = {"type": "tool_call", "name": "manage_memory",
                   "args": arguments, "id": f"call-{ordinal}"}
        config = {"configurable": {"user_id": user}}
        return (asyncio.run(strict.ainvoke(payload, config=config)) if asynchronous
                else strict.invoke(payload, config=config))

    absent = str(uuid.uuid4())
    for ordinal, arguments in enumerate(({}, {"action": "create"},
                                         {"action": "create", "content": None}), 10):
        rejected = call(arguments, "alice", ordinal)
        assert rejected.status == "error"
        assert json.loads(str(rejected.content))["reason"] == "content_required"
    assert store.writes == 0 and store.deletes == 0
    assert store.search(("langmem", "alice")) == []
    missing = call({"action": "update", "id": absent, "content": "proposal"}, "alice", 0)
    assert missing.status == "error"
    assert json.loads(str(missing.content)) == {
        "ok": False, "status": "not_found", "id": absent}
    assert store.writes == 0
    created = call({"action": "create", "content": "first"}, "alice", 1)
    memory_id = json.loads(str(created.content))["id"]
    assert created.status == "success"
    assert store.get(("langmem", "alice"), memory_id).value == {"content": "first"}
    assert store.writes == 1
    for ordinal, arguments in enumerate((
        {"action": "update", "id": memory_id},
        {"action": "update", "id": memory_id, "content": None},
    ), 20):
        rejected = call(arguments, "alice", ordinal)
        assert rejected.status == "error"
        assert json.loads(str(rejected.content))["reason"] == "content_required"
    assert store.writes == 1 and store.deletes == 0
    assert store.get(("langmem", "alice"), memory_id).value == {"content": "first"}
    cross_owner = call({"action": "update", "id": memory_id,
                        "content": "wrong owner"}, "bob", 2)
    assert cross_owner.status == "error"
    assert store.writes == 1
    same = call({"action": "update", "id": memory_id, "content": "first"}, "alice", 3)
    assert json.loads(str(same.content))["status"] == "no_change"
    assert store.writes == 1
    changed = call({"action": "update", "id": memory_id, "content": "second"},
                   "alice", 4)
    assert json.loads(str(changed.content))["status"] == "updated"
    assert store.writes == 2
    search = create_search_memory_tool(namespace=("langmem", "{user_id}"), store=store)
    hits = json.loads(search.invoke({"query": "second", "limit": 3},
                                   config={"configurable": {"user_id": "alice"}}))
    assert [(hit["key"], hit["value"]) for hit in hits] == [
        (memory_id, {"content": "second"})]
    assert json.loads(search.invoke({"query": "second", "limit": 3},
                                    config={"configurable": {"user_id": "bob"}})) == []
    deleted = call({"action": "delete", "id": memory_id}, "alice", 5)
    assert json.loads(str(deleted.content))["status"] == "deleted"
    assert store.deletes == 1
    missing_again = call({"action": "delete", "id": memory_id}, "alice", 6)
    assert missing_again.status == "error"
    assert store.deletes == 1
    assert store.get(("langmem", "alice"), memory_id) is None


def test_boundary_executor_uses_same_strict_content_guard() -> None:
    store = InMemoryStore()
    scope = StateScope("run", "boundary", "alice")
    memory_id = str(uuid.uuid4())
    namespace = ("langmem", "run", "boundary", "alice")
    store.put(namespace, memory_id, {"content": "original"})
    toolset = create_writer_tools(LocalStateBank(store), MEMORY_NAMESPACE)
    config = {"configurable": {"foundation_run_id": scope.run_id,
                               "arm_id": scope.arm_id, "user_id": scope.user_id,
                               "workspace_id": scope.workspace_id}}
    result = execute_writes(toolset, [{"name": "manage_memory", "arguments": {
        "action": "update", "id": memory_id}}], config=config, scope=scope,
        batch_id="boundary", event_ids=set())
    assert result.status == "PARTIAL_REJECTED"
    assert result.receipts[0].status == "error"
    assert json.loads(str(result.receipts[0].content))["reason"] == "content_required"
    assert store.get(namespace, memory_id).value == {"content": "original"}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_strict_store_failures_propagate(asynchronous: bool) -> None:
    class BrokenStore(InMemoryStore):
        def get(self, *_args: Any, **_kwargs: Any) -> Any:
            raise ValueError("store read failed")

        async def aget(self, *_args: Any, **_kwargs: Any) -> Any:
            raise ValueError("store read failed")

    strict = create_strict_manage_memory_tool(("langmem", "{user_id}"), BrokenStore())
    payload = {"type": "tool_call", "name": "manage_memory", "id": "call",
               "args": {"action": "update", "id": str(uuid.uuid4()), "content": "x"}}
    config = {"configurable": {"user_id": "alice"}}
    with pytest.raises(ValueError, match="store read failed"):
        if asynchronous:
            asyncio.run(strict.ainvoke(payload, config=config))
        else:
            strict.invoke(payload, config=config)

    class BrokenDeleteStore(InMemoryStore):
        def delete(self, *_args: Any, **_kwargs: Any) -> None:
            raise ValueError("store delete failed")

        async def adelete(self, *_args: Any, **_kwargs: Any) -> None:
            raise ValueError("store delete failed")

    delete_store = BrokenDeleteStore()
    memory_id = str(uuid.uuid4())
    delete_store.put(("langmem", "alice"), memory_id, {"content": "saved"})
    deleting = create_strict_manage_memory_tool(("langmem", "{user_id}"), delete_store)
    payload["args"] = {"action": "delete", "id": memory_id}
    with pytest.raises(ValueError, match="store delete failed"):
        if asynchronous:
            asyncio.run(deleting.ainvoke(payload, config=config))
        else:
            deleting.invoke(payload, config=config)
    assert delete_store.get(("langmem", "alice"), memory_id) is not None


def test_strict_conflicts_with_external_memory_tools(tmp_path: Path) -> None:
    @tool
    def manage_memory(action: str) -> str:
        """An external memory tool."""
        return action

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock")) as client:
        model = VLLMChatModel(client=client)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            with pytest.raises(ValueError, match="LANGMEM_STRICT_CUSTOM_MEMORY_TOOLS_CONFLICT"):
                build_agent(model, InMemoryStore(), saver, memory_tools=[manage_memory],
                            memory_contract="strict")
