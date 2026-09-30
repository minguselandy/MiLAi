"""Offline equal-base paired cluster analysis; never scores or starts model calls.

Input keeps a predeclared plan (base metadata, conditions, methods) separate from
actual rows. An absent planned row stays missing. Source/template components are
transitive across the whole plan; seeds/variants belong to their base task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

COSTS = (
    "generation_requests", "charged_generation_tokens", "known_generation_tokens",
    "embedding_requests", "charged_embedding_tokens", "known_embedding_tokens",
    "generation_unknown_usage", "embedding_unknown_usage",
)


def components(bases: list[dict[str, Any]]) -> dict[str, str]:
    parent = {b["base_id"]: b["base_id"] for b in bases}
    if len(parent) != len(bases):
        raise ValueError("Duplicate base task in the predeclared plan")

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    seen: dict[tuple[str, str], str] = {}
    for base in bases:
        for kind in ("source_components", "template_families"):
            if not isinstance(base.get(kind), list) or not base[kind]:
                raise ValueError("Predeclared source and task-family metadata lists required")
            for value in base[kind]:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Blank dependency identifiers are invalid")
                node = (kind, value)
                if node in seen:
                    parent[find(base["base_id"])] = find(seen[node])
                seen[node] = base["base_id"]
    members: dict[str, list[str]] = {}
    for key in parent:
        members.setdefault(find(key), []).append(key)
    canonical = {root: min(keys) for root, keys in members.items()}
    return {key: canonical[find(key)] for key in parent}


def analyze(payload: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    if payload["stage"] not in ("development", "pilot", "formal"):
        raise ValueError("Stage must be development, pilot or formal")
    plan = payload["plan"]
    if type(plan["requires_independent_rating"]) is not bool:
        raise ValueError("requires_independent_rating must be a boolean")
    if not isinstance(plan["metric"], str) or not plan["metric"].strip():
        raise ValueError("The outcome metric must be predeclared")
    bases = plan["bases"]
    if not isinstance(bases, list) or not isinstance(plan["methods"], list):
        raise ValueError("bases and methods must be lists")
    for value in plan["methods"]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A method must have a nonblank identifier")
    if not plan["methods"] or len(set(plan["methods"])) != len(plan["methods"]):
        raise ValueError("Methods must be nonempty and unique")
    for base in bases:
        for field in ("base_id", "workflow"):
            if not isinstance(base[field], str) or not base[field].strip():
                raise ValueError("Base task and workflow identifiers must be nonblank")
        if not isinstance(base["variants"], list) or not base["variants"]:
            raise ValueError("Every base task must declare at least one variant")
        for variant in base["variants"]:
            if not isinstance(variant["condition"], str) or not variant["condition"].strip():
                raise ValueError("Every variant must declare its condition")
            if type(variant["replicate"]) not in (str, int) or not str(variant["replicate"]):
                raise ValueError("Replicate must be a nonblank string or integer")
    cluster = components(bases)
    metadata = {base["base_id"]: base for base in bases}
    planned = {
        (b["base_id"], v["condition"], str(v["replicate"]), method)
        for b in bases for v in b["variants"] for method in plan["methods"]
    }
    expected_count = sum(len(b["variants"]) * len(plan["methods"]) for b in bases)
    if len(planned) != expected_count:
        raise ValueError("Duplicate planned variant or method")
    actual = {}
    for row in payload["rows"]:
        key = (row["base_id"], row["condition"], str(row["replicate"]), row["method"])
        if key not in planned or key in actual:
            raise ValueError("Unplanned or duplicated actual result; no best-result selection")
        utility = row.get("utility")
        if utility is not None and (type(utility) not in (bool, int, float)
                                    or not 0 <= utility <= 1):
            raise ValueError("Utility must be declared [0,1] or null")
        if type(row.get("independent_rating", False)) is not bool:
            raise ValueError("independent_rating must be a boolean")
        for cost in COSTS:
            value = row.get("costs", {}).get(cost)
            if value is not None and (type(value) not in (int, float)
                                      or not math.isfinite(value) or value < 0):
                raise ValueError("Cost must be finite nonnegative or null")
        actual[key] = row

    strata = sorted({(b["workflow"], v["condition"]) for b in bases for v in b["variants"]})
    comparisons = [design["primary_comparison"], design["secondary_comparison"]]
    results = []
    for workflow, condition in strata:
        for left, right in comparisons:
            if left not in plan["methods"] or right not in plan["methods"]:
                continue
            base_values, missing, review_ok, binary = {}, 0, True, True
            scorable_deltas, unknown_cost_rows = [], 0
            for base_id, base in metadata.items():
                variants = [v for v in base["variants"] if v["condition"] == condition]
                if base["workflow"] != workflow or not variants:
                    continue
                values = []
                for variant in variants:
                    pair = [actual.get((base_id, condition, str(variant["replicate"]), m), {})
                            for m in (left, right)]
                    utilities = [r.get("utility") for r in pair]
                    binary &= all(u is None or u in (0, 1) for u in utilities)
                    missing += sum(u is None for u in utilities)
                    review_ok &= all(r.get("independent_rating") is True for r in pair)
                    bounds = [(0.0, 1.0) if u is None else (float(u), float(u))
                              for u in utilities]
                    point = (np.nan if None in utilities
                             else float(utilities[0]) - float(utilities[1]))
                    if not np.isnan(point):
                        scorable_deltas.append((base_id, point))
                    costs = []
                    for cost in COSTS:
                        x, y = [r.get("costs", {}).get(cost) for r in pair]
                        costs.append(np.nan if x is None or y is None else float(x) - float(y))
                    unknown_cost_rows += sum(
                        any(r.get("costs", {}).get(k) is None for k in COSTS)
                        or any(r.get("costs", {}).get(k) not in (0, 0.0) for k in
                            ("generation_unknown_usage", "embedding_unknown_usage"))
                        for r in pair
                    )
                    values.append([point, bounds[0][0] - bounds[1][1],
                                   bounds[0][1] - bounds[1][0], *costs, *bounds[0], *bounds[1]])
                base_values[base_id] = np.asarray(values).mean(axis=0)
            matrix = np.stack(list(base_values.values()))
            group_ids = [cluster[k] for k in base_values]
            groups = sorted(set(group_ids))
            point = matrix.mean(axis=0)
            n = len(groups)
            intervals = None
            draw_sha = None
            if n >= design["bootstrap"]["minimum_clusters_for_inferential_claim"]:
                aggregates = np.stack([
                    matrix[np.asarray(group_ids) == g].sum(axis=0) for g in groups
                ])
                counts = np.asarray([group_ids.count(g) for g in groups])
                rng = np.random.default_rng(design["bootstrap"]["seed"])
                draws = rng.integers(n, size=(design["bootstrap"]["replicates"], n))
                # One cluster draw is shared by every utility-bound and cost column.
                boot = aggregates[draws].sum(axis=1) / counts[draws].sum(axis=1)[:, None]
                intervals = np.quantile(boot, [0.025, 0.975], axis=0)
                draw_sha = hashlib.sha256(draws.tobytes()).hexdigest()

            def number(value: Any) -> float | None:
                return None if not np.isfinite(value) else float(value)

            def interval(column: int, limits: Any = intervals) -> list[float] | None:
                if limits is None or not np.isfinite(limits[:, column]).all():
                    return None
                return [float(v) for v in limits[:, column]]

            complete_base = {}
            for base_id, value in scorable_deltas:
                complete_base.setdefault(base_id, []).append(value)
            lower = None if intervals is None else number(intervals[0, 1])
            inferential = (n >= design["bootstrap"]["minimum_clusters_for_inferential_claim"]
                           and (review_ok or not plan["requires_independent_rating"])
                           and payload["stage"] == "formal")
            ni = (condition == "clean" and [left, right] == design["primary_comparison"]
                  and plan["metric"] == "task_lifecycle_success" and binary
                  and inferential and plan["requires_independent_rating"] and review_ok
                  and lower is not None
                  and lower >= -design["clean_noninferiority"]["margin_pp"] / 100)
            results.append({
                "workflow": workflow, "condition": condition, "comparison": [left, right],
                "metric": plan["metric"],
                "planned_base_tasks": len(base_values), "independent_components": n,
                "missing_utility_arm_rows": missing,
                "unknown_or_missing_cost_arm_rows": unknown_cost_rows,
                "allplanned_utility_difference": number(point[0]),
                "allplanned_utility_difference_bounds": [number(point[1]), number(point[2])],
                "allplanned_arm_utility_bounds": {
                    method: [number(point[3 + len(COSTS) + 2 * i + j]) for j in (0, 1)]
                    for i, method in enumerate((left, right))},
                "utility_difference_interval": interval(0),
                "worstcase_missing_lower_interval": interval(1),
                "worstcase_missing_upper_interval": interval(2),
                "scorable_pairs_only_equal_base_difference": (
                    float(np.mean([np.mean(v) for v in complete_base.values()]))
                    if complete_base else None),
                "scorable_pairs_only_base_count": len(complete_base),
                "cost_differences": {k: {"allplanned_mean": number(point[3 + i]),
                                        "interval": interval(3 + i)} for i, k in enumerate(COSTS)},
                "shared_bootstrap_draw_sha256": draw_sha,
                "independent_rating_required_for_declared_metric": (
                    plan["requires_independent_rating"]),
                "independent_rating_gate_satisfied": review_ok,
                "inferential_claim_admitted": inferential,
                "clean_5pp_noninferiority": (
                    "ESTABLISHED_UNDER_DECLARED_PROTOCOL" if ni else "NOT_ESTABLISHED"),
                "qualification": "Small component counts are descriptive. Missing is not zero. "
                "Charged/known costs stay separate; no dollar/GPU estimate. Bootstrap intervals "
                "describe observed variation and do not establish zero failure risk. Metadata "
                "timing, dependency validity, independent review and complete ledger allocation "
                "must be verified externally; declared booleans are not evidence of independence.",
            })
    return {"kind": "V13_2_OFFLINE_PAIRED_CLUSTER_ANALYSIS", "stage": payload["stage"],
            "planned_rows": len(planned), "actual_rows": len(actual),
            "missing_rows": len(planned) - len(actual),
            "source_dependency_components": len(set(cluster.values())), "results": results,
            "plan_sha256": hashlib.sha256(json.dumps(
                plan, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()).hexdigest(),
            "generation_requests": 0, "embedding_requests": 0, "product": "NO_GO"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(json.loads(args.input.read_text()), json.loads(args.design.read_text()))
    result["input_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    result["design_sha256"] = hashlib.sha256(args.design.read_bytes()).hexdigest()
    result["analyzer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("planned_rows", "actual_rows", "missing_rows")}))


if __name__ == "__main__":
    main()
