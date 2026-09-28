"""Mock HTTP and local SQLite checks for complete fixed-bank read turns."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.harness.contextual_artifacts import Trace, read_json, write_json
from milai_lab.methods.local_state_attention.protocol import (
    READ_SELECTOR_PROMPT,
    read_selector_payload,
    selection_schema,
)
from milai_lab.methods.local_state_attention.read_probe import (
    enhance_query,
    select_directory_a,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners import fixed_state_read as runner
from milai_lab.runners.langmem_application_runtime import ApplicationRuntime


def _state(key: str, content: str) -> dict[str, Any]:
    return {"id": key, "title": "matter " + key, "content": content,
            "needs": [], "evidence_refs": [], "revision": 2, "archived": False}


def _case() -> dict[str, Any]:
    return {"case_id": "case", "user_id": "alice", "current_task": "Which plan?",
            "raw_history": [{"role": "user", "content": "Remember two plans."},
                            {"role": "assistant", "content": "I heard them."},
                            {"role": "user", "content": "Which plan?"}],
            "states": [_state("state-b", "Plan B is blue."),
                       _state("state-a", "Plan A is amber.")],
            "memories": [], "source_events": [], "pending_event_ids": []}


def _config(root: Path) -> dict[str, Any]:
    return {"host": {"base_url": "http://mock/v1/", "model": "mock",
                     "temperature": 0, "max_tokens": 4096, "timeout": 30,
                     "tool_mode": "json_action", "max_calls": 12,
                     "enable_thinking": False},
            "embedding": {"base_url": "http://mock/v1/", "model": "bge-m3"},
            "control": {"max_tokens": 2048, "max_calls_per_message": 13,
                        "max_states": 32, "max_events": 256,
                        "max_pending_batch": 24},
            "capacity": {"enable_thinking": False},
            "memory_contract": "strict", "budget_path": str(root / "budget.json")}


@contextmanager
def _runtime(root: Path, replies: list[dict[str, Any]],
             requests: list[dict[str, Any]], *, max_calls: int = 12) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(200, json={"id": "gen-" + str(len(requests)),
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"role": "assistant",
                                                                  "content": json.dumps(
                                                                      replies.pop(0))}}],
                                         "usage": {"prompt_tokens": 20,
                                                   "completion_tokens": 5,
                                                   "total_tokens": 25}})

    with VLLMClient(VLLMConfig(**_config(root)["host"]),
                    transport=httpx.MockTransport(respond),
                    emit=Trace(root / "trace.jsonl", "mock")) as client:
        model = VLLMChatModel(client=client,
                              capacity_path=root / "message-capacity.json",
                              max_calls_per_message=max_calls)
        with SqliteSaver.from_conn_string(str(root / "checkpoints.sqlite")) as saver:
            yield ApplicationRuntime(model, InMemoryStore(), saver, None)  # type: ignore[arg-type]


def test_complete_read_only_graph_multi_read_and_full_history_control(
    tmp_path: Path,
) -> None:
    case, config = _case(), _config(tmp_path)
    for arm, chosen in (("all", ["state-a", "state-b"]), ("full_history", [])):
        root = tmp_path / arm
        root.mkdir()
        requests: list[dict[str, Any]] = []
        replies = [{"calls": [
            {"name": "read_record", "arguments": {"target_kind": "state",
                                                  "id": "state-a"}},
            {"name": "read_record", "arguments": {"target_kind": "state",
                                                  "id": "state-b"}}]},
            {"answer": "Both actual records were read."}]
        with _runtime(root, replies, requests) as runtime:
            result = runner._run_one(case, {"job_id": arm, "case_id": "case",
                                            "arm": arm}, config, runtime,
                                     root, "run:" + arm, arm)
        assert result["status"] == "COMPLETED" and result["answer"] == (
            "Both actual records were read.")
        assert result["selected_state_ids"] == chosen
        assert result["states_before"] == result["states_after"]
        assert result["ordinary_memory_before"] == result["ordinary_memory_after"] == []
        assert len(result["readbacks"]) == 2
        assert all(json.loads(row["content"])["status"] == "found"
                   for row in result["readbacks"])
        assert len(requests) == 2
        assert {row["name"] for row in result["read_only_tool_catalog"]} == {
            "search_memory", "read_record"}
        assert "read_record" in requests[0]["messages"][0]["content"]
        first = requests[0]["messages"]
        assert [row["content"] for row in first[1:]] == [
            "Remember two plans.", "I heard them.", "Which plan?"]
        assert "state-a" in first[0]["content"] and "state-b" in first[0]["content"]
        assert ("Plan A is amber." in first[0]["content"]) == (arm == "all")
        assert requests[1]["messages"][:len(first)] == first
        assert [row["tool_call_id"] for row in requests[1]["messages"]
                if row["role"] == "tool"] == ["gen-1:tool:0", "gen-1:tool:1"]
        assert sum(row["known_tokens"] for row in result["accounting"]["by_role"].values()
                   ) == 50


def test_empty_selection_still_can_read_and_capacity_keeps_real_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, config = _case(), _config(tmp_path)
    root = tmp_path / "job"
    root.mkdir()
    monkeypatch.setattr(runner, "select_directory_a", lambda *_args: [])
    requests: list[dict[str, Any]] = []
    replies = [{"calls": [{"name": "read_record", "arguments": {
        "target_kind": "state", "id": "state-a"}}]}]

    @contextmanager
    def selector_client(*_args: Any, **_kwargs: Any) -> Any:
        yield SimpleNamespace()

    monkeypatch.setattr(runner, "VLLMClient", selector_client)
    with _runtime(root, replies, requests, max_calls=1) as runtime:
        with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
            runner._run_one(case, {"job_id": "job", "case_id": "case",
                                   "arm": "a_selector"}, config, runtime,
                            root, "run:job", "a_selector")
    output = read_json(root / "result.json")
    assert len(requests) == 1
    assert len(output["readbacks"]) == 1
    assert output["selected_state_ids"] == []
    assert output["states_before"] == output["states_after"]
    assert list(output["host_capacity"].values()) == [1]
    assert list(output["control_capacity"].values()) == [1]


def test_directory_a_and_enhancement_share_directory_but_keep_query(
) -> None:
    bank = _case()["states"]
    seen: list[dict[str, Any]] = []

    class Client:
        def chat(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
            seen.append({"messages": messages, "kwargs": kwargs})
            name = kwargs["response_format"]["json_schema"]["name"]
            content = ({"read_ids": ["state-b", "state-a"]}
                       if name == "local_state_read_selector_v1" else
                       {"entity_anchors": ["Plan B", "amber"]})
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(content)}}]}

    client = Client()
    query = "Which plan? Keep this exact query."
    actual = [{"id": "new-event", "kind": "user", "content": "New observation."}]
    selected = select_directory_a(bank, query, client, observations=actual)  # type: ignore[arg-type]
    assert [row["id"] for row in selected] == ["state-a", "state-b"]
    request = seen[0]
    assert request["messages"][0]["content"] == READ_SELECTOR_PROMPT
    assert json.loads(request["messages"][1]["content"]) == read_selector_payload(
        query, actual, sorted(bank, key=lambda row: row["id"]))
    assert request["kwargs"]["response_format"]["json_schema"]["schema"] == (
        selection_schema("read_ids", {"state-a", "state-b"}))
    enhanced, anchors = enhance_query(bank, query, client)  # type: ignore[arg-type]
    assert enhanced.startswith(query) and anchors == ["Plan B", "amber"]
    assert len(seen) == 2
    assert json.loads(seen[1]["messages"][1]["content"])["directory"] == (
        json.loads(seen[0]["messages"][1]["content"])["directory"])


def test_query_enhancement_and_embedding_are_both_charged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, config = _case(), _config(tmp_path)
    case["states"].append(_state("state-c", "Plan C is crimson."))
    root = tmp_path / "job"
    root.mkdir()
    requests: list[dict[str, Any]] = []
    embedded: list[list[str]] = []

    class SelectionClient:
        def __init__(self, _config: Any, *, emit: Any, **_kwargs: Any) -> None:
            self.emit = emit

        def __enter__(self) -> SelectionClient:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def chat(self, _messages: Any, **_kwargs: Any) -> dict[str, Any]:
            self.emit({"event": "vllm_response", "path": "chat/completions",
                       "usage": {"prompt_tokens": 5, "total_tokens": 9}})
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"entity_anchors":["amber"]}'}}]}

        def embed(self, texts: list[str], _model: str) -> list[list[float]]:
            embedded.append(texts)
            self.emit({"event": "vllm_response", "path": "embeddings",
                       "usage": {"prompt_tokens": 6, "total_tokens": 6}})
            return [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]

    monkeypatch.setattr(runner, "VLLMClient", SelectionClient)
    with _runtime(root, [{"answer": "Read-only answer."}], requests) as runtime:
        output = runner._run_one(case, {"job_id": "job", "case_id": "case",
                                         "arm": "query_enhanced"}, config, runtime,
                                 root, "run:job", "query_enhanced")
    assert output["status"] == "COMPLETED"
    assert output["retrieval_query"].startswith(case["current_task"])
    assert output["entity_anchors"] == ["amber"]
    assert embedded[0][0] == output["retrieval_query"]
    assert output["selected_state_ids"] == ["state-a", "state-b"]
    assert "Plan C is crimson." not in requests[0]["messages"][0]["content"]
    assert output["accounting"]["by_role"]["query_enhancer"]["known_tokens"] == 9
    assert output["accounting"]["by_role"]["embedding"]["known_tokens"] == 6
    assert output["accounting"]["by_role"]["task_host"]["known_tokens"] == 25


def test_prepare_identity_and_attempt_guard(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    case, config = _case(), _config(tmp_path)
    config_path, inputs_path = tmp_path / "config.json", tmp_path / "inputs.json"
    write_json(config_path, config)
    write_json(inputs_path, {"kind": "MILAI_FIXED_READ_INPUTS", "cases": [case],
                             "jobs": [{"job_id": "one", "case_id": "case",
                                       "arm": "all"}]})
    root = tmp_path / "run"
    args = SimpleNamespace(config=config_path, inputs=inputs_path, run="run",
                           runtime_root=root, output=root / "prepared.json",
                           prepared=root / "prepared.json", job="one", stage="mock")
    lab_root = Path(__file__).resolve().parents[2]
    assert runner.prepare(args, lab_root=lab_root)["jobs"] == 1
    identity = read_json(root / "run_manifest.json")["identity"]
    assert identity["read_only_tool_catalog"]
    assert identity["inputs_sha256"]

    @contextmanager
    def fail_open(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("mock runtime failure")
        yield

    monkeypatch.setattr(runner, "open_application_runtime", fail_open)
    with pytest.raises(RuntimeError, match="mock runtime failure"):
        runner.run_job(args, lab_root=lab_root)
    with pytest.raises(ValueError, match="FIXED_READ_JOB_ALREADY_ATTEMPTED"):
        runner.run_job(args, lab_root=lab_root)
