"""Loss on explicitly reviewed branch pairs; unexamined options remain unlabelled."""
from __future__ import annotations

from collections import Counter
from typing import Any


def validate_feedback(row: dict[str, Any]) -> None:
    """Validate the reviewed pair pool without inferring preferences from action names."""
    keys = row["questions"]["next"]["criteria"]
    if row["gold"]:
        raise ValueError("Feedback rows must not also contain full-option CE labels")
    seen = set()
    for pair in row["feedback"]["comparisons"]:
        left, right = pair["left"], pair["right"]
        if left == right or left not in keys or right not in keys:
            raise ValueError("A comparison must name two different actual offered options")
        identity = frozenset((left, right))
        if identity in seen:
            raise ValueError("A branch pair was reviewed twice in the same state")
        seen.add(identity)
        for target in ("answer", "delivery"):
            if pair[target] not in {"left", "right", "tie", "unknown"}:
                raise ValueError("Feedback must retain an explicit direction, tie or unknown")


def encoding_row(row: dict[str, Any]) -> dict[str, Any]:
    """Uniform dummy targets satisfy the SDK codec, never the preference objective."""
    if "feedback" not in row:
        return row
    validate_feedback(row)
    keys = row["questions"]["next"]["criteria"]
    return {**row, "gold": {"next": {"probabilities": {k: 1 / len(keys) for k in keys}}}}


def feedback_dev_report(
    rows: list[dict[str, Any]], train: list[dict[str, Any]], old_dev: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep the new target's denominator and original source exposure explicit."""
    for row in rows:
        validate_feedback(row)
        if row["metadata"]["split"] != "dev":
            raise ValueError("Feedback development requires declared dev-source states")
    families = {row["metadata"]["family"] for row in rows}
    if families & {row["metadata"]["family"] for row in train}:
        raise ValueError("Feedback development source family overlaps training")
    return {
        "states": len(rows), "families": len(families),
        "old_dev_family_overlap": sorted(families & {
            row["metadata"]["family"] for row in old_dev}),
        "targets": {target: feedback_counts(rows, target) for target in ("answer", "delivery")},
    }


def pair_loss(
    logits: Any, keys: list[str], comparisons: list[dict[str, Any]], target: str,
) -> Any:
    """Mean over reviewed directional pairs in one state; ties/unknowns add no direction."""
    import torch
    import torch.nn.functional as functional

    positions = {key: i for i, key in enumerate(keys)}
    terms = []
    for pair in comparisons:
        outcome = pair[target]
        if outcome in {"tie", "unknown"}:
            continue
        winner, loser = ((pair["left"], pair["right"]) if outcome == "left"
                         else (pair["right"], pair["left"]))
        terms.append(functional.softplus(logits[positions[loser]] - logits[positions[winner]]))
    return torch.stack(terms).mean() if terms else logits[0] * 0


def feedback_counts(rows: list[dict[str, Any]], target: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if "feedback" not in row:
            counts["replay_states"] += 1
            continue
        counts["feedback_states"] += 1
        outcomes = [pair[target] for pair in row["feedback"]["comparisons"]]
        counts["states_with_direction"] += int(any(x in {"left", "right"} for x in outcomes))
        for outcome in outcomes:
            counts["directional_pairs" if outcome in {"left", "right"} else outcome + "_pairs"] += 1
    return dict(counts)


def score_feedback(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]], target: str,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for row, prediction in zip(rows, predictions, strict=True):
        if "feedback" not in row:
            continue
        for pair in row["feedback"]["comparisons"]:
            outcome = pair[target]
            if outcome in {"tie", "unknown"}:
                counts[outcome] += 1
                continue
            margin = prediction["logits"][pair["left"]] - prediction["logits"][pair["right"]]
            counts["directional_pairs"] += 1
            counts["ordered_correctly"] += int(margin > 0 if outcome == "left" else margin < 0)
    return {"counts": dict(counts), "target": target,
            "scope": "Ordering of reviewed branch pairs; not exhaustive policy or Host quality."}
