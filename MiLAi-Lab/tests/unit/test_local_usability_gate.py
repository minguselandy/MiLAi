from milai_lab.local_usability_gate import (
    LocalUsabilityMetrics,
    percentile,
    typed_terminal,
)


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([4, 1, 3, 2], 0.95) == 4
    assert percentile([4, 1, 3, 2], 0.5) == 2


def test_exit_gate_requires_exact_workload_cardinality() -> None:
    metrics = LocalUsabilityMetrics(
        golden_flow=True,
        scenario_count=24,
        scenario_success_count=22,
        warm_request_count=100,
        typed_terminal_count=100,
        read_after_write_p95_ms=4_999,
        retrieval_context_p95_ms=1_999,
        warm_control_p95_ms=499,
        model_outage_fallback_rate=1.0,
        governance_leak_count=0,
        canonical_read_mutation_count=0,
        baseline_restore=True,
    )
    assert all(metrics.exit_checks().values())
    assert metrics.task_success_rate == 22 / 24


def test_typed_terminal_accepts_both_public_response_families() -> None:
    assert typed_terminal({"status": "HIT"})
    assert typed_terminal({"abstained": True})
    assert not typed_terminal({"items": []})
