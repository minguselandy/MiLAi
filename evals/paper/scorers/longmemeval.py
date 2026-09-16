"""Deterministic LongMemEval EM/F1 and retrieval metrics."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

SCORER_ID = "DG11_PAPER_DETERMINISTIC_NORMALIZED_EM_F1_V1"


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    text = text.replace("'", "")
    text = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in text
    )
    tokens = [token for token in text.split() if token not in {"a", "an", "the"}]
    return " ".join(tokens)


def _f1(prediction: str, answer: str) -> float:
    predicted = normalize(prediction).split()
    expected = normalize(answer).split()
    if not predicted or not expected:
        return float(predicted == expected)
    overlap = sum((Counter(predicted) & Counter(expected)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(predicted)
    recall = overlap / len(expected)
    return 2 * precision * recall / (precision + recall)


def score_answer(
    prediction: str, answers: Sequence[str]
) -> dict[str, float | int | str]:
    if not answers:
        raise ValueError("answer labels cannot be empty")
    exact = max(int(normalize(prediction) == normalize(answer)) for answer in answers)
    f1 = max(_f1(prediction, answer) for answer in answers)
    return {
        "exact_match": exact,
        "normalized_f1": round(f1, 9),
        "scorer": SCORER_ID,
    }


def _trace_session_id(item: Mapping[str, Any]) -> str | None:
    explicit = item.get("session_id")
    if isinstance(explicit, str):
        return explicit
    source = item.get("source_id")
    if not isinstance(source, str):
        return None
    return re.sub(r"(?::\d+|_\d+)$", "", source)


def score_retrieval(
    trace: Sequence[Mapping[str, Any]], relevant_session_ids: Sequence[str]
) -> dict[str, float | int]:
    relevant = set(relevant_session_ids)
    ranked = [value for item in trace if (value := _trace_session_id(item)) is not None]
    unique_ranked = list(dict.fromkeys(ranked))
    hits = relevant.intersection(unique_ranked)
    hit = int(bool(hits))
    recall = len(hits) / len(relevant) if relevant else 0.0
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, session_id in enumerate(unique_ranked)
        if session_id in relevant
    )
    ideal = sum(
        1.0 / math.log2(index + 2)
        for index in range(min(len(relevant), len(unique_ranked)))
    )
    return {
        "hit_at_k": hit,
        "ndcg_at_k": round(dcg / ideal, 9) if ideal else 0.0,
        "relevant_coverage_at_k": round(recall, 9),
        "retrieved_k": len(unique_ranked),
    }
