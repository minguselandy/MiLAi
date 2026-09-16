from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

INTEGRATION_CONFIG_ENV = "DG14_INTEGRATION_CONFIG"


def _run_opt_in_contract() -> dict[str, Any]:
    raw_path = os.environ.get(INTEGRATION_CONFIG_ENV)
    if not raw_path:
        pytest.skip(
            f"real DG14 Postgres/Runtime/Worker/stdio MCP test requires {INTEGRATION_CONFIG_ENV}"
        )
    config_path = Path(raw_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    command = config.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) or not part for part in command)
    ):
        pytest.fail("DG14 integration config must provide a non-empty argv command")
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
        timeout=900,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"DG14 integration command did not emit one JSON report: {exc}")
    assert isinstance(report, dict)
    return report


def test_real_postgres_runtime_worker_stdio_mcp_governance_scope_and_restart() -> None:
    report = _run_opt_in_contract()

    assert report["classification"] == "OPENED_DEV_SMOKE / CHARACTERIZATION"
    assert report["formal_holdout_consumed"] is False
    assert report["transport"] == "stdio-mcp"
    assert report["storage_backend"] == "postgresql"
    assert report["runtime_process"]["kind"] == "milai-runtime"
    assert report["worker_process"]["kind"] == "milai-worker"
    assert report["mcp_process"]["profiles"] == [
        "submitter",
        "reviewer",
        "reader-detail",
        "operator",
    ]
    assert report["mcp_process"]["max_retries"] == 0

    governance = report["governance"]
    assert governance["capture_receipt"]["evidence_id"]
    assert governance["canonical_claims_after_capture"] == 0
    assert governance["proposal_receipt"]["proposal_id"]
    assert governance["canonical_claims_before_review"] == 0
    assert governance["review_receipt"]["claim_version_id"]
    assert governance["reviewer_actor"] != governance["submitter_actor"]
    assert governance["projection_ready_after_review"] is True

    correctness = report["correctness"]
    for metric in (
        "wrong_scope_acceptance",
        "cross_case_contamination",
        "stale_revoked_evidence_acceptance",
        "silent_fallback",
    ):
        assert correctness[metric]["accepted"] == 0
        assert correctness[metric]["denominator"] > 0

    restart = report["restart_persistence"]
    assert restart["mcp_pid_before"] != restart["mcp_pid_after"]
    assert restart["runtime_persistence_reused"] is True
    assert restart["resolve_after_restart"]["status"] == "OK"
    assert restart["resolve_after_restart"]["source_ids"]

    cleanup = report["cleanup"]
    assert cleanup["namespace_exact"] is True
    assert cleanup["evidence_revoked"] > 0
    assert cleanup["other_namespaces_changed"] == 0
