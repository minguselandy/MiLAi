"""Loss on explicitly reviewed branch pairs; unexamined options remain unlabelled."""
from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from typing import Any

RESOURCE_FIELDS = ("retrieval_generation_requests", "retrieval_generation_tokens",
                   "acquisition_operations", "read_operations", "wire_tokens")


def resource_preference(left: dict[str, int], right: dict[str, int]) -> str:
    """Componentwise cost comparison, only after a separately reviewed quality tie."""
    a, b = [left[k] for k in RESOURCE_FIELDS], [right[k] for k in RESOURCE_FIELDS]
    if a == b:
        return "tie"
    if all(x <= y for x, y in zip(a, b, strict=True)):
        return "left"
    if all(x >= y for x, y in zip(a, b, strict=True)):
        return "right"
    return "incomparable"


def common_support(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Retain the exact state/replay pool, restricting pairs to shared directional support."""
    selected = copy.deepcopy(rows)
    counts: Counter[str] = Counter()
    for row in selected:
        if "feedback" not in row:
            continue
        validate_feedback(row)
        pairs = row["feedback"]["comparisons"]
        common = [pair for pair in pairs
                  if all(pair[target] in {"left", "right"} for target in ("answer", "delivery"))]
        counts["pairs_outside_common_support"] += len(pairs) - len(common)
        counts["states_with_common_direction"] += bool(common)
        for pair in common:
            counts["directional_pairs"] += 1
            counts["same_direction_pairs" if pair["answer"] == pair["delivery"]
                   else "opposite_direction_pairs"] += 1
        row["feedback"]["comparisons"] = common
        row["metadata"]["feedback_scope"] = "answer_delivery_common_directional_pairs"
    return selected, {
        "counts": dict(counts), "states_retained": len(selected),
        "original": {target: feedback_counts(rows, target) for target in ("answer", "delivery")},
        "common": {target: feedback_counts(selected, target) for target in ("answer", "delivery")},
        "scope": "Conditional diagnostic, not replacement for the full feedback pool. "
                 "State order/IDs/replay retained; both targets use identical pair support. "
                 "States with no common direction remain zero-direction states.",
    }


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
    families: dict[str, list[tuple[float, float]]] = defaultdict(list)
    all_families = set()
    for row, prediction in zip(rows, predictions, strict=True):
        if "feedback" not in row:
            continue
        family = row["metadata"]["family"]
        all_families.add(family)
        correct, losses = [], []
        for pair in row["feedback"]["comparisons"]:
            outcome = pair[target]
            if outcome in {"tie", "unknown"}:
                counts[outcome] += 1
                continue
            margin = prediction["logits"][pair["left"]] - prediction["logits"][pair["right"]]
            signed_margin = margin if outcome == "left" else -margin
            accepted = int(signed_margin > 0)
            counts["directional_pairs"] += 1
            counts["ordered_correctly"] += accepted
            correct.append(accepted)
            losses.append(max(-signed_margin, 0) + math.log1p(math.exp(-abs(signed_margin))))
        if correct:
            families[family].append((sum(correct) / len(correct), sum(losses) / len(losses)))
    by_family = {family: {"states_with_direction": len(states),
                          "state_pair_accuracy_mean": sum(s[0] for s in states) / len(states),
                          "state_pair_loss_mean": sum(s[1] for s in states) / len(states)}
                 for family, states in families.items()}
    return {"counts": dict(counts), "target": target,
            "families": len(all_families), "families_with_direction": len(families),
            "by_family": by_family,
            "family_macro_state_pair_accuracy": (
                sum(v["state_pair_accuracy_mean"] for v in by_family.values()) / len(families)
                if families else None),
            "family_macro_state_pair_loss": (
                sum(v["state_pair_loss_mean"] for v in by_family.values()) / len(families)
                if families else None),
            "coverage": feedback_counts(rows, target),
            "scope": "Reviewed pair ordering; average within covered state, then source family. "
                     "Conditional on directional coverage, not all states or Host success."}
