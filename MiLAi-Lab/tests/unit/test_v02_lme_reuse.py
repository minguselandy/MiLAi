from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
reuse = importlib.import_module("run_v02_lme_reuse")


def test_branch_remapping_preserves_unrelated_content_and_original_snapshot() -> None:
    original = {"summary": "source old-id", "refs": ["lme://old/session/1/turn/2"],
                "other": {"note": "unchanged"}}
    result = reuse.remap(original, {"old-id": "new-id", "lme://old/": "lme://new/"})
    assert result["summary"] == "source new-id"
    assert result["refs"] == ["lme://new/session/1/turn/2"]
    assert original["summary"] == "source old-id"
    assert result["other"] == original["other"]


def test_l4_budget_keeps_generator_failures_and_bounds_remaining_online(tmp_path: Path) -> None:
    root = tmp_path / "run"
    config = {"model_phase_limits": {"total": 40}, "batch_wall_seconds": 1200,
              "session_timeout_seconds": 300}
    for index in range(2):
        p = root / "sessions" / str(index)
        p.mkdir(parents=True)
        (p / "allocation.json").write_text(json.dumps({"phase": "L4", "kind": "UPDATE",
                                                       "batch_id": "g"}))
        (p / "result.json").write_text(json.dumps({"returncode": 1, "elapsed_seconds": 560}))
    with pytest.raises(RuntimeError, match="generator budget"):
        reuse.reserve(root, "third", "other", "UPDATE", config)
    _, remaining = reuse.reserve(root, "followup", "g", "FOLLOWUP", config)
    assert remaining == 80


def test_generator_plan_does_not_include_future_questions_in_current_task() -> None:
    plan = json.loads(reuse.PLAN.read_text())
    for cluster in plan["clusters"]:
        questions = [f["question"] for f in cluster["followups"]]
        assert len(set(questions)) == 2
        assert all(q not in cluster["current_task"] for q in questions)
        assert len(set(map(tuple, cluster["order"]))) == 4
