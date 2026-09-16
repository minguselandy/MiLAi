from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any

from evals.benchmark import dg11_holdout, dg11_measurement
from scripts import run_dg10_benchmark_dev_smoke as scorer_v1

ARMS = (
    "CTRL_NO_MEMORY",
    "CTRL_CUSTOM_LEXICAL_TOP1",
    "MILAI_DG10_FROZEN",
    "MILAI_DG11_FROZEN",
)
CASE_COUNT = 100
GENERATION_SEED_NAMESPACE = "dg11-generalization-v2-v1"


def schedule(case_index: int) -> tuple[str, ...]:
    if case_index < 0:
        raise ValueError("case_index must be non-negative")
    offset = case_index % len(ARMS)
    return ARMS[offset:] + ARMS[:offset]


def generation_id(case_index: int, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError("unknown generalization-v2 arm")
    return f"{GENERATION_SEED_NAMESPACE}-{case_index + 1:03d}-{arm.casefold()}"


def score_records(
    generation_records: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    if len(generation_records) != CASE_COUNT * len(ARMS):
        raise dg11_holdout.HoldoutError("v2 generation denominator is not 400")
    by_case: defaultdict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    scored: list[dict[str, Any]] = []
    for source in generation_records:
        source_id = str(source["source_id"])
        arm = str(source["arm"])
        answers = labels.get(source_id)
        if not answers:
            raise dg11_holdout.HoldoutError("a v2 case has no sealed label")
        if arm not in ARMS or arm in by_case[source_id]:
            raise dg11_holdout.HoldoutError("duplicate or unknown v2 arm/case")
        answer = str(source["answer"])
        record = {
            **source,
            "scorer_v1": scorer_v1._score(answer, list(answers)),
            "scorer_v2": dg11_measurement.score_v2(answer, list(answers)),
        }
        by_case[source_id][arm] = record
        scored.append(record)
    if len(by_case) != CASE_COUNT or any(
        set(case) != set(ARMS) for case in by_case.values()
    ):
        raise dg11_holdout.HoldoutError("v2 four-arm case matrix is incomplete")

    arms = {
        arm: {
            scorer: dg11_holdout._aggregate(
                [record for record in scored if record["arm"] == arm], scorer
            )
            for scorer in ("scorer_v1", "scorer_v2")
        }
        for arm in ARMS
    }
    categories: dict[str, Any] = {}
    for category in sorted({str(record["category"]) for record in scored}):
        categories[category] = {
            arm: {
                scorer: dg11_holdout._aggregate(
                    [
                        record
                        for record in scored
                        if record["category"] == category and record["arm"] == arm
                    ],
                    scorer,
                )
                for scorer in ("scorer_v1", "scorer_v2")
            }
            for arm in ARMS
        }

    paired: dict[str, Any] = {}
    for scorer in ("scorer_v1", "scorer_v2"):
        values = [
            float(case["MILAI_DG11_FROZEN"][scorer]["normalized_f1"])
            - float(case["MILAI_DG10_FROZEN"][scorer]["normalized_f1"])
            for case in by_case.values()
        ]
        paired[scorer] = {
            "dg11_minus_dg10_f1_mean": round(mean(values), 6),
            "bootstrap": dg11_measurement._bootstrap_interval(values),
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "ties": sum(value == 0 for value in values),
        }
    return {
        "arms": arms,
        "categories": categories,
        "paired": paired,
        "records": scored,
    }


def category_delta(
    scored: Mapping[str, Any], category: str, left: str, right: str
) -> float:
    values = scored["categories"].get(category)
    if not isinstance(values, Mapping):
        raise dg11_holdout.HoldoutError(f"required v2 category is absent: {category}")
    return round(
        float(values[left]["scorer_v1"]["normalized_f1_mean"])
        - float(values[right]["scorer_v1"]["normalized_f1_mean"]),
        6,
    )


def schedule_identity() -> str:
    schedules = [list(schedule(index)) for index in range(CASE_COUNT)]
    return hashlib.sha256(dg11_holdout.canonical(schedules)).hexdigest()
