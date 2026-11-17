"""Native answer references and literal delivered support, with three-valued availability.

Answer normalization/F1 follows HotpotQA's Apache-2.0 official evaluation:
https://github.com/hotpotqa/hotpot/blob/master/hotpot_evaluate_v1.py .
This scorer's delivery conjunction is a declared adaptation, NOT official jointEM.
"""
from __future__ import annotations

import json
import re
import string
from collections import Counter
from typing import Any


def normalize_hotpot_answer(text: str) -> str:
    lower = text.lower()
    unpunctuated = "".join(char for char in lower if char not in string.punctuation)
    return " ".join(re.sub(r"\b(a|an|the)\b", " ", unpunctuated).split())


def hotpot_answer_scores(prediction: str, reference: str) -> dict[str, float | bool]:
    left, right = normalize_hotpot_answer(prediction), normalize_hotpot_answer(reference)
    exact = left == right
    special = {"yes", "no", "noanswer"}
    if left != right and (left in special or right in special):
        return {"exact_match": exact, "f1": 0.0}
    predicted, expected = left.split(), right.split()
    common = sum((Counter(predicted) & Counter(expected)).values())
    f1 = 2 * common / (len(predicted) + len(expected)) if common else 0.0
    return {"exact_match": exact, "f1": f1}


def reference_coverage(required: list[dict[str, Any]],
                       delivered: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Full union coverage of every annotated literal span, with exact source version."""
    if not required or any(span["end"] <= span["start"] for span in required):
        return {"complete": None, "reason": "reference_unavailable", "covered": None}
    if delivered is None:
        return {"complete": None, "reason": "delivery_capture_unavailable", "covered": None}
    covered = 0
    for needed in required:
        intervals = sorted((span["start"], span["end"]) for span in delivered
            if span["original_event_id"] == needed["original_event_id"]
            and span["source_revision"] == needed["source_revision"])
        end = needed["start"]
        for start, stop in intervals:
            if start > end:
                break
            end = max(end, stop)
        covered += end >= needed["end"]
    return {"complete": covered == len(required), "reason": "literal_reference_ranges_only",
            "covered": covered, "required": len(required)}


def score_reference_first(reference: dict[str, Any], delivered: list[dict[str, Any]] | None,
                           response: dict[str, Any] | None, *,
                           observed_status: str | None = None,
                           outcome_protocol: str = "legacy_v1") -> dict[str, Any]:
    """Do not extract a favorable substring or treat malformed research JSON as unknown.

    A plain first answer can still match the native reference. Otherwise use the
    explicit answer field, or the entire raw text when no valid field is available.
    Explanations and semantic material sufficiency are outside this metric's scope.
    """
    if outcome_protocol not in {"legacy_v1", "observed_execution_v2"}:
        raise ValueError("Unknown declared native outcome protocol")
    coverage = reference_coverage(reference["reference_support_spans"], delivered)
    execution, output_format, answer = "UNKNOWN", "unavailable", None
    if (response is None and observed_status in {"FAILED", "NOT_EXECUTED"}
            and outcome_protocol == "legacy_v1"):
        execution = "FAILED"
    if (response is None and observed_status == "NOT_EXECUTED"
            and outcome_protocol == "observed_execution_v2"):
        execution = "NOT_RUN"
    if response is not None:
        choice = response["choices"][0]
        execution = "COMPLETED" if choice["finish_reason"] == "stop" else "FAILED"
        if choice["finish_reason"] is None and outcome_protocol == "observed_execution_v2":
            execution = "UNKNOWN"
        if execution == "COMPLETED":
            raw = choice["message"]["content"]
            if isinstance(raw, str):
                answer, output_format = raw, "invalid_research_json_whole_text_scored"
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
                        answer, output_format = obj["answer"], "answer_field_available"
                except ValueError:
                    pass
    scores = hotpot_answer_scores(answer, reference["native_answer"]) if answer is not None else {
        "exact_match": None, "f1": None}
    if outcome_protocol == "observed_execution_v2" and execution in {"UNKNOWN", "NOT_RUN"}:
        # Missing transport responses are not semantic negatives. Literal range
        # coverage remains separately measurable, including when it is incomplete.
        primary: bool | None = None
    elif execution == "FAILED" or scores["exact_match"] is False or coverage["complete"] is False:
        primary = False
    elif (execution == "COMPLETED" and scores["exact_match"] is True
          and coverage["complete"] is True):
        primary = True
    else:
        primary = None
    return {"execution_status": execution, "output_format_status": output_format,
        "scored_answer": answer, "native_answer_em": scores["exact_match"],
        "native_answer_f1": scores["f1"], "reference_support": coverage,
        "primary_outcome": primary,
        "metric_version": "native-answer-em-and-delivered-reference-spans-" + (
            "v2" if outcome_protocol == "observed_execution_v2" else "v1"),
        **({"observed_transport_status": observed_status,
            "semantic_material_sufficiency": None,
            "quality_target_known": primary is not None,
            "outcome_protocol": outcome_protocol}
           if outcome_protocol == "observed_execution_v2" else {}),
        "scope": "Native reference answer correctness and literal reference delivery; "
                 "not official jointEM, explanation truth, or semantic sufficiency"}
