"""Unknown judgments and failed first responses must not become supported successes."""
import pytest

from summarize_trajectory_outcomes import endpoint_status, summarize


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

