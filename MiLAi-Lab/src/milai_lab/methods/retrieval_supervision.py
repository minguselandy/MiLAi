"""Attach explicit source-reviewed preferences to unchanged observed decisions."""
from __future__ import annotations

import copy
from typing import Any


def annotate_decisions(
    rows: list[dict[str, Any]], reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """No observed teacher action or executable option becomes an automatic label.

    The review is an offline judgment, not a claim that every other action is
    illegal or that its probability is calibrated. Unreviewed states stay masked.
    """
    by_event = {review["event_id"]: review for review in reviews}
    if len(by_event) != len(reviews):
        raise ValueError("More than one review for the same decision")
    unknown = set(by_event) - {row["metadata"]["event_id"] for row in rows}
    if unknown:
        raise ValueError("Review does not identify an observed decision: " + str(sorted(unknown)))
    result = []
    for original in rows:
        row = copy.deepcopy(original)
        review = by_event.get(row["metadata"]["event_id"])
        choices = row["questions"]["next"]["criteria"]
        row["gold"] = {}
        if review is not None:
            row["metadata"]["source_review"] = copy.deepcopy(review)
            selected = list(dict.fromkeys(review["preferred_actions"]))
            if set(selected) - set(choices):
                raise ValueError("Preference is outside the actual executable action set")
            if selected and len(choices) > 1:
                row["gold"] = {"next": {"probabilities": {
                    key: 1 / len(selected) if key in selected else 0.0 for key in choices}}}
                row["metadata"]["label_status"] = "source_reviewed_preference"
            else:
                row["metadata"]["label_status"] = (
                    "forced_single_action_masked" if len(choices) == 1
                    else "reviewed_ambiguous_masked")
        else:
            row["metadata"]["label_status"] = "unreviewed_masked"
        result.append(row)
    return result
