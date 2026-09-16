import pytest

from milai_lab.methods.external_diagnostic import Diagnosis, next_branch, require_ready, summarize


def test_missing_support_or_disputed_does_not_manufacture_relation_signal():
    rows = [Diagnosis(str(i), "V2", ability, str(i), True, support, judgment,
                      "TEMPORAL_RELATIONAL_USE_FAILURE", True)
            for i, (ability, support, judgment) in enumerate([
                ("dynamic", False, "INCORRECT"), ("workflow", True, "DISPUTED"),
                ("gotcha", True, "INCORRECT")])]
    result = summarize(rows)
    assert result["relation_failures"] == result["support_presented_wrong"] == 1
    assert result["candidate_gate"] is False
    assert next_branch(rows) == "EXPAND_FROZEN_V2_HIT_ABILITIES"


def test_acquisition_and_unqualified_cases_cannot_become_behavioral_failures():
    row = Diagnosis("a", "V2", "workflow", None, True, False, "INCORRECT",
                    "SOURCE_NOT_ACQUIRED")
    assert next_branch([row]) == "ROUTE_TO_ACQUISITION"
    with pytest.raises(ValueError, match="EXPOSURE"):
        require_ready({"status": "UNKNOWN"}, {}, {"status": "FIT"}, {})
    with pytest.raises(ValueError, match="EVALUATION"):
        require_ready({"status": "CERTIFIED_DISTINCT"}, {"generic_template": True},
                      {"status": "FIT"}, {})


def test_shared_source_is_not_three_independent_failures():
    rows = [Diagnosis(str(i), "V2", ability, "same-source", True, True, "INCORRECT",
                      "TEMPORAL_RELATIONAL_USE_FAILURE", True)
            for i, ability in enumerate(["dynamic", "workflow", "gotcha"])]
    assert summarize(rows)["candidate_gate"] is False
