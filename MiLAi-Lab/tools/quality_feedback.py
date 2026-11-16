"""Quality/tie/cost supervision over the same explicitly reviewed branch pairs."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Literal

from retrieval_feedback import resource_preference, score_feedback, validate_feedback
from retrieval_mixture import event_weights, normalized_mixture

QualityMode = Literal["quality-direction", "quality-tie", "quality-cost"]
QUALITY_MODES = ("quality-direction", "quality-tie", "quality-cost")
ANSWER_FIRST_MASSES = {"answer": 0.80, "delivery_auxiliary": 0.20}


def answer_first_pairs(comparisons: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Mask each pair, not the state; retain original judgments and known answer ties."""
    result: dict[str, list[dict[str, Any]]] = {key: [] for key in ANSWER_FIRST_MASSES}
    for pair in comparisons:
        quality = pair["basis"]["quality_before_resource_tiebreak"]
        if quality["answer"] != "unknown":
            result["answer"].append(pair)
        elif quality["delivery"] != "unknown":
            result["delivery_auxiliary"].append(pair)
    return result


def answer_first_weights(rows: list[dict[str, Any]], replay_weight: float,
                         ) -> list[dict[str, float]]:
    """Independent family/event normalization; missing mass is zero, never reassigned."""
    masses = {**ANSWER_FIRST_MASSES, "replay": replay_weight}
    indices: dict[str, list[int]] = {key: [] for key in masses}
    for i, row in enumerate(rows):
        if "feedback" not in row:
            indices["replay"].append(i)
        else:
            for key, pairs in answer_first_pairs(row["feedback"]["comparisons"]).items():
                if pairs:
                    indices[key].append(i)
    result = [dict.fromkeys(masses, 0.0) for _ in rows]
    for key, positions in indices.items():
        if not positions:
            continue
        local = event_weights([rows[i] for i in positions])
        scale = len(rows) * masses[key] / len(positions)
        for i, weight in zip(positions, local, strict=True):
            result[i][key] = weight * scale
    return result


def answer_first_loss(logits: Any, keys: list[str], comparisons: list[dict[str, Any]],
                      weights: dict[str, float], *, label_smoothing: float = 0.0) -> Any:
    parts = answer_first_pairs(comparisons)
    return sum(weights[key] * quality_pair_loss(
        logits, keys, pairs, "answer" if key == "answer" else "delivery", "quality-tie",
        label_smoothing=label_smoothing) for key, pairs in parts.items())


def answer_first_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    components: dict[str, Counter[str]] = {key: Counter() for key in ANSWER_FIRST_MASSES}
    families: dict[str, set[str]] = {key: set() for key in components}
    events: dict[str, set[tuple[str, Any]]] = {key: set() for key in components}
    for row in rows:
        if "feedback" not in row:
            counts["replay_states"] += 1
            continue
        counts["feedback_states"] += 1
        comparisons = row["feedback"]["comparisons"]
        parts = answer_first_pairs(comparisons)
        counts["states_with_targets"] += any(parts.values())
        counts["unknown_pairs"] += len(comparisons) - sum(map(len, parts.values()))
        counts["answer_unknown_pairs"] += sum(
            p["basis"]["quality_before_resource_tiebreak"]["answer"] == "unknown"
            for p in comparisons)
        for key, pairs in parts.items():
            if not pairs:
                continue
            target = "answer" if key == "answer" else "delivery"
            meta = row["metadata"]
            families[key].add(meta["family"])
            events[key].add((meta["family"], meta.get("training_event", meta["row"])))
            components[key]["states"] += 1
            components[key]["pairs"] += len(pairs)
            counts["target_pairs"] += len(pairs)
            for pair in pairs:
                label = pair["basis"]["quality_before_resource_tiebreak"][target]
                field = "tie_pairs" if label == "tie" else "directional_pairs"
                components[key][field] += 1
                counts[field] += 1
    return {**counts, "components": {key: {**value,
        "families": len(families[key]), "events": len(events[key])}
        for key, value in components.items()}}


def score_answer_first(rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
                       ) -> dict[str, Any]:
    """Task-only diagnostic with the training component normalization; not Host success."""
    weights = answer_first_weights(rows, 0.0)
    contributions = dict.fromkeys(ANSWER_FIRST_MASSES, 0.0)
    for row, prediction, weight in zip(rows, predictions, weights, strict=True):
        if "feedback" not in row:
            continue
        for key, pairs in answer_first_pairs(row["feedback"]["comparisons"]).items():
            target = "answer" if key == "answer" else "delivery"
            losses = []
            for left, right, y in targets(pairs, target, "quality-tie"):
                margin = prediction["logits"][left] - prediction["logits"][right]
                losses.append(max(margin, 0) - y * margin + math.log1p(math.exp(-abs(margin))))
            if losses:
                contributions[key] += weight[key] * sum(losses) / len(losses) / len(rows)
    counts = answer_first_counts(rows)
    return {"mode": "answer-first", "component_masses": ANSWER_FIRST_MASSES,
        "coverage": counts, "weighted_task_pair_loss": sum(contributions.values()),
        "components": {key: {"weighted_loss": value, "family_event_pair_loss": (
            value / ANSWER_FIRST_MASSES[key] if counts["components"][key].get("pairs") else None)}
            for key, value in contributions.items()},
        "scope": "Answer known (including tie), else known delivery auxiliary, else masked. "
            "Pairs averaged within state, then eligible events/families independently per "
            "component. Missing component contributes zero without reallocating mass. "
            "No cost tiebreak, replay loss or claim of selected-action/Host quality."}


def outcome(pair: dict[str, Any], target: str, mode: QualityMode) -> str:
    quality: str = pair["basis"]["quality_before_resource_tiebreak"][target]
    if mode == "quality-cost" and quality == "tie":
        order = pair["basis"]["resource_order"]
        cost = resource_preference(order["left"], order["right"])
        if cost in {"left", "right"}:
            return cost
    return quality


def targets(
    comparisons: list[dict[str, Any]], target: str, mode: QualityMode,
) -> list[tuple[str, str, float]]:
    result = []
    for pair in comparisons:
        label = outcome(pair, target, mode)
        if label == "unknown" or (label == "tie" and mode == "quality-direction"):
            continue
        result.append((pair["left"], pair["right"], {"left": 1.0, "right": 0.0, "tie": .5}[label]))
    return result


def validate_quality_pool(rows: list[dict[str, Any]]) -> None:
    """Require explicit pre-cost judgments, never infer quality from a final cost label."""
    for row in rows:
        if "feedback" not in row:
            continue
        validate_feedback(row)
        for pair in row["feedback"]["comparisons"]:
            for target in ("answer", "delivery"):
                quality = pair["basis"]["quality_before_resource_tiebreak"][target]
                if quality not in {"left", "right", "tie", "unknown"}:
                    raise ValueError("Explicit quality target is missing or invalid")
                if pair[target] != outcome(pair, target, "quality-cost"):
                    raise ValueError("Original label does not match its quality/cost evidence")


def quality_pair_loss(
    logits: Any, keys: list[str], comparisons: list[dict[str, Any]], target: str, mode: QualityMode,
    *, label_smoothing: float = 0.0,
) -> Any:
    """Mean known-pair BCE; optional smoothing leaves ties and unknown masks unchanged."""
    import torch
    import torch.nn.functional as functional

    positions = {key: i for i, key in enumerate(keys)}
    losses = []
    for left, right, y in targets(comparisons, target, mode):
        margin = logits[positions[left]] - logits[positions[right]]
        y = (1 - label_smoothing) * y + label_smoothing * (1 - y)
        losses.append(y * functional.softplus(-margin) + (1-y) * functional.softplus(margin))
    return torch.stack(losses).mean() if losses else logits[0] * 0


def quality_counts(rows: list[dict[str, Any]], target: str, mode: QualityMode) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if "feedback" not in row:
            counts["replay_states"] += 1
            continue
        counts["feedback_states"] += 1
        comparisons = row["feedback"]["comparisons"]
        known = targets(comparisons, target, mode)
        counts["states_with_targets"] += bool(known)
        counts["target_pairs"] += len(known)
        for pair in comparisons:
            label = outcome(pair, target, mode)
            counts["directional_pairs" if label in {"left", "right"} else label+"_pairs"] += 1
            if (mode == "quality-cost" and label in {"left", "right"}
                    and pair["basis"]["quality_before_resource_tiebreak"][target] == "tie"):
                counts["cost_only_direction_pairs"] += 1
    return dict(counts)


def quality_event_weights(
    rows: list[dict[str, Any]], target: str, mode: QualityMode, replay_weight: float,
    *, normalize_total: bool = True,
) -> list[float]:
    """Retain every draw, normalize loss over eligible family/events in each component.

    Zero-target states get zero weight. Uniform sampling still visits them; scaling
    by the full row count prevents unknown states from diluting the known loss.
    A component with no known targets contributes zero, without giving its mass away.
    Q-tie and Q-cost have identical eligibility, hence identical weights.
    """
    masses = {"feedback": 1.0, "replay": replay_weight}
    if normalize_total:
        masses = normalized_mixture(masses)
    groups: dict[str, list[int]] = {"feedback": [], "replay": []}
    for i, row in enumerate(rows):
        if "feedback" not in row:
            groups["replay"].append(i)
        elif targets(row["feedback"]["comparisons"], target, mode):
            groups["feedback"].append(i)
    weights = [0.0] * len(rows)
    for component, indices in groups.items():
        if not indices:
            continue
        local = event_weights([rows[i] for i in indices])
        scale = len(rows) * masses[component] / len(indices)
        for i, weight in zip(indices, local, strict=True):
            weights[i] = scale * weight
    return weights


def score_quality_feedback(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]], target: str,
    mode: QualityMode = "quality-tie",
) -> dict[str, Any]:
    """Known-pair loss includes ties; directional accuracy remains a separate readout."""
    families: dict[str, list[tuple[float, float]]] = defaultdict(list)
    projected = []
    for row, prediction in zip(rows, predictions, strict=True):
        if "feedback" not in row:
            projected.append(row)
            continue
        comparisons = row["feedback"]["comparisons"]
        projected.append({**row, "feedback": {**row["feedback"], "comparisons": [
            {**pair, target: outcome(pair, target, mode)} for pair in comparisons]}})
        losses, errors = [], []
        for left, right, y in targets(comparisons, target, mode):
            margin = prediction["logits"][left] - prediction["logits"][right]
            loss = (max(margin, 0) - y*margin + math.log1p(math.exp(-abs(margin))))
            probability = (1 / (1 + math.exp(-margin)) if margin >= 0 else
                           math.exp(margin) / (1 + math.exp(margin)))
            losses.append(loss)
            errors.append((probability-y)**2)
        if losses:
            families[row["metadata"]["family"]].append((
                sum(losses)/len(losses), sum(errors)/len(errors)))
    by_family = {family: {"states_with_targets": len(states),
                         "state_known_pair_loss": sum(s[0] for s in states)/len(states),
                         "state_known_pair_brier": sum(s[1] for s in states)/len(states)}
                 for family, states in families.items()}
    return {"target": target, "mode": mode, "coverage": quality_counts(rows, target, mode),
        "families_with_targets": len(families), "by_family": by_family,
        "family_macro_state_known_pair_loss": (
            sum(v["state_known_pair_loss"] for v in by_family.values())/len(families)
            if families else None),
        "family_macro_state_known_pair_brier": (
            sum(v["state_known_pair_brier"] for v in by_family.values())/len(families)
            if families else None),
        "directional": score_feedback(projected, predictions, target),
        "scope": "Known reviewed pair loss, average within state then family; ties target0.5, "
                 "unknown skipped. Brier measures pair-target fit, not calibrated task success."}


def choose_quality_checkpoint(points: list[dict[str, Any]], target: str) -> dict[str, Any]:
    eligible = [p for p in points if p["pure_quality"][target][
        "directional"]["family_macro_state_pair_accuracy"] is not None]
    if not eligible:
        raise ValueError("No checkpoint has quality-direction development coverage")
    return min(eligible, key=lambda p: (
        -p["pure_quality"][target]["directional"]["family_macro_state_pair_accuracy"], p["update"]))
