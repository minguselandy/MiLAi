from __future__ import annotations

import importlib
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
deadline_module = importlib.import_module("v02_deadline")
provider_module = importlib.import_module("v02_local_provider")
runner = importlib.import_module("run_v02_local_vllm")
state = importlib.import_module("v02_e2e_state")


def config():
    value = json.loads(runner.CONFIG.read_text())
    value.update(
        model_transport_enabled=True,
        new_model_allocations_authorized=3,
        new_model_tokens_authorized=60000,
        session_timeout_seconds=30,
    )
    return value


@pytest.mark.parametrize("stage", ["restore", "tool", "checkpoint"])
def test_one_deadline_does_not_reset_for_each_stage(stage):
    now = [100.0]
    deadline = deadline_module.Deadline(100, 30, lambda: now[0])
    now[0] += 29
    assert deadline.check("earlier") == 1
    now[0] += 2
    with pytest.raises(deadline_module.DeadlineExpired, match=stage):
        deadline.check(stage)


def test_tokenization_consumes_remaining_time_before_any_generation(tmp_path):
    now = [100.0]
    deadline = deadline_module.Deadline(100, 30, lambda: now[0])
    calls = []

    def handle(request):
        calls.append(request.url.path)
        now[0] += 31
        return httpx.Response(200, json={"count": 100})

    provider = provider_module.LocalProvider(
        config(), tmp_path, "G", httpx.MockTransport(handle), deadline=deadline
    )
    with pytest.raises(deadline_module.DeadlineExpired):
        provider.complete([], {}, tmp_path)
    provider.close()
    assert calls == ["/tokenize"]
    assert not provider_module.read_events(tmp_path / "provider-ledger.jsonl")


def test_cancellation_during_generation_keeps_reservation_and_blocks_restart(tmp_path):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        raise deadline_module.DeadlineExpired("synthetic clock cancellation")

    provider = provider_module.LocalProvider(config(), tmp_path, "G", httpx.MockTransport(handle))
    with pytest.raises(deadline_module.DeadlineExpired):
        provider.complete([], {}, tmp_path)
    provider.close()
    events = provider_module.read_events(tmp_path / "provider-ledger.jsonl")
    assert provider_module.accounting(events)["pending"]
    again = provider_module.LocalProvider(config(), tmp_path, "B", httpx.MockTransport(handle))
    with pytest.raises(provider_module.LocalGateError, match="UNRESOLVED"):
        again.complete([], {}, tmp_path)
    again.close()
    assert calls == ["/tokenize", "/v1/chat/completions"]


def test_save_cancellation_keeps_operation_unknown_without_followup_get(tmp_path):
    local = {"experiment_id": "test", "l1_path": "l1", "l2_path": "l2"}
    (tmp_path / "l1").write_text("state")
    (tmp_path / "l2").write_text("detail")
    calls = []

    def call(tool, args):
        calls.append(tool)
        if tool.endswith("update"):
            raise deadline_module.DeadlineExpired("write outcome unknown")
        return {
            "schema_version": "host-cognitive-state-v1",
            "authority": "HOST_WORKING",
            "scope": "TASK",
            "status": "ABSENT",
            "version": 0,
            "state_id": None,
            "payload": {},
            "warnings": [],
        }

    value = state.save_layers(call, tmp_path, local, {}, "one")
    assert value["cancelled"] and value["operation"]["outcome"] == "UNKNOWN"
    assert calls == ["milai_working_state_get", "milai_working_state_update"]


def test_worker_includes_tail_save_and_preserves_delivered_task_on_timeout(tmp_path, monkeypatch):
    cfg = config()
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    directory = tmp_path / "G"
    workspace = directory / "workspace"
    workspace.mkdir(parents=True)
    (directory / "assignment.json").write_text(
        json.dumps({"project": "p", "task_ref": "t", "task": "work", "file_evidence_refs": {}})
    )
    (directory / "initial-files.json").write_text("{}")
    now = [100.0]
    deadline = deadline_module.Deadline(100, 30, lambda: now[0])
    seen = []

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self):
            return {}

        def close(self):
            pass

        def complete(self, *args):
            now[0] += 15
            return json.dumps({"tool": "finish", "answer": "delivered", "arguments_json": "{}"})

    @contextmanager
    def observer(*args):
        def call(tool, args):
            seen.append(tool)
            if tool is None:
                return {"tools": {"tools": []}}
            return {
                "schema_version": "host-cognitive-state-v1",
                "authority": "HOST_WORKING",
                "scope": "TASK",
                "status": "ABSENT",
                "version": 0,
                "state_id": None,
                "payload": {},
                "warnings": [],
            }

        now[0] += 10
        yield call, {}

    def checkpoint(*args, **kwargs):
        assert "call" in kwargs
        seen.append("required_save")
        now[0] += 6
        return {"status": "UNKNOWN", "operation": {"outcome": "UNKNOWN"}}

    monkeypatch.setattr(runner, "LocalProvider", Provider)
    monkeypatch.setattr(runner, "observer", observer)
    monkeypatch.setattr(runner, "checkpoint", checkpoint)
    runner._session(tmp_path, "G", deadline)
    result = json.loads((directory / "result.json").read_text())
    assert result["task_delivered"] and result["answer"] == "delivered"
    assert json.loads((directory / "final-delivery.json").read_text())["answer"] == "delivered"
    assert result["status"] == "FAILED" and result["error_type"] == "DeadlineExpired"
    assert result["deadline"]["online_elapsed_seconds"] == 31
    assert seen[-1] == "required_save"
    assert json.loads((tmp_path / "checkpoint-result.json").read_text())["status"] == "UNKNOWN"


def test_real_process_alarm_interrupts_blocking_tool():
    code = (
        "import time\nfrom v02_deadline import Deadline, DeadlineExpired\n"
        "try:\n with Deadline(time.monotonic(), .05):\n  time.sleep(5)\n"
        "except DeadlineExpired:\n print('CANCELLED')\nelse:\n raise AssertionError()\n"
    )
    completed = subprocess.run(  # noqa: S603 -- fixed no-model worker
        [sys.executable, "-c", code],
        cwd=TOOLS,
        capture_output=True,
        text=True,
        timeout=3,
        check=True,
    )
    assert completed.stdout.strip() == "CANCELLED"


def test_real_process_kill_after_reservation_blocks_next_request(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(config()))
    code = """
import json, os, signal, sys
from pathlib import Path
import httpx
from v02_local_provider import LocalProvider
root = Path(sys.argv[1])
def handle(request):
    if request.url.path == '/tokenize':
        return httpx.Response(200, json={'count': 100})
    os.kill(os.getpid(), signal.SIGKILL)
provider = LocalProvider(json.loads((root/'config.json').read_text()), root, 'G',
                         httpx.MockTransport(handle))
provider.complete([], {}, root)
"""
    completed = subprocess.run(  # noqa: S603 -- fixed no-network crash worker
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=TOOLS,
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert completed.returncode == -9
    events = provider_module.read_events(tmp_path / "provider-ledger.jsonl")
    assert provider_module.accounting(events)["pending"]
    assert any(e["event"] == "DISPATCH_ATTEMPT" for e in events)
    client = provider_module.LocalProvider(
        config(),
        tmp_path,
        "B",
        httpx.MockTransport(lambda _: pytest.fail("Network after unknown killed request")),
    )
    with pytest.raises(provider_module.LocalGateError, match="UNRESOLVED"):
        client.complete([], {}, tmp_path)
    client.close()


def test_late_valid_usage_is_settled_but_output_is_not_acted_on(tmp_path):
    now = [100.0]
    deadline = deadline_module.Deadline(100, 30, lambda: now[0])

    def handle(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        now[0] += 31
        return httpx.Response(
            200,
            json={
                "id": "late",
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            },
        )

    client = provider_module.LocalProvider(
        config(), tmp_path, "G", httpx.MockTransport(handle), deadline=deadline
    )
    with pytest.raises(deadline_module.DeadlineExpired, match="response_settled"):
        client.complete([], {}, tmp_path)
    client.close()
    ledger = provider_module.accounting(
        provider_module.read_events(tmp_path / "provider-ledger.jsonl")
    )
    assert ledger["raw_tokens"] == 110 and ledger["pending"] == []


def test_parent_deadline_stops_preparation_before_worker_launch(tmp_path, monkeypatch):
    cfg = config()
    cfg["session_timeout_seconds"] = 0.05
    (tmp_path / "config.json").write_text(json.dumps(cfg))

    class SlowFiles(dict):
        def items(self):
            time.sleep(5)
            return super().items()

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("Worker started"))
    value = runner.launch(tmp_path, "G", "task", SlowFiles({"source": "text"}), None)
    assert value["status"] == "FAILED" and "SESSION_DEADLINE" in value["error"]
    assert value["deadline"]["online_elapsed_seconds"] < 1
    assert not (tmp_path / "provider-ledger.jsonl").exists()
