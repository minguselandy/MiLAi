"""Finite action budget, evidence projection and explicit stopping semantics."""

import pytest

from milai_lab.methods.bounded_evidence import decision_payload, select_bounded


def item(index):
    return {"id": f"p{index}", "title": "source", "text": f"Fact {index}",
            "is_supporting": True, "answer": "offline-only"}


def test_open_then_stop_uses_only_actually_read_evidence():
    calls = []

    def decide(payload):
        calls.append(payload)
        return "open_p1" if len(calls) == 1 else "stop_sufficient"

    result = select_bounded("question", [item(0), item(1)], decide)
    assert result["selected_ids"] == ["p1"]
    assert result["stop_reason"] == "stop_sufficient"
    assert calls[0]["state"]["read_evidence"] == []
    assert calls[1]["state"]["read_evidence"] == [
        {"id": "p1", "title": "source", "text": "Fact 1"}]
    assert list(calls[1]["questions"]["next"]["criteria"]) == [
        "open_p0", "stop_sufficient", "stop_exhausted"]


def test_insufficient_stop_is_distinct_from_budget_and_pool_consumption():
    result = select_bounded("q", [item(0)], lambda _: "stop_exhausted")
    assert result["stop_reason"] == "stop_exhausted"
    assert result["selected_ids"] == []
    result = select_bounded("q", [item(0)], lambda _: "open_p0")
    assert result["stop_reason"] == "pool_consumed"
    assert result["decision_calls"] == 1


def test_controller_calls_and_offered_candidates_are_bounded():
    calls = []

    def decide(payload):
        calls.append(payload)
        return next(iter(payload["questions"]["next"]["criteria"]))

    result = select_bounded("q", [item(i) for i in range(100)], decide,
                            max_candidates=8, max_reads=4)
    assert result["selected_ids"] == ["p0", "p1", "p2", "p3"]
    assert result["decision_calls"] == 4
    assert result["stop_reason"] == "read_budget"
    assert [len(c["state"]["candidates"]) for c in calls] == [8, 7, 6, 5]
    assert all(len(c["questions"]["next"]["criteria"]) <= 10 for c in calls)


def test_unoffered_decision_fails_without_retries_or_empty_success():
    with pytest.raises(ValueError, match="outside"):
        select_bounded("q", [item(0)], lambda _: "open_p99")


def test_runtime_projection_drops_training_metadata():
    payload = decision_payload("q", [item(0)], [item(1)])
    assert set(payload) == {"state", "questions"}
    assert all(set(p) == {"id", "title", "text"}
               for p in payload["state"]["read_evidence"] + payload["state"]["candidates"])
