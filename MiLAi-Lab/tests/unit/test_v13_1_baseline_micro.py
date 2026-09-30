"""Generic orchestration with Fake native SDK boundary, MockHTTP, and local resources."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.runners import v13_1_baseline_micro as runner


def inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str = "simplemem_text"
) -> Path:
    RunBudget(RunLimits(1, 1, None, None, None), tmp_path / "ledger.json").reserve(
        "chat/completions",
        {"messages": [], "max_tokens": 1},
    )
    fixture = {
        "cases": [
            {
                "case_id": "public-case",
                "owner": "alice",
                "steps": [
                    {
                        "step_id": "save",
                        "operation": "archive",
                        "records": [
                            {
                                "role": "tool",
                                "event_id": "actual-event",
                                "id": "actual-message",
                                "content": "original partial receipt",
                                "status": "partial",
                            },
                        ],
                    },
                    {
                        "step_id": "query",
                        "operation": "search",
                        "query": "native query",
                        "reader_question": "FUTURE_READER_QUESTION",
                        "generation_cap": 2,
                    },
                    {
                        "step_id": "refused",
                        "operation": "archive",
                        "generation_cap": 0,
                        "records": [{"role": "user", "content": "second actual archive"}],
                    },
                    {
                        "step_id": "foreign",
                        "operation": "search",
                        "owner": "bob",
                        "query": "foreign query",
                    },
                    {"step_id": "snapshot", "operation": "snapshot"},
                ],
            }
        ]
    }
    config = {
        "host": {"base_url": "http://mock/v1/", "model": "mechanical", "temperature": 0},
        "embedding": {"base_url": "http://mock/v1/", "model": "bge-m3"},
        "capacity": {},
        "budget_path": str(tmp_path / "ledger.json"),
        "reader_system_prompt": "  Configured common reader prompt.\n",
        "embedding_dimension": 1024,
        "embedding_context_tokens": 8192,
        "simplemem_source_root": str(tmp_path / "unused-pinned-source"),
    }
    write_json(tmp_path / "public.json", fixture)
    write_json(tmp_path / "config.json", config)
    monkeypatch.setattr(
        runner,
        "_dependency_identity",
        lambda backend, config: {
            "source_commit": "fake-SDK-boundary",
            "backend": backend,
        },
    )
    root = tmp_path / "run"
    runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root, backend)
    return root


def mock_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict[str, Any]], list[Any]]:
    wires: list[dict[str, Any]] = []
    calls: list[Any] = []
    original_client = runner.VLLMClient

    def send(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        wires.append({"path": request.url.path, **body})
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [0.01] * 1024}
                        for index, _ in enumerate(body["input"])
                    ],
                    "usage": {"total_tokens": 3},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "common answer"},
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
        )

    class Native:
        def __init__(
            self,
            backend: str,
            config: Any,
            resource: Path,
            run_id: str,
            owner: str,
            host: Any,
            embed: Any,
            admit: Any,
        ) -> None:
            self.backend, self.resource, self.owner = backend, resource, owner
            self.host, self.embed, self.admit = host, embed, admit
            calls.append(("open", resource, owner))
            assert host.budget is embed.budget

        def snapshot(self, owner: str) -> list[Any]:
            if owner != self.owner:
                if self.backend == "simplemem_text":
                    raise ValueError("SIMPLEMEM_OWNER_SCOPE_CHANGED")
                return []
            path = self.resource / "native.json"
            return read_json(path) if path.exists() else []

        def add_archive(self, owner: str, records: Any) -> dict[str, Any]:
            calls.append(("archive", json.loads(json.dumps(records))))
            try:
                self.admit()
            except ValueError as error:
                return {
                    "status": "INCOMPLETE"
                    if self.backend == "simplemem_text"
                    else ("MAINTENANCE_INCOMPLETE"),
                    "admission_rejections": [str(error)],
                    "records_after": self.snapshot(owner),
                }
            self.host.chat([{"role": "user", "content": json.dumps(records)}])
            self.embed.embed(["native formed text"], "bge-m3")
            saved = [*self.snapshot(owner), *records]
            write_json(self.resource / "native.json", saved)
            return {"status": "COMPLETED", "records_after": saved}

        def search_archive(self, owner: str, query: str) -> dict[str, Any]:
            rows = self.snapshot(owner)
            self.admit()
            self.host.chat([{"role": "user", "content": query}])
            return {"results": rows}

        def close(self) -> None:
            calls.append(("close", self.resource))

    monkeypatch.setattr(runner, "HostCapacity", lambda config: None)
    monkeypatch.setattr(
        runner,
        "VLLMClient",
        lambda *args, **kwargs: original_client(
            *args,
            transport=httpx.MockTransport(send),
            **kwargs,
        ),
    )
    monkeypatch.setattr(runner, "_native_runtime", Native)
    return wires, calls


@pytest.mark.parametrize("backend", ["simplemem_text", "mem0_oss"])
def test_archive_is_current_records_only_and_reader_uses_shared_wire_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    root = inputs(tmp_path, monkeypatch, backend)
    wires, calls = mock_runtime(monkeypatch)
    frozen = runner._frozen(root)
    saved = runner.step(root, "public-case", "save")
    assert saved["status"] == "COMPLETED" and not saved["stop_case"]
    assert "FUTURE_READER_QUESTION" not in json.dumps(wires)
    archived = next(row[1] for row in calls if row[0] == "archive")
    assert archived == frozen["fixture"]["cases"][0]["steps"][0]["records"]
    queried = runner.step(root, "public-case", "query")
    assert queried["reader_status"] == "COMPLETED" and queried["answer"] == "common answer"
    assert queried["generation_admitted"] == 2
    assert (
        queried["budget_after"]["generation_requests"]
        - queried["budget_before"]["generation_requests"]
        == 2
    )
    reader = wires[-1]
    assert reader["messages"][0] == {
        "role": "system",
        "content": frozen["config"]["reader_system_prompt"],
    }
    assert json.loads(reader["messages"][1]["content"]) == {
        "question": "FUTURE_READER_QUESTION",
        "memories": saved["records_after"],
    }
    assert reader["temperature"] == 0
    assert queried["process_id"] == os.getpid() and queried["persistent_resource_bytes"]
    count = len(wires)
    assert runner.step(root, "public-case", "query") == queried and len(wires) == count
    assert len([row for row in calls if row[0] == "open"]) == 2


def test_reader_has_no_free_generation_after_native_consumes_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = inputs(tmp_path, monkeypatch)
    fixture = read_json(tmp_path / "public.json")
    fixture["cases"][0]["steps"][1]["generation_cap"] = 1
    write_json(tmp_path / "public.json", fixture)
    (root / "input-freeze.json").unlink()
    runner.prepare(tmp_path / "public.json", tmp_path / "config.json", root, "simplemem_text")
    wires, _calls = mock_runtime(monkeypatch)
    runner.step(root, "public-case", "save")
    before = len(wires)
    result = runner.step(root, "public-case", "query")
    assert result["status"] == "MAINTENANCE_INCOMPLETE" and not result["stop_case"]
    assert result["reader_status"] == "NOT_RUN_CAP_REFUSAL"
    assert len(wires) == before + 1 and result["generation_admitted"] == 1
    assert result["native_result"]["results"] == result["records_after"]


@pytest.mark.parametrize("backend", ["simplemem_text", "mem0_oss"])
def test_charged_formation_then_zero_cap_and_owner_range_preserve_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    root = inputs(tmp_path, monkeypatch, backend)
    wires, _calls = mock_runtime(monkeypatch)
    saved = runner.step(root, "public-case", "save")
    runner.step(root, "public-case", "query")
    before = len(wires)
    refused = runner.step(root, "public-case", "refused")
    expected_status = "INCOMPLETE" if backend == "simplemem_text" else "MAINTENANCE_INCOMPLETE"
    assert refused["status"] == refused["native_result"]["status"] == expected_status
    assert not refused["stop_case"]
    assert refused["records_after"] == saved["records_after"]
    assert len(wires) == before and refused["admission_rejections"]
    assert refused["budget_before"]["generation_requests"] > 0
    foreign = runner.step(root, "public-case", "foreign")
    if backend == "simplemem_text":
        assert foreign["status"] == "REJECTED" and not foreign["stop_case"]
    else:
        assert foreign["status"] == "COMPLETED" and foreign["native_result"]["results"] == []
    assert runner.step(root, "public-case", "snapshot")["records_after"] == saved["records_after"]
    first_path = runner._paths(root, "public-case", "refused")[0] / "first-error.json"
    assert read_json(first_path)["step_id"] == "refused"


def test_init_failure_terminal_and_first_error_are_persisted_without_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = inputs(tmp_path, monkeypatch)
    wires, _calls = mock_runtime(monkeypatch)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("native initialization failed before any provider")

    monkeypatch.setattr(runner, "_native_runtime", fail)
    result = runner.step(root, "public-case", "save")
    assert result["status"] == "INTERRUPTED" and result["stop_case"]
    assert result["failure_stage"] == "setup" and not wires
    assert result["error"] == "native initialization failed before any provider"
    assert runner.step(root, "public-case", "save") == result
    first_path = runner._paths(root, "public-case", "save")[0] / "first-error.json"
    assert read_json(first_path)["first_error"] == result["first_error"]


@pytest.mark.parametrize("backend", ["simplemem_text", "mem0_oss"])
def test_dynamic_constructor_uses_frozen_mode_and_same_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    from milai_lab.integrations.memory import mem0, simplemem

    captured: dict[str, Any] = {}

    def constructor(*args: Any, **kwargs: Any) -> object:
        captured.update(args=args, kwargs=kwargs)
        return object()

    module = simplemem if backend == "simplemem_text" else mem0
    class_name = "SimpleMemTextRuntime" if backend == "simplemem_text" else "Mem0NativeRuntime"
    monkeypatch.setattr(module, class_name, constructor)
    config = {"simplemem_source_root": str(tmp_path / "source")}
    host, embed, admit = object(), object(), object()
    runner._native_runtime(
        backend, config, tmp_path / "resource", "run", "alice", host, embed, admit
    )
    assert captured["kwargs"]["admit_generation"] is admit
    assert captured["args"][0] == tmp_path / "resource"
    if backend == "simplemem_text":
        assert captured["kwargs"]["archive_input_mode"] == "trace_equal_v1"
        assert captured["args"][3:6] == ("alice", host, embed)
        assert captured["args"][6] == {
            **simplemem.POLICY,
            "source_root": config["simplemem_source_root"],
        }
    else:
        assert "archive_input_mode" not in captured["kwargs"]
        assert captured["args"][3:5] == (host, embed)


def test_provider_interruption_retains_charges_trace_and_first_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = inputs(tmp_path, monkeypatch)
    mock_runtime(monkeypatch)
    original_client = runner.VLLMClient

    def failed_client(*args: Any, **kwargs: Any) -> Any:
        client = original_client(*args, **kwargs)
        client._client.close()
        client._client = httpx.Client(
            base_url="http://mock/v1/",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503, json={"error": "actual mock outage"}),
            ),
        )
        return client

    monkeypatch.setattr(runner, "VLLMClient", failed_client)
    result = runner.step(root, "public-case", "save")
    assert result["status"] == "INTERRUPTED" and result["stop_case"]
    assert result["first_error"]["event"]["http_status"] == 503
    assert result["first_error"]["event"]["event"] == "vllm_error"
    assert (
        result["budget_after"]["generation_requests"]
        == result["budget_before"]["generation_requests"] + 1
    )
    assert result["budget_after"]["generation"]["unknown_usage"] > 0
    assert runner.step(root, "public-case", "save") == result
    assert [row["status"] for row in runner.run(root)] == [
        "INTERRUPTED",
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    ]


@pytest.mark.parametrize(
    "changed", ["fixture", "config", "source", "dependency", "budget_limits", "freeze_copy"]
)
def test_zero_http_freeze_covers_prompt_policy_sources_and_detects_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("prepare must not instantiate provider or native runtime")

    monkeypatch.setattr(runner, "VLLMClient", forbidden)
    monkeypatch.setattr(runner, "HostCapacity", forbidden)
    monkeypatch.setattr(runner, "_native_runtime", forbidden)
    root = inputs(tmp_path, monkeypatch)
    frozen = runner._frozen(root)
    assert frozen["native"]["archive_input_mode"] == "trace_equal_v1"
    assert frozen["native"]["policy"]["enable_parallel_processing"] is False
    assert (
        frozen["reader_prompt_sha256"]
        == hashlib.sha256(
            frozen["config"]["reader_system_prompt"].encode(),
        ).hexdigest()
    )
    assert {
        "src/milai_lab/runners/v13_1_baseline_micro.py",
        "tools/run_v13_1_baseline_micro.py",
        "src/milai_lab/integrations/memory/simplemem.py",
        "src/milai_lab/baselines/langmem_instrumentation.py",
    } <= frozen["source_sha256"].keys()
    assert frozen["embedding_context"] == {"configured_tokens": 8192, "admission_enforced": False}
    if changed in {"fixture", "config"}:
        (tmp_path / ("public.json" if changed == "fixture" else "config.json")).write_text("{}")
    elif changed == "source":
        monkeypatch.setattr(runner, "_sources", lambda: {})
    elif changed == "dependency":
        monkeypatch.setattr(runner, "_dependency_identity", lambda *args: {})
    elif changed == "freeze_copy":
        frozen["config"]["reader_system_prompt"] = "unrecorded changed prompt"
        write_json(root / "input-freeze.json", frozen)
    else:
        ledger = read_json(tmp_path / "ledger.json")
        ledger["limits"]["questions"] += 1
        write_json(tmp_path / "ledger.json", ledger)
    with pytest.raises(ValueError, match="CHANGED"):
        runner._frozen(root)


def test_run_uses_step_processes_continues_rejection_and_marks_remaining_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = inputs(tmp_path, monkeypatch)
    process_calls: list[list[str]] = []

    def process(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        process_calls.append(args)
        case_id, step_id = args[args.index("--case-id") + 1], args[args.index("--step-id") + 1]
        status = "REJECTED" if step_id == "save" else "INTERRUPTED"
        write_json(
            runner._paths(root, case_id, step_id)[1],
            {
                "status": status,
                "stop_case": status == "INTERRUPTED",
                "process_id": 123,
            },
        )
        assert args[0] == sys.executable and kwargs["env"]["PYTHONPATH"] == str(runner.LAB / "src")
        return subprocess.CompletedProcess(args, int(status == "INTERRUPTED"), "terminal", "")

    monkeypatch.setattr(runner.subprocess, "run", process)
    results = runner.run(root)
    assert [row["status"] for row in results] == [
        "REJECTED",
        "INTERRUPTED",
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    ]
    assert len(process_calls) == 2
    assert runner.run(root)[:2] == [
        {
            "case_id": "public-case",
            "step_id": "save",
            "status": "REJECTED",
            "reused": True,
            "process_id": 123,
        },
        {
            "case_id": "public-case",
            "step_id": "query",
            "status": "INTERRUPTED",
            "reused": True,
            "process_id": 123,
        },
    ]


def test_real_cli_process_records_pre_provider_failure_pid(tmp_path: Path) -> None:
    root = tmp_path / "no-freeze"
    process = subprocess.run(  # noqa: S603 - fixed own CLI, no freeze means no provider execution
        [
            sys.executable,
            str(runner.CLI),
            "step",
            "--run-root",
            str(root),
            "--case-id",
            "public-case",
            "--step-id",
            "save",
        ],
        capture_output=True,
        text=True,
        cwd=runner.LAB,
        env={**os.environ, "PYTHONPATH": str(runner.LAB / "src")},
    )
    result = read_json(runner._paths(root, "public-case", "save")[1])
    assert process.returncode == 1 and result["status"] == "INTERRUPTED"
    assert result["process_id"] != os.getpid() and result["failure_stage"] == "freeze"
    assert result["generation_admitted"] == 0 and result["budget_after"] is None
