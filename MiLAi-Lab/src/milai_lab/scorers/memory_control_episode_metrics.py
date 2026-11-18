"""Native episode aggregation and paired native-group uncertainty."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from statistics import fmean
from typing import Any

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
    "episode_wall_ms",
    "preflight_wall_ms",
    "controller_wall_ms",
    "read_operation_wall_ms",
    "pool_and_bm25_wall_ms",
    "materialization_and_wire_wall_ms",
    "navigation_tokens",
    "navigation_and_admission_wall_ms",
    "encoder_input_tokens",
)


def percentiles(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower, upper = math.floor(index), math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def input_result(
    root: Path,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    protocol = read_json(root / "protocol.json")
    if not protocol:
        raise ValueError("An actual evaluation protocol is required")
    received = {}
    for task in protocol["population"]["tasks"]:
        path = root / "episodes" / f"{task['task_id']}.json"
        if path.is_file():
            row = read_json(path)
            if any(row[k] != task[k] for k in ("task_id", "dataset", "native_group")):
                raise ValueError("Saved episode and frozen group allocation disagree")
            received[task["task_id"]] = row
    return protocol, received


def summarize(root: Path) -> dict[str, Any]:
    protocol, episodes = input_result(root)
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for task in protocol["population"]["tasks"]:
        grouped[task["dataset"]][task["native_group"]].append(
            episodes.get(task["task_id"], {"status": "unissued"})
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


def paired_comparison(
    policy_roots: Sequence[Path],
    baseline_root: Path | Sequence[Path],
    *,
    repeats: int = 2000,
    seed: int = 20261118,
) -> dict[str, Any]:
    baseline_paths = [baseline_root] if isinstance(baseline_root, Path) else list(baseline_root)
    if not policy_roots or not baseline_paths or repeats < 1:
        raise ValueError("Provide actual policy runs and a positive bootstrap count")
    base_protocol, first_baseline = input_result(baseline_paths[0])
    population = base_protocol["population"]

    def read_peer(path: Path) -> tuple[dict[int, dict[str, Any]], int | None]:
        protocol, predictions = input_result(path)
        if protocol["population"] != population:
            raise ValueError("Use the same frozen native groups and tasks in all compared runs")
        reader_keys = {
            "reader_protocol",
            "model_revision",
            "tokenizer",
            "temperature",
            "enable_thinking",
            "output_tokens",
            "option_seed",
            "delivery",
            "scorer",
        }
        if any(
            base_protocol["comparison"][key] != protocol["comparison"][key] for key in reader_keys
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
        by_task = [
            records[n]["grade"]["native_metrics"]
            for n in ids
            if n in records and "grade" in records[n]
        ]
        if source == MUSIQUE:
            return [musique_pair(by_task)[QUALITY_AXES[source]]] if len(by_task) == 2 else []
        return [row[QUALITY_AXES[source]] for row in by_task] if len(by_task) == len(ids) else []

    def input_tokens(records: dict[int, dict[str, Any]], ids: list[int]) -> list[int]:
        return [
            token
            for tid in ids
            if tid in records
            and type(token := records[tid].get("costs", {}).get("reader_input_tokens")) is int
        ]

    # Each row remains one independent cluster, regardless of task count or model seed count.
    paired: dict[str, list[tuple[float, float, int, float, float, int]]] = defaultdict(list)
    baseline_n = len(baselines)
    for source, groups in registered.items():
        for ids in groups.values():
            peer_quality = [quality(arm, ids, source) for arm in [*baselines, *policy_runs]]
            peer_cost = [input_tokens(arm, ids) for arm in [*baselines, *policy_runs]]
            quality_n = len(peer_quality[0]) if all(peer_quality) else 0
            cost_n = len(ids) if all(len(row) == len(ids) for row in peer_cost) else 0
            paired[source].append(
                (
                    fmean(sum(row) for row in peer_quality[baseline_n:]) if quality_n else 0.0,
                    fmean(sum(row) for row in peer_quality[:baseline_n]) if quality_n else 0.0,
                    quality_n,
                    fmean(sum(row) for row in peer_cost[baseline_n:]) if cost_n else 0.0,
                    fmean(sum(row) for row in peer_cost[:baseline_n]) if cost_n else 0.0,
                    cost_n,
                )
            )

    def aggregate(
        grouped: dict[str, list[tuple[float, float, int, float, float, int]]],
    ) -> tuple[float | None, float | None, dict[str, dict[str, Any]]]:
        components: dict[str, dict[str, Any]] = {}
        for source, clusters in grouped.items():
            policy_q, baseline_q, qn, policy_c, baseline_c, cn = map(
                sum, zip(*clusters, strict=True)
            )
            components[source] = {
                "quality_delta": 100 * (policy_q - baseline_q) / qn if qn else None,
                "policy_input_tokens": policy_c / cn if cn else None,
                "baseline_input_tokens": baseline_c / cn if cn else None,
                "quality_units": int(qn),
                "cost_tasks": int(cn),
            }
        if not set(SOURCES) <= components.keys():
            return None, None, components
        score = (
            fmean(m["quality_delta"] for m in components.values())
            if all(m["quality_units"] for m in components.values())
            else None
        )
        savings = None
        if all(m["cost_tasks"] for m in components.values()):
            denom = fmean(m["baseline_input_tokens"] for m in components.values())
            if denom > 0:
                savings = 1 - fmean(m["policy_input_tokens"] for m in components.values()) / denom
        return score, savings, components

    point_quality, point_cost, strata = aggregate(paired)
    rng = random.Random(seed)  # noqa: S311 -- predeclared native-group bootstrap
    quality_draws, cost_draws = [], []
    for _ in range(repeats):
        sample = {source: rng.choices(groups, k=len(groups)) for source, groups in paired.items()}
        q, c, _ = aggregate(sample)
        if q is not None:
            quality_draws.append(q)
        if c is not None:
            cost_draws.append(c)
    quality_ci = [percentiles(quality_draws, p) for p in (0.025, 0.975)] if quality_draws else None
    cost_ci = [percentiles(cost_draws, p) for p in (0.025, 0.975)] if cost_draws else None
    full = set(strata) == set(SOURCES) and all(
        s["quality_units"]
        == (
            len(registered[source])
            if source == MUSIQUE
            else sum(len(ids) for ids in registered[source].values())
        )
        and s["cost_tasks"] == sum(len(ids) for ids in registered[source].values())
        for source, s in strata.items()
    )
    confirmed = (
        population["role"] == "confirm"
        and full
        and set(seed_labels) == set(population["confirmation_seeds"])
    )
    quality_supported = bool(confirmed and quality_ci and quality_ci[0] > 0)
    cost_supported = bool(
        confirmed
        and quality_ci
        and quality_ci[0] >= -population["quality_noninferiority_points"]
        and cost_ci
        and cost_ci[0] > 0
        and point_cost is not None
        and point_cost >= population["reader_input_savings_floor"]
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
        "independent_groups": {k: len(v) for k, v in registered.items()},
        "repeats": repeats,
        "bootstrap_seed": seed,
        "paired_measurements_complete": full,
        "quality_path_supported": quality_supported,
        "cost_path_supported": cost_supported,
        "seed_summaries": [summarize(path) for path in policy_roots],
        "baseline": (summarize(baseline_paths[0]) if len(baselines) == 1 else {
            "model_seeds": list(baseline_seeds),
            "seed_summaries": [summarize(path) for path in baseline_paths],
        }),
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
