"""Merge, score, and classify the complete LongMemEval matched validation."""

from __future__ import annotations

import hashlib
import math
import os
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

from evals.paper.datasets.longmemeval import labels_from_dataset, load_inputs
from evals.paper.scorers.longmemeval import SCORER_ID, score_answer, score_retrieval

from .longmemeval_contexts import load_context_records
from .longmemeval_contract import (
    ARMS,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CASE_COUNT,
    CHECKPOINT_ROOT,
    DATASET_PATH,
    INPUT_PATH,
    RETRIEVAL_CASE_COUNT,
    RUN_ID,
    RUN_ROOT,
    SCHEMA_VERSION,
    LongMemEvalClosureError,
    atomic_json,
    canonical_json,
    load_json,
    require_run_lock,
    sha256_file,
)
from .longmemeval_providers import load_answer_records, load_judge_records


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _latency(values: Sequence[float]) -> dict[str, float]:
    return {
        "count": len(values),
        "mean_ms": round(mean(values), 6) if values else 0.0,
        "p50_ms": round(_percentile(values, 0.5), 6),
        "p95_ms": round(_percentile(values, 0.95), 6),
        "total_ms": round(sum(values), 6),
    }


def _paired_bootstrap(values: Sequence[float]) -> dict[str, float | int | str]:
    if len(values) != CASE_COUNT:
        raise LongMemEvalClosureError("paired bootstrap denominator drifted")
    generator = random.Random(BOOTSTRAP_SEED)
    samples = []
    for _sample in range(BOOTSTRAP_SAMPLES):
        samples.append(
            sum(values[generator.randrange(len(values))] for _ in values) / len(values)
        )
    return {
        "observed_delta": round(mean(values), 9),
        "ci95_lower": round(_percentile(samples, 0.025), 9),
        "ci95_upper": round(_percentile(samples, 0.975), 9),
        "samples": BOOTSTRAP_SAMPLES,
        "seed": BOOTSTRAP_SEED,
        "unit": "question_id",
    }


def _mrr(trace: Sequence[Mapping[str, Any]], relevant: set[str]) -> float:
    seen: set[str] = set()
    rank = 0
    for item in trace:
        session_id = item.get("session_id")
        if not isinstance(session_id, str) or session_id in seen:
            continue
        seen.add(session_id)
        rank += 1
        if session_id in relevant:
            return 1.0 / rank
    return 0.0


def _ability(case_id: str, category: str) -> str:
    if "_abs" in case_id:
        return "abstention"
    return {
        "single-session-preference": "preference",
        "single-session-user": "single-session user",
        "single-session-assistant": "single-session assistant",
        "multi-session": "multi-session",
        "temporal-reasoning": "temporal reasoning",
        "knowledge-update": "knowledge update",
    }.get(category, category)


def _first_loss(record: Mapping[str, Any], *, abstention: bool) -> str:
    if record["context_terminal_status"] != "SUCCEEDED":
        return "CONTEXT_OR_PRODUCT_PATH_FAILURE"
    if record["answer_terminal_status"] != "SUCCEEDED":
        return "ANSWER_PROVIDER_FAILURE"
    if record["judge_terminal_status"] != "SUCCEEDED":
        return "JUDGE_PROVIDER_FAILURE"
    retrieval = record.get("retrieval_score")
    if (
        not abstention
        and isinstance(retrieval, Mapping)
        and retrieval.get("hit_at_k") == 0
    ):
        return "RETRIEVAL_FIRST_LOSS"
    if record["official_accuracy"] == 0:
        return "READER_SYNTHESIS_OR_SUFFICIENCY_FIRST_LOSS"
    return "NO_LOSS"


def _arm_record(
    *,
    context: Mapping[str, Any],
    answer: Mapping[str, Any],
    judge: Mapping[str, Any],
    labels: Mapping[str, Any],
) -> dict[str, Any]:
    case_id = str(context["case_id"])
    abstention = "_abs" in case_id
    answer_score = (
        score_answer(str(answer["answer"]), labels["answers"])
        if answer.get("terminal_status") == "SUCCEEDED"
        else {"exact_match": 0, "normalized_f1": 0.0, "scorer": SCORER_ID}
    )
    trace = [
        dict(item)
        for item in context.get("retrieval_trace", [])
        if isinstance(item, Mapping)
    ]
    retrieval_score: Mapping[str, Any] | None = None
    reciprocal_rank: float | None = None
    answer_session_turn_hit: int | None = None
    if not abstention:
        retrieval_score = score_retrieval(trace, labels["answer_session_ids"])
        relevant = {str(value) for value in labels["answer_session_ids"]}
        reciprocal_rank = round(_mrr(trace, relevant), 9)
        answer_session_turn_hit = int(
            any(item.get("session_id") in relevant for item in trace)
        )
    official_accuracy = int(
        judge.get("terminal_status") == "SUCCEEDED"
        and judge.get("judge_correct") is True
    )
    sufficiency = str(context.get("sufficiency_status", "UNKNOWN"))
    result = {
        "arm": context["arm"],
        "context_terminal_status": context["terminal_status"],
        "context_sha256": context["context_sha256"],
        "context_tokens": context["context_tokens"],
        "retrieval_status": context.get("retrieval_status"),
        "retrieval_trace": trace,
        "retrieval_score": retrieval_score,
        "retrieval_mrr": reciprocal_rank,
        "answer_session_turn_hit_at_k": answer_session_turn_hit,
        "answer_terminal_status": answer["terminal_status"],
        "answer": answer["answer"],
        "answer_sha256": answer["answer_sha256"],
        "answer_score": answer_score,
        "judge_terminal_status": judge["terminal_status"],
        "judge_correct": judge["judge_correct"],
        "judge_response_sha256": judge["judge_response_sha256"],
        "official_accuracy": official_accuracy,
        "sufficiency_status": sufficiency,
        "wrong_complete": int(sufficiency == "COMPLETE" and not official_accuracy),
        "accepted_binding_precision": context["accepted_binding_precision"],
        "boundary_binding_recall": context["boundary_binding_recall"],
        "operator_ready": context.get("operator_ready", 0),
        "temporal_complete": context.get("temporal_complete"),
        "reader_grounding_violation": context["reader_grounding_violation"],
        "authority_scope_revocation_violation": context[
            "authority_scope_revocation_violation"
        ],
        "formation": dict(context.get("formation", {})),
        "timings_ms": dict(context.get("timings_ms", {})),
        "usage": dict(context.get("usage", {})),
        "answer_usage": {
            "wall_ms": answer.get("wall_ms", 0),
            "tokenize_ms": answer.get("tokenize_ms", 0),
            "provider_ms": answer.get("provider_ms", 0),
            "prompt_tokens": answer.get("prompt_tokens", 0),
            "memory_tokens": answer.get("memory_tokens", 0),
            "completion_tokens": answer.get("completion_tokens", 0),
            "provider_called": answer.get("provider_called") is True,
        },
        "judge_usage": {
            "wall_ms": judge.get("wall_ms", 0),
            "prompt_tokens": judge.get("prompt_tokens", 0),
            "completion_tokens": judge.get("completion_tokens", 0),
        },
    }
    result["first_loss"] = _first_loss(result, abstention=abstention)
    return result


def _aggregate_arm(records: Sequence[Mapping[str, Any]], arm: str) -> dict[str, Any]:
    selected = [record["arms"][arm] for record in records]
    retrieval = [
        value for value in selected if isinstance(value.get("retrieval_score"), Mapping)
    ]
    by_ability: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for outer, value in zip(records, selected, strict=True):
        by_ability[str(outer["ability"])].append(value)
    return {
        "qa_denominator": len(selected),
        "retrieval_denominator": len(retrieval),
        "official_accuracy": round(
            mean(value["official_accuracy"] for value in selected), 9
        ),
        "exact_match": round(
            mean(value["answer_score"]["exact_match"] for value in selected), 9
        ),
        "normalized_f1": round(
            mean(value["answer_score"]["normalized_f1"] for value in selected), 9
        ),
        "ability_accuracy": {
            ability: {
                "accuracy": round(
                    mean(value["official_accuracy"] for value in values), 9
                ),
                "count": len(values),
            }
            for ability, values in sorted(by_ability.items())
        },
        "retrieval": {
            "session_hit_at_k": round(
                mean(value["retrieval_score"]["hit_at_k"] for value in retrieval), 9
            ),
            "session_recall_at_k": round(
                mean(
                    value["retrieval_score"]["relevant_coverage_at_k"]
                    for value in retrieval
                ),
                9,
            ),
            "ndcg_at_k": round(
                mean(value["retrieval_score"]["ndcg_at_k"] for value in retrieval), 9
            ),
            "mrr": round(mean(value["retrieval_mrr"] for value in retrieval), 9),
            "answer_session_turn_hit_at_k": round(
                mean(value["answer_session_turn_hit_at_k"] for value in retrieval), 9
            ),
            "exact_answer_turn_labels_available": False,
            "turn_metric_interpretation": (
                "selected turn Evidence belongs to a labeled answer-bearing session"
            ),
        },
        "context_failures": sum(
            value["context_terminal_status"] != "SUCCEEDED" for value in selected
        ),
        "answer_failures": sum(
            value["answer_terminal_status"] != "SUCCEEDED" for value in selected
        ),
        "judge_failures": sum(
            value["judge_terminal_status"] != "SUCCEEDED" for value in selected
        ),
        "AcceptedBindingPrecision": min(
            int(value["accepted_binding_precision"]) for value in selected
        ),
        "ValidBindingRecall_boundary": min(
            int(value["boundary_binding_recall"]) for value in selected
        ),
        "OperatorReadyRate": round(
            mean(value["operator_ready"] for value in selected), 9
        ),
        "TemporalCompletenessRate": round(
            mean(
                value["temporal_complete"]
                for value in selected
                if value["temporal_complete"] is not None
            ),
            9,
        ),
        "WrongCOMPLETE": sum(value["wrong_complete"] for value in selected),
        "reader_grounding_violations": sum(
            value["reader_grounding_violation"] for value in selected
        ),
        "authority_scope_revocation_violations": sum(
            value["authority_scope_revocation_violation"] for value in selected
        ),
        "formation_applied": sum(
            value["formation"].get("applied") is True for value in selected
        ),
        "formation_fallback": sum(
            value["formation"].get("fallback_taken") is True for value in selected
        ),
        "formation_canonical_mutations": sum(
            value["formation"].get("canonical_mutation") is True for value in selected
        ),
        "hydrated_evidence_units": sum(
            int(value["formation"].get("hydrated_source_count") or 0)
            for value in selected
        ),
        "first_loss": {
            label: sum(value["first_loss"] == label for value in selected)
            for label in sorted({str(value["first_loss"]) for value in selected})
        },
    }


def _efficiency(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    arm_values = [value for record in records for value in record["arms"].values()]
    stages = {
        "ingest": [float(value["timings_ms"].get("ingest", 0)) for value in arm_values],
        "index": [
            float(value["timings_ms"].get("index_barrier", 0)) for value in arm_values
        ],
        "query": [
            float(value["usage"].get("retrieval_ms") or 0) for value in arm_values
        ],
        "context_compile": [
            float(value["usage"].get("context_compile_ms") or 0) for value in arm_values
        ],
        "reader": [
            float(value["answer_usage"].get("wall_ms", 0)) for value in arm_values
        ],
        "judge": [
            float(value["judge_usage"].get("wall_ms", 0)) for value in arm_values
        ],
    }
    shard_terminals = []
    for arm in ARMS:
        for shard in range(4):
            path = (
                CHECKPOINT_ROOT / "full/contexts" / arm / f"shard-{shard}-terminal.json"
            )
            value = load_json(path)
            if isinstance(value, dict):
                shard_terminals.append(value)
    answer_seal = load_json(CHECKPOINT_ROOT / "full/answer-seal.json")
    judge_seal = load_json(CHECKPOINT_ROOT / "full/judge-seal.json")
    context_wall_ms = sum(
        max(
            float(value.get("wall_ms", 0))
            for value in shard_terminals
            if value.get("arm") == arm
        )
        for arm in ARMS
    )
    total_wall_ms = (
        context_wall_ms
        + float(answer_seal.get("wall_ms", 0))
        + float(judge_seal.get("wall_ms", 0))
    )
    return {
        "latency": {name: _latency(values) for name, values in stages.items()},
        "context_stage_wall_ms_estimate": round(context_wall_ms, 6),
        "answer_stage_wall_ms": answer_seal.get("wall_ms"),
        "judge_stage_wall_ms": judge_seal.get("wall_ms"),
        "end_to_end_stage_wall_ms_estimate": round(total_wall_ms, 6),
        "throughput_case_arm_per_minute": round(
            (CASE_COUNT * len(ARMS)) / (total_wall_ms / 60_000)
            if total_wall_ms > 0
            else 0.0,
            6,
        ),
        "model_calls": {
            "formation": 0,
            "memory_query": 0,
            "answer": sum(
                value["answer_usage"]["provider_called"] for value in arm_values
            ),
            "judge": len(arm_values),
        },
        "tokens": {
            "answer_prompt": sum(
                int(value["answer_usage"].get("prompt_tokens", 0))
                for value in arm_values
            ),
            "answer_memory": sum(
                int(value["answer_usage"].get("memory_tokens", 0))
                for value in arm_values
            ),
            "answer_completion": sum(
                int(value["answer_usage"].get("completion_tokens", 0))
                for value in arm_values
            ),
            "judge_prompt": sum(
                int(value["judge_usage"].get("prompt_tokens", 0))
                for value in arm_values
            ),
            "judge_completion": sum(
                int(value["judge_usage"].get("completion_tokens", 0))
                for value in arm_values
            ),
        },
        "peak_child_rss_kib": max(
            (int(value.get("peak_rss_kib", 0)) for value in shard_terminals),
            default=0,
        ),
        "gpu_assignment": "existing vLLM on cuda:0,1; no dense lane",
    }


def _write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        for record in records:
            handle.write(canonical_json(record))
            handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _terminal_records_digest(records: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        records,
        key=lambda value: (str(value.get("case_id")), str(value.get("arm"))),
    )
    return hashlib.sha256(canonical_json(ordered)).hexdigest()


def _require_scoring_seals(
    *,
    run_lock_digest: str,
    answers: Sequence[Mapping[str, Any]],
    judges: Sequence[Mapping[str, Any]],
) -> None:
    answer_seal = load_json(CHECKPOINT_ROOT / "full/answer-seal.json")
    judge_seal = load_json(CHECKPOINT_ROOT / "full/judge-seal.json")
    label_open = load_json(CHECKPOINT_ROOT / "full/labels-opened.json")
    if (
        not isinstance(answer_seal, dict)
        or answer_seal.get("schema") != f"{SCHEMA_VERSION}.answer-seal"
        or answer_seal.get("run_lock_digest") != run_lock_digest
        or answer_seal.get("terminal_count") != CASE_COUNT * len(ARMS)
        or answer_seal.get("records_digest") != _terminal_records_digest(answers)
        or answer_seal.get("labels_opened") is not False
    ):
        raise LongMemEvalClosureError("scoring answer seal is invalid")
    if (
        not isinstance(judge_seal, dict)
        or judge_seal.get("schema") != f"{SCHEMA_VERSION}.judge-seal"
        or judge_seal.get("run_lock_digest") != run_lock_digest
        or judge_seal.get("terminal_count") != CASE_COUNT * len(ARMS)
        or judge_seal.get("records_digest") != _terminal_records_digest(judges)
        or judge_seal.get("labels_opened_after_answer_seal") is not True
    ):
        raise LongMemEvalClosureError("scoring judge seal is invalid")
    if (
        not isinstance(label_open, dict)
        or label_open.get("schema") != f"{SCHEMA_VERSION}.label-open"
        or label_open.get("run_lock_digest") != run_lock_digest
        or label_open.get("status") != "OPENED"
        or label_open.get("formal_holdout") != "NOT_OPENED"
        or label_open.get("dataset_sha256") != sha256_file(DATASET_PATH)
        or label_open.get("answer_seal_digest") != answer_seal.get("records_digest")
    ):
        raise LongMemEvalClosureError("scoring label-open boundary is invalid")


def score_and_finalize() -> tuple[dict[str, Any], dict[str, Any]]:
    run_lock = require_run_lock()
    run_lock_digest = str(run_lock["run_lock_digest"])
    _partition, cases = load_inputs(INPUT_PATH)
    context_records = load_context_records("full")
    answer_records = load_answer_records()
    judge_records = load_judge_records()
    contexts = {
        (str(value["case_id"]), str(value["arm"])): value for value in context_records
    }
    answers = {
        (str(value["case_id"]), str(value["arm"])): value for value in answer_records
    }
    judges = {
        (str(value["case_id"]), str(value["arm"])): value for value in judge_records
    }
    expected = {(case.source_id, arm) for case in cases for arm in ARMS}
    if set(contexts) != expected or set(answers) != expected or set(judges) != expected:
        raise LongMemEvalClosureError(
            "score inputs do not cover the matched denominator"
        )
    _require_scoring_seals(
        run_lock_digest=run_lock_digest,
        answers=answer_records,
        judges=judge_records,
    )
    labels = labels_from_dataset(DATASET_PATH, tuple(case.source_id for case in cases))
    records: list[dict[str, Any]] = []
    for case in sorted(cases, key=lambda value: value.source_id):
        arms = {
            arm: _arm_record(
                context=contexts[(case.source_id, arm)],
                answer=answers[(case.source_id, arm)],
                judge=judges[(case.source_id, arm)],
                labels=labels[case.source_id],
            )
            for arm in ARMS
        }
        records.append(
            {
                "schema": f"{SCHEMA_VERSION}.case-terminal",
                "run_id": RUN_ID,
                "run_lock_digest": run_lock_digest,
                "case_id": case.source_id,
                "category": case.category,
                "ability": _ability(case.source_id, case.category),
                "abstention": "_abs" in case.source_id,
                "terminal_status": "TERMINAL",
                "arms": arms,
                "paired": {
                    "official_accuracy_delta": (
                        arms["LME-C"]["official_accuracy"]
                        - arms["LME-R"]["official_accuracy"]
                    ),
                    "normalized_f1_delta": round(
                        float(arms["LME-C"]["answer_score"]["normalized_f1"])
                        - float(arms["LME-R"]["answer_score"]["normalized_f1"]),
                        9,
                    ),
                    "correct_case_regression": int(
                        arms["LME-R"]["official_accuracy"] == 1
                        and arms["LME-C"]["official_accuracy"] == 0
                    ),
                },
            }
        )
    if len(records) != CASE_COUNT or sum(
        not value["abstention"] for value in records
    ) != (RETRIEVAL_CASE_COUNT):
        raise LongMemEvalClosureError("LongMemEval final denominator drifted")
    aggregates = {arm: _aggregate_arm(records, arm) for arm in ARMS}
    paired = _paired_bootstrap(
        [float(record["paired"]["normalized_f1_delta"]) for record in records]
    )
    abilities = sorted({str(record["ability"]) for record in records})
    ability_deltas = {
        ability: round(
            aggregates["LME-C"]["ability_accuracy"][ability]["accuracy"]
            - aggregates["LME-R"]["ability_accuracy"][ability]["accuracy"],
            9,
        )
        for ability in abilities
    }
    correct_case_regression = sum(
        int(record["paired"]["correct_case_regression"]) for record in records
    )
    core_gates = {
        "qa_terminal_500_of_500": len(records) == CASE_COUNT,
        "retrieval_denominator_470": sum(not value["abstention"] for value in records)
        == RETRIEVAL_CASE_COUNT,
        "unique_merge": len({value["case_id"] for value in records}) == CASE_COUNT,
        "label_leakage": 0,
        "authority_scope_revocation_violations": aggregates["LME-C"][
            "authority_scope_revocation_violations"
        ],
    }
    external_gates = {
        "paired_normalized_f1_delta_ci95_lower_gte_minus_0_02": (
            float(paired["ci95_lower"]) >= -0.02
        ),
        "no_ability_accuracy_delta_lt_minus_0_05": all(
            value >= -0.05 for value in ability_deltas.values()
        ),
        "AcceptedBindingPrecision_eq_1": aggregates["LME-C"]["AcceptedBindingPrecision"]
        == 1,
        "WrongCOMPLETE_eq_0": aggregates["LME-C"]["WrongCOMPLETE"] == 0,
        "CorrectCaseRegression_eq_0": correct_case_regression == 0,
    }
    safety_pass = (
        aggregates["LME-C"]["authority_scope_revocation_violations"] == 0
        and aggregates["LME-C"]["reader_grounding_violations"] == 0
        and aggregates["LME-C"]["formation_canonical_mutations"] == 0
    )
    complete_execution = all(
        [
            core_gates["qa_terminal_500_of_500"],
            core_gates["retrieval_denominator_470"],
            core_gates["unique_merge"],
            core_gates["label_leakage"] == 0,
            core_gates["authority_scope_revocation_violations"] == 0,
        ]
    )
    external_pass = all(external_gates.values())
    mediator_direction_consistent = (
        aggregates["LME-C"]["formation_applied"] > 0
        and float(paired["observed_delta"]) >= 0
    )
    if not safety_pass:
        status = "FAIL_LONGMEMEVAL_AUTHORITY_OR_DATA_SAFETY"
        recommendation = "REJECT_CANDIDATE"
        support = "NO_EXTERNAL_SUPPORT"
    elif not complete_execution:
        status = "PARKED_LONGMEMEVAL_INCOMPLETE_EXECUTION"
        recommendation = "KEEP_FLAG_OFF"
        support = "NO_EXTERNAL_SUPPORT"
    elif not external_pass:
        status = "BELOW_TARGET"
        recommendation = "KEEP_FLAG_OFF"
        support = "NO_EXTERNAL_SUPPORT"
    else:
        status = "PASS_LONGMEMEVAL_EXTERNAL_NONREGRESSION"
        recommendation = "SHADOW_ONLY"
        support = (
            "EXTERNAL_SUPPORT"
            if mediator_direction_consistent
            else "NONREGRESSION_ONLY"
        )
    results_path = RUN_ROOT / "longmemeval-results.jsonl"
    _write_jsonl(results_path, records)
    summary_material = {
        "schema": f"{SCHEMA_VERSION}.summary",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock_digest,
        "status": status,
        "classification": "EXTERNAL_PUBLIC_BENCHMARK",
        "formal_validation": "NOT_RUN",
        "case_count": CASE_COUNT,
        "arm_count": len(ARMS),
        "qa_denominator": CASE_COUNT,
        "retrieval_denominator": RETRIEVAL_CASE_COUNT,
        "result_records_sha256": sha256_file(results_path),
        "dataset_sha256": sha256_file(DATASET_PATH),
        "scorer": SCORER_ID,
        "judge_protocol": {
            "prompt_semantics": "UPSTREAM_GET_ANSCHECK_PROMPT",
            "model": run_lock["provider"]["model_id"],
            "same_model_self_judge": True,
            "leaderboard_equivalence_claimed": False,
        },
        "arms": aggregates,
        "paired_normalized_f1": paired,
        "ability_accuracy_deltas_candidate_minus_raw": ability_deltas,
        "CorrectCaseRegression": correct_case_regression,
        "core_execution_gates": core_gates,
        "external_nonregression_gates": external_gates,
        "safety_pass": safety_pass,
        "complete_execution": complete_execution,
        "external_nonregression_pass": external_pass,
        "mediator_direction_consistent_with_c2": mediator_direction_consistent,
        "external_evidence_classification": support,
        "release_recommendation": recommendation,
        "efficiency": _efficiency(records),
        "retuning_after_results": False,
        "rerun_after_results": False,
    }
    summary = {
        **summary_material,
        "summary_digest": hashlib.sha256(canonical_json(summary_material)).hexdigest(),
    }
    atomic_json(RUN_ROOT / "longmemeval-summary.json", summary)
    terminal_material = {
        "schema": f"{SCHEMA_VERSION}.terminal",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock_digest,
        "status": status,
        "summary_digest": summary["summary_digest"],
        "results_sha256": sha256_file(results_path),
        "qa_denominator": CASE_COUNT,
        "retrieval_denominator": RETRIEVAL_CASE_COUNT,
        "formal_validation": "NOT_RUN",
        "external_evidence_classification": support,
        "release_recommendation": recommendation,
    }
    terminal = {
        **terminal_material,
        "terminal_digest": hashlib.sha256(
            canonical_json(terminal_material)
        ).hexdigest(),
    }
    atomic_json(RUN_ROOT / "longmemeval-terminal.json", terminal)
    return summary, terminal


__all__ = ["score_and_finalize"]
