from __future__ import annotations

import importlib
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
summary = importlib.import_module("summarize_v02_e2e_generality")
provider_module = importlib.import_module("v02_local_provider")
runner = importlib.import_module("run_v02_local_vllm")
deadline_module = importlib.import_module("v02_deadline")


@pytest.mark.parametrize("mode", ["not_assembled", "reserved_only", "unknown", "confirmed"])
def test_acquired_span_does_not_prove_presentation(tmp_path, mode):
    config = json.loads(
        (Path(__file__).resolve().parents[2] / "configs/v02-local-vllm-simulation.json").read_text()
    )
    config.update(
        model_transport_enabled=True,
        new_model_allocations_authorized=3,
        new_model_tokens_authorized=60000,
    )
    directory = tmp_path / "G"
    directory.mkdir()
    marker = "CRITICAL_SPAN_f51a"
    # This acquisition artifact alone must never be counted as model input.
    (directory / "tool-result.json").write_text(json.dumps({"text": marker}))

    def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        if mode == "unknown":
            raise httpx.ReadTimeout("response lost")
        return httpx.Response(
            200,
            json={
                "id": "observed",
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            },
        )

    provider = provider_module.LocalProvider(config, tmp_path, "G", httpx.MockTransport(handle))
    messages = [{"role": "user", "content": marker if mode != "not_assembled" else "other"}]
    if mode == "unknown":
        with pytest.raises(provider_module.LocalGateError, match="UNRESOLVED"):
            provider.complete(messages, {}, directory)
    else:
        provider.complete(messages, {}, directory)
    provider.close()
    if mode == "reserved_only":
        # Negative fixture has a saved request and reservation but no dispatch evidence.
        ledger = provider_module.read_events(tmp_path / "provider-ledger.jsonl")
        (tmp_path / "provider-ledger.jsonl").write_text(json.dumps(ledger[0]) + "\n")
        (directory / "G-001-http.json").unlink()
    observed = summary.span_observation(summary.observe_requests(tmp_path, "G"), marker)
    expected = {
        "not_assembled": "NOT_PROVEN_PRESENTED",
        "reserved_only": "NOT_PROVEN_PRESENTED",
        "unknown": "INPUT_SUBMISSION_UNKNOWN",
        "confirmed": "CONFIRMED_INPUT",
    }
    assert observed["status"] == expected[mode]
    assert observed["correct_interpretation"] == "NOT_EVALUATED"
    if mode == "confirmed":
        path = directory / "G-001-request.json"
        changed = json.loads(path.read_text())
        changed["messages"][0]["content"] = "different"
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
            summary.observe_requests(tmp_path, "G")


def test_actual_host_request_path_prefetches_only_for_a(tmp_path, monkeypatch):
    config = json.loads(runner.CONFIG.read_text())
    config.update(
        model_transport_enabled=True,
        new_model_allocations_authorized=3,
        new_model_tokens_authorized=60000,
        session_timeout_seconds=30,
    )
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "evaluation-contract.json").write_text('{"gold":"EVALUATOR_ONLY_f7a"}')
    continuation = importlib.import_module("run_v02_e2e_generality").continuation_task({
        "question": "Same continuation", "question_date": "2023/02/15 (Wed) 23:50",
    })
    bodies = []
    head = {}

    def handle(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": provider_module.MODEL}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "tool": "finish",
                                    "answer": "fixture output",
                                    "arguments_json": "{}",
                                }
                            )
                        },
                    }
                ],
            },
        )

    @contextmanager
    def observer(*args):
        def call(tool, args):
            return {"tools": {"tools": []}} if tool is None else head

        yield call, {}

    monkeypatch.setattr(runner, "observer", observer)
    monkeypatch.setattr(
        runner,
        "LocalProvider",
        lambda *args, **kwargs: provider_module.LocalProvider(
            *args, **kwargs, transport=httpx.MockTransport(handle)
        ),
    )
    for arm in ("A", "B"):
        directory = tmp_path / arm
        workspace = directory / "workspace"
        workspace.mkdir(parents=True)
        detail = workspace / config["l2_path"]
        detail.write_text("DETAIL_ONLY_CANARY_e19d")
        files = runner.manifest(workspace)
        (directory / "initial-files.json").write_text(json.dumps(files))
        (directory / "assignment.json").write_text(
            json.dumps(
                {
                    "project": "p",
                    "task_ref": arm,
                    "task": continuation,
                    "file_evidence_refs": {config["l2_path"]: []},
                }
            )
        )
        head = {
            "schema_version": "host-cognitive-state-v1",
            "authority": "HOST_WORKING",
            "scope": "TASK",
            "status": "ACTIVE",
            "version": 1,
            "state_id": "same",
            "state_version_id": "same-version",
            "warnings": [],
            "payload": {
                runner.FIELD: {
                    "owner": config["experiment_id"],
                    "l1": "L1_CANARY_a83f",
                    "l2": {"path": config["l2_path"], "sha256": runner.sha(detail)},
                    "evidence_refs": [],
                }
            },
        }
        runner._session(tmp_path, arm, deadline_module.Deadline(time.monotonic(), 30))
        assert json.loads((directory / "result.json").read_text())["status"] == "COMPLETED"
    assert len(bodies) == 2
    assert all(
        any(m["role"] == "user" and m["content"].startswith(continuation + "\n")
            for m in body["messages"])
        for body in bodies
    )
    assert all("EVALUATOR_ONLY_f7a" not in json.dumps(body) for body in bodies)
    assert all("L1_CANARY_a83f" in json.dumps(body) for body in bodies)
    assert "DETAIL_ONLY_CANARY_e19d" in json.dumps(bodies[0])
    assert "DETAIL_ONLY_CANARY_e19d" not in json.dumps(bodies[1])
    for arm, expected in (("A", "CONFIRMED_INPUT"), ("B", "NOT_PROVEN_PRESENTED")):
        observed = summary.span_observation(
            summary.observe_requests(tmp_path, arm), "DETAIL_ONLY_CANARY_e19d"
        )
        assert observed["status"] == expected
