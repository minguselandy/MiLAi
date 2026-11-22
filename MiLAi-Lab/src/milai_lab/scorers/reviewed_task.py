"""Explicit offline task reviews, independent of any native answer/span convention."""
from __future__ import annotations

import copy
from typing import Any


def first_review_observation(record: dict[str, Any]) -> dict[str, Any]:
    """The actual parsed response and failure that were available to the reviewer."""
    return {key: record.get(key) for key in ("status", "answer", "answer_fields", "reason")}


class TaskReviewIndex:
    """Literal full task/wire matching; a different first cannot inherit a review."""

    def __init__(self, artifact: dict[str, Any]) -> None:
        if artifact["schema"] != "reviewed_task_outcomes_v1":
            raise ValueError("Unsupported task review schema")
        self.entries: list[dict[str, Any]] = artifact["entries"]

    def find(self, case: dict[str, Any], wire: dict[str, Any],
             record: dict[str, Any]) -> dict[str, Any] | None:
        found = []
        for entry in self.entries:
            if (entry["family"] != case["family"] or entry["response_event_id"] !=
                    case.get("response_event_id", case["event_id"]) or entry["wire"] != wire):
                continue
            if entry["first_observation"] != first_review_observation(record):
                raise ValueError("Task review belongs to a different observed first")
            found.append(entry["review"])
        if any(review != found[0] for review in found[1:]):
            raise ValueError("Conflicting reviews require explicit adjudication")
        return copy.deepcopy(found[0]) if found else None


def reviewed_task_outcome(native: dict[str, Any],
                          review: dict[str, Any] | None) -> dict[str, Any]:
    """Keep diagnostics, mask absent judgments, and respect actual execution status.

    The review's grade/limitations are data, never upgraded by this adapter. This
    protocol does not equate an annotated witness requirement with semantic truth.
    """
    material: bool | None = None
    resolution: bool | None = None
    if review is not None:
        if (review["material_status"] not in {"SUFFICIENT", "INSUFFICIENT", "UNKNOWN"}
                or type(review["task_resolution"]) not in {bool, type(None)}
                or type(review["answer_grounding"]) not in {bool, type(None)}
                or not review.get("grade") or not review.get("review_note")):
            raise ValueError("Task review requires explicit axes, grade and rationale")
        material = {"SUFFICIENT": True, "INSUFFICIENT": False, "UNKNOWN": None}[
            review["material_status"]]
        resolution = review["task_resolution"]
        if resolution is True and (material is not True or review["answer_grounding"] is not True):
            raise ValueError("A resolved source-grounded task needs sufficient, supported material")
    if native["execution_status"] in {"UNKNOWN", "NOT_RUN"}:
        resolution = None
    elif native["execution_status"] == "FAILED":
        if resolution is True:
            raise ValueError("A review cannot turn actual execution failure into success")
        resolution = False
    return {**copy.deepcopy(native), "native_primary_outcome": native["primary_outcome"],
        "primary_outcome": resolution, "semantic_material_sufficiency": material,
        "quality_target_known": resolution is not None, "task_review": copy.deepcopy(review),
        "outcome_protocol": "reviewed_execution_v3",
        "metric_version": "explicit-reviewed-task-resolution-v1",
        "scope": "Offline reviewed task resolution at the recorded review grade; unreviewed "
                 "completed responses remain unknown. Native diagnostics retained separately. "
                 "Review independence and calibration limits are not removed by this adapter."}
