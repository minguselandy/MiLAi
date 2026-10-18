import importlib.util
import json
import sys
from pathlib import Path

from milai_lab.runners import functional


def test_continuation_preserves_failed_prefix_and_runs_only_new_messages(tmp_path, monkeypatch):
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
                "error": "VLLM_CHAT_TRUNCATED" if kwargs["message_id"] == "q2" else None,
                "budget_before": usage, "budget_after": usage}

    monkeypatch.setattr(functional, "message", message)
    monkeypatch.setattr(sys, "argv", ["dispatch", str(config), str(fixture_path), str(new),
        "--source-version", "same-runtime", "--policies", "fixed", "--continue-from", str(old)])
    module.main()
    assert called == ["q2", "q3"]
    assert json.loads((old / "driver.json").read_text()) == prior
    result = json.loads((new / "driver.json").read_text())
    assert result["status"] == "COMPLETED_WITH_FAILURES"
    assert result["inherited_positions"] == 1
    assert result["completed"][0] == prior["completed"][0]
