from __future__ import annotations

from evals.agent_efficiency.benchmark import (
    _counter,
    _load_fixtures,
    _workload_result,
    dataset_fingerprint,
    turns,
)
from evals.agent_efficiency.postgres_scale import ROOT, _alembic_config


def test_fixed_workloads_have_exact_twenty_percent_memory_labels() -> None:
    fixtures, _ = _load_fixtures()
    for count in (20, 100, 500):
        workload = turns(fixtures, count)
        assert len(workload) == count
        assert sum(turn.requires_memory for turn in workload) == count // 5


def test_hundred_turn_regression_meets_route_quality_and_token_gate() -> None:
    fixtures, _ = _load_fixtures()
    result = _workload_result(fixtures, 100, _counter(fixtures))
    assert result["quality_route_accuracy"] == 1.0
    assert result["routes"] == {"NONE": 80, "CACHE": 0, "L0": 0, "L1": 20}
    assert result["optimized"]["total_milai_input_tokens"] == 10_280
    assert result["estimated_token_reduction"] > 0.85
    assert result["provider_usage_verified"] is False
    assert result["execution"]["optimized_logical_recall_operations"] == 20
    assert result["execution"]["network_or_service_round_trips_executed"] == 0
    assert result["execution"]["extra_model_round_trips"] is None
    assert result["execution"]["end_to_end_agent_wall_ms"] is None


def test_scale_dataset_generator_is_deterministic_without_retaining_corpus() -> None:
    assert dataset_fingerprint(1) == {
        "claims": 1,
        "bytes": 363,
        "sha256": "95bdc089c483c1f0e1e85ebbc6ddb80415dbb70cf5feaf6a408677377a2991d6",
    }
    assert dataset_fingerprint(1_000)["sha256"] == (
        "1b91041dcf41eaa9d356a0418112500e1346e42a2133dad51f52b746e09b3f73"
    )


def test_scale_migration_paths_are_absolute_and_cwd_independent() -> None:
    config = _alembic_config()
    assert config.get_main_option("script_location") == str(
        ROOT / "runtime" / "migrations"
    )
    assert config.get_main_option("prepend_sys_path") == str(ROOT / "runtime")
