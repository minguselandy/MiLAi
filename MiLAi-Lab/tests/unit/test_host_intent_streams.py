"""Request variants inherit their original source split and complete ordered arrivals."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_host_intent_streams import prepare_streams


def inputs():
    sources = [
        {"event_key": "a", "role": "user", "content": "First report", "occurred_at": None},
        {"event_key": "b", "role": "user", "content": "Correction", "occurred_at": None},
    ]
    fixture = {"histories": [{"id": "original", "source_group": "same-family", "split": "dev",
                             "continuous": True, "sources": [],
                             "requests": [{"incoming_sources": sources}]}]}
    recipe = {"scope": "Development, not blind", "split": "dev", "streams": [{
        "id": "requests", "history_id": "original", "requests": [
            {"id": "first", "after_sources": 1, "content": "Current value?"},
            {"id": "quote", "after_sources": 1, "content": "Quote it"},
            {"id": "later", "after_sources": 2, "content": "Current value?"},
        ]}]}
    return fixture, recipe, sources


def test_explicit_dev_keeps_identity_bodies_roles_clocks_and_order():
    fixture, recipe, sources = inputs()
    original = copy.deepcopy(fixture)
    stream, = prepare_streams(fixture, recipe)["histories"]
    assert stream["split"] == "dev" and stream["source_group"] == "same-family"
    assert [s for request in stream["requests"] for s in request["incoming_sources"]] == sources
    assert stream["requests"][1]["incoming_sources"] == []
    assert fixture == original


def test_default_training_preparation_cannot_move_dev_sources_into_train():
    fixture, recipe, _ = inputs()
    del recipe["split"]
    with pytest.raises(ValueError, match="declared source split"):
        prepare_streams(fixture, recipe)
