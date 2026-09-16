"""Official-label HorizonBench accuracy and paired statistics."""

from __future__ import annotations

import random
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any

SCORER_ID = "HORIZON_OFFICIAL_EXTRACT_LETTER_ACCURACY_V1"
_LETTER = re.compile(r"\b([A-E])\b")


class HorizonScorerError(RuntimeError):
    pass


def extract_letter(response: str) -> str:
    """Match the released evaluator's first-letter/fallback-regex behavior."""

    text = response.strip()
    if text and text[0] in "ABCDE":
        return text[0]
    match = _LETTER.search(text)
    return match.group(1) if match else ""


def _bootstrap_mean_ci(
    values: Sequence[float], *, seed: int, samples: int = 10_000
) -> tuple[float, float]:
    if not values:
        raise HorizonScorerError("cannot bootstrap an empty Horizon stratum")
    rng = random.Random(seed)
    size = len(values)
    estimates = sorted(
        mean(values[rng.randrange(size)] for _ in range(size))
        for _ in range(samples)
    )
    return estimates[int(samples * 0.025)], estimates[int(samples * 0.975) - 1]


def aggregate(
    *,
    labels: Sequence[Mapping[str, Any]],
    generations: Sequence[Mapping[str, Any]],
    methods: Sequence[str],
    bootstrap_seed: int = 20_260_824,
) -> dict[str, Any]:
    label_by_id: dict[str, Mapping[str, Any]] = {}
    for row in labels:
        case_id = row.get("case_id")
        if (
            not isinstance(case_id, str)
            or row.get("correct_letter") not in set("ABCDE")
            or row.get("distractor_letter") not in set("ABCDE")
            or not isinstance(row.get("has_evolved"), bool)
            or not isinstance(row.get("generator"), str)
            or case_id in label_by_id
        ):
            raise HorizonScorerError("Horizon label contract drifted")
        label_by_id[case_id] = row
    if not label_by_id or not methods or len(set(methods)) != len(methods):
        raise HorizonScorerError("Horizon denominator or method list is empty")
    expected = {(case_id, method) for case_id in label_by_id for method in methods}
    generation_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in generations:
        key = (str(row.get("case_id")), str(row.get("method_id")))
        if key not in expected or key in generation_by_key:
            raise HorizonScorerError("Horizon generation identity drifted")
        if not isinstance(row.get("answer"), str):
            raise HorizonScorerError("Horizon answer is absent")
        generation_by_key[key] = row
    if set(generation_by_key) != expected:
        raise HorizonScorerError("Horizon generation denominator is incomplete")
    per_case = []
    for method in methods:
        for case_id, label in label_by_id.items():
            answer = str(generation_by_key[(case_id, method)]["answer"])
            predicted = extract_letter(answer)
            correct = predicted == label["correct_letter"]
            per_case.append(
                {
                    "case_id": case_id,
                    "correct": correct,
                    "generator": label["generator"],
                    "hard_negative_selected": (
                        bool(label["has_evolved"])
                        and predicted == label["distractor_letter"]
                    ),
                    "has_evolved": label["has_evolved"],
                    "method_id": method,
                    "predicted_letter": predicted,
                    "response_valid": predicted in set("ABCDE"),
                }
            )
    by_method: dict[str, Any] = {}
    rows_by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_case:
        rows_by_method[str(row["method_id"])].append(row)
    for method_ordinal, method in enumerate(methods):
        rows = rows_by_method[method]
        values = [float(row["correct"]) for row in rows]
        low, high = _bootstrap_mean_ci(
            values, seed=bootstrap_seed + method_ordinal
        )
        evolved = [row for row in rows if row["has_evolved"] is True]
        static = [row for row in rows if row["has_evolved"] is False]
        by_method[method] = {
            "accuracy": mean(values),
            "accuracy_bootstrap_95_ci": [low, high],
            "accuracy_by_evolution": {
                "evolved": mean(float(row["correct"]) for row in evolved),
                "static": mean(float(row["correct"]) for row in static),
            },
            "accuracy_by_generator": {
                generator: mean(
                    float(row["correct"])
                    for row in rows
                    if row["generator"] == generator
                )
                for generator in sorted({str(row["generator"]) for row in rows})
            },
            "case_count": len(rows),
            "evolved_hard_negative_rate": mean(
                float(row["hard_negative_selected"]) for row in evolved
            ),
            "invalid_response_rate": mean(
                float(not row["response_valid"]) for row in rows
            ),
        }
    paired = {}
    reference = methods[0]
    reference_by_case = {
        str(row["case_id"]): float(row["correct"])
        for row in rows_by_method[reference]
    }
    for method_ordinal, method in enumerate(methods[1:], start=1):
        deltas = [
            float(row["correct"]) - reference_by_case[str(row["case_id"])]
            for row in rows_by_method[method]
        ]
        low, high = _bootstrap_mean_ci(
            deltas, seed=bootstrap_seed + 100 + method_ordinal
        )
        paired[f"{method}-minus-{reference}"] = {
            "accuracy_delta": mean(deltas),
            "paired_bootstrap_95_ci": [low, high],
        }
    return {
        "bootstrap_samples": 10_000,
        "bootstrap_seed": bootstrap_seed,
        "by_method": by_method,
        "case_count": len(label_by_id),
        "methods": list(methods),
        "paired_against_first_method": paired,
        "per_case": per_case,
        "scorer_id": SCORER_ID,
        "schema": "milai.dg11.paper-horizon-metrics.v1",
    }
