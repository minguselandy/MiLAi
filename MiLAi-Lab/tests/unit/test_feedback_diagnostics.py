"""Shared support and source-level scores must not inflate evidence from additional pairs."""
import copy
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from retrieval_feedback import RESOURCE_FIELDS, common_support, resource_preference, score_feedback
from retrieval_mixture import event_weights


def row(family, index, pairs):
    return {"state": {"task": "literal request"}, "questions": {"next": {"criteria": {
        "a": "READ first binding", "b": "READ second binding", "c": "HANDOFF", "d": "SEARCH"}}},
        "gold": {}, "metadata": {"family": family, "row": index, "event_id": str(index)},
        "feedback": {"comparisons": pairs}}


def pair(left="a", right="b", answer="left", delivery="left"):
    return dict(left=left, right=right, answer=answer, delivery=delivery)


def test_common_support_keeps_zero_direction_states_replay_ids_and_sampling_weights():
    rows = [row("f", 1, [pair(), pair("a", "c", delivery="right"),
                           pair("b", "d", answer="tie")]),
            row("g", 2, [pair(answer="unknown")])]
    replay = copy.deepcopy(rows[1])
    replay.pop("feedback")
    replay["gold"] = {"next": {"probabilities": {"a": 1}}}
    replay["metadata"].update(row=3, event_id="3")
    rows.append(replay)
    original = copy.deepcopy(rows)
    selected, report = common_support(rows)
    assert rows == original and len(selected) == 3
    assert selected[1]["feedback"]["comparisons"] == []
    assert selected[2] == replay
    assert selected[0]["feedback"]["comparisons"] == rows[0]["feedback"]["comparisons"][:2]
    assert event_weights(selected) == event_weights(rows)
    assert report["counts"] == {"pairs_outside_common_support": 2,
        "states_with_common_direction": 1, "directional_pairs": 2,
        "same_direction_pairs": 1, "opposite_direction_pairs": 1}
    assert all(selected[i]["state"] == rows[i]["state"] for i in range(3))


def test_source_macro_averages_states_before_families_and_exposes_unknown_coverage():
    rows = [row("f", 1, [pair(), pair("a", "c"), pair("a", "d")]),
            row("f", 2, [pair(answer="right")]),
            row("g", 3, [pair(answer="right")]),
            row("unknown-only", 4, [pair(answer="unknown")])]
    predictions = [{"logits": {"a": 2., "b": 0., "c": 0., "d": 0.}} for _ in rows]
    result = score_feedback(rows, predictions, "answer")
    assert result["counts"] == {"directional_pairs": 5, "ordered_correctly": 3, "unknown": 1}
    assert result["family_macro_state_pair_accuracy"] == .25
    assert result["family_macro_state_pair_loss"] == pytest.approx(1.5 + math.log1p(math.exp(-2)))
    assert result["families"] == 3 and result["families_with_direction"] == 2
    assert result["coverage"]["states_with_direction"] == 3
    unknown = score_feedback(rows[-1:], predictions[-1:], "answer")
    assert unknown["family_macro_state_pair_accuracy"] is None


def test_resource_dominance_never_sums_tokens_operations_or_wall_time():
    left = dict.fromkeys(RESOURCE_FIELDS, 0)
    right = dict.fromkeys(RESOURCE_FIELDS, 1)
    assert resource_preference(left, right) == "left"
    assert resource_preference(right, left) == "right"
    assert resource_preference(left, left) == "tie"
    left["read_operations"] = 2
    assert resource_preference(left, right) == "incomparable"
