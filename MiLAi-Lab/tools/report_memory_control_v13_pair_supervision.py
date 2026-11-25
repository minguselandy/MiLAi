"""Measure label support and scalar coefficients of a closed paired fit, before clipping."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import torch

from diagnose_memory_control_v13_evidence import native_deltas
from milai_lab.datasets.memory_control_report import write_json
from milai_lab.methods.pretrained_objective import group_weights, root_loss
from milai_lab.runners.pretrained_control_train import TrainingRoots


def sign(value):
    return "positive" if value > 0 else "negative" if value < 0 else "tie"


def measure(directory, packs, penalty):
    receipt = json.loads((directory / "run.json").read_text())
    c = receipt["contract"]
    if (
        receipt["status"] != "completed"
        or not receipt["reload_scores_equal"]
        or c["supervision_mode"] != "paired"
        or c["input"] != str([packs])
    ):
        raise ValueError("Expected a closed paired fit on the supplied data")
    roots = TrainingRoots(SimpleNamespace(objective="paired", data=[packs]))
    weights, batch_size = c["source_weights"], c["effective_batch"]
    cells = defaultdict(Counter)
    control = Counter()
    for epoch in range(c["epochs"]):
        rng = random.Random(c["seed"] + epoch)  # noqa: S311 -- reproduce the registered fit
        order = list(roots.epoch(rng, weights))[: c["selected_per_epoch"]]
        counts = Counter((source, group) for _, source, group in order)
        groups = Counter(source for source, _ in counts)
        mass = sum(weights[source] for source in groups)
        for offset in range(0, len(order), batch_size):
            batch = order[offset : offset + batch_size]
            for key, source, group in batch:
                row = roots.row(key)
                outcomes = {o["first_action_id"]: o for o in row["outcomes"]}
                pairs = [
                    (a, b)
                    for a, b in row["comparisons"]
                    if all(act in outcomes and outcomes[act]["quality_observed"] for act in (a, b))
                ]
                heads = group_weights(c["seed"], f"{source}/{group}")
                root_weight = (
                    weights[source]
                    * len(order)
                    / (mass * groups[source] * counts[source, group] * len(batch))
                )
                control["roots"] += 1
                expected = 0.0
                for a, b in pairs:
                    delta = outcomes[a]["reader_quality"] - outcomes[b]["reader_quality"]
                    reliability = min(1.0, abs(delta) / 0.05)
                    weight = root_weight * c["pair_weight"] * reliability / len(pairs)
                    if "handoff" in (a, b):
                        read = a if b == "handoff" else b
                        measured = native_deltas(outcomes, read, penalty, c["cost_scale"])
                        category = (
                            "read_minus_handoff/"
                            + sign(measured["quality"])
                            + "/"
                            + (sign(measured["utility"]) if "utility" in measured else "unknown")
                        )
                    else:
                        category = "other_predefined_pair"
                    cell = cells[source, category]
                    cell["exposures"] += 1
                    cell["nonzero_reliability_exposures"] += int(reliability > 0)
                    cell["scalar_mass"] += weight
                    # At a zero predicted difference the native Huber loss is delta^2/2.
                    expected += weight * 0.5 * delta**2
                # Subtract the direct objective to isolate the paired term.
                zeros = torch.zeros((len(row["online"]["actions"]), 4), dtype=torch.float64)
                args = row, zeros, zeros, heads, c["cost_scale"]
                paired, n = root_loss(*args, pair_weight=c["pair_weight"])
                direct, _ = root_loss(*args, pair_weight=0.0)
                if n != len(pairs) or abs(float(paired - direct) * root_weight - expected) > 1e-10:
                    raise ValueError("Reconstruction differs from the fitted root objective")
                control["observed_pair_exposures"] += n
    if (control["roots"], control["observed_pair_exposures"]) != (
        receipt["roots"],
        receipt["paired_loss_comparisons"],
    ):
        raise ValueError("Label accounting and native fit exposure differ")
    total = sum(row["scalar_mass"] for row in cells.values())
    return dict(
        input_directory=str(packs),
        fit=str(directory),
        epochs=c["epochs"],
        seed=c["seed"],
        cost_scale=c["cost_scale"],
        utility_lambda=penalty,
        pair_weight=c["pair_weight"],
        coverage=control,
        total_pair_scalar_mass=total,
        cells=[
            dict(
                source=s,
                category=k,
                **v,
                share_of_pair_scalar_mass=v["scalar_mass"] / total if total else None,
            )
            for (s, k), v in sorted(cells.items())
        ],
        model_forwards=0,
        reader_calls=0,
        optimizer_updates=0,
        scope=(
            "Pre-clipping scalar coefficients summed over registered fitting exposures "
            "and the four normalized heads. These do not measure gradients or parameter updates."
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("fit", "packs", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--utility-lambda", type=float, required=True)
    options = parser.parse_args()
    write_json(options.output, measure(options.fit, options.packs, options.utility_lambda))
