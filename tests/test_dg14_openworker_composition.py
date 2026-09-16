from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from evals.dg14.benchmark import ARMS

OPENWORKER_CONFIG_ENV = "DG14_OPENWORKER_SMOKE_CONFIG"


def _run_opt_in_smoke() -> dict[str, Any]:
    raw_path = os.environ.get(OPENWORKER_CONFIG_ENV)
    if not raw_path:
        pytest.skip(
            f"DG14 OpenWorker composition smoke requires {OPENWORKER_CONFIG_ENV}"
        )
    config_path = Path(raw_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    command = config.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) or not part for part in command)
    ):
        pytest.fail(
            "DG14 OpenWorker smoke config must provide a non-empty argv command"
        )
    configured_cwd = config.get("cwd")
    cwd = (
        Path(configured_cwd).resolve()
        if isinstance(configured_cwd, str)
        else config_path.parent
    )
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"DG14 OpenWorker command did not emit one JSON report: {exc}")
    assert isinstance(report, dict)
    return report


def test_openworker_is_fresh_one_resolve_one_provider_composition_not_an_arm() -> None:
    report = _run_opt_in_smoke()

    assert report["classification"] == "OPENED_DEV_SMOKE / CHARACTERIZATION"
    assert report["formal_holdout_consumed"] is False
    assert report["composition_path"] == [
        "OpenWorker",
        "MCP",
        "MiLA",
        "vLLM",
    ]
    assert report["openworker"]["retained_messages_before"] == 0
    assert report["openworker"]["history_messages_forwarded"] == 0
    assert report["openworker"]["memory_source"] == "MiLA Runtime persistence"
    assert report["openworker"]["transport"] == "relay/UDS/broker/milai-mcp"
    assert report["openworker"]["mcp_tool_calls_requested"] == 1
    assert report["openworker"]["mcp_tool_results_observed"] == 1
    assert report["calls"]["milai_memory_resolve"] == 1
    assert report["calls"]["persistence_check_resolve"] == 1
    assert report["calls"]["provider"] == 1
    assert report["calls"]["provider_fallback"] == 0
    assert report["algorithm_arm_registered"] is False
    assert report.get("method_id") not in ARMS

    restart = report["fresh_context_check"]
    assert restart["worker_session_before"] != restart["worker_session_after"]
    assert restart["retained_messages_after_clear"] == 0
    assert restart["resolve_after_clear"]["status"] == "OK"
    assert restart["same_persisted_source_ids"] is True
