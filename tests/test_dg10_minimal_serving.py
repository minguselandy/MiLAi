from __future__ import annotations

from evals.serving import minimal_baseline
from scripts import run_dg10_minimal_serving


def _record(tier: str, repetition: int, latency: float) -> dict[str, object]:
    return {
        "tier": tier,
        "repetition": repetition,
        "lifecycle": "cold" if repetition == 0 else "warm",
        "status": "PASS",
        "e2e_ms": latency,
        "memory_control_ms": latency / 2 if tier == "T3a" else None,
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "model_calls": 1,
        "mcp_calls": 1 if tier == "T3a" else 0,
        "memory_source": "HOST_MCP_COMPOSITE" if tier == "T3a" else "NO_MEMORY",
    }


def test_schedule_is_balanced_latin_rotation() -> None:
    orders = [minimal_baseline.schedule(index) for index in range(4)]

    assert [order[0] for order in orders] == list(minimal_baseline.TIERS)
    assert all(set(order) == set(minimal_baseline.TIERS) for order in orders)


def test_aggregate_separates_one_cold_and_thirty_warm_samples() -> None:
    records = [
        _record(tier, repetition, float(repetition + 1))
        for repetition in range(minimal_baseline.REPETITIONS)
        for tier in minimal_baseline.TIERS
    ]

    aggregates = minimal_baseline.aggregate(records)

    assert aggregates["T0"]["cold_request_count"] == 1
    assert aggregates["T0"]["warm_request_count"] == 30
    assert aggregates["T0"]["warm_e2e_ms"]["p95"] == 30.0
    assert aggregates["T0"]["warm_e2e_ms"]["p99"] is None
    assert aggregates["T3a"]["warm_memory_control_ms"]["count"] == 30


def _report(t3_mean: float, t3_p95: float, memory_p95: float) -> dict[str, object]:
    return {
        "aggregates": {
            tier: {
                "request_count": minimal_baseline.REPETITIONS,
                "failure_count": 0,
                "warm_e2e_ms": {
                    "mean": t3_mean if tier == "T3a" else 100.0,
                    "p95": t3_p95 if tier == "T3a" else 110.0,
                },
                "warm_memory_control_ms": {
                    "p95": memory_p95 if tier == "T3a" else None
                },
            }
            for tier in minimal_baseline.TIERS
        }
    }


def test_serving_comparison_keeps_target_meeting_host_prefetch() -> None:
    comparison = run_dg10_minimal_serving._comparison(
        "serving-baseline-001",
        _report(650.0, 1_000.0, 322.0),
        _report(500.0, 700.0, 120.0),
    )

    assert comparison["decision"] == "KEEP_EFFICIENCY"
    assert comparison["terminal_failures"] == 0
    assert comparison["memory_control_p95_delta_ms"] == -202.0


def test_t3a_success_requires_invisible_host_mcp_composite_context() -> None:
    record = minimal_baseline._provider_record(
        tier="T3a",
        repetition=1,
        order=minimal_baseline.TIERS,
        elapsed_ms=100.0,
        native_request_id="native-1",
        prompt_tokens=100,
        completion_tokens=10,
        finish_reason="stop",
        answer={"answer": "3.11", "status": "KNOWN", "memory_used": True},
        expected={"answer": "3.11", "status": "KNOWN", "memory_used": True},
        memory_control_ms=20.0,
        adapter_total_ms=90.0,
        tool_names=(),
        provider_calls=1,
        memory_source="HOST_MCP_COMPOSITE",
        mcp_calls=1,
    )

    assert record["status"] == "PASS"
    assert record["failed_assertions"] == []
    assert record["tool_names"] == []


def test_reclassification_explains_and_repairs_stale_prefetch_label() -> None:
    record = minimal_baseline._provider_record(
        tier="T3a",
        repetition=1,
        order=minimal_baseline.TIERS,
        elapsed_ms=100.0,
        native_request_id="native-1",
        prompt_tokens=100,
        completion_tokens=10,
        finish_reason="stop",
        answer={"answer": "3.11", "status": "KNOWN", "memory_used": True},
        expected={"answer": "3.11", "status": "KNOWN", "memory_used": True},
        memory_control_ms=20.0,
        adapter_total_ms=90.0,
        tool_names=(),
        provider_calls=1,
        memory_source="HOST_MCP_PREFETCH",
        mcp_calls=1,
    )

    assert record["status"] == "FAILED"
    assert record["failed_assertions"] == ["memory_source"]

    reclassified = minimal_baseline.reclassify_record(
        {**record, "memory_source": "HOST_MCP_COMPOSITE"}
    )

    assert reclassified["status"] == "PASS"
    assert reclassified["failed_assertions"] == []
