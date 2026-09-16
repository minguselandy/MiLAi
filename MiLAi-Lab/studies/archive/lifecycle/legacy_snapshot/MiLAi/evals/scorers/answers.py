from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Sequence


class ScoringInputError(ValueError):
    pass


def answer_values(value: object) -> tuple[str, ...]:
    """Normalize a scalar or multi-span answer into non-empty strings."""
    if isinstance(value, str) and value.strip():
        return (value,)
    if isinstance(value, int) and not isinstance(value, bool):
        return (str(value),)
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item.strip() for item in value)
    ):
        return tuple(value)
    raise ScoringInputError("answer must be a non-empty string, integer, or string list")


def _normalize_answer(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    value = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in value
    )
    return " ".join(token for token in value.split() if token not in {"a", "an", "the"})


def score_normalized_em_f1_v1(
    prediction: str, answers: Sequence[str]
) -> dict[str, float | int | str]:
    prediction_tokens = _normalize_answer(prediction).split()

    def f1(answer: str) -> float:
        answer_tokens = _normalize_answer(answer).split()
        if not prediction_tokens or not answer_tokens:
            return float(prediction_tokens == answer_tokens)
        overlap = sum((Counter(prediction_tokens) & Counter(answer_tokens)).values())
        if overlap == 0:
            return 0.0
        precision = overlap / len(prediction_tokens)
        recall = overlap / len(answer_tokens)
        return 2 * precision * recall / (precision + recall)

    exact = max(
        int(_normalize_answer(prediction) == _normalize_answer(answer)) for answer in answers
    )
    return {
        "scorer": "DG10_LOCAL_DEV_SMOKE_NORMALIZED_EM_F1_V1_NOT_OFFICIAL_SCORE",
        "exact_match": exact,
        "normalized_f1": round(max(f1(answer) for answer in answers), 6),
    }
