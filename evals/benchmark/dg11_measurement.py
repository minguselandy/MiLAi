from __future__ import annotations

import math
import random
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any

from evals.scorers import score_normalized_em_f1_v1

SCORER_V2 = "DG11_NORMALIZED_EM_F1_V2_NUMERIC_DATE_UNIT_ABSTENTION"
_ABSTENTION = re.compile(
    r"^(?:unknown|unavailable|not known|cannot determine|cant determine|"
    r"could not determine|couldnt determine|insufficient (?:information|memory)|"
    r"i (?:do not|dont) know)$"
)
_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
_ONES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_UNITS = {
    "dollar": "usd",
    "dollars": "usd",
    "usd": "usd",
    "pound": "gbp",
    "pounds": "gbp",
    "gbp": "gbp",
    "euro": "eur",
    "euros": "eur",
    "eur": "eur",
    "minute": "min",
    "minutes": "min",
    "mins": "min",
    "hour": "hr",
    "hours": "hr",
    "hrs": "hr",
    "kilogram": "kg",
    "kilograms": "kg",
    "kgs": "kg",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
}


def _canonical_dates(value: str) -> str:
    def month_date(match: re.Match[str]) -> str:
        month = _MONTHS[match.group(1).casefold()]
        return f" {int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d} "

    value = re.sub(
        r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b",
        month_date,
        value,
        flags=re.IGNORECASE,
    )

    def numeric_date(match: re.Match[str]) -> str:
        first, second, year = (int(match.group(index)) for index in range(1, 4))
        if first > 12 or second > 31:
            return match.group(0)
        return f" {year:04d}-{first:02d}-{second:02d} "

    return re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", numeric_date, value)


def _number_words(tokens: Sequence[str]) -> list[str]:
    result: list[str] = []
    index = 0
    numeric = set(_ONES) | set(_TENS) | {"hundred", "thousand"}
    while index < len(tokens):
        if tokens[index] not in numeric:
            result.append(tokens[index])
            index += 1
            continue
        end = index
        current = 0
        total = 0
        while end < len(tokens) and tokens[end] in numeric | {"and"}:
            token = tokens[end]
            if token in _ONES:
                current += _ONES[token]
            elif token in _TENS:
                current += _TENS[token]
            elif token == "hundred":
                current = max(1, current) * 100
            elif token == "thousand":
                total += max(1, current) * 1000
                current = 0
            end += 1
        result.append(str(total + current))
        index = end
    return result


def normalize_v2(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold().strip()
    value = _canonical_dates(value)
    value = re.sub(r"\$\s*(\d+(?:\.\d+)?)", r"\1 usd", value)
    value = re.sub(r"£\s*(\d+(?:\.\d+)?)", r"\1 gbp", value)
    value = re.sub(r"€\s*(\d+(?:\.\d+)?)", r"\1 eur", value)
    value = value.replace("'", "")
    value = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in value
    )
    tokens = [token for token in value.split() if token not in {"a", "an", "the"}]
    normalized = " ".join(_number_words([_UNITS.get(token, token) for token in tokens]))
    return "unknown" if _ABSTENTION.fullmatch(normalized) else normalized


def _token_f1(prediction: str, answer: str) -> float:
    prediction_tokens = normalize_v2(prediction).split()
    answer_tokens = normalize_v2(answer).split()
    if not prediction_tokens or not answer_tokens:
        return float(prediction_tokens == answer_tokens)
    overlap = sum((Counter(prediction_tokens) & Counter(answer_tokens)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(prediction_tokens)
    recall = overlap / len(answer_tokens)
    return 2 * precision * recall / (precision + recall)


def score_v2(prediction: str, answers: Sequence[str]) -> dict[str, float | int | str]:
    if not answers:
        raise ValueError("answers cannot be empty")
    exact = max(int(normalize_v2(prediction) == normalize_v2(answer)) for answer in answers)
    f1 = max(_token_f1(prediction, answer) for answer in answers)
    return {
        "scorer": SCORER_V2,
        "exact_match": exact,
        "normalized_f1": round(f1, 6),
    }


def _is_unknown(answer: str) -> bool:
    return normalize_v2(answer) == "unknown"


def _certainty_class(answer: str, score: Mapping[str, Any]) -> str:
    if _is_unknown(answer):
        return "ABSTAINED"
    if int(score["exact_match"]) == 1:
        return "CORRECT_CERTAIN"
    if float(score["normalized_f1"]) > 0:
        return "PARTIAL_CERTAIN"
    return "WRONG_CERTAIN"


def answer_span_present(context: str, answers: Sequence[str]) -> bool:
    normalized_context = f" {normalize_v2(context)} "
    return any(
        normalized and f" {normalized} " in normalized_context
        for answer in answers
        if (normalized := normalize_v2(answer)) != "unknown"
    )


def _bootstrap_interval(values: Sequence[float], *, samples: int = 10_000) -> dict[str, float]:
    if not values:
        raise ValueError("paired values cannot be empty")
    rng = random.Random(11_000)
    estimates = sorted(
        mean(values[rng.randrange(len(values))] for _ in values) for _ in range(samples)
    )
    lower = estimates[math.floor(0.025 * (samples - 1))]
    upper = estimates[math.floor(0.975 * (samples - 1))]
    return {"lower95": round(lower, 6), "upper95": round(upper, 6)}


def recompute(
    records: Sequence[Mapping[str, Any]],
    *,
    relevant_sessions: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    if len(records) != 150:
        raise ValueError("DG-10 baseline must contain exactly 150 arm records")
    by_case: defaultdict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    enriched: list[dict[str, Any]] = []
    for source in records:
        record = dict(source)
        case_id = str(record["case_id"])
        arm = str(record["arm"])
        answers = [str(value) for value in record["gold_answers"]]
        v1 = score_normalized_em_f1_v1(str(record["answer"]), answers)
        v2 = score_v2(str(record["answer"]), answers)
        if v1 != record["score"]:
            raise ValueError("frozen scorer v1 cannot be reproduced")
        relevant = set(relevant_sessions.get(case_id.removeprefix("longmemeval:"), ()))
        retrieved = [str(value) for value in record["retrieved_session_ids"]]
        ranks = [index for index, value in enumerate(retrieved, start=1) if value in relevant]
        enriched_record = {
            "case_id": case_id,
            "category": str(record["category"]),
            "arm": arm,
            "scorer_v1": v1,
            "scorer_v2": v2,
            "retrieval_hit_at_k": float(record["retrieval_recall_at_k"]),
            "relevant_coverage_at_k": float(record["retrieval_relevant_coverage_at_k"]),
            "answer_session_rank": min(ranks) if ranks else None,
            "answer_span_present_after_compile": answer_span_present(
                str(record["memory_context"]), answers
            ),
            "unknown": _is_unknown(str(record["answer"])),
            "certainty_v1": _certainty_class(str(record["answer"]), v1),
            "certainty_v2": _certainty_class(str(record["answer"]), v2),
            "memory_tokens": int(record["memory_tokens"]),
            "prompt_tokens": int(record["prompt_tokens"]),
            "model_calls": int(record["model_calls"]),
            "hidden_model_calls": int(record["hidden_model_calls"]),
        }
        if arm in by_case[case_id]:
            raise ValueError("duplicate arm/case record")
        by_case[case_id][arm] = enriched_record
        enriched.append(enriched_record)
    if len(by_case) != 50 or any(
        set(arms) != {"NO_MEMORY", "NAIVE_RAG", "MILAI_T3A"}
        for arms in by_case.values()
    ):
        raise ValueError("DG-10 50-case three-arm denominator drifted")

    def aggregate(group: Sequence[Mapping[str, Any]], scorer: str) -> dict[str, Any]:
        return {
            "case_count": len(group),
            "exact_match_mean": round(mean(float(x[scorer]["exact_match"]) for x in group), 6),
            "normalized_f1_mean": round(
                mean(float(x[scorer]["normalized_f1"]) for x in group), 6
            ),
        }

    arms: dict[str, Any] = {}
    for arm in ("NO_MEMORY", "NAIVE_RAG", "MILAI_T3A"):
        group = [record for record in enriched if record["arm"] == arm]
        hits = [record for record in group if record["retrieval_hit_at_k"] == 1]
        ranks = [int(record["answer_session_rank"]) for record in group if record["answer_session_rank"]]
        arms[arm] = {
            "scorer_v1": aggregate(group, "scorer_v1"),
            "scorer_v2": aggregate(group, "scorer_v2"),
            "retrieval_hit_at_k_mean": round(mean(float(x["retrieval_hit_at_k"]) for x in group), 6),
            "relevant_coverage_at_k_mean": round(
                mean(float(x["relevant_coverage_at_k"]) for x in group), 6
            ),
            "answer_session_rank_mean_on_hit": round(mean(ranks), 6) if ranks else None,
            "answer_span_survival_on_hit": round(
                mean(float(x["answer_span_present_after_compile"]) for x in hits), 6
            )
            if hits
            else None,
            "hit_and_v1_f1_zero_count": sum(
                x["retrieval_hit_at_k"] == 1
                and float(x["scorer_v1"]["normalized_f1"]) == 0
                for x in group
            ),
            "hit_and_answer_span_missing_count": sum(
                x["retrieval_hit_at_k"] == 1
                and not x["answer_span_present_after_compile"]
                for x in group
            ),
            "unknown_count": sum(bool(x["unknown"]) for x in group),
            "wrong_certain_v1_count": sum(x["certainty_v1"] == "WRONG_CERTAIN" for x in group),
            "wrong_certain_v2_count": sum(x["certainty_v2"] == "WRONG_CERTAIN" for x in group),
            "memory_tokens_mean": round(mean(int(x["memory_tokens"]) for x in group), 6),
            "memory_tokens_max": max(int(x["memory_tokens"]) for x in group),
        }

    paired: dict[str, Any] = {}
    for scorer in ("scorer_v1", "scorer_v2"):
        values = [
            float(arms_for_case["MILAI_T3A"][scorer]["normalized_f1"])
            - float(arms_for_case["NAIVE_RAG"][scorer]["normalized_f1"])
            for arms_for_case in by_case.values()
        ]
        paired[scorer] = {
            "milai_minus_naive_rag_f1_mean": round(mean(values), 6),
            "bootstrap": _bootstrap_interval(values),
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "ties": sum(value == 0 for value in values),
        }

    category: dict[str, Any] = {}
    for name in sorted({str(record["category"]) for record in enriched}):
        milai = [record for record in enriched if record["category"] == name and record["arm"] == "MILAI_T3A"]
        category[name] = {
            "case_count": len(milai),
            "scorer_v1": aggregate(milai, "scorer_v1"),
            "scorer_v2": aggregate(milai, "scorer_v2"),
            "retrieval_hit_at_k_mean": round(mean(float(x["retrieval_hit_at_k"]) for x in milai), 6),
            "relevant_coverage_at_k_mean": round(
                mean(float(x["relevant_coverage_at_k"]) for x in milai), 6
            ),
            "answer_span_survival_on_hit": round(
                mean(
                    float(x["answer_span_present_after_compile"])
                    for x in milai
                    if x["retrieval_hit_at_k"] == 1
                ),
                6,
            )
            if any(x["retrieval_hit_at_k"] == 1 for x in milai)
            else None,
        }
    return {
        "case_count": len(by_case),
        "record_count": len(enriched),
        "arms": arms,
        "paired": paired,
        "category": category,
        "records": enriched,
        "provider_requests": 0,
    }
