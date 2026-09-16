from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from milai_openworker_mcp.broker import BrokerError, Policy


def _policy(tmp_path: Path) -> Policy:
    executable = tmp_path / "milai-mcp"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o500)
    raw = {
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "profile": "reader-lite",
        "socket_path": str(tmp_path / "reader-lite.sock"),
        "socket_mode": "0600",
        "allowed_peer_uids": [os.geteuid()],
        "mcp_executable": str(executable),
        "mcp_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "base_url": "http://127.0.0.1:18080",
        "scope": {"project_ids": ["synthetic-wide"]},
        "required_authority": "ACTION_SAFE",
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_limit": 50,
        "max_connections": 4,
        "child_shutdown_seconds": 5,
        "mcp_max_retries": 0,
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    path.chmod(0o600)
    return Policy.load(path)


def test_broker_passes_host_owned_wide_profile_only_as_child_startup_argument(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path)

    assert policy.child_argv("OPENWORKER_USABILITY_WIDE_V01") == [
        str(policy.mcp_executable),
        "--profile",
        "reader-lite",
        "--max-retries",
        "0",
        "--resolve-budget-profile",
        "OPENWORKER_USABILITY_WIDE_V01",
    ]
    assert "MILAI_AGENT_RESOLVE_BUDGET" not in policy.child_environment("x" * 32)


def test_broker_accepts_host_owned_wide_v02_profile(tmp_path: Path) -> None:
    policy = _policy(tmp_path)

    assert policy.child_argv("OPENWORKER_USABILITY_WIDE_V02")[-2:] == [
        "--resolve-budget-profile",
        "OPENWORKER_USABILITY_WIDE_V02",
    ]


def test_broker_accepts_neutral_mcp_budget_profile_names(tmp_path: Path) -> None:
    policy = _policy(tmp_path)

    for profile in (
        "MCP_INTERACTIVE_STANDARD_V01",
        "MCP_INTERACTIVE_WIDE_V01",
        "MCP_RESEARCH_V01",
    ):
        assert policy.child_argv(profile)[-2:] == ["--resolve-budget-profile", profile]


def test_broker_rejects_unknown_resolve_budget_profile(tmp_path: Path) -> None:
    with pytest.raises(BrokerError, match="RESOLVE_BUDGET_PROFILE_REJECTED"):
        _policy(tmp_path).child_argv("WIDE_BY_MODEL")
