"""Offline mechanical checks for revision-checked full and literal State updates."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import MEMORY_NAMESPACE
from milai_lab.harness.contextual_artifacts import write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.writers import (
    create_writer_tools,
    execute_writes,
)
from milai_lab.runners import state_update_probe


def _bank() -> tuple[LocalStateBank, StateScope]:
    bank, scope = LocalStateBank(InMemoryStore()), StateScope("run", "replace", "alice")
    for source_id in ("prior", "change", "next"):
        bank.record_event(scope, {"id": source_id, "kind": "user", "actor": "alice",
                                  "tool_call_id": None,
                                  "content": ("actual change" if source_id == "next"
                                              else "actual " + source_id)})
    bank.acknowledge_events(scope, {"prior", "next"})
    return bank, scope


def _state(bank: LocalStateBank, scope: StateScope) -> str:
    receipt, invalid = bank.apply(scope, [{
        "id": None, "title": "one matter", "content": "count 5; door at 10:15; keep foam",
        "needs": ["confirm"], "evidence": ["prior"]}], {"prior"})
    assert not invalid
    return receipt[0]["id"]


def _update(state_id: str, *, revision: int = 1,
            mode: str = "patch", **fields: Any) -> dict[str, Any]:
    return {"id": state_id, "expected_revision": revision, "mode": mode, **fields}


def test_patch_is_atomic_preserves_omitted_fields_and_retracts_only_links() -> None:
    bank, scope = _bank()
    state_id = _state(bank, scope)
    edit = _update(state_id, patches=[
        {"old_text": "10:15", "new_text": "11:45"},
        {"old_text": "count 5", "new_text": "count 6"}],
        evidence=["change"], remove_evidence=["prior"])
    receipts, invalid = bank.apply(scope, [edit], {"change"}, batch_id="batch",
                                   edit_slots=[7], ack_events=False)
    assert not invalid and receipts[0]["status"] == "updated"
    state = bank.state(scope, state_id)
    assert state is not None
    assert state["content"] == "count 6; door at 11:45; keep foam"
    assert state["title"] == "one matter" and state["needs"] == ["confirm"]
    assert state["evidence_refs"] == ["change"]
    assert {"prior", "change"} <= set(state["dependency_source_ids"])
    assert {row["id"] for row in bank.events(scope)} == {"prior", "change", "next"}
    assert [row["id"] for row in bank.pending(scope)] == ["change"]


def test_literal_context_insertion_empty_replacement_and_noop() -> None:
    bank, scope = _bank()
    state_id = _state(bank, scope)
    no_change, invalid = bank.apply(scope, [_update(
        state_id, patches=[{"old_text": "foam", "new_text": "foam"}])],
        {"change"}, ack_events=False)
    assert not invalid and no_change[0]["status"] == "noop"
    assert bank.state(scope, state_id)["revision"] == 1
    changed, invalid = bank.apply(scope, [_update(state_id, patches=[
        {"old_text": "door at 10:15", "new_text": "door at 11:45; arrive early"},
        {"old_text": "; keep foam", "new_text": ""}])],
        {"change"}, ack_events=False)
    assert not invalid and changed[0]["status"] == "updated"
    assert bank.state(scope, state_id)["content"] == (
        "count 5; door at 11:45; arrive early")


@pytest.mark.parametrize("edit,reason", [
    ({"mode": "replace", "content": "new", "patches": []},
     "replace_arguments_invalid"),
    ({"mode": "patch", "patches": [{"old_text": "missing", "new_text": "x"}]},
     "patch_text_not_unique"),
    ({"mode": "patch", "patches": [{"old_text": "ount 5", "new_text": "ount 6"},
                                    {"old_text": "count 5", "new_text": "count 6"}]},
     "patch_spans_overlap"),
    ({"mode": "patch", "patches": [{"old_text": "", "new_text": "x"}]},
     "patch_arguments_invalid"),
    ({"mode": "patch", "patches": [{"old_text": "foam", "new_text": "x"}],
      "evidence": ["change"], "remove_evidence": ["change"]},
     "explicit_update_invalid"),
])
def test_invalid_update_is_one_state_zero_write(
    edit: dict[str, Any], reason: str,
) -> None:
    bank, scope = _bank()
    state_id = _state(bank, scope)
    before = bank.state(scope, state_id)
    puts = bank.store_stats()["put"]["calls"]
    receipts, invalid = bank.apply(scope, [{"id": state_id,
                                           "expected_revision": 1, **edit}],
                                   {"change"}, ack_events=False)
    assert invalid and receipts == [{"id": state_id,
                                     "status": "skipped_invalid_edit", "reason": reason}]
    assert bank.state(scope, state_id) == before
    assert bank.store_stats()["put"]["calls"] == puts
    assert [row["id"] for row in bank.pending(scope)] == ["change"]


def test_revision_noop_same_slot_replay_and_distinct_event() -> None:
    bank, scope = _bank()
    state_id = _state(bank, scope)
    patch = _update(state_id, patches=[{"old_text": "10:15", "new_text": "11:45"}])
    first, invalid = bank.apply(scope, [patch], {"change"}, batch_id="batch",
                                edit_slots=[4], ack_events=False)
    assert not invalid and first[0]["revision"] == 2
    replay, invalid = bank.apply(scope, [patch], {"change"}, batch_id="batch",
                                 edit_slots=[4], ack_events=False)
    assert not invalid and replay[0]["status"] == "noop"
    assert replay[0]["replayed"] is True and bank.state(scope, state_id)["revision"] == 2
    switched, invalid = bank.apply(scope, [_update(
        state_id, mode="replace", content="an alternative full proposal")],
        {"change"}, batch_id="batch", edit_slots=[4], ack_events=False)
    assert not invalid and switched[0]["status"] == "noop"
    assert switched[0]["replayed"] is True
    stale, invalid = bank.apply(scope, [patch], {"change"}, batch_id="other",
                                edit_slots=[4], ack_events=False)
    assert invalid and stale[0]["reason"] == "revision_conflict"
    same_text_new_id = _update(state_id, revision=2, mode="replace",
                               content="count 5; door at 11:45; keep foam")
    noop, invalid = bank.apply(scope, [same_text_new_id], {"next"},
                               batch_id="new-output", edit_slots=[4])
    assert not invalid and noop[0]["status"] == "noop"
    assert bank.state(scope, state_id)["revision"] == 2
    bank.record_event(scope, {"id": "fresh-id", "kind": "user", "actor": "alice",
                              "tool_call_id": None, "content": "actual change"})
    fresh, invalid = bank.apply(scope, [_update(
        state_id, revision=2, mode="replace",
        content="count 6; door at 11:45; keep foam")],
        {"fresh-id"}, batch_id="fresh-output", edit_slots=[4])
    assert not invalid and fresh[0]["status"] == "updated"
    assert bank.state(scope, state_id)["revision"] == 3


def test_duplicate_span_wrong_revision_and_cross_state_partial_success() -> None:
    bank, scope = _bank()
    state_id = _state(bank, scope)
    bank.apply(scope, [{"id": state_id, "content": "same same; keep foam"}],
               set(), ack_events=False)
    second, invalid = bank.apply(scope, [{"id": None, "title": "independent",
                                         "content": "door 10:15"}], set())
    assert not invalid
    second_id = second[0]["id"]
    edits = [
        _update(state_id, revision=2, patches=[{"old_text": "same",
                                                "new_text": "other"}]),
        _update(second_id, patches=[{"old_text": "10:15",
                                    "new_text": "11:45"}]),
    ]
    receipts, invalid = bank.apply(scope, edits, {"change"}, ack_events=False)
    assert invalid and receipts[0]["reason"] == "patch_text_not_unique"
    assert receipts[1]["status"] == "updated"
    assert bank.state(scope, state_id)["content"] == "same same; keep foam"
    assert bank.state(scope, second_id)["content"] == "door 11:45"


def test_explicit_tool_contract_and_real_executor_rejections() -> None:
    bank, scope = _bank()
    state_id = _state(bank, scope)
    legacy = create_writer_tools(bank, MEMORY_NAMESPACE)
    replace = create_writer_tools(bank, MEMORY_NAMESPACE,
                                  state_update_contract="replace")
    patch = create_writer_tools(bank, MEMORY_NAMESPACE,
                                state_update_contract="patch_or_replace")
    old_schema = convert_to_openai_tool(legacy.manage_state)["function"]["parameters"]
    replace_schema = convert_to_openai_tool(replace.manage_state)["function"]["parameters"]
    patch_schema = convert_to_openai_tool(patch.manage_state)["function"]["parameters"]
    assert "expected_revision" not in old_schema["properties"]
    assert "patches" not in replace_schema["properties"]
    assert {"old_text", "new_text"} <= set(
        patch_schema["properties"]["patches"]["anyOf"][0]["items"]["required"])
    config = {"configurable": {"foundation_run_id": "run", "arm_id": "replace",
                               "user_id": "alice", "workspace_id": "default"}}
    bad = execute_writes(replace, [{"name": "manage_state", "arguments": {
        "action": "update", "id": state_id, "expected_revision": 1,
        "mode": "replace", "content": "wrong", "patches": []}}],
        config=config, scope=scope, batch_id="bad", event_ids={"change"})
    assert bad.status == "PARTIAL_REJECTED"
    assert json.loads(str(bad.receipts[0].content))["status"] == "invalid_arguments"
    assert bank.state(scope, state_id)["content"].startswith("count 5")
    good = execute_writes(replace, [{"name": "manage_state", "arguments": {
        "action": "update", "id": state_id, "expected_revision": 1,
        "mode": "replace", "content": "count 5; door at 11:45; keep foam"}}],
        config=config, scope=scope, batch_id="good", event_ids={"change"})
    assert good.status == "APPLIED"
    assert bank.state(scope, state_id)["revision"] == 2
    assert bank.pending(scope) == []
    fallback = execute_writes(patch, [{"name": "manage_state", "arguments": {
        "action": "update", "id": state_id, "expected_revision": 2,
        "mode": "replace", "content": "count 6; door at 11:45; keep foam"}}],
        config=config, scope=scope, batch_id="fallback", event_ids={"next"})
    assert fallback.status == "APPLIED"
    assert bank.state(scope, state_id)["revision"] == 3


class ControlReplies:
    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {"id": "generation-one", "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(self.answer)}}]}


def test_runner_one_real_proposal_executes_and_reports_actual_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = {"user_id": "alice", "states": [{
        "id": "state-id", "title": "matter", "content": "door 10:15",
        "needs": [], "evidence_refs": [], "revision": 1, "archived": False}],
        "source_events": [{"id": "change", "kind": "user", "actor": "alice",
                           "tool_call_id": None, "content": "door now 11:45"}],
        "pending_event_ids": ["change"], "current_task": "door now 11:45",
        "raw_history": [{"role": "user", "content": "door now 11:45"}]}
    answer = {"calls": [{"name": "manage_state", "arguments": {
        "action": "update", "id": "state-id", "expected_revision": 1,
        "mode": "patch", "patches": [{"old_text": "10:15",
                                       "new_text": "11:45"}]}}]}
    replies = ControlReplies(answer)

    @contextmanager
    def control_client(*_args: Any, **_kwargs: Any) -> Any:
        yield replies

    monkeypatch.setattr(state_update_probe, "VLLMClient", control_client)
    runtime = SimpleNamespace(store=InMemoryStore(), model=SimpleNamespace(
        client=SimpleNamespace(emit=None, budget=None, capacity=None)))
    config = {"host": {"base_url": "http://mock/v1/", "model": "mock",
                       "tool_mode": "json_action", "max_tokens": 4096,
                       "max_calls": 12},
              "control": {"max_tokens": 2048, "max_calls_per_message": 13,
                          "max_states": 32, "max_events": 256,
                          "max_pending_batch": 24},
              "budget_path": str(tmp_path / "budget.json")}
    result = state_update_probe._run_one(
        case, {"job_id": "job", "update_contract": "patch_or_replace"}, config,
        runtime, tmp_path, "run", "patch_or_replace")
    assert len(replies.calls) == 1
    payload = json.loads(replies.calls[0]["messages"][1]["content"])
    assert payload["states"][0]["revision"] == 1
    assert payload["new_observations"][0]["id"] == "change"
    assert result["status"] == "APPLIED"
    assert result["states_after"][0]["content"] == "door 11:45"
    assert result["pending_event_ids"] == []
    assert result["store_stats"]["put"]["calls"] >= 3
    assert result["control_capacity"] == {"job": 1}


def test_prepare_is_zero_model_ordered_and_identity_bound(tmp_path: Path) -> None:
    lab = Path(__file__).resolve().parents[2]
    config_path, input_path = tmp_path / "config.json", tmp_path / "inputs.json"
    config = {"host": {"tool_mode": "json_action", "max_calls": 12,
                       "max_tokens": 4096},
              "control": {"max_calls_per_message": 13, "max_tokens": 2048},
              "embedding": {}, "capacity": {},
              "budget_path": str(tmp_path / "budget.json")}
    cases = [{"case_id": "case", "user_id": "alice", "states": [{
        "id": "s", "title": "matter", "content": "old", "needs": [],
        "evidence_refs": [], "revision": 1, "archived": False}],
        "source_events": [{"id": "e", "kind": "user", "actor": "alice",
                           "tool_call_id": None, "content": "new"}],
        "pending_event_ids": ["e"], "current_task": "new",
        "raw_history": [{"role": "user", "content": "new"}]}]
    inputs = {"kind": "MILAI_LOCAL_UPDATE_INPUTS", "cases": cases,
              "jobs": [{"job_id": "first", "case_id": "case",
                        "update_contract": "replace"},
                       {"job_id": "second", "case_id": "case",
                        "update_contract": "patch_or_replace"}]}
    write_json(config_path, config)
    write_json(input_path, inputs)
    args = SimpleNamespace(config=config_path, inputs=input_path, run="run",
                           runtime_root=tmp_path / "runtime",
                           output=tmp_path / "prepared.json")
    prepared = state_update_probe.prepare(args, lab_root=lab)
    assert prepared["status"] == "PREPARED_ZERO_MODEL" and prepared["jobs"] == 2
    assert not (args.runtime_root / "jobs").exists()
    inputs["jobs"].reverse()
    write_json(input_path, inputs)
    with pytest.raises(ValueError, match="STATE_UPDATE_RUN_IDENTITY_CHANGED"):
        state_update_probe.prepare(args, lab_root=lab)
