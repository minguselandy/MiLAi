from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from evals.benchmark import dg11_measurement
from evals.benchmark import lme_product_smoke as benchmark
from scripts import run_dg10_benchmark_dev_smoke as scorer_v1

ARMS = (
    "NO_MEMORY",
    "NAIVE_RAG",
    "MILAI_DG10_FROZEN",
    "MILAI_DG11_CURRENT",
)
CASE_COUNT = 100
GENERATION_SEED_NAMESPACE = "dg11-sealed-holdout-v1"
SPLIT_SEED = "dg11-sealed-holdout-split-v1"


class HoldoutError(RuntimeError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def consumed_source_ids() -> set[str]:
    return set(benchmark.SMOKE_SOURCE_IDS).union(
        benchmark.DEV_SOURCE_IDS,
        benchmark.CONSUMED_CONFIRMATION_V1_SOURCE_IDS,
        benchmark.CONSUMED_CONFIRMATION_V2_SOURCE_IDS,
        benchmark.CONFIRMATION_SOURCE_IDS,
    )


def _stable_rank(source_id: str) -> str:
    return hashlib.sha256(f"{SPLIT_SEED}:{source_id}".encode()).hexdigest()


def stratified_source_ids(
    rows: Sequence[Mapping[str, Any]], *, count: int = CASE_COUNT
) -> tuple[tuple[str, ...], dict[str, int]]:
    excluded = consumed_source_ids()
    by_category: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        source_id = row.get("question_id")
        category = row.get("question_type")
        if (
            isinstance(source_id, str)
            and source_id not in excluded
            and isinstance(category, str)
            and category
        ):
            by_category[category].append(source_id)
    if len(set().union(*map(set, by_category.values()))) < count:
        raise HoldoutError("fewer than 100 unused LongMemEval cases remain")
    for source_ids in by_category.values():
        source_ids.sort(key=_stable_rank)

    eligible = sum(len(source_ids) for source_ids in by_category.values())
    raw = {
        category: count * len(source_ids) / eligible
        for category, source_ids in by_category.items()
    }
    allocation = {category: int(value) for category, value in raw.items()}
    remainder = count - sum(allocation.values())
    remainder_order = sorted(
        by_category,
        key=lambda category: (-(raw[category] - allocation[category]), category),
    )
    for category in remainder_order[:remainder]:
        allocation[category] += 1
    if any(allocation[category] > len(by_category[category]) for category in allocation):
        raise HoldoutError("stratified allocation exceeds an eligible category")

    selected = {
        category: deque(source_ids[: allocation[category]])
        for category, source_ids in sorted(by_category.items())
    }
    ordered: list[str] = []
    categories = list(selected)
    while len(ordered) < count:
        progressed = False
        for category in categories:
            if selected[category]:
                ordered.append(selected[category].popleft())
                progressed = True
        if not progressed:
            break
    if len(ordered) != count or len(set(ordered)) != count:
        raise HoldoutError("stratified selection denominator drifted")
    return tuple(ordered), dict(sorted(allocation.items()))


def label_free_inputs(
    rows: Sequence[Mapping[str, Any]], source_ids: Sequence[str]
) -> dict[str, Any]:
    selected = set(source_ids)
    inputs: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = row.get("question_id")
        if source_id not in selected:
            continue
        sessions = row.get("haystack_sessions")
        session_ids = row.get("haystack_session_ids")
        dates = row.get("haystack_dates")
        if (
            not isinstance(source_id, str)
            or not isinstance(row.get("question"), str)
            or not isinstance(row.get("question_type"), str)
            or not isinstance(row.get("question_date"), str)
            or not isinstance(sessions, list)
            or not isinstance(session_ids, list)
            or not isinstance(dates, list)
            or len(sessions) != len(session_ids)
            or len(sessions) != len(dates)
        ):
            raise HoldoutError("selected LongMemEval input contract failed")
        inputs[source_id] = {
            "source_id": source_id,
            "category": row["question_type"],
            "question": row["question"],
            "question_date": row["question_date"],
            "sessions": [
                {
                    "session_id": str(session_id),
                    "observed_at": str(observed_at),
                    "text": scorer_v1._session_text(session),
                }
                for session_id, observed_at, session in zip(
                    session_ids, dates, sessions, strict=True
                )
            ],
        }
    if set(inputs) != selected:
        raise HoldoutError("label-free holdout input package is incomplete")
    ordered = [inputs[source_id] for source_id in source_ids]
    payload = {
        "schema": "milai.dg11.holdout-inputs.v1",
        "label_fields_present": False,
        "source_ids": list(source_ids),
        "cases": ordered,
    }
    forbidden = {"answer", "answers", "answer_session_ids", "gold_answers"}
    if any(forbidden.intersection(case) for case in ordered):
        raise HoldoutError("label field leaked into holdout input package")
    return payload


def parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise HoldoutError("holdout timestamp is invalid")
    try:
        return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)
    except ValueError as exc:
        raise HoldoutError("holdout timestamp contract failed") from exc


def product_case(value: Mapping[str, Any]) -> benchmark.ProductSmokeCase:
    sessions = value.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise HoldoutError("holdout case sessions are absent")
    source_id = str(value["source_id"])
    return benchmark.ProductSmokeCase(
        case_id=f"longmemeval:{source_id}",
        source_case_id=source_id,
        dataset="LONGMEMEVAL_CLEANED_500",
        category=str(value["category"]),
        question=str(value["question"]),
        answers=(),
        sessions=tuple(
            (str(session["session_id"]), str(session["text"]))
            for session in sessions
        ),
        question_at=parse_datetime(value["question_date"]),
        session_observed_at=tuple(
            parse_datetime(session["observed_at"]) for session in sessions
        ),
    )


def schedule(case_index: int) -> tuple[str, ...]:
    if case_index < 0:
        raise ValueError("case_index must be non-negative")
    offset = case_index % len(ARMS)
    return ARMS[offset:] + ARMS[:offset]


def generation_id(case_index: int, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError("unknown holdout arm")
    return f"{GENERATION_SEED_NAMESPACE}-{case_index + 1:03d}-{arm.casefold()}"


def _aggregate(records: Sequence[Mapping[str, Any]], scorer: str) -> dict[str, Any]:
    if not records:
        raise HoldoutError("cannot aggregate an empty record group")
    return {
        "case_count": len(records),
        "exact_match_mean": round(
            mean(float(record[scorer]["exact_match"]) for record in records), 6
        ),
        "normalized_f1_mean": round(
            mean(float(record[scorer]["normalized_f1"]) for record in records), 6
        ),
        "prompt_tokens_mean": round(
            mean(int(record["prompt_tokens"]) for record in records), 3
        ),
    }


def score_records(
    generation_records: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    if len(generation_records) != CASE_COUNT * len(ARMS):
        raise HoldoutError("holdout generation denominator is not 400")
    by_case: defaultdict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    scored: list[dict[str, Any]] = []
    for source in generation_records:
        source_id = str(source["source_id"])
        arm = str(source["arm"])
        answers = labels.get(source_id)
        if not answers:
            raise HoldoutError("a generated case has no sealed label")
        answer = str(source["answer"])
        record = {
            **source,
            "scorer_v1": scorer_v1._score(answer, list(answers)),
            "scorer_v2": dg11_measurement.score_v2(answer, list(answers)),
        }
        if arm in by_case[source_id]:
            raise HoldoutError("duplicate arm/case generation record")
        by_case[source_id][arm] = record
        scored.append(record)
    if len(by_case) != CASE_COUNT or any(set(value) != set(ARMS) for value in by_case.values()):
        raise HoldoutError("holdout four-arm case matrix is incomplete")

    arms = {
        arm: {
            scorer: _aggregate(
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
                scorer: _aggregate(
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
            float(case["MILAI_DG11_CURRENT"][scorer]["normalized_f1"])
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
    if not isinstance(values, dict):
        raise HoldoutError(f"required holdout category is absent: {category}")
    return round(
        float(values[left]["scorer_v1"]["normalized_f1_mean"])
        - float(values[right]["scorer_v1"]["normalized_f1_mean"]),
        6,
    )


def allocation_from_inputs(inputs: Mapping[str, Any]) -> dict[str, int]:
    cases = inputs.get("cases")
    if not isinstance(cases, list):
        raise HoldoutError("holdout input cases are invalid")
    return dict(sorted(Counter(str(case["category"]) for case in cases).items()))
