from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
protocol = importlib.import_module("v02_low_cost_protocol")


def config() -> dict:
    return {"model_phase_limits": {"N0_N2": 4, "N3_N4": 12, "N5": 12, "total": 28},
            "known_token_launch_gate": 2400000, "batch_wall_seconds": 1200,
            "batch_session_limit": 4, "session_timeout_seconds": 300}


def test_projection_removes_task_fields_and_future_turns_without_rewriting_text() -> None:
    source = {"schema_version": "v02-lme-source-only-v1", "case_id": "a",
              "question": "SECRET FUTURE QUESTION", "question_date": "2099/01/01 00:00",
              "sessions": [{"session_ordinal": 0, "session_id": "session-0",
                            "observed_at": "2023/01/01 12:00", "turns": [
                                {"turn_ordinal": 0, "role": "user", "content": "exact\ntext"},
                                {"turn_ordinal": 2, "role": "assistant", "content": "future"}]}]}
    projected = protocol.derived_history(source, "2023-01-01T12:00:01+00:00")
    assert "SECRET FUTURE QUESTION" not in str(projected)
    assert len(projected["sessions"][0]["turns"]) == 1
    assert protocol.derived_events(projected, "branch")[0]["content"] == "exact\ntext"
    with pytest.raises(ValueError, match="task/label"):
        protocol.derived_events({**projected, "question": "leak"}, "branch")


def test_launch_gate_counts_cancelled_and_unknown_usage() -> None:
    a = {"phase": "N0_N2", "batch_id": "b"}
    cancelled = {"model_started": False, "usage": None, "raw_online_seconds": 0}
    with pytest.raises(RuntimeError, match="PHASE"):
        protocol.allocation_gate([(a, cancelled)] * 4, config(), "N0_N2", "next")
    with pytest.raises(RuntimeError, match="UNKNOWN"):
        protocol.allocation_gate([(a, {"model_started": True})], config(), "N0_N2", "next")
    with pytest.raises(RuntimeError, match="UNRESOLVED"):
        protocol.allocation_gate([(a, None)], config(), "N0_N2", "next")


def test_known_token_stop_and_batch_remaining_use_actual_cost() -> None:
    a = {"phase": "N3_N4", "batch_id": "b"}
    used = {"model_started": True, "usage": [{"input_tokens": 2399999, "output_tokens": 1}],
            "raw_online_seconds": 1190}
    with pytest.raises(RuntimeError, match="KNOWN_TOKEN"):
        protocol.allocation_gate([(a, used)], config(), "N3_N4", "b")
    used["usage"][0]["input_tokens"] = 10
    assert protocol.allocation_gate([(a, used)], config(), "N3_N4", "b") == 10


def test_corrective_run_retains_prior_budget_and_unresolved_allocations(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    for root in (old, new):
        directory = root / "sessions" / "a"
        directory.mkdir(parents=True)
        (directory / "allocation.json").write_text(json.dumps({"phase": "N3_N4",
                                                               "batch_id": root.name}))
    (old / "sessions/a/result.json").write_text(json.dumps({
        "usage": [{"input_tokens": 2400000, "output_tokens": 0}]}))
    rows = protocol.allocation_rows([old, new, old])
    assert len(rows) == 2
    with pytest.raises(RuntimeError, match="UNRESOLVED"):
        protocol.allocation_gate(rows, config(), "N3_N4", "next")
    (new / "sessions/a/result.json").write_text(json.dumps({"model_started": False}))
    with pytest.raises(RuntimeError, match="KNOWN_TOKEN"):
        protocol.allocation_gate(protocol.allocation_rows([old, new]), config(), "N3_N4", "next")
    with pytest.raises(ValueError, match="Missing allocation root"):
        protocol.allocation_rows([tmp_path / "missing"])
