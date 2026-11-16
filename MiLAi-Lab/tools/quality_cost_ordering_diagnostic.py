"""Additive readout of original ordering scores, retaining their exact state/family denominator."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from retrieval_feedback import resource_preference, score_feedback, validate_feedback


def ordering_components(
    rows: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    target: str,
) -> dict[str, Any]:
    """Partition existing directional labels; no new label or training attribution is inferred.

    Component contributions use the ORIGINAL covered-state denominators. Their
    sum is the original macro score, unlike separately normalized subgroup accuracies.
    """
    categories = ("quality_direction", "cost_tie_break")
    families: dict[str, list[dict[str, float]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    conditional_rows: dict[str, list[dict[str, Any]]] = {name: [] for name in categories}
    for row, prediction in zip(rows, predictions, strict=True):
        validate_feedback(row)
        values: Counter[str] = Counter()
        selected: dict[str, list[dict[str, Any]]] = {name: [] for name in categories}
        for pair in row["feedback"]["comparisons"]:
            quality = pair["basis"]["quality_before_resource_tiebreak"][target]
            label = pair[target]
            if quality not in {"left", "right", "tie", "unknown"}:
                raise ValueError("An explicit pre-cost quality judgment is required")
            expected = quality
            if quality == "tie":
                order = pair["basis"]["resource_order"]
                cost = resource_preference(order["left"], order["right"])
                expected = cost if cost in {"left", "right"} else "tie"
            if label != expected:
                raise ValueError("Original ordering label contradicts its quality/cost evidence")
            category = None
            if label in {"left", "right"}:
                category = "quality_direction" if quality != "tie" else "cost_tie_break"
                margin = prediction["logits"][pair["left"]] - prediction["logits"][pair["right"]]
                correct = int((margin if label == "left" else -margin) > 0)
                values[category + "_pairs"] += 1
                values[category + "_correct"] += correct
                counts[category + "_pairs"] += 1
                counts[category + "_correct"] += correct
            else:
                counts[label + "_pairs"] += 1
            if category is not None:
                selected[category].append(pair)
        total = sum(values[name + "_pairs"] for name in categories)
        if total:
            family = row["metadata"]["family"]
            families[family].append(
                {
                    key: values[name + suffix] / total
                    for name in categories
                    for key, suffix in (
                        (name + "_contribution", "_correct"),
                        (name + "_mass", "_pairs"),
                    )
                }
            )
            counts["original_covered_states"] += 1
        for name in categories:
            conditional_rows[name].append(
                {**row, "feedback": {**row["feedback"], "comparisons": selected[name]}}
            )
    by_family = {
        family: {key: sum(v[key] for v in states) / len(states) for key in states[0]}
        for family, states in families.items()
    }
    macro = (
        {
            key: sum(v[key] for v in by_family.values()) / len(by_family)
            for key in next(iter(by_family.values()))
        }
        if by_family
        else {}
    )
    original = score_feedback(rows, predictions, target)
    if by_family:
        assert math.isclose(sum(macro[name + "_mass"] for name in categories), 1, abs_tol=1e-12)
        assert math.isclose(
            sum(macro[name + "_contribution"] for name in categories),
            original["family_macro_state_pair_accuracy"],
            abs_tol=1e-12,
        )
    return {
        "target": target,
        "counts": dict(counts),
        "families": len(by_family),
        "original_metric": original,
        "original_denominator_macro": macro,
        "original_denominator_by_family": by_family,
        "conditional_group_metrics": {
            name: score_feedback(conditional_rows[name], predictions, target) for name in categories
        },
        "scope": "Exact arithmetic partition of the original metric with its covered-state and "
        "family weights preserved. Conditional subgroup accuracies have different support and "
        "cannot be added. This is an outcome readout, not causal attribution of training benefit. "
        "Unknown and non-directional pairs remain outside the original accuracy denominator.",
    }
