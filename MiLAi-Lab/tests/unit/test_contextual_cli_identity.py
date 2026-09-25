"""Run identity and cumulative budget scope stay fixed across output directories."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from milai_lab.harness.contextual_artifacts import RunLimits

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
cli = importlib.import_module("run_contextual_user_memory")


def test_cumulative_budget_survives_new_run_directory_and_locks_scope(tmp_path: Path) -> None:
    path = tmp_path / "shared" / "budget.json"
    config = {
        "history_capacity": {}, "cumulative_budget_path": str(path),
        "cumulative_budget_scope": "goal-v4-exposed-only",
    }
    limits = RunLimits(generation_requests=3, generation_tokens=1000)
    first = cli.open_run_budget(config, tmp_path / "run-a", limits)
    first.reserve("chat/completions", {"messages": [], "max_tokens": 10})
    second = cli.open_run_budget(config, tmp_path / "run-b", limits)
    assert second.path == path
    assert second.state["generation_requests"] == 1
    assert second.state["generation"]["unknown_usage"] == 1
    with pytest.raises(ValueError, match="SCOPE_OR_LIMITS_CHANGED"):
        cli.open_run_budget(
            {**config, "cumulative_budget_scope": "another-goal"},
            tmp_path / "run-c", limits,
        )
    with pytest.raises(ValueError, match="SCOPE_OR_LIMITS_CHANGED"):
        cli.open_run_budget(config, tmp_path / "run-c", RunLimits(generation_requests=4))
    with pytest.raises(ValueError, match="OUTSIDE_RUN_DIRECTORY"):
        cli.open_run_budget(
            {**config, "cumulative_budget_path": str(tmp_path / "run-c" / "budget.json")},
            tmp_path / "run-c", limits,
        )


def test_manifest_identity_names_protocol_prompts_capacity_config_and_models(monkeypatch) -> None:
    class Capacity:
        def __init__(self, config):
            self.identity = {"tokenizer_files_sha256": config["tokenizer_files_sha256"]}

    monkeypatch.setattr(cli, "HostCapacity", Capacity)
    config = {
        "model_identity": {"artifacts": [{"sha256": "pinned"}]},
        "history_capacity": {"tokenizer_files_sha256": {"tokenizer.json": "fixed"}},
        "host": {"model": "host-model"}, "embedding": {"model": "embedding-model"},
        "judge": {"model": "judge-model"},
    }
    identity = cli.execution_identity(config)
    assert identity["method_version"] == cli.METHOD_VERSION
    assert identity["ingestion_protocol"] == cli.PROTOCOL_VERSION
    assert identity["operation_contract"] == cli.OPERATION_CONTRACT_VERSION
    assert identity["write_contract"] == cli.WRITE_CONTRACT_VERSION
    assert identity["material_view_protocol"] == cli.VIEW_PROTOCOL
    assert identity["models"] == {
        "host": "host-model", "embedding": "embedding-model", "judge": "judge-model",
    }
    assert identity["host_capacity"]["tokenizer_files_sha256"] == {"tokenizer.json": "fixed"}
    assert identity["config_sha256"] == cli.digest(config)
    assert set(identity["prompt_sha256"]) == {"common", "context", "ingestion"}
