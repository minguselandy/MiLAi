"""Matched loss changes do not alter the source text, target tokens or empty-label meaning."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from train_innovation_adapter import OBJECTIVES, render_target, token_weights


def test_exact_unicode_json_has_distinct_quality_relation_and_consequence_loss():
    target = {
        "delta": {
            "creates": [
                {
                    "nodes": [
                        {
                            "id": "n0",
                            "text": '资格须培训且凭据有效"。',
                            "basis": "e1",
                            "kind": "reported",
                        }
                    ],
                    "rules": [{"target": "n0", "all": ["n1"], "any": [["n2"]], "basis": "e1"}],
                }
            ],
            "changes": {},
        },
        "consequences": [{"card": False, "pass": None, "training": True, "eligibility": "unknown"}],
    }
    text, spans = render_target(target)
    assert json.loads(text) == target
    offsets = [(i, i + 1) for i in range(len(text))]
    weights = {objective: token_weights(offsets, spans, objective) for objective in OBJECTIVES}
    assert len({len(value) for value in weights.values()}) == 1
    claim = text.index("资格")
    rule = text.index('"n1"') + 1
    consequence = text.index("unknown")
    assert [weights[o][claim] for o in OBJECTIVES] == [1, 2, 2]
    assert [weights[o][rule] for o in OBJECTIVES] == [1, 1, 2]
    assert [weights[o][consequence] for o in OBJECTIVES] == [0, 0, 1]


def test_missing_consequence_labels_are_not_trained_as_a_true_empty_answer():
    text, spans = render_target({"delta": {"creates": [], "changes": {}}, "consequences": []})
    start = text.index("[]", text.index("consequences"))
    for objective in OBJECTIVES:
        weights = token_weights([(start, start + 2)], spans, objective)
        assert weights == [0.0]
