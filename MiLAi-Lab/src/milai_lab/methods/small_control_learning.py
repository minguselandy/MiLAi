"""Sparse, source-weighted learning; unobserved actions never become negative labels."""
from __future__ import annotations

import math
from typing import Any

from milai_lab.methods.control_numeric import MATERIAL_UNIT

PAIRED_OBJECTIVES = ("u0-reset", "u1", "u2")


def weak_evidence_targets(action_ids: list[str], supervision: dict[str, Any],
                          ) -> list[tuple[int, bool]]:
    """Known native annotation targets are independent of executed outcomes."""
    values = supervision.get("weak_evidence_values", {})
    if not set(values) <= set(action_ids) or any(
            value is not None and type(value) is not bool for value in values.values()):
        raise ValueError("Weak evidence requires nullable boolean targets for legal actions")
    return [(i, values[key]) for i, key in enumerate(action_ids) if values.get(key) is not None]


def state_loss(scores: Any, action_ids: list[str], supervision: dict[str, Any], *,
               component_scales: dict[str, float] | None = None,
               parts: dict[str, Any] | None = None) -> Any:
    """Average within a state before weighting states across the complete update window."""
    import torch  # type: ignore[import-not-found]
    import torch.nn.functional as F  # type: ignore[import-not-found]

    pair_weight = float(supervision.get("pair_loss_weight", 1.0))
    if pair_weight < 0 or not math.isfinite(pair_weight):
        raise ValueError("Preference loss weight must be finite and nonnegative")
    value_weight = float(supervision.get("value_loss_weight", 0.0))
    if value_weight < 0 or not math.isfinite(value_weight):
        raise ValueError("Observed value loss weight must be finite and nonnegative")
    cost_weight = float(supervision.get("success_cost_loss_weight", 0.0))
    if cost_weight < 0 or not math.isfinite(cost_weight):
        raise ValueError("Success cost loss weight must be finite and nonnegative")
    weak_weight = float(supervision.get("weak_evidence_loss_weight", 0.0))
    if weak_weight < 0 or not math.isfinite(weak_weight):
        raise ValueError("Weak evidence loss weight must be finite and nonnegative")
    if len(action_ids) <= 1 and not value_weight and not cost_weight and not weak_weight:
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
    pair_loss = torch.stack(terms).mean() * pair_weight if terms and pair_weight else None
    if not value_weight and not cost_weight and not weak_weight:
        if parts is not None and pair_loss is not None:
            parts["quality_rank"] = pair_loss
        return (pair_loss * component_scales["pair"]
                if pair_loss is not None and component_scales is not None else pair_loss)
    values = supervision.get("observed_values", {})
    if not set(values) <= observed:
        raise ValueError("Value targets require actually observed actions")
    known = [(key, value) for key, value in values.items() if value is not None]
    if any(not 0 <= value <= 1 for _, value in known):
        raise ValueError("Observed value targets must lie in the unit interval")
    value_loss = None
    if known and value_weight:
        logits = scores[[positions[key] for key, _ in known]].float()
        targets = torch.tensor([value for _, value in known], device=scores.device,
                               dtype=torch.float32)
        value_loss = F.binary_cross_entropy_with_logits(logits, targets)
    cost_terms = []
    if cost_weight:
        witnesses = supervision.get("success_cost_witness_values", {})
        costs = supervision.get("observed_costs", {})
        for pair in supervision.get("success_cost_preferences", []):
            left, right, axis = pair["left"], pair["right"], pair["axis"]
            if left == right or not {left, right} <= observed:
                raise ValueError("Success cost pairs require two actually observed actions")
            if any(values.get(key) != 1.0 or witnesses.get(key) != 1.0
                   for key in (left, right)):
                raise ValueError("Success cost pairs require both known success witnesses")
            if axis not in {"material_UTF8_tokens", "reader_input_tokens", "reader_output_tokens",
                            "local_action_to_request_wall_seconds",
                            "local_action_to_request_cpu_seconds"}:
                raise ValueError("Success cost axis must name an actual measured resource")
            a, b = (costs.get(key, {}).get(axis) for key in (left, right))
            if any(type(value) not in {int, float} or not math.isfinite(value) or value < 0
                   for value in (a, b)):
                raise ValueError("Success cost targets must be known finite nonnegative values")
            expected = "left" if a < b else "right" if b < a else "tie"
            if pair["outcome"] != expected or expected == "tie":
                raise ValueError("Success cost direction must follow unequal measured costs")
            good, bad = (left, right) if expected == "left" else (right, left)
            cost_terms.append(F.softplus(scores[positions[bad]].float()
                                         - scores[positions[good]].float()))
    cost_loss = torch.stack(cost_terms).mean() if cost_terms else None
    weak = weak_evidence_targets(action_ids, supervision) if weak_weight else []
    scales = component_scales or {"pair": 1.0, "value": 1.0, "success_cost": 1.0,
                                  "weak_evidence": 1.0}
    combined = {}
    if pair_loss is not None:
        combined["quality_rank"] = pair_loss * scales["pair"]
    if value_loss is not None:
        combined["quality_value"] = value_loss * value_weight * scales["value"]
    if cost_loss is not None:
        combined["success_cost_quality"] = cost_loss * cost_weight * scales["success_cost"]
    if weak:
        logits = scores[[i for i, _ in weak]].float()
        labels = torch.tensor([v for _, v in weak], device=scores.device, dtype=torch.float32)
        combined["weak_evidence"] = (F.binary_cross_entropy_with_logits(logits, labels)
                                     * weak_weight * scales["weak_evidence"])
    if parts is not None:
        parts.update(combined)
    return sum(combined.values()) if combined else None


def paired_state_losses(
    quality_logits: Any,
    cost_units: Any,
    action_ids: list[str],
    supervision: dict[str, Any],
    objective: str,
) -> dict[str, Any]:
    """Return state-mean loss components with their frozen experiment coefficients."""
    import torch  # type: ignore[import-not-found]
    import torch.nn.functional as F  # type: ignore[import-not-found]

    if objective not in PAIRED_OBJECTIVES:
        raise ValueError("Select a registered quality/cost objective")
    positions = {key: index for index, key in enumerate(action_ids)}
    parts: dict[str, Any] = {}
    state_loss(
        quality_logits, action_ids, {
            **supervision, "pair_loss_weight": 0.2, "value_loss_weight": 1.0,
            "success_cost_loss_weight": 0.05 if objective == "u0-reset" else 0.0,
            "weak_evidence_loss_weight": 0.0,
        }, parts=parts,
    )
    handled = set(supervision["observed_action_ids"])
    costs = supervision.get("outcome_cost_tokens", {})
    if costs:
        if not costs.keys() <= handled or any(
            not math.isfinite(cost) or cost < 0 for cost in costs.values()
        ):
            raise ValueError("Reader cost targets require measured nonnegative input usage")
        predicted = cost_units[[positions[a] for a in costs]].float().log1p()
        measured = predicted.new_tensor([math.log1p(v / MATERIAL_UNIT) for v in costs.values()])
        parts["cost_regression"] = 0.05 * F.smooth_l1_loss(predicted, measured, beta=0.1)
    if objective == "u2":
        pairs = [pair for pair in supervision.get("paired_deltas", []) if pair["quality_known"]]
        if pairs:
            if any(
                pair["left"] == pair["right"] or not {pair["left"], pair["right"]} <= handled
                or not -1 <= pair["quality_delta"] <= 1
                or pair["common_quality_repeats"] <= 0 for pair in pairs
            ):
                raise ValueError("Quality differences require compatible observed repeats")
            q = quality_logits.float().sigmoid()
            left = q[[positions[pair["left"]] for pair in pairs]]
            right = q[[positions[pair["right"]] for pair in pairs]]
            measured = torch.tensor([p["quality_delta"] for p in pairs], device=q.device,
                                    dtype=torch.float32)
            parts["quality_delta"] = 0.2 * F.smooth_l1_loss(left - right, measured, beta=0.1)
    return parts


def window_loss(losses: list[Any], weights: list[float]) -> tuple[Any, float]:
    """One denominator for all valid states, independent of microbatch boundaries."""
    terms = [(loss, weight) for loss, weight in zip(losses, weights, strict=True)
             if loss is not None and weight > 0]
    if not terms:
        return None, 0.0
    denominator = sum(weight for _, weight in terms)
    return sum(loss * weight for loss, weight in terms) / denominator, denominator
