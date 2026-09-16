from __future__ import annotations

from milai.observability import OperationTimer


def test_operation_timer_records_payload_free_duration_and_count() -> None:
    timer = OperationTimer()

    assert timer.call("query_total_ms", lambda: "done") == "done"

    assert timer.counts == {"query_total_ms": 1}
    assert timer.duration("query_total_ms") >= 0


def test_operation_timer_snapshot_combines_stage_duration_and_usage_counts() -> None:
    timer = OperationTimer()
    timer.call("vector_projection_ms", lambda: None)
    timer.increment("embedding_logical_items", 3)
    timer.increment("embedding_inference_batches")

    assert timer.snapshot() == {
        "durations_ms": {"vector_projection_ms": timer.duration("vector_projection_ms")},
        "counts": {
            "embedding_inference_batches": 1,
            "embedding_logical_items": 3,
            "vector_projection_ms": 1,
        },
    }


def test_operation_timer_can_attach_one_measured_upstream_stage() -> None:
    timer = OperationTimer()

    timer.observe_duration("state_address_resolution_ms", 1.25)

    assert timer.sequence() == ("state_address_resolution_ms",)
    assert timer.snapshot() == {
        "durations_ms": {"state_address_resolution_ms": 1.25},
        "counts": {"state_address_resolution_ms": 1},
    }
