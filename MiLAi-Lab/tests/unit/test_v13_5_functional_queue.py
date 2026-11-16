"""Finite queue admission is durable even when no provider response returns."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget, RunLimits
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.providers.functional_queue import FunctionalQueue, FunctionalVLLMClient


def test_unknown_reservation_survives_independent_process(tmp_path: Path) -> None:
    path = tmp_path / "admission.json"
    gate = FunctionalQueue(path, requests=2, reserved_tokens=100)
    gate.reserve({"messages": [{"role": "user", "content": "保存"}]}, {"total_reserved_tokens": 40})
    child = subprocess.run(  # noqa: S603 -- fixed local Python and argv, no shell
        [
            sys.executable,
            "-c",
            """
from pathlib import Path
import sys
from milai_lab.providers.functional_queue import FunctionalQueue
FunctionalQueue(Path(sys.argv[1]), requests=2, reserved_tokens=100).reserve(
    {'messages': []}, {'total_reserved_tokens': 40})
""",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    with pytest.raises(BudgetExceeded, match="QUEUE_BUDGET_EXHAUSTED"):
        gate.reserve({}, {"total_reserved_tokens": 1})
    saved = json.loads(path.read_text())
    assert saved["requests"] == 2
    assert saved["reserved_tokens"] == 80
    assert len(saved["reservations"]) == 2


def test_tokens_reject_before_reservation_and_changed_config(tmp_path: Path) -> None:
    path = tmp_path / "admission.json"
    gate = FunctionalQueue(path, requests=8, reserved_tokens=100)
    gate.reserve({}, {"total_reserved_tokens": 90})
    before = path.read_bytes()
    with pytest.raises(BudgetExceeded):
        gate.reserve({}, {"total_reserved_tokens": 11})
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="CONFIGURATION_CHANGED"):
        FunctionalQueue(path, requests=9, reserved_tokens=100).reserve(
            {}, {"total_reserved_tokens": 1}
        )
    assert path.read_bytes() == before


def test_durable_counter_cannot_drop_earlier_unknown_reservation(tmp_path: Path) -> None:
    path = tmp_path / "admission.json"
    gate = FunctionalQueue(path, requests=2, reserved_tokens=100)
    gate.reserve({}, {"total_reserved_tokens": 40})
    corrupt = json.loads(path.read_text())
    corrupt["requests"] = 0
    path.write_text(json.dumps(corrupt))
    with pytest.raises(ValueError, match="FUNCTIONAL_QUEUE_STATE_INVALID"):
        gate.reserve({}, {"total_reserved_tokens": 40})


@pytest.mark.parametrize("confirmed_usage", [True, False])
def test_queued_native_accounting_and_transport_receipt_are_preserved(
    tmp_path: Path, confirmed_usage: bool,
) -> None:
    wire = {"model": "fixture", "messages": [], "max_completion_tokens": 2}
    accounting = {**wire, "max_tokens": 2}
    capacity = {"prompt_tokens": 3, "output_reserve_tokens": 2, "total_reserved_tokens": 5}
    events: list[dict[str, Any]] = []
    actual_requests: list[dict[str, Any]] = []
    budget = RunBudget(RunLimits(generation_requests=2, generation_tokens=100),
                       tmp_path / "budget.json")

    def complete(request: httpx.Request) -> httpx.Response:
        actual_requests.append(json.loads(request.content))
        usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        if not confirmed_usage:
            usage["total_tokens"] = 4
        return httpx.Response(200, json={"choices": [], "usage": usage})

    with FunctionalVLLMClient(
        VLLMConfig("http://fixture/v1", "fixture", max_tokens=2), budget=budget,
        transport=httpx.MockTransport(complete),
    ) as client:
        client.queue = FunctionalQueue(tmp_path / "admission.json", requests=1,
                                       reserved_tokens=5)
        client._post("chat/completions", wire, capacity_receipt=capacity,
                     accounting_request=accounting, on_event=events.append)
        with pytest.raises(BudgetExceeded, match="FUNCTIONAL_QUEUE_BUDGET_EXHAUSTED"):
            client._post("chat/completions", wire, capacity_receipt=capacity,
                         accounting_request=accounting, on_event=events.append)

    assert actual_requests == [wire]
    assert events[-1]["usage_confirmed"] is confirmed_usage
    assert events[-1]["accounting_request"] == accounting
    assert json.loads(events[-1]["request_body"]) == wire
    assert budget.state["generation_requests"] == 1
    assert budget.state["generation"]["known_tokens"] == (5 if confirmed_usage else 0)
    assert budget.state["generation"]["charged_tokens"] == 5
    assert budget.state["generation"]["unknown_usage"] == (0 if confirmed_usage else 1)
    assert json.loads((tmp_path / "admission.json").read_text())["requests"] == 1
