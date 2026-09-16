"""Official Memora FAMA criterion loading and deterministic aggregation."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from evals.paper.datasets.memora import MemoraCase, MemoraCohort, load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready

DEFAULT_DATA_ROOT = Path("/cra/memory/mx_memory/benchmarks/Memora/data")


class MemoraScorerError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemoraCriterion:
    case_id: str
    criterion_id: str
    evaluation_question: str
    evaluation_type: str
    expected_answer: str
    source_question_id: str
    task: str


def fama_score(
    memory_presence_correct: int,
    memory_presence_total: int,
    forgetting_absence_correct: int,
    forgetting_absence_total: int,
) -> float:
    """Compute the released per-question FAMA definition in [0, 1]."""

    values = (
        memory_presence_correct,
        memory_presence_total,
        forgetting_absence_correct,
        forgetting_absence_total,
    )
    if any(isinstance(value, bool) or value < 0 for value in values):
        raise ValueError("FAMA counts must be non-negative integers")
    if (
        memory_presence_correct > memory_presence_total
        or forgetting_absence_correct > forgetting_absence_total
    ):
        raise ValueError("FAMA correct counts cannot exceed denominators")
    if memory_presence_total == 0 and forgetting_absence_total == 0:
        return 0.0
    memory_presence_accuracy = (
        memory_presence_correct / memory_presence_total
        if memory_presence_total
        else 0.0
    )
    forgetting_absence_accuracy = (
        forgetting_absence_correct / forgetting_absence_total
        if forgetting_absence_total
        else 1.0
    )
    penalty_weight = forgetting_absence_total / (
        memory_presence_total + forgetting_absence_total
    )
    return max(
        0.0,
        memory_presence_accuracy - penalty_weight * (1.0 - forgetting_absence_accuracy),
    )


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoraScorerError(f"invalid Memora label file: {path}") from exc
    if not isinstance(value, dict):
        raise MemoraScorerError(f"expected Memora label object: {path}")
    return value


def _cohort_criteria(
    *, cohort: MemoraCohort, cases: Sequence[MemoraCase], data_root: Path
) -> tuple[MemoraCriterion, ...]:
    path = (
        data_root
        / cohort.period
        / cohort.persona
        / f"evaluation_questions_{cohort.persona}.json"
    )
    value = _object(path)
    groups = value.get("questions")
    if value.get("persona") != cohort.persona or not isinstance(groups, dict):
        raise MemoraScorerError("Memora label root drifted")
    case_by_source = {case.source_question_id: case for case in cases}
    if len(case_by_source) != len(cases):
        raise MemoraScorerError("Memora source question IDs are not unique")
    criteria: list[MemoraCriterion] = []
    observed_sources: set[str] = set()
    for task_key, task_rows in groups.items():
        if not isinstance(task_key, str) or not isinstance(task_rows, list):
            raise MemoraScorerError("Memora label task group drifted")
        for row in task_rows:
            if not isinstance(row, dict):
                raise MemoraScorerError("Memora label row is invalid")
            source_id = row.get("question_id")
            if source_id not in case_by_source:
                continue
            case = case_by_source[str(source_id)]
            evaluation = row.get("evaluation")
            raw_criteria = (
                evaluation.get("evaluation_questions")
                if isinstance(evaluation, dict)
                else None
            )
            if not isinstance(raw_criteria, list) or not raw_criteria:
                raise MemoraScorerError("Memora criterion list drifted")
            observed_sources.add(str(source_id))
            for raw in raw_criteria:
                if not isinstance(raw, dict):
                    raise MemoraScorerError("Memora criterion is invalid")
                criterion_id = raw.get("evaluation_question_id")
                question = raw.get("evaluation_question")
                evaluation_type = raw.get("evaluation_type")
                expected = raw.get("expected_answer")
                if (
                    not isinstance(criterion_id, str)
                    or not criterion_id
                    or not isinstance(question, str)
                    or not question
                    or evaluation_type not in {"memory_presence", "forgetting_absence"}
                    or not isinstance(expected, str)
                    or expected.casefold() not in {"yes", "no"}
                ):
                    raise MemoraScorerError("Memora criterion contract drifted")
                criteria.append(
                    MemoraCriterion(
                        case_id=case.case_id,
                        criterion_id=criterion_id,
                        evaluation_question=question,
                        evaluation_type=str(evaluation_type),
                        expected_answer=expected.casefold(),
                        source_question_id=case.source_question_id,
                        task=case.task,
                    )
                )
    if observed_sources != set(case_by_source):
        raise MemoraScorerError("Memora criteria do not cover the frozen cases")
    identities = {(item.case_id, item.criterion_id) for item in criteria}
    if len(identities) != len(criteria):
        raise MemoraScorerError("Memora criterion IDs are not unique per case")
    return tuple(criteria)


def load_official_criteria(
    *,
    input_path: Path,
    data_root: Path = DEFAULT_DATA_ROOT,
    freeze_manifest: Path = DEFAULT_MANIFEST,
    allow_unfrozen_smoke: bool = False,
) -> tuple[MemoraCriterion, ...]:
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    cohorts, cases = load_inputs(input_path)
    cases_by_cohort: dict[str, list[MemoraCase]] = defaultdict(list)
    for case in cases:
        cases_by_cohort[case.cohort_id].append(case)
    criteria = tuple(
        criterion
        for cohort in cohorts
        for criterion in _cohort_criteria(
            cohort=cohort,
            cases=cases_by_cohort[cohort.cohort_id],
            data_root=data_root,
        )
    )
    if not allow_unfrozen_smoke and len(criteria) != 651:
        raise MemoraScorerError("formal Memora criterion denominator drifted")
    return criteria


def _ratio(correct: int, total: int) -> float | None:
    return correct / total if total else None


def aggregate_judgments(
    *,
    cases: Sequence[MemoraCase],
    methods: Sequence[str],
    criteria: Sequence[MemoraCriterion],
    judgments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    criterion_by_key = {(item.case_id, item.criterion_id): item for item in criteria}
    expected = {
        (method, criterion.case_id, criterion.criterion_id)
        for method in methods
        for criterion in criteria
    }
    judgment_by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for judgment in judgments:
        key = (
            str(judgment.get("method_id")),
            str(judgment.get("case_id")),
            str(judgment.get("criterion_id")),
        )
        if key in judgment_by_key:
            raise MemoraScorerError("duplicate Memora judgment")
        if (
            key not in expected
            or judgment.get("judge_answer") not in {"yes", "no"}
            or not isinstance(judgment.get("is_correct"), bool)
        ):
            raise MemoraScorerError("invalid Memora judgment")
        criterion = criterion_by_key[(key[1], key[2])]
        expected_correct = judgment["judge_answer"] == criterion.expected_answer
        if judgment["is_correct"] is not expected_correct:
            raise MemoraScorerError("Memora judgment correctness drifted")
        judgment_by_key[key] = judgment
    if set(judgment_by_key) != expected:
        raise MemoraScorerError("Memora judgment denominator is incomplete")
    per_question = []
    for method in methods:
        for case in cases:
            case_criteria = [item for item in criteria if item.case_id == case.case_id]
            presence = [
                item
                for item in case_criteria
                if item.evaluation_type == "memory_presence"
            ]
            forgetting = [
                item
                for item in case_criteria
                if item.evaluation_type == "forgetting_absence"
            ]
            presence_correct = sum(
                judgment_by_key[(method, case.case_id, item.criterion_id)]["is_correct"]
                is True
                for item in presence
            )
            forgetting_correct = sum(
                judgment_by_key[(method, case.case_id, item.criterion_id)]["is_correct"]
                is True
                for item in forgetting
            )
            per_question.append(
                {
                    "case_id": case.case_id,
                    "cohort_id": case.cohort_id,
                    "fama": fama_score(
                        presence_correct,
                        len(presence),
                        forgetting_correct,
                        len(forgetting),
                    ),
                    "forgetting_absence_correct": forgetting_correct,
                    "forgetting_absence_total": len(forgetting),
                    "memory_presence_correct": presence_correct,
                    "memory_presence_total": len(presence),
                    "method_id": method,
                    "task": case.task,
                }
            )
    by_method: dict[str, dict[str, Any]] = {}
    for method in methods:
        rows = [row for row in per_question if row["method_id"] == method]
        presence_correct = sum(int(row["memory_presence_correct"]) for row in rows)
        presence_total = sum(int(row["memory_presence_total"]) for row in rows)
        forgetting_correct = sum(int(row["forgetting_absence_correct"]) for row in rows)
        forgetting_total = sum(int(row["forgetting_absence_total"]) for row in rows)
        by_task = {
            task: round(
                mean(float(row["fama"]) for row in rows if row["task"] == task) * 100,
                6,
            )
            for task in sorted({str(row["task"]) for row in rows})
        }
        by_method[method] = {
            "deletion_leak_rate": (
                round(1.0 - forgetting_correct / forgetting_total, 9)
                if forgetting_total
                else None
            ),
            "fama": round(mean(float(row["fama"]) for row in rows) * 100, 6),
            "fama_by_task": by_task,
            "forgetting_absence_accuracy": _ratio(forgetting_correct, forgetting_total),
            "forgetting_absence_correct": forgetting_correct,
            "forgetting_absence_total": forgetting_total,
            "memory_presence_accuracy": _ratio(presence_correct, presence_total),
            "memory_presence_correct": presence_correct,
            "memory_presence_total": presence_total,
            "question_count": len(rows),
        }
    return {
        "by_method": by_method,
        "case_count": len(cases),
        "criterion_count_per_method": len(criteria),
        "judgment_count": len(judgments),
        "methods": list(methods),
        "per_question": per_question,
        "schema": "milai.dg11.paper-memora-metrics.v1",
    }
