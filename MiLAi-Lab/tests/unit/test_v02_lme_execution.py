from __future__ import annotations

import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
runner = importlib.import_module("run_v02_lme_incremental")
host = importlib.import_module("v02_lme_host")
sources = importlib.import_module("v02_lme_sources")


def test_source_mapping_preserves_duplicate_session_instances_and_roles() -> None:
    source = {"schema_version": "v02-lme-source-only-v1", "case_id": "a", "question": "q",
              "question_date": "2023/01/02", "sessions": [
                  {"session_id": f"session-{index}", "session_ordinal": index,
                   "observed_at": "2023/01/01 (Sun) 10:00", "turns": [
                       {"turn_ordinal": 0, "role": "user", "content": "question"},
                       {"turn_ordinal": 1, "role": "assistant", "content": "response"},
                   ]} for index in [0, 1]]}
    events = sources.history_events(source, "branch-a")
    other = sources.history_events(source, "branch-b")
    assert len(events) == 4
    assert len({e["source_id"] for e in events}) == 4
    assert len({e["session_id"] for e in events}) == 2
    assert events[1]["event_type"] == "ASSISTANT_MESSAGE"
    assert events[0]["next_turn_id"] == events[1]["turn_id"]
    assert {e["event_id"] for e in events}.isdisjoint(e["event_id"] for e in other)
    source["sessions"][0]["session_id"] = "answer_secret"
    with pytest.raises(ValueError, match="neutral"):
        sources.history_events(source, "branch-c")
    source["sessions"][0]["session_id"] = "session-0"
    source["answer"] = "forbidden"
    with pytest.raises(ValueError, match="unapproved"):
        sources.history_events(source, "branch-c")


@pytest.mark.parametrize("tool_count,deadline,expected", [(24, 10, "TOOL_WATCHDOG"),
                                                        (0, .1, "SESSION_TIMEOUT")])
def test_actual_watchdog_terminates_non_model_process(
    tmp_path: Path, tool_count: int, deadline: float, expected: str,
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text("".join(json.dumps({"type": "item.started", "item": {
        "id": str(i), "type": "file_change"}}) + "\n" for i in range(tool_count)))
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    started = time.perf_counter()
    try:
        reason = host.watch_process(process, events, started, deadline, 24, process.terminate)
        assert reason == expected
        assert process.poll() is not None
        assert time.perf_counter() - started < 3
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_budget_counts_failed_allocations_and_online_sum(tmp_path: Path) -> None:
    root = tmp_path / "run"
    old = root / "sessions" / "failed"
    old.mkdir(parents=True)
    (old / "allocation.json").write_text(json.dumps({
        "phase": "L0_L2", "kind": "SMOKE", "batch_id": "batch"}))
    (old / "result.json").write_text(json.dumps({"elapsed_seconds": 1100, "returncode": 1}))
    config = {"model_phase_limits": {"L0_L2": 16, "total": 40},
              "batch_session_limit": 4, "batch_wall_seconds": 1200,
              "session_timeout_seconds": 300}
    _, allowed = runner.reserve(root, "next", "batch", "SMOKE", config)
    assert allowed == 100
    (old / "result.json").unlink()
    with pytest.raises(RuntimeError, match="Unresolved"):
        runner.reserve(root, "other", "nextbatch", "DIAGNOSTIC", config)
