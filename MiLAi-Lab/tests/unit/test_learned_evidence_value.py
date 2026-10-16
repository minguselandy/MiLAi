"""Conditional gain, label isolation and portable fitted coefficients."""

import copy
import json
from pathlib import Path

import numpy as np

from milai_lab.methods.learned_evidence_value import LearnedValue, ValueFeatures, ridge_fit


def packet(opened=False):
    return {
        "question": "How many days between the two visits?",
        "date": "2030-01-20",
        "memories": (
            [
                {
                    "label": "e9",
                    "evidence": [
                        {
                            "source": "s7",
                            "content": "The first visit was January 8.",
                            "reported_at": "2030-01-08",
                        }
                    ],
                }
            ]
            if opened
            else []
        ),
        "candidate_actions": [
            {
                "item_index": 3,
                "excerpt": "The second visit was January 15.",
                "date": "2030-01-15",
                "expand_context": True,
            }
        ],
    }


def test_same_candidate_can_have_different_conditional_gain():
    before, after = packet(), packet(True)
    features = ValueFeatures.fit([before, after])
    independent = np.stack([features.encode(p, conditional=False) for p in (before, after)])
    conditional = np.stack([features.encode(p, conditional=True) for p in (before, after)])
    assert np.array_equal(independent[0], independent[1])
    assert not np.array_equal(conditional[0], conditional[1])
    target = np.asarray([0.0, 1.0])
    independent_predictions = independent @ ridge_fit(independent, target, 0.001)
    conditional_predictions = conditional @ ridge_fit(conditional, target, 0.001)
    assert abs(independent_predictions[0] - independent_predictions[1]) < 1e-12
    assert np.mean((conditional_predictions - target) ** 2) < 0.001


def test_ids_review_and_outcome_labels_never_change_features():
    original = packet(True)
    features = ValueFeatures.fit([original])
    changed = copy.deepcopy(original)
    changed.update(correct=True, observed_gain=1, condition="gold", review="SECRET_REVIEW")
    changed["candidate_actions"][0]["item_index"] = 100
    changed["memories"][0]["label"] = "different"
    changed["memories"][0]["evidence"][0]["source"] = "different-source"
    assert np.array_equal(
        features.encode(original, conditional=True), features.encode(changed, conditional=True)
    )
    assert "secret_review" not in ValueFeatures.fit([changed]).vocabulary


def test_fitted_model_round_trip_preserves_predictions():
    inputs = [packet(), packet(True)]
    features = ValueFeatures.fit(inputs)
    matrix = np.stack([features.encode(p, conditional=True) for p in inputs])
    weights = ridge_fit(matrix, np.asarray([0.0, 1.0]), 0.1)
    model = LearnedValue(features, True, {"immediate": weights})
    loaded = LearnedValue.from_json(json.loads(json.dumps(model.to_json())))
    assert model.predict(inputs[1]) == loaded.predict(inputs[1])


def test_unreviewed_labels_are_excluded_per_head(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    from train_evidence_value import training_examples

    rows = training_examples(
        [
            {
                "question_id": "case",
                "transitions": [
                    {
                        "before_condition": "empty",
                        "after_condition": "one",
                        "model_input": packet(),
                        "observed_gain": None,
                        "observed_two_open_return_gain": None,
                    },
                    {
                        "before_condition": "one",
                        "after_condition": "both",
                        "model_input": packet(True),
                        "observed_gain": 1,
                        "observed_two_open_return_gain": None,
                    },
                ],
                "states": [
                    {"condition": "empty", "model_input": packet(), "observed_return": False},
                    {"condition": "one", "model_input": packet(True), "observed_return": None},
                ],
            }
        ]
    )
    assert len(rows["immediate"]) == len(rows["answer_return"]) == 1
    assert rows["two_open"] == []
    assert rows["answer_return"][0]["target"] == 0.0
