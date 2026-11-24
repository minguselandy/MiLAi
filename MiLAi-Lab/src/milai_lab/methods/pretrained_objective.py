"""Root-averaged training objectives for four group-bootstrap value heads."""

from __future__ import annotations

import math
import random

import torch
from torch.nn import functional as F


def group_weights(seed, group):
    rng = random.Random()  # noqa: S311
    rng.seed(f"{seed}/{group}", version=1)
    weights = []
    for _ in range(4):
        draw = math.exp(-1)
        count, product = 0, rng.random()
        while product > draw:
            count += 1
            product *= rng.random()
        weights.append(count)
    if not any(weights):
        weights[rng.randrange(4)] = 1
    return weights


def root_loss(row, quality, future, weights, cost_scale, *, pair_weight):
    ids = [a["id"] for a in row["online"]["actions"]]
    if len(ids) != len(set(ids)) or row["split_role"] != "train":
        raise ValueError("Expected a unique legal TRAIN menu")
    head_weights = quality.new_tensor(weights)
    head_weights = head_weights / head_weights.sum()
    losses = quality.new_zeros(4)
    if "weak" in row:
        measured = [
            (i, row["weak"][key]) for i, key in enumerate(ids) if row["weak"].get(key) is not None
        ]
        if measured:
            ix, labels = zip(*measured, strict=False)
            y = quality.new_tensor(labels)[:, None].expand(-1, 4)
            losses += F.binary_cross_entropy(quality[list(ix)], y, reduction="none").mean(0)
        if row["demo"] is not None:
            logits = torch.logit(quality.clamp(1e-6, 1 - 1e-6))
            losses -= logits.log_softmax(0)[ids.index(row["demo"])]
        return losses @ head_weights, 0
    if row["continuation_mode"] != "full_episode":
        raise ValueError("Only full continuations can fit terminal values")
    measured = {}
    for outcome in row["outcomes"]:
        key = outcome["first_action_id"]
        if key not in ids or key in measured:
            raise ValueError("Outcome must identify a unique offered action")
        measured[key] = outcome
    for values, name, flag, scale, coefficient in [
        (quality, "reader_quality", "quality_observed", 1.0, 1.0),
        (future, "future_cost", "future_cost_observed", cost_scale, 0.1),
    ]:
        selected = [(ids.index(k), o[name]) for k, o in measured.items() if o[flag]]
        if not selected:
            continue
        ix, y = zip(*selected, strict=False)
        if any(not math.isfinite(v) for v in y) or (
            name == "reader_quality" and any(not 0 <= v <= 1 for v in y)
        ):
            raise ValueError("Invalid observed value")
        actual = values.new_tensor(y)[:, None].expand(-1, 4) / scale
        losses += coefficient * F.smooth_l1_loss(values[list(ix)], actual, reduction="none").mean(0)
    differences = []
    for a, b in row["comparisons"]:
        if all(k in measured and measured[k]["quality_observed"] for k in (a, b)):
            delta = measured[a]["reader_quality"] - measured[b]["reader_quality"]
            estimate = quality[ids.index(a)] - quality[ids.index(b)]
            # Continuous reliability weight around near ties.
            differences.append(
                min(1.0, abs(delta) / 0.05)
                * F.smooth_l1_loss(estimate, torch.full_like(estimate, delta), reduction="none")
            )
    if differences:
        losses += pair_weight * torch.stack(differences).mean(0)
    return losses @ head_weights, len(differences)
