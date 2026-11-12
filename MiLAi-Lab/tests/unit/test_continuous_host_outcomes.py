"""Continuous comparisons retain future evidence, failures and shared participants."""
import copy

import pytest

from summarize_continuous_host_outcomes import group_values, summarize


def inputs():
    fixture = {"histories": [{"id": "h", "source_group": "g", "sources": [],
        "requests": [{"id": "now", "incoming_sources": [{"content": "original"}]},
                     {"id": "later", "incoming_sources": []}]}]}
    controls = [{"history": "h", "request_id": request, "source_group": "g",
        "all_native_references_arrived": request == "now", "native_answer": "Tuesday",
        "native_evidence_ids": ["D1"], "missing_native_evidence_ids": [],
        "not_yet_arrived_native_evidence_ids": [] if request == "now" else ["D1"]}
        for request in ("now", "later")]
    driver = {"status": "FAILED", "continue_host_history": True,
        "completed": [{"history": "h", "request": "now", "policy": "laya",
            "status": "COMPLETED", "answer": "Tuesday"}]}
    return fixture, controls, driver


def test_failed_partial_run_keeps_full_panel_and_unknown_support():
    fixture, controls, driver = inputs()
    result = summarize(fixture, controls, {"s1": (driver, "laya"),
                       "new": (driver, "laya")}, [], ("new", "s1"))
    assert result["methods"]["new"]["status_counts"] == {"COMPLETED": 1, "NOT_EXECUTED": 1}
    assert result["methods"]["new"]["group_macro"]["execution_complete"] == .5
    assert result["methods"]["new"]["group_macro"]["observed_supported"] == 0
    assert result["primary"]["unknown_identification_interval"] == [-.5, .5]
    assert result["positions"][0]["reference_overlap_f1"] == 1
    assert result["positions"][1]["reference_overlap_f1"] is None


def test_review_binds_method_and_exact_first_answer_and_preserves_failed_answer():
    fixture, controls, driver = inputs()
    failed = copy.deepcopy(driver)
    failed["completed"][0]["status"] = "FAILED"
    review = {"method": "s1", "history": "h", "request": "now",
              "answer": "Tuesday", "outcome": "supported"}
    runs = {"s1": (driver, "laya"), "new": (failed, "laya")}
    result = summarize(fixture, controls, runs, [review], ("new", "s1"))
    assert result["methods"]["new"]["group_macro"]["reference_overlap_f1"] == 0
    assert result["primary"]["unknown_identification_interval"] == [-.5, -.5]
    with pytest.raises(ValueError, match="actual completed answer"):
        summarize(fixture, controls, runs, [{**review, "method": "new"}], ("new", "s1"))
    with pytest.raises(ValueError, match="actual completed answer"):
        summarize(fixture, controls, runs, [{**review, "answer": "Friday"}], ("new", "s1"))


def test_grouping_does_not_count_shared_histories_or_longer_histories_as_independent():
    rows = [{"source_group": "shared", "history": "short", "value": 1}]
    rows += [{"source_group": "shared", "history": "long", "value": 0}] * 9
    rows += [{"source_group": "other", "history": "third", "value": 1}]
    assert group_values(rows, "value") == {"shared": .5, "other": 1}
