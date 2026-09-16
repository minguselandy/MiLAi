"""Deterministic scoring and paired inference for ML-R01 R4."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any

from evals.ml_repair.mlr01_r4_contexts import load_context_records
from evals.ml_repair.mlr01_r4_contract import (
    ARMS,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    DATASET_PATH,
    FORMAL_TARGET_COUNTS,
    PRODUCT_ARMS,
    R4_ROOT,
    RUN_ID,
    RUN_ROOT,
    SCHEMA_VERSION,
    MLR01R4Error,
    atomic_json,
    canonical_sha256,
    capability_seal_digest,
    load_json,
    records_sha256,
    require_stage_seal,
    stage_seal_path,
    target_cases,
)
from evals.ml_repair.mlr01_r4_providers import (
    load_answer_records,
    load_judge_records,
)
from evals.paper.datasets.longmemeval import labels_from_dataset
from evals.paper.scorers.longmemeval import score_answer, score_retrieval

RAW_ARM = "MLR01-R"
FORMED_ARM = "MLR01-F"


def _mrr(
    trace: Sequence[Mapping[str, Any]], relevant_session_ids: Sequence[str]
) -> float:
    relevant = set(relevant_session_ids)
    ranked = list(
        dict.fromkeys(
            str(item["session_id"])
            for item in trace
            if isinstance(item.get("session_id"), str)
        )
    )
    for ordinal, session_id in enumerate(ranked, start=1):
        if session_id in relevant:
            return round(1 / ordinal, 9)
    return 0.0


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile sample cannot be empty")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def paired_bootstrap(
    differences: Sequence[float],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if not differences:
        return {
            "estimate": None,
            "ci95": [None, None],
            "samples": samples,
            "seed": seed,
            "unit": "question_id",
        }
    rng = random.Random(seed)
    count = len(differences)
    draws = [
        mean(differences[rng.randrange(count)] for _ in range(count))
        for _ in range(samples)
    ]
    return {
        "estimate": round(mean(differences), 9),
        "ci95": [
            round(_percentile(draws, 0.025), 9),
            round(_percentile(draws, 0.975), 9),
        ],
        "samples": samples,
        "seed": seed,
        "unit": "question_id",
    }


def _relative_delta(value: float, baseline: float) -> float | None:
    return round((value - baseline) / baseline, 9) if baseline else None


def _mean(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return round(mean(float(row[key]) for row in rows), 9) if rows else 0.0


def _arm_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "VLLMJudgeAccuracy": _mean(rows, "judge_correct"),
        "exact_match": _mean(rows, "exact_match"),
        "normalized_f1": _mean(rows, "normalized_f1"),
        "AnswerSessionRecallAtK": _mean(rows, "retrieval_recall"),
        "NDCGAtK": _mean(rows, "ndcg_at_k"),
        "MRR": _mean(rows, "mrr"),
        "hit_at_k": _mean(rows, "hit_at_k"),
        "context_tokens_mean": _mean(rows, "context_tokens"),
        "answer_prompt_tokens_sum": sum(
            int(row["answer_prompt_tokens"]) for row in rows
        ),
        "answer_completion_tokens_sum": sum(
            int(row["answer_completion_tokens"]) for row in rows
        ),
        "judge_prompt_tokens_sum": sum(int(row["judge_prompt_tokens"]) for row in rows),
        "judge_completion_tokens_sum": sum(
            int(row["judge_completion_tokens"]) for row in rows
        ),
        "answer_provider_wall_ms_sum": round(
            sum(float(row["answer_provider_wall_ms"]) for row in rows), 6
        ),
        "judge_provider_wall_ms_sum": round(
            sum(float(row["judge_provider_wall_ms"]) for row in rows), 6
        ),
    }


def score(target_count: int) -> dict[str, Any]:
    score_path = stage_seal_path("score", target_count)
    if score_path.is_file():
        value = load_json(score_path)
        if (
            isinstance(value, dict)
            and value.get("schema") == f"{SCHEMA_VERSION}.score-seal"
            and value.get("target_count") == target_count
            and value.get("capability_seal_digest") == capability_seal_digest()
        ):
            return value
        raise MLR01R4Error("R4 score seal drifted")
    context_seal = require_stage_seal("context", target_count)
    answer_seal = require_stage_seal("answer", target_count)
    judge_seal = require_stage_seal("judge", target_count)
    seal_digest = capability_seal_digest()
    contexts = load_context_records(target_count)
    answers = load_answer_records(target_count)
    judges = load_judge_records(target_count)
    if (
        context_seal.get("records_digest") != records_sha256(contexts)
        or answer_seal.get("records_digest") != records_sha256(answers)
        or judge_seal.get("records_digest") != records_sha256(judges)
    ):
        raise MLR01R4Error("R4 sealed cells drifted before scoring")
    cases = target_cases(target_count)
    labels = labels_from_dataset(DATASET_PATH, tuple(case.source_id for case in cases))
    context_by_key = {(str(row["case_id"]), str(row["arm"])): row for row in contexts}
    answer_by_key = {(str(row["case_id"]), str(row["arm"])): row for row in answers}
    judge_by_key = {(str(row["case_id"]), str(row["arm"])): row for row in judges}
    scored: list[dict[str, Any]] = []
    for case in cases:
        label = labels[case.source_id]
        relevant = list(label["answer_session_ids"])
        for arm in ARMS:
            key = case.source_id, arm
            context = context_by_key[key]
            answer = answer_by_key[key]
            judge = judge_by_key[key]
            if any(
                row.get("terminal_status") != "SUCCEEDED"
                for row in (context, answer, judge)
            ):
                raise MLR01R4Error("R4 scoring requires succeeded context/model cells")
            answer_score = score_answer(str(answer["answer"]), label["answers"])
            trace = context.get("retrieval_trace")
            if not isinstance(trace, list) or not all(
                isinstance(item, dict) for item in trace
            ):
                raise MLR01R4Error("R4 retrieval trace is invalid")
            retrieval = score_retrieval(trace, relevant)
            formation = context.get("formation")
            formed_applied = bool(
                arm == FORMED_ARM
                and isinstance(formation, Mapping)
                and formation.get("formation_applied") is True
            )
            scored.append(
                {
                    "case_id": case.source_id,
                    "category": case.category,
                    "arm": arm,
                    "judge_correct": int(judge["judge_correct"] is True),
                    "exact_match": int(answer_score["exact_match"]),
                    "normalized_f1": float(answer_score["normalized_f1"]),
                    "hit_at_k": int(retrieval["hit_at_k"]),
                    "retrieval_recall": float(retrieval["relevant_coverage_at_k"]),
                    "ndcg_at_k": float(retrieval["ndcg_at_k"]),
                    "mrr": _mrr(trace, relevant),
                    "retrieved_k": int(retrieval["retrieved_k"]),
                    "context_tokens": int(context["context_tokens"]),
                    "formation_applied": formed_applied,
                    "answer_prompt_tokens": int(answer["prompt_tokens"]),
                    "answer_completion_tokens": int(answer["completion_tokens"]),
                    "judge_prompt_tokens": int(judge["prompt_tokens"]),
                    "judge_completion_tokens": int(judge["completion_tokens"]),
                    "answer_provider_wall_ms": float(answer["wall_ms"]),
                    "judge_provider_wall_ms": float(judge["wall_ms"]),
                }
            )
    by_arm = {arm: [row for row in scored if row["arm"] == arm] for arm in ARMS}
    summaries = {arm: _arm_summary(by_arm[arm]) for arm in ARMS}
    paired_by_case = {
        case.source_id: {
            arm: next(
                row
                for row in scored
                if row["case_id"] == case.source_id and row["arm"] == arm
            )
            for arm in PRODUCT_ARMS
        }
        for case in cases
    }
    judge_differences = [
        float(rows[FORMED_ARM]["judge_correct"]) - float(rows[RAW_ARM]["judge_correct"])
        for rows in paired_by_case.values()
    ]
    recall_differences = [
        float(rows[FORMED_ARM]["retrieval_recall"])
        - float(rows[RAW_ARM]["retrieval_recall"])
        for rows in paired_by_case.values()
    ]
    f1_differences = [
        float(rows[FORMED_ARM]["normalized_f1"]) - float(rows[RAW_ARM]["normalized_f1"])
        for rows in paired_by_case.values()
    ]
    applied_cases = [
        rows
        for rows in paired_by_case.values()
        if rows[FORMED_ARM]["formation_applied"]
    ]
    correct_case_regression = sum(
        rows[RAW_ARM]["judge_correct"] == 1 and rows[FORMED_ARM]["judge_correct"] == 0
        for rows in paired_by_case.values()
    )
    correct_case_gain = sum(
        rows[RAW_ARM]["judge_correct"] == 0 and rows[FORMED_ARM]["judge_correct"] == 1
        for rows in paired_by_case.values()
    )
    paired_judge = paired_bootstrap(judge_differences)
    paired_recall = paired_bootstrap(recall_differences, seed=BOOTSTRAP_SEED + 1)
    paired_f1 = paired_bootstrap(f1_differences, seed=BOOTSTRAP_SEED + 2)
    ability: dict[str, dict[str, Any]] = {}
    for category in sorted({case.category for case in cases}):
        ability[category] = {
            arm: _arm_summary(
                [row for row in by_arm[arm] if row["category"] == category]
            )
            for arm in ARMS
        }
    formation_applied = int(context_seal["formation"]["applied"])
    formation_rate = formation_applied / target_count
    applied_subset = {
        "count": len(applied_cases),
        "interpretation": "DESCRIPTIVE_NOT_AN_INDEPENDENT_CAUSAL_ESTIMATE",
        "judge_accuracy_R": (
            round(mean(row[RAW_ARM]["judge_correct"] for row in applied_cases), 9)
            if applied_cases
            else None
        ),
        "judge_accuracy_F": (
            round(mean(row[FORMED_ARM]["judge_correct"] for row in applied_cases), 9)
            if applied_cases
            else None
        ),
        "judge_delta_F_minus_R": (
            round(
                mean(
                    row[FORMED_ARM]["judge_correct"] - row[RAW_ARM]["judge_correct"]
                    for row in applied_cases
                ),
                9,
            )
            if applied_cases
            else None
        ),
        "retrieval_recall_delta_F_minus_R": (
            round(
                mean(
                    row[FORMED_ARM]["retrieval_recall"]
                    - row[RAW_ARM]["retrieval_recall"]
                    for row in applied_cases
                ),
                9,
            )
            if applied_cases
            else None
        ),
    }
    safety = {
        "CorrectCaseRegression": correct_case_regression,
        "ReaderGroundingViolation": sum(
            int(row.get("reader_grounding_violation") or 0)
            for row in contexts
            if row["arm"] in PRODUCT_ARMS
        ),
        "AuthorityScopeRevocationViolation": sum(
            int(row.get("authority_scope_revocation_violation") or 0)
            for row in contexts
            if row["arm"] in PRODUCT_ARMS
        ),
        "CrossCaseEvidenceLeak": sum(
            int(row.get("cross_case_evidence_leak") or 0)
            for row in contexts
            if row["arm"] in PRODUCT_ARMS
        ),
        "AcceptedEvidenceIdentityIntegrity": min(
            int(row.get("accepted_evidence_identity_integrity") or 0)
            for row in contexts
            if row["arm"] in PRODUCT_ARMS
        ),
        "ReaderEvidenceSubsetIntegrity": min(
            int(row.get("reader_evidence_subset_integrity") or 0)
            for row in contexts
            if row["arm"] in PRODUCT_ARMS
        ),
    }
    full_run_viability = {
        "all_context_cells_terminal_and_succeeded": context_seal["status"] == "PASS",
        "all_answer_cells_terminal_and_succeeded": answer_seal["status"] == "PASS",
        "all_judge_cells_terminal_and_succeeded": judge_seal["status"] == "PASS",
        "product_delivery_success_1": context_seal["gate"][
            "product_delivery_success_1"
        ],
        "zero_isolation_safety_violation": all(
            safety[key] == 0
            for key in (
                "ReaderGroundingViolation",
                "AuthorityScopeRevocationViolation",
                "CrossCaseEvidenceLeak",
            )
        ),
        "projected_500_within_resource_window": context_seal["gate"][
            "projected_500_within_resource_window"
        ],
        "formation_coverage_reported": isinstance(
            context_seal.get("formation", {}).get("applied"), int
        ),
        "formation_applied_nonzero": formation_applied > 0,
    }
    execution_complete = all(
        value
        for key, value in full_run_viability.items()
        if key != "formation_applied_nonzero"
    )
    formal_denominator = target_count in FORMAL_TARGET_COUNTS
    viable = (
        execution_complete
        and full_run_viability["formation_applied_nonzero"]
        and formal_denominator
    )
    r3 = load_json(RUN_ROOT / "checkpoints/r3/progressive-boundary.json")
    if not isinstance(r3, dict) or r3.get("status") != "PASS":
        raise MLR01R4Error("R3 strict safety witness drifted before R4 scoring")
    r3_metrics = r3.get("metrics")
    if not isinstance(r3_metrics, dict):
        raise MLR01R4Error("R3 strict safety metrics are absent")
    strict_safety = {
        "source": "R3_PROGRESSIVE_BOUNDARY_SEALED_WITNESS",
        "StrictAcceptedBindingCorrect": r3_metrics.get("StrictAcceptedBindingCorrect"),
        "StrictAcceptedBindingTotal": r3_metrics.get("StrictAcceptedBindingTotal"),
        "StrictAcceptedBindingPrecision": r3_metrics.get(
            "StrictAcceptedBindingPrecision"
        ),
        "WrongCOMPLETE": r3_metrics.get("WrongCOMPLETE"),
        "CorrectCaseRegression": r3_metrics.get("CorrectCaseRegression"),
    }
    judge_lower = paired_judge["ci95"][0]
    candidate_supported = bool(
        viable
        and safety["ReaderGroundingViolation"] == 0
        and safety["AuthorityScopeRevocationViolation"] == 0
        and safety["CrossCaseEvidenceLeak"] == 0
        and safety["CorrectCaseRegression"] == 0
        and strict_safety["StrictAcceptedBindingPrecision"] == 1
        and strict_safety["WrongCOMPLETE"] == 0
        and strict_safety["CorrectCaseRegression"] == 0
        and isinstance(judge_lower, float)
        and judge_lower > 0
    )
    if not formal_denominator:
        candidate_disposition = "PILOT_ONLY_NO_FORMAL_CANDIDATE_DECISION"
    elif candidate_supported:
        candidate_disposition = "SUPPORTED_PAIRED_JUDGE_CI_POSITIVE"
    else:
        candidate_disposition = "NOT_SUPPORTED_BY_PAIRED_JUDGE_CI"
    comparisons: dict[str, dict[str, float | None]] = {}
    for arm in ARMS:
        if arm == RAW_ARM:
            continue
        comparisons[f"{arm}_minus_{RAW_ARM}"] = {
            metric: round(
                float(summaries[arm][metric]) - float(summaries[RAW_ARM][metric]), 9
            )
            for metric in (
                "VLLMJudgeAccuracy",
                "normalized_f1",
                "AnswerSessionRecallAtK",
                "NDCGAtK",
                "MRR",
            )
        }
        comparisons[f"{arm}_minus_{RAW_ARM}"]["judge_relative_delta"] = _relative_delta(
            float(summaries[arm]["VLLMJudgeAccuracy"]),
            float(summaries[RAW_ARM]["VLLMJudgeAccuracy"]),
        )
    score_records = {
        "schema": f"{SCHEMA_VERSION}.scored-records",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "record_count": len(scored),
        "records": scored,
        "reference_answers_retained": False,
    }
    atomic_json(R4_ROOT / f"scored-records-{target_count}.json", score_records)
    value = {
        "schema": f"{SCHEMA_VERSION}.score-seal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "terminal_count": len(scored),
        "status": (
            "PASS_PILOT_ONLY"
            if execution_complete and not formal_denominator
            else ("PASS" if viable else "FAIL_VIABILITY")
        ),
        "scored_records_digest": canonical_sha256(score_records),
        "arms": summaries,
        "ability_strata": ability,
        "comparisons": comparisons,
        "paired_F_minus_R": {
            "VLLMJudgeAccuracy": paired_judge,
            "normalized_f1": paired_f1,
            "AnswerSessionRecallAtK": paired_recall,
            "correct_case_gain": correct_case_gain,
            "correct_case_regression": correct_case_regression,
            "attribution_scope": "FORMATION_CAUSAL_COMPARISON_ONLY_FOR_F_MINUS_R",
        },
        "formation": {
            **dict(context_seal["formation"]),
            "applied_rate": round(formation_rate, 9),
            "treatment_interpretation": (
                "SPARSE_SPECIALIST_TREATMENT"
                if formation_rate < 0.10
                else "BROAD_TREATMENT"
            ),
            "ITT": {
                "judge_delta_F_minus_R": paired_judge["estimate"],
                "retrieval_recall_delta_F_minus_R": paired_recall["estimate"],
                "normalized_f1_delta_F_minus_R": paired_f1["estimate"],
            },
            "applied_subset": applied_subset,
        },
        "safety": safety,
        "strict_safety": strict_safety,
        "full_run_viability": full_run_viability,
        "pilot_execution_complete": execution_complete,
        "viable_for_500_extension": viable,
        "formal_denominator": formal_denominator,
        "execution_scope": (
            "USER_LIMITED_8_CASE_PILOT" if target_count == 8 else "FORMAL_STAIRCASE"
        ),
        "candidate_disposition_rule": (
            "SUPPORTED only when paired F-minus-R JudgeAccuracy bootstrap CI95 "
            "lower bound is >0 and all delivery/isolation safety gates pass"
        ),
        "candidate_disposition": candidate_disposition,
        "candidate_supported": candidate_supported,
        "baseline_comparison_scope": (
            "BM25/Dense differences are local system comparisons, not Formation attribution"
        ),
        "leaderboard_equivalence_claimed": False,
        "external_openai_or_gpt4o_calls": 0,
        "formal_holdout": False,
    }
    atomic_json(stage_seal_path("score", target_count), value)
    return value


__all__ = ["paired_bootstrap", "score"]
