"""Offline preferences cannot change inputs or turn unreviewed actions into gold."""
import copy

import pytest

from milai_lab.methods.retrieval_supervision import annotate_decisions


def test_review_masks_and_inputs_are_preserved_without_teacher_imitation():
    rows = [{"state": {"task": {"retrieval_request": {"query": "first saved version"}}},
             "questions": {"next": {"criteria": {"read": "READ", "return": "HANDOFF"}}},
             "gold": {}, "metadata": {"event_id": str(i), "selected_teacher_action": "read"}}
            for i in range(3)]
    rows.append({**copy.deepcopy(rows[0]), "metadata": {"event_id": "forced"},
                 "questions": {"next": {"criteria": {"return": "HANDOFF"}}}})
    original = copy.deepcopy(rows)
    result = annotate_decisions(rows, [
        {"event_id": "0", "preferred_actions": ["return"], "basis": "Actual revision1 opened"},
        {"event_id": "1", "preferred_actions": [], "basis": "Generated view not adjudicated"},
        {"event_id": "forced", "preferred_actions": ["return"], "basis": "Only option"}])
    assert rows == original
    assert result[0]["gold"]["next"]["probabilities"] == {"read": 0.0, "return": 1.0}
    assert all(not row["gold"] for row in result[1:])
    assert [r["state"] for r in result] == [r["state"] for r in rows]
    assert [r["questions"] for r in result] == [r["questions"] for r in rows]
    with pytest.raises(ValueError, match="outside"):
        annotate_decisions(rows, [{"event_id": "0", "preferred_actions": ["invented"]}])
