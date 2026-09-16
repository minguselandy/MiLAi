"""Construct the complete label-free LongMemEval method/case denominator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evals.paper.datasets.longmemeval import load_inputs

from .schedule import FrozenSchedule


class PlanError(RuntimeError):
    pass


def _history_length_bucket(session_count: int) -> str:
    if session_count <= 0:
        raise PlanError("LongMemEval case has no history sessions")
    if session_count <= 10:
        return "SHORT_01_10"
    if session_count <= 30:
        return "MEDIUM_11_30"
    return "LONG_31_PLUS"


@dataclass(frozen=True)
class PlanCell:
    ordinal: int
    case_ordinal: int
    input_ordinal: int
    period: int
    case_id: str
    category: str
    history_length_bucket: str
    service_window: str
    matrix: str
    method_id: str
    track: str


def build_lme_plan(
    *,
    input_path: Path,
    schedule_path: Path,
    matrices: tuple[str, ...] = ("LME_CONTROLLED",),
) -> dict[str, Any]:
    partition, cases = load_inputs(input_path)
    schedule = FrozenSchedule.load(schedule_path)
    cells: list[PlanCell] = []
    ordinal = 0
    if not matrices or len(set(matrices)) != len(matrices):
        raise PlanError("plan matrices must be non-empty and unique")
    track_by_matrix = {
        "LME_CONTROLLED": "CONTROLLED_OR_UPPER_BOUND",
        "NATIVE_SHARED_CONTEXT": "NATIVE_OPEN_SOURCE",
    }
    if any(matrix not in track_by_matrix for matrix in matrices):
        raise PlanError("unknown plan matrix")
    matrix_tracks = tuple((matrix, track_by_matrix[matrix]) for matrix in matrices)
    sorted_cases = sorted(
        enumerate(cases),
        key=lambda item: (
            item[1].category,
            _history_length_bucket(len(item[1].sessions)),
            "SINGLE_FROZEN_WINDOW",
            "",
            item[1].source_id,
        ),
    )
    for case_ordinal, (input_ordinal, case) in enumerate(sorted_cases):
        history_bucket = _history_length_bucket(len(case.sessions))
        for matrix, track in matrix_tracks:
            for period, method_id in enumerate(schedule.order(matrix, case_ordinal)):
                cells.append(
                    PlanCell(
                        ordinal=ordinal,
                        case_ordinal=case_ordinal,
                        input_ordinal=input_ordinal,
                        period=period,
                        case_id=case.source_id,
                        category=case.category,
                        history_length_bucket=history_bucket,
                        service_window="SINGLE_FROZEN_WINDOW",
                        matrix=matrix,
                        method_id=method_id,
                        track=track,
                    )
                )
                ordinal += 1
    expected_methods = {
        method for matrix in matrices for method in schedule.matrices[matrix][0]
    }
    pairs = {(cell.case_id, cell.method_id) for cell in cells}
    expected_pairs = {
        (case.source_id, method) for case in cases for method in expected_methods
    }
    if pairs != expected_pairs or len(cells) != len(expected_pairs):
        raise PlanError("formal plan denominator is incomplete or duplicated")
    return {
        "schema": "milai.dg12.paper-lme-plan.v3",
        "status": "LABEL_FREE_PLAN_COMPLETE",
        "partition": partition,
        "case_count": len(cases),
        "method_count": len(expected_methods),
        "cell_count": len(cells),
        "methods": sorted(expected_methods),
        "matrices": list(matrices),
        "schedule_namespace": schedule.namespace,
        "block_sort_keys": [
            "benchmark",
            "category_or_stratum",
            "history_length_bucket",
            "service_window",
            "history_id",
            "case_id",
        ],
        "history_length_buckets": {
            "SHORT_01_10": "1-10 sessions",
            "MEDIUM_11_30": "11-30 sessions",
            "LONG_31_PLUS": "31 or more sessions",
        },
        "service_window": "SINGLE_FROZEN_WINDOW",
        "paper_labels_opened": False,
        "formal_method_outputs_generated": False,
        "cells": [asdict(cell) for cell in cells],
    }
