"""Equivalent probes must preserve evidence, stop semantics and action identity."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from milai_lab.methods.bounded_evidence import decision_payload
from probe_bounded_invariance import canonical_prediction, transform


@pytest.mark.parametrize("variant", ["aliases", "candidate_order", "option_order"])
def test_equivalent_views_preserve_source_and_canonical_actions(variant):
    evidence = [{"id": "p0", "title": "Read", "text": "A says p2 literally."}]
    candidates = [{"id": "p1", "title": "One", "text": "One source."},
                  {"id": "p2", "title": "Two", "text": "Another source."}]
    payload = decision_payload("Which subject?", evidence, candidates)
    changed, mapping = transform(payload, variant, 7)
    assert payload == decision_payload("Which subject?", evidence, candidates)
    assert changed["state"]["question"] == payload["state"]["question"]
    for field in ("read_evidence", "candidates"):
        assert sorted((x["title"], x["text"]) for x in changed["state"][field]) == sorted(
            (x["title"], x["text"]) for x in payload["state"][field])
    criteria = changed["questions"]["next"]["criteria"]
    assert set(mapping.values()) == set(payload["questions"]["next"]["criteria"])
    assert set(mapping) == set(criteria)
    for stop in ("stop_sufficient", "stop_exhausted"):
        assert mapping[stop] == stop
        assert criteria[stop] == payload["questions"]["next"]["criteria"][stop]
    assert (changed["questions"]["next"]["instructions"]
            == payload["questions"]["next"]["instructions"])
    transformed_open = next(key for key in mapping if mapping[key] == "open_p2")
    canonical = canonical_prediction({"choice": transformed_open,
        "logits": {key: 0.1 for key in criteria},
        "probabilities": {key: 1 / len(criteria) for key in criteria}}, mapping)
    assert canonical["choice"] == "open_p2"
    assert set(canonical["logits"]) == set(mapping.values())


def test_title_frame_preserves_names_body_and_action_meaning():
    payload = decision_payload("Which city?", [], [
        {"id": "p0", "title": "Trinity Church (Boston)", "text": "Boston, not Cornish."}])
    changed, mapping = transform(payload, "title_frame", 0)
    assert changed["state"]["candidates"] == [{
        "id": "p0", "title": "Passage titled: Trinity Church (Boston)",
        "text": "Boston, not Cornish."}]
    assert changed["questions"] == payload["questions"]
    assert mapping == {key: key for key in payload["questions"]["next"]["criteria"]}
