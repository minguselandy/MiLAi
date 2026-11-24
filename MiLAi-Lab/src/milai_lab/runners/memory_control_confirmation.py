"""Allocate fresh native groups and model confirmation precision from DEV outcomes."""

from __future__ import annotations

import random
from collections import Counter, defaultdict, deque
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_episode_archive import episode_packet_exists
from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import read_json
from milai_lab.datasets.memory_control_store import connect, get_meta
from milai_lab.runners.memory_control_episode import allocate_native_groups
from milai_lab.scorers.memory_control_episode_metrics import (
    SOURCES,
    _primary_group_quality,
    centered_bootstrap_pvalue,
    input_result,
    matching_derived_dev,
    select_dev_records,
)


class InsufficientDevGroups(ValueError):
    """DEV has too few observed native clusters for the planned variance simulation."""


def confirmation_capacity(
    data: Path, target_tasks: int, seed: int, exposure_runs: list[Path],
) -> dict[str, Any]:
    if target_tasks <= 0:
        raise ValueError("Provide a positive confirmation capacity target")
    exposed: set[tuple[str, str]] = set()
    for path in exposure_runs:
        protocol = read_json(path / "protocol.json")
        population = protocol["population"]
        if population["role"] != "confirm":
            raise ValueError("Supply protected historical readout roots for exposure accounting")
        archived = read_json(path / "episode-archive.json", {})
        complete = read_json(path / "run.json", {}).get("status") == "COMPLETED" or (
            archived.get("status") == "ARCHIVED_COMPLETED_EPISODES"
            and archived.get("episodes") == len(population["tasks"])
        )
        exposed.update(
            (task["dataset"], task["native_group"]) for task in population["tasks"]
            if complete or episode_packet_exists(path / "episodes" / f"{task['task_id']}.json")
        )
    eligible: dict[str, list[tuple[str, int]]] = defaultdict(list)
    with closing(connect(data)) as db:
        run_id = get_meta(db, "run_id")
        for source, group, size in db.execute("""
            SELECT t.dataset,t.native_group,count(*) FROM experiment_tasks t
            JOIN experiment_groups g USING(dataset,native_group)
            WHERE t.experiment_role='confirm' AND g.eligible_fresh_confirmation=1
            GROUP BY t.dataset,t.native_group ORDER BY t.dataset,t.native_group
        """):
            if (source, group) not in exposed:
                eligible[source].append((group, size))
    if set(eligible) != set(SOURCES):
        raise ValueError("The fresh confirmation registry lacks a native source")
    selected: dict[str, list[tuple[str, int]]] = defaultdict(list)
    sizes = {source: dict(groups) for source, groups in eligible.items()}
    for source, group in allocate_native_groups(sizes, target_tasks, seed):
        selected[source].append((group, sizes[source][group]))
    if set(selected) != set(SOURCES):
        raise ValueError("The confirmation target must admit every native source")
    n = sum(size for groups in selected.values() for _, size in groups)
    return {
        "dataset_run_id": run_id, "seed": seed, "target_tasks": target_tasks,
        "actual_tasks": n, "eligible_source_capacity": {
            source: {"native_groups": len(groups), "tasks": sum(size for _, size in groups)}
            for source, groups in eligible.items()
        },
        "selected_groups": {
            source: [{"native_group": group, "tasks": size} for group, size in groups]
            for source, groups in selected.items()
        },
        "exposure_run_roots": [str(path.resolve()) for path in exposure_runs],
        "excluded_exposed_native_groups": sorted(exposed), "confirm_labels_read": 0,
        "confirm_reader_requests": 0, "sha_validation": False,
    }


def confirmation_repeat_population(
    population: dict[str, Any], primary_plan: Path, *, reader_cap: int,
) -> dict[str, Any]:
    """Register a bounded repeat subset using complete native groups from the first draw."""
    if population["role"] != "confirm" or not population.get("arms"):
        raise ValueError("Repeats require a locked confirmation population")
    if population.get("measurement_repeat_of"):
        raise ValueError("Repeats must use the first frozen confirmation population")
    tasks = population["tasks"]
    arms = len(population["arms"])
    remaining = min(len(tasks) // 10, reader_cap // arms - len(tasks))
    if remaining < 0:
        raise ValueError("The primary confirmation cohort exceeds the registered budget")
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for task in tasks:
        groups[task["dataset"]][task["native_group"]] += 1
    rng = random.Random(population["seed"] + 1)  # noqa: S311 -- frozen repeat allocation
    queues: dict[str, deque[str]] = {}
    for source in sorted(groups):
        order = sorted(groups[source])
        rng.shuffle(order)
        queues[source] = deque(order)
    selected: set[tuple[str, str]] = set()
    while remaining and any(queues.values()):
        for source, queue in queues.items():
            while queue:
                group = queue.popleft()
                size = groups[source][group]
                if size <= remaining:
                    selected.add((source, group))
                    remaining -= size
                    break
    repeated = [r for r in tasks if (r["dataset"], r["native_group"]) in selected]
    ids = {str(r["task_id"]) for r in repeated}
    return {
        **population, "tasks": repeated, "target_tasks": len(repeated),
        "task_counts": dict(Counter(r["dataset"] for r in repeated)),
        "seed": population["seed"] + 104729,
        "predeclared_unevaluable_tasks": {
            t: why for t, why in population.get("predeclared_unevaluable_tasks", {}).items()
            if str(t) in ids
        },
        "measurement_repeat_of": str(primary_plan.resolve()),
        "primary_plus_repeat_slots": arms * (len(tasks) + len(repeated)),
    }


def full_tune_parent(roster: dict[str, Any] | None) -> dict[str, Any] | None:
    if roster is None:
        return None
    kind = roster.get("subset_kind")
    if kind is None:
        parent = roster
    elif kind == "frozen_fit_repeat" and roster.get("parent_tune_roster"):
        parent = read_json(Path(roster["parent_tune_roster"]))
    else:
        raise ValueError("Unrecognized frozen fit-repeat cohort or missing parent TUNE roster")
    if (not parent or parent.get("subset_kind") is not None or any(
        p.get("role") != "dev" or p.get("v13_role") != "tune" or p.get("material_budget") != 2048
        for p in (parent, roster)
    )):
        raise ValueError("Fit-repeat support and its parent must both be natural TUNE")
    # Check ordered group membership and the public mask using only registered task metadata.
    # This also validates a subset run whose own protocol never contained its omitted siblings.
    if roster is not parent:
        task_metadata = {t["task_id"]: t for t in parent["tasks"]}
        select_dev_records({"population": parent}, task_metadata, roster)
    return parent


def power_dev_records(
    path: Path, roster: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    metadata_path = path / "protocol.json"
    original = (read_json(metadata_path) or {}).get("population", {})
    if original and (original.get("role") != "dev" or original.get("v13_role") == "calibration"):
        raise ValueError("Confirmation power may read only natural TUNE or legacy DEV records")
    if roster is None:
        return input_result(path)
    # Reject a wrong registration before accessing any episode packets.
    if not original or original.get("v13_role") != "tune":
        raise ValueError("Projected confirmation power requires natural TUNE runs")
    parent = full_tune_parent(roster)
    if original != roster and original != parent:
        raise ValueError("A projected run must match the registered subset or its parent TUNE")
    protocol, episodes = input_result(path)
    return select_dev_records(protocol, episodes, roster)


def plan_confirmation_power(
    capacity: dict[str, Any],
    policy: list[Path],
    baseline: Path | Sequence[Path],
    *,
    draws: int,
    repeats: int,
    analysis_seed: int,
    primary_comparisons: int,
    holm_plan: bool = False,
    cost_field: str = "reader_input_tokens",
    minimum_quality_effect: float | None = None,
    mask_unknown_quality: bool = False,
    savings_null: float = 0.0,
    total_workload_cost: bool = False,
    tune_subset: Path | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sample clustered DEV residuals into the candidate fresh source/group allocation."""
    import numpy as np

    dev_roster = read_json(tune_subset) if isinstance(tune_subset, Path) else tune_subset
    if tune_subset is not None and not isinstance(dev_roster, dict):
        raise ValueError("Missing frozen TUNE subset declaration")
    if min(draws, repeats, primary_comparisons) <= 0 or len(policy) != 3:
        raise ValueError("Power uses three actual DEV seeds and positive simulation settings")
    baselines = [baseline] if isinstance(baseline, Path) else list(baseline)
    if len(baselines) not in {1, 3}:
        raise ValueError("Power requires one fixed or three seed-matched DEV baselines")
    comparison_runs = [power_dev_records(path, dev_roster) for path in baselines]
    base_protocol = comparison_runs[0][0]
    population = base_protocol["population"]
    if population["role"] != "dev":
        raise ValueError("Review only DEV responses for power planning")
    loaded = [power_dev_records(path, dev_roster) for path in policy]
    seeds = [protocol["arm"].get("seed") for protocol, _ in loaded]
    baseline_seeds = [protocol["arm"].get("seed") for protocol, _ in comparison_runs]
    if len(comparison_runs) == 3 and set(baseline_seeds) != set(seeds):
        raise ValueError("Baseline DEV seeds differ from the training seeds")
    base_by_seed = dict(zip(baseline_seeds, (rows for _, rows in comparison_runs), strict=True))
    fixed_records = (
        [comparison_runs[0][1]] * len(loaded) if len(comparison_runs) == 1
        else [base_by_seed[s] for s in seeds]
    )
    if set(seeds) != {11, 29, 47} or any(
        not (protocol["population"] == population
             or matching_derived_dev(population, protocol["population"]))
        for protocol, _ in [*loaded, *comparison_runs]
    ):
        raise ValueError("Power requires the same DEV task groups for actual seeds 11/29/47")
    reader_keys = base_protocol["comparison"].keys() - {"observation", "continuation"}
    if any(
        any(protocol["comparison"].get(k) != base_protocol["comparison"][k] for k in reader_keys)
        for protocol, _ in [*loaded, *comparison_runs]
    ):
        raise ValueError("Power requires a common Reader, tokenizer and scoring protocol")
    by_group: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for task in population["tasks"]:
        if str(task["task_id"]) not in population.get("predeclared_unevaluable_tasks", {}):
            by_group[task["dataset"]][task["native_group"]].append(task["task_id"])
    profiles: dict[str, list[tuple[int, list[tuple[float, float, float]]]]] = defaultdict(list)
    for source, groups in by_group.items():
        for ids in groups.values():
            records_by_arm = [[records.get(t, {}) for t in ids]
                              for records in [*fixed_records, *(rows for _, rows in loaded)]]
            qualities = [
                _primary_group_quality(source, records, failure_zero=not mask_unknown_quality)
                for records in records_by_arm
            ]
            costs = [[r.get("costs", {}).get(cost_field) for r in records]
                     for records in records_by_arm]
            if cost_field == "reader_input_tokens":
                measured = all(type(c) is int for row in costs for c in row)
            else:
                measured = all(
                    type(c) in (int, float) and np.isfinite(c) and c >= 0
                    for row in costs for c in row
                )
            if not all(qualities) or not measured:
                continue
            n = len(seeds)
            profiles[source].append((len(ids), [
                (100 * (float(np.mean(q)) - float(np.mean(bq))),
                 float(np.mean(c)), float(np.mean(bc)))
                for q, c, bq, bc in zip(
                    qualities[n:], costs[n:], qualities[:n], costs[:n], strict=True,
                )
            ]))
    if set(profiles) != set(SOURCES) or any(len(values) < 2 for values in profiles.values()):
        raise InsufficientDevGroups(
            "Actual DEV outcomes need multiple measured groups per native source"
        )

    alternatives = [(0.0, 0.20), (0.0, 0.15), (-0.5, 0.20), (-1.0, 0.20), (-2.0, 0.20)]
    passes: Counter[tuple[float, float]] = Counter()
    rng = np.random.default_rng(analysis_seed)
    arrays = {source: np.array([record for _, record in values], dtype=float)
              for source, values in profiles.items()}
    source_sizes = {source: np.array([size for size, _ in values])
                    for source, values in profiles.items()}
    confirm_sizes = {source: np.array([g["tasks"] for g in capacity["selected_groups"][source]])
                     for source in SOURCES}
    neighbors = {
        source: [np.flatnonzero(abs(sizes - size) == abs(sizes - size).min())
                 for size in confirm_sizes[source]]
        for source, sizes in source_sizes.items()
    }
    cost_mass = {s: float(confirm_sizes[s].sum()) if total_workload_cost else 1.0 for s in SOURCES}
    dev_points = np.zeros((len(seeds), 3))
    for source in SOURCES:
        sizes = source_sizes[source]
        q_weights = np.ones(len(sizes)) if source == MUSIQUE else sizes
        dev_points[:, 0] += np.average(arrays[source][:, :, 0], axis=0, weights=q_weights)
        for axis in (1, 2):
            dev_points[:, axis] += cost_mass[source] * np.average(
                arrays[source][:, :, axis], axis=0, weights=sizes)
    dev_quality = dev_points[:, 0] / len(SOURCES)
    dev_savings = 1 - dev_points[:, 1] / dev_points[:, 2]
    conservative_quality, conservative_savings = float(min(dev_quality)), float(min(dev_savings))
    superiority_passes = advantage_passes = minimum_effect_passes = 0
    alpha = 0.025 / primary_comparisons
    interval_alpha = 0.025 if holm_plan else alpha

    def fits_family(
        quality_test: tuple[Any, float], cost_test: tuple[Any, float] | None = None,
    ) -> bool:
        if not holm_plan:
            return True
        # First Holm rank is conservative for unknown sibling effects.
        q_draws, q_estimate = quality_test
        q_p = centered_bootstrap_pvalue(q_draws, q_estimate, 0.0 if cost_test is None else -1.0)
        cost_p = centered_bootstrap_pvalue(*cost_test, savings_null) if cost_test is not None else 0
        return bool(max(q_p, cost_p) <= alpha)

    for _ in range(draws):
        seed_draw = rng.integers(0, len(policy), size=len(policy))
        reference = np.zeros(3)
        bootstrap = np.zeros((repeats, 3))
        for source in SOURCES:
            sizes = source_sizes[source]
            values = arrays[source][:, seed_draw].mean(axis=1)
            all_seeds = arrays[source].mean(axis=1)
            target = confirm_sizes[source]
            simulated = values[[rng.choice(indices) for indices in neighbors[source]]]
            q_weights = np.ones(len(target)) if source == MUSIQUE else target
            raw_q_weights = np.ones(len(sizes)) if source == MUSIQUE else sizes
            simulated[:, 0] -= np.average(all_seeds[:, 0], weights=raw_q_weights)
            simulated[:, 1] -= np.average(all_seeds[:, 1] - all_seeds[:, 2], weights=sizes)
            reference += [np.average(simulated[:, 0], weights=q_weights),
                          cost_mass[source] * np.average(simulated[:, 1], weights=target),
                          cost_mass[source] * np.average(simulated[:, 2], weights=target)]
            sample = rng.integers(0, len(target), size=(repeats, len(target)))
            q_w, c_w = q_weights[sample], target[sample]
            bootstrap[:, 0] += (simulated[sample, 0] * q_w).sum(axis=1) / q_w.sum(axis=1)
            for axis in (1, 2):
                means = (simulated[sample, axis] * c_w).sum(axis=1) / c_w.sum(axis=1)
                bootstrap[:, axis] += cost_mass[source] * means
        q_distribution = bootstrap[:, 0] / len(SOURCES)
        input_distribution = 1 - bootstrap[:, 1] / bootstrap[:, 2]
        q_point = np.quantile(q_distribution, interval_alpha)
        input_point = 1 - reference[1] / reference[2]
        input_low = np.quantile(input_distribution, interval_alpha)
        observed_q = reference[0] / len(SOURCES)
        quality_at_dev = (q_distribution + conservative_quality, observed_q + conservative_quality)
        cost_at_dev = (
            input_distribution + conservative_savings, input_point + conservative_savings,
        )
        superiority_passes += bool(q_point + conservative_quality > 0.0
                                   and fits_family(quality_at_dev))
        if minimum_quality_effect is not None:
            effect = minimum_quality_effect
            minimum_effect_passes += bool(q_point + effect > 0.0 and fits_family(
                (q_distribution + effect, observed_q + effect)))
        advantage_passes += bool(
            q_point + conservative_quality >= -1.0
            and input_low + conservative_savings > savings_null
            and fits_family(quality_at_dev, cost_at_dev)
        )
        for quality, saving in alternatives:
            passes[quality, saving] += bool(
                q_point + quality >= -1.0 and input_point + saving >= 0.15
                and input_low + saving > savings_null and fits_family(
                    (q_distribution + quality, observed_q + quality),
                    (input_distribution + saving, input_point + saving),
                )
            )
    return {
        "design": "stratified_native_group_dev_residual_simulation",
        **({"projected_dev_tasks": len(dev_roster["tasks"]), "projection_reader_requests": 0,
            "projected_resource_field": cost_field}
           if dev_roster is not None else {}),
        **({"cost_field": cost_field, "minimum_quality_effect_points": minimum_quality_effect,
            "quality_power_at_minimum_effect": minimum_effect_passes / draws}
           if minimum_quality_effect is not None else {}),
        "capacity_registration": {
            k: capacity[k] for k in ("dataset_run_id", "seed", "target_tasks", "selected_groups")
        },
        "source_groups_used": {source: len(rows) for source, rows in profiles.items()},
        "source_groups_available": {source: len(groups) for source, groups in by_group.items()},
        "selected_confirmation_by_source": {
            source: {"native_groups": len(sizes), "tasks": int(sizes.sum())}
            for source, sizes in confirm_sizes.items()
        },
        "model_seeds": seeds, "analysis_seed": analysis_seed, "draws": draws, "repeats": repeats,
        "baseline_seeds": baseline_seeds,
        "conservative_dev_design": {
            "seed_quality_delta_points": dev_quality.tolist(),
            "seed_input_savings": dev_savings.tolist(),
            "true_quality_delta_points": conservative_quality,
            "true_input_savings": conservative_savings,
            "quality_superiority_probability": superiority_passes / draws,
            "quality_preserving_cost_advantage_probability": advantage_passes / draws,
        },
        "primary_comparisons": primary_comparisons, "lower_quantile": alpha,
        **({"family_power_method": "null_centered_bootstrap_at_first_rank_holm_cutoff",
            "holm_planning_bound": "first_rank_guarantees_rejection_for_any_companion_pvalues",
            "family_alpha": 0.025}
           if holm_plan else {}),
        "target_pass_probability": 0.80,
        "planned_alternative_passes": passes[0.0, 0.20] / draws >= 0.80,
        "scenarios": [
            {"true_quality_delta_points": q, "true_input_savings": s,
             "joint_pass_probability": passes[q, s] / draws}
            for q, s in alternatives
        ],
        "confirm_labels_read": 0, "confirm_reader_requests": 0, "sha_validation": False,
    }
