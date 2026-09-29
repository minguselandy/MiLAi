"""Offline checks for explicit writer cadence and real graph tool receipts."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.application.journal import BusinessActionJournal
from milai_lab.application.tools import BUSINESS_NAMES
from milai_lab.application.world import ApplicationWorld
from milai_lab.baselines.langmem_agent import MEMORY_NAMESPACE, FoundationScope
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel as VLLMChatModel
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import LocalStateController
from milai_lab.methods.local_state_attention.writers import create_writer_tools
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.langmem_application_runtime import ApplicationRuntime
from milai_lab.runners.writer_policy import (
    _cases_and_jobs,
    _seed,
    prepare,
    run_job,
    run_writer_policy_turn,
)


class ControlReplies:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.payloads: list[dict[str, Any]] = []

    def chat(self, messages: Any, **_kwargs: Any) -> dict[str, Any]:
        payload = json.loads(messages[1]["content"])
        self.payloads.append(payload)
        answer = self.replies.pop(0)
        if callable(answer):
            answer = answer(payload)
        return {"id": f"control-{len(self.payloads)}", "choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(answer)}}]}


@contextmanager
def _runtime(tmp_path: Path, actions: list[dict[str, Any]],
             requests: list[dict[str, Any]], *, max_calls: int = 12) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json={"id": f"host-{len(requests)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(actions.pop(0))}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5,
                      "total_tokens": 13}})

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        model = VLLMChatModel(client=client,
                              capacity_path=tmp_path / "message-capacity.json",
                              max_calls_per_message=max_calls)
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            yield ApplicationRuntime(model, InMemoryStore(), saver, None)  # type: ignore[arg-type]


def _turn(tmp_path: Path, policy: str, control: list[Any], host: list[dict[str, Any]],
          *, seed: Callable[[Any, LocalStateBank, StateScope], None] | None = None,
          ) -> tuple[dict[str, Any], ControlReplies, list[dict[str, Any]], LocalStateBank]:
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, host, requests) as runtime:
        bank = LocalStateBank(runtime.store)
        scope = StateScope("run", policy, "alice")
        bank.record_event(scope, {"id": "source-current", "kind": "user",
                                  "actor": "alice", "tool_call_id": None,
                                  "content": "Remember the current plan."})
        if seed is not None:
            seed(runtime.store, bank, scope)
        replies = ControlReplies(control)
        controller = LocalStateController(
            bank, replies, capacity_path=tmp_path / "control-capacity.json",
            max_calls_per_message=13)  # type: ignore[arg-type]
        tools = create_writer_tools(bank, MEMORY_NAMESPACE)
        world = ApplicationWorld(tmp_path / "business.sqlite", False)
        journal = BusinessActionJournal(tmp_path / "journal.json", BUSINESS_NAMES)
        try:
            result = run_writer_policy_turn(
                policy, [HumanMessage(content="Remember the current plan.")],
                ({"role": "user", "content": "Remember the current plan."},),
                runtime, FoundationScope("run", policy, "alice", "episode"),
                world, journal, bank, tools, controller)
            result["memory"] = [row.value for row in runtime.store.search(
                ("langmem", "run", policy, "alice"))]
            return result, replies, requests, bank
        finally:
            world.close()


def test_host_both_uses_actual_toolnode_and_terminal_ack_only_for_seen_sources(
    tmp_path: Path,
) -> None:
    output, control, requests, bank = _turn(tmp_path, "host_both", [], [
        {"calls": [
            {"name": "manage_memory", "arguments": {"action": "create",
                                                    "content": "record M"}},
            {"name": "manage_state", "arguments": {"action": "create",
                                                   "title": "record S", "content": "state S",
                                                   "evidence": ["source-current"]}}]},
        {"answer": "Both receipts observed."}])
    assert len(requests) == 2 and not control.payloads
    assert [row["name"] for row in output["host_tool_receipts"]] == [
        "manage_memory", "manage_state"]
    assert output["memory"] == [{"content": "record M"}]
    assert output["states"][0]["content"] == "state S"
    assert output["pending_event_ids"] == []
    assert output["host_acknowledged_event_ids"][0] == "source-current"
    assert len(output["host_acknowledged_event_ids"]) == 3
    scope = StateScope("run", "host_both", "alice")
    bank.record_event(scope, {"id": "next-distinct-id", "kind": "user",
                              "actor": "alice", "tool_call_id": None,
                              "content": "Remember the current plan."})
    assert [row["id"] for row in bank.pending(scope)] == ["next-distinct-id"]


def test_boundary_reads_then_writes_and_host_trigger_returns_real_receipts(
    tmp_path: Path,
) -> None:
    output, control, requests, _ = _turn(tmp_path, "boundary_both", [
        {"calls": [{"name": "read_record", "arguments": {
            "target_kind": "state", "id": "missing"}}]},
        {"calls": [{"name": "manage_state", "arguments": {
            "action": "create", "title": "actual", "content": "from source",
            "evidence": ["source-current"]}}]},
        {"calls": [{"name": "manage_memory", "arguments": {
            "action": "create", "content": "later memory"}}]},
    ], [{"calls": [{"name": "maintain_records", "arguments": {
        "reason": "Please reconsider the actual records."}}]},
        {"answer": "Maintenance receipts returned."}])
    assert len(control.payloads) == 3
    assert control.payloads[1]["actual_tool_receipts"][0]["status"] == "error"
    assert control.payloads[2]["host_maintenance_request_non_evidence"] == (
        "Please reconsider the actual records.")
    assert [row["id"] for row in control.payloads[2]["source_event_catalog"]] == [
        "source-current"]
    assert output["initial_boundary"]["status"] == "APPLIED"
    assert output["initial_boundary"]["acknowledged_event_ids"] == ["source-current"]
    assert output["memory"] == [{"content": "later memory"}]
    trigger = next(row for row in output["host_tool_receipts"]
                   if row["name"] == "maintain_records")
    assert json.loads(trigger["content"])["receipts"][0]["name"] == "manage_memory"
    assert "maintain_records" in requests[0]["messages"][0]["content"]
    assert "Actual automatic maintenance result" in requests[0]["messages"][0]["content"]
    assert '"status": "APPLIED"' in requests[0]["messages"][0]["content"]


def test_overlap_waits_for_host_answer_then_uses_actual_memory_receipt(
    tmp_path: Path,
) -> None:
    output, control, requests, _ = _turn(tmp_path, "overlap", [
        lambda payload: {"calls": [{"name": "manage_state", "arguments": {
            "action": "create", "title": "after memory", "content": "actual receipt",
            "evidence": [payload["new_observations"][-1]["id"]]}}]},
    ], [{"calls": [{"name": "manage_memory", "arguments": {
        "action": "create", "content": "host fact"}}]},
        {"answer": "Host answered first."}])
    assert len(requests) == 2 and len(control.payloads) == 1
    assert output["answer"] == "Host answered first."
    assert "created" in control.payloads[0]["actual_tool_receipts"][-1]["content"]
    assert output["post_turn_boundary"]["status"] == "APPLIED"
    assert output["states"][0]["content"] == "actual receipt"
    assert output["pending_event_ids"] == []


def test_empty_boundary_is_no_change_not_host_answer(tmp_path: Path) -> None:
    output, control, requests, _ = _turn(tmp_path, "boundary_both",
                                           [{"calls": []}], [{"answer": "Host answer."}])
    assert output["initial_boundary"]["status"] == "NO_CHANGE"
    assert output["answer"] == "Host answer."
    assert len(control.payloads) == len(requests) == 1


def test_native_host_policy_keeps_the_original_memory_business_catalog(
    tmp_path: Path,
) -> None:
    output, control, requests, _ = _turn(
        tmp_path, "native_host", [], [{"answer": "Ordinary reply."}])
    assert output["answer"] == "Ordinary reply."
    assert control.payloads == []
    system = requests[0]["messages"][0]["content"]
    assert "Scoped State directory" not in system
    assert "ordinary memory records" not in system
    names = {branch["properties"]["name"]["const"] for branch in
             requests[0]["response_format"]["json_schema"]["schema"]["oneOf"][1][
                 "properties"]["calls"]["items"]["oneOf"]}
    assert names == {"manage_memory", "search_memory", *BUSINESS_NAMES}


@pytest.mark.parametrize("policy", ["host_both", "boundary_both", "overlap"])
def test_three_writer_policies_receive_same_actual_record_ids_bodies_and_sources(
    tmp_path: Path, policy: str,
) -> None:
    def seed(store: Any, _bank: LocalStateBank, scope: StateScope) -> None:
        store.put(("langmem", scope.run_id, scope.arm_id, "alice"), "memory-id",
                  {"content": "actual ordinary body"})
        store.put(scope.namespace("states"), "state-id", {
            "id": "state-id", "title": "actual State title", "content": "actual State body",
            "needs": [], "evidence_refs": ["source-current"],
            "revision": 2, "archived": False}, index=False)

    control = [] if policy == "host_both" else [{"calls": []}]
    output, replies, requests, _ = _turn(
        tmp_path, policy, control, [{"answer": "Host answer."}], seed=seed)
    system = requests[0]["messages"][0]["content"]
    for fragment in ("memory-id", "actual ordinary body", "state-id",
                     "actual State body", "source-current",
                     "Remember the current plan."):
        assert fragment in system
    assert '"revision": 2' in system
    policy_instruction = {"host_both": "You own ordinary-memory and local-State writes",
                          "boundary_both": "An automatic writer boundary ran",
                          "overlap": "One separate local-State maintenance boundary runs"}
    assert policy_instruction[policy] in system
    assert len(replies.payloads) == (0 if policy == "host_both" else 1)
    if replies.payloads:
        payload = replies.payloads[0]
        assert payload["ordinary_memory_records"][0]["id"] == "memory-id"
        assert payload["source_event_catalog"][0]["content"] == (
            "Remember the current plan.")
    if policy == "boundary_both":
        assert output["initial_boundary"]["status"] == "NO_CHANGE"
        assert '"status": "NO_CHANGE"' in system


def test_host_both_actual_update_nochange_then_delete_and_owner_scope(
    tmp_path: Path,
) -> None:
    memory_id = str(uuid.uuid4())

    def seed(store: Any, _bank: LocalStateBank, scope: StateScope) -> None:
        store.put(("langmem", scope.run_id, scope.arm_id, "alice"), memory_id,
                  {"content": "unchanged"})
        store.put(scope.namespace("states"), "state-id", {
            "id": "state-id", "title": "record", "content": "same",
            "needs": [], "evidence_refs": ["source-current"],
            "revision": 1, "archived": False}, index=False)
        store.put(("langmem", scope.run_id, scope.arm_id, "bob"), memory_id,
                  {"content": "Bob's record"})

    output, _, requests, bank = _turn(tmp_path, "host_both", [], [
        {"calls": [
            {"name": "manage_memory", "arguments": {"action": "update",
                "id": memory_id, "content": "unchanged"}},
            {"name": "manage_state", "arguments": {"action": "update",
                "id": "state-id", "content": "same"}}]},
        {"calls": [
            {"name": "manage_memory", "arguments": {"action": "delete", "id": memory_id}},
            {"name": "manage_state", "arguments": {"action": "delete", "id": "state-id"}}]},
        {"answer": "Actual removals observed."}], seed=seed)
    assert len(requests) == 3
    assert '"id": "state-id"' in requests[0]["messages"][0]["content"]
    assert '"revision": 1' in requests[0]["messages"][0]["content"]
    assert [json.loads(row["content"])["status"] for row in
            output["host_tool_receipts"]] == ["no_change", "noop", "deleted", "deleted"]
    assert output["memory"] == [] and output["states"] == []
    assert bank.store.get(("langmem", "run", "host_both", "bob"), memory_id).value == {
        "content": "Bob's record"}


def test_host_failure_keeps_partial_writes_and_unacknowledged_sources(
    tmp_path: Path,
) -> None:
    requests: list[dict[str, Any]] = []
    first = {"calls": [{"name": "manage_memory", "arguments": {
        "action": "create", "content": "committed before capacity failure"}}]}
    with _runtime(tmp_path, [first], requests, max_calls=1) as runtime:
        bank = LocalStateBank(runtime.store)
        scope = StateScope("run", "host_both", "alice")
        bank.record_event(scope, {"id": "source-current", "kind": "user",
                                  "actor": "alice", "tool_call_id": None,
                                  "content": "Remember the current plan."})
        tools = create_writer_tools(bank, MEMORY_NAMESPACE)
        controller = LocalStateController(bank, ControlReplies([]))  # type: ignore[arg-type]
        world = ApplicationWorld(tmp_path / "business.sqlite", False)
        journal = BusinessActionJournal(tmp_path / "journal.json", BUSINESS_NAMES)
        try:
            with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
                run_writer_policy_turn(
                    "host_both", [HumanMessage(content="Remember the current plan.")],
                    ({"role": "user", "content": "Remember the current plan."},),
                    runtime, FoundationScope("run", "host_both", "alice", "episode"),
                    world, journal, bank, tools, controller)
            assert len(requests) == 1
            assert len(runtime.store.search(("langmem", "run", "host_both", "alice"))) == 1
            pending = bank.pending(scope)
            assert pending[0]["id"] == "source-current"
            assert len(pending) == 2 and pending[1]["kind"] == "tool"
        finally:
            world.close()


def test_boundary_capacity_failure_keeps_pending_and_host_continues(
    tmp_path: Path,
) -> None:
    reads = [{"calls": [{"name": "read_record", "arguments": {
        "target_kind": "state", "id": "missing"}}]} for _ in range(13)]
    output, control, requests, _ = _turn(
        tmp_path, "boundary_both", reads, [{"answer": "Host still answered."}])
    assert len(control.payloads) == 13 and len(requests) == 1
    assert output["initial_boundary"]["status"] == "DEGRADED"
    assert output["pending_event_ids"] == ["source-current"]
    assert output["answer"] == "Host still answered."


def test_boundary_partial_write_keeps_real_commit_and_pending(
    tmp_path: Path,
) -> None:
    output, control, requests, _ = _turn(tmp_path, "boundary_both", [
        {"calls": [
            {"name": "manage_state", "arguments": {"action": "create",
                "title": "committed", "content": "one actual row",
                "evidence": ["source-current"]}},
            {"name": "manage_state", "arguments": {"action": "update",
                "id": "missing", "content": "invalid target"}}]},
    ], [{"answer": "Host sees partial result."}])
    assert len(control.payloads) == len(requests) == 1
    assert output["initial_boundary"]["status"] == "PARTIAL_REJECTED"
    assert [row["status"] for row in output["initial_boundary"]["receipts"]] == [
        "success", "error"]
    assert output["states"][0]["content"] == "one actual row"
    assert output["pending_event_ids"] == ["source-current"]
    assert '"status": "PARTIAL_REJECTED"' in requests[0]["messages"][0]["content"]


def test_partial_automatic_receipts_reach_explicit_trigger_proposal(
    tmp_path: Path,
) -> None:
    output, control, requests, _ = _turn(tmp_path, "boundary_both", [
        {"calls": [
            {"name": "manage_state", "arguments": {"action": "create",
                "title": "committed", "content": "real row"}},
            {"name": "manage_state", "arguments": {"action": "update",
                "id": "missing", "content": "invalid"}}]},
        {"calls": [{"name": "manage_memory", "arguments": {
            "action": "create", "content": "real later memory"}}]},
        {"calls": []},
    ], [{"calls": [{"name": "maintain_records", "arguments": {
        "reason": "Recheck the actual partial receipt."}}]},
        {"calls": [{"name": "maintain_records", "arguments": {
            "reason": "Check the subsequent real receipt."}}]},
        {"answer": "Receipt inspected."}])
    assert len(control.payloads) == 3 and len(requests) == 3
    earlier = control.payloads[1]["actual_tool_receipts"]
    boundary_earlier = [row for row in earlier if row["origin"] == "boundary_executor"]
    assert [row["status"] for row in boundary_earlier] == ["success", "error"]
    boundary_later = [row for row in control.payloads[2]["actual_tool_receipts"]
                      if row["origin"] == "boundary_executor"]
    assert [row["status"] for row in boundary_later] == [
        "success", "error", "success"]
    assert output["initial_boundary"]["status"] == "PARTIAL_REJECTED"
    assert output["states"][0]["content"] == "real row"


def test_seed_rejects_dirty_current_owner_and_keeps_other_owner_isolated(
    tmp_path: Path,
) -> None:
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, [], requests) as runtime:
        bank = LocalStateBank(runtime.store)
        scope = StateScope("run", "host_both", "alice")
        case = {"user_id": "alice", "memories": [{"owner": "bob", "key": "bob-id",
                    "value": {"content": "Bob's only"}}], "source_events": [],
                "pending_event_ids": [], "states": []}
        runtime.store.put(("langmem", "run", "host_both", "alice"),
                          "dirty", {"content": "already here"})
        with pytest.raises(ValueError, match="WRITER_POLICY_NAMESPACE_DIRTY"):
            _seed(case, runtime, bank, scope, tmp_path, tmp_path / "budget.json")
        assert runtime.store.search(("langmem", "run", "host_both", "bob")) == []
    assert requests == []


def test_seed_preserves_actual_ids_and_indexing_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, [], requests) as runtime:
        bank = LocalStateBank(runtime.store)
        scope = StateScope("run", "boundary_both", "alice")
        puts: list[tuple[tuple[str, ...], str, Any]] = []
        original_put = InMemoryStore.put

        def tracked_put(store: InMemoryStore, namespace: tuple[str, ...], key: str,
                        value: dict[str, Any], *, index: Any = None) -> None:
            puts.append((namespace, key, index))
            original_put(store, namespace, key, value, index=index)

        monkeypatch.setattr(InMemoryStore, "put", tracked_put)
        case = {"user_id": "alice", "memories": [{"owner": "alice", "key": "memory-id",
                    "value": {"content": "actual memory"}}], "source_events": [
            {"id": "old-source", "kind": "user", "actor": "alice",
             "tool_call_id": None, "content": "old"},
            {"id": "new-source", "kind": "user", "actor": "alice",
             "tool_call_id": None, "content": "new"}],
                "pending_event_ids": ["new-source"], "states": [{
                    "id": "state-id", "title": "actual", "content": "known",
                    "needs": [], "evidence_refs": ["old-source"],
                    "revision": 3, "archived": False}]}
        seed = _seed(case, runtime, bank, scope, tmp_path, tmp_path / "budget.json")
        assert seed["pending_event_ids"] == ["new-source"]
        assert bank.states(scope)[0]["revision"] == 3
        assert bank.events(scope)[0]["id"] == "old-source"
        assert puts[0] == (("langmem", "run", "boundary_both", "alice"),
                           "memory-id", None)
        assert any(row[0] == scope.namespace("states") and row[1] == "state-id"
                   and row[2] is False for row in puts)
        assert bank.states(StateScope("run", "boundary_both", "bob")) == []
    assert requests == []


def test_prepare_locks_order_and_failed_attempt_cannot_reseed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.runners import writer_policy as runner

    config = {"host": {"base_url": "http://mock/v1/", "model": "mock",
                       "tool_mode": "json_action", "max_calls": 12,
                       "max_tokens": 4096}, "embedding": {"base_url": "http://mock/v1/",
                       "model": "embed"}, "capacity": {"enable_thinking": False},
              "control": {"max_calls_per_message": 13, "max_tokens": 2048},
              "memory_contract": "strict", "source_view_max_bytes": 16384,
              "budget_path": str(tmp_path / "budget.json")}
    case = {"case_id": "case", "user_id": "alice", "raw_history": [
        {"role": "user", "content": "Question"}], "current_task": "Question",
        "states": [], "memories": [], "source_events": [], "pending_event_ids": []}
    inputs = {"kind": "MILAI_WRITER_POLICY_INPUTS", "cases": [case], "jobs": [
        {"job_id": "first", "case_id": "case", "writer_policy": "host_both"}]}
    assert len(_cases_and_jobs(inputs)[1]) == 1
    config_path, inputs_path = tmp_path / "config.json", tmp_path / "inputs.json"
    write_json(config_path, config)
    write_json(inputs_path, inputs)
    args = SimpleNamespace(config=config_path, inputs=inputs_path, run="run",
                           runtime_root=tmp_path / "runtime",
                           output=tmp_path / "prepared.json",
                           prepared=tmp_path / "prepared.json", job="first", stage="mock")
    lab_root = Path(__file__).resolve().parents[2]
    assert prepare(args, lab_root=lab_root)["jobs"] == 1

    @contextmanager
    def fail_open(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("opening failed")
        yield

    monkeypatch.setattr(runner, "open_application_runtime", fail_open)
    with pytest.raises(RuntimeError, match="opening failed"):
        run_job(args, lab_root=lab_root)
    with pytest.raises(ValueError, match="WRITER_POLICY_JOB_ALREADY_ATTEMPTED"):
        run_job(args, lab_root=lab_root)
    assert read_json(args.runtime_root / "run_manifest.json")["attempts"]["first"][
        "status"] == "FAILED"
