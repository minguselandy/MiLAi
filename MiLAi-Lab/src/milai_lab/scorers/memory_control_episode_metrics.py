"""Native episode aggregation and paired native-group uncertainty."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

from milai_lab.datasets.memory_control_episode_archive import read_archived_episodes
from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.datasets.memory_control_report import read_json
from milai_lab.scorers.memory_control_native import musique_pair

SOURCES = (MUSIQUE, QASPER, PERSONA)
QUALITY_AXES = {MUSIQUE: "group_answer_sufficiency_f1", QASPER: "answer_f1", PERSONA: "accuracy"}
RESOURCE_AXES = (
    "reader_material_tokens",
    "reader_input_tokens",
    "reader_output_tokens",
    "reader_cached_tokens",
    "reader_wall_ms",
    "reader_client_wall_ms",
    "reader_ttft_ms",
    "episode_wall_ms",
    "episode_live_readout_ms",
    "episode_local_wall_ms",
    "episode_local_cpu_ms",
    "preflight_wall_ms",
    "controller_wall_ms",
    "read_operation_wall_ms",
    "search_wall_ms",
    "pool_and_bm25_wall_ms",
    "materialization_and_wire_wall_ms",
    "navigation_tokens",
    "navigation_cpu_ms",
    "navigation_wall_ms",
    "navigation_scanned_chars",
    "navigation_cache_hit",
    "navigation_and_admission_wall_ms",
    "encoder_input_tokens",
    "encoder_padded_tokens",
    "encoder_forwards",
)
Cluster = tuple[float, float, float, float, float, float, float]


def percentiles(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower, upper = math.floor(index), math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def centered_bootstrap_pvalue(
    draws: Sequence[float], point: float, null_boundary: float,
) -> float:
    """One-sided upper-tail test from paired bootstrap draws centered on the null."""
    if not len(draws):
        raise ValueError("A centered bootstrap test requires actual resamples")
    tail = sum(draw - point >= point - null_boundary for draw in draws)
    return (1 + tail) / (1 + len(draws))


def holm_adjust(pvalues: dict[str, float | None]) -> dict[str, float | None]:
    ordered = sorted(pvalues, key=lambda key: (
        1.0 if pvalues[key] is None else pvalues[key], key,
    ))
    adjusted: dict[str, float | None] = {}
    largest = 0.0
    for i, key in enumerate(ordered):
        p = pvalues[key]
        if p is None:
            adjusted[key] = None
            continue
        if not 0.0 <= p <= 1.0:
            raise ValueError("A Holm family requires valid one-sided p values")
        largest = max(largest, min(1.0, p * (len(ordered) - i)))
        adjusted[key] = largest
    return adjusted


def _observed_seed_spread(values: Sequence[float | None]) -> dict[str, Any]:
    observed = [value for value in values if value is not None]
    return {
        "observed_seeds": len(observed),
        "mean": fmean(observed) if observed else None,
        "range": [min(observed), max(observed)] if observed else None,
        "sample_standard_deviation": stdev(observed) if len(observed) > 1 else None,
    }


def input_result(
    root: Path,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    protocol = read_json(root / "protocol.json")
    if not protocol:
        raise ValueError("An actual evaluation protocol is required")
    tasks = protocol["population"]["tasks"]
    archive = read_archived_episodes(root, tasks)
    if archive is not None:
        return protocol, archive
    received = {}
    try:
        for task in tasks:
            row = read_json(root / "episodes" / f"{task['task_id']}.json")
            if row is not None:
                if any(row[k] != task[k] for k in ("task_id", "dataset", "native_group")):
                    raise ValueError("Saved episode and frozen group allocation disagree")
                received[task["task_id"]] = row
    except FileNotFoundError:
        archive = read_archived_episodes(root, tasks)
        if archive is None:
            raise
        return protocol, archive
    if len(received) < len(tasks):
        archive = read_archived_episodes(root, tasks)
        if archive is not None:
            return protocol, archive
    return protocol, received


TERMINAL_FAILURES = {"action_failed", "reader_error", "reader_interrupted", "scorer_error"}


def _primary_group_quality(
    source: str, records: list[dict[str, Any]], *, failure_zero: bool,
) -> list[float]:
    if not all("grade" in row or (failure_zero and row.get("status") in TERMINAL_FAILURES)
               for row in records):
        return []
    if source == MUSIQUE:
        if len(records) != 2:
            return []
        if any("grade" not in row for row in records):
            return [0.0]
        return [musique_pair([row["grade"]["native_metrics"] for row in records])
                [QUALITY_AXES[source]]]
    return [row["grade"]["native_metrics"][QUALITY_AXES[source]]
            if "grade" in row else 0.0 for row in records]


def summarize(root: Path) -> dict[str, Any]:
    protocol, episodes = input_result(root)
    population = protocol["population"]
    terminal_policy = (
        population.get("terminal_quality_failures") == "score_zero_keep_unknown_resource"
    )
    unavailable = population.get("predeclared_unevaluable_tasks", {})
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for task in population["tasks"]:
        grouped[task["dataset"]][task["native_group"]].append(
            episodes.get(task["task_id"], {"status": "unissued", "task_id": task["task_id"]})
        )
    by_source: dict[str, dict[str, Any]] = {}
    for source, groups in grouped.items():
        rows = [row for members in groups.values() for row in members]
        scored = [row["grade"]["native_metrics"] for row in rows if "grade" in row]
        statuses = Counter(row["status"] for row in rows)
        quality = defaultdict(list)
        source_strata: dict[str, Counter[str]] = defaultdict(Counter)
        for metric in scored:
            for axis in ("accuracy", "answer_f1", "answer_em", "support_f1"):
                if metric.get(axis) is not None:
                    quality[axis].append(metric[axis])
            filters = (
                {
                    "figure_only": metric.get("figure_only"),
                    "answer_type": metric.get("best_reference_type"),
                }
                if source == QASPER
                else metric.get("strata", {})
                if source == PERSONA
                else {"answerable": metric["gold_answerable"]}
            )
            for k, val in filters.items():
                key = f"{k}/{val}"
                source_strata[key]["tasks"] += 1
                source_strata[key]["unit_scores_sum"] += metric.get(
                    "accuracy", metric.get("answer_f1") or 0.0
                )
        if source == MUSIQUE:
            for members in groups.values():
                if len(members) != 2:
                    raise ValueError("Registered MuSiQue population lacks paired context variants")
                if all("grade" in row for row in members):
                    pair = musique_pair([row["grade"]["native_metrics"] for row in members])
                    for axis, value in pair.items():
                        quality[axis].append(value)
        if terminal_policy:
            known = []
            for members in groups.values():
                eligible = [row for row in members if str(row["task_id"]) not in unavailable]
                known.extend(_primary_group_quality(source, eligible, failure_zero=True))
            quality[QUALITY_AXES[source]] = known
        resource = {}
        for axis in RESOURCE_AXES:
            values = [
                value
                for row in rows
                if type(value := row.get("costs", {}).get(axis)) in {int, float}
            ]
            if values:
                resource[axis] = {
                    "measured": len(values),
                    "mean": fmean(values),
                    "p50": percentiles(values, 0.50),
                    "p95": percentiles(values, 0.95),
                }
        by_source[source] = {
            "configured_tasks": len(rows),
            "scored_tasks": len(scored),
            "native_groups": len(groups),
            "status": dict(statuses),
            **({"terminal_failures": sum(statuses[name] for name in TERMINAL_FAILURES)}
               if terminal_policy else {}),
            "metrics": {
                k: {"mean": fmean(values), "n": len(values)} for k, values in quality.items()
            },
            "resource": resource,
            "strata": source_strata,
        }
    primary = [native["metrics"].get(QUALITY_AXES[source]) for source, native in by_source.items()]
    available_macro = (
        100 * fmean(m["mean"] for m in primary if m)
        if (len(primary) == len(SOURCES) and all(primary))
        else None
    )
    return {
        "arm": protocol["arm"],
        "role": protocol["population"]["role"],
        "sources": by_source,
        "available_case_macro_quality_points": available_macro,
        "score_complete": sum(row["scored_tasks"] for row in by_source.values())
        == len(protocol["population"]["tasks"]),
    }


def _same_reader_wire(left: dict[str, Any], right: dict[str, Any]) -> bool:
    wire = left.get("reader_wire")
    return isinstance(wire, dict) and bool(wire) and wire == right.get("reader_wire")


def _shared_request_quality_delta(
    source: str,
    ids: list[int],
    left: dict[int, dict[str, Any]],
    right: dict[int, dict[str, Any]],
) -> float:
    shared = [_same_reader_wire(left[i], right[i]) for i in ids]
    if all(shared):
        return 0.0
    a = [left[i]["grade"]["native_metrics"] for i in ids]
    b = [right[i]["grade"]["native_metrics"] for i in ids]
    key = QUALITY_AXES[source]
    if source != MUSIQUE:
        return sum(
            float(x[key]) - float(y[key])
            for x, y, same in zip(a, b, shared, strict=True)
            if not same
        )
    if not any(shared):
        return musique_pair(a)[key] - musique_pair(b)[key]
    # Re-score the whole native pair with either measured shared reply on both sides.
    # This retains its sufficiency gate when just one of the two contexts is shared.
    p = shared.index(True)
    deltas = []
    for grade in (a[p], b[p]):
        first, second = a.copy(), b.copy()
        first[p] = second[p] = grade
        deltas.append(musique_pair(first)[key] - musique_pair(second)[key])
    return fmean(deltas)


def paired_comparison(
    policy_roots: Sequence[Path],
    baseline_root: Path | Sequence[Path],
    *,
    repeats: int = 2000,
    seed: int = 20261118,
    allow_derived_dev_roster: bool = False,
    primary_comparisons: int = 1,
) -> dict[str, Any]:
    baseline_paths = [baseline_root] if isinstance(baseline_root, Path) else list(baseline_root)
    if not policy_roots or not baseline_paths or repeats < 1:
        raise ValueError("Provide actual policy runs and a positive bootstrap count")
    base_protocol, first_baseline = input_result(baseline_paths[0])
    population = base_protocol["population"]
    v12_terminal_policy = bool(population.get("terminal_quality_failures"))

    def read_peer(path: Path) -> tuple[dict[int, dict[str, Any]], int | None]:
        nonlocal v12_terminal_policy
        protocol, predictions = input_result(path)
        if protocol["population"] != population:
            peer = protocol["population"]
            if not allow_derived_dev_roster or not matching_derived_dev(population, peer):
                raise ValueError("Use the same frozen native groups and tasks in all compared runs")
        v12_terminal_policy |= bool(protocol["population"].get("terminal_quality_failures"))
        reader_keys = {
            "reader_protocol",
            "model_revision",
            "reader_config",
            "config_version",
            "tokenizer",
            "temperature",
            "enable_thinking",
            "output_tokens",
            "option_seed",
            "delivery",
            "scorer",
            "native_reference_sources",
        }
        if any(
            base_protocol["comparison"].get(key) != protocol["comparison"].get(key)
            for key in reader_keys
        ):
            raise ValueError("Comparative Reader, delivery or scorer settings changed")
        return predictions, protocol["arm"].get("seed")

    policy_runs, seed_labels = zip(*(read_peer(path) for path in policy_roots), strict=True)
    if len(seed_labels) > 1 and len(set(seed_labels)) != len(seed_labels):
        raise ValueError("Distinct fitted seed IDs are required for multi-seed aggregation")
    baselines, baseline_seeds = zip(
        (first_baseline, base_protocol["arm"].get("seed")),
        *(read_peer(path) for path in baseline_paths[1:]),
        strict=True,
    )
    if len(baselines) > 1 and (
        len(set(baseline_seeds)) != len(baselines)
        or None in baseline_seeds
        or set(baseline_seeds) != set(seed_labels)
    ):
        raise ValueError("Multi-seed baseline arms must match the fitted policy seed IDs")
    calculation = population
    if v12_terminal_policy:
        calculation = {
            **population, "terminal_quality_failures": "score_zero_keep_unknown_resource",
        }
    metrics = _paired_metrics(
        calculation, policy_runs, baselines, seed_labels, baseline_seeds,
        repeats=repeats, seed=seed, primary_comparisons=primary_comparisons,
    )
    return {
        **metrics,
        "seed_summaries": [summarize(path) for path in policy_roots],
        "baseline": (summarize(baseline_paths[0]) if len(baselines) == 1 else {
            "model_seeds": list(baseline_seeds),
            "seed_summaries": [summarize(path) for path in baseline_paths],
        }),
    }


def matching_derived_dev(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["role"] != right["role"] or left["role"] != "dev":
        return False
    parent_link = (
        left.get("parent_dataset_run_id") == right["dataset_run_id"]
        or right.get("parent_dataset_run_id") == left["dataset_run_id"]
    )
    standardized = ("protocol", "role", "tasks", "material_budget", "seed", "primary_quality",
                    "predeclared_unevaluable_tasks")
    return parent_link and all(left.get(key) == right.get(key) for key in standardized)


def paired_repeat_measurements(
    primary: Path, repeated: Path, *, repeats: int, seed: int,
) -> dict[str, Any]:
    """Compare the registered repeat to its original tasks without extending the main roster."""
    base, first = input_result(primary)
    child, again = input_result(repeated)
    population = base["population"]
    subset = child["population"]
    if (
        population["role"] not in {"confirm", "dev"} or subset["role"] != population["role"]
        or not subset.get("measurement_repeat_of") or population["seed"] == subset["seed"]
        or any(population[key] != subset[key] for key in ("dataset_run_id", "material_budget"))
        or base["arm"] != child["arm"] or base["comparison"] != child["comparison"]
    ):
        raise ValueError("The repeat must retain its frozen arm and Reader bindings")
    groups = {(r["dataset"], r["native_group"]) for r in subset["tasks"]}
    unique_ids = {r["task_id"] for r in subset["tasks"]}
    if set(again) != unique_ids or not unique_ids <= first.keys() or subset["tasks"] != [
        r for r in population["tasks"] if (r["dataset"], r["native_group"]) in groups
    ]:
        raise ValueError("The repeated positions must cover exactly their original native groups")
    model_seed = base["arm"].get("seed")
    output = _paired_metrics(
        subset, [again], [first], [model_seed], [model_seed],
        repeats=repeats, seed=seed,
    )
    wires: Counter[str] = Counter()
    for tid in unique_ids:
        a, b = first[tid].get("reader_wire"), again[tid].get("reader_wire")
        if not isinstance(a, dict) or not isinstance(b, dict):
            wires["unmeasured"] += 1
            continue
        same_prompt = {k: v for k, v in a.items() if k != "seed"} == {
            k: v for k, v in b.items() if k != "seed"
        }
        key = "same_payload_new_seed" if (
            same_prompt and a.get("seed") != b.get("seed")
        ) else "identical_wire" if a == b else "other_payload_change"
        wires[key] += 1
    return {**output, "reader_repeat_bindings": dict(wires), "adds_independent_groups": False}


def summarize_inline_policy_load(
    population: dict[str, Any],
    episodes: dict[int, dict[str, Any]],
    windows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Report measured inline task timing and amortize actual policy loads over the fixed cohort."""
    registered = {row["task_id"] for row in population["tasks"]}
    if registered != episodes.keys() or len(registered) != len(population["tasks"]):
        raise ValueError("The inline timing roster must reproduce all registered task positions")
    unavailable = population.get("predeclared_unevaluable_tasks", {})
    eligible = {tid for tid in registered if str(tid) not in unavailable}
    timed = []
    for tid in sorted(eligible):
        row = episodes[tid]
        costs = row.get("costs", {})
        value = costs.get("episode_live_readout_ms")
        if (row["status"] in {"scored", "scored_format_failure"}
                and costs.get("reader_request_attempted") is True
                and type(value) in (int, float) and math.isfinite(value) and value > 0):
            timed.append(float(value))

    have_loads = bool(windows)
    load_values = []
    for window in windows:
        value = window.get("policy_load_ms_this_invocation")
        if (window.get("readout_schedule") == "inline"
                and type(value) in (int, float) and math.isfinite(value) and value >= 0):
            load_values.append(float(value))
        else:
            have_loads = False
    total_load = sum(load_values) if have_loads else None
    loads = sum(value > 0 for value in load_values) if have_loads else None
    load_per_task = total_load / len(eligible) if total_load is not None and eligible else None
    complete = bool(eligible) and len(timed) == len(eligible)
    inline_mean = fmean(timed) if timed else None
    return {
        "registered_tasks": len(registered), "eligible_tasks": len(eligible),
        "timed_live_reader_tasks": len(timed), "inline_timings_complete": complete,
        "live_task_wall_ms": {
            "mean": inline_mean,
            "p50": percentiles(timed, .50) if timed else None,
            "p95": percentiles(timed, .95) if timed else None,
        },
        "policy_load_records_complete": have_loads,
        "policy_load_count": loads, "total_policy_load_ms": total_load,
        "eligible_tasks_per_policy_load": len(eligible) / loads if loads else None,
        "policy_load_ms_per_eligible_task": load_per_task,
        "mean_live_task_wall_ms_with_amortized_policy_load": (
            inline_mean + load_per_task if complete and load_per_task is not None else None
        ),
    }


def paired_inline_latency(
    policy: Sequence[Path], baseline: Path, *, repeats: int, seed: int,
) -> dict[str, Any]:
    """Bootstrap continuously timed local-execution-to-Reader latency by native group."""
    import numpy as np

    if not policy or repeats < 1:
        raise ValueError("Use actual paired policies and a positive latency resample count")
    reference, baseline_records = input_result(baseline)
    loaded = [input_result(path) for path in policy]
    population = reference["population"]
    keys = set(reference["comparison"]) - {"observation", "continuation"}
    for protocol, _ in [(reference, baseline_records), *loaded]:
        if (
            protocol.get("readout_schedule") != "inline" or protocol["population"] != population
            or any(protocol["comparison"].get(k) != reference["comparison"][k] for k in keys)
        ):
            raise ValueError("Latency comparisons require the same independently timed roster")
    selected_groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    unavailable = population.get("predeclared_unevaluable_tasks", {})
    for row in population["tasks"]:
        if str(row["task_id"]) not in unavailable:
            selected_groups[row["dataset"]][row["native_group"]].append(row["task_id"])

    def measured(rows: dict[int, dict[str, Any]], ids: list[int]) -> list[float]:
        found = []
        for tid in ids:
            row = rows.get(tid, {})
            value = row.get("costs", {}).get("episode_live_readout_ms")
            if (
                row.get("status") not in {"scored", "scored_format_failure"}
                or type(value) not in (float, int) or not math.isfinite(value) or value <= 0
            ):
                return []
            found.append(float(value))
        return found

    seeds = [protocol["arm"].get("seed") for protocol, _ in loaded]
    if len(seeds) > 1 and len(set(seeds)) != len(seeds):
        raise ValueError("Multi-seed latency requires distinct fitted seeds")
    profiles: dict[str, list[tuple[float, ...]]] = defaultdict(list)
    for source, groups in selected_groups.items():
        for ids in groups.values():
            left = [measured(rows, ids) for _, rows in loaded]
            right = measured(baseline_records, ids)
            if all(left) and right:
                profiles[source].append((*map(sum, left), sum(right), len(ids)))
    counts = {
        source: {
            "registered_groups": len(groups), "paired_groups": len(profiles[source]),
            "paired_tasks": int(sum(row[-1] for row in profiles[source])),
        }
        for source, groups in selected_groups.items()
    }
    complete = set(counts) == set(SOURCES) and all(
        row["registered_groups"] == row["paired_groups"] for row in counts.values()
    )
    output: dict[str, Any] = {
        "scope": "wall_from_local_task_execution_start_through_live_reader_reply",
        "policy_initialization_reported_separately": True,
        "by_source": counts, "paired_latency_complete": complete,
        "latency_saving": None, "latency_saving_interval_95": None,
        "repeats": repeats, "bootstrap_seed": seed,
    }
    if len(seeds) > 1:
        output["interval_conditioned_on_model_seeds"] = seeds
    if set(counts) != set(SOURCES) or any(not profiles[source] for source in SOURCES):
        if len(seeds) > 1:
            output["by_seed"] = [
                {"model_seed": label, "latency_saving": None, "latency_saving_interval_95": None}
                for label in seeds
            ]
        return output
    rng = np.random.default_rng(seed)
    base = np.zeros(len(seeds) + 1)
    cluster_draws = np.zeros((repeats, len(base)))
    for source in SOURCES:
        arrays = np.asarray(profiles[source])
        base += arrays[:, :-1].sum(axis=0) / arrays[:, -1].sum()
        sample = rng.integers(0, len(arrays), size=(repeats, len(arrays)))
        totals = arrays[sample, :].sum(axis=1)
        cluster_draws += totals[:, :-1] / totals[:, -1:]
    per_seed = 1 - base[:-1] / base[-1]
    per_seed_draws = 1 - cluster_draws[:, :-1] / cluster_draws[:, -1:]
    output.update({
        "latency_saving": float(per_seed.mean()),
        "latency_saving_interval_95": np.quantile(
            per_seed_draws.mean(axis=1), [0.025, 0.975],
        ).tolist(),
    })
    if len(seeds) > 1:
        intervals = np.quantile(per_seed_draws, [0.025, 0.975], axis=0).T.tolist()
        seed_draws = np.random.default_rng(seed + 1).integers(
            0, len(seeds), size=(repeats, len(seeds)),
        )
        joint = per_seed_draws[np.arange(repeats)[:, None], seed_draws].mean(axis=1)
        output.update({
            "by_seed": [
                {"model_seed": label, "latency_saving": float(value),
                 "latency_saving_interval_95": interval}
                for label, value, interval in zip(seeds, per_seed, intervals, strict=True)
            ],
            "seed_spread": _observed_seed_spread(per_seed.tolist()),
            "seed_and_group_sensitivity": {
                "latency_saving_interval_95": np.quantile(joint, [0.025, 0.975]).tolist(),
            },
        })
    return output


def paired_budget_response_metrics(
    reference_protocol: dict[str, Any],
    held_protocol: dict[str, Any],
    reference: dict[int, dict[str, Any]],
    observed_for_held: dict[int, dict[str, Any]],
    *,
    repeats: int = 2000,
    seed: int = 20261118,
) -> dict[str, Any]:
    """Pair observed replies for one DEV arm across a reference and held material budget."""
    base = reference_protocol["population"]
    held = held_protocol["population"]
    base_budget, held_budget = base["material_budget"], held["material_budget"]
    if (
        base["role"] != "dev" or repeats < 1
        or any(type(budget) is not int or budget < 1 for budget in (base_budget, held_budget))
        or held_budget == base_budget or {**base, "material_budget": held_budget} != held
        or reference_protocol["comparison"] != held_protocol["comparison"]
        or reference_protocol["arm"] != held_protocol["arm"]
    ):
        raise ValueError("A held-budget comparison requires the same DEV arm and task declaration")
    model_seed = reference_protocol["arm"].get("seed")
    metrics = _paired_metrics(
        held, (observed_for_held,), (reference,), (model_seed,), (model_seed,), repeats=repeats,
        seed=seed,
    )
    return {**metrics, "reference_budget": base_budget, "held_budget": held_budget}


def _paired_metrics(
    population: dict[str, Any],
    policy_runs: Sequence[dict[int, dict[str, Any]]],
    baselines: Sequence[dict[int, dict[str, Any]]],
    seed_labels: Sequence[int | None],
    baseline_seeds: Sequence[int | None],
    *,
    repeats: int,
    seed: int,
    primary_comparisons: int = 1,
) -> dict[str, Any]:
    if primary_comparisons < 1:
        raise ValueError("Register a positive number of primary comparisons")
    if family := population.get("confirmation_primary_comparisons"):
        if primary_comparisons not in {1, family}:
            raise ValueError("Primary comparison family differs from the frozen confirmation")
        primary_comparisons = family
    wires: dict[str, Counter[str]] = defaultdict(Counter)
    baseline_by_seed = dict(zip(baseline_seeds, baselines, strict=True))
    seed_pairs = [
        (policy, baselines[0] if len(baselines) == 1 else baseline_by_seed[model_seed])
        for policy, model_seed in zip(policy_runs, seed_labels, strict=True)
    ]
    for policy, baseline in seed_pairs:
        for tid in policy.keys() & baseline.keys():
            left, right = policy[tid], baseline[tid]
            if "grade" not in left or "grade" not in right:
                continue
            a, b = left.get("reader_wire"), right.get("reader_wire")
            if not isinstance(a, dict) or not isinstance(b, dict):
                continue
            counts = wires[left["dataset"]]
            if not _same_reader_wire(left, right):
                counts["different_requests"] += 1
                continue
            counts["identical_requests"] += 1
            counts["identical_requests_different_native_grade"] += left["grade"] != right["grade"]
            x, y = left["grade"].get("training_quality"), right["grade"].get("training_quality")
            if x is not None and y is not None:
                counts["identical_requests_different_training_quality"] += x != y
    registered: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    declared_unavailable = population.get("predeclared_unevaluable_tasks", {})
    for row in population["tasks"]:
        if str(row["task_id"]) in declared_unavailable:
            tid = row["task_id"]
            if not all(
                arm.get(tid, {}).get("status") == "action_failed"
                and arm[tid].get("failure_reason") == declared_unavailable[str(tid)]
                for arm in [*baselines, *policy_runs]
            ):
                raise ValueError("The preregistered non-evaluable task status must be preserved")
            continue
        registered[row["dataset"]][row["native_group"]].append(row["task_id"])

    def quality(records: dict[int, dict[str, Any]], ids: list[int], source: str) -> list[float]:
        return _primary_group_quality(
            source, [records.get(n, {}) for n in ids],
            failure_zero=bool(population.get("terminal_quality_failures")),
        )

    def input_tokens(records: dict[int, dict[str, Any]], ids: list[int]) -> list[int]:
        return [
            token
            for tid in ids
            if tid in records
            and type(token := records[tid].get("costs", {}).get("reader_input_tokens")) is int
        ]

    # Each row remains one independent cluster, regardless of task count or model seed count.
    paired: dict[str, list[Cluster]] = defaultdict(list)
    seed_clusters: dict[str, list[list[Cluster]]] = defaultdict(list)
    baseline_n = len(baselines)
    for source, groups in registered.items():
        for ids in groups.values():
            peer_quality = [quality(arm, ids, source) for arm in [*baselines, *policy_runs]]
            peer_cost = [input_tokens(arm, ids) for arm in [*baselines, *policy_runs]]
            quality_n = len(peer_quality[0]) if all(peer_quality) else 0
            cost_n = len(ids) if all(len(row) == len(ids) for row in peer_cost) else 0
            group_sensitivity = []
            seed_rows: list[Cluster] = []
            for seed_index, (policy, baseline) in enumerate(seed_pairs):
                baseline_index = 0 if baseline_n == 1 else baseline_seeds.index(
                    seed_labels[seed_index],
                )
                p = baseline_n + seed_index
                if quality_n and all(
                    "grade" in arm[tid] for arm in (policy, baseline) for tid in ids
                ):
                    common = _shared_request_quality_delta(source, ids, policy, baseline)
                else:
                    common = (sum(peer_quality[p]) - sum(peer_quality[baseline_index])
                              if quality_n else 0.0)
                group_sensitivity.append(common)
                if len(seed_pairs) > 1:
                    seed_rows.append((
                        sum(peer_quality[p]) if quality_n else 0.0,
                        sum(peer_quality[baseline_index]) if quality_n else 0.0,
                        quality_n,
                        sum(peer_cost[p]) if cost_n else 0.0,
                        sum(peer_cost[baseline_index]) if cost_n else 0.0,
                        cost_n, common,
                    ))
            if seed_rows:
                seed_clusters[source].append(seed_rows)
            paired[source].append(
                (
                    fmean(sum(row) for row in peer_quality[baseline_n:]) if quality_n else 0.0,
                    fmean(sum(row) for row in peer_quality[:baseline_n]) if quality_n else 0.0,
                    quality_n,
                    fmean(sum(row) for row in peer_cost[baseline_n:]) if cost_n else 0.0,
                    fmean(sum(row) for row in peer_cost[:baseline_n]) if cost_n else 0.0,
                    cost_n,
                    fmean(group_sensitivity),
                )
            )

    def aggregate_totals(
        totals: dict[str, Sequence[float]],
    ) -> tuple[float | None, float | None, float | None, dict[str, dict[str, Any]]]:
        components: dict[str, dict[str, Any]] = {}
        for source, cluster in totals.items():
            policy_q, baseline_q, qn, policy_c, baseline_c, cn, shared_delta = cluster
            components[source] = {
                "quality_delta": 100 * (policy_q - baseline_q) / qn if qn else None,
                "shared_request_quality_delta": 100 * shared_delta / qn if qn else None,
                "policy_input_tokens": policy_c / cn if cn else None,
                "baseline_input_tokens": baseline_c / cn if cn else None,
                "quality_units": int(qn),
                "cost_tasks": int(cn),
            }
        if not set(SOURCES) <= components.keys():
            return None, None, None, components
        score = (
            fmean(m["quality_delta"] for m in components.values())
            if all(m["quality_units"] for m in components.values())
            else None
        )
        savings = None
        sensitivity = (
            fmean(m["shared_request_quality_delta"] for m in components.values())
            if all(m["quality_units"] for m in components.values())
            else None
        )
        if all(m["cost_tasks"] for m in components.values()):
            denom = fmean(m["baseline_input_tokens"] for m in components.values())
            if denom > 0:
                savings = 1 - fmean(m["policy_input_tokens"] for m in components.values()) / denom
        return score, savings, sensitivity, components

    def aggregate(
        grouped: dict[str, list[Cluster]],
    ) -> tuple[float | None, float | None, float | None, dict[str, dict[str, Any]]]:
        return aggregate_totals({
            source: tuple(map(sum, zip(*clusters, strict=True)))
            for source, clusters in grouped.items()
        })

    point_quality, point_cost, point_sensitivity, strata = aggregate(paired)
    rng = random.Random(seed)  # noqa: S311 -- predeclared native-group bootstrap
    quality_draws, cost_draws, sensitivity_draws = [], [], []
    seed_group_quality, seed_group_cost = [], []
    seed_rng = random.Random(seed + 1)  # noqa: S311 -- seed-resampling sensitivity
    source_draws: dict[str, list[float]] = defaultdict(list)
    shared_source_draws: dict[str, list[float]] = defaultdict(list)
    seed_outputs: list[dict[str, Any]] = []
    seed_intervals: list[tuple[list[float], list[float]]] = []
    seed_arrays = {}
    if seed_clusters:
        import numpy as np

        seed_arrays = {source: np.asarray(rows) for source, rows in seed_clusters.items()}
        source_totals = {source: rows.sum(axis=0) for source, rows in seed_arrays.items()}
        for i, label in enumerate(seed_labels):
            q, c, _, components = aggregate_totals({
                source: totals[i] for source, totals in source_totals.items()
            })
            seed_outputs.append({
                "model_seed": label,
                "baseline_seed": baseline_seeds[0] if baseline_n == 1 else label,
                "quality_delta_points": q, "reader_input_token_savings": c,
                "source_strata": components,
            })
            seed_intervals.append(([], []))
    for _ in range(repeats):
        sampled = {source: rng.choices(range(len(groups)), k=len(groups))
                   for source, groups in paired.items()}
        sample = {source: [paired[source][i] for i in indices]
                  for source, indices in sampled.items()}
        q, c, sensitivity, points = aggregate(sample)
        if q is not None:
            quality_draws.append(q)
        if c is not None:
            cost_draws.append(c)
        if sensitivity is not None:
            sensitivity_draws.append(sensitivity)
        for source, point in points.items():
            if point["quality_delta"] is not None:
                source_draws[source].append(point["quality_delta"])
                shared_source_draws[source].append(point["shared_request_quality_delta"])
        if seed_arrays:
            resampled_totals = {
                source: seed_arrays[source][indices].sum(axis=0)
                for source, indices in sampled.items()
            }
            for i, (q_draws, cost_per_seed) in enumerate(seed_intervals):
                q_seed, c_seed, _, _ = aggregate_totals({
                    source: totals[i] for source, totals in resampled_totals.items()
                })
                if q_seed is not None:
                    q_draws.append(q_seed)
                if c_seed is not None:
                    cost_per_seed.append(c_seed)
            draw = seed_rng.choices(range(len(seed_pairs)), k=len(seed_pairs))
            q_mixed, c_mixed, _, _ = aggregate_totals({
                source: totals[draw].mean(axis=0) for source, totals in resampled_totals.items()
            })
            if q_mixed is not None:
                seed_group_quality.append(q_mixed)
            if c_mixed is not None:
                seed_group_cost.append(c_mixed)
    quality_ci = [percentiles(quality_draws, p) for p in (0.025, 0.975)] if quality_draws else None
    cost_ci = [percentiles(cost_draws, p) for p in (0.025, 0.975)] if cost_draws else None
    family_quantiles = (0.025 / primary_comparisons, 1 - 0.025 / primary_comparisons)
    family_quality = (
        [percentiles(quality_draws, p) for p in family_quantiles] if quality_draws else None
    )
    family_cost = [percentiles(cost_draws, p) for p in family_quantiles] if cost_draws else None
    for source, component in strata.items():
        for key, draws in (
            ("quality_interval_95", source_draws[source]),
            ("shared_request_quality_interval_95", shared_source_draws[source]),
        ):
            component[key] = [percentiles(draws, p) for p in (0.025, 0.975)] if draws else None
    complete_sources = set(strata) == set(SOURCES)
    quality_complete = complete_sources and all(
        s["quality_units"]
        == (
            len(registered[source])
            if source == MUSIQUE
            else sum(len(ids) for ids in registered[source].values())
        )
        for source, s in strata.items()
    )
    cost_complete = complete_sources and all(
        s["cost_tasks"] == sum(len(ids) for ids in registered[source].values())
        for source, s in strata.items()
    )
    confirmed = (
        population["role"] == "confirm"
        and quality_complete
        and set(seed_labels) == set(population["confirmation_seeds"])
    )
    centered = None
    if population["role"] == "confirm":
        centered = {
            "quality_superiority": centered_bootstrap_pvalue(quality_draws, point_quality, 0.0)
            if confirmed and point_quality is not None else None,
            "quality_noninferiority": centered_bootstrap_pvalue(
                quality_draws, point_quality, -population["quality_noninferiority_points"],
            ) if confirmed and point_quality is not None else None,
            "positive_input_savings": centered_bootstrap_pvalue(cost_draws, point_cost, 0.0)
            if confirmed and cost_complete and point_cost is not None else None,
        }
    quality_supported = bool(confirmed and family_quality and family_quality[0] > 0)
    cost_advantage_supported = bool(
        confirmed and cost_complete
        and family_quality
        and family_quality[0] >= -population["quality_noninferiority_points"]
        and family_cost
        and family_cost[0] > 0
    )
    cost_supported = bool(
        cost_advantage_supported
        and point_cost is not None
        and point_cost >= population["reader_input_savings_floor"]
    )
    for output, (quality_per_seed, cost_per_seed) in zip(seed_outputs, seed_intervals, strict=True):
        output["quality_interval_95"] = (
            [percentiles(quality_per_seed, p) for p in (0.025, 0.975)]
            if quality_per_seed else None
        )
        output["token_savings_interval_95"] = (
            [percentiles(cost_per_seed, p) for p in (0.025, 0.975)] if cost_per_seed else None
        )
    return {
        "role": population["role"],
        "configured_tasks": len(population["tasks"]),
        "predeclared_unevaluable_tasks": len(declared_unavailable),
        "model_seeds": list(seed_labels),
        "quality_delta_points": point_quality,
        "quality_interval_95": quality_ci,
        "reader_input_token_savings": point_cost,
        "token_savings_interval_95": cost_ci,
        "source_strata": strata,
        "shared_request_sensitivity": {
            "method": "literal_equal_wire_share_observed_replies_v1",
            "quality_delta_points": point_sensitivity,
            "quality_interval_95": (
                [percentiles(sensitivity_draws, p) for p in (0.025, 0.975)]
                if sensitivity_draws else None
            ),
        },
        "scored_request_equality_by_source": dict(wires),
        "independent_groups": {k: len(v) for k, v in registered.items()},
        "repeats": repeats,
        "bootstrap_seed": seed,
        "paired_measurements_complete": quality_complete and cost_complete,
        "paired_quality_complete": quality_complete,
        "paired_reader_input_complete": cost_complete,
        **({"primary_family_comparison_count": primary_comparisons,
            "familywise_quality_interval": family_quality,
            "familywise_cost_interval": family_cost} if primary_comparisons > 1 else {}),
        "quality_path_supported": quality_supported,
        "quality_preserving_cost_advantage_supported": cost_advantage_supported,
        "cost_path_supported": cost_supported,
        **({"one_sided_centered_pvalues": centered} if centered is not None else {}),
        **({"interval_conditioned_on_model_seeds": list(seed_labels),
            "by_seed": seed_outputs,
            "seed_spread": {
                key: _observed_seed_spread([row[key] for row in seed_outputs])
                for key in ("quality_delta_points", "reader_input_token_savings")
            }} if seed_outputs else {}),
        **({"seed_and_group_sensitivity": {
            "seed_resampling_count": len(seed_pairs),
            "quality_interval_95": [percentiles(seed_group_quality, p) for p in (0.025, 0.975)]
            if seed_group_quality else None,
            "token_savings_interval_95": [percentiles(seed_group_cost, p) for p in (0.025, 0.975)]
            if seed_group_cost else None,
        }} if seed_clusters else {}),
    }


def select_baseline(runs: Sequence[Path]) -> dict[str, Any]:
    """Pick the strongest baseline on a common, already executed DEV population."""
    loaded = [input_result(path) for path in runs]
    if not loaded:
        raise ValueError("Actual DEV baseline runs are required")
    plan = loaded[0][0]["population"]
    if plan["role"] != "dev" or any(proto["population"] != plan for proto, _ in loaded):
        raise ValueError("Baseline selection requires the same registered DEV tasks")
    names = [proto["arm"]["policy"] for proto, _ in loaded]
    if len(names) != 5 or set(names) != {"B0", "B1", "B2", "B3", "B4"}:
        raise ValueError("Use all five deployable baseline conditions")
    for _, episodes in loaded:
        if any(task["task_id"] not in episodes for task in plan["tasks"]):
            raise ValueError("All baseline task positions must be terminal before selection")
        if any(
            row["status"] in {"not_issued_budget", "ready", "dispatching", "reader_completed"}
            for row in episodes.values()
        ):
            raise ValueError("Baseline selection requires terminal Reader/scoring status")
    complete_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    group_tasks: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in plan["tasks"]:
        group_tasks[row["dataset"], row["native_group"]].append(row["task_id"])
    for key, ids in group_tasks.items():
        if all("grade" in episodes[tid] for _, episodes in loaded for tid in ids):
            complete_groups[key] = ids
    if {source for source, _ in complete_groups} != set(SOURCES):
        raise ValueError("Baseline selection requires comparable outcomes for all three sources")
    results = []
    for path, (protocol, episodes) in zip(runs, loaded, strict=True):
        grouped_quality: dict[str, list[float]] = defaultdict(list)
        grouped_costs: dict[str, list[int]] = defaultdict(list)
        for (source, _), ids in complete_groups.items():
            rows = [episodes[tid] for tid in ids]
            native = [row["grade"]["native_metrics"] for row in rows]
            axis = QUALITY_AXES[source]
            if source == MUSIQUE:
                grouped_quality[source].append(musique_pair(native)[axis])
            else:
                grouped_quality[source].extend(row[axis] for row in native)
            grouped_costs[source].extend(row["costs"]["reader_input_tokens"] for row in rows)
        score = 100 * fmean(fmean(grouped_quality[source]) for source in SOURCES)
        cost = fmean(fmean(grouped_costs[source]) for source in SOURCES)
        results.append(
            {
                "arm": protocol["arm"],
                "run": str(path.resolve()),
                "macro_quality_points": score,
                "macro_reader_input_tokens": cost,
            }
        )
    ordered = sorted(
        results,
        key=lambda row: (
            -row["macro_quality_points"],
            row["macro_reader_input_tokens"],
            row["arm"]["policy"],
        ),
    )
    return {
        "role": "dev",
        "dataset_run_id": plan["dataset_run_id"],
        "selected": ordered[0],
        "selection": "highest_source_macro_quality_then_lowest_macro_input_tokens",
        "baseline_ranking": ordered,
        "registered_tasks": len(plan["tasks"]),
        "common_scored_tasks": sum(len(ids) for ids in complete_groups.values()),
        "common_source_groups": len(complete_groups),
    }


def observation_factorial(
    roots: Sequence[Path],
    *,
    repeats: int = 2000,
    seed: int = 20261118,
) -> dict[str, Any]:
    """Matched navigation and architecture effects on the native quality metric."""
    expected = (
        ("object_mlp", "metadata_v1"),
        ("object_mlp", "semantic_nav_v1"),
        ("latent_pointer", "metadata_v1"),
        ("latent_pointer", "semantic_nav_v1"),
    )
    if len(roots) != len(expected) or repeats < 1:
        raise ValueError("Provide (M0N0, M0N1, M1N0, M1N1) and positive bootstrap repetitions")
    loaded = [input_result(root) for root in roots]
    first = loaded[0][0]
    population = first["population"]
    stage_fields = (
        "dataset_run_id",
        "supervision_mode",
        "sampling",
        "seed",
        "epochs",
        "steps",
        "batch_states",
        "learning_rate",
        "eligible_states",
    )
    reference_fit = None
    reference_config = None
    for (protocol, _), (architecture, observation) in zip(loaded, expected, strict=True):
        comparison = {k: v for k, v in protocol["comparison"].items() if k != "observation"}
        reference = {k: v for k, v in first["comparison"].items() if k != "observation"}
        if protocol["population"] != population or comparison != reference:
            raise ValueError("Factorial comparisons require the same tasks, runtime and Reader")
        arm = protocol["arm"]
        if (
            arm["policy"] != "checkpoint"
            or arm["observation_protocol"] != observation
            or arm["stop"] != "fixed"
            or arm["precision"] != first["arm"]["precision"]
            or arm["reads"] != first["arm"]["reads"]
        ):
            raise ValueError("Use the matched weak policy stop and precision across all four arms")
        checkpoint = Path(arm["checkpoint"])
        config = read_json(checkpoint / "config.json")
        if config["object_architecture"] != architecture:
            raise ValueError("Actual checkpoint architecture disagrees with the matrix position")
        common_config = {k: v for k, v in config.items() if k != "object_architecture"}
        if reference_config is None:
            reference_config = common_config
        elif common_config != reference_config:
            raise ValueError("Factorial encoder and head settings differ outside architecture")
        run_path = next(
            (
                parent / "run.json"
                for parent in (checkpoint.parent, checkpoint.parent.parent)
                if (parent / "run.json").is_file()
            ),
            None,
        )
        if run_path is None:
            raise ValueError("Factorial comparison needs actual training receipts")
        fit = read_json(run_path)
        declared = {k: fit["contract"][k] for k in stage_fields}
        if (fit["status"] != "COMPLETED" or declared["supervision_mode"] != "weak"
                or checkpoint.name != "checkpoint"):
            raise ValueError("Use full completed weak fits")
        if reference_fit is None:
            reference_fit = declared
        elif reference_fit != declared:
            raise ValueError("Weak training coverage, updates, optimizer recipe or seed differ")

    registered: dict[tuple[str, str], list[int]] = defaultdict(list)
    for task in population["tasks"]:
        registered[task["dataset"], task["native_group"]].append(task["task_id"])
    clusters: dict[str, list[tuple[int, list[float]]]] = defaultdict(list)
    excluded: Counter[str] = Counter()
    for (source, _), ids in registered.items():
        if any(
            any(tid not in outcomes or "grade" not in outcomes[tid] for tid in ids)
            for _, outcomes in loaded
        ):
            excluded[source] += 1
            continue
        results = [
            [outcomes[tid]["grade"]["native_metrics"] for tid in ids] for _, outcomes in loaded
        ]
        qualities = (
            [musique_pair(rows)[QUALITY_AXES[source]] for rows in results]
            if source == MUSIQUE
            else [sum(row[QUALITY_AXES[source]] for row in rows) for rows in results]
        )
        clusters[source].append((1 if source == MUSIQUE else len(ids), qualities))
    if set(clusters) != set(SOURCES):
        raise ValueError("All three sources need paired native group measurements")

    def macro(data: dict[str, list[tuple[int, list[float]]]]) -> list[float]:
        return [
            100
            * fmean(
                sum(quality[i] for _, quality in rows) / sum(n for n, _ in rows)
                for rows in data.values()
            )
            for i in range(4)
        ]

    def effects(points: list[float]) -> dict[str, float]:
        a, b, c, d = points
        return {
            "navigation_on_M0": b - a,
            "navigation_on_M1": d - c,
            "attention_with_N0": c - a,
            "attention_with_N1": d - b,
            "interaction": (d - b) - (c - a),
        }

    point = macro(clusters)
    rng = random.Random(seed)  # noqa: S311 -- declared paired native-group bootstrap
    draws: dict[str, list[float]] = defaultdict(list)
    for _ in range(repeats):
        values = effects(
            macro({source: rng.choices(rows, k=len(rows)) for source, rows in clusters.items()})
        )
        for key, value in values.items():
            draws[key].append(value)
    assert reference_fit is not None
    return {
        "role": population["role"],
        "model_seed": reference_fit["seed"],
        "source_macro_by_arm": dict(zip(("M0N0", "M0N1", "M1N0", "M1N1"), point, strict=True)),
        "effect_points": effects(point),
        "intervals_95": {
            k: [percentiles(v, 0.025), percentiles(v, 0.975)] for k, v in draws.items()
        },
        "paired_native_groups": {s: len(rows) for s, rows in clusters.items()},
        "unpaired_missing_groups": dict(excluded),
        "reader_resources": {str(root): summarize(root)["sources"] for root in roots},
        "bootstrap_repeats": repeats,
        "bootstrap_seed": seed,
    }
