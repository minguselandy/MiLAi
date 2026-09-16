from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


def module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "tools/summarize_v02_memory_flow.py"
    spec = importlib.util.spec_from_file_location("v02_summary", path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_unreported_usage_is_unknown_and_reasoning_excluded(tmp_path: Path) -> None:
    (tmp_path / "allocation.json").write_text('{}')
    assert module().session_facts(tmp_path)["terminal_receipt"] is False
    result = {"returncode": 1, "stop_reason": "SESSION_TIMEOUT", "elapsed_seconds": 240,
              "usage": None, "before_version": 1, "after_version": 1}
    (tmp_path / "result.json").write_text(json.dumps(result))
    for name in ("before", "after"):
        (tmp_path / f"{name}.json").write_text('{"payload":{"note":"preserved"}}')
    (tmp_path / "events.jsonl").write_text(
        '{"type":"item.completed","item":{"type":"reasoning","text":"private"}}\n'
    )
    facts = module().session_facts(tmp_path)
    assert facts["total_input_output_tokens"] is None
    assert facts["external_messages"] == []
    assert facts["payload_changed"] is False
