"""Promote only preregistered, fully read out development checkpoints."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from statistics import fmean
from typing import Any

from milai_lab.datasets.memory_control_report import read_json
from milai_lab.scorers.memory_control_episode_metrics import (
    input_result,
    paired_comparison,
    summarize,
)


def training_receipt(checkpoint: Path) -> Path:
    path = checkpoint.resolve(strict=True)
    if not (path / "config.json").is_file() or not (path / "weights.pt").is_file():
        raise ValueError(f"No complete checkpoint at {path}")
    for parent in (path.parent, path.parent.parent):
        receipt = parent / "run.json"
        if receipt.is_file():
            return receipt
    raise ValueError(f"No training receipt beside {checkpoint}")


def select_checkpoint(
    candidates: Sequence[Path], *, baseline: Path | None = None,
    lambda_tie_order: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Apply the registered epoch or lambda comparison to actual complete DEV readouts."""
    if not candidates or len(candidates) > (3 if baseline is not None else 2):
        raise ValueError("Use the registered one/two epoch points or three lambda points")
    rows = []
    population = receipt = None
    for path in candidates:
        protocol, records = input_result(path)
        observed = protocol["population"]
        arm = protocol["arm"]
        if (observed["role"] != "dev" or arm["policy"] != "checkpoint"
                or read_json(path / "run.json", {}).get("status") != "COMPLETED"
                or set(records) != {task["task_id"] for task in observed["tasks"]}):
            raise ValueError("Selection requires terminal results for all registered DEV tasks")
        checkpoint = Path(arm["checkpoint"])
        fit_receipt = training_receipt(checkpoint)
        if population is not None and (observed != population or fit_receipt != receipt):
            raise ValueError("Compare the same DEV population and training run")
        population, receipt = observed, fit_receipt
        run = read_json(fit_receipt)
        contract = run["contract"]
        if run["status"] != "COMPLETED":
            raise ValueError("Select after the registered fit has completed")
        if checkpoint.name.startswith("step-"):
            step = int(checkpoint.name.removeprefix("step-"))
        elif checkpoint.name == "checkpoint":
            step = run["final_step"]
        else:
            raise ValueError("Choose a trained first or terminal epoch")
        epoch = math.ceil(step / contract["steps_per_epoch"])
        if epoch not in {1, contract["epochs"]}:
            raise ValueError("Only a registered first or terminal epoch can be selected")
        metrics = summarize(path)
        macro = metrics["available_case_macro_quality_points"]
        if macro is None:
            raise ValueError("All native sources need an evaluable quality denominator")
        costs = [source["resource"].get("reader_input_tokens")
                 for source in metrics["sources"].values()]
        cost = fmean(item["mean"] for item in costs if item) if all(costs) else None
        rows.append({
            "checkpoint": str(checkpoint.resolve()), "epoch": epoch, "step": step,
            "dev_run": str(path.resolve()), "quality_points": macro,
            "reader_input_tokens": cost, "scored_all_tasks": metrics["score_complete"],
            "utility_lambda": arm.get("utility_lambda"),
            "stop": arm["stop"], "precision": arm["precision"],
            "observation_protocol": arm["observation_protocol"],
            "seed": contract["seed"],
        })
    arms = [(row["epoch"], row["utility_lambda"]) for row in rows]
    if len(set(arms)) != len(arms):
        raise ValueError("Each registered candidate must represent a distinct epoch/lambda point")

    def quality_order(row: dict[str, Any]) -> tuple[Any, ...]:
        cost = row["reader_input_tokens"]
        return (-row["quality_points"], math.inf if cost is None else cost, row["epoch"])

    if baseline is None:
        if len({row["utility_lambda"] for row in rows}) != 1:
            raise ValueError("Epoch comparison requires a common frozen lambda")
        winner = min(rows, key=quality_order)
        reason = "highest_dev_macro_quality_then_lowest_reader_input"
    else:
        if (len({row["epoch"] for row in rows}) != 1
                or {row["utility_lambda"] for row in rows} != {0.0, 0.05, 0.10}):
            raise ValueError("Lambda selection requires all three registered values at one epoch")
        assert population is not None
        for row in rows:
            paired = paired_comparison(
                [Path(row["dev_run"])], baseline, repeats=5000, seed=population["seed"],
                allow_derived_dev_roster=True,
            )
            interval = paired["quality_interval_95"]
            row["paired_quality_interval_95"] = interval
            row["quality_constraint_met"] = (
                interval is not None and interval[0] >= -population["quality_noninferiority_points"]
            )
        eligible = [row for row in rows if row["quality_constraint_met"]
                    and row["reader_input_tokens"] is not None]
        if lambda_tie_order is not None and (
            len(lambda_tie_order) != 3 or set(lambda_tie_order) != {0.0, 0.05, 0.10}
        ):
            raise ValueError("Declare one tie order for the three registered lambda points")
        if eligible:
            winner = min(eligible, key=lambda row: (
                row["reader_input_tokens"], -row["quality_points"], row["utility_lambda"],
            ))
            reason = "lowest_reader_input_with_dev_quality_constraint"
        else:
            winner = min(rows, key=quality_order)
            reason = "highest_dev_quality_without_established_quality_constraint"
        if lambda_tie_order is not None:
            pool = eligible or rows
            if eligible:
                optimum = min(row["reader_input_tokens"] for row in pool)
                pool = [row for row in pool if row["reader_input_tokens"] <= optimum + 1e-8]
            quality = max(row["quality_points"] for row in pool)
            pool = [row for row in pool if row["quality_points"] >= quality - 1e-8]
            if not eligible and (costs := [row["reader_input_tokens"] for row in pool
                                           if row["reader_input_tokens"] is not None]):
                cutoff = min(costs) + 1e-8
                pool = [row for row in pool if row["reader_input_tokens"] is not None
                        and row["reader_input_tokens"] <= cutoff]
            winner = min(pool, key=lambda row: lambda_tie_order.index(row["utility_lambda"]))
    return {
        "status": "SELECTED_DEV_CHECKPOINT", "role": "dev", "selection_rule": reason,
        "selected_checkpoint": winner["checkpoint"], "selected": winner, "candidates": rows,
    }


def selected_candidate(selection: Path) -> dict[str, Any]:
    record = read_json(selection)
    if record.get("status") != "SELECTED_DEV_CHECKPOINT" or record.get("role") != "dev":
        raise ValueError("Expected a registered DEV checkpoint selection")
    selected = record["selected"]
    if (record["selected_checkpoint"] != selected["checkpoint"]
            or selected not in record["candidates"]):
        raise ValueError("Selection has inconsistent checkpoint identity")
    training_receipt(Path(selected["checkpoint"]))
    return dict(selected)
