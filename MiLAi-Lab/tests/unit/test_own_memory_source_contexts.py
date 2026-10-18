import importlib.util
from pathlib import Path


def review():
    spec = importlib.util.spec_from_file_location("own_labels", Path(__file__).parents[2]
        / "tools/prepare_own_memory_operation_labels.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.source_task_review


def test_review_context_tracks_each_actual_task_instead_of_collapsing_all_changes():
    family = {"offline_review": {"steps": {
        "q1": {"context": "initial", "support_sets": [["old"]], "answer": "original"},
        "q2": {"context": "proposed", "support_sets": [["old", "plan"]],
               "answer": "original, with pending change"},
        "q3": {"context": "cancelled", "support_sets": [["cancel"]],
               "answer": "original, plan withdrawn"},
        "q4": {"context": "cancelled", "support_sets": [["cancel"]],
               "answer": "original, plan withdrawn"}}}}
    label = review()
    assert label(family, "q2", {"old", "plan"}) == (
        "proposed", [{"old", "plan"}], "original, with pending change")
    assert label(family, "q3", {"old", "plan", "cancel"}) == label(
        family, "q4", {"old", "plan", "cancel"})


def test_existing_frozen_before_after_source_contract_remains_compatible():
    family = {"offline_review": {"before_answer": "old", "after_answer": "new",
        "before_support_sets": [["a"]], "after_support_sets": [["a", "u"]]}}
    label = review()
    assert label(family, "repeat", {"a", "n"}) == ("before", [{"a"}], "old")
    assert label(family, "repeat", {"a", "u", "n"}) == ("after", [{"a", "u"}], "new")
