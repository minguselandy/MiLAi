"""Mock HTTP and actual InMemoryStore checks for fixed candidate maintenance."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langgraph.store.memory import InMemoryStore

from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import LocalStateController
from milai_lab.methods.local_state_attention.protocol import (
    READ_SELECTOR_PROMPT,
    UPDATE_SELECTOR_PROMPT,
    control_prompt,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import fixed_state_update as runner


def _case() -> dict[str, Any]:
    return {"case_id": "case", "user_id": "alice", "query": "Read matter a.",
            "memories": [], "states": [
                {"id": key, "title": "matter " + key, "content": "old " + key,
                 "needs": ["keep"], "evidence_refs": ["prior"], "revision": 1,
                 "archived": False} for key in ("a", "b", "c")],
            "source_events": [
                {"id": "prior", "kind": "user", "actor": "alice",
                 "tool_call_id": None, "content": "Three continuing matters."},
                {"id": "change", "kind": "tool", "actor": "real_tool",
                 "tool_call_id": "real-call", "content": '{"ok":false,"partial":"b"}'}],
            "pending_event_ids": ["change"]}


def _config(root: Path) -> dict[str, Any]:
    return {"host": {"base_url": "http://mock/v1/", "model": "mock",
                     "temperature": 0, "max_tokens": 4096, "timeout": 30,
                     "tool_mode": "json_action", "max_calls": 12,
                     "enable_thinking": False},
            "embedding": {"base_url": "http://mock/v1/", "model": "bge-m3"},
            "control": {"max_tokens": 2048, "max_calls_per_message": 13,
                        "max_states": 32, "max_events": 256, "max_pending_batch": 24,
                        "aggregate_content_chars": 16000, "local_granularity": True},
            "capacity": {"enable_thinking": False},
            "budget_path": str(root / "budget.json")}


@contextmanager
def _runtime(root: Path, replies: list[dict[str, Any]], requests: list[dict[str, Any]],
             monkeypatch: pytest.MonkeyPatch, *, finish: str = "stop") -> Any:
    config = _config(root)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json={"id": "generation-" + str(len(requests)),
                                        "choices": [{"finish_reason": finish,
                                                     "message": {"role": "assistant",
                                                                 "content": json.dumps(
                                                                     replies.pop(0))}}],
                                        "usage": {"prompt_tokens": 10,
                                                  "completion_tokens": 5,
                                                  "total_tokens": 15}})

    transport = httpx.MockTransport(respond)

    def make_client(value: VLLMConfig, **kwargs: Any) -> VLLMClient:
        return VLLMClient(value, transport=transport, **kwargs)

    monkeypatch.setattr(runner, "VLLMClient", make_client)
    budget = RunBudget(RunLimits(1, 4, None, None, None), Path(config["budget_path"]))
    with VLLMClient(VLLMConfig(**config["host"]), transport=transport,
                    budget=budget, emit=Trace(root / "trace.jsonl", "mock")) as client:
        yield SimpleNamespace(model=SimpleNamespace(client=client), store=InMemoryStore())


@pytest.mark.parametrize("arm,mask,stage", [
    ("all", ["a", "b", "c"], None),
    ("u_selector", ["b"], "update_selector"),
    ("u_equals_a", ["a"], "read_selector"),
    ("oracle_u", ["b"], None),
])
def test_actual_mask_shared_maintenance_scope_and_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str,
    mask: list[str], stage: str | None,
) -> None:
    config, case = _config(tmp_path), _case()
    job = {"job_id": "job", "case_id": "case", "arm": arm,
           "oracle_update_ids": ["b"]}
    replies = ([{"update_ids": mask}] if arm == "u_selector" else
               [{"read_ids": mask}] if arm == "u_equals_a" else [])
    target = "a" if arm == "u_equals_a" else "b"
    replies.append({"edits": [{"id": target, "content": "actual changed",
                                "evidence": ["change"]}]})
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, replies, requests, monkeypatch) as runtime:
        foreign_scope = StateScope("run", arm, "other")
        runtime.store.put(foreign_scope.namespace("states"), "b",
                          {**case["states"][1], "content": "private foreign body"}, index=False)
        result = runner._run_one(case, job, config, runtime, tmp_path, "run", arm)
    assert result["status"] == "APPLIED" and result["selected_update_ids"] == mask
    assert result["pending_event_ids_after"] == []
    assert result["acknowledged_event_ids"] == ["change"]
    assert len(requests) == (2 if stage else 1)
    assert "private foreign body" not in json.dumps(requests)
    maintenance = requests[-1]
    assert maintenance["max_tokens"] == 2048
    assert maintenance["messages"][0]["content"] == control_prompt(
        "local", local_granularity=True, maintenance=True, candidate_only=True)
    payload = json.loads(maintenance["messages"][1]["content"])
    assert set(payload) == {"new_observations", "states", "source_ids_available"}
    assert [row["id"] for row in payload["states"]] == mask
    assert payload["new_observations"] == [case["source_events"][1]]
    assert payload["source_ids_available"] == ["prior", "change"]
    selection = next(row for row in (json.loads(line) for line in
                     (tmp_path / "trace.jsonl").read_text().splitlines())
                     if row["event"] == "fixed_update_selection")
    assert selection["candidate_body_bytes"] == len(json.dumps(
        payload["states"], ensure_ascii=False).encode())
    after = {row["id"]: row for row in result["states_after"]}
    assert after[target]["content"] == "actual changed"
    assert after[target]["needs"] == ["keep"]
    assert all(after[key]["content"] == "old " + key for key in {"a", "b", "c"}-{target})
    assert result["accounting"]["by_role"]["state_control"]["known_tokens"] == 15*len(requests)
    assert result["accounting"]["by_control_stage"]["maintenance"]["requests"] == 1
    assert list(result["control_capacity"].values()) == [len(requests)]
    assert read_json(Path(config["budget_path"]))["generation_requests"] == len(requests)
    if stage:
        choice = json.loads(requests[0]["messages"][1]["content"])
        assert choice["new_observations"] == [case["source_events"][1]]
        assert "old a" not in requests[0]["messages"][1]["content"]
        assert ("current_task" in choice) == (arm == "u_equals_a")
        if arm == "u_equals_a":
            assert requests[0]["messages"][0]["content"] == READ_SELECTOR_PROMPT
            assert choice["current_task"] == case["query"]
        else:
            assert requests[0]["messages"][0]["content"] == UPDATE_SELECTOR_PROMPT


def test_empty_u_can_create_and_partial_outside_u_keeps_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, mask, edits in (
        ("empty", [], [{"id": None, "title": "new matter", "content": "new actual body",
                        "evidence": ["change"]}]),
        ("partial", ["b"], [{"id": "b", "content": "actual change"},
                             {"id": "a", "content": "unauthorized change"}]),
    ):
        root = tmp_path / name
        root.mkdir()
        requests: list[dict[str, Any]] = []
        with _runtime(root, [{"update_ids": mask}, {"edits": edits}], requests,
                      monkeypatch) as runtime:
            result = runner._run_one(_case(), {"job_id": "job", "case_id": "case",
                                               "arm": "u_selector"}, _config(root),
                                     runtime, root, "run", "u_selector")
        assert result["selected_update_ids"] == mask
        assert len(requests) == 2
        if name == "empty":
            assert json.loads(requests[-1]["messages"][1]["content"])["states"] == []
            assert result["receipts"][0]["status"] == "created"
            assert len(result["states_after"]) == 4 and result["pending_event_ids_after"] == []
        else:
            assert result["status"] == "PARTIAL_REJECTED"
            assert [row["status"] for row in result["receipts"]] == [
                "updated", "skipped_invalid_edit"]
            assert result["pending_event_ids_after"] == ["change"]
            assert result["acknowledged_event_ids"] == []
            assert {row["id"]: row["content"] for row in result["states_after"]} == {
                "a": "old a", "b": "actual change", "c": "old c"}


@pytest.mark.parametrize("boundary", ["bad_selection", "truncated", "capacity"])
def test_failed_control_keeps_prestate_and_actual_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str,
) -> None:
    replies = [{"update_ids": ["outside"]}] if boundary == "bad_selection" else [{"edits": []}]
    arm = "u_selector" if boundary != "truncated" else "all"
    if boundary == "capacity":
        write_json(tmp_path / "control-capacity.json", {"job": 13})
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, replies, requests, monkeypatch,
                  finish="length" if boundary == "truncated" else "stop") as runtime:
        result = runner._run_one(_case(), {"job_id": "job", "case_id": "case",
                                           "arm": arm}, _config(tmp_path), runtime,
                                 tmp_path, "run", arm)
    assert result["status"] == "CONTROL_REJECTED"
    assert result["states_before"] == result["states_after"]
    assert result["pending_event_ids_after"] == ["change"]
    assert len(requests) == (0 if boundary == "capacity" else 1)
    if boundary == "capacity":
        assert result["reason"] == "LSA_CONTROL_CAPACITY"


@pytest.mark.parametrize("store_failure", [False, True])
def test_empty_proposal_ack_is_not_store_success_and_store_error_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store_failure: bool,
) -> None:
    proposal = {"edits": [{"id": "b", "content": "reject-store"}]} if store_failure else {
        "edits": []}
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, [proposal], requests, monkeypatch) as runtime:
        class FailingStore(InMemoryStore):
            def put(self, namespace: Any, key: str, value: Any, **kwargs: Any) -> None:
                if isinstance(value, dict) and value.get("content") == "reject-store":
                    raise ValueError("synthetic Store failure")
                super().put(namespace, key, value, **kwargs)

        runtime.store = FailingStore()
        if store_failure:
            with pytest.raises(ValueError, match="synthetic Store failure"):
                runner._run_one(_case(), {"job_id": "job", "case_id": "case",
                                          "arm": "all"}, _config(tmp_path), runtime,
                                tmp_path, "run", "all")
            result = read_json(tmp_path / "result.json")
            assert result["status"] == "FAILED"
            assert result["pending_event_ids_after"] == ["change"]
        else:
            result = runner._run_one(_case(), {"job_id": "job", "case_id": "case",
                                               "arm": "all"}, _config(tmp_path), runtime,
                                     tmp_path, "run", "all")
            assert result["status"] == "NO_CHANGE"
            assert result["pending_event_ids_after"] == []
        assert result["states_after"] == result["states_before"]
        assert result["receipts"] == [] and len(requests) == 1


def test_legacy_update_selector_wire_and_prompt_are_unchanged() -> None:
    bank, scope = LocalStateBank(InMemoryStore()), StateScope("run", "lru", "alice")
    for row in _case()["states"]:
        bank.store.put(scope.namespace("states"), row["id"], row, index=False)
    bank.record_event(scope, _case()["source_events"][1])
    calls: list[dict[str, Any]] = []

    class Client:
        def chat(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append({"messages": messages, **kwargs})
            plan = ({"update_ids": ["b"]} if len(calls) == 1 else
                    {"edits": []} if len(calls) == 2 else {"read_ids": []})
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(plan)}}]}

    controller = LocalStateController(bank, Client(), update_policy="lru")  # type: ignore[arg-type]
    result = controller.prepare(scope, "change", "Read matter a.", "public-turn")
    assert not result["degraded"] and len(calls) == 3
    assert calls[0]["messages"][0]["content"] == (
        "From source-identified new observations and the short State directory, "
        "select every existing State that may need an update. Selection is about "
        "event impact, not the current reading task. Return update_ids only; "
        "creation is decided by the shared maintainer.")
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert list(payload) == ["current_task", "new_observations", "directory"]
    assert payload["current_task"] == "Read matter a."
    assert calls[0]["response_format"]["json_schema"]["name"] == (
        "local_state_update_selector_v1")


def test_prepare_order_identity_and_single_attempt_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, inputs_path = tmp_path / "config.json", tmp_path / "inputs.json"
    write_json(config_path, _config(tmp_path))
    write_json(inputs_path, {"kind": "MILAI_FIXED_UPDATE_INPUTS", "cases": [_case()],
                             "jobs": [{"job_id": key, "case_id": "case", "arm": "all"}
                                      for key in ("one", "two")]})
    root = tmp_path / "run"
    args = SimpleNamespace(config=config_path, inputs=inputs_path, run="run",
                           runtime_root=root, output=root / "prepared.json",
                           prepared=root / "prepared.json", job="two", stage="mock")
    lab = Path(__file__).resolve().parents[2]
    assert runner.prepare(args, lab_root=lab)["jobs"] == 2
    with pytest.raises(ValueError, match="FIXED_UPDATE_JOB_OUT_OF_ORDER"):
        runner.run_job(args, lab_root=lab)

    @contextmanager
    def fail_open(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("mock infrastructure")
        yield

    monkeypatch.setattr(runner, "open_application_runtime", fail_open)
    args.job = "one"
    with pytest.raises(RuntimeError, match="mock infrastructure"):
        runner.run_job(args, lab_root=lab)
    with pytest.raises(ValueError, match="FIXED_UPDATE_JOB_ALREADY_ATTEMPTED"):
        runner.run_job(args, lab_root=lab)
