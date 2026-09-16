from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
timing = importlib.import_module("summarize_v02_request_timing")


def records():
    return (
        {
            "phase": "c8-r0",
            "runtime_request_id_fingerprint": "a",
            "status": "COMPLETED",
            "elapsed_ms": 20,
        },
        {
            "request_id_fingerprint": "a",
            "safe_metadata": {
                "status_code": 200,
                "application_ms": 10,
                "counts": {"db_pool_acquire_ms": 1, "db_connection_hold_ms": 1},
                "durations_ms": {"db_pool_acquire_ms": 1, "db_connection_hold_ms": 8},
            },
        },
        {"runtime_request_id_fingerprint": "a", "handler_ms": 16, "runtime_client_ms": 15},
    )


def test_disjoint_values_are_computed_on_correlated_requests():
    event, runtime, mcp = records()
    row = timing.correlate([event], [runtime], [mcp])[0]
    assert row["status"] == "MATCHED"
    assert row["residuals"] == {
        "outside_handler_ms": 4,
        "handler_outside_runtime_ms": 1,
        "runtime_call_outside_application_ms": 5,
        "application_outside_connection_ms": 1,
    }


@pytest.mark.parametrize("mode", ["missing", "collision", "nested", "error", "negative"])
def test_missing_ambiguous_or_nonpartitionable_data_cannot_become_zero_or_pass(mode):
    event, runtime, mcp = records()
    runtimes = [runtime]
    if mode == "missing":
        mcp["runtime_request_id_fingerprint"] = "different"
    elif mode == "collision":
        runtimes.append(copy.deepcopy(runtime))
    elif mode == "nested":
        runtime["safe_metadata"]["counts"]["db_connection_hold_ms"] = 2
    elif mode == "error":
        runtime["safe_metadata"]["status_code"] = 500
    else:
        event["elapsed_ms"] = 1
    row = timing.correlate([event], runtimes, [mcp])[0]
    assert row["status"] != "MATCHED"


@pytest.mark.parametrize("mode", ["complete", "partial", "nested", "negative"])
def test_optional_transaction_partition_requires_both_single_edges(mode):
    event, runtime, mcp = records()
    raw = runtime["safe_metadata"]
    raw["counts"]["db_transaction_enter_ms"] = 2 if mode == "nested" else 1
    raw["durations_ms"]["db_transaction_enter_ms"] = 1
    if mode != "partial":
        raw["counts"]["db_transaction_exit_ms"] = 1
        raw["durations_ms"]["db_transaction_exit_ms"] = 9 if mode == "negative" else 5
    row = timing.correlate([event], [runtime], [mcp])[0]
    if mode == "complete":
        assert row["status"] == "MATCHED"
        assert row["residuals"]["connection_outside_transaction_edges_ms"] == 2
        assert row["values"]["db_transaction_exit_ms"] == 5
    else:
        assert row["status"] != "MATCHED"


@pytest.mark.parametrize("mode", ["complete", "clock", "missing", "order", "duration"])
def test_absolute_edges_require_shared_clock_and_consistent_request_boundaries(mode):
    event, runtime, mcp = records()
    event.update(start_s=1.0, end_s=1.02)
    mcp.update(handler_start_monotonic_s=1.001, handler_end_monotonic_s=1.017)
    if mode == "missing":
        del mcp["handler_start_monotonic_s"]
    elif mode == "order":
        mcp["handler_start_monotonic_s"] = 0.5
    elif mode == "duration":
        mcp["handler_end_monotonic_s"] = 1.016
    row = timing.correlate([event], [runtime], [mcp], shared_clock=mode != "clock")[0]
    edges = row["handler_edges"]
    if mode == "complete":
        assert edges["status"] == "MATCHED"
        assert edges["before_handler_ms"] == pytest.approx(1)
        assert edges["after_handler_ms"] == pytest.approx(3)
    else:
        assert edges["status"] != "MATCHED" and "before_handler_ms" not in edges
