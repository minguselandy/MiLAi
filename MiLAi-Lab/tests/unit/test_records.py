from __future__ import annotations

import pytest

from milai_lab.contracts.records import HistoryItem, WorkloadHistory


def test_workload_fingerprint_is_order_sensitive_and_deterministic() -> None:
    first = HistoryItem("a", "session-1", "user", "hello")
    second = HistoryItem("b", "session-1", "assistant", "hi")
    workload = WorkloadHistory("workload", "dataset", (first, second))

    assert workload.fingerprint == workload.fingerprint
    assert workload.fingerprint != WorkloadHistory(
        "workload", "dataset", (second, first)
    ).fingerprint


def test_workload_rejects_duplicate_item_identity() -> None:
    item = HistoryItem("same", "session", "user", "content")
    with pytest.raises(ValueError, match="unique"):
        WorkloadHistory("workload", "dataset", (item, item))

