"""Settled malformed actions get bounded visible feedback, not repair or free calls."""

import json

import pytest
from test_v0218_host import (
    test_visible_schema_error_feedback_and_next_dispatch_sources as exercise_host,
)


@pytest.mark.parametrize("arm", ["N0", "N1", "N2"])
@pytest.mark.parametrize(
    "malformed",
    [
        '{"action":"save_note",',
        json.dumps({"action": "save_note", "arguments_json": '{"note":"unclosed'}),
        json.dumps({"action": "unknown", "arguments_json": "{}"}),
        json.dumps({"action": "read", "arguments_json": "[]"}),
    ],
)
def test_parse_rejection_preserves_world_budget_and_following_source_visibility(
    tmp_path, monkeypatch, arm, malformed
):
    exercise_host(tmp_path, monkeypatch, arm, True, malformed)
    result = json.loads((tmp_path / "episode/result.json").read_text())
    assert result["actions"][0]["action"] == {"action": "invalid_action"}
    assert result["actions"][0]["tool_result"]["reason"].startswith("INVALID_ACTION_ENCODING:")
    assert result["accounting"]["requests"] == 3
    assert result["agent_note_writes"] == 0
    assert result["actions"][-1]["action"]["action"] == "finish"
