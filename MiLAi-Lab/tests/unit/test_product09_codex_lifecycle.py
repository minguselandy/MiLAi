from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

LAB = Path(__file__).resolve().parents[2]
RUNNER = LAB / "tools" / "run_product09_codex_lifecycle.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("product09_codex_lifecycle", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_codex_trace_keeps_only_completed_memory_calls() -> None:
    module = _module()
    lines = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": "milai_memory_resolve",
                "status": "completed",
                "arguments": {"query": "lease fix"},
                "result": {
                    "structured_content": {
                        "schema_version": "memory-evidence-context-v1",
                        "retrieval_status": "HIT",
                        "evidence": [{"text": "answer"}],
                    }
                },
            },
        },
    ]
    trace = module._codex_trace("\n".join(json.dumps(line) for line in lines))
    assert trace == [
        {
            "arguments": {"query": "lease fix"},
            "structured_content": {
                "schema_version": "memory-evidence-context-v1",
                "retrieval_status": "HIT",
                "evidence": [{"text": "answer"}],
            },
        }
    ]


def test_answer_normalization_only_removes_presentation_wrappers() -> None:
    module = _module()
    assert module._normalized_answer("`uv run pytest -q`\n") == "uv run pytest -q"
    assert module._normalized_answer("```text\nrolling-quartz\n```") == "rolling-quartz"
