"""Measure conditional reading and stopping from durable paired Reader outcomes."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from statistics import fmean
from typing import Any

from milai_lab.datasets.memory_control_report import write_json
from milai_lab.datasets.memory_control_store import connect, unpack
from milai_lab.scorers.memory_control_episode_metrics import percentiles


@dataclass(frozen=True)
class Branch:
    action_id: str
    kind: str
    parameters: dict[str, Any]
    status: str
    wire: dict[str, Any] | None
    quality: float | None
    provider_input_tokens: int | None

    @classmethod
    def read(cls, row: sqlite3.Row) -> Branch:
        action = unpack(row["bound_action"])
        status = row["execution_status"]
        if status != "ingested" or row["training_quality"] is None:
            return cls(
                row["action_id"], action["kind"], action["parameters"], status, None, None, None
            )
        staged = unpack(row["task_result"])
        result = staged.get("reader_result") or {}
        wire = staged.get("reader_wire")
        if result.get("status") != "reader_completed" or not isinstance(wire, dict) or not wire:
            raise ValueError("Ingested quality requires an actual Reader reply and request")
        costs = unpack(row["costs"])
        tokens = costs.get("reader_input_tokens")
        return cls(
            row["action_id"],
            action["kind"],
            action["parameters"],
            status,
            wire,
            float(row["training_quality"]),
            tokens
            if costs.get("reader_usage_source") == "provider"
            and type(tokens) is int
            and tokens >= 0
            else None,
        )


@dataclass(frozen=True)
class Pair:
    state_id: int
    group: str
    budget: int
    sampling_origin: str
    actions: tuple[str, str]
    branch_statuses: tuple[str, str]
    identical_wire: bool | None
    quality_delta: float | None
    provider_input_delta: float | None

    @classmethod
    def compare(cls, before: sqlite3.Row, action: Branch, reference: Branch) -> Pair:
        measured = action.quality is not None and reference.quality is not None
        action_tokens = action.provider_input_tokens
        reference_tokens = reference.provider_input_tokens
        return cls(
            before["state_id"],
            before["native_group"],
            before["material_budget"],
            before["sampling_origin"],
            (action.action_id, reference.action_id),
            (action.status, reference.status),
            action.wire == reference.wire if measured else None,
            action.quality - reference.quality
            if action.quality is not None and reference.quality is not None
            else None,
            float(action_tokens - reference_tokens)
            if action_tokens is not None and reference_tokens is not None
            else None,
        )


def _cluster_metric(
    pairs: list[Pair], values: list[float | None], repeats: int, seed: int
) -> dict[str, Any]:
    bindings: dict[tuple[str, int, tuple[str, str]], list[float]] = defaultdict(list)
    for pair, value in zip(pairs, values, strict=True):
        if value is not None:
            bindings[pair.group, pair.state_id, pair.actions].append(value)
    grouped: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (group, state, _), measurements in bindings.items():
        grouped[group][state].append(fmean(measurements))
    means = [fmean(fmean(values) for values in states.values()) for states in grouped.values()]
    interval = None
    if len(means) > 1 and repeats:
        rng = random.Random(seed)  # noqa: S311 -- declared native-group bootstrap
        draws = [fmean(rng.choices(means, k=len(means))) for _ in range(repeats)]
        interval = [percentiles(draws, probability) for probability in (0.025, 0.975)]
    return {
        "independent_groups": len(means),
        "matched_before_states": sum(len(states) for states in grouped.values()),
        "mean": fmean(means) if means else None,
        "interval_95": interval,
    }


def _summarize(pairs: list[Pair], repeats: int, seed: int) -> dict[str, Any]:
    measured = [p for p in pairs if p.quality_delta is not None]
    changed = [p for p in measured if p.identical_wire is False]
    changed_deltas = [p.quality_delta for p in changed if p.quality_delta is not None]
    same = [p for p in measured if p.identical_wire is True]
    raw = [100 * p.quality_delta if p.quality_delta is not None else None for p in pairs]
    shared = [0.0 if p.identical_wire else q for p, q in zip(pairs, raw, strict=True)]
    by_binding: dict[tuple[int, tuple[str, str]], list[float]] = defaultdict(list)
    for pair, quality in zip(pairs, shared, strict=True):
        if quality is not None:
            by_binding[pair.state_id, pair.actions].append(quality)
    repeated = [values for values in by_binding.values() if len(values) > 1]
    return {
        "configured_pairs": len(pairs),
        "measured_pairs": len(measured),
        "different_terminal_requests": len(changed),
        "identical_terminal_requests": len(same),
        "identical_requests_with_raw_quality_disagreement": sum(p.quality_delta != 0 for p in same),
        "bindings_with_repeated_measurements": len(repeated),
        "repeated_bindings_with_opposed_quality_directions": sum(
            min(values) < 0 < max(values) for values in repeated
        ),
        "branch_status_pairs": dict(Counter("/".join(p.branch_statuses) for p in pairs)),
        "sampling_origins": dict(Counter(p.sampling_origin for p in pairs)),
        "different_request_raw_directions": {
            "improved": sum(q > 0 for q in changed_deltas),
            "tied": sum(q == 0 for q in changed_deltas),
            "decreased": sum(q < 0 for q in changed_deltas),
        },
        "raw_training_quality_delta_points": _cluster_metric(pairs, raw, repeats, seed),
        "shared_request_quality_delta_points": _cluster_metric(pairs, shared, repeats, seed),
        "provider_input_token_delta": _cluster_metric(
            pairs, [p.provider_input_delta for p in pairs], repeats, seed
        ),
    }


def report(db: sqlite3.Connection, run_id: str, *, repeats: int, seed: int) -> dict[str, Any]:
    row = db.execute("SELECT config FROM outcome_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown outcome run {run_id}")
    declaration = json.loads(row[0])
    role = declaration["role"]
    if role not in {"train", "dev"}:
        raise ValueError("Branch contrasts require a declared TRAIN or DEV run")
    rows = db.execute(
        """
        SELECT o.state_id,o.action_id,o.repeat_index,o.branch_seed,o.bound_action,
               o.execution_status,o.training_quality,o.task_result,o.costs,o.sampling_origin,
               t.id AS task_id,t.dataset,t.native_group,t.experiment_role,v.material_budget
        FROM action_outcomes o JOIN states s ON s.id=o.state_id
        JOIN experiment_tasks t ON t.id=s.task_id
        JOIN state_variants v ON v.state_id=s.id
        WHERE o.run_id=? ORDER BY o.state_id,o.repeat_index,o.action_id
    """,
        (run_id,),
    )
    axes = ("R3_minus_R2", "READ_minus_HANDOFF")
    contrasts: dict[str, dict[str, list[Pair]]] = defaultdict(lambda: {a: [] for a in axes})
    statuses: Counter[str] = Counter()
    observed_states: set[int] = set()
    observed_tasks: set[int] = set()
    observed_groups: dict[str, set[str]] = defaultdict(set)
    for _, batch in groupby(rows, key=lambda r: (r["state_id"], r["repeat_index"])):
        placed = list(batch)
        before = placed[0]
        if before["experiment_role"] != role or len({r["branch_seed"] for r in placed}) != 1:
            raise ValueError("Paired branches must share the declared role and repeat seed")
        source = contrasts[before["dataset"]]
        statuses.update(r["execution_status"] for r in placed)
        observed_states.add(before["state_id"])
        observed_tasks.add(before["task_id"])
        observed_groups[before["dataset"]].add(before["native_group"])
        branches = [Branch.read(r) for r in placed]
        reads = [b for b in branches if b.kind == "READ"]
        handoff = next((b for b in branches if b.kind == "HANDOFF"), None)
        for read in reads:
            if handoff is not None:
                source["READ_minus_HANDOFF"].append(Pair.compare(before, read, handoff))
            if not read.parameters.get("expand_context"):
                continue
            focus_binding = {k: v for k, v in read.parameters.items() if k != "expand_context"}
            focus = next(
                (
                    b
                    for b in reads
                    if not b.parameters.get("expand_context")
                    and {k: v for k, v in b.parameters.items() if k != "expand_context"}
                    == focus_binding
                ),
                None,
            )
            if focus is not None:
                source["R3_minus_R2"].append(Pair.compare(before, read, focus))
    by_source = {}
    for source_name, axes_by_source in sorted(contrasts.items()):
        entries = {}
        for axis, pairs in axes_by_source.items():
            budgets: dict[int, list[Pair]] = defaultdict(list)
            for pair in pairs:
                budgets[pair.budget].append(pair)
            entries[axis] = {
                **_summarize(pairs, repeats, seed),
                "by_material_budget": {
                    budget: _summarize(selected, repeats, seed)
                    for budget, selected in sorted(budgets.items())
                },
            }
        by_source[source_name] = entries
    return {
        "run_id": run_id,
        "role": role,
        "sealed": declaration["sealed"],
        "comparison_protocol": declaration["comparison_protocol"],
        "state_count": len(observed_states),
        "task_count": len(observed_tasks),
        "independent_groups_by_source": {k: len(v) for k, v in observed_groups.items()},
        "branch_status_counts": dict(statuses),
        "quality_scope": "per-branch scorer training quality from actual Reader outcomes",
        "quality_sensitivity": "identical literal terminal Reader inputs contribute zero delta",
        "mean_weighting": (
            "average repeats per bound pair, bound pairs per state, states per native group"
        ),
        "bootstrap_repeats": repeats,
        "bootstrap_seed": seed,
        "by_source": by_source,
        "reader_requests_in_report": 0,
        "sha_validation": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-repeats", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()
    if args.bootstrap_repeats < 1:
        parser.error("use a positive bootstrap repeat count")
    with closing(connect(args.data)) as db:
        db.execute("BEGIN")
        result = report(db, args.run_id, repeats=args.bootstrap_repeats, seed=args.seed)
    write_json(args.output, result)
    print(f"Paired outcome report at {args.output}")


if __name__ == "__main__":
    main()
