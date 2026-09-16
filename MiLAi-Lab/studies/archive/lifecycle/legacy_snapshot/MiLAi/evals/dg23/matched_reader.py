"""DG-23 S7 sealed-context matched Reader execution and post-seal scoring."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

from evals.dg16.lme10 import load_public_dev_cases, load_public_dev_labels
from evals.dg23.reader_boundary import (
    FROZEN_READER_CONTRACT_SHA256,
    dg23_matched_seed,
)
from evals.paper.scorers.longmemeval import score_answer

BASELINE_ARM = "A_DG22_FROZEN_FINAL_CONTEXT"
CANDIDATE_ARM = "B_DG23_BUDGET_INVARIANT_CONTEXT"
ARMS = (BASELINE_ARM, CANDIDATE_ARM)
MODES = ("LEGACY_512", "LEGACY_2048", "REFERENCE_B_REF", "ADAPTIVE_RUNTIME")
REPLICATES = (0, 1, 2)
CONTEXT_SCHEMA = "milai.dg23.s7-matched-reader-context-product.v0.1"
READER_SCHEMA = "milai.dg23.s7-matched-reader-product.v0.1"
S6_RECEIPT = Path(
    "var/dg23/s6/dg23-s6-opened-dev-context-20260829-020/receipt.json"
)
S6_PRODUCT = Path(
    "var/dg23/s6/dg23-s6-opened-dev-context-20260829-019/"
    "sealed-opened-dev-context-product.json"
)
DG22_PRODUCT = Path(
    "var/dg22/s7/dg22-s7-mediator-20260829-001/sealed-mediator-product.json"
)
DG22_ARM = "E_SAFE_TEMPORAL_APPLICABILITY_COUNT"
DG22_ANSWER_SCORE = Path(
    "var/dg22/s8/dg22-s8-answer-correctness-20260829-001/answer-score.json"
)
DG22_ANSWER_ARM = "B_DG22_FROZEN_FINAL_CONTEXT"


def build_matched_reader_context_product(root: Path, *, run_id: str) -> dict[str, Any]:
    """Freeze all logical Reader cells without loading answers or labels."""

    s6_receipt = _read(root / S6_RECEIPT)
    s6 = _read(root / S6_PRODUCT)
    dg22 = _read(root / DG22_PRODUCT)
    if (
        s6_receipt.get("status") != "PASS_DG23_OPENED_DEV_CONTEXT_LADDER"
        or s6_receipt.get("hard_gate", {}).get("passed") is not True
        or s6_receipt.get("structural_gate", {}).get("passed") is not True
    ):
        raise ValueError("DG23_S7_S6_ENTRY_GATE_FAILED")
    if s6_receipt["sealed_context_product"]["sha256"] != _sha256(root / S6_PRODUCT):
        raise ValueError("DG23_S7_S6_PRODUCT_IDENTITY_DRIFT")
    cases, selection = load_public_dev_cases()
    case_by_id = {str(case.case_id): case for case in cases}
    summaries = {str(row["case_id"]): row for row in s6["case_summaries"]}
    candidate = {
        (str(row["case_id"]), str(row["mode"])): row
        for row in s6["reader_mode_records"]
    }
    baseline = {
        (str(row["case_id"]), int(row["token_budget"])): row
        for row in dg22["records"]
        if row.get("arm") == DG22_ARM
    }
    records: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.case_id)
        source_snapshot_digest = str(summaries[case_id]["source_snapshot_digest"])
        for replicate_index in REPLICATES:
            for arm in ARMS:
                for mode in MODES:
                    if arm == CANDIDATE_ARM:
                        source = candidate[(case_id, mode)]
                        presentation_budget = int(source["budget"])
                        context = str(source["context"])
                        context_digest = str(source["reader_context_digest"])
                        estimated_tokens = int(source["estimated_tokens"])
                        readiness = str(source["readiness"])
                        source_mode = mode
                    else:
                        source_budget = 512 if mode == "LEGACY_512" else 2048
                        source = baseline[(case_id, source_budget)]
                        if str(source["source_snapshot_digest"]) != source_snapshot_digest:
                            raise ValueError("DG23_S7_SOURCE_SNAPSHOT_DRIFT")
                        presentation_budget = source_budget
                        context = str(source["context"])
                        context_digest = str(source["context_sha256"])
                        estimated_tokens = int(source["context_tokens"])
                        readiness = "READY"
                        source_mode = f"DG22_FROZEN_{source_budget}"
                    if hashlib.sha256(context.encode()).hexdigest() != context_digest:
                        raise ValueError("DG23_S7_CONTEXT_DIGEST_DRIFT")
                    records.append(
                        {
                            "case_id": case_id,
                            "category": str(case.category),
                            "arm": arm,
                            "method_id": arm,
                            "mode": mode,
                            "source_mode": source_mode,
                            "replicate_index": replicate_index,
                            "presentation_budget": presentation_budget,
                            "question": str(case.question),
                            "question_as_of": str(case.question_at),
                            "context": context,
                            "reader_context_digest": context_digest,
                            "estimated_tokens": estimated_tokens,
                            "readiness": readiness,
                            "source_snapshot_digest": source_snapshot_digest,
                            "sampling_seed": dg23_matched_seed(
                                source_snapshot_digest, replicate_index
                            ),
                            "reader_source": "PENDING_AFTER_CONTEXT_SEAL",
                        }
                    )
    _validate_context_records(records, case_by_id)
    return {
        "schema": CONTEXT_SCHEMA,
        "status": "SEALED_CONTEXTS_PENDING_READER",
        "run_id": run_id,
        "arms": list(ARMS),
        "modes": list(MODES),
        "replicates": list(REPLICATES),
        "case_order": [str(case.case_id) for case in cases],
        "records": records,
        "reader_contract_digest": FROZEN_READER_CONTRACT_SHA256,
        "baseline_mode_mapping": {
            "LEGACY_512": "DG22_FROZEN_512",
            "LEGACY_2048": "DG22_FROZEN_2048",
            "REFERENCE_B_REF": "DG22_FROZEN_2048",
            "ADAPTIVE_RUNTIME": "DG22_FROZEN_2048",
        },
        "entry_s6_receipt": _identity(root / S6_RECEIPT, root),
        "entry_s6_product": _identity(root / S6_PRODUCT, root),
        "dg22_frozen_context_product": _identity(root / DG22_PRODUCT, root),
        "selection_identity": selection["identities"],
        "labels_loaded": False,
        "answers_present": False,
        "retrieval_frozen": True,
        "candidate_default": False,
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
    }


def seal_matched_reader_context_product(product: Mapping[str, Any], path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    records = product.get("records")
    cases = {str(case.case_id): case for case in load_public_dev_cases()[0]}
    if (
        product.get("schema") != CONTEXT_SCHEMA
        or product.get("labels_loaded") is not False
        or product.get("answers_present") is not False
        or not isinstance(records, list)
        or any(isinstance(row, Mapping) and "answer" in row for row in records)
    ):
        raise ValueError("DG23_S7_CONTEXT_PRODUCT_INVALID")
    _validate_context_records(records, cases)
    _write(path, product)


def seal_matched_reader_product(product: Mapping[str, Any], path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    records = product.get("records")
    cases = {str(case.case_id): case for case in load_public_dev_cases()[0]}
    if (
        product.get("schema") != READER_SCHEMA
        or product.get("labels_loaded") is not False
        or not isinstance(records, list)
    ):
        raise ValueError("DG23_S7_READER_PRODUCT_INVALID")
    _validate_context_records(records, cases)
    if not all(isinstance(row.get("answer"), str) for row in records):
        raise ValueError("DG23_S7_READER_ANSWER_MISSING")
    _write(path, product)


def score_matched_reader_product(root: Path, path: Path) -> dict[str, Any]:
    """Load public-development labels only after every Reader cell is sealed."""

    sealed_sha256 = _sha256(path)
    product = _read(path)
    cases, _selection = load_public_dev_cases()
    case_ids = tuple(str(case.case_id) for case in cases)
    case_by_id = {str(case.case_id): case for case in cases}
    if product.get("schema") != READER_SCHEMA or product.get("labels_loaded") is not False:
        raise ValueError("DG23_S7_SCORE_BOUNDARY_INVALID")
    _validate_context_records(product["records"], case_by_id)
    labels, label_identity = load_public_dev_labels(case_ids)
    scored: list[dict[str, Any]] = []
    for row in product["records"]:
        answers = labels[str(row["case_id"])].get("answers")
        if not isinstance(answers, list) or not answers:
            raise ValueError("DG23_S7_SCORING_LABEL_INVALID")
        answer_score = score_answer(str(row["answer"]), [str(value) for value in answers])
        scored.append(
            {
                "case_id": row["case_id"],
                "arm": row["arm"],
                "mode": row["mode"],
                "replicate_index": row["replicate_index"],
                "answer": row["answer"],
                "answer_score": answer_score,
                "readiness": row["readiness"],
                "reader_source": row["reader_source"],
                "reader_context_digest": row["reader_context_digest"],
            }
        )
    summaries = {
        arm: {
            mode: {
                str(replicate): _summary(scored, arm, mode, replicate)
                for replicate in REPLICATES
            }
            for mode in MODES
        }
        for arm in ARMS
    }
    primary_regressions = _correct_case_regressions(
        scored, modes=("REFERENCE_B_REF", "ADAPTIVE_RUNTIME")
    )
    all_regressions = _correct_case_regressions(scored, modes=MODES)
    historical = _read(root / DG22_ANSWER_SCORE)
    historical_512_correct = {
        str(row["case_id"])
        for row in historical["scored_records"]
        if row.get("arm") == DG22_ANSWER_ARM
        and row.get("token_budget") == 512
        and row.get("answer_score", {}).get("exact_match") == 1
    }
    scored_index = {
        (
            str(row["case_id"]),
            str(row["arm"]),
            str(row["mode"]),
            int(row["replicate_index"]),
        ): row
        for row in scored
    }
    legacy_512_losses = sorted(
        (case_id, replicate)
        for case_id in historical_512_correct
        for replicate in REPLICATES
        if scored_index[(case_id, CANDIDATE_ARM, "LEGACY_512", replicate)][
            "answer_score"
        ]["exact_match"]
        != 1
    )
    historical_regression_losses = sorted(
        replicate
        for replicate in REPLICATES
        if scored_index[
            ("gpt4_88806d6e", CANDIDATE_ARM, "LEGACY_2048", replicate)
        ]["answer_score"]["exact_match"]
        != 1
    )
    saturated_mismatches = _saturated_answer_mismatches(product["records"])
    reference = summaries[CANDIDATE_ARM]["REFERENCE_B_REF"]
    adaptive = summaries[CANDIDATE_ARM]["ADAPTIVE_RUNTIME"]
    checks = {
        "reader_contract_drift_zero": product.get("reader_contract_digest")
        == FROZEN_READER_CONTRACT_SHA256,
        "reader_seed_excludes_budget_and_arm": _seed_invariance(product["records"]),
        "invalid_json_zero": int(product.get("invalid_json_count", -1)) == 0,
        "automatic_retry_zero": int(product.get("automatic_retries", -1)) == 0,
        "exact_identity_duplicate_call_zero": int(
            product.get("duplicate_reader_identity_call_count", -1)
        )
        == 0,
        "infeasible_reader_call_zero": int(product.get("infeasible_reader_calls", -1))
        == 0,
        "correct_case_regression_zero_primary": not primary_regressions,
        "historical_regression_2048_correct_all_replicates": not historical_regression_losses,
        "legacy_512_historical_correct_set_retained": not legacy_512_losses,
        "candidate_b_ref_em_at_least_6_all_replicates": all(
            reference[str(rep)]["exact_match_count"] >= 6 for rep in REPLICATES
        ),
        "candidate_b_ref_f1_at_least_floor_all_replicates": all(
            reference[str(rep)]["normalized_f1"] >= 0.633715799 for rep in REPLICATES
        ),
        "adaptive_em_noninferior_all_replicates": all(
            adaptive[str(rep)]["exact_match_count"]
            >= reference[str(rep)]["exact_match_count"]
            for rep in REPLICATES
        ),
        "adaptive_f1_noninferior_all_replicates": all(
            adaptive[str(rep)]["normalized_f1"]
            >= reference[str(rep)]["normalized_f1"] - 0.01
            for rep in REPLICATES
        ),
        "saturated_context_answer_mismatch_zero": not saturated_mismatches,
        "wrong_complete_zero": int(product.get("wrong_complete", -1)) == 0,
        "retrieval_frozen": product.get("retrieval_frozen") is True,
        "formal_holdout_untouched": product.get("formal_holdout_consumed") is False,
    }
    return {
        "schema": "milai.dg23.s7-matched-reader-score.v0.1",
        "status": "PASS_DG23_MATCHED_READER_ANSWER_CLOSURE"
        if all(checks.values())
        else "FAIL_DG23_MATCHED_READER_ANSWER_CLOSURE",
        "summaries": summaries,
        "primary_correct_case_regressions": primary_regressions,
        "all_correct_case_regressions": all_regressions,
        "legacy_512_historical_losses": [
            {"case_id": case_id, "replicate_index": replicate}
            for case_id, replicate in legacy_512_losses
        ],
        "historical_regression_2048_losses": historical_regression_losses,
        "saturated_context_answer_mismatches": saturated_mismatches,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "scored_records": scored,
        "scoring_identity": label_identity,
        "labels_loaded_after_reader_product_seal_sha256": sealed_sha256,
        "formal_holdout_consumed": False,
    }


def _validate_context_records(
    records: object, cases: Mapping[str, Any]
) -> None:
    if not isinstance(records, list):
        raise TypeError("DG23_S7_RECORDS_INVALID")
    expected = {
        (case_id, arm, mode, replicate)
        for case_id in cases
        for arm in ARMS
        for mode in MODES
        for replicate in REPLICATES
    }
    observed = {
        (
            str(row.get("case_id")),
            str(row.get("arm")),
            str(row.get("mode")),
            int(row.get("replicate_index", -1)),
        )
        for row in records
        if isinstance(row, Mapping)
    }
    if len(records) != 240 or observed != expected:
        raise ValueError("DG23_S7_DENOMINATOR_DRIFT")
    for row in records:
        if not isinstance(row, Mapping):
            raise TypeError("DG23_S7_RECORD_INVALID")
        context = row.get("context")
        if not isinstance(context, str) or hashlib.sha256(context.encode()).hexdigest() != row.get(
            "reader_context_digest"
        ):
            raise ValueError("DG23_S7_CONTEXT_IDENTITY_DRIFT")


def _summary(
    records: Sequence[Mapping[str, Any]], arm: str, mode: str, replicate: int
) -> dict[str, Any]:
    cells = [
        row
        for row in records
        if row["arm"] == arm
        and row["mode"] == mode
        and row["replicate_index"] == replicate
    ]
    if len(cells) != 10:
        raise ValueError("DG23_S7_SUMMARY_DENOMINATOR_DRIFT")
    return {
        "case_count": 10,
        "exact_match_count": sum(int(row["answer_score"]["exact_match"]) for row in cells),
        "normalized_f1": round(
            mean(float(row["answer_score"]["normalized_f1"]) for row in cells), 9
        ),
    }


def _correct_case_regressions(
    records: Sequence[Mapping[str, Any]], *, modes: Sequence[str]
) -> list[dict[str, Any]]:
    index = {
        (str(row["case_id"]), str(row["arm"]), str(row["mode"]), int(row["replicate_index"])): row
        for row in records
    }
    return [
        {"case_id": case_id, "mode": mode, "replicate_index": replicate}
        for case_id in {str(row["case_id"]) for row in records}
        for mode in modes
        for replicate in REPLICATES
        if index[(case_id, BASELINE_ARM, mode, replicate)]["answer_score"]["exact_match"]
        == 1
        and index[(case_id, CANDIDATE_ARM, mode, replicate)]["answer_score"][
            "exact_match"
        ]
        != 1
    ]


def _saturated_answer_mismatches(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, str], set[str]] = {}
    for row in records:
        if row.get("arm") != CANDIDATE_ARM or row.get("readiness") != "READY":
            continue
        key = (
            str(row["case_id"]),
            int(row["replicate_index"]),
            str(row["reader_context_digest"]),
        )
        groups.setdefault(key, set()).add(str(row.get("answer", "")))
    return [
        {
            "case_id": key[0],
            "replicate_index": key[1],
            "reader_context_digest": key[2],
        }
        for key, answers in groups.items()
        if len(answers) > 1
    ]


def _seed_invariance(records: Sequence[Mapping[str, Any]]) -> bool:
    groups: dict[tuple[str, int], set[int]] = {}
    for row in records:
        key = (str(row["case_id"]), int(row["replicate_index"]))
        groups.setdefault(key, set()).add(int(row["sampling_seed"]))
    return all(len(values) == 1 for values in groups.values())


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
    "CANDIDATE_ARM",
    "CONTEXT_SCHEMA",
    "MODES",
    "READER_SCHEMA",
    "REPLICATES",
    "build_matched_reader_context_product",
    "score_matched_reader_product",
    "seal_matched_reader_context_product",
    "seal_matched_reader_product",
]
