from __future__ import annotations

import importlib
import json
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
environment = importlib.import_module("v02_readable_container")
audit = importlib.import_module("audit_v02_task_cost")


@pytest.mark.parametrize("state", ["ABSENT", "ACTIVE 中文\n  note\n"])
def test_capability_notice_preserves_each_arms_bootstrap_and_mcp(state: str) -> None:
    original = ("developer_instructions = " + json.dumps(state)
                + '\n[mcp_servers.milai]\nurl="local"\n')
    result = tomllib.loads(environment.augment_profile(original))
    assert result["developer_instructions"] == state + "\n" + environment.CAPABILITIES
    assert result["mcp_servers"] == tomllib.loads(original)["mcp_servers"]


def test_paid_launch_guard_precedes_any_environment_or_process_access(monkeypatch) -> None:
    monkeypatch.setattr(environment, "load_environment", lambda: {
        "model_execution_authorized": False, "provider_cost_control_verified": False})
    monkeypatch.setattr(environment.os, "execvp", lambda *_: pytest.fail("Unexpected execution"))
    with pytest.raises(RuntimeError, match="C3_NOT_AUTHORIZED"):
        environment.main()


def test_smoke_and_future_runner_share_source_mount_and_tools(tmp_path: Path) -> None:
    args = environment.docker_command("sha256:example", tmp_path, tmp_path / "home",
                                     tmp_path / "bin/codex", tmp_path / "rg", "owned",
                                     network="none", entrypoint="python3")
    assert "--read-only" in args and "--cap-drop=ALL" in args
    assert f"type=bind,src={tmp_path / 'sources'},dst={tmp_path / 'sources'},readonly" in args
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--entrypoint") + 1] == "python3"


def test_audit_counts_completed_commands_only_and_keeps_failures() -> None:
    item = {"id": "1", "type": "command_execution", "command": "python3 x",
            "exit_code": 127, "aggregated_output": "python3: command not found\n"}
    result = audit.command_rows([{"type": "item.started", "item": item},
                                 {"type": "item.completed", "item": item},
                                 {"type": "turn.completed", "usage": {}}])
    assert len(result) == 1 and result[0]["missing_program"] == "python3"
