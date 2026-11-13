"""Unknown judgments and failed first responses must not become supported successes."""
import pytest

from summarize_trajectory_outcomes import endpoint_status, native_panel, summarize


def review(path, answer="complete"):
    return {"readout": path, "event_id": "review/f/q", "family": "f",
            "actual_action": {"id": "handoff", "kind": "HANDOFF"},
            "answer_status": answer, "material_status": "sufficient", "answer_support": "supported"}


def test_failed_transport_and_unsupported_completion_are_not_success():
    assert endpoint_status("FAILED", review("a")) == "execution_failed"
    assert endpoint_status("COMPLETED", None) == "unknown"
    assert endpoint_status("COMPLETED", {**review("a"), "answer_support": "qualified"}) == "unknown"
    assert endpoint_status("COMPLETED", review("a")) == "complete_supported"


def test_same_action_ids_keep_distinct_readouts_and_unknown_difference_bounds():
    bindings = {path: {"method": path, "family": "f", "native_question_id": "q",
        "original_event_id": f"f/q/step-{i}", "actual_action": review(path)["actual_action"],
        "review_group": "review/f/q"} for i, path in enumerate(["a", "b"])}
    cases = [{"branches": [{"readout": p, "readout_status": "COMPLETED"} for p in bindings]}]
    result = summarize(cases, bindings, [review("a")], ("a", "b"))
    assert result["methods"]["a"]["status_counts"] == {"complete_supported": 1}
    assert result["methods"]["b"]["status_counts"] == {"unknown": 1}
    assert result["primary"]["observed_complete_difference"] == 1
    assert result["primary"]["unknown_identification_interval"] == [0, 1]
    with pytest.raises(ValueError, match="provenance"):
        summarize(cases, bindings, [{**review("a"), "event_id": "other"}], ("a", "b"))


def test_collection_failure_is_uncompleted_pipeline_not_a_fake_reader_or_semantic_label():
    binding = {"method": "b", "family": "f", "native_question_id": "q",
        "original_event_id": "f/q/step-2", "actual_action": review("b")["actual_action"],
        "review_group": "review/f/q"}
    cases = [{"branches": [{"readout": "b", "readout_status": "COMPLETED"}]}]
    failure = {"method": "a", "family": "f", "native_question_id": "q",
               "status": "collection_failed", "readout": None, "actual_terminal_action": None}
    result = summarize(cases, {"b": binding}, [review("b")], ("b", "a"),
                       collection_failures=[failure],
                       expected_tasks=[{"family": "f", "native_question_id": "q"}])
    failed = result["methods"]["a"]
    assert failed["questions"] == 1 and failed["status_counts"] == {"collection_failed": 1}
    assert failed["endpoints"][0]["transport_status"] == "NOT_INVOKED"
    assert failed["endpoints"][0]["actual_action"] is None
    assert result["primary"]["unknown_identification_interval"] == [1, 1]
    with pytest.raises(ValueError, match="repeated collection"):
        summarize(cases, {"b": binding}, [review("b")], ("b", "a"),
                  collection_failures=[failure, failure])


def test_native_panel_retains_declared_missing_source_without_dropping_denominator():
    expected = [{"family": f, "native_question_id": f} for f in ["f", "g"]]
    metrics = {"a": {"states": 1, "sources": 1, "source_means": {"f": 1.0},
                     "status_counts": {"COMPLETED": 1}},
               "b": {"states": 2, "sources": 2, "source_means": {"f": 1.0, "g": 1.0},
                     "status_counts": {"COMPLETED": 2}}}
    failures = [{"method": "a", "family": "g", "status": "collection_failed"}]
    result = native_panel(expected, metrics, failures, ("b", "a"), 0)
    assert result["methods"]["a"]["source_macro_answer_f1_missing_zero"] == .5
    assert result["methods"]["a"]["actual_reader_positions"] == 1
    assert result["methods"]["a"]["retained_collection_failures"] == 1
    assert result["primary"]["paired_source_mean_difference"] == .5
    with pytest.raises(ValueError, match="exactly the actual"):
        native_panel(expected, metrics, [], ("b", "a"), 0)

