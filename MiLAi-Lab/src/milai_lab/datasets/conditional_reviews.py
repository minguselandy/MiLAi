"""Supplement unjudged cells in one declared split; preserve native gold and provenance."""
from __future__ import annotations

import copy
from collections import Counter
from typing import Any, Literal

from milai_lab.datasets.conditional_applicability import OPTIONS
from milai_lab.datasets.followir import applicability_input


def binary_label(row: dict[str, Any]) -> bool | None:
    target = row["gold"].get("applicability", {}).get("probabilities", {})
    if not target:
        return None
    if target == {"satisfies": 1., "does_not_satisfy": 0.}:
        return True
    if target == {"satisfies": 0., "does_not_satisfy": 1.}:
        return False
    raise ValueError("Conditional applicability requires a known binary label or empty gold")


def label_origin(row: dict[str, Any]) -> str:
    if row["metadata"].get("source_author_review"):
        return "source_author_review" if row["gold"] else "unjudged_after_source_review"
    return "native" if row["gold"] else row["metadata"]["label_status"]


def apply_training_applicability_reviews(
    matrix: list[dict[str, Any]], pairs: list[dict[str, Any]], records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep the existing training-only entry point and its split restriction."""
    return _apply_applicability_reviews(matrix, pairs, records, split="train")


def apply_development_applicability_reviews(
    matrix: list[dict[str, Any]], pairs: list[dict[str, Any]], records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create attributed development judgments without admitting them to training."""
    return _apply_applicability_reviews(matrix, pairs, records, split="dev")


def _apply_applicability_reviews(
    matrix: list[dict[str, Any]], pairs: list[dict[str, Any]], records: list[dict[str, Any]],
    *, split: Literal["train", "dev"],
) -> dict[str, Any]:
    """Bind each review to its exact visible task, retain unknowns and rebuild paired labels.

    Quote checks establish traceable input identity, not semantic correctness. The
    supplied review remains an explicitly attributed author judgment.
    """
    rows = copy.deepcopy(matrix)
    by_id = {row["metadata"]["event_id"]: row for row in rows}
    events = [review["event_id"] for review in records]
    if (len(by_id) != len(rows) or len(set(events)) != len(events)
            or len({r["review_id"] for r in records}) != len(records)):
        raise ValueError("Review application requires distinct cells and one judgment per cell")
    for review in records:
        row = by_id[review["event_id"]]
        meta = row["metadata"]
        if (meta["split"] != split or row["gold"] or meta["native_judgments"]
                or meta["label_status"] != "unjudged" or meta.get("source_author_review")):
            name = "training" if split == "train" else "development"
            raise ValueError(f"Only originally unjudged {name} cells may receive this supplement")
        binding = review["input_binding"]
        visible = applicability_input(binding["query"], binding["purpose"], binding["candidate"])
        if (meta["family"] != review["family"]
                or any(row[key] != visible[key] for key in ("state", "questions"))):
            raise ValueError("Review task/candidate/family differs from the actual cell")
        if review["decision"] not in {*OPTIONS, "unknown"} or not review["anchors"]:
            raise ValueError("Review requires a declared decision and literal source anchors")
        for anchor in review["anchors"]:
            if anchor["field"] not in {"title", "text"}:
                raise ValueError("Review anchors must refer to supplied candidate material")
            text = row["state"]["candidate"][anchor["field"]]
            start, end = anchor["range"]
            if not 0 <= start < end <= len(text) or text[start:end] != anchor["quote"]:
                raise ValueError("Review quote/range differs from the literal candidate")
        meta["source_author_review"] = copy.deepcopy({key: review[key] for key in (
            "review_id", "decision", "rationale", "anchors", "basis",
            "factuality_independently_verified")})
        if review["decision"] != "unknown":
            row["gold"] = {"applicability": {"probabilities": {
                option: float(option == review["decision"]) for option in OPTIONS}}}
            meta["native_label_status"] = meta["label_status"]
            meta["label_status"] = "source_author_reviewed"
    revised_pairs = []
    for pair in pairs:
        left, right = [by_id[pair[key]] for key in ("left_event", "right_event")]
        if (left["state"]["candidate"] != right["state"]["candidate"]
                or any(left["metadata"][key] != right["metadata"][key]
                       or left["metadata"][key] != pair[key] for key in ("family", "query_unit"))):
            raise ValueError("Conditional pair no longer names the same query-unit/candidate")
        a, z = binary_label(left), binary_label(right)
        if (left["state"]["task"]["retrieval_request"]["query"]
                != right["state"]["task"]["retrieval_request"]["query"]):
            kind, reason = "unknown", "query_text_also_changed"
        elif a is None or z is None:
            kind = "unknown"
            reason = ("conflicting_native_judgments" if any(
                row["metadata"]["label_status"] == "conflicting_native_judgments"
                for row in (left, right)) else "missing_cross_condition_judgment")
        else:
            kind = "change" if a != z else "stable"
            reason = ("both_native_conditions_judged" if all(label_origin(row) == "native"
                       for row in (left, right)) else "native_and_source_author_judgments")
        revised = {**copy.deepcopy(pair), "kind": kind, "reason": reason,
                   "left_label": a, "right_label": z}
        if any(row["metadata"].get("source_author_review") for row in (left, right)):
            revised["label_origins"] = {"left": label_origin(left), "right": label_origin(right)}
        revised_pairs.append(revised)
    return {"matrix": rows, "pairs": revised_pairs,
        "counts": {"reviewed_cells": len(records),
            "new_known_cells": sum(r["decision"] != "unknown" for r in records),
            "reviewed_still_unknown_cells": sum(r["decision"] == "unknown" for r in records),
            "label_status": dict(Counter(r["metadata"]["label_status"] for r in rows)),
            "comparison_kind": dict(Counter(p["kind"] for p in revised_pairs))}}
