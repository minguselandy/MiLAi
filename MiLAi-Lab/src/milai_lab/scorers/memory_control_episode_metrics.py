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
    baseline_root: Path,
    *,
    repeats: int = 2000,
    seed: int = 20261118,
) -> dict[str, Any]:
    if not policy_roots or repeats < 1:
        raise ValueError("Provide actual policy runs and a positive bootstrap count")
    base_protocol, baseline = input_result(baseline_root)
    population = base_protocol["population"]
    policy_runs, seed_labels = [], []
    for path in policy_roots:
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
        policy_runs.append(predictions)
        seed_labels.append(protocol["arm"].get("seed"))
    if len(seed_labels) > 1 and len(set(seed_labels)) != len(seed_labels):
        raise ValueError("Distinct fitted seed IDs are required for multi-seed aggregation")
    registered: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for row in population["tasks"]:
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
    for source, groups in registered.items():
        for ids in groups.values():
            peer_quality = [quality(arm, ids, source) for arm in [baseline, *policy_runs]]
            peer_cost = [input_tokens(arm, ids) for arm in [baseline, *policy_runs]]
            quality_n = len(peer_quality[0]) if all(peer_quality) else 0
            cost_n = len(ids) if all(len(row) == len(ids) for row in peer_cost) else 0
            paired[source].append(
                (
                    fmean(sum(row) for row in peer_quality[1:]) if quality_n else 0.0,
                    sum(peer_quality[0]) if quality_n else 0.0,
                    quality_n,
                    fmean(sum(row) for row in peer_cost[1:]) if cost_n else 0.0,
                    sum(peer_cost[0]) if cost_n else 0.0,
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
        population["role"] == "confirm" and full
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
        "model_seeds": seed_labels,
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
        "baseline": summarize(baseline_root),
    }
