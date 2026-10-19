import importlib.util
import json
import sys
from pathlib import Path

import pytest

from milai_lab.runners import functional


def test_projection_preserves_source_sessions_roles_and_unknown_dates():
    spec = importlib.util.spec_from_file_location("dynamic_dispatch", Path(__file__).parents[2]
        / "tools/run_dynamic_memory_histories.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sources = [{"session_id": "original-0", "role": "user", "content": "Earlier report.",
                "event_key": "turn-1", "occurred_at": None},
               {"session_id": "original-1", "role": "assistant", "content": "A suggestion.",
                "event_key": "turn-2", "occurred_at": None},
               {"role": "user", "content": "A new event.", "event_key": "turn-3"}]
    step = {"id": "q", "session": "query-reopened", "incoming_sources": sources,
            "content": "What is established?", "occurred_at": None, "query_time": None,
            "expected": "OFFLINE_ONLY", "operations": [{"target": "OFFLINE_ONLY"}]}
    projected = module.host_input(step, bank="b")
    assert projected["incoming_sources"][:2] == sources[:2]
    assert projected["incoming_sources"][2]["session_id"] == "source-stream"
    assert "session_id" not in sources[2]
    assert projected["query_time"] is None and projected["occurred_at"] is None
    assert "OFFLINE_ONLY" not in json.dumps(projected)


@pytest.mark.parametrize("failure,unknown,continues", [
    ("VLLM_CHAT_TRUNCATED", 0, True),
    ("Finite decision input exceeds declared complete-input capacity", 0, True),
    ("Finite decision input exceeds declared complete-input capacity", 1, False),
    ("Unexpected execution failure", 0, False),
])
def test_continuation_preserves_failed_prefix_and_runs_only_new_messages(
    tmp_path, monkeypatch, failure, unknown, continues,
):
    spec = importlib.util.spec_from_file_location("dynamic_dispatch", Path(__file__).parents[2]
        / "tools/run_dynamic_memory_histories.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    steps = [{"id": f"q{i}", "kind": "task", "session": "offline-family", "content": f"Q{i}",
              "incoming_sources": [], "query_time": "2031-04-01", "occurred_at": "2031-04-01",
              "expected": "OFFLINE_ONLY"} for i in (1, 2, 3)]
    fixture = {"histories": [{"id": "family", "task_count": 3, "steps": steps}]}
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture))
    (old / "fixture.json").write_text(json.dumps(fixture))
    prior = {"status": "FAILED", "histories": ["family"], "policies": ["fixed"],
             "completed": [{"policy": "fixed", "history": "family", "step": "q1",
                            "status": "FAILED", "error": "VLLM_CHAT_TRUNCATED"}]}
    (old / "driver.json").write_text(json.dumps(prior))
    budget = tmp_path / "budget.json"
    budget.write_text("{}")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"entrypoints": {"functional": {"budget_path": str(budget)}}}))
    called = []

    def message(root, **kwargs):
        assert root == old / "fixed"
        assert "OFFLINE_ONLY" not in str(kwargs) and "offline-family" not in str(kwargs)
        called.append(kwargs["message_id"])
        usage = {k: {"unknown_usage": 0} for k in ("generation", "embedding")}
        return {"status": "FAILED" if kwargs["message_id"] == "q2" else "COMPLETED",
                "error": failure if kwargs["message_id"] == "q2" else None,
                "budget_before": usage,
                "budget_after": {k: {"unknown_usage": unknown} for k in usage}}

    monkeypatch.setattr(functional, "message", message)
    monkeypatch.setattr(sys, "argv", ["dispatch", str(config), str(fixture_path), str(new),
        "--source-version", "same-runtime", "--policies", "fixed", "--continue-from", str(old)])
    if continues:
        module.main()
    else:
        with pytest.raises(RuntimeError, match="First Host failure retained"):
            module.main()
    assert called == (["q2", "q3"] if continues else ["q2"])
    assert json.loads((old / "driver.json").read_text()) == prior
    result = json.loads((new / "driver.json").read_text())
    assert result["status"] == ("COMPLETED_WITH_FAILURES" if continues else "FAILED")
    assert result["inherited_positions"] == 1
    assert result["completed"][0] == prior["completed"][0]
