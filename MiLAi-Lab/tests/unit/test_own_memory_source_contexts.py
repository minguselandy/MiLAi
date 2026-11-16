import importlib.util
from pathlib import Path


def module():
    spec = importlib.util.spec_from_file_location("own_labels", Path(__file__).parents[2]
        / "tools/prepare_own_memory_operation_labels.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def review():
    return module().source_task_review


def test_repeated_literal_cannot_bind_an_earlier_capture_to_a_future_event():
    helpers = module()
    originals = [{"id": key, "role": "user", "content": "Value is five."} for key in ("a", "u")]
    earlier = {"capture_key": "a", "role": "user", "content": "Value is five.",
               "source_revision": 1, "observed_at": "same-clock"}
    sources = {"original-id": earlier}
    assert helpers.original_source_mapping(originals, sources) == {"original-id": "a"}
    sources["new-id"] = {**earlier, "capture_key": "u"}
    mapping = helpers.original_source_mapping(originals, sources)
    event = {"before": {"visible_evidence": [{"kind": "original_source", "evidence": [
        {"role": "user", "content": "Value is five.", "captured_at": "same-clock"}]}]},
        "opened_original_source_ranges": [
            {"source_ref": "original-id", "source_revision": 1, "start": 0, "end": 5},
            {"source_ref": "original-id", "source_revision": 1, "start": 5, "end": 14}]}
    assert helpers.delivered_original_sources(event, mapping, sources) == ({"a"}, False)
    event.pop("opened_original_source_ranges")
    assert helpers.delivered_original_sources(event, mapping, sources) == (set(), True)
    sources["new-id"]["observed_at"] = "later-clock"
    assert helpers.delivered_original_sources(event, mapping, sources) == ({"a"}, False)


def test_partial_or_other_revision_body_is_not_a_complete_original_proof():
    helpers = module()
    sources = {"s": {"content": "Whole body", "source_revision": 1}}
    event = {"opened_original_source_ranges": [
        {"source_ref": "s", "source_revision": 1, "start": 0, "end": 5},
        {"source_ref": "s", "source_revision": 2, "start": 5, "end": 10}]}
    assert helpers.delivered_original_sources(event, {"s": "original"}, sources) == (set(), False)


def test_a_generated_echo_is_not_automatically_the_imported_original():
    helpers = module()
    original = {"id": "imported", "role": "assistant", "content": "Recorded statement."}
    sources = {
        "old": {**original, "capture_key": "imported", "observed_at": "old"},
        "reply": {**original, "capture_key": "new-generated-reply", "observed_at": "new"},
    }
    mapping = helpers.original_source_mapping([original], sources)
    assert mapping == {"old": "imported"}
    body = {"role": "assistant", "content": "Recorded statement."}
    event = {"before": {"visible_evidence": [{"kind": "original_source", "evidence": [body]}]}}
    assert helpers.delivered_original_sources(event, mapping, sources) == (set(), True)
    body["captured_at"] = "new"
    assert helpers.delivered_original_sources(event, mapping, sources) == (set(), False)


def test_structured_source_uses_actual_rendered_body_and_keeps_scalar_types():
    helpers = module()
    original = {"id": "a", "role": "tool", "content": {"value": False}}
    source = {**original, "capture_key": "a", "source_revision": 1}
    wrong = {**source, "content": {"value": 0}}
    assert helpers.original_source_mapping([original], {"s": wrong}) == {}
    mapping = helpers.original_source_mapping([original], {"s": source})
    event = {"opened_original_source_ranges": [{"source_ref": "s", "source_revision": 1,
        "start": 0, "end": len(helpers.body_text(source))}]}
    assert helpers.delivered_original_sources(event, mapping, {"s": source}) == ({"a"}, False)


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
