"""Seal and score the frozen four-arm DG-21 opened-development evaluation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.dg16.lme10 import load_public_dev_cases, load_public_dev_labels
from evals.dg17.measurement import load_answer_bearing_labels
from evals.dg17.q6_matched import score_matched_records, summarize_matched_records
from evals.dg20.matched_q6_eval import _plans, _prepare_scoring_records

ARM_A = "A_DG20_TERMINAL_BASELINE"
ARM_B = "B_TYPE_SEMANTICS_FAST_STOP"
ARM_C = "C_TARGET_SOURCE_ADJACENCY_PREFERENCE"
ARM_D = "D_SAFE_QUERY_TIME_TEMPORAL_EVENT"
ARMS = (ARM_A, ARM_B, ARM_C, ARM_D)
BUDGETS = (512, 2_048)
CONTEXT_SCHEMA = "milai.dg21.s7-context-product.v0.1"
PRODUCT_SCHEMA = "milai.dg21.s7-matched-product.v0.1"
_FORBIDDEN = frozenset(
    {"answers", "answer_session_ids", "atoms", "gold_ir", "scorer_truth"}
)
_ZERO_GAIN = frozenset(
    {"2a1811e2", "2e6d26dc", "88432d0a", "9a707b82", "a89d7624", "gpt4_8279ba03"}
)


class DG21MatchedError(RuntimeError):
    pass


def seal_context_product(product: Mapping[str, Any], path: Path) -> None:
    _validate(product, CONTEXT_SCHEMA, require_answers=False)
    _seal(product, path)


def seal_reader_product(product: Mapping[str, Any], path: Path) -> None:
    _validate(product, PRODUCT_SCHEMA, require_answers=True)
    _seal(product, path)


def score_product(path: Path) -> dict[str, Any]:
    product = _load(path)
    _validate(product, PRODUCT_SCHEMA, require_answers=True)
    cases, selection = load_public_dev_cases()
    _envelope, labeled_cases, labels = load_answer_bearing_labels()
    case_ids = tuple(str(case.case_id) for case in cases)
    if tuple(str(case.case_id) for case in labeled_cases) != case_ids:
        raise DG21MatchedError("opened-development label order drifted")
    scoring_labels, scoring_identity = load_public_dev_labels(case_ids)
    plans = _plans(cases)
    prepared_records = _prepare_scoring_records(product["records"])
    scored: dict[str, list[dict[str, Any]]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        records = [row for row in prepared_records if row["arm"] == arm]
        scored[arm] = score_matched_records(
            records,
            cases=cases,
            labels=labels,
            scoring_labels=scoring_labels,
            plans=plans,
        )
        summaries[arm] = summarize_matched_records(scored[arm])

    final = summaries[ARM_D]
    baseline = summaries[ARM_A]
    a2048 = {
        row["case_id"]: row for row in scored[ARM_A] if row["token_budget"] == 2_048
    }
    d2048 = {
        row["case_id"]: row for row in scored[ARM_D] if row["token_budget"] == 2_048
    }
    already_correct = {
        case_id
        for case_id, row in a2048.items()
        if row["answer_score"]["exact_match"] == 1
    }
    regressions = sorted(
        case_id
        for case_id in already_correct
        if d2048[case_id]["answer_score"]["exact_match"] != 1
    )
    mediator_gain = sorted(
        case_id
        for case_id in _ZERO_GAIN
        if len(d2048[case_id]["retrieved_atom_ids"])
        > len(a2048[case_id]["retrieved_atom_ids"])
        or (
            bool(d2048[case_id]["operator_execution_correct"])
            and not bool(a2048[case_id]["operator_execution_correct"])
        )
    )
    efficiency = _efficiency(product["records"])
    floors = {
        "2048_coverage": final["2048"]["required_evidence_set_coverage"] >= 0.347826087,
        "2048_operator_ready": final["2048"]["operator_execution_accuracy"] is not None
        and round(float(final["2048"]["operator_execution_accuracy"]) * 9) >= 2,
        "2048_exact_match": int(final["2048"]["exact_match_count"]) >= 2,
        "2048_f1": float(final["2048"]["normalized_f1"]) >= 0.234848485,
        "2048_correct_regression_zero": not regressions,
        "512_coverage": final["512"]["required_evidence_set_coverage"] >= 0.304347826,
        "512_operator_ready": final["512"]["operator_execution_accuracy"] is not None
        and round(float(final["512"]["operator_execution_accuracy"]) * 9) >= 2,
        "512_exact_match": int(final["512"]["exact_match_count"]) >= 1,
        "512_f1": float(final["512"]["normalized_f1"]) >= 0.219896104,
    }
    safety = {
        "wrong_complete_zero": all(
            int(final[str(budget)]["wrong_complete_count"]) == 0 for budget in BUDGETS
        ),
        "automatic_retry_zero": sum(
            int(row["usage"]["automatic_retries"]) for row in product["records"]
        )
        == 0,
        "provider_controller_calls_zero": sum(
            int(row["usage"]["residual_provider_calls"]) for row in product["records"]
        )
        == 0,
        "canonical_mutation_zero": not any(
            bool(row["recovery"].get("canonical_mutation"))
            for row in product["records"]
        ),
        "formal_holdout_untouched": selection["formal_source_id_overlap"] == [],
        "candidate_default_false": product["candidate_default"] is False,
        "time_axis_substitution_zero": _recursive_sum(
            product, "time_axis_substitution_count"
        )
        == 0,
        "dg20_baseline_identity_exact": _baseline_matches_dg20_floor(baseline),
    }
    effect = {
        "prior_zero_gain_mediator_gain": bool(mediator_gain),
        "gain_case_ids": mediator_gain,
    }
    hard_gate = {
        "floors": {"passed": all(floors.values()), "checks": floors},
        "efficiency": {
            "passed": all(efficiency["checks"].values()),
            "checks": efficiency["checks"],
        },
        "safety": {"passed": all(safety.values()), "checks": safety},
        "effect": {
            "passed": bool(mediator_gain),
            "checks": {"prior_zero_gain_mediator_gain": bool(mediator_gain)},
        },
    }
    passed = all(section["passed"] for section in hard_gate.values())
    return {
        "schema": "milai.dg21.s7-score.v0.1",
        "status": "PASS_TYPE_DIRECTED_ACQUISITION_EFFICIENCY"
        if passed
        else "PARTIAL_OR_FAILED_GATES",
        "run_id": product["run_id"],
        "summaries": summaries,
        "efficiency": efficiency,
        "effect": effect,
        "correct_case_regressions": regressions,
        "hard_gate": {"passed": passed, "sections": hard_gate},
        "records": scored,
        "scoring_identity": scoring_identity,
        "labels_loaded_after_product_seal_sha256": hashlib.sha256(
            path.read_bytes()
        ).hexdigest(),
    }


def _efficiency(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    final = [
        row for row in records if row["arm"] == ARM_D and row["token_budget"] == 2_048
    ]
    audits = [row["search_trace"].get("semantic_audit") for row in final]
    legacy = sum(
        int(audit.get("legacy_binding_evaluation_count", 0))
        for audit in audits
        if isinstance(audit, Mapping)
    )
    current = sum(
        int(audit.get("binding_evaluation_count", 0))
        for audit in audits
        if isinstance(audit, Mapping)
    )
    mismatches = sum(
        int(audit.get("materialized_type_mismatch_count", 0))
        for audit in audits
        if isinstance(audit, Mapping)
    )
    additional = sum(int(row["usage"]["additional_acquisition_calls"]) for row in final)
    hydrated = sum(_extra_hydrated(row) for row in final)
    target_global = sum(_target_global_probe(row) for row in final)
    exact_aux = sum(_exact_complete_aux(row) for row in final)
    reduction = 1.0 - current / legacy if legacy else 0.0
    metrics: dict[str, Any] = {
        "legacy_binding_evaluation_count": legacy,
        "binding_evaluation_count": current,
        "binding_evaluation_reduction": round(reduction, 9),
        "materialized_type_mismatch_count": mismatches,
        "materialized_type_mismatch_reduction": 1.0 if mismatches == 0 else 0.0,
        "candidates_hydrated": hydrated,
        "additional_acquisition_calls": additional,
        "target_only_global_probe_executions": target_global,
        "exact_complete_auxiliary_calls": exact_aux,
    }
    metrics["checks"] = {
        "materialized_type_mismatch_reduction_at_least_80pct": metrics[
            "materialized_type_mismatch_reduction"
        ]
        >= 0.8,
        "binding_evaluation_reduction_at_least_70pct": reduction >= 0.7,
        "candidates_hydrated_at_most_64": hydrated <= 64,
        "additional_acquisition_calls_at_most_8": additional <= 8,
        "target_only_global_probe_executions_zero": target_global == 0,
        "exact_complete_auxiliary_calls_zero": exact_aux == 0,
    }
    return metrics


def _baseline_matches_dg20_floor(summary: Mapping[str, Mapping[str, Any]]) -> bool:
    expected = {
        "2048": (0.347826087, 0.222222222, 2, 0.234848485),
        "512": (0.304347826, 0.222222222, 1, 0.219896104),
    }
    for budget, (coverage, operator, exact, f1) in expected.items():
        observed = summary[budget]
        if (
            float(observed["required_evidence_set_coverage"]) != coverage
            or float(observed["operator_execution_accuracy"]) != operator
            or int(observed["exact_match_count"]) != exact
            or float(observed["normalized_f1"]) != f1
        ):
            return False
    return True


def _extra_hydrated(row: Mapping[str, Any]) -> int:
    if int(row["usage"]["additional_acquisition_calls"]) == 0:
        return 0
    dispositions = row["search_trace"].get("acquisition_probe_dispositions", [])
    return sum(
        int(item.get("selected_candidate_count", 0))
        for item in dispositions
        if isinstance(item, Mapping)
        and item.get("status") == "EXECUTED"
        and str(item.get("probe_id", "")).startswith("action:")
    )


def _target_global_probe(row: Mapping[str, Any]) -> int:
    recovery = row["recovery"]
    decision = recovery.get("decision") if isinstance(recovery, Mapping) else None
    action = decision.get("selected_action") if isinstance(decision, Mapping) else None
    if not isinstance(action, Mapping) or not action.get("target_requirement_id"):
        return 0
    dispositions = row["search_trace"].get("acquisition_probe_dispositions", [])
    return sum(
        1
        for item in dispositions
        if isinstance(item, Mapping)
        and item.get("status") == "EXECUTED"
        and item.get("requirement_id") is None
    )


def _exact_complete_aux(row: Mapping[str, Any]) -> int:
    recovery = row["recovery"]
    return int(
        recovery.get("attempted") is False
        and recovery.get("decision", {}).get("reason_code") == "COMPLETE"
        and int(recovery.get("extra_pass_count", 0)) != 0
    )


def _validate(
    product: Mapping[str, Any], schema: str, *, require_answers: bool
) -> None:
    records = product.get("records")
    expected = {
        (case.case_id, arm, budget)
        for case in load_public_dev_cases()[0]
        for arm in ARMS
        for budget in BUDGETS
    }
    if (
        product.get("schema") != schema
        or product.get("labels_loaded") is not False
        or not isinstance(records, list)
    ):
        raise DG21MatchedError("product envelope is invalid")
    observed = {
        (row.get("case_id"), row.get("arm"), row.get("token_budget"))
        for row in records
        if isinstance(row, Mapping)
    }
    if len(records) != 80 or observed != expected or len(observed) != 80:
        raise DG21MatchedError("four-arm denominator drifted")
    if require_answers != all(isinstance(row.get("answer"), str) for row in records):
        raise DG21MatchedError("Reader phase boundary drifted")
    if _recursive_keys(product).intersection(_FORBIDDEN):
        raise DG21MatchedError("scorer truth leaked into product")


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(value).union(*(_recursive_keys(v) for v in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_recursive_keys(v) for v in value), set())
    return set()


def _recursive_sum(value: object, key: str) -> int:
    if isinstance(value, Mapping):
        return (
            int(value.get(key, 0)) if isinstance(value.get(key, 0), int) else 0
        ) + sum(_recursive_sum(v, key) for v in value.values())
    if isinstance(value, list):
        return sum(_recursive_sum(v, key) for v in value)
    return 0


def _seal(value: Mapping[str, Any], path: Path) -> None:
    if path.exists():
        raise DG21MatchedError(f"sealed artifact exists: {path}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value
