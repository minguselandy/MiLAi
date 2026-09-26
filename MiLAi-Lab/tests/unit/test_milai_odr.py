"""Focused zero-model checks for request-local v19 behavior."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("langmem")

from jsonschema import ValidationError, validate
from langchain_core.embeddings import Embeddings
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
from milai_lab.baselines.langmem_revision_store import ObservedStore, RevisionSidecar
from milai_lab.methods.on_demand_reconstruction.controller import ODRController
from milai_lab.methods.on_demand_reconstruction.freshness import freshness_block, inspect_freshness
from milai_lab.methods.on_demand_reconstruction.schema import odr_action_schema
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import IncompleteChatResponse, VLLMChatModel, _action_schema
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


def _reconstruction(ref: str, proposition: str) -> dict[str, Any]:
    return {"proposition": proposition,
            "action_scope": {"subject": "user", "item": "crate", "action_type": "record",
                             "critical_parameters": ["temperature"]},
            "evidence_used": [{"ref": ref, "support_role": "supports_value"}],
            "unresolved_gap": None}


def test_schema_and_revision_freshness(tmp_path: Path) -> None:
    business = {"type": "function", "function": {"name": "record", "parameters": {
        "type": "object", "properties": {}}}}
    base = _action_schema([business], generation_only=True)
    schema = odr_action_schema(base)
    for action in ({"reconstruction": None, "answer": "ordinary"},
                   {"reconstruction": None,
                    "calls": [{"name": "record", "arguments": {}}]},
                   {"reconstruction": _reconstruction("e0", "Use current value."),
                    "answer": "pending"},
                   {"reconstruction": _reconstruction("e0", "Use current value."),
                    "calls": [{"name": "record", "arguments": {}}]}):
        validate(action, schema)
    with pytest.raises(ValidationError):
        validate({"reconstruction": {"op": "set"},
                  "calls": [{"name": "record", "arguments": {}}]}, schema)
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "odr")
    store = ObservedStore(InMemoryStore(), observer)
    scope = FoundationScope("run", "odr", "user", "episode")
    x = _fixture_memory_effect("seed:x", {"action": "create", "content": "same"},
                               scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    y = _fixture_memory_effect("seed:y", {"action": "create", "content": "unrelated"},
                               scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    namespace = ("langmem", "run", "odr", "user")
    x1 = f"memory:{x['memory_id']}@1"
    x2 = f"memory:{x['memory_id']}@2"
    y1 = f"memory:{y['memory_id']}@1"
    handles = {x1: {"kind": "memory", "namespace": namespace,
                    "memory_id": x["memory_id"], "revision": 1}}
    assert inspect_freshness(handles, sidecar)[x1]["status"] == "CURRENT"
    assert freshness_block(handles, inspect_freshness(handles, sidecar)) == ""
    _fixture_memory_effect("update:x", {"action": "update", "id": x["memory_id"],
                                        "content": "same"},
                           scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    state = inspect_freshness(handles, sidecar)
    assert state[x1] == {"status": "SUPERSEDED", "current_ref": x2,
                         "current_body_delivered": False}
    assert "same" not in freshness_block(handles, state)
    assert y1 not in freshness_block(handles, state)
    handles[x2] = {"kind": "memory", "namespace": namespace,
                   "memory_id": x["memory_id"], "revision": 2}
    states = inspect_freshness(handles, sidecar)
    assert states[x1]["current_body_delivered"]
    assert states[x2]["status"] == "CURRENT"
    handles["memory:unknown@1"] = {"kind": "memory", "namespace": namespace,
                                   "memory_id": "unknown", "revision": 1}
    assert inspect_freshness(handles, sidecar)["memory:unknown@1"]["status"] == "UNKNOWN"
    _fixture_memory_effect("delete:x", {"action": "delete", "id": x["memory_id"]},
                           scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    assert inspect_freshness(handles, sidecar)[x1]["status"] == "DELETED"
    sidecar.close()


def test_b1_freshness_only_wire_parity_without_stale(tmp_path: Path) -> None:
    wires: list[dict[str, Any]] = []
    for arm in ("b1_control", "freshness_only"):
        sidecar = RevisionSidecar(tmp_path / f"{arm}.sqlite")
        observer = ProvenanceObserver(sidecar, "run", arm)
        scope = FoundationScope("run", arm, "user", "episode")
        store = ObservedStore(InMemoryStore(), observer)
        def respond(request: httpx.Request) -> httpx.Response:
            wires.append(json.loads(request.read()))
            return httpx.Response(200, json=_receipt({"answer": "done"}, "g1"))
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                        transport=httpx.MockTransport(respond),
                        emit=observer.capture_provider_event) as client:
            controller = (ODRController(observer, arm, tmp_path / "analysis.jsonl")
                          if arm != "b1_control" else None)
            model = VLLMChatModel(client=client, observer=observer, odr=controller)
            with SqliteSaver.from_conn_string(str(tmp_path / f"{arm}-checkpoint.sqlite")) as saver:
                agent = build_agent(model, store, saver, observer=observer)
                invoke_public_message(agent, model, scope, "ordinary question")
        sidecar.close()
    assert wires[0] == wires[1]
    assert "reconstruction" not in json.dumps(wires[1])
    assert "Evidence freshness" not in json.dumps(wires[1])


def test_imported_search_result_is_unknown_without_freshness_block(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "freshness_only")
    scope = FoundationScope("run", "freshness_only", "user", "episode")
    inner = InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                 "fields": ["content"]})
    inner.put(("langmem", "run", "freshness_only", "user"), "imported", {
        "content": "imported preference"})
    store = ObservedStore(inner, observer)
    wires: list[dict[str, Any]] = []
    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append(wire)
        action = ({"calls": [{"name": "search_memory", "arguments": {
            "query": "imported preference"}}]} if len(wires) == 1 else {"answer": "seen"})
        return httpx.Response(200, json=_receipt(action, f"g{len(wires)}"))
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        controller = ODRController(observer, "freshness_only", tmp_path / "trace.jsonl")
        model = VLLMChatModel(client=client, observer=observer, odr=controller)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver, observer=observer)
            invoke_public_message(agent, model, scope, "Find imported preference.")
    request = sidecar.rows("requests")[-1]
    actual = controller.view.request_messages(request["request_id"])
    handles = controller.view.handles(actual,
                                      thread_id=scope.config()["configurable"]["thread_id"],
                                      public_index=0, request_id=request["request_id"])
    unknown = [ref for ref in handles if ref.startswith("memory_unknown:")]
    assert len(unknown) == 1
    statuses = inspect_freshness(handles, sidecar)
    assert statuses[unknown[0]]["status"] == "UNKNOWN"
    assert freshness_block(handles, statuses) == ""
    assert "Evidence freshness" not in wires[-1]["messages"][0]["content"]
    sidecar.close()


def test_real_graph_exact_delivery_restart_and_replay(tmp_path: Path) -> None:
    sidecar_path = tmp_path / "sidecar.sqlite"
    sidecar = RevisionSidecar(sidecar_path)
    observer = ProvenanceObserver(sidecar, "run", "odr")
    scope = FoundationScope("run", "odr", "user", "episode")
    store = ObservedStore(InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                         "fields": ["content"]}), observer)
    seed = _fixture_memory_effect("seed", {"action": "create", "content": "hold 4 C"},
                                  scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    world: list[str] = []
    @tool
    def record(value: str) -> str:
        """Record a holding value."""
        world.append(value)
        return value
    journal = BusinessActionJournal(tmp_path / "business.json", ["record"])
    turns = 0
    wires: list[dict[str, Any]] = []
    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal turns
        turns += 1
        wire = json.loads(request.read())
        wires.append(wire)
        system = wire["messages"][0]["content"]
        if turns in (1, 3):
            action = {"reconstruction": None, "calls": [
                {"name": "search_memory", "arguments": {"query": "holding", "limit": 1}}]}
        elif turns in (2, 4):
            version = 1 if turns == 2 else 2
            match = re.search(rf"(e\d+): search result [^\n]*@{version}", system)
            assert match is not None
            action = {"reconstruction": _reconstruction(
                match.group(1), f"ODR_PROP_{version}"), "answer": "pending"}
        elif turns == 5:
            action = {"reconstruction": None, "calls": [
                {"name": "record", "arguments": {"value": "8 C"}}]}
        else:
            receipt = re.search(r"(e\d+): record result at message", system)
            user = re.findall(r"(e\d+): user message at position", system)
            assert receipt is not None and user
            reconstructed = _reconstruction(receipt.group(1), "Recorded from receipt.")
            reconstructed["evidence_used"] = [
                {"ref": receipt.group(1), "support_role": "records_execution"},
                {"ref": user[-1], "support_role": "contextual"}]
            action = {"reconstruction": reconstructed, "answer": "recorded"}
        return httpx.Response(200, json=_receipt(action, f"g{turns}"))
    trace_path = tmp_path / "reconstruction.jsonl"
    checkpoint_path = tmp_path / "checkpoint.sqlite"
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer,
                              odr=ODRController(observer, "odr", trace_path))
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            agent = build_agent(model, store, saver, [record],
                                business_call_wrapper=journal, observer=observer)
            invoke_public_message(agent, model, scope, "What is saved?")
    sidecar.close()
    sidecar = RevisionSidecar(sidecar_path)
    observer = ProvenanceObserver(sidecar, "run", "odr")
    store.observer = observer
    _fixture_memory_effect("external_update", {"action": "update",
                           "id": seed["memory_id"], "content": "hold 8 C"},
                           scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    trace_path.write_text(trace_path.read_text() + '{"forged":"SENTINEL_NEVER_INPUT"}\n')
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer,
                              odr=ODRController(observer, "odr", trace_path))
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            agent = build_agent(model, store, saver, [record],
                                business_call_wrapper=journal, observer=observer)
            invoke_public_message(agent, model, scope, "Still pending.")
            messages = invoke_public_message(agent, model, scope, "Approve.")
            before = (len(wires), len(world), len(sidecar.rows("operations")))
            replay = resume_public_message(agent, model, scope)
            assert replay[-1].content == messages[-1].content
            assert before == (len(wires), len(world), len(sidecar.rows("operations")))
    assert world == ["8 C"]
    assert "Evidence freshness:" in wires[2]["messages"][0]["content"]
    assert "ODR_PROP_1" not in json.dumps(wires[2])
    assert "SENTINEL_NEVER_INPUT" not in json.dumps(wires[2])
    assert any(row["revision"] == 2 for row in sidecar.rows("revisions"))
    rows = [json.loads(line) for line in trace_path.read_text().splitlines()
            if "odr_reconstruction" in line]
    assert rows[-2]["reconstruction"] is None
    assert rows[-2]["metric"] == "ACTION_WITHOUT_RECONSTRUCTION"
    assert rows[1]["reconstruction"]["evidence_used"][0]["ref"] == (
        f"memory:{seed['memory_id']}@1")
    assert rows[3]["reconstruction"]["evidence_used"][0]["ref"] == (
        f"memory:{seed['memory_id']}@2")
    assert [item["ref"].split(":", 1)[0] for item in
            rows[-1]["reconstruction"]["evidence_used"]] == ["observation", "observation"]
    actual = model.odr.view.request_messages(rows[1]["request_id"])
    historical_tool = next(message for message in actual if message["role"] == "tool")
    duplicated = [*actual, historical_tool]
    thread = scope.config()["configurable"]["thread_id"]
    assert model.odr.view.handles(actual, thread_id=thread, public_index=0) == (
        model.odr.view.handles(duplicated, thread_id=thread, public_index=0))
    sidecar.close()


def test_invalid_stale_reconstruction_has_zero_business_effect(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "odr")
    scope = FoundationScope("run", "odr", "user", "episode")
    store = ObservedStore(InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                         "fields": ["content"]}), observer)
    seed = _fixture_memory_effect("seed", {"action": "create", "content": "old"},
                                  scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    world: list[str] = []
    @tool
    def record(value: str) -> str:
        """Record a value."""
        world.append(value)
        return value
    journal = BusinessActionJournal(tmp_path / "business.json", ["record"])
    turns = 0
    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal turns
        turns += 1
        system = json.loads(request.read())["messages"][0]["content"]
        if turns == 1:
            action = {"reconstruction": None, "calls": [
                {"name": "search_memory", "arguments": {"query": "old"}}]}
        elif turns == 2:
            action = {"reconstruction": None, "answer": "pending"}
        else:
            short = re.search(r"(e\d+): search result [^\n]*@1", system)
            assert short is not None
            action = {"reconstruction": _reconstruction(short.group(1), "use old"),
                      "calls": [{"name": "record", "arguments": {"value": "old"}}]}
        return httpx.Response(200, json=_receipt(action, f"g{turns}"))
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer,
                              odr=ODRController(observer, "odr", tmp_path / "trace.jsonl"))
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver, [record],
                                business_call_wrapper=journal, observer=observer)
            invoke_public_message(agent, model, scope, "Read memory.")
            _fixture_memory_effect("update", {"action": "update", "id": seed["memory_id"],
                                               "content": "new"},
                                   scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
            with pytest.raises(IncompleteChatResponse, match="ODR_STALE_SUPPORTS_VALUE"):
                invoke_public_message(agent, model, scope, "Record now.")
    assert world == []
    assert journal.calls_for_thread(scope.config()["configurable"]["thread_id"]) == []
    assert not any(row["tool_name"] == "record" for row in sidecar.rows("tool_calls"))
    sidecar.close()
