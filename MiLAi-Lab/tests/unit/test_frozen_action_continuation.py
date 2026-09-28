"""Offline graph continuation from a recorded first JSON-action reply."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    convert_to_openai_messages,
)
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import SYSTEM_PROMPT
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import (
    VLLMChatModel,
    _action_prompt,
    _action_schema,
    _json_action_history,
)
from milai_lab.runners.frozen_action_continuation import (
    _catalog,
    continue_job,
    prepare,
    run_job,
    validate_frozen_job,
)
from milai_lab.runners.langmem_application_runtime import ApplicationRuntime


def _frozen(tmp_path: Path, *, with_prior_tool: bool = False
            ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = {"host": {"base_url": "http://mock/v1/", "model": "mock",
                       "temperature": 0, "max_tokens": 4096, "timeout": 30,
                       "tool_mode": "json_action", "max_calls": 12,
                       "enable_thinking": False},
              "capacity": {"enable_thinking": False},
              "memory_contract": "strict", "budget_path": str(tmp_path / "budget.json")}
    catalog = _catalog()
    prefix = _action_prompt(catalog) + "\n"
    prompt = SYSTEM_PROMPT + "\n[Local State working view: synthetic source.]"
    history: list[Any] = [HumanMessage(content="Reserve one box.")]
    if with_prior_tool:
        history = [HumanMessage(content="Check the old box."),
                   AIMessage(id="old-generation", content="", tool_calls=[{
                       "name": "get_reservation", "args": {"item_key": "box-A"},
                       "id": "old-generation:tool:0"}]),
                   ToolMessage(content='{"ok":false,"status":"not_found"}',
                               name="get_reservation",
                               tool_call_id="old-generation:tool:0"),
                   AIMessage(content="No reservation exists."), *history]
    wire = convert_to_openai_messages([SystemMessage(content=prompt), *history])
    assert isinstance(wire, list)
    wire = _json_action_history(wire)
    wire[0]["content"] = prefix + prompt
    request = {"model": "mock", "messages": wire,
               "temperature": 0, "max_tokens": 4096,
               "chat_template_kwargs": {"enable_thinking": False},
               "response_format": {"type": "json_schema", "json_schema": {
                   "name": "langmem_json_action_v1", "strict": True,
                   "schema": _action_schema(catalog, generation_only=True)}}}
    action = {"calls": [{"name": "reserve_and_label", "arguments": {
        "item_key": "box-A", "quantity": 1, "destination": "room-1", "packing": "paper"}}]}
    receipt = {"id": "frozen-generation", "model": "mock", "choices": [
        {"finish_reason": "stop", "message": {"role": "assistant",
                                                "content": json.dumps(action)}}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    job = {"job_id": "job-one", "case_id": "case-one",
           "arm": "diagnostic", "variant": "original"}
    result = {"status": "COMPLETED_FIRST_REQUEST_ONLY", "job": job,
              "case_id": "case-one", "host_request": request,
              "host_receipt": receipt, "first_action": action,
              "business_tools_executed": 0}
    prestate = {"case_id": "case-one", "user_id": "alice",
                "initial_label_available": False,
                "business_world": {"reservations": [], "attempts": []},
                "memory_records": [{"user_id": "bob", "key": "prior-bob",
                                    "value": {"content": "Only Bob may read this."}}],
                "source_selection": {"private_metadata": "never model input"}}
    return config, result, prestate


def _runtime(tmp_path: Path, config: dict[str, Any],
             responses: list[dict[str, Any]], requests: list[dict[str, Any]],
             *, max_calls: int = 12) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    @contextmanager
    def opened() -> Any:
        with VLLMClient(VLLMConfig(**config["host"]),
                        transport=httpx.MockTransport(respond)) as client:
            model = VLLMChatModel(client=client,
                                  capacity_path=tmp_path / "message-capacity.json",
                                  max_calls_per_message=max_calls)
            with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
                yield ApplicationRuntime(model, InMemoryStore(), saver, None)  # type: ignore[arg-type]

    return opened()


@pytest.mark.parametrize("with_prior_tool", [False, True])
def test_frozen_first_action_runs_once_then_graph_host_uses_same_prefix(
    tmp_path: Path, with_prior_tool: bool,
) -> None:
    config, frozen, prestate = _frozen(tmp_path, with_prior_tool=with_prior_tool)
    validate_frozen_job(frozen, config)
    responses = [{"id": "next-generation", "model": "mock", "choices": [
        {"finish_reason": "stop", "message": {"role": "assistant",
                                            "content": '{"answer":"Reservation observed."}'}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5}}]
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, config, responses, requests) as runtime:
        output = continue_job(frozen, prestate, config, runtime,
                              tmp_path, "run:job-one", "frozen_action")
        assert runtime.store.get(("langmem", "run:job-one", "frozen_action", "alice"),
                                 "prior-bob") is None
    assert output["status"] == "COMPLETED"
    assert len(requests) == 1
    first_messages = frozen["host_request"]["messages"]
    assert requests[0]["messages"][:len(first_messages)] == first_messages
    assert requests[0]["response_format"] == frozen["host_request"]["response_format"]
    assert "private_metadata" not in json.dumps(requests[0])
    assert output["capacity"] == {next(iter(output["capacity"])): 2}
    assert output["world"]["reservations"][0]["quantity"] == 1
    assert len(output["world"]["attempts"]) == len(output["business_calls"]) == 1
    assert output["business_calls"][0]["generation_id"] == "frozen-generation"
    assert output["business_calls"][0]["call_id"] == "frozen-generation:tool:0"
    assert output["memory_before_action"]["bob"] == [
        {"key": "prior-bob", "value": {"content": "Only Bob may read this."}}]
    raw = read_json(tmp_path / "frozen-first-response.json")
    assert raw["host_receipt"] == frozen["host_receipt"]
    assert raw["mapped_ai_message"]["id"] == "frozen-generation"


def test_imported_first_call_consumes_capacity_without_replaying_tool(
    tmp_path: Path,
) -> None:
    config, frozen, prestate = _frozen(tmp_path)
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, config, [], requests, max_calls=1) as runtime:
        with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
            continue_job(frozen, prestate, config, runtime,
                         tmp_path, "run:job-one", "frozen_action")
    saved = read_json(tmp_path / "result.json")
    assert saved["exception"]["message"] == "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"
    assert list(saved["capacity"].values()) == [1]
    assert requests == []
    assert len(saved["business_calls"]) == len(saved["world"]["attempts"]) == 1


def test_frozen_contract_rejects_changed_catalog_and_parallel_first_calls(
    tmp_path: Path,
) -> None:
    config, frozen, _ = _frozen(tmp_path)
    frozen["host_request"]["messages"][0]["content"] = (
        "changed catalog\n" + frozen["host_request"]["messages"][0]["content"])
    with pytest.raises(ValueError, match="FROZEN_CATALOG_PREFIX_CHANGED"):
        validate_frozen_job(frozen, config)
    config, frozen, _ = _frozen(tmp_path)
    frozen["first_action"]["calls"].append(frozen["first_action"]["calls"][0])
    frozen["host_receipt"]["choices"][0]["message"]["content"] = json.dumps(
        frozen["first_action"])
    with pytest.raises(ValueError, match="FROZEN_FIRST_ACTION_CARDINALITY_UNSUPPORTED"):
        validate_frozen_job(frozen, config)


def test_current_owner_namespace_must_be_empty_even_without_seed_records(
    tmp_path: Path,
) -> None:
    config, frozen, prestate = _frozen(tmp_path)
    prestate["memory_records"] = []
    requests: list[dict[str, Any]] = []
    with _runtime(tmp_path, config, [], requests) as runtime:
        runtime.store.put(("langmem", "run:job-one", "frozen_action", "alice"),
                          "unexpected", {"content": "dirty prior state"})
        with pytest.raises(ValueError, match="FROZEN_PRESTATE_NAMESPACE_DIRTY"):
            continue_job(frozen, prestate, config, runtime,
                         tmp_path, "run:job-one", "frozen_action")
        assert len(runtime.store.search(("langmem", "run:job-one",
                                         "frozen_action", "alice"))) == 1
    assert requests == []
    assert not (tmp_path / "business-world.sqlite").exists()


def test_prepare_identity_and_failed_attempt_guard(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    from milai_lab.runners import frozen_action_continuation as runner

    config, result, prestate = _frozen(tmp_path)
    first_root = tmp_path / "first-run"
    write_json(first_root / "jobs" / "job-one.json", result)
    config_path, inputs_path, prestate_path = (tmp_path / name for name in
                                                ("config.json", "inputs.json", "prestates.json"))
    write_json(config_path, config)
    write_json(inputs_path, {"kind": "LSA_READ_PROBE_INPUTS", "jobs": [result["job"]]})
    write_json(prestate_path, {"kind": "MILAI_FROZEN_ACTION_PRESTATES",
                               "cases": [prestate]})
    args = SimpleNamespace(config=config_path, inputs=inputs_path,
                           first_run_root=first_root, prestates=prestate_path,
                           run="new-run", arm="frozen_action",
                           runtime_root=tmp_path / "runtime",
                           output=tmp_path / "prepared.json",
                           prepared=tmp_path / "prepared.json",
                           job="job-one", stage="mock")
    lab_root = Path(__file__).resolve().parents[2]
    assert prepare(args, lab_root=lab_root)["jobs"] == 1

    @contextmanager
    def fail_open(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("pre-connection failure")
        yield

    monkeypatch.setattr(runner, "open_application_runtime", fail_open)
    with pytest.raises(RuntimeError, match="pre-connection failure"):
        run_job(args, lab_root=lab_root)
    with pytest.raises(ValueError, match="FROZEN_JOB_ALREADY_ATTEMPTED"):
        run_job(args, lab_root=lab_root)
    assert read_json(args.runtime_root / "run_manifest.json")["attempts"][
        "job-one"]["status"] == "FAILED"

    changed = read_json(first_root / "jobs" / "job-one.json")
    changed["first_action"]["calls"][0]["arguments"]["quantity"] = 2
    write_json(first_root / "jobs" / "job-one.json", changed)
    with pytest.raises(ValueError, match="FROZEN_PREPARED_IDENTITY_CHANGED"):
        run_job(args, lab_root=lab_root)
