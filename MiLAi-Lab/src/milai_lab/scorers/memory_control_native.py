"""Source-native answer metrics with an explicit same-state training mapping."""

from __future__ import annotations

import json
import re
import string
from collections import Counter
from collections.abc import Sequence
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.methods.dataset_reader import ReaderTask

SCORER_VERSION = "native_memory_control_v1"
NATIVE_SCORER_SOURCES = {
    MUSIQUE: "https://github.com/StonyBrookNLP/musique/blob/"
    "922ac98f19a201998dbdae6d7f2887a5258dbdeb/evaluate_v1.0.py",
    QASPER: "https://github.com/allenai/qasper-led-baseline/blob/"
    "afd0fb96bf78ce8cd8157639c6f6a6995e4f9089/scripts/evaluator.py",
    PERSONA: "https://github.com/bowen-upenn/PersonaMem-v2/blob/"
    "d29d91d016add354e459dfeb0d24af08bc402e2a/inference.py",
}
_PUNCTUATION = str.maketrans("", "", string.punctuation)
_ARTICLES = re.compile(r"\b(?:a|an|the)\b")


def answer_tokens(text: str) -> list[str]:
    return _ARTICLES.sub(" ", text.lower().translate(_PUNCTUATION)).split()


def token_f1(prediction: str, reference: str, *, equal_empty: bool) -> float:
    predicted = answer_tokens(prediction)
    gold = answer_tokens(reference)
    if not predicted or not gold:
        return float(equal_empty and predicted == gold)
    common = sum((Counter(predicted) & Counter(gold)).values())
    if not common:
        return 0.0
    precision, recall = common / len(predicted), common / len(gold)
    return 2 * precision * recall / (precision + recall)


def qasper_reference(answer: dict[str, Any]) -> tuple[str, str]:
    if answer["unanswerable"]:
        return "Unanswerable", "none"
    if answer["extractive_spans"]:
        return ", ".join(answer["extractive_spans"]), "extractive"
    if answer["free_form_answer"]:
        return answer["free_form_answer"], "abstractive"
    if type(answer["yes_no"]) is bool:
        return ("Yes" if answer["yes_no"] else "No"), "boolean"
    raise ValueError("Invalid QASPER reference answer")


def parsed_answer(content: str, public: ReaderTask) -> dict[str, Any] | None:
    try:
        body = json.loads(content)
    except json.JSONDecodeError:
        return None
    properties = public.schema()["properties"]
    if not isinstance(body, dict) or body.keys() != properties.keys():
        return None
    if public.source == PERSONA:
        return body if body["selected_option"] in properties["selected_option"]["enum"] else None
    if (
        not isinstance(body["answer"], str)
        or not isinstance(body["evidence"], list)
        or any(not isinstance(item, str) for item in body["evidence"])
    ):
        return None
    if public.source == MUSIQUE and type(body["answerable"]) is not bool:
        return None
    return body


def score_answer(
    content: str,
    public: ReaderTask,
    gold: dict[str, Any],
    correct_options: frozenset[str],
    *,
    support_aliases: dict[str, int] | None = None,
) -> dict[str, Any]:
    body = parsed_answer(content, public)
    valid = body is not None
    predicted = body or {}
    quality = 0.0
    metrics: dict[str, Any]
    if public.source == PERSONA:
        if public.invalid_reason or not correct_options:
            raise ValueError("PersonaMCQ scoring requires all valid choices")
        quality = float(predicted.get("selected_option") in correct_options)
        metrics = {
            "accuracy": quality,
            "selected_option": predicted.get("selected_option"),
            "strata": {
                k: gold.get(k)
                for k in ("who", "updated", "sensitive_info", "pref_type", "snippet_fully_visible")
            },
        }
    elif public.source == QASPER:
        refs = [qasper_reference(item["answer"]) for item in gold["answer_annotations"]]
        scores = [
            (token_f1(predicted["answer"], answer, equal_empty=False) if valid else 0.0, kind)
            for answer, kind in refs
        ]
        quality, answer_type = max(scores, key=lambda item: item[0])
        evidence_kinds = {
            m["evidence_kind"]
            for row in gold["answer_annotations"]
            for m in row["evidence_alignment"]
        }
        metrics = {
            "answer_f1": quality,
            "best_reference_type": answer_type,
            "reference_types": sorted({kind for _, kind in refs}),
            "figure_only": evidence_kinds == {"caption_only"},
            "predicted_evidence_labels": predicted.get("evidence"),
        }
    else:
        expected = gold["answerable"]
        references = [gold["answer"], *gold["answer_aliases"]]
        f1 = (
            max(token_f1(predicted["answer"], ref, equal_empty=True) for ref in references)
            if valid and expected
            else None
        )
        em = (
            max(
                float(answer_tokens(predicted["answer"]) == answer_tokens(ref))
                for ref in references
            )
            if valid and expected
            else None
        )
        sufficiency_correct = valid and predicted["answerable"] is expected
        if sufficiency_correct:
            quality = float(f1) if f1 is not None else 1.0
        supports = support_aliases or {}
        returned = set(predicted.get("evidence", []))
        predicted_objects = {supports[alias] for alias in returned if alias in supports}
        gold_objects = set(gold["support_objects"])
        # An unbound alias is a false positive, even though it cannot map to a native object.
        support_size = len(predicted_objects) + len(returned - supports.keys())
        support_f1 = (
            (
                2 * len(predicted_objects & gold_objects) / (support_size + len(gold_objects))
                if support_size + len(gold_objects)
                else 1.0
            )
            if expected and valid
            else None
        )
        metrics = {
            "gold_answerable": expected,
            "predicted_answerable": predicted.get("answerable"),
            "answer_f1": (f1 or 0.0) if expected else None,
            "answer_em": (em or 0.0) if expected else None,
            "support_f1": (support_f1 or 0.0) if expected else None,
            "predicted_support_objects": sorted(predicted_objects),
            "unbound_prediction_labels": sorted(returned - supports.keys()),
            "sufficiency_correct": sufficiency_correct,
        }
    return {
        "status": "scored" if valid else "scored_format_failure",
        "native_metrics": metrics,
        "training_quality": quality,
        "success_witness": valid and quality == 1.0,
    }


def musique_pair(metrics: Sequence[dict[str, Any]]) -> dict[str, float]:
    if len(metrics) != 2 or {row["gold_answerable"] for row in metrics} != {True, False}:
        raise ValueError("The official MuSiQue grouping requires both original context variants")
    answerable = next(row for row in metrics if row["gold_answerable"])
    correct = all(row["sufficiency_correct"] for row in metrics)
    return {
        "group_answer_sufficiency_f1": answerable["answer_f1"] if correct else 0.0,
        "group_answer_sufficiency_em": answerable["answer_em"] if correct else 0.0,
        "group_support_sufficiency_f1": answerable["support_f1"] if correct else 0.0,
        "group_sufficiency": float(correct),
    }
