from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any

from evals.benchmark import dg11_measurement
from evals.scorers import answer_values

RECOVERY_SPLIT_SEED = "dg11-recovery-v2-paper-v1"
SPLIT_SIZE = 100

TARGETED_FIXES: dict[str, dict[str, str]] = {
    "94f70d80": {
        "layer": "R0",
        "fix": "duration wording no longer implies calendar-distance operator",
    },
    "9aaed6a3": {
        "layer": "R0",
        "fix": "weekday event qualifier no longer overrides amount lookup",
    },
    "37d43f65": {
        "layer": "R3",
        "fix": "numeric value and unit are protected during compilation",
    },
    "cc539528": {
        "layer": "R3",
        "fix": "assistant role and multiline recommendation list are preserved",
    },
    "6222b6eb": {
        "layer": "R3",
        "fix": "escaped identifier and enumerated-list subject are preserved",
    },
}


class RecoveryError(RuntimeError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _rank(label: str, source_id: str) -> str:
    return hashlib.sha256(
        f"{RECOVERY_SPLIT_SEED}:{label}:{source_id}".encode()
    ).hexdigest()


def _round_robin(
    by_category: Mapping[str, Sequence[str]], allocation: Mapping[str, int]
) -> tuple[str, ...]:
    selected = {
        category: deque(source_ids[: allocation[category]])
        for category, source_ids in sorted(by_category.items())
    }
    ordered: list[str] = []
    while any(selected.values()):
        for source_ids in selected.values():
            if source_ids:
                ordered.append(source_ids.popleft())
    return tuple(ordered)


def partition_remaining(
    rows: Sequence[Mapping[str, Any]],
    consumed_ids: set[str],
    *,
    split_size: int = SPLIT_SIZE,
) -> dict[str, Any]:
    ids = [row.get("question_id") for row in rows]
    if len(ids) != len(set(ids)) or any(not isinstance(value, str) for value in ids):
        raise RecoveryError("dataset source IDs must be unique strings")
    dataset_ids = {str(value) for value in ids}
    if not consumed_ids.issubset(dataset_ids):
        raise RecoveryError("consumed source IDs are absent from the dataset")
    remaining_ids = dataset_ids.difference(consumed_ids)
    if len(remaining_ids) != split_size * 2:
        raise RecoveryError("recovery split requires exactly two unused 100-case sets")

    by_category: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        source_id = str(row["question_id"])
        category = row.get("question_type")
        if source_id in remaining_ids:
            if not isinstance(category, str) or not category:
                raise RecoveryError("remaining case has no category")
            by_category[category].append(source_id)
    for category, source_ids in by_category.items():
        source_ids.sort(key=lambda source_id: _rank(f"v2:{category}", source_id))

    v2_allocation = {
        category: len(source_ids) // 2 for category, source_ids in by_category.items()
    }
    remainder = split_size - sum(v2_allocation.values())
    odd_categories = sorted(
        (
            category
            for category, source_ids in by_category.items()
            if len(source_ids) % 2
        ),
        key=lambda category: _rank("allocation", category),
    )
    if remainder < 0 or remainder > len(odd_categories):
        raise RecoveryError("balanced category allocation cannot reach 100 cases")
    for category in odd_categories[:remainder]:
        v2_allocation[category] += 1

    v2_by_category = {
        category: source_ids[: v2_allocation[category]]
        for category, source_ids in by_category.items()
    }
    paper_by_category = {
        category: sorted(
            source_ids[v2_allocation[category] :],
            key=lambda source_id: _rank(f"paper:{category}", source_id),
        )
        for category, source_ids in by_category.items()
    }
    paper_allocation = {
        category: len(source_ids) for category, source_ids in paper_by_category.items()
    }
    v2_ids = _round_robin(v2_by_category, v2_allocation)
    paper_ids = _round_robin(paper_by_category, paper_allocation)
    if len(v2_ids) != split_size or len(paper_ids) != split_size:
        raise RecoveryError("recovery split denominator drifted")
    if set(v2_ids).intersection(paper_ids) or set(v2_ids).union(paper_ids) != remaining_ids:
        raise RecoveryError("recovery splits are not an exact partition")
    return {
        "generalization_v2": v2_ids,
        "paper_test_v1": paper_ids,
        "generalization_v2_allocation": dict(sorted(v2_allocation.items())),
        "paper_test_v1_allocation": dict(sorted(paper_allocation.items())),
    }


def _operator(context: str) -> str | None:
    marker = "\nDERIVED "
    if marker not in context:
        return None
    return context.split(marker, 1)[1].split(maxsplit=1)[0]


def _primary_layer(flags: Mapping[str, bool]) -> str:
    for layer in ("R0", "R5", "R6", "R1", "R2", "R3", "R4", "R7"):
        if flags[layer]:
            return layer
    return "PASS"


def build_v1_error_matrix(
    rows: Sequence[Mapping[str, Any]],
    scored_records: Sequence[Mapping[str, Any]],
    current_context_records: Sequence[Mapping[str, Any]],
    dg10_context_records: Sequence[Mapping[str, Any]],
    source_ids: Sequence[str],
) -> dict[str, Any]:
    if len(source_ids) != 100 or len(set(source_ids)) != 100:
        raise RecoveryError("v1 error matrix denominator must be 100 unique cases")
    dataset = {str(row["question_id"]): row for row in rows}
    current_scores = {
        str(record["source_id"]): record
        for record in scored_records
        if record.get("arm") == "MILAI_DG11_CURRENT"
    }
    dg10_scores = {
        str(record["source_id"]): record
        for record in scored_records
        if record.get("arm") == "MILAI_DG10_FROZEN"
    }
    current_contexts = {
        str(record["source_id"]): record for record in current_context_records
    }
    dg10_contexts = {
        str(record["source_id"]): record for record in dg10_context_records
    }
    required = set(source_ids)
    for name, values in (
        ("dataset", dataset),
        ("DG11 scores", current_scores),
        ("DG10 scores", dg10_scores),
        ("DG11 contexts", current_contexts),
        ("DG10 contexts", dg10_contexts),
    ):
        if not required.issubset(values):
            raise RecoveryError(f"{name} do not cover the v1 denominator")

    matrix: list[dict[str, Any]] = []
    for source_id in source_ids:
        row = dataset[source_id]
        current_score = current_scores[source_id]
        dg10_score = dg10_scores[source_id]
        current_record = current_contexts[source_id]
        dg10_record = dg10_contexts[source_id]
        context = str(current_record["context"]["rendered"])
        context_status = str(current_record["context"]["status"])
        relevant = {str(value) for value in row.get("answer_session_ids", [])}
        retrieved = {
            str(value) for value in current_record["trace"]["retrieved_session_ids"]
        }
        hits = relevant.intersection(retrieved)
        answers = answer_values(row["answer"])
        span_present = dg11_measurement.answer_span_present(context, answers)
        f1_v1 = float(current_score["scorer_v1"]["normalized_f1"])
        f1_v2 = float(current_score["scorer_v2"]["normalized_f1"])
        exact_match = int(current_score["scorer_v1"]["exact_match"])
        operator = _operator(context)
        targeted = TARGETED_FIXES.get(source_id)
        flags = {
            "R0": targeted is not None and targeted["layer"] == "R0",
            "R1": not bool(hits),
            "R2": bool(hits) and bool(relevant) and len(hits) < len(relevant),
            "R3": bool(hits) and not span_present,
            "R4": span_present and exact_match == 0,
            "R5": operator is not None or (
                targeted is not None and targeted["layer"] == "R0"
            ),
            "R6": context_status in {"UNCERTAIN", "UNAVAILABLE"},
            "R7": f1_v1 != f1_v2,
        }
        matrix.append(
            {
                "source_id": source_id,
                "category": str(row["question_type"]),
                "question": str(row["question"]),
                "current_answer": str(current_score["answer"]),
                "current_f1_v1": f1_v1,
                "current_f1_v2": f1_v2,
                "current_exact_match": exact_match,
                "dg10_f1_v1": float(dg10_score["scorer_v1"]["normalized_f1"]),
                "retrieved_session_ids": sorted(retrieved),
                "relevant_session_count": len(relevant),
                "retrieval_hit_at_3": int(bool(hits)),
                "relevant_coverage_at_3": (
                    round(len(hits) / len(relevant), 6) if relevant else 0.0
                ),
                "answer_span_present_after_compile": span_present,
                "context_status": context_status,
                "dg10_context_status": str(dg10_record["context"]["status"]),
                "derived_operator": operator,
                "unknown_answer": str(current_score["answer"]).strip().casefold()
                == "unknown",
                "memory_tokens": int(current_score["memory_tokens"]),
                "dg10_memory_tokens": int(dg10_score["memory_tokens"]),
                "layer_flags": flags,
                "primary_layer": _primary_layer(flags),
                "targeted_fix": targeted,
            }
        )

    category_metrics: dict[str, Any] = {}
    for category in sorted({record["category"] for record in matrix}):
        group = [record for record in matrix if record["category"] == category]
        hits = [record for record in group if record["retrieval_hit_at_3"] == 1]
        category_metrics[str(category)] = {
            "case_count": len(group),
            "retrieval_hit_at_3_mean": round(
                mean(record["retrieval_hit_at_3"] for record in group), 6
            ),
            "relevant_coverage_at_3_mean": round(
                mean(record["relevant_coverage_at_3"] for record in group), 6
            ),
            "answer_span_survival_on_hit": (
                round(
                    mean(record["answer_span_present_after_compile"] for record in hits),
                    6,
                )
                if hits
                else 0.0
            ),
            "operator_route_rate": round(
                mean(record["derived_operator"] is not None for record in group), 6
            ),
            "unknown_rate": round(mean(record["unknown_answer"] for record in group), 6),
            "f1_v1_mean": round(mean(record["current_f1_v1"] for record in group), 6),
            "exact_match_mean": round(
                mean(record["current_exact_match"] for record in group), 6
            ),
            "primary_layer_counts": dict(
                sorted(Counter(record["primary_layer"] for record in group).items())
            ),
        }
    return {
        "schema": "milai.dg11.v1-error-matrix.v1",
        "classification": "DETERMINISTIC_SIGNALS_WITH_HEURISTIC_PRIMARY_LAYER",
        "case_count": len(matrix),
        "provider_requests": 0,
        "hidden_provider_calls": 0,
        "category_metrics": category_metrics,
        "targeted_fix_source_ids": sorted(TARGETED_FIXES),
        "records": matrix,
    }
