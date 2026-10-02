"""Finite queue admission is durable even when no provider response returns."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from milai_lab.harness.contextual_artifacts import BudgetExceeded
from milai_lab.providers.functional_queue import FunctionalQueue


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
