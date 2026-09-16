"""DG-22 S8 frozen-context matched answer correctness."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

from evals.dg14.provider import full_provider_contract_sha256
from evals.dg16.lme10 import load_public_dev_cases, load_public_dev_labels
from evals.paper.scorers.longmemeval import score_answer

BASELINE_ARM = "A_DG20_BASELINE_ANSWER_REUSE"
CANDIDATE_ARM = "B_DG22_FROZEN_FINAL_CONTEXT"
ARMS = (BASELINE_ARM, CANDIDATE_ARM)
BUDGETS = (512, 2048)
CONTEXT_SCHEMA = "milai.dg22.s8-answer-context-product.v0.1"
READER_SCHEMA = "milai.dg22.s8-answer-reader-product.v0.1"
S2_RECEIPT = Path("var/dg22/s2/dg22-s2-reader-conformance-20260829-001/receipt.json")
S2_CONTRACT = Path(
    "var/dg22/s2/dg22-s2-reader-conformance-20260829-001/selected-reader-contract.json"
)
S7_RECEIPT = Path("var/dg22/s7/dg22-s7-mediator-20260829-001/receipt.json")
S7_PRODUCT = Path(
    "var/dg22/s7/dg22-s7-mediator-20260829-001/sealed-mediator-product.json"
)
DG20_PRODUCT = Path(
    "var/dg20/s5/dg20-s5-matched-q6-20260828-002/sealed-product-trace.json"
)
DG20_SOURCE_ARM = "B_FRESH_STATE_DETERMINISTIC_CAPABILITY_POLICY"
S7_BASELINE_ARM = "A_DG20_TERMINAL_BASELINE"
S7_CANDIDATE_ARM = "E_SAFE_TEMPORAL_APPLICABILITY_COUNT"


def build_answer_context_product(root: Path, *, run_id: str) -> dict[str, Any]:
    """Freeze the two answer arms without loading scorer answers or labels."""
    s2 = _read(root / S2_RECEIPT)
    s7 = _read(root / S7_RECEIPT)
    contract = _read(root / S2_CONTRACT)
    mediator = _read(root / S7_PRODUCT)
    dg20 = _read(root / DG20_PRODUCT)
    if s2.get("status") != "PASS_READER_CONFORMANCE" or not s2["hard_gate"]["passed"]:
        raise ValueError("DG22_S8_READER_ENTRY_GATE_FAILED")
    if (
        s7.get("status") != "PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION"
        or not s7["hard_gate"]["passed"]
    ):
        raise ValueError("DG22_S8_MEDIATOR_ENTRY_GATE_FAILED")
    if contract.get("contract_sha256") != full_provider_contract_sha256():
        raise ValueError("DG22_S8_READER_CONTRACT_DRIFT")
    cases, selection = load_public_dev_cases()
    case_ids = tuple(str(case.case_id) for case in cases)
    questions = {str(case.case_id): str(case.question) for case in cases}
    question_times = {str(case.case_id): str(case.question_at) for case in cases}
    baseline = _index(mediator["records"], S7_BASELINE_ARM)
    candidate = _index(mediator["records"], S7_CANDIDATE_ARM)
    dg20_baseline = _index(dg20["records"], DG20_SOURCE_ARM)
    records: list[dict[str, Any]] = []
    for case_id in case_ids:
        for budget in BUDGETS:
            key = (case_id, budget)
            if baseline[key]["context_sha256"] != dg20_baseline[key]["context_sha256"]:
                raise ValueError("DG22_S8_DG20_BASELINE_CONTEXT_DRIFT")
            for arm, source in (
                (BASELINE_ARM, baseline[key]),
                (CANDIDATE_ARM, candidate[key]),
            ):
                records.append(
                    {
                        "case_id": case_id,
                        "category": source["category"],
                        "arm": arm,
                        "method_id": arm,
                        "token_budget": budget,
                        "question": questions[case_id],
                        "question_as_of": question_times[case_id],
                        "context": source["context"],
                        "context_sha256": source["context_sha256"],
                        "context_tokens": source["context_tokens"],
                        "selected_source_refs": list(source["selected_source_refs"]),
                        "source_snapshot_digest": source["source_snapshot_digest"],
                        "sufficiency_status": source.get(
                            "sufficiency_status", "PARTIAL"
                        ),
                        "operator_ready": bool(source.get("operator_ready")),
                        "reader_source": "PENDING_AFTER_CONTEXT_SEAL",
                    }
                )
    _validate_denominator(records)
    return {
        "schema": CONTEXT_SCHEMA,
        "status": "CONTEXTS_FROZEN_UNREAD",
        "run_id": run_id,
        "arms": list(ARMS),
        "budgets": list(BUDGETS),
        "case_order": case_ids,
        "records": records,
        "reader_contract": contract,
        "entry_s2_receipt": _identity(root / S2_RECEIPT, root),
        "entry_s7_receipt": _identity(root / S7_RECEIPT, root),
        "sealed_s7_product": _identity(root / S7_PRODUCT, root),
        "dg20_baseline_product": _identity(root / DG20_PRODUCT, root),
        "selection_identity": selection["identities"],
        "labels_loaded": False,
        "retrieval_frozen": True,
        "candidate_default": False,
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
    }


def seal_answer_context_product(product: Mapping[str, Any], path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    if (
        product.get("schema") != CONTEXT_SCHEMA
        or product.get("labels_loaded") is not False
    ):
        raise ValueError("DG22_S8_CONTEXT_PRODUCT_INVALID")
    records = product.get("records", [])
    if any(isinstance(row, Mapping) and "answer" in row for row in records):
        raise ValueError("DG22_S8_ANSWER_BEFORE_CONTEXT_SEAL")
    _validate_denominator(records)
    _write(path, product)


def seal_answer_reader_product(product: Mapping[str, Any], path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    if (
        product.get("schema") != READER_SCHEMA
        or product.get("labels_loaded") is not False
    ):
        raise ValueError("DG22_S8_READER_PRODUCT_INVALID")
    records = product.get("records", [])
    _validate_denominator(records)
    if not all(isinstance(row.get("answer"), str) for row in records):
        raise ValueError("DG22_S8_READER_ANSWER_MISSING")
    _write(path, product)


def score_answer_reader_product(path: Path) -> dict[str, Any]:
    """Open public-dev answer labels only after the Reader product is sealed."""
    product_sha256 = _sha256(path)
    product = _read(path)
    if (
        product.get("schema") != READER_SCHEMA
        or product.get("labels_loaded") is not False
    ):
        raise ValueError("DG22_S8_SCORE_BOUNDARY_INVALID")
    _validate_denominator(product["records"])
    cases, _selection = load_public_dev_cases()
    case_ids = tuple(str(case.case_id) for case in cases)
    labels, label_identity = load_public_dev_labels(case_ids)
    scored: list[dict[str, Any]] = []
    for row in product["records"]:
        answers = labels[row["case_id"]].get("answers")
        if not isinstance(answers, list) or not answers:
            raise ValueError("DG22_S8_SCORING_LABEL_INVALID")
        answer_score = score_answer(str(row["answer"]), [str(item) for item in answers])
        scored.append(
            {
                "case_id": row["case_id"],
                "arm": row["arm"],
                "token_budget": row["token_budget"],
                "answer": row["answer"],
                "answer_score": answer_score,
                "reader_source": row["reader_source"],
                "context_sha256": row["context_sha256"],
            }
        )
    summaries = {
        arm: {str(budget): _summary(scored, arm, budget) for budget in BUDGETS}
        for arm in ARMS
    }
    regressions: dict[str, list[str]] = {}
    for budget in BUDGETS:
        baseline = {
            row["case_id"]: row
            for row in scored
            if row["arm"] == BASELINE_ARM and row["token_budget"] == budget
        }
        candidate = {
            row["case_id"]: row
            for row in scored
            if row["arm"] == CANDIDATE_ARM and row["token_budget"] == budget
        }
        regressions[str(budget)] = sorted(
            case_id
            for case_id, row in baseline.items()
            if int(row["answer_score"]["exact_match"]) == 1
            and int(candidate[case_id]["answer_score"]["exact_match"]) != 1
        )
    final_2048 = summaries[CANDIDATE_ARM]["2048"]
    final_512 = summaries[CANDIDATE_ARM]["512"]
    checks = {
        "2048_exact_match_at_least_3": final_2048["exact_match_count"] >= 3,
        "2048_normalized_f1_at_least_030": final_2048["normalized_f1"] >= 0.30,
        "512_exact_match_at_least_2": final_512["exact_match_count"] >= 2,
        "512_normalized_f1_at_least_027": final_512["normalized_f1"] >= 0.27,
        "baseline_correct_regression_zero_both_budgets": not any(regressions.values()),
        "wrong_complete_zero": int(product.get("wrong_complete", -1)) == 0,
        "automatic_retry_zero": int(product.get("automatic_retries", -1)) == 0,
        "one_call_per_new_identity": int(
            product.get("duplicate_reader_identity_count", -1)
        )
        == 0,
        "retrieval_frozen": product.get("retrieval_frozen") is True,
        "formal_holdout_untouched": product.get("formal_holdout_consumed") is False,
    }
    if checks["baseline_correct_regression_zero_both_budgets"] is False:
        status = "FAIL_CORRECT_CASE_REGRESSION"
    elif all(checks.values()):
        status = "PASS_MATCHED_ANSWER_CORRECTNESS"
    else:
        status = "PARTIAL_MEDIATOR_PASS_ANSWER_GATE_MISS"
    return {
        "schema": "milai.dg22.s8-answer-score.v0.1",
        "status": status,
        "summaries": summaries,
        "baseline_correct_regressions": regressions,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "scored_records": scored,
        "scoring_identity": label_identity,
        "labels_loaded_after_reader_product_seal_sha256": product_sha256,
        "formal_holdout_consumed": False,
    }


def _summary(
    records: Sequence[Mapping[str, Any]], arm: str, budget: int
) -> dict[str, Any]:
    cells = [
        row for row in records if row["arm"] == arm and row["token_budget"] == budget
    ]
    if len(cells) != 10:
        raise ValueError("DG22_S8_SUMMARY_DENOMINATOR_DRIFT")
    return {
        "case_count": 10,
        "exact_match_count": sum(
            int(row["answer_score"]["exact_match"]) for row in cells
        ),
        "normalized_f1": round(
            mean(float(row["answer_score"]["normalized_f1"]) for row in cells), 9
        ),
    }


def _validate_denominator(records: object) -> None:
    if not isinstance(records, list):
        raise ValueError("DG22_S8_RECORDS_INVALID")
    expected = {
        (case.case_id, arm, budget)
        for case in load_public_dev_cases()[0]
        for arm in ARMS
        for budget in BUDGETS
    }
    observed = {
        (row.get("case_id"), row.get("arm"), row.get("token_budget"))
        for row in records
        if isinstance(row, Mapping)
    }
    if len(records) != 40 or observed != expected:
        raise ValueError("DG22_S8_DENOMINATOR_DRIFT")


def _index(
    records: Sequence[Mapping[str, Any]], arm: str
) -> dict[tuple[str, int], Mapping[str, Any]]:
    result = {
        (str(row["case_id"]), int(row["token_budget"])): row
        for row in records
        if row.get("arm") == arm
    }
    if len(result) != 20:
        raise ValueError(f"DG22_S8_SOURCE_ARM_DRIFT:{arm}")
    return result


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(map(str, value)) | set().union(
            *(_recursive_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value), set())
    return set()


def _identity(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "ARMS",
    "BASELINE_ARM",
    "BUDGETS",
    "CANDIDATE_ARM",
    "build_answer_context_product",
    "score_answer_reader_product",
    "seal_answer_context_product",
    "seal_answer_reader_product",
]
