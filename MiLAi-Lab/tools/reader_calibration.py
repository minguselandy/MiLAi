"""Scalar temperature diagnostics for frozen reference-proof action distributions.

No thresholds or policies are learned here. A positive temperature preserves the
argmax, and annotated proof completion is not semantic answer sufficiency.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

from train_bounded_laya import event_weights


def log_probabilities(logits: dict[str, float], temperature: float) -> dict[str, float]:
    scaled = {key: value / temperature for key, value in logits.items()}
    peak = max(scaled.values())
    normalizer = peak + math.log(sum(math.exp(x - peak) for x in scaled.values()))
    return {key: value - normalizer for key, value in scaled.items()}


def cross_entropy(target: dict[str, float], logs: dict[str, float]) -> float:
    return -sum(value * logs[key] for key, value in target.items() if value)


def fit_temperature(rows: list[dict], predictions: list[dict]) -> dict:
    weights = event_weights(rows)
    targets = [row["gold"]["next"]["probabilities"] for row in rows]

    def objective(log_temperature: float) -> float:
        temperature = math.exp(log_temperature)
        return sum(w * cross_entropy(q, log_probabilities(p["logits"], temperature))
                   for w, q, p in zip(weights, targets, predictions, strict=True)) / sum(weights)

    # A fixed, predeclared one-dimensional fit; no test results select the bounds.
    low, high = math.log(0.05), math.log(20.0)
    ratio = (math.sqrt(5) - 1) / 2
    left, right = high - ratio * (high - low), low + ratio * (high - low)
    fl, fr = objective(left), objective(right)
    for _ in range(64):
        if fl < fr:
            high, right, fr = right, left, fl
            left = high - ratio * (high - low)
            fl = objective(left)
        else:
            low, left, fl = left, right, fr
            right = low + ratio * (high - low)
            fr = objective(right)
    candidates = [math.log(0.05), 0.0, (low + high) / 2, math.log(20.0)]
    best = min(candidates, key=objective)
    temperature = math.exp(best)
    return {"temperature": temperature, "bounds": [0.05, 20.0],
            "at_bound": temperature < 0.050001 or temperature > 19.99999,
            "calibration_soft_ce_before": objective(0.0),
            "calibration_soft_ce_after": objective(best),
            "objective": "soft CE; equal family, then source event, then prefix weight",
            "test_used": False, "policy_changed": False}


def reliability(items: list[tuple[float, float, float]]) -> dict:
    bins = [[0.0, 0.0, 0.0] for _ in range(10)]
    total = sum(weight for _, _, weight in items)
    for probability, target, weight in items:
        bucket = bins[min(9, int(probability * 10))]
        bucket[0] += weight
        bucket[1] += weight * probability
        bucket[2] += weight * target
    return {"ece": sum(abs(p - q) for _, p, q in bins) / total,
            "bins": [{"lower": i / 10, "upper": (i + 1) / 10,
                      "weight_fraction": w / total, "confidence": p / w if w else None,
                      "target": q / w if w else None}
                     for i, (w, p, q) in enumerate(bins)]}


def metrics(rows: list[dict], predictions: list[dict], temperature: float) -> dict:
    weights = event_weights(rows)
    total = sum(weights)
    sums: dict[str, float] = defaultdict(float)
    top_soft, top_accepted = [], []
    stops: dict[str, list] = {key: [] for key in ("stop_sufficient", "stop_exhausted")}
    strata: dict[str, list] = defaultdict(list)
    for row, prediction, weight in zip(rows, predictions, weights, strict=True):
        q = row["gold"]["next"]["probabilities"]
        logs = log_probabilities(prediction["logits"], temperature)
        probabilities = {key: math.exp(value) for key, value in logs.items()}
        choice = max(logs, key=logs.get)
        accepted = float(q.get(choice, 0) > 0)
        sums["soft_ce"] += weight * cross_entropy(q, logs)
        sums["target_entropy"] -= weight * sum(v * math.log(v) for v in q.values() if v)
        sums["brier"] += weight * sum((p - q.get(k, 0)) ** 2 for k, p in probabilities.items())
        sums["accepted_top"] += weight * accepted
        sums["acceptable_action_mass"] += weight * sum(probabilities[k] for k, v in q.items() if v)
        top_soft.append((probabilities[choice], q.get(choice, 0), weight))
        top_accepted.append((probabilities[choice], accepted, weight))
        for key, values in stops.items():
            values.append((probabilities[key], q.get(key, 0), weight))
            sums[key + "_brier"] += weight * (probabilities[key] - q.get(key, 0)) ** 2
        strata[row["metadata"]["label_status"]].append((accepted, weight))
    return {**{key: value / total for key, value in sums.items()},
            "states": len(rows), "families": len({r["metadata"]["family"] for r in rows}),
            "top_soft_target_reliability": reliability(top_soft),
            "top_accepted_reliability_diagnostic": reliability(top_accepted),
            "stop_reliability": {key: reliability(values) for key, values in stops.items()},
            "strata": {key: {"states": len(v), "accepted": sum(a for a, _ in v),
                             "weighted_acceptance": sum(a * w for a, w in v) / sum(w for _, w in v)}
                       for key, v in strata.items()}}


def paired_family_interval(rows: list[dict], predictions: list[dict], temperature: float) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for row, prediction in zip(rows, predictions, strict=True):
        groups[row["metadata"]["family"]].append((row, prediction))
    differences = []
    for values in groups.values():
        subset, outputs = map(list, zip(*values, strict=True))
        before = metrics(subset, outputs, 1.0)["soft_ce"]
        after = metrics(subset, outputs, temperature)["soft_ce"]
        differences.append(after - before)
    rng = random.Random(20261017)  # noqa: S311 -- reproducible statistical resampling
    samples = sorted(sum(rng.choices(differences, k=len(differences))) / len(differences)
                     for _ in range(2000))
    return {"metric": "soft CE after minus before", "families": len(groups),
            "difference": sum(differences) / len(differences),
            "percentile_95_interval": [samples[49], samples[1949]],
            "resamples": 2000, "seed": 20261017,
            "scope": "Family bootstrap conditional on this frozen calibrator and sampled corpus"}
