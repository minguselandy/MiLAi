"""Small arithmetic/acceptance tests; never substitutes for actual Product/PG checks."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from check_v0214_live import latency_summary, peak_overlap, verify_cas


def test_empty_latency_is_unknown_not_zero():
    assert latency_summary([])["p95_seconds"] is None


def test_latency_uses_actual_overlap_span_and_nearest_rank():
    events = [{"start": 0, "end": 2}, {"start": 1, "end": 4}]
    summary = latency_summary(events)
    assert summary["throughput_per_second"] == 0.5
    assert summary["p50_seconds"] == 2 and summary["p99_seconds"] == 3
    assert peak_overlap(events) == 2


def test_cas_requires_one_stale_loser_and_matching_head():
    winner = {"version": 2, "payload": {"writer": 1}}
    loser = {"mcp_error": True, "content": "STALE_WORKING_STATE"}
    assert verify_cas([winner, loser], winner)["status"] == "PASS"
    with pytest.raises(AssertionError):
        verify_cas([winner, winner], winner)
    with pytest.raises(AssertionError):
        verify_cas([winner, loser], {"version": 2, "payload": {"writer": 0}})
