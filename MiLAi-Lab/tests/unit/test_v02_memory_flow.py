from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "v02_memory_flow", TOOLS / "run_v02_memory_flow.py"
    )
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(loaded)
    finally:
        sys.path.remove(str(TOOLS))
    return loaded


def test_uv_remaps_by_source_identity_without_mutating_parent() -> None:
    runner = module()
    parent = {"note": "source old-a; retain timeout and privacy", "evidence_refs": ["old-b"]}
    old = [{"filename": "a", "receipt": {"evidence_id": "old-a"}},
           {"filename": "b", "receipt": {"evidence_id": "old-b"}}]
    new = [{"filename": "b", "receipt": {"evidence_id": "new-b"}},
           {"filename": "a", "receipt": {"evidence_id": "new-a"}}]
    mapped, mapping = runner.remap_snapshot(parent, old, new)
    assert mapped == {"note": "source new-a; retain timeout and privacy",
                      "evidence_refs": ["new-b"]}
    assert parent["evidence_refs"] == ["old-b"]
    assert mapping == {"old-a": "new-a", "old-b": "new-b"}
    with pytest.raises(ValueError, match="identical source"):
        runner.remap_snapshot(parent, old, new[:1])


def test_timeout_is_not_claimed_as_no_save_and_head_is_checked() -> None:
    runner = module()
    started = [{"type": "item.started", "item": {
        "tool": "milai_working_state_update", "status": "in_progress"}}]
    assert runner.save_status(started, {"version": 1}, {"version": 1}) == "OUTCOME_UNKNOWN"
    assert runner.save_status(started, {"version": 1}, {"version": 2}) == "COMMITTED_OBSERVED_HEAD"
    assert runner.save_status([], {"version": 1}, {"version": 1}) == "NOT_ATTEMPTED"


def test_conflict_and_tool_failure_stay_distinct() -> None:
    runner = module()
    item = {"tool": "milai_working_state_update", "status": "failed", "error": "VERSION_CONFLICT"}
    assert runner.save_status([{"item": item}], {"version": 1}, {"version": 1}) == "CONFLICT"
    item["error"] = "unavailable"
    assert runner.save_status([{"item": item}], {"version": 1}, {"version": 1}) == "FAILED"


def test_plain_mcp_error_is_preserved_without_json_parsing() -> None:
    result = {"isError": True, "structuredContent": None,
              "content": [{"type": "text", "text": "STALE_WORKING_STATE: update rejected"}]}
    assert module().structured(result) == {"mcp_error": True, "content": result["content"]}


def test_host_config_preserves_model_and_executable_rollout_settings() -> None:
    runner = module()
    config = runner.read_json(runner.CONFIG)
    parsed = tomllib.loads(runner.codex_config(config))
    assert parsed["model"] == config["model"]
    assert parsed["model_reasoning_effort"] == config["reasoning_effort"]
    assert parsed["features"]["rollout_budget"]["reminder_at_remaining_tokens"] == [60000, 10000]
    assert parsed["features"]["multi_agent"] is False
    opportunity = config["host_opportunity"]
    hosted = tomllib.loads(runner.codex_config(config, opportunity))
    assert hosted.pop("developer_instructions") == opportunity
    assert hosted == parsed


def test_tool_watchdog_counts_file_changes_and_deduplicates_lifecycle_events() -> None:
    item = {"id": "patch-1", "type": "file_change"}
    assert module().tool_action_count([
        {"type": "item.started", "item": item},
        {"type": "item.completed", "item": item},
        {"type": "item.completed", "item": {"id": "shell-2", "type": "command_execution"}},
    ]) == 2


def test_partial_jsonl_keeps_prior_external_events(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"type":"turn.started"}\n{"type":')
    assert module().parse_events(path) == [{"type": "turn.started"}]
