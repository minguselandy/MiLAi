"""Focused zero-model checks for v18 proposition and recheck completion."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
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
from milai_lab.methods.milai_m1.decision_basis import DecisionDeltaError, validate_delta
from milai_lab.methods.milai_m1.recheck import completion_proof, refresh_rechecks
from milai_lab.methods.milai_m1.state_store import DecisionBasisStore
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import (
    IncompleteChatResponse,
    VLLMChatModel,
    _action_schema,
)
from milai_lab.runners.langmem_foundation import BusinessActionJournal
from milai_lab.runners.langmem_m1_mechanism import _fixture_memory_effect, run_mechanism


class FixedEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


class Stub:
    client = type("Client", (), {"emit": None})()


def receipt(action: dict[str, Any], identity: str) -> dict[str, Any]:
    return {"id": identity, "model": "mock", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


def delta(refs: list[str], *, proposition: str = "Use the saved holding value.",
          outcome: str | None = None, status: str = "active") -> dict[str, Any]:
    return {"op": "set", "proposition": proposition,
            "action_scope": {"subject": "user", "item": "crate", "action_type": "record",
                             "critical_parameters": ["holding_value"]},
            "adopted_evidence": [{"ref": ref, "support_role": "supports_value"}
                                 for ref in refs],
            "unresolved_gap": None, "status": status, "recheck_outcome": outcome}


def binding(ref: str, *, sha: str = "sha", role: str = "supports_value") -> dict[str, Any]:
    return {"ref": ref, "kind": "memory", "content_sha256": sha,
            "request_id": "adopt-request", "delivery": "search_tool_message",
            "label": ref, "support_role": role}


def test_schema_reducer_and_old_state_format(tmp_path: Path) -> None:
    tool_schema = {"type": "function", "function": {"name": "record",
                   "parameters": {"type": "object", "properties": {}}}}
    schema = m1_action_schema(_action_schema([tool_schema], generation_only=True))
    for action in (
        {"decision_delta": None, "answer": "ordinary"},
        {"decision_delta": None,
         "calls": [{"name": "record", "arguments": {}}]},
        {"decision_delta": delta(["e0"]), "answer": "pending"},
        {"decision_delta": delta(["e0"], outcome="changed"),
         "calls": [{"name": "record", "arguments": {}}]},
        {"decision_delta": delta([], outcome="unresolved", status="deferred"),
         "calls": [{"name": "record", "arguments": {}}]},
        {"decision_delta": {"op": "clear"}, "answer": "done"},
        {"decision_delta": {"op": "clear", "clear_reason": "task_ended"},
         "answer": "cancelled"},
        {"decision_delta": {"op": "clear", "clear_reason": "recheck_completed",
                            "proposition": "Use revised value.",
                            "action_scope": delta([])["action_scope"],
                            "adopted_evidence": delta(["e1"])["adopted_evidence"],
                            "unresolved_gap": None, "recheck_outcome": "changed"},
         "answer": "done"},
    ):
        validate(action, schema)
        validate_delta(action["decision_delta"])
    with pytest.raises(ValidationError):
        validate({"decision_delta": {"op": "clear", "decision": "old label"},
                  "answer": "bad"}, schema)
    with pytest.raises(ValidationError):
        validate({"decision_delta": {"op": "clear", "clear_reason": "task_ended"},
                  "calls": [{"name": "record", "arguments": {}}]}, schema)
    for bad in (
        {**delta([]), "proposition": "  "},
        {**delta([]), "action_scope": {"subject": "user"}},
        {**delta(["e0"]), "adopted_evidence": [
            {"ref": "e0", "support_role": "invented"}]},
        {**delta([]), "action_scope": {**delta([])["action_scope"],
                                       "critical_parameters": ["a", "a"]}},
    ):
        with pytest.raises(DecisionDeltaError):
            validate_delta(bad)
    assert validate_delta({**delta([]), "unresolved_gap": "Which value is current?"})[
        "unresolved_gap"] == "Which value is current?"
    old = tmp_path / "v17.sqlite"
    with sqlite3.connect(old) as conn:
        conn.execute("CREATE TABLE bases(old_field TEXT)")
    with pytest.raises(ValueError, match="M1_STATE_FORMAT_MISMATCH"):
        DecisionBasisStore(old)
    current = DecisionBasisStore(tmp_path / "v18.sqlite")
    assert current.rows("m1_format")[0]["version"] == current.FORMAT
    assert current.rows("write_transactions") == []
    current.close()


def test_recheck_outcomes_exact_current_and_cold_replay(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    store = ObservedStore(InMemoryStore(), observer)
    scope = FoundationScope("run", "m1", "user", "episode")
    x = _fixture_memory_effect("seed:x", {"action": "create", "content": "value 4"},
                               scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    y = _fixture_memory_effect("seed:y", {"action": "create", "content": "other A"},
                               scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    x1 = f"memory:{x['memory_id']}@1"
    key = ("run", "m1", "user", "task")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    state.activate(key)
    first = delta([x1], proposition="Current value is 4.")
    first["adopted_evidence"][0]["ref"] = x1
    state.apply(key, "adopt-request", "g1", first, [binding(x1)], [], [])
    _fixture_memory_effect("update:y", {"action": "update", "id": y["memory_id"],
                                        "content": "other B"}, scope, store, observer,
                           tmp_path, Stub())  # type: ignore[arg-type]
    refresh_rechecks(state, sidecar, key)
    assert not state.get(key)["needs_recheck"]  # type: ignore[index]
    _fixture_memory_effect("update:x2", {"action": "update", "id": x["memory_id"],
                                         "content": "value 8"}, scope, store, observer,
                           tmp_path, Stub())  # type: ignore[arg-type]
    refresh_rechecks(state, sidecar, key)
    pending = state.get(key)
    assert pending is not None and pending["needs_recheck"]
    state.close()
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    assert state.get(key)["needs_recheck"]  # type: ignore[index]
    other_key = ("run", "m1", "user", "other-task")
    state.activate(other_key)
    assert state.get(other_key) is None
    assert state.get(key)["needs_recheck"]  # type: ignore[index]
    state.activate(key)
    pending = state.get(key)
    assert pending is not None and pending["needs_recheck"]
    y1 = f"memory:{y['memory_id']}@1"
    stale_y = binding(y1)
    with pytest.raises(DecisionDeltaError, match="DECISION_RECHECK_CURRENT_EVIDENCE_MISSING"):
        completion_proof(pending, delta([y1], proposition="Current value is 4.",
                                       outcome="retained"),
                         [stale_y], {y1: stale_y}, [], sidecar, key)
    with pytest.raises(DecisionDeltaError, match="DECISION_PENDING_CLEAR_INCOMPLETE"):
        completion_proof(pending, {"op": "clear"}, [], {}, [], sidecar, key)
    with pytest.raises(DecisionDeltaError, match="DECISION_PENDING_RECHECK_OUTCOME_MISSING"):
        completion_proof(pending, delta([x1]), [], {}, [], sidecar, key)
    assert completion_proof(pending, {"op": "clear", "clear_reason": "task_ended"},
                            [], {}, [], sidecar, key) == ([], [])
    unresolved = delta([x1], proposition="Current value is 4.",
                       outcome="unresolved", status="deferred")
    assert completion_proof(pending, unresolved, [], {}, [], sidecar, key) == ([], [])
    state.apply(key, "unresolved", "g2", unresolved, [binding(x1)], [], [])
    assert state.get(key)["needs_recheck"]  # type: ignore[index]
    assert state.get(key)["host_status"] == "deferred"  # type: ignore[index]
    _fixture_memory_effect("update:x3", {"action": "update", "id": x["memory_id"],
                                         "content": "value 9"}, scope, store, observer,
                           tmp_path, Stub())  # type: ignore[arg-type]
    refresh_rechecks(state, sidecar, key)
    pending = state.get(key)
    assert pending is not None and len(pending["recheck_reasons"]) == 2
    x3 = f"memory:{x['memory_id']}@3"
    row = next(item for item in sidecar.rows("revisions")
               if item["memory_id"] == x["memory_id"] and item["revision"] == 3)
    current = binding(x3, sha=row["content_sha256"])
    changed = delta([x3], proposition="Current value is 9.", outcome="changed")
    ack, proof = completion_proof(pending, changed, [current], {x3: current}, [],
                                  sidecar, key)
    assert len(ack) == 2 and proof == [x3]
    assert state.apply(key, "complete", "g3", changed, [current], ack, proof) == "SET"
    assert not state.get(key)["needs_recheck"]  # type: ignore[index]
    assert state.get(key)["adopted_evidence"] == changed["adopted_evidence"]  # type: ignore[index]
    before = len(state.rows("write_transactions"))
    assert state.apply(key, "complete", "g3", changed, [current], ack, proof) == "SET"
    assert len(state.rows("write_transactions")) == before
    refresh_rechecks(state, sidecar, key)
    assert not state.get(key)["needs_recheck"]  # type: ignore[index]
    state.close()
    restored = DecisionBasisStore(tmp_path / "basis.sqlite")
    assert restored.get(key)["proposition"] == "Current value is 9."  # type: ignore[index]
    assert restored.get(key)["recheck_outcome"] == "changed"  # type: ignore[index]
    assert len(restored.rows("write_transactions")) == before
    restored.close()
    sidecar.close()


def test_retained_clear_and_tombstone_contract(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    store = ObservedStore(InMemoryStore(), observer)
    scope = FoundationScope("run", "m1", "user", "episode")
    x = _fixture_memory_effect("seed", {"action": "create", "content": "same value; note A"},
                               scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    key = ("run", "m1", "user", "task")
    x1 = f"memory:{x['memory_id']}@1"
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    state.activate(key)
    original = delta([x1], proposition="Use value 8.")
    state.apply(key, "first", "g1", original, [binding(x1)], [], [])
    _fixture_memory_effect("update", {"action": "update", "id": x["memory_id"],
                                      "content": "same value; note B"},
                           scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    refresh_rechecks(state, sidecar, key)
    pending = state.get(key)
    assert pending is not None
    with pytest.raises(DecisionDeltaError, match="DECISION_RECHECK_CURRENT_EVIDENCE_MISSING"):
        completion_proof(pending, delta([x1], proposition="Use value 8.",
                                       outcome="retained"),
                         [binding(x1)], {x1: binding(x1)}, [], sidecar, key)
    x2 = f"memory:{x['memory_id']}@2"
    revision = next(item for item in sidecar.rows("revisions")
                    if item["memory_id"] == x["memory_id"] and item["revision"] == 2)
    current = binding(x2, sha=revision["content_sha256"])
    retained = delta([x2], proposition="Use value 8.", outcome="retained")
    ack, proof = completion_proof(pending, retained, [current], {x2: current}, [],
                                  sidecar, key)
    assert proof == [x2]
    assert state.apply(key, "retained", "g2", retained, [current], ack, proof) == "SET"
    assert not state.get(key)["needs_recheck"]  # type: ignore[index]
    refresh_rechecks(state, sidecar, key)
    assert not state.get(key)["needs_recheck"]  # type: ignore[index]
    _fixture_memory_effect("update-three", {"action": "update", "id": x["memory_id"],
                                            "content": "same value; note C"},
                           scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    refresh_rechecks(state, sidecar, key)
    pending = state.get(key)
    assert pending is not None
    assert [reason["current_ref"] for reason in pending["recheck_reasons"]] == [
        f"memory:{x['memory_id']}@3"]
    x3 = f"memory:{x['memory_id']}@3"
    revision3 = next(item for item in sidecar.rows("revisions")
                     if item["memory_id"] == x["memory_id"] and item["revision"] == 3)
    current3 = binding(x3, sha=revision3["content_sha256"])
    retained3 = delta([x3], proposition="Use value 8.", outcome="retained")
    ack3, proof3 = completion_proof(pending, retained3, [current3], {x3: current3}, [],
                                    sidecar, key)
    state.apply(key, "retained-three", "g2b", retained3, [current3], ack3, proof3)
    assert not state.get(key)["needs_recheck"]  # type: ignore[index]
    _fixture_memory_effect("delete", {"action": "delete", "id": x["memory_id"]},
                           scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    refresh_rechecks(state, sidecar, key)
    pending = state.get(key)
    assert pending is not None
    reason = pending["recheck_reasons"][0]
    assert reason["kind"] == "deleted_or_tombstoned"
    obs = {"ref": "observation:new", "kind": "observation", "content_sha256": "new-sha",
           "request_id": "new-request", "delivery": "current_user",
           "support_role": "constrains_applicability"}
    cleared = {"op": "clear", "clear_reason": "recheck_completed",
               "proposition": "Do not use deleted instruction.",
               "action_scope": original["action_scope"],
               "adopted_evidence": [{"ref": obs["ref"],
                                     "support_role": obs["support_role"]}],
               "unresolved_gap": None, "recheck_outcome": "changed"}
    ack, proof = completion_proof(
        pending, cleared, [obs], {obs["ref"]: obs},
        [{"role": "system", "content": canonical_json(reason)}], sidecar, key,
    )
    assert ack == [reason] and proof == [obs["ref"]]
    assert state.apply(key, "clear-after-complete", "g3", cleared, [obs], ack, proof) \
        == "CLEARED_RECHECK_COMPLETED"
    assert state.get(key) is None
    assert [row["event"] for row in state.rows("events")].count("RECHECK_COMPLETED") == 3
    ended_key = ("run", "m1", "user", "ended-task")
    state.activate(ended_key)
    state.apply(ended_key, "ended-adopt", "g4", original, [binding(x1)], [], [])
    refresh_rechecks(state, sidecar, ended_key)
    assert state.get(ended_key)["needs_recheck"]  # type: ignore[index]
    assert state.apply(ended_key, "ended-clear", "g5",
                       {"op": "clear", "clear_reason": "task_ended"}, [], [], []) \
        == "CLEARED_TASK_ENDED"
    assert state.get(ended_key) is None
    assert [row["event"] for row in state.rows("events")].count(
        "RECHECK_ABANDONED_TASK_ENDED") == 1
    state.close()
    sidecar.close()


def test_real_graph_changed_recheck_and_completed_replay(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    controller = M1Controller(state, observer)
    scope = FoundationScope("run", "m1", "user", "episode")
    store = ObservedStore(InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                         "fields": ["content"]}), observer)
    seed = _fixture_memory_effect("seed", {"action": "create", "content": "hold 4 C"},
                                  scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    world: list[str] = []

    @tool
    def record(value: str) -> str:
        """Record a local holding value."""
        world.append(value)
        return value

    turns = 0
    wire: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal turns
        raw = request.read()
        wire.append(raw)
        messages = json.loads(raw)["messages"]
        system = messages[0]["content"]
        turns += 1
        if turns in (1, 3):
            action = {"decision_delta": None, "calls": [
                {"name": "search_memory", "arguments": {"query": "holding", "limit": 1}}]}
        elif turns in (2, 4):
            version = 1 if turns == 2 else 2
            match = re.search(rf"(e\d+): search_memory result [^\n]*@{version}", system)
            assert match is not None
            action = {"decision_delta": delta([match.group(1)],
                      proposition=f"Use {4 if version == 1 else 8} C.",
                      outcome="changed" if version == 2 else None),
                      "answer": "Pending approval."}
        elif turns == 5:
            action = {"decision_delta": None, "calls": [
                {"name": "record", "arguments": {"value": "8 C"}}]}
        else:
            action = {"decision_delta": None, "answer": "Recorded."}
        return httpx.Response(200, json=receipt(action, f"g{turns}"))

    journal = BusinessActionJournal(tmp_path / "business.json", ["record"])
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer, m1=controller)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver, [record],
                                business_call_wrapper=journal, observer=observer)
            invoke_public_message(agent, model, scope, "What is saved?", "task")
            assert state.get(("run", "m1", "user", "task"))["adopted_evidence"][0]["ref"] \
                == f"memory:{seed['memory_id']}@1"  # type: ignore[index]
            _fixture_memory_effect("external_update", {"action": "update",
                                   "id": seed["memory_id"], "content": "hold 8 C"},
                                   scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
            invoke_public_message(agent, model, scope, "Still pending.", "task")
            basis = state.get(("run", "m1", "user", "task"))
            assert basis is not None and basis["proposition"] == "Use 8 C."
            assert basis["adopted_evidence"][0]["ref"] == f"memory:{seed['memory_id']}@2"
            assert not basis["needs_recheck"]
            messages = invoke_public_message(agent, model, scope, "Approve record.", "task")
            before = (len(wire), len(sidecar.rows("operations")),
                      len(state.rows("delta_receipts")),
                      len(state.rows("write_transactions")), len(world))
            replayed = resume_public_message(agent, model, scope, "task")
            assert replayed[-1].content == messages[-1].content
            assert before == (len(wire), len(sidecar.rows("operations")),
                              len(state.rows("delta_receipts")),
                              len(state.rows("write_transactions")), len(world))
    assert world == ["8 C"]
    assert len(journal.calls_for_thread(scope.config()["configurable"]["thread_id"])) == 1
    assert [row["event"] for row in state.rows("events")].count("RECHECK_COMPLETED") == 1
    assert [row["event"] for row in state.rows("events")].count("RECHECK_PROJECTED") >= 1
    state.close()
    sidecar.close()


@pytest.mark.parametrize("mode", ["invalid_clear", "invalid_task_ended", "unresolved"])
def test_pending_protocol_or_unresolved_business_action(tmp_path: Path, mode: str) -> None:
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    scope = FoundationScope("run", "m1", "user", "episode")
    store = ObservedStore(InMemoryStore(index={"dims": 2, "embed": FixedEmbeddings(),
                                         "fields": ["content"]}), observer)
    seed = _fixture_memory_effect("seed", {"action": "create", "content": "old"},
                                  scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
    world: list[str] = []

    @tool
    def record(value: str) -> str:
        """Record a local value."""
        world.append(value)
        return value

    responses = [
        receipt({"decision_delta": None, "calls": [{"name": "search_memory",
                 "arguments": {"query": "old", "limit": 1}}]}, "g1"),
        receipt({"decision_delta": delta(["e1"], proposition="Use old value."),
                 "answer": "Pending."}, "g2"),
    ]
    if mode in {"invalid_clear", "invalid_task_ended"}:
        clear = ({"op": "clear"} if mode == "invalid_clear"
                 else {"op": "clear", "clear_reason": "task_ended"})
        responses.append(receipt({"decision_delta": clear, "calls": [
            {"name": "record", "arguments": {"value": "old"}}]}, "g3"))
    else:
        responses.extend([
            receipt({"decision_delta": delta([], proposition="Use old value.",
                                             outcome="unresolved", status="deferred"),
                     "calls": [{"name": "record", "arguments": {"value": "old"}}]}, "g3"),
            receipt({"decision_delta": None, "answer": "Recorded while unresolved."}, "g4"),
        ])
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(200, json=responses.pop(0))),
                    emit=observer.capture_provider_event) as client:
        model = VLLMChatModel(client=client, observer=observer,
                              m1=M1Controller(state, observer))
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            agent = build_agent(model, store, saver, [record], observer=observer)
            invoke_public_message(agent, model, scope, "What is saved?", "task")
            _fixture_memory_effect("external_update", {"action": "update",
                                   "id": seed["memory_id"], "content": "new"},
                                   scope, store, observer, tmp_path, Stub())  # type: ignore[arg-type]
            if mode in {"invalid_clear", "invalid_task_ended"}:
                # The v18 calls schema rejects task_ended before M1 commit runs.
                expected = (DecisionDeltaError if mode == "invalid_clear"
                            else IncompleteChatResponse)
                with pytest.raises(expected,
                                   match=("DECISION_PENDING_CLEAR_INCOMPLETE"
                                          if mode == "invalid_clear"
                                          else "JSON_ACTION_SCHEMA_INVALID")):
                    invoke_public_message(agent, model, scope, "Still pending.", "task")
                assert world == []
                assert state.rows("delta_receipts")[-1]["status"] == "ERROR"
            else:
                invoke_public_message(agent, model, scope, "Still pending.", "task")
                assert world == ["old"]
                basis = state.get(("run", "m1", "user", "task"))
                assert basis is not None and basis["host_status"] == "deferred"
                assert basis["needs_recheck"]
    state.close()
    sidecar.close()


def test_multi_seed_fixture_runner_and_completed_replay(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    freeze_path = tmp_path / "freeze.json"
    fixture = {
        "kind": "M1_V18_RECHECK_DIAGNOSTIC", "case_id": "generic",
        "user_id": "user", "task_id": "task",
        "seed_memories": [{"name": "primary", "content": "one"},
                          {"name": "auxiliary", "content": "other"}],
        "revision_update": {"after_public_index": 0, "target": "auxiliary",
                            "content": "other revised"},
        "public_messages": ["Review.", "Continue.", "Done."],
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
    responses = [receipt({"decision_delta": None, "answer": "pending"}, f"g{i}")
                 for i in range(3)]
    sidecar = RevisionSidecar(tmp_path / "b1.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "m1")
    state = DecisionBasisStore(tmp_path / "basis.sqlite")
    store = ObservedStore(InMemoryStore(), observer)
    wire: list[bytes] = []

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
    assert len(sidecar.rows("revisions")) == 3
    assert {row["content_json"] for row in sidecar.rows("revisions")} == {
        '"one"', '"other"', '"other revised"'}
    assert second["sim_world"]["records"] == []
    assert len(wire) == 3
    state.close()
    sidecar.close()
