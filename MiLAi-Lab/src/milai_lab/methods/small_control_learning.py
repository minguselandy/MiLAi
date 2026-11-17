"""Sparse, source-weighted learning; unobserved actions never become negative labels."""
from __future__ import annotations

import math
from typing import Any


def state_loss(scores: Any, action_ids: list[str], supervision: dict[str, Any], *,
               component_scales: dict[str, float] | None = None) -> Any:
    """Average within a state before weighting states across the complete update window."""
    import torch  # type: ignore[import-not-found]
    import torch.nn.functional as F  # type: ignore[import-not-found]

    value_weight = float(supervision.get("value_loss_weight", 0.0))
    if value_weight < 0 or not math.isfinite(value_weight):
        raise ValueError("Observed value loss weight must be finite and nonnegative")
    if len(action_ids) <= 1 and not value_weight:
        return None
    positions = {key: index for index, key in enumerate(action_ids)}
    observed = set(supervision.get("observed_action_ids", []))
    if not observed <= positions.keys():
        raise ValueError("Observed supervision names an unavailable binding")
    terms = []
    for pair in supervision.get("preferences", []):
        if pair["outcome"] not in {"left", "right"}:
            continue
        left, right = pair["left"], pair["right"]
        if left == right or not {left, right} <= observed:
            raise ValueError("Directional preferences require two actually observed actions")
        good, bad = (left, right) if pair["outcome"] == "left" else (right, left)
        terms.append(F.softplus(scores[positions[bad]].float() - scores[positions[good]].float()))
    # CE is allowed only on an explicitly comparable subset, with known good and bad.
    good_ids = set(supervision.get("good_action_ids", []))
    comparable = supervision.get("choice_action_ids", [])
    if good_ids:
        if not good_ids < set(comparable) or not set(comparable) <= observed:
            raise ValueError("Choice loss requires observed good and bad actions")
        logits = scores[[positions[key] for key in comparable]].float()
        good = [index for index, key in enumerate(comparable) if key in good_ids]
        terms.append(torch.logsumexp(logits, 0) - torch.logsumexp(logits[good], 0))
    pair_loss = torch.stack(terms).mean() if terms else None
    if not value_weight:
        return (pair_loss * component_scales["pair"]
                if pair_loss is not None and component_scales is not None else pair_loss)
    values = supervision.get("observed_values", {})
    if not set(values) <= observed:
        raise ValueError("Value targets require actually observed actions")
    known = [(key, value) for key, value in values.items() if value is not None]
    if any(not 0 <= value <= 1 for _, value in known):
        raise ValueError("Observed value targets must lie in the unit interval")
    value_loss = None
    if known:
        logits = scores[[positions[key] for key, _ in known]].float()
        targets = torch.tensor([value for _, value in known], device=scores.device,
                               dtype=torch.float32)
        value_loss = F.binary_cross_entropy_with_logits(logits, targets)
    scales = component_scales or {"pair": 1.0, "value": 1.0}
    combined = []
    if pair_loss is not None:
        combined.append(pair_loss * scales["pair"])
    if value_loss is not None:
        combined.append(value_loss * value_weight * scales["value"])
    return sum(combined) if combined else None


def window_loss(losses: list[Any], weights: list[float]) -> tuple[Any, float]:
    """One denominator for all valid states, independent of microbatch boundaries."""
    terms = [(loss, weight) for loss, weight in zip(losses, weights, strict=True)
             if loss is not None and weight > 0]
    if not terms:
        return None, 0.0
    denominator = sum(weight for _, weight in terms)
    return sum(loss * weight for loss, weight in terms) / denominator, denominator
