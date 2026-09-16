from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "tools/run_mcp_tool_selection.py"
    spec = importlib.util.spec_from_file_location("run_mcp_tool_selection", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summary_recognizes_top_level_completed_mcp_call() -> None:
    module = _module()
    events = [
        {
            "type": "item.started",
            "item": {
                "type": "mcp_tool_call",
                "server": "milai",
                "tool": "milai_working_state_get",
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "milai",
                "tool": "milai_working_state_get",
                "arguments": {"scope": "TASK"},
                "status": "completed",
                "error": None,
            },
        },
    ]

    summary = module._summary(events, "milai_working_state_get")

    assert summary["expected_tool_selected"] is True
    assert summary["expected_tool_succeeded"] is True
    assert summary["mcp_call_count"] == 1
    assert summary["first_action"]["type"] == "mcp_tool_call"


def test_skill_diagnostics_excludes_repository_text_echoed_by_command() -> None:
    module = _module()
    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "aggregated_output": "an old document contains <skills_instructions>",
            },
        }
    ]

    diagnostics = module._skill_diagnostics(events, "")

    assert diagnostics["skill_instruction_block"] is False
    assert diagnostics["skill_literal_command_output_echo_count"] == 1
    assert diagnostics["skill_literal_non_command_event_count"] == 0


def test_skill_diagnostics_rejects_non_command_skill_block() -> None:
    module = _module()
    events = [
        {
            "type": "model_input",
            "text": "<skills_instructions>loaded instructions</skills_instructions>",
        }
    ]

    diagnostics = module._skill_diagnostics(events, "")

    assert diagnostics["skill_instruction_block"] is True
    assert diagnostics["skill_literal_non_command_event_count"] == 1
