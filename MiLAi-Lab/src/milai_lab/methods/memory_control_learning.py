"""Offline operation examples and metrics; task success requires actual rollouts."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from milai_lab.methods.laya_memory_policy import operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState


def decision_example(event: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Export the same model input, initially masked until a source-grounded review."""
    state = MemoryControlState(**event["before"])
    actions = [MemoryAction(**a) for a in event["actions"]]
    return {**operation_payload(state, actions), "gold": {},
            "metadata": {**metadata, "action_kinds": {a.id: a.kind for a in actions},
                         "label_status": "unreviewed_masked"}}


def score_operation_predictions(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    strata: dict[str, Counter[str]] = defaultdict(Counter)
    chosen: dict[str, Counter[str]] = defaultdict(Counter)
    families: dict[str, list[int]] = defaultdict(list)
    for row, prediction in zip(rows, predictions, strict=True):
        target = row.get("gold", {}).get("next", {}).get("probabilities", {})
        if not target:
            counts["masked"] += 1
            continue
        choice = prediction["choice"]
        accepted = int(target.get(choice, 0) > 0)
        kind = row["metadata"]["action_kinds"][choice]
        counts.update(labelled=1, accepted=accepted)
        strata[row["metadata"]["label_status"]].update(labelled=1, accepted=accepted)
        chosen[kind].update(selected=1, accepted=accepted)
        families[row["metadata"]["family"]].append(accepted)
        if kind == "HANDOFF" and not accepted:
            counts["handoff_outside_reviewed_preference"] += 1
    return {"counts": dict(counts), "strata": dict(strata), "selected_operations": dict(chosen),
            "families": len(families), "family_macro_acceptance": (
                sum(sum(v) / len(v) for v in families.values()) / len(families)
                if families else None),
            "scope": "Reviewed operation preferences; not exhaustive action legality, "
                     "Reader task/state success or cost benefit"}
