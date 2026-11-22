"""Allocate fresh native groups and model confirmation precision from DEV outcomes."""

from __future__ import annotations

import random
from collections import Counter, defaultdict, deque
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

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
)


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
            if complete or (path / "episodes" / f"{task['task_id']}.json").is_file()
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
) -> dict[str, Any]:
    """Sample clustered DEV residuals into the candidate fresh source/group allocation."""
    import numpy as np

    if min(draws, repeats, primary_comparisons) <= 0 or len(policy) != 3:
        raise ValueError("Power uses three actual DEV seeds and positive simulation settings")
    baselines = [baseline] if isinstance(baseline, Path) else list(baseline)
    if len(baselines) not in {1, 3}:
        raise ValueError("Power requires one fixed or three seed-matched DEV baselines")
    comparison_runs = [input_result(path) for path in baselines]
    base_protocol = comparison_runs[0][0]
    population = base_protocol["population"]
    if population["role"] != "dev":
        raise ValueError("Review only DEV responses for power planning")
    loaded = [input_result(path) for path in policy]
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
                _primary_group_quality(source, records, failure_zero=True)
                for records in records_by_arm
            ]
            costs = [[r.get("costs", {}).get("reader_input_tokens") for r in records]
                     for records in records_by_arm]
            if not all(qualities) or not all(type(c) is int for row in costs for c in row):
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
        raise ValueError("Actual DEV outcomes need multiple measured groups per native source")

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
    dev_points = np.zeros((len(seeds), 3))
    for source in SOURCES:
        sizes = source_sizes[source]
        q_weights = np.ones(len(sizes)) if source == MUSIQUE else sizes
        dev_points[:, 0] += np.average(arrays[source][:, :, 0], axis=0, weights=q_weights)
        for axis in (1, 2):
            dev_points[:, axis] += np.average(arrays[source][:, :, axis], axis=0, weights=sizes)
    dev_quality = dev_points[:, 0] / len(SOURCES)
    dev_savings = 1 - dev_points[:, 1] / dev_points[:, 2]
    conservative_quality, conservative_savings = float(min(dev_quality)), float(min(dev_savings))
    superiority_passes = advantage_passes = 0
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
        cost_p = centered_bootstrap_pvalue(*cost_test, 0.0) if cost_test is not None else 0
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
                          np.average(simulated[:, 1], weights=target),
                          np.average(simulated[:, 2], weights=target)]
            sample = rng.integers(0, len(target), size=(repeats, len(target)))
            q_w, c_w = q_weights[sample], target[sample]
            bootstrap[:, 0] += (simulated[sample, 0] * q_w).sum(axis=1) / q_w.sum(axis=1)
            for axis in (1, 2):
                bootstrap[:, axis] += (simulated[sample, axis] * c_w).sum(axis=1) / c_w.sum(axis=1)
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
        advantage_passes += bool(
            q_point + conservative_quality >= -1.0
            and input_low + conservative_savings > 0.0
            and fits_family(quality_at_dev, cost_at_dev)
        )
        for quality, saving in alternatives:
            passes[quality, saving] += bool(
                q_point + quality >= -1.0 and input_point + saving >= 0.15
                and input_low + saving > 0.0 and fits_family(
                    (q_distribution + quality, observed_q + quality),
                    (input_distribution + saving, input_point + saving),
                )
            )
    return {
        "design": "stratified_native_group_dev_residual_simulation",
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
