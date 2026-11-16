"""Sparse, source-weighted learning; unobserved actions never become negative labels."""
from __future__ import annotations

from typing import Any


def state_loss(scores: Any, action_ids: list[str], supervision: dict[str, Any]) -> Any:
    """Average within a state before weighting states across the complete update window."""
    import torch  # type: ignore[import-not-found]
    import torch.nn.functional as F  # type: ignore[import-not-found]

    if len(action_ids) <= 1:
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
    return torch.stack(terms).mean() if terms else None


def window_loss(losses: list[Any], weights: list[float]) -> tuple[Any, float]:
    """One denominator for all valid states, independent of microbatch boundaries."""
    terms = [(loss, weight) for loss, weight in zip(losses, weights, strict=True)
             if loss is not None and weight > 0]
    if not terms:
        return None, 0.0
    denominator = sum(weight for _, weight in terms)
    return sum(loss * weight for loss, weight in terms) / denominator, denominator
