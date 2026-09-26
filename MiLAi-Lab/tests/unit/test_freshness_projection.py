"""Narrow zero-model checks for request-copy item quarantine and B1 delivery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("langmem")

from langchain_core.embeddings import Embeddings
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import (
    FoundationScope,
    build_agent,
    invoke_public_message,
    resume_public_message,
)
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import (
    ObservedStore,
    RevisionSidecar,
    canonical_json,
    content_identity,
)
from milai_lab.methods.freshness_projection.controller import ProjectionController
from milai_lab.methods.freshness_projection.projection import (
    SOURCE_AUTHORITY,
    project_current_evidence,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_foundation import BusinessActionJournal
from milai_lab.runners.langmem_m1_mechanism import _fixture_memory_effect


class FixedEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


class Stub:
    client = type("Client", (), {"emit": None})()


def _receipt(action: dict[str, Any], identity: str) -> dict[str, Any]:
    return {"id": identity, "model": "mock", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


def test_current_body_delivery_requires_same_namespace_and_item(tmp_path: Path) -> None:
    user_ns = ["langmem", "run", "a2_quarantine", "user"]
    child_ns = [*user_ns, "child"]
    old = {"namespace": user_ns, "key": "same-id", "value": {"content": "old"}}
    child = {"namespace": child_ns, "key": "same-id", "value": {"content": "child"}}
    messages = []
    searches = []
    for index, item in enumerate((old, child)):
        body = json.dumps([item], ensure_ascii=False, separators=(",", ":"))
        messages.append({"role": "tool", "tool_call_id": f"call-{index}", "content": body})
        searches.append({"thread_id": "thread", "call_id": f"call-{index}",
                         "search_id": f"search-{index}", "status": "returned",
                         "tool_message_body_ref": content_identity(body)[2],
                         "returned_json": json.dumps([{
                             "namespace": item["namespace"], "memory_id": item["key"],
                             "revision": index + 1, "revision_status": "EXACT",
                             "body_ref": content_identity(item["value"]["content"])[2],
                             "store_item": item,
                         }])})

    class Sidecar:
        def rows(self, table: str) -> list[dict[str, Any]]:
            assert table == "searches"
            return searches

        def latest_revision(self, namespace: tuple[str, ...], memory_id: str) -> dict[str, Any]:
            assert memory_id == "same-id"
            return {"revision": 2, "tombstone": 0}

    projection = project_current_evidence(messages, Sidecar(), "thread")  # type: ignore[arg-type]
    assert projection.items[0]["status"] == "SUPERSEDED"
    assert projection.items[0]["current_body_delivered"] is False
    assert projection.items[1]["status"] == "CURRENT"
    assert projection.messages[1] == messages[1]
    assert "old" not in projection.messages[0]["content"]
    assert "old" in messages[0]["content"]


def test_exact_refresh_deduplicates_and_keeps_uncertain_reads_quarantined() -> None:
    namespace = ("langmem", "run", "a3_exact_refresh", "user")
    store = InMemoryStore()
    store.put(namespace, "x", {"content": "old-4"})
    old = store.get(namespace, "x")
    assert old is not None
    store.put(namespace, "x", {"content": "new-8"})
    current = store.get(namespace, "x")
    assert current is not None
    latest = {"revision": 2, "tombstone": 0,
              "post_item_json": canonical_json(current.dict())}

    def search(call_id: str, item: dict[str, Any], revision: int) -> tuple[
        dict[str, Any], dict[str, Any]]:
        body = json.dumps([item], ensure_ascii=False, separators=(",", ":"))
        message = {"role": "tool", "tool_call_id": call_id, "content": body}
        row = {"thread_id": "thread", "call_id": call_id,
               "search_id": call_id + ":search", "status": "returned",
               "tool_message_body_ref": content_identity(body)[2],
               "returned_json": json.dumps([{
                   "namespace": list(namespace), "memory_id": "x",
                   "revision": revision, "revision_status": "EXACT",
                   "body_ref": content_identity(item["value"]["content"])[2],
                   "store_item": item,
               }])}
        return message, row

    old_message, old_row = search("old", old.dict(), 1)
    duplicate, duplicate_row = search("duplicate", old.dict(), 1)
    current_message, current_row = search("current", current.dict(), 2)

    class Sidecar:
        def __init__(self, searches: list[dict[str, Any]]) -> None:
            self.searches = searches

        def rows(self, table: str) -> list[dict[str, Any]]:
            assert table == "searches"
            return self.searches

        def latest_revision(self, ns: tuple[str, ...], memory_id: str) -> dict[str, Any]:
            assert ns == namespace and memory_id == "x"
            return latest

    get_calls: list[tuple[tuple[str, ...], str]] = []
    reads: list[dict[str, Any]] = []

    def get(ns: tuple[str, ...], memory_id: str) -> Any:
        get_calls.append((ns, memory_id))
        return store.get(ns, memory_id, refresh_ttl=False)

    with_current = project_current_evidence(
        [old_message, current_message], Sidecar([old_row, current_row]),  # type: ignore[arg-type]
        "thread", get, reads.append)
    assert not get_calls and not reads
    assert with_current.items[0]["current_body_delivered"] is True
    assert with_current.messages[1] == current_message

    projected = project_current_evidence(
        [old_message, duplicate], Sidecar([old_row, duplicate_row]),  # type: ignore[arg-type]
        "thread", get, reads.append)
    assert get_calls == [(namespace, "x")]
    assert len(reads) == 1 and reads[0]["status"] == "BOUND_CURRENT"
    assert len(projected.exact_reads) == 1
    assert all(item["current_body_delivered"] for item in projected.items)
    assert all("new-8" in message["content"] and "old-4" not in message["content"]
               for message in projected.messages)

    store.put(namespace, "x", {"content": "unbound"})
    uncertain = project_current_evidence(
        [old_message], Sidecar([old_row]), "thread", get,  # type: ignore[arg-type]
        reads.append)
    assert reads[-1]["status"] == "UNKNOWN_BINDING"
    assert uncertain.items[0]["current_body_delivered"] is False
    assert "unbound" not in uncertain.messages[0]["content"]
    assert "withheld" in uncertain.messages[0]["content"]

    store.delete(namespace, "x")
    missing = project_current_evidence(
        [old_message], Sidecar([old_row]), "thread", get,  # type: ignore[arg-type]
        reads.append)
    assert reads[-1]["status"] == "UNKNOWN_NOT_FOUND"
    assert missing.items[0]["current_body_delivered"] is False

    def failing_get(ns: tuple[str, ...], memory_id: str) -> Any:
        raise RuntimeError("store unavailable")

    failed = project_current_evidence(
        [old_message], Sidecar([old_row]), "thread",  # type: ignore[arg-type]
        failing_get, reads.append)
    assert reads[-1]["status"] == "UNKNOWN_ERROR"
    assert reads[-1]["error_type"] == "RuntimeError"
    assert failed.items[0]["current_body_delivered"] is False


@pytest.mark.parametrize("arm", ["a2_quarantine", "a3_exact_refresh"])
def test_mixed_projection_actual_material_and_completed_replay(
    tmp_path: Path, arm: str,
) -> None:
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", arm)
    scope = FoundationScope("run", arm, "user", "episode")
    namespace = ("langmem", "run", arm, "user")
    inner = InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                 "fields": ["content"]})
    store = ObservedStore(inner, observer)
    seeds = {}
    for name, content in (("changed", "old-4-body"), ("current", "current-y-body"),
                          ("deleted", "deleted-z-body"), ("same", "same-w-body")):
        seeds[name] = _fixture_memory_effect(
            "seed:" + name, {"action": "create", "content": content},
            scope, store, observer, tmp_path, Stub(),  # type: ignore[arg-type]
        )["memory_id"]
    inner.put(namespace, "imported", {"content": "unknown-imported-body"})
    business: list[str] = []

    @tool
    def record(value: str) -> str:
        """Record the selected value."""
        business.append(value)
        return value

    journal = BusinessActionJournal(tmp_path / "journal.json", ["record"])
    wires: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def emit(event: dict[str, Any]) -> None:
        events.append(event)
        observer.capture_provider_event(event)

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        action = ({"calls": [{"name": "search_memory", "arguments": {
            "query": "body", "limit": 10}}]} if len(wires) == 1 else
                  {"answer": "Prior assistant thought old-4-body"} if len(wires) == 2 else
                  {"calls": [{"name": "record", "arguments": {"value": "done"}}]}
                  if len(wires) == 4 else {"answer": "pending"})
        return httpx.Response(200, json=_receipt(action, f"g{len(wires)}"))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond), emit=emit) as client:
        model = VLLMChatModel(client=client, observer=observer,
                              projection=ProjectionController(observer, emit,
                                                              arm=arm, store=store))
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver, [record],
                                business_call_wrapper=journal, observer=observer)
            invoke_public_message(agent, model, scope, "Find memories.")
            _fixture_memory_effect("update:changed", {
                "action": "update", "id": seeds["changed"], "content": "new-8-body"},
                scope, store, observer, tmp_path, Stub(),  # type: ignore[arg-type]
            )
            _fixture_memory_effect("update:same", {
                "action": "update", "id": seeds["same"], "content": "same-w-body"},
                scope, store, observer, tmp_path, Stub(),  # type: ignore[arg-type]
            )
            _fixture_memory_effect("delete:deleted", {
                "action": "delete", "id": seeds["deleted"]},
                scope, store, observer, tmp_path, Stub(),  # type: ignore[arg-type]
            )
            before_reads = sidecar.costs()["extra_store_reads"]
            invoke_public_message(agent, model, scope, "Continue.")
            assert sidecar.costs()["extra_store_reads"] == before_reads
            original = next(message for message in agent.get_state(scope.config()).values[
                "messages"] if isinstance(message, ToolMessage)
                and message.name == "search_memory")
            original_items = json.loads(original.content)
            request_tool = next(item for item in wires[2]["messages"]
                                if item["role"] == "tool")
            visible_items = json.loads(request_tool["content"])
            assert [item["key"] for item in visible_items] == [
                item["key"] for item in original_items]
            original_by_id = {item["key"]: item for item in original_items}
            visible_by_id = {item["key"]: item for item in visible_items}
            for name in ("changed", "same", "deleted"):
                old_value = original_by_id[seeds[name]]["value"]["content"]
                if name != "same" or arm == "a2_quarantine":
                    assert old_value not in request_tool["content"]
                if arm == "a3_exact_refresh" and name != "deleted":
                    assert visible_by_id[seeds[name]]["value"]["content"] == (
                        "new-8-body" if name == "changed" else "same-w-body")
                    assert visible_by_id[seeds[name]]["_version_projection"]["source"] == (
                        "public Store.get")
                else:
                    assert "withheld" in visible_by_id[seeds[name]]["value"]["content"]
                assert old_value in original.content
            for key in (seeds["current"], "imported"):
                assert visible_by_id[key] == original_by_id[key]
            assert SOURCE_AUTHORITY in wires[2]["messages"][0]["content"]
            assert any(item.get("role") == "assistant"
                       and item.get("content") == "Prior assistant thought old-4-body"
                       for item in wires[2]["messages"])
            assert "reconstruction" not in json.dumps(wires[2])
            projected_request = sidecar.rows("requests")[2]
            material = [row for row in sidecar.rows("request_material")
                        if row["request_id"] == projected_request["request_id"]]
            assert len(material) == 1 and material[0]["coverage"] == (
                "PROJECTED_REFRESHED" if arm == "a3_exact_refresh" else
                "PROJECTED_WITHHELD")
            event = [event for event in events
                     if event.get("event") == "freshness_projection"][-1]
            assert event["request_id"] == projected_request["request_id"]
            assert event["public_message_index"] == 1
            assert event["exact_store_reads"] == (2 if arm == "a3_exact_refresh" else 0)
            if arm == "a3_exact_refresh":
                reads = [row for row in events if row.get("event") == "freshness_exact_read"]
                assert len(reads) == 2
                assert {row["status"] for row in reads} == {"BOUND_CURRENT"}
                assert all(row["request_id"] == event["request_id"]
                           and row["provider_delivery"] is False for row in reads)
                assert {row["memory_id"] for row in reads} == {
                    seeds["changed"], seeds["same"]}
                assert event["actual_material"][original.tool_call_id]["coverage"] == (
                    "PROJECTED_REFRESHED")
            statuses = {item["memory_id"]: item["status"] for item in event["items"]}
            assert statuses == {seeds["changed"]: "SUPERSEDED",
                                seeds["same"]: "SUPERSEDED",
                                seeds["deleted"]: "DELETED",
                                seeds["current"]: "CURRENT", "imported": "UNKNOWN"}
            _fixture_memory_effect("update:current", {
                "action": "update", "id": seeds["current"], "content": "new-y-body"},
                scope, store, observer, tmp_path, Stub(),  # type: ignore[arg-type]
            )
            invoke_public_message(agent, model, scope, "Approve.")
            assert "current-y-body" not in json.dumps(wires[3])
            after = (len(wires), len(business), len(sidecar.rows("tool_calls")))
            replay = resume_public_message(agent, model, scope)
            assert replay[-1].content == "pending"
            assert after == (len(wires), len(business), len(sidecar.rows("tool_calls")))
    assert business == ["done"]
    sidecar.close()
