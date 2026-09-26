"""Narrow zero-model checks for request-copy item quarantine and B1 delivery."""

from __future__ import annotations

import json
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
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import RECIPE_ID as B1_RECIPE_ID
from milai_lab.baselines.langmem_agent import (
    FoundationScope,
    build_agent,
    invoke_public_message,
    resume_public_message,
)
from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import (
    ObservedStore,
    RevisionSidecar,
    canonical_json,
    content_identity,
)
from milai_lab.datasets.merit import load_exposed_arc, load_frozen_arc
from milai_lab.methods.freshness_projection.controller import (
    SER_V21_RECIPE_ID,
    ProjectionController,
)
from milai_lab.methods.freshness_projection.identity import LAB
from milai_lab.methods.freshness_projection.lineage import (
    DERIVED_WITHHELD,
    project_derived_assistants,
)
from milai_lab.methods.freshness_projection.projection import (
    SOURCE_AUTHORITY,
    ProjectedRequest,
    project_current_evidence,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners import langmem_merit
from milai_lab.runners.langmem_diagnostic import run_frozen_diagnostics
from milai_lab.runners.langmem_foundation import BusinessActionJournal
from milai_lab.runners.langmem_m1_mechanism import (
    SearchResultRequestView,
    _fixture_memory_effect,
    run_mechanism,
)


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


def test_rank_bounded_refresh_uses_actual_search_order_and_exact_read_cap() -> None:
    namespace = ("langmem", "run", "a5_rank_bounded_rebase", "user")
    store = InMemoryStore()
    old: dict[str, dict[str, Any]] = {}
    latest: dict[str, dict[str, Any]] = {}
    for name in ("x", "y", "current", "deleted"):
        store.put(namespace, name, {"content": f"old-{name}"})
        item = store.get(namespace, name)
        assert item is not None
        old[name] = item.dict()
        if name == "deleted":
            latest[name] = {"revision": 2, "tombstone": 1}
            store.delete(namespace, name)
        elif name == "current":
            latest[name] = {"revision": 1, "tombstone": 0,
                            "post_item_json": canonical_json(item.dict())}
        else:
            store.put(namespace, name, {"content": f"new-{name}"})
            item = store.get(namespace, name)
            assert item is not None
            latest[name] = {"revision": 2, "tombstone": 0,
                            "post_item_json": canonical_json(item.dict())}
    unknown = {"namespace": list(namespace), "key": "unknown",
               "value": {"content": "unversioned"}}

    def search(call_id: str, names: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
        items = [unknown if name == "unknown" else old[name] for name in names]
        body = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        entries = [{"namespace": list(namespace), "memory_id": name,
                    "revision": None if name == "unknown" else 1,
                    "revision_status": "UNKNOWN" if name == "unknown" else "EXACT",
                    "body_ref": content_identity(item["value"]["content"])[2],
                    "store_item": item} for name, item in zip(names, items, strict=True)]
        return ({"role": "tool", "tool_call_id": call_id, "content": body},
                {"thread_id": "thread", "call_id": call_id,
                 "search_id": call_id + ":search", "status": "returned",
                 "tool_message_body_ref": content_identity(body)[2],
                 "returned_json": json.dumps(entries)})

    class Sidecar:
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self.searches = rows

        def rows(self, table: str) -> list[dict[str, Any]]:
            assert table == "searches"
            return self.searches

        def latest_revision(self, ns: tuple[str, ...], memory_id: str) -> dict[str, Any] | None:
            assert ns == namespace
            return latest.get(memory_id)

    calls: list[str] = []

    def get(ns: tuple[str, ...], memory_id: str) -> Any:
        assert ns == namespace
        calls.append(memory_id)
        return store.get(ns, memory_id, refresh_ttl=False)

    def project(names: list[str], getter: Any = get) -> Any:
        message, row = search("first", names)
        return project_current_evidence(
            [message], Sidecar([row]), "thread", getter,  # type: ignore[arg-type]
            refresh_until_current_candidate=True, max_exact_refresh_per_search=1)

    higher_current = project(["current", "x"])
    assert calls == []
    assert higher_current.items[1]["refresh_skip_reason"] == (
        "HIGHER_RANK_CURRENT_CANDIDATE")
    assert "old-x" not in higher_current.messages[0]["content"]

    higher_stale = project(["x", "y"])
    assert calls == ["x"] and len(higher_stale.exact_reads) == 1
    assert higher_stale.items[0]["delivery_source"] == "public Store.get"
    assert higher_stale.items[1]["refresh_skip_reason"] == (
        "HIGHER_RANK_CURRENT_CANDIDATE")
    assert "new-x" in higher_stale.messages[0]["content"]
    assert "new-y" not in higher_stale.messages[0]["content"]

    calls.clear()
    first, first_row = search("first", ["x"])
    second, second_row = search("second", ["x"])
    repeated = project_current_evidence(
        [first, second], Sidecar([first_row, second_row]), "thread", get,  # type: ignore[arg-type]
        refresh_until_current_candidate=True, max_exact_refresh_per_search=1)
    assert calls == ["x"] and len(repeated.exact_reads) == 1
    assert repeated.items[1]["current_body_delivered"] is True
    assert "Current revision body is absent" not in repeated.messages[1]["content"]

    calls.clear()

    def absent(ns: tuple[str, ...], memory_id: str) -> None:
        calls.append(memory_id)
        return None

    uncertain = project(["unknown", "deleted", "x", "y"], absent)
    assert calls == ["x"] and uncertain.exact_reads[0]["status"] == "UNKNOWN_NOT_FOUND"
    assert [item["status"] for item in uncertain.items[:2]] == ["UNKNOWN", "DELETED"]
    assert uncertain.items[3]["refresh_skip_reason"] == "SEARCH_EXACT_READ_LIMIT"
    assert all("withheld" in json.loads(uncertain.messages[0]["content"])[index][
        "value"]["content"] for index in (1, 2, 3))


def test_lineage_uses_namespace_revision_and_response_id() -> None:
    snapshot = [{"namespace": ["run", "user"], "memory_id": "same-id",
                 "revision": 1, "ref": "memory:same-id@1", "body_ref": "body:old"}]
    lineage = {"original_body_ref": content_identity("same text")[2],
               "generating_request_id": "request-one",
               "exact_snapshot_json": canonical_json(snapshot)}

    class Sidecar:
        own_revision = 1

        def get_assistant_lineage(self, thread_id: str,
                                  response_id: str) -> dict[str, Any] | None:
            assert thread_id == "thread"
            return lineage if response_id == "response-one" else None

        def latest_revision(self, namespace: tuple[str, ...],
                            memory_id: str) -> dict[str, Any] | None:
            assert memory_id == "same-id"
            return {"revision": 2 if namespace == ("run", "other") else
                    self.own_revision, "tombstone": 0}

    sidecar = Sidecar()
    graph = [AIMessage(id="response-one", content="same text"),
             AIMessage(id="response-two", content="same text")]
    wire = [{"role": "assistant", "content": "same text"} for _ in graph]
    current = project_derived_assistants(graph, wire, sidecar, "thread")  # type: ignore[arg-type]
    assert current.messages == wire and not current.rebases
    assert current.unknown_bindings[0]["response_id"] == "response-two"
    sidecar.own_revision = 2
    stale = project_derived_assistants(graph, wire, sidecar, "thread")  # type: ignore[arg-type]
    assert stale.messages[0]["content"] == DERIVED_WITHHELD
    assert stale.messages[1] == wire[1]
    assert stale.rebases[0]["stale_refs"][0]["namespace"] == ["run", "user"]


def test_exposed_diagnostic_identity_uses_actual_projection_recipe(tmp_path: Path) -> None:
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps({"cases": [{"id": "identity", "tools": [],
                                                   "sessions": []}]}), encoding="utf-8")
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps({"inputs_file_sha256": sha256_file(inputs_path),
                                       "cases": 1}), encoding="utf-8")
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            for arm, expected in (("b1_control", B1_RECIPE_ID),
                                  ("a5_rank_bounded_rebase", SER_V21_RECIPE_ID)):
                sidecar = RevisionSidecar(tmp_path / f"{arm}.sqlite")
                observer = ProvenanceObserver(sidecar, "run", arm)
                store = ObservedStore(InMemoryStore(), observer)
                projection = (ProjectionController(
                    observer, arm=arm, store=store, stage="v21",
                    refresh_until_current_candidate=True, max_exact_refresh_per_search=1)
                    if arm == "a5_rank_bounded_rebase" else None)
                model = VLLMChatModel(client=client, observer=observer,
                                      projection=projection)
                output = tmp_path / arm
                result = run_frozen_diagnostics(
                    inputs_path, freeze_path, output, "run", model, store, saver,
                    {"lock": "same"}, arm_id=arm, observer=observer)
                assert result["status"] == "TERMINAL"
                assert json.loads((output / "run-identity.json").read_text())[
                    "recipe_id"] == expected
                sidecar.close()


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


@pytest.mark.parametrize("omit_old_search", [False, True])
@pytest.mark.parametrize("arm", ["a4_selective_rebase", "a5_rank_bounded_rebase"])
def test_rebase_binds_equal_text_to_response_identity_across_restart(
    tmp_path: Path, omit_old_search: bool, arm: str,
) -> None:
    sidecar_path = tmp_path / "sidecar.sqlite"
    checkpoint_path = tmp_path / "checkpoint.sqlite"
    scope = FoundationScope("run", arm, "user", "episode")
    inner = InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                 "fields": ["content"]})
    wires: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        action = ({"calls": [{"name": "search_memory", "arguments": {
            "query": "old-4-body", "limit": 10}}]} if len(wires) == 2 else
                  {"answer": "new conclusion"} if len(wires) == 4 else
                  {"answer": "same-note"} if len(wires) in {1, 3} else
                  {"answer": "done"})
        return httpx.Response(200, json=_receipt(action, f"g{len(wires)}"))

    def make_model(observer: ProvenanceObserver, store: ObservedStore,
                   client: VLLMClient) -> VLLMChatModel:
        def emit(event: dict[str, Any]) -> None:
            events.append(event)
            observer.capture_provider_event(event)

        client.emit = emit
        model = VLLMChatModel(client=client, observer=observer,
                              projection=ProjectionController(
                                  observer, emit, arm=arm, store=store, stage="v21",
                                  refresh_until_current_candidate=(
                                      arm == "a5_rank_bounded_rebase"),
                                  max_exact_refresh_per_search=(
                                      1 if arm == "a5_rank_bounded_rebase" else None)))
        if omit_old_search:
            model.request_view = SearchResultRequestView(
                {"omit_search_results_before_public_index": 2,
                 "activate_at_public_index": 2}, observer, emit)
        return model

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond)) as client:
        first_sidecar = RevisionSidecar(sidecar_path)
        first_observer = ProvenanceObserver(first_sidecar, "run", arm)
        first_store = ObservedStore(inner, first_observer)
        model = make_model(first_observer, first_store, client)
        seed = _fixture_memory_effect(
            "seed:x", {"action": "create", "content": "old-4-body"},
            scope, first_store, first_observer, tmp_path, Stub(),  # type: ignore[arg-type]
        )
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            agent = build_agent(model, first_store, saver, [], observer=first_observer)
            invoke_public_message(agent, model, scope, "State a note.")
            invoke_public_message(agent, model, scope, "Find memory x.")
            assert len(wires) == 3
            assert len(first_sidecar.rows("assistant_lineage")) == 2
        _fixture_memory_effect(
            "update:x", {"action": "update", "id": seed["memory_id"],
                         "content": "new-8-body"},
            scope, first_store, first_observer, tmp_path, Stub(),  # type: ignore[arg-type]
        )
        first_sidecar.close()

        sidecar = RevisionSidecar(sidecar_path)
        observer = ProvenanceObserver(sidecar, "run", arm)
        store = ObservedStore(inner, observer)
        restarted_model = make_model(observer, store, client)
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            agent = build_agent(restarted_model, store, saver, [], observer=observer)
            invoke_public_message(agent, restarted_model, scope, "Proceed with current x.")
            third_request = wires[3]["messages"]
            assistant_texts = [item["content"] for item in third_request
                               if item["role"] == "assistant"]
            assert assistant_texts.count("same-note") == 1
            assert assistant_texts.count(DERIVED_WITHHELD) == 1
            assert any('"search_memory"' in content for content in assistant_texts)
            tool_contents = [item["content"] for item in third_request
                             if item["role"] == "tool"]
            assert all("old-4-body" not in content for content in tool_contents)
            if omit_old_search:
                assert not tool_contents
                view = [event for event in events
                        if event.get("event") == "fixture_request_view"][-1]
                assert view["omitted_search_results"][0]["source_public_message_index"] == 1
            else:
                assert any("new-8-body" in content for content in tool_contents)
            rebases = [event for event in events
                       if event.get("event") == "derived_output_rebase"]
            assert len(rebases) == 1
            assert rebases[0]["response_id"] == "g3"
            assert rebases[0]["generating_request_id"] == next(
                row["generating_request_id"] for row in sidecar.rows("assistant_lineage")
                if row["response_id"] == "g3")
            assert rebases[0]["stale_refs"][0]["revision"] == 1
            assert rebases[0]["current_refs"][0]["revision"] == 2
            original_assistants = [message for message in agent.get_state(scope.config()).values[
                "messages"] if getattr(message, "id", None) in {"g1", "g3"}]
            assert [message.content for message in original_assistants] == [
                "same-note", "same-note"]
            assert any(isinstance(message, ToolMessage)
                       and "old-4-body" in message.content for message in
                       agent.get_state(scope.config()).values["messages"])
            invoke_public_message(agent, restarted_model, scope, "Continue.")
            assert "new conclusion" in [item["content"] for item in wires[4]["messages"]
                                      if item["role"] == "assistant"]
            g4 = next(row for row in sidecar.rows("assistant_lineage")
                      if row["response_id"] == "g4")
            if omit_old_search:
                assert json.loads(g4["exact_snapshot_json"]) == []
            else:
                assert json.loads(g4["exact_snapshot_json"])[0]["revision"] == 2
            before = len(wires)
            resume_public_message(agent, restarted_model, scope)
            assert len(wires) == before
        sidecar.close()


def test_fixture_update_list_delete_unknown_seed_and_completed_resume(tmp_path: Path) -> None:
    fixture = {
        "kind": "SER_V20_REVISION_DIAGNOSTIC", "case_id": "generic-changes",
        "user_id": "user", "task_id": "task",
        "seed_memories": [{"name": "primary", "content": "initial"},
                          {"name": "remove", "content": "temporary"}],
        "unobserved_seed_memories": [{"name": "unknown", "content": "imported"}],
        "revision_updates": [
            {"after_public_index": 0, "target": "primary", "action": "update",
             "content": "second"},
            {"after_public_index": 0, "target": "remove", "action": "delete"},
            {"after_public_index": 1, "target": "primary", "action": "update",
             "content": "third"},
        ],
        "public_messages": ["Start.", "Continue.", "Finish."],
        "business_tool_schema": {"type": "function", "function": {
            "name": "record", "description": "Record a value.",
            "parameters": {"type": "object", "properties": {"value": {"type": "string"}},
                           "required": ["value"], "additionalProperties": False}}},
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps({"case_id": fixture["case_id"],
                                       "fixture_sha256": sha256_file(fixture_path),
                                       "public_messages": 3}), encoding="utf-8")
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    arm = "a4_selective_rebase"
    observer = ProvenanceObserver(sidecar, "run", arm)
    inner = InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                 "fields": ["content"]})
    store = ObservedStore(inner, observer)
    wires: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def emit(event: dict[str, Any]) -> None:
        events.append(event)
        observer.capture_provider_event(event)

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        return httpx.Response(200, json=_receipt({"answer": "ok"}, f"g{len(wires)}"))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond), emit=emit) as client:
        model = VLLMChatModel(client=client, observer=observer,
                              projection=ProjectionController(
                                  observer, emit, arm=arm, store=store, stage="v20"))
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            output = tmp_path / "run"
            result = run_mechanism(fixture_path, freeze_path, output,
                                   "run", arm, model, store, saver, observer)
            assert result["status"] == "TERMINAL" and len(wires) == 3
            effects = json.loads((output / "fixture-effects.json").read_text())
            primary = effects["seed:primary"]["memory_id"]
            removed = effects["seed:remove"]["memory_id"]
            unknown = effects["seed_unobserved:unknown"]["memory_id"]
            namespace = ("langmem", "run", arm, "user")
            assert sidecar.latest_revision(namespace, primary)["revision"] == 3
            assert sidecar.latest_revision(namespace, removed)["tombstone"] == 1
            assert sidecar.latest_revision(namespace, unknown) is None
            assert store.get(namespace, unknown) is not None
            assert effects["seed_unobserved:unknown"]["origin"] == (
                "FIXTURE_CONTROLLED_UNOBSERVED_SEED")
            assert effects["seed_unobserved:unknown"]["call_key"] is None
            counts = (len(wires), len(sidecar.rows("revisions")),
                      len(sidecar.rows("operations")))
            again = run_mechanism(fixture_path, freeze_path, output,
                                  "run", arm, model, store, saver, observer)
            assert again["status"] == "TERMINAL"
            assert counts == (len(wires), len(sidecar.rows("revisions")),
                              len(sidecar.rows("operations")))
    sidecar.close()


@pytest.mark.parametrize(("failure", "frozen"), [
    (ValueError("PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"), False),
    (RuntimeError("service unavailable"), False),
    (ValueError("PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"), True),
])
def test_merit_local_capacity_keeps_native_result_and_continues_only_that_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception, frozen: bool,
) -> None:
    tasks = [SimpleNamespace(task_id=f"task-{index}", kind="native", dependent=False,
                             checker="done", checker_args={},
                             user_messages=["first", "never after cap"], golds=lambda: [])
             for index in range(2)]
    arc = SimpleNamespace(arc_id="arc", episodes=[
        SimpleNamespace(index=index, task=task) for index, task in enumerate(tasks)])
    selection = {"private_artifacts": {"arc_sha256": "arc-hash"},
                 "episode_count": 2, "dependent_episode_count": 0}
    monkeypatch.setattr(langmem_merit, "load_exposed_arc", lambda _path: (
        selection, arc, SimpleNamespace(TOOL_SCHEMAS=[], TOOL_FUNCS={}),
        SimpleNamespace(done=lambda snapshot: snapshot["done"],
                        memory_utilized=lambda _calls, _golds: False),
        SimpleNamespace(SYSTEM_PROMPT="rules {memory_block}")))
    monkeypatch.setattr(langmem_merit, "load_frozen_arc", langmem_merit.load_exposed_arc)
    monkeypatch.setattr(langmem_merit, "build_agent", lambda *args, **kwargs: (
        SimpleNamespace(get_state=lambda _config: SimpleNamespace(
            values={"messages": [AIMessage(content="partial")]}))))
    selection_path = tmp_path / "selection.json"
    selection_path.write_text("{}", encoding="utf-8")
    model = SimpleNamespace(m1=None, odr=None, projection=None,
                            client=SimpleNamespace(budget=None))

    world = SimpleNamespace(done=False, conn=SimpleNamespace(close=lambda: None))
    world.snapshot = lambda: {"done": world.done}
    monkeypatch.setattr(langmem_merit, "_world_for_run", lambda *_args: world)
    attempts: list[tuple[str, int]] = []

    def invoke(_agent: Any, _model: Any, scope: FoundationScope, _content: str,
               index: int, _pending: bool, **_kwargs: Any) -> list[AIMessage]:
        attempts.append((scope.episode_id, index))
        if scope.episode_id == "episode:0":
            if isinstance(failure, ValueError):
                world.done = True
            raise failure
        return [AIMessage(content="done")]

    monkeypatch.setattr(langmem_merit, "invoke_or_resume_public_message", invoke)
    output = tmp_path / "run"

    def run_arc() -> dict[str, Any]:
        args = (selection_path, output, "run", model, InMemoryStore(), object(), {})
        if frozen:
            return langmem_merit.run_frozen_merit_arc(
                *args, {"method": "ser_v23", "lock_sha256": "lock"},
                continue_on_local_capacity=True)
        return langmem_merit.run_exposed_merit_arc(
            *args, continue_on_local_capacity=True)

    if isinstance(failure, RuntimeError):
        with pytest.raises(RuntimeError, match="service unavailable"):
            run_arc()
        assert attempts == [("episode:0", 0)]
        assert not (output / "episodes/episode-1.json").exists()
        return
    result = run_arc()
    assert attempts == [("episode:0", 0), ("episode:1", 0), ("episode:1", 1)]
    failed = json.loads((output / "episodes/episode-0.json").read_text())
    assert failed["native_score"]["success"] is True
    assert failed["host_status"] == "LOCAL_CAPACITY_EXCEEDED"
    assert failed["attempted_public_message_indexes"] == [0]
    assert failed["completed_public_message_indexes"] == []
    assert failed["skipped_public_message_indexes"] == [1]
    assert result["native_successes"] == 1
    assert not (output / "interruption.json").exists()
    identity = json.loads((output / "run-identity.json").read_text())
    if frozen:
        assert identity["method"] == "ser_v23" and identity["lock_sha256"] == "lock"
    else:
        assert set(identity) == {"recipe_id", "run_id", "arc_id",
                                 "selection_sha256", "config_sha256", "arc_sha256"}


def test_frozen_merit_loader_and_three_arm_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection_path = LAB / "data/manifests/contextual-memory-v7-e0-selection-final.json"
    selection, arc, _, _, _ = load_frozen_arc(selection_path)
    assert arc.arc_id == selection["arc_id"] and len(arc.episodes) == 5
    assert load_exposed_arc(selection_path)[1].arc_id == arc.arc_id

    changed = json.loads(selection_path.read_text())
    changed["generator_arguments"]["base_seed"] = 3
    changed_path = tmp_path / "changed-selection.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="MERIT_EXPOSED_SELECTION_CHANGED"):
        load_exposed_arc(changed_path)
    changed["generator_arguments"]["base_seed"] = 0
    changed["private_artifacts"]["arc_sha256"] = "0" * 64
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="MERIT_ARC_IDENTITY_MISMATCH"):
        load_frozen_arc(changed_path)

    monkeypatch.syspath_prepend(str(LAB / "tools"))
    from run_milai_ser_v23 import projection_for_arm

    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "b1_control")
    store = ObservedStore(InMemoryStore(), observer)
    assert projection_for_arm(observer, None, store, "b1_control") is None
    for arm in ("a3_exact_refresh", "a4_selective_rebase"):
        projection = projection_for_arm(observer, None, store, arm)
        assert projection is not None
        assert projection.arm == arm and projection.stage == "v21"
        assert projection.refresh_until_current_candidate is False
        assert projection.max_exact_refresh_per_search is None
        assert projection.recipe_id == SER_V21_RECIPE_ID
    sidecar.close()


def test_v23_prepare_binds_declared_arc_and_pre_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(LAB / "tools"))
    import run_milai_ser_v23 as entry

    arguments = {"n_arcs": 1, "episodes_per_arc": 2, "dep_ratio": 0.5,
                 "base_seed": 17, "difficulty": "hard"}
    selection = {"generator_arguments": arguments,
                 "source_sha256": {"declared": "hash"}, "source_commit": "pinned",
                 "private_artifacts": {"arc_sha256": "arc-hash",
                                       "initial_world_sha256": "world-hash"}}
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    pre_registration_path = tmp_path / "pre-registration.json"
    pre_registration_path.write_text(json.dumps({
        "generator_arguments": [arguments], "source_sha256": selection["source_sha256"],
        "source_commit": selection["source_commit"]}), encoding="utf-8")
    monkeypatch.setattr(entry, "SER_V23_PRE_REGISTRATION", pre_registration_path)
    monkeypatch.setattr(entry, "verify_ser_v23_lock", lambda *_args: None)
    arc = SimpleNamespace(arc_id="arc", episodes=[
        SimpleNamespace(task=SimpleNamespace(dependent=index == 1,
                                             user_messages=["message"]))
        for index in range(2)])
    monkeypatch.setattr(entry, "load_frozen_arc", lambda _path: (
        selection, arc, None, None, None))
    freeze = {"kind": "MILAI_SER_V23_ARC_FREEZE",
              "selection_path": str(selection_path),
              "selection_sha256": sha256_file(selection_path),
              "arc_sha256": "arc-hash", "world_sha256": "world-hash",
              "arc_id": "arc", "episode_count": 2, "dependent_episode_count": 1,
              "public_messages": 2,
              "pre_registration_path": str(pre_registration_path),
              "pre_registration_sha256": sha256_file(pre_registration_path),
              "unseen_at_selection": True}
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    lock_path, config_path = tmp_path / "lock.json", tmp_path / "config.json"
    lock_path.write_text("{}", encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")
    args = SimpleNamespace(lock=lock_path, config=config_path, freeze=freeze_path,
                           selection=selection_path, run="run", arm="a3_exact_refresh",
                           output=tmp_path / "prepared.json")
    receipt = entry.prepare(args)
    assert receipt["status"] == "PREPARED_ZERO_MODEL"
    assert (receipt["arc_sha256"], receipt["world_sha256"], receipt["episodes"],
            receipt["dependent_episodes"], receipt["public_messages"]) == (
                "arc-hash", "world-hash", 2, 1, 2)
    freeze["selection_sha256"] = "changed"
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    with pytest.raises(ValueError, match="SER_V23_FROZEN_ARC_CHANGED"):
        entry.prepare(args)


def test_v21_authority_only_when_actual_memory_or_derived_risk_is_projected() -> None:
    class Projection:
        def __init__(self, stage: str, items: list[dict[str, Any]],
                     rebases: list[dict[str, Any]]) -> None:
            self.stage, self.items, self.rebases = stage, items, rebases

        def project(self, messages: list[dict[str, Any]], *_args: Any) -> ProjectedRequest:
            return ProjectedRequest(messages, {}, self.items, [], self.rebases)

        def record_delivery(self, *_args: Any) -> tuple[list[dict[str, Any]], int]:
            return [], 0

        def record_output(self, *_args: Any) -> None:
            pass

    def wire(history: list[Any], projection: Projection | None) -> dict[str, Any]:
        requests: list[dict[str, Any]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.read()))
            return httpx.Response(200, json=_receipt({"answer": "ok"}, "response"))

        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                   tool_mode="json_action"),
                        transport=httpx.MockTransport(respond)) as client:
            VLLMChatModel(client=client, projection=projection).invoke(
                history, tools=[{"type": "function", "function": {
                    "name": "search_memory", "description": "Search memory.",
                    "parameters": {"type": "object", "properties": {
                        "query": {"type": "string"}}, "required": ["query"]}}}])
        return requests[0]

    empty = [HumanMessage(content="Please check.")]
    empty_search = [*empty, AIMessage(content="", tool_calls=[{
        "name": "search_memory", "args": {"query": "check"}, "id": "call-1"}]),
        ToolMessage(content="[]", tool_call_id="call-1", name="search_memory")]
    for history in (empty, empty_search):
        assert wire(history, Projection("v21", [], [])) == wire(history, None)

    baseline = wire(empty, None)
    for items, rebases in (([{"status": "CURRENT"}], []),
                           ([{"status": "UNKNOWN"}], []),
                           ([], [{"response_id": "bound-stale-output"}])):
        projected = wire(empty, Projection("v21", items, rebases))
        assert SOURCE_AUTHORITY in projected["messages"][0]["content"]
        assert projected["messages"][1:] == baseline["messages"][1:]
    assert SOURCE_AUTHORITY in wire(
        empty, Projection("v20", [], []))["messages"][0]["content"]
