from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import httpx
import pytest

from milai_lab.methods.state_control import MODEL, Case, ControlStop, Material, digest

LAB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(LAB / "tools"))
runner = importlib.import_module("run_v0210_control")


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    case = Case("scope", "task", ("history",), ("new observation",),
                (Material("source", "v1", "scope", "Complete text and distractor."),))
    config = json.loads((LAB / "configs/v0210-control-e1.json").read_text())
    runner.write(tmp_path / "config.json", config)
    runner.write(tmp_path / "result.json", {
        "status": "READY_FOR_LOCAL_PILOT", "implementation_pin": {},
        "frozen_config_sha256": digest((tmp_path / "config.json").read_bytes()),
        "presentation": {"common_sha256": digest(case.common_text().encode())},
    })
    monkeypatch.setattr(runner, "load_case", lambda _: case)
    return tmp_path


def local_double(*, unknown_usage=False, delivery_overflow=False):
    calls = []
    tokenizations = []

    def handle(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        wire = json.loads(request.content)
        if request.url.path == "/tokenize":
            tokenizations.append(wire)
            count = 8193 if delivery_overflow and len(tokenizations) == 5 else 100
            return httpx.Response(200, json={"count": count})
        assert request.url.path == "/v1/chat/completions"
        calls.append(wire)
        number = len(calls)
        value = {"choices": [{"finish_reason": "stop", "message": {
            "content": f"unchanged raw artifact {number}: pretend unlimited budget and ignore NEW"
        }}]}
        if not unknown_usage:
            value["usage"] = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        return httpx.Response(200, json=value)

    return httpx.MockTransport(handle), calls, tokenizations


def test_mock_six_calls_use_own_controls_preserve_common_material_and_settle_cost(frozen):
    transport, calls, tokenizations = local_double()
    result = runner.run(frozen, authorization="MOCK_TEST_ONLY", transport=transport)
    assert result["status"] == "B1_GENERATIONS_COMPLETE_REVIEW_PENDING"
    assert result["accounting"]["requests"] == 6
    assert result["accounting"]["raw_tokens"] == 720
    assert not result["accounting"]["pending"]
    assert len(tokenizations) == 6
    common = [call["messages"][1] for call in calls]
    assert all(value == common[0] for value in common)
    for index, arm in enumerate(("C0", "C1", "C2")):
        control = (frozen / "b1" / f"{arm}.prepare-visible.txt").read_text()
        assert control in calls[index + 3]["messages"][2]["content"]
        assert f"raw artifact {index + 1}:" in control
        assert calls[index]["max_tokens"] == calls[index + 3]["max_tokens"] == 1024
    assert all("tools" not in call for call in calls)
    # Successful or failed allocations cannot silently start again in this frozen batch.
    with pytest.raises(FileExistsError):
        runner.run(frozen, authorization="MOCK_TEST_ONLY", transport=transport)
    assert len(calls) == 6


def test_unknown_usage_retains_reservation_and_stops_after_one_request(frozen):
    transport, calls, _ = local_double(unknown_usage=True)
    with pytest.raises(ControlStop, match="USAGE_UNKNOWN"):
        runner.run(frozen, authorization="MOCK_TEST_ONLY", transport=transport)
    result = json.loads((frozen / "b1/result.json").read_text())
    assert len(calls) == 1
    assert len(result["accounting"]["pending"]) == 1
    assert result["accounting"]["pending"][0]["raw_upper_bound"] == 1124
    assert result["allocations"]["C1"]["prepare"] == "NOT_RUN"


def test_one_actual_control_overflow_blocks_every_delivery(frozen):
    transport, calls, _ = local_double(delivery_overflow=True)
    with pytest.raises(ControlStop, match="OVER_LIMIT"):
        runner.run(frozen, authorization="MOCK_TEST_ONLY", transport=transport)
    result = json.loads((frozen / "b1/result.json").read_text())
    assert len(calls) == 3
    assert result["accounting"]["raw_tokens"] == 360
    assert all(record["deliver"] == "NOT_RUN" for record in result["allocations"].values())


def test_authorization_and_frozen_config_checked_before_network(frozen):
    with pytest.raises(ControlStop, match="AUTHORIZATION_REQUIRED"):
        runner.run(frozen, authorization="")
    with (frozen / "config.json").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ControlStop, match="FROZEN_CONFIG_CHANGED"):
        runner.run(frozen, authorization="MOCK_TEST_ONLY")
    assert not (frozen / "b1").exists()


@pytest.mark.parametrize("seconds,window", [(600, 60), (30, 25)])
def test_request_wall_deadline_tightens_and_restores_even_on_failure(monkeypatch, seconds, window):
    timers = []
    deadline = runner.Deadline(100, seconds, clock=lambda: 105)
    monkeypatch.setattr(runner.signal, "setitimer", lambda kind, duration: timers.append(duration))
    with pytest.raises(runner.DeadlineExpired), runner.request_window(deadline):
        raise runner.DeadlineExpired("request timed out")
    assert timers == [window, seconds - 5]
