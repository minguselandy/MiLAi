from __future__ import annotations

import json

from scripts.run_dg10_vllm_openworker_e2e import (
    OpenWorkerHarness,
    _parse_agent_events,
    _validated_ab_summary,
)


def test_candidate_2_ab_prerequisite_is_complete_and_at_tool_budget() -> None:
    assert _validated_ab_summary() == {
        "status": "LOCAL_AB_CAPTURE_COMPLETE_REVIEW_REQUIRED",
        "validated_local_inferences": 1000,
        "unique_native_ids": 1000,
        "reader_lite_tool_schema_tokens": 250,
        "completed_gates_pass": True,
    }


def test_config_diff_reports_paths_without_values() -> None:
    paths = OpenWorkerHarness._config_diff_paths(
        {"provider": {"secret": "before"}, "mcp": [1]},
        {"provider": {"secret": "after"}, "mcp": [1, 2]},
    )
    assert paths == ["$.mcp.length", "$.provider.secret"]
    assert "before" not in repr(paths)
    assert "after" not in repr(paths)


def test_agent_event_parser_keeps_only_normalized_execution_data() -> None:
    raw = "\n".join(
        [
            json.dumps(
                {
                    "type": "step_start",
                    "sessionID": "ses_synthetic_0001",
                    "part": {"id": "part-start", "type": "step-start"},
                }
            ),
            json.dumps(
                {
                    "type": "tool_use",
                    "sessionID": "ses_synthetic_0001",
                    "part": {
                        "id": "part-tool",
                        "type": "tool",
                        "tool": "milai_recall",
                        "state": {"status": "completed"},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "text",
                    "sessionID": "ses_synthetic_0001",
                    "part": {"type": "text", "text": "synthetic answer"},
                }
            ),
            json.dumps(
                {
                    "type": "step_finish",
                    "sessionID": "ses_synthetic_0001",
                    "part": {
                        "type": "step-finish",
                        "tokens": {
                            "input": 10,
                            "output": 3,
                            "reasoning": 0,
                            "cache": {"read": 2},
                        },
                    },
                }
            ),
        ]
    )
    parsed = _parse_agent_events(raw, 12.5, 2)
    assert parsed.tool_names == ("milai_recall",)
    assert parsed.tokens == {
        "input": 10,
        "output": 3,
        "reasoning": 0,
        "cache_read": 2,
    }
    public = parsed.public()
    assert "text" not in public
    assert len(public["output_sha256"]) == 64
