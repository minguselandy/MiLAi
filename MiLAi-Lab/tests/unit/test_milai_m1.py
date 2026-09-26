"""Small zero-model checks of exact adoption, state, recheck and Graph side effects."""

from __future__ import annotations

import hashlib
import json
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
from milai_lab.baselines.langmem_revision_store import (
    ObservedStore,
    RevisionSidecar,
    canonical_json,
)
from milai_lab.harness.contextual_artifacts import write_json
from milai_lab.methods.milai_m1.controller import M1Controller, m1_action_schema
from milai_lab.methods.milai_m1.decision_basis import DecisionDeltaError
from milai_lab.methods.milai_m1.recheck import acknowledgements, refresh_rechecks
from milai_lab.methods.milai_m1.state_store import DecisionBasisStore
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel, _action_schema
from milai_lab.runners.langmem_foundation import BusinessActionJournal
from milai_lab.runners.langmem_m1_mechanism import _fixture_memory_effect, run_mechanism


class FixedEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _receipt(action: dict[str, Any], identity: str) -> dict[str, Any]:
    return {"id": identity, "model": "mock", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


def _set(refs: list[str], decision: str = "Use the saved temperature.") -> dict[str, Any]:
    return {"op": "set", "decision": decision,
            "scope": {"subject": "user", "item": "crate", "context": "holding"},
            "adopted_evidence": refs, "critical_gap": None, "status": "active"}


def test_generation_schema_matches_delta_branches() -> None:
    tool_schema = {"type": "function", "function": {"name": "example",
                   "parameters": {"type": "object", "properties": {}}}}
    schema = m1_action_schema(_action_schema([tool_schema], generation_only=True))
    calls = {"calls": [{"name": "example", "arguments": {}}]}
    for action in (
        {"decision_delta": None, "answer": "Done."},
        {"decision_delta": {"op": "clear"}, "answer": "Done."},
        {"decision_delta": _set(["e0"]), **calls},
    ):
        validate(action, schema)
    for delta in (
        {"op": "clear", "decision": "confirm_refund_amount"},
        {"op": "set", "decision": "Use saved temperature."},
        {**_set(["e0"]), "scope": {"subject": "user", "item": "crate",
                                      "context": "holding", "extra": "invalid"}},
    ):
        with pytest.raises(ValidationError):
            validate({"decision_delta": delta, "answer": "Done."}, schema)


def test_real_graph_adoption_exact_revision_recheck_and_restore(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    controller = M1Controller(state, observer)
    store = ObservedStore(InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                         "fields": ["content"]}), observer)
    scope = FoundationScope("run", "m1", "user", "episode")
    class Stub:
        client = type("Client", (), {"emit": None})()

    seed = _fixture_memory_effect("seed", {"action": "create", "content": "4 C"},
                                  scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    responses = [
        _receipt({"decision_delta": None, "calls": [{"name": "search_memory",
                 "arguments": {"query": "temperature", "limit": 1}}]}, "g1"),
        _receipt({"decision_delta": _set(["e1"]), "answer": "Use 4 C."}, "g2"),
        _receipt({"decision_delta": None, "answer": "I should recheck."}, "g3"),
        _receipt({"decision_delta": None, "calls": [{"name": "search_memory",
                 "arguments": {"query": "temperature", "limit": 1}}]}, "g4"),
        _receipt({"decision_delta": _set(["e2"], "Use the revised temperature."),
                 "answer": "Use 8 C."}, "g5"),
    ]
    wire: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer, m1=controller)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver, observer=observer)
            first = invoke_public_message(agent, model, scope, "What is saved?", "task")
            assert first[-1].content == "Use 4 C."
            basis = state.get(("run", "m1", "user", "task"))
            assert basis is not None
            assert basis["adopted_evidence"] == [f"memory:{seed['memory_id']}@1"]
            assert (basis["adopted_bindings"][0]["request_id"]
                    == sidecar.rows("requests")[1]["request_id"])
            not_sent = controller.view.handles(
                [{"role": "user", "content": "No search result in this request."}],
                thread_id=scope.config()["configurable"]["thread_id"], public_index=0,
            )
            assert all(not ref.startswith("memory:") for ref in not_sent)
            _fixture_memory_effect(
                "external_update", {"action": "update", "id": seed["memory_id"],
                                    "content": "8 C"}, scope, store, observer,
                tmp_path, Stub(),  # type: ignore[arg-type]
            )
            second = invoke_public_message(agent, model, scope, "Still pending.", "task")
            assert second[-1].content == "I should recheck."
            assert state.get(("run", "m1", "user", "task"))["needs_recheck"] is True  # type: ignore[index]
            third = invoke_public_message(agent, model, scope, "Please recheck.", "task")
            assert third[-1].content == "Use 8 C."
            before = (len(state.rows("delta_receipts")), len(state.rows("events")),
                      len(sidecar.rows("operations")), len(wire))
            replayed = resume_public_message(agent, model, scope, "task")
            assert replayed[-1].content == "Use 8 C."
            assert before == (len(state.rows("delta_receipts")), len(state.rows("events")),
                              len(sidecar.rows("operations")), len(wire))
    reopened = DecisionBasisStore(tmp_path / "basis.sqlite")
    basis = reopened.get(("run", "m1", "user", "task"))
    assert basis is not None
    assert basis["adopted_evidence"] == [f"memory:{seed['memory_id']}@2"]
    assert basis["needs_recheck"] is False
    assert [row["event"] for row in reopened.rows("events")].count("RECHECK_ACKNOWLEDGED") == 1
    assert "e0: current user message" in wire[0]["messages"][0]["content"]
    assert f"{seed['memory_id']}@1" in wire[1]["messages"][0]["content"]
    assert "new_observation_refs" in wire[2]["messages"][0]["content"]
    assert len(reopened.rows("delta_receipts")) == 5
    reopened.close()
    state.close()
    sidecar.close()


def test_continued_short_handle_is_not_a_reread_and_observation_ids_differ(
    tmp_path: Path,
) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    controller = M1Controller(state, observer)
    scope = FoundationScope("run", "m1", "user", "episode-one")
    other = FoundationScope("run", "m1", "user", "episode-two")
    observer.begin_public_message(scope, 0, "same text")
    observer.begin_public_message(other, 0, "same text")
    obs = sidecar.rows("observations")
    assert len(obs) == 2
    assert obs[0]["observation_id"] != obs[1]["observation_id"]
    key = ("run", "m1", "user", "task")
    state.activate(key)
    prior_binding = {"ref": "memory:00000000-0000-4000-8000-000000000001@1",
                     "kind": "memory", "content_sha256": "original-sha",
                     "request_id": "old-request", "delivery": "search_tool_message",
                     "label": "search_memory result 0 in tool message at position 3"}
    old_delta = _set([prior_binding["ref"]])
    state.apply(key, "old-request", "old-receipt", old_delta, [prior_binding], [])
    controller.begin_public_message(scope, "task", 0)
    planned = [{"role": "system", "content": "system"},
               {"role": "user", "content": "same text"}]
    context = controller.prompt_context(planned)
    assert "c0: search_memory result 0" in context
    assert "new_observation_refs: [\"e0\"]" in context
    request_id = controller.request_id(1)
    thread = scope.config()["configurable"]["thread_id"]
    sidecar.plan_request(request_id, thread, 0, 1)
    sidecar.finish_request(request_id, "completed", {
        "request": {"model": "mock", "messages": planned},
        "receipt": {"id": "new-receipt"},
    })
    assert controller.commit(1, "new-receipt", _set(["c0"])) == "NO_STATE_CHANGE"
    basis = state.get(key)
    assert basis is not None
    assert basis["revision"] == 1
    assert basis["adopted_bindings"][0]["request_id"] == "old-request"
    continuation = json.loads(state.rows("events")[-1]["detail_json"])
    assert continuation["adopted_bindings"][0]["continuation_request_id"] == request_id
    assert sidecar.rows("request_material") == []
    state.close()
    sidecar.close()


def test_invalid_delta_has_durable_error_and_no_tool_side_effect(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    controller = M1Controller(state, observer)
    world: list[str] = []

    @tool
    def record(value: str) -> str:
        """Record a local value."""
        world.append(value)
        return value

    action = {"decision_delta": _set(["e9"]),
              "calls": [{"name": "record", "arguments": {"value": "bad"}}]}
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(200, json=_receipt(action, "invalid"))),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer, m1=controller)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, ObservedStore(InMemoryStore(), observer), saver,
                                [record], observer=observer)
            with pytest.raises(DecisionDeltaError, match="DECISION_EVIDENCE_NOT_DELIVERED"):
                invoke_public_message(
                    agent, model, FoundationScope("run", "m1", "user", "episode"),
                    "Record bad.", "task",
                )
    assert world == []
    assert state.rows("delta_receipts")[0]["status"] == "ERROR"
    assert state.rows("delta_receipts")[0]["error_code"] == "DECISION_EVIDENCE_NOT_DELIVERED"
    assert sidecar.rows("tool_calls") == []
    state.close()
    sidecar.close()


def test_set_and_ordered_calls_share_one_generation_with_tool_error(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    controller = M1Controller(state, observer)
    world: list[str] = []

    @tool
    def record(value: str) -> str:
        """Record a local value."""
        assert state.get(("run", "m1", "user", "task")) is not None
        world.append(value)
        return value

    responses = [
        _receipt({"decision_delta": _set(["e0"]), "calls": [
            {"name": "record", "arguments": {"value": "first"}},
            {"name": "record", "arguments": {"wrong": "rejected"}},
        ]}, "g1"),
        _receipt({"decision_delta": None, "answer": "One record succeeded."}, "g2"),
    ]
    journal = BusinessActionJournal(tmp_path / "business.json", ["record"])
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(200, json=responses.pop(0))),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer, m1=controller)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            scope = FoundationScope("run", "m1", "user", "episode")
            agent = build_agent(model, ObservedStore(InMemoryStore(), observer), saver,
                                [record], business_call_wrapper=journal, observer=observer)
            messages = invoke_public_message(agent, model, scope, "Record first.", "task")
    assert messages[-1].content == "One record succeeded."
    assert world == ["first"]
    tool_messages = [message for message in messages if message.type == "tool"]
    assert [message.status for message in tool_messages] == ["success", "error"]
    assert len(journal.calls_for_thread(scope.config()["configurable"]["thread_id"])) == 1
    assert state.get(("run", "m1", "user", "task"))["revision"] == 1  # type: ignore[index]
    state.close()
    sidecar.close()


def test_store_noop_ack_suppression_task_isolation_and_clear(tmp_path: Path) -> None:
    path = tmp_path / "basis.sqlite"
    state = DecisionBasisStore(path)
    key = ("run", "m1", "user", "task-one")
    state.activate(key)
    delta = _set([])
    assert state.apply(key, "request-1", "g1", delta, [], []) == "SET"
    reason = {"kind": "revision_changed", "adopted_ref": "memory:x@1",
              "current_ref": "memory:x@2", "current_content_sha256": "sha"}
    assert state.add_reason(key, reason)
    assert state.apply(key, "request-2", "g2", delta, [], [reason]) == "NO_STATE_CHANGE"
    assert state.get(key)["revision"] == 1  # type: ignore[index]
    assert not state.add_reason(key, reason)
    assert state.apply(key, "request-2", "g2", delta, [], [reason]) == "NO_STATE_CHANGE"
    assert len(state.rows("delta_receipts")) == 2
    other = ("run", "m1", "user", "task-two")
    state.activate(other)
    assert state.get(other) is None
    assert state.get(key)["needs_recheck"] is True  # type: ignore[index]
    assert state.apply(other, "request-3", "g3", None, [], []) == "NO_STATE_CHANGE"
    state.close()
    restored = DecisionBasisStore(path)
    assert restored.get(key) is not None
    assert restored.apply(key, "request-4", "g4", {"op": "clear"}, [], []) == "CLEARED"
    assert restored.get(key) is None
    restored.close()


def test_unrelated_revision_does_not_trigger_and_tombstone_does(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    store = ObservedStore(InMemoryStore(), observer)
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    scope = FoundationScope("run", "m1", "user", "episode")
    class Stub:
        client = type("Client", (), {"emit": None})()

    x = _fixture_memory_effect("seed", {"action": "create", "content": "x"},
                               scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    y = _fixture_memory_effect("other_seed", {"action": "create", "content": "y"},
                               scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    y_id = y["result"].rsplit(" ", 1)[-1]
    key = ("run", "m1", "user", "task")
    state.activate(key)
    adopted = f"memory:{x['memory_id']}@1"
    state.apply(key, "r1", "g1", _set([adopted]), [{"ref": adopted,
                "kind": "memory", "content_sha256": "sha", "request_id": "r1",
                "label": "x", "delivery": "search_tool_message"}], [])
    _fixture_memory_effect("other_update", {"action": "update", "id": y_id,
                          "content": "y2"}, scope, store, observer, tmp_path,
                          Stub())  # type: ignore[arg-type]
    refresh_rechecks(state, sidecar, key)
    assert not state.get(key)["needs_recheck"]  # type: ignore[index]
    _fixture_memory_effect("delete_x", {"action": "delete", "id": x["memory_id"]},
                          scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    refresh_rechecks(state, sidecar, key)
    basis = state.get(key)
    assert basis is not None
    assert basis["adopted_evidence"] == [adopted]
    assert basis["recheck_reasons"][0]["kind"] == "deleted_or_tombstoned"
    assert basis["recheck_reasons"][0]["current_ref"] == f"memory:{x['memory_id']}@2"
    reason = basis["recheck_reasons"][0]
    assert acknowledgements(basis, None, {}, [{"role": "system",
                                                "content": canonical_json(reason)}], None) == []
    assert acknowledgements(basis, _set([adopted]), {}, [{"role": "system",
        "content": canonical_json(reason)}], None) == [reason]
    state.close()
    sidecar.close()


def test_controlled_fixture_uses_upstream_store_and_completed_run_replays_without_effect(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "fixture.json"
    freeze_path = tmp_path / "freeze.json"
    fixture = {
        "kind": "M1_MECHANISM_DIAGNOSTIC", "case_id": "generic",
        "user_id": "user", "task_id": "task",
        "seed_memory": {"content": "first"},
        "revision_update": {"after_public_index": 0, "content": "second"},
        "public_messages": ["Review.", "Review again.", "Record."],
        "business_tool_schema": {"type": "function", "function": {
            "name": "record", "description": "Record a local value.",
            "parameters": {"type": "object", "properties": {
                "value": {"type": "string"}}, "required": ["value"],
                "additionalProperties": False},
        }},
    }
    write_json(fixture_path, fixture)
    write_json(freeze_path, {"fixture_sha256": hashlib.sha256(
        fixture_path.read_bytes()).hexdigest(), "case_id": "generic", "public_messages": 3})
    responses = [
        _receipt({"decision_delta": None, "answer": "pending"}, "g1"),
        _receipt({"decision_delta": None, "answer": "pending"}, "g2"),
        _receipt({"decision_delta": None, "calls": [{"name": "record",
                 "arguments": {"value": "second"}}]}, "g3"),
        _receipt({"decision_delta": None, "answer": "done"}, "g4"),
    ]
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    store = ObservedStore(InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                         "fields": ["content"]}), observer)
    wire = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire.append(request.read())
        return httpx.Response(200, json=responses.pop(0))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer,
                              m1=M1Controller(state, observer))
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            output = tmp_path / "result"
            first = run_mechanism(fixture_path, freeze_path, output, "run", "m1",
                                  model, store, saver, observer)
            before = (len(sidecar.rows("operations")), len(state.rows("delta_receipts")),
                      len(wire), len(first["sim_world"]["records"]))
            second = run_mechanism(fixture_path, freeze_path, output, "run", "m1",
                                   model, store, saver, observer)
    assert second["status"] == "TERMINAL"
    assert before == (len(sidecar.rows("operations")), len(state.rows("delta_receipts")),
                      len(wire), len(second["sim_world"]["records"]))
    assert [row["content_json"] for row in sidecar.rows("revisions")] == [
        '"first"', '"second"']
    assert second["sim_world"]["records"] == [{"value": "second"}]
    assert len(first["business_calls"]) == 1
    state.close()
    sidecar.close()
