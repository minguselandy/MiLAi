"""One real upstream tool path with frozen, zero-network model receipts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

pytest.importorskip("langmem")

import langgraph.store.memory as memory_module
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.store.base import PutOp
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import FoundationScope, build_agent, invoke_public_message
from milai_lab.baselines.langmem_instrumentation import (
    CallContext,
    InstrumentationIncomplete,
    ProvenanceObserver,
)
from milai_lab.baselines.langmem_revision_store import (
    ObservedStore,
    RevisionSidecar,
    content_identity,
)
from milai_lab.harness.contextual_artifacts import Trace
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_foundation import BusinessActionJournal, UnknownBusinessAction


class FixedEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _receipt(action: dict[str, Any], identity: str) -> dict[str, Any]:
    return {"id": identity, "model": "mock", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


def test_real_tools_record_return_time_revision_and_actual_request(tmp_path: Path) -> None:
    memory_id = "00000000-0000-4000-8000-000000000001"
    responses = [
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "content": "ramen", "id": memory_id, "action": "update"}}]}, "g1"),
        _receipt({"calls": [{"name": "search_memory", "arguments": {
            "query": "food", "limit": 1}}, {"name": "manage_memory", "arguments": {
            "content": "soba", "id": memory_id, "action": "update"}}]}, "g2"),
        _receipt({"answer": "Done."}, "g3"),
    ]
    wire: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "b1")
    inner = InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                 "fields": ["content"]})
    store = ObservedStore(inner, observer)
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, store, saver, observer=observer), model,
                FoundationScope("run", "b1", "user", "episode"), "Remember food.",
            )
    observer.assert_healthy()
    revisions = sidecar.rows("revisions")
    assert [(row["revision"], row["actual_effect"], row["content_json"])
            for row in revisions] == [(1, "insert", '"ramen"'), (2, "update", '"soba"')]
    search = sidecar.rows("searches")[0]
    assert json.loads(search["returned_json"])[0]["revision"] == 1
    assert [row["status"] for row in sidecar.rows("requests")] == ["completed"] * 3
    assert {row["coverage"] for row in sidecar.rows("request_material")} == {"FULL"}
    assert len(sidecar.rows("request_material")) == 4
    assert messages[-1].content == "Done."
    assert inner.get(("langmem", "run", "b1", "user"), memory_id).value == {
        "content": "soba"}
    assert len(wire) == 3
    sidecar.close()


def test_null_body_identity_differs_from_string_null() -> None:
    assert content_identity(None) != content_identity("null")
    assert content_identity("") != content_identity(None)


def test_main_write_survives_sidecar_failure_but_cold_resume_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [_receipt({"calls": [{"name": "manage_memory", "arguments": {
        "content": "ramen"}}]}, "g1")]
    wire: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    path = tmp_path / "sidecar.sqlite"
    sidecar = RevisionSidecar(path)
    observer = ProvenanceObserver(sidecar, "run", "b1")
    inner = InMemoryStore()
    store = ObservedStore(inner, observer)

    def fail_after_main(*_: Any, **__: Any) -> None:
        raise OSError("sidecar write failed")

    monkeypatch.setattr(sidecar, "finish_operation", fail_after_main)
    scope = FoundationScope("run", "b1", "user", "episode")
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver, observer=observer)
            with pytest.raises(InstrumentationIncomplete):
                invoke_public_message(agent, model, scope, "Remember ramen.")
            snapshot = agent.get_state(scope.config())
            assert any(message.type == "tool" and
                       str(message.content).startswith("created memory ")
                       for message in snapshot.values["messages"])
    assert len(inner.search(("langmem", "run", "b1", "user"))) == 1
    assert len(wire) == 1
    assert sidecar.rows("operations")[0]["status"] == "started"
    sidecar.close()
    reopened = RevisionSidecar(path)
    with pytest.raises(InstrumentationIncomplete):
        ProvenanceObserver(reopened, "run", "b1").assert_healthy()
    reopened.close()


def test_planned_request_without_provider_receipt_is_unknown_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "sidecar.sqlite"
    sidecar = RevisionSidecar(path)
    sidecar.plan_request("request-1", "thread", 0, 1)
    assert sidecar.rows("requests")[0]["status"] == "planned_unknown"
    sidecar.close()
    reopened = RevisionSidecar(path)
    with pytest.raises(InstrumentationIncomplete):
        ProvenanceObserver(reopened, "run", "b1").assert_healthy()
    reopened.close()


def test_same_receipts_keep_control_and_b1_wire_world_and_checkpoint_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime(2026, 9, 26, tzinfo=tz)

    monkeypatch.setattr(memory_module, "datetime", FixedDateTime)
    memory_id = "00000000-0000-4000-8000-000000000002"
    actions = [
        _receipt({"calls": [
            {"name": "record_action", "arguments": {"value": "one"}},
            {"name": "manage_memory", "arguments": {
                "action": "update", "id": memory_id, "content": "ramen"}},
            {"name": "search_memory", "arguments": {"query": "food", "limit": 1}},
        ]}, "g1"),
        _receipt({"answer": "Done."}, "g2"),
        _receipt({"answer": "The action was recorded."}, "g3"),
    ]

    def run(name: str, instrumented: bool) -> dict[str, Any]:
        world: list[str] = []

        @tool
        def record_action(value: str) -> str:
            """Record an action in the parity world."""
            world.append(value)
            return json.dumps({"recorded": value})

        sent: list[dict[str, Any]] = []
        sent_wire: list[str] = []
        receipts = list(actions)

        def respond(request: httpx.Request) -> httpx.Response:
            raw = request.read()
            sent_wire.append(raw.decode("utf-8"))
            sent.append(json.loads(raw))
            return httpx.Response(200, json=receipts.pop(0))

        path = tmp_path / name
        path.mkdir()
        sidecar = RevisionSidecar(path / "instrumentation.sqlite") if instrumented else None
        observer = (ProvenanceObserver(sidecar, "parity", "logical")
                    if sidecar is not None else None)
        base_store = InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                          "fields": ["content"]})
        store = ObservedStore(base_store, observer) if observer is not None else base_store
        journal = BusinessActionJournal(path / "journal.json", ["record_action"])
        scope = FoundationScope("parity", "logical", "user", "episode")
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                        transport=httpx.MockTransport(respond),
                        emit=observer.capture_provider_event if observer else None) as client:
            model = VLLMChatModel(client=client, observer=observer)
            with SqliteSaver.from_conn_string(str(path / "checkpoint.sqlite")) as saver:
                agent = build_agent(model, store, saver, [record_action],
                                    business_call_wrapper=journal, observer=observer)
                first = invoke_public_message(agent, model, scope, "Record and remember.")
                second = invoke_public_message(agent, model, scope, "What happened?")
                checkpoint = agent.get_state(scope.config())
        result = {
            "wire": sent,
            "wire_bytes_utf8": sent_wire,
            "messages": [(message.type, message.content,
                          getattr(message, "status", None),
                          getattr(message, "tool_call_id", None)) for message in second],
            "first_answer": first[-1].content,
            "world": world,
            "journal": journal.calls_for_thread(scope.config()["configurable"]["thread_id"]),
            "store": [item.dict() for item in base_store.search(
                ("langmem", "parity", "logical", "user"), limit=1000)],
            "checkpoint_turns": sum(message.type == "human"
                                    for message in checkpoint.values["messages"]),
        }
        if observer is not None:
            observer.assert_healthy()
            assert len(sidecar.rows("searches")) == 1  # Audit Store.search was excluded.
            assert len(sidecar.rows("observations")) == 3  # Two users, one business result.
            sidecar.close()
        return result

    control = run("control", False)
    instrumented = run("instrumented", True)
    assert instrumented == control
    assert control["world"] == ["one"]
    assert control["checkpoint_turns"] == 2


def test_upstream_effect_matrix_and_same_body_different_revision(tmp_path: Path) -> None:
    memory_id = "00000000-0000-4000-8000-000000000003"
    absent_id = "00000000-0000-4000-8000-000000000004"

    def manage(action: str, content: Any, identity: str = memory_id) -> dict[str, Any]:
        return {"name": "manage_memory", "arguments": {
            "action": action, "content": content, "id": identity}}

    responses = [
        _receipt({"calls": [
            manage("update", "ramen"),
            manage("update", "ramen"),
            manage("update", "soba"),
            manage("update", "ramen"),
            {"name": "search_memory", "arguments": {"query": "food", "limit": 1}},
            manage("delete", None, absent_id),
            manage("delete", None),
            manage("update", "ramen"),
            manage("update", None),
        ]}, "g1"),
        _receipt({"answer": "Done."}, "g2"),
    ]

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "b1")
    inner = InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                 "fields": ["content"]})
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, ObservedStore(inner, observer), saver, observer=observer),
                model, FoundationScope("run", "b1", "user", "episode"), "Exercise effects.",
            )
    observer.assert_healthy()
    revisions = sidecar.rows("revisions")
    assert [row["revision"] for row in revisions] == list(range(1, 8))
    assert [row["actual_effect"] for row in revisions] == [
        "insert", "update", "update", "update", "delete", "recreate", "update"]
    assert revisions[1]["content_unchanged"] == 1
    assert revisions[0]["body_ref"] == revisions[3]["body_ref"]
    assert revisions[0]["revision"] != revisions[3]["revision"]
    assert revisions[4]["tombstone"] == 1 and revisions[4]["body_ref"] is None
    assert revisions[6]["tombstone"] == 0
    assert revisions[6]["content_kind"] == "NoneType"
    assert all(row["source_refs_json"] is None and
               row["source_status"] == "UNKNOWN_NOT_DECLARED" for row in revisions)
    assert any(row["memory_id"] == absent_id and row["actual_effect"] == "none"
               for row in sidecar.rows("operations"))
    assert json.loads(sidecar.rows("searches")[0]["returned_json"])[0]["revision"] == 4
    assert inner.get(("langmem", "run", "b1", "user"), memory_id).value == {
        "content": None}
    assert messages[-1].content == "Done."
    sidecar.close()


def test_business_journal_key_replay_and_unknown_are_linked_without_reexecution(
    tmp_path: Path,
) -> None:
    scope = FoundationScope("run", "b1", "user", "episode")
    thread_id = scope.config()["configurable"]["thread_id"]
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "b1")
    observer.begin_public_message(scope, 0, "Do the action.")
    journal = BusinessActionJournal(tmp_path / "journal.json", ["record_action"])
    effects: list[str] = []

    def request(generation_id: str, call_id: str) -> ToolCallRequest:
        call = {"name": "record_action", "args": {"value": "one"}, "id": call_id}
        return ToolCallRequest(
            tool_call=call, tool=None,
            state={"messages": [AIMessage(content="", id=generation_id,
                                           tool_calls=[call])]},
            runtime=SimpleNamespace(config={"configurable": {"thread_id": thread_id}}),
        )

    def body(item: ToolCallRequest) -> ToolMessage:
        effects.append(item.tool_call["id"])
        return ToolMessage(content="done", tool_call_id=item.tool_call["id"])

    first = request("generation-1", "call-1")
    for _ in range(2):
        observer.run_tool(first, lambda item: journal(item, body), journal)
    assert effects == ["call-1"]
    entry = journal.calls_for_thread(thread_id)[0]
    call_row = sidecar.rows("tool_calls")[0]
    assert call_row["call_key"] == hashlib.sha256(json.dumps(
        [thread_id, "generation-1", "call-1"], ensure_ascii=False,
    ).encode()).hexdigest()
    assert entry["status"] == call_row["journal_status"] == "complete"
    assert call_row["attempts"] == 1 and call_row["deliveries"] == 2
    assert sidecar.rows("observations")[1]["delivery_count"] == 2

    def interrupted(item: ToolCallRequest) -> ToolMessage:
        effects.append(item.tool_call["id"])
        raise RuntimeError("outcome unknown")

    unknown = request("generation-2", "call-2")
    with pytest.raises(RuntimeError, match="outcome unknown"):
        observer.run_tool(unknown, lambda item: journal(item, interrupted), journal)
    with pytest.raises(UnknownBusinessAction):
        observer.run_tool(unknown, lambda item: journal(item, body), journal)
    assert effects == ["call-1", "call-2"]
    assert len(sidecar.rows("observations")) == 2
    sidecar.close()


def test_observation_event_ids_and_provider_send_statuses(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "b1")
    scope = FoundationScope("run", "b1", "user", "episode")
    observer.begin_public_message(scope, 0, "same")
    observer.begin_public_message(scope, 1, "same")
    observer.begin_public_message(scope, 1, "same")  # Checkpoint resume.
    observations = sidecar.rows("observations")
    assert len(observations) == 2
    assert observations[0]["observation_id"] != observations[1]["observation_id"]
    assert observations[0]["content_sha256"] == observations[1]["content_sha256"]
    assert [row["delivery_count"] for row in observations] == [1, 1]

    thread_id = scope.config()["configurable"]["thread_id"]
    key = f"{thread_id}:1"
    request = {"messages": [{"role": "user", "content": "same"}], "model": "mock"}
    with observer.request_scope(key, 1):
        observer.capture_provider_event({
            "event": "vllm_response", "path": "chat/completions",
            "request": request, "receipt": {"id": "g1"},
        }, {"path": str(tmp_path / "trace.jsonl"), "byte_offset": 42,
            "record_sha256": "trace-sha"})
    with observer.request_scope(key, 2):
        observer.capture_provider_event({
            "event": "vllm_budget_rejected", "path": "chat/completions",
            "request_sent": False,
        })
    with observer.request_scope(key, 3):
        observer.capture_provider_event({
            "event": "vllm_error", "path": "chat/completions",
            "request": request, "exception": {"type": "ConnectError"},
        })
    with observer.request_scope(key, 4):
        observer.capture_provider_event({
            "event": "vllm_error", "path": "chat/completions",
            "request": request, "http_status": 400,
            "exception": {"type": "HTTPStatusError"},
        })
    rows = sidecar.rows("requests")
    assert [row["status"] for row in rows] == ["completed", "not_sent", "unknown", "error"]
    assert rows[0]["request_json"] is None and rows[0]["trace_byte_offset"] == 42
    assert rows[0]["request_object_sha256"] == hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode()).hexdigest()
    assert rows[1]["request_object_sha256"] is None
    observer.assert_healthy()
    sidecar.close()


def test_formal_trace_reference_resolves_exact_request(tmp_path: Path) -> None:
    cli = run_path(str(Path(__file__).resolve().parents[2] /
                       "tools/run_langmem_provenance.py"))
    read_sidecar, trace_emit = cli["_read_sidecar"], cli["_trace_emit"]
    path = tmp_path / "sidecar.sqlite"
    sidecar = RevisionSidecar(path)
    observer = ProvenanceObserver(sidecar, "run", "b1")
    scope = FoundationScope("run", "b1", "user", "episode")
    observer.begin_public_message(scope, 0, "hello")
    trace = Trace(tmp_path / "trace.jsonl", "v0")
    request = {"model": "mock", "messages": [{"role": "user", "content": "hello"}]}
    emit = trace_emit(trace, observer)
    key = f"{scope.config()['configurable']['thread_id']}:0"
    with observer.request_scope(key, 1):
        emit({"event": "vllm_response", "path": "chat/completions",
              "request": request, "receipt": {"id": "g1"}})
    row = read_sidecar(path, "requests", [], resolve_request=True)[0]
    assert row["request_json"] is None
    assert row["resolved_request"] == request
    assert row["trace_byte_offset"] == 0
    trace.path.write_text("changed\n")
    with pytest.raises(ValueError, match="B1_QUERY_TRACE_REF_CHANGED"):
        read_sidecar(path, "requests", [], resolve_request=True)
    sidecar.close()


def test_uncertain_store_boundaries_and_actual_reexecution_never_invent_history(
    tmp_path: Path,
) -> None:
    namespace = ("langmem", "run", "b1", "user")
    memory_id = "00000000-0000-4000-8000-000000000005"

    def pair(name: str) -> tuple[RevisionSidecar, ProvenanceObserver]:
        sidecar = RevisionSidecar(tmp_path / f"{name}.sqlite")
        return sidecar, ProvenanceObserver(sidecar, "run", "b1")

    def put_in_call(
        observer: ProvenanceObserver, store: ObservedStore,
        content: str, attempt: int,
    ) -> None:
        context = CallContext(
            "call", "thread", "generation", "tool", "manage_memory",
            {"action": "update"}, attempt,
        )
        token = observer._call.set(context)
        try:
            store.put(namespace, memory_id, {"content": content})
        finally:
            observer._call.reset(token)

    class FirstReadFails(InMemoryStore):
        failed = False

        def get(self, namespace: tuple[str, ...], key: str,
                *, refresh_ttl: bool | None = None) -> Any:
            if not self.failed:
                self.failed = True
                raise OSError("pre-read unavailable")
            return super().get(namespace, key, refresh_ttl=refresh_ttl)

    sidecar, observer = pair("pre-read")
    inner = FirstReadFails()
    put_in_call(observer, ObservedStore(inner, observer), "ramen", 1)
    assert inner.get(namespace, memory_id).value == {"content": "ramen"}
    assert sidecar.rows("revisions") == []
    assert sidecar.rows("operations")[0]["status"] == "binding_unknown"
    with pytest.raises(InstrumentationIncomplete):
        observer.assert_healthy()
    sidecar.close()

    class WriteThenRaise(InMemoryStore):
        def batch(self, ops: Any) -> Any:
            operations = list(ops)
            result = super().batch(operations)
            if any(isinstance(op, PutOp) for op in operations):
                raise RuntimeError("outcome hidden after commit")
            return result

    sidecar, observer = pair("write-unknown")
    inner = WriteThenRaise()
    with pytest.raises(RuntimeError, match="outcome hidden"):
        put_in_call(observer, ObservedStore(inner, observer), "ramen", 1)
    assert inner.get(namespace, memory_id).value == {"content": "ramen"}
    assert sidecar.rows("revisions") == []
    assert sidecar.rows("operations")[0]["status"] == "unknown"
    sidecar.close()
    reopened = RevisionSidecar(tmp_path / "write-unknown.sqlite")
    with pytest.raises(InstrumentationIncomplete):
        ProvenanceObserver(reopened, "run", "b1").assert_healthy()
    reopened.close()

    sidecar, observer = pair("imported-gap")
    inner = InMemoryStore()
    inner.put(namespace, memory_id, {"content": "before observer"})
    store = ObservedStore(inner, observer)
    put_in_call(observer, store, "observed", 1)
    assert sidecar.rows("revisions")[0]["history_status"] == "IMPORTED_UNKNOWN"
    inner.delete(namespace, memory_id)  # External gap in the observed chain.
    put_in_call(observer, store, "after gap", 2)
    assert len(sidecar.rows("revisions")) == 1
    assert sidecar.rows("operations")[-1]["status"] == "binding_unknown"
    assert inner.get(namespace, memory_id).value == {"content": "after gap"}
    sidecar.close()

    sidecar, observer = pair("reexecution")
    inner = InMemoryStore()
    store = ObservedStore(inner, observer)
    scope = FoundationScope("run", "b1", "user", "episode")
    observer.begin_public_message(scope, 0, "Remember twice.")
    thread_id = scope.config()["configurable"]["thread_id"]
    call = {"name": "manage_memory", "args": {"action": "update"}, "id": "tool"}
    request = ToolCallRequest(
        tool_call=call, tool=None,
        state={"messages": [AIMessage(content="", id="generation", tool_calls=[call])]},
        runtime=SimpleNamespace(config={"configurable": {"thread_id": thread_id}}),
    )

    def execute(_: ToolCallRequest) -> ToolMessage:
        store.put(namespace, memory_id, {"content": "same"})
        return ToolMessage(content="updated", tool_call_id="tool")

    observer.run_tool(request, execute)
    first = sidecar.rows("operations")[0]
    sidecar.finish_operation(
        first["operation_id"], None, None, deleted=False,
        extra_reads=0, before_known=True,
    )  # Already confirmed log delivery is idempotent.
    assert len(sidecar.rows("revisions")) == 1
    observer.run_tool(request, execute)  # The upstream write actually runs again.
    assert [row["revision"] for row in sidecar.rows("revisions")] == [1, 2]
    assert sidecar.rows("tool_calls")[0]["attempts"] == 2
    sidecar.close()

    sidecar, observer = pair("invalid-argument")
    responses = [
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "search", "content": "must not write"}}]}, "invalid"),
        _receipt({"answer": "The call was invalid."}, "final"),
    ]

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    inner = InMemoryStore()
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer)
        with SqliteSaver.from_conn_string(str(tmp_path / "invalid-checkpoint.sqlite")) as saver:
            messages = invoke_public_message(
                build_agent(model, ObservedStore(inner, observer), saver,
                            observer=observer), model,
                FoundationScope("run", "b1", "user", "invalid"), "Try invalid action.",
            )
    assert any(message.type == "tool" and message.status == "error"
               for message in messages)
    assert sidecar.rows("operations") == [] and sidecar.rows("revisions") == []
    assert inner.search(namespace) == []
    sidecar.close()
