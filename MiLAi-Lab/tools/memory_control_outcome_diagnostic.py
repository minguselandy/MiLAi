"""Compare matched supervision runs on their common measured DEV actions."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean
from typing import Any

from memory_control_representation_screen import verify_matched_initial
from milai_lab.datasets.memory_control_report import read_json


def _update_schedule(run: Path) -> list[tuple[int, int, int, float]]:
    return [
        (row["step"], row["epoch"], row["states"], row["lr_next_step"])
        for row in map(json.loads, (run / "steps.jsonl").read_text().splitlines())
    ]


def verify_added_outcome_supervision(
    reference: Path, candidate: Path, candidate_outcomes: list[str],
) -> dict[str, Any]:
    """Verify an added-label contrast while retaining the same TRAIN population and schedule."""
    receipts = [read_json(run / "run.json") for run in (reference, candidate)]
    if any(r["status"] != "COMPLETED" for r in receipts):
        raise ValueError("The supervision comparison requires two completed fits")
    a, b = (r["contract"] for r in receipts)
    shared = a["outcome_runs"]
    if (a["supervision_mode"] != "outcome" or not shared or b["outcome_runs"] != candidate_outcomes
            or b["outcome_runs"][:len(shared)] != shared or len(candidate_outcomes) <= len(shared)
            or b["outcome_protocols"][:len(shared)] != a["outcome_protocols"]):
        raise ValueError("The candidate must retain the original outcomes and append measured runs")
    varying = {"outcome_runs", "outcome_protocols"}
    if {k: v for k, v in a.items() if k not in varying} != {
        k: v for k, v in b.items() if k not in varying
    }:
        raise ValueError("The supervision arms use different training or held DEV contracts")

    coverage = [read_json(run / "coverage.json") for run in (reference, candidate)]
    if any(not item["full_coverage"] for item in coverage):
        raise ValueError("Both supervision arms require complete training coverage")
    counts = ("eligible_states", "full_epochs", "total_optimizer_updates", "total_states_exposed")
    if any(coverage[0][key] != coverage[1][key] for key in counts):
        raise ValueError("The supervision arms have unequal training exposure")
    if (coverage[0]["eligible_states"] != len(a["eligible_states"])
            or coverage[0]["full_epochs"] != a["epochs"]
            or coverage[0]["total_optimizer_updates"] != a["steps"]):
        raise ValueError("Completed exposure differs from the common fit contract")
    schedule = _update_schedule(reference)
    if (len(schedule) != coverage[0]["total_optimizer_updates"]
            or sum(row[2] for row in schedule) != coverage[0]["total_states_exposed"]
            or schedule != _update_schedule(candidate)):
        raise ValueError("The supervision arms have different completed update schedules")
    return {
        "training_reader_outcomes_reference": shared,
        "training_reader_outcomes_candidate": candidate_outcomes,
        "matched_initial_head_tensors": verify_matched_initial(reference, candidate),
        **{key: coverage[0][key] for key in counts},
    }


def _held_actions(path: Path) -> list[tuple[str, str, list[str]]]:
    return [
        (row["sample_id"], row["group_id"], row["actions"])
        for row in map(json.loads, (path / "predictions.jsonl").read_text().splitlines())
    ]


def _source_diagnostics(summary: dict[str, Any], actions: dict[str, Any]) -> dict[str, Any]:
    cost_count = sum(row["provider_input_measured"] for row in actions.values())
    cost_error = sum(
        row["provider_input_measured"] * row["input_tokens_mae"]
        for row in actions.values() if row["provider_input_measured"]
    )
    pairs = summary.get("observed_delta_pairs", 0)
    return {
        "quality_mse": summary.get("observed_value_brier"),
        "observed_delta_mse": (
            summary["observed_delta_error_squared_sum"] / pairs if pairs else None
        ),
        "provider_input_mae_tokens": cost_error / cost_count if cost_count else None,
        "observed_top1_coverage": summary.get("observed_choice_coverage"),
    }


def compare_held_calibration(
    reference: Path, candidate: Path, *, utility_lambda: float,
) -> dict[str, Any]:
    """Describe calibration deltas on identical measured DEV support without selecting a model."""
    paths = (reference, candidate)
    receipts = [read_json(p / "run.json") for p in paths]
    if any(r["status"] != "COMPLETED" or r["reader_calls"] or r["source_overlap"]
           or not r["dev_outcome_runs"] for r in receipts):
        raise ValueError("Calibration comparison needs complete held DEV-only evaluations")
    for key in ("data", "dev_outcome_runs", "states", "groups"):
        if receipts[0][key] != receipts[1][key]:
            raise ValueError(f"Calibration cohorts differ in {key}")
    actions = _held_actions(reference)
    if (len(actions) != len({row[0] for row in actions}) or len(actions) != receipts[0]["states"]
            or actions != _held_actions(candidate)):
        raise ValueError("Calibration evaluations have different before-state menus or groups")

    results = [read_json(p / "result.json") for p in paths]
    cals = [r["outcome_calibration"] for r in results]
    if any(c["utility_lambda"] != utility_lambda for c in cals):
        raise ValueError("Both calibration evaluations require the registered utility lambda")
    by_action = [c["by_dataset_and_action"] for c in cals]
    support = [
        {source: {action: tuple(row[key] for key in (
            "offered", "quality_measured", "provider_input_measured",
        )) for action, row in table.items()} for source, table in groups.items()}
        for groups in by_action
    ]
    if not support[0] or support[0] != support[1]:
        raise ValueError("The measured quality or cost support changed between evaluations")
    by_source = {}
    for source in sorted(support[0]):
        paired_support = [r["by_dataset"][source].get("observed_delta_pairs", 0) for r in results]
        if paired_support[0] != paired_support[1]:
            raise ValueError("Held paired quality support changed between evaluations")
        a, b = [_source_diagnostics(r["by_dataset"][source], g[source])
                for r, g in zip(results, by_action, strict=True)]
        by_source[source] = {
            "reference": a, "candidate": b,
            "candidate_minus_reference": {
                key: b[key] - a[key] if a[key] is not None and b[key] is not None else None
                for key in a
            },
        }
    absolute_fields = ("reference", "candidate", "candidate_minus_reference")
    macro = {}
    for field in absolute_fields:
        sources = [row[field] for row in by_source.values()]
        macro[field] = {
            key: (fmean(s[key] for s in sources)
                  if all(s[key] is not None for s in sources) else None)
            for key in sources[0]
        }
    return {
        "scope": "Same recorded held DEV actions and source-macro calibration",
        "reference_evaluation": str(reference), "candidate_evaluation": str(candidate),
        "states": receipts[0]["states"], "native_groups": receipts[0]["groups"],
        "utility_lambda": utility_lambda, "by_source": by_source, "source_macro": macro,
        "selection_use": "none", "reader_requests": 0, "sha_validation": False,
    }
