from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.dg20.deterministic_policy_eval import (
    PRODUCT_SCHEMA,
    DG20S2EvaluationError,
    acquisition_loss_ledger,
    score_s2_product,
    seal_s2_product,
)


def _execution(
    *,
    source_ref: str,
    matched: bool,
    final: bool,
) -> dict[str, object]:
    return {
        "action_digest": "b" * 64 if final else None,
        "candidate_refs": [source_ref],
        "binding_trace": {
            "TARGET_EVENT": (
                [{"source_turn_ref": source_ref, "status": "MATCH"}] if matched else []
            )
        },
        "requirement_state": {
            "state_epoch": 1 if final else 0,
            "requirements": [
                {
                    "requirement_id": "TARGET_EVENT",
                    "status": "SATISFIED" if final else "MISSING",
                }
            ],
        },
        "sufficiency_decision": {"status": "COMPLETE" if final else "UNSATISFIED"},
        "operator_ready": final,
        "governance": {
            "wrong_scope_accepted": 0,
            "permission_unknown_accepted": 0,
            "revoked_evidence_accepted": 0,
            "authority_violation_accepted": 0,
        },
    }


def _product_and_labels() -> tuple[dict[str, object], dict[str, object]]:
    cases = []
    labels = []
    for index in range(10):
        case_id = f"case-{index}"
        noise = f"{case_id}:s0:session-noise:t0"
        answer = f"{case_id}:s1:session-answer:t0"
        cases.append(
            {
                "case_id": case_id,
                "runtime_requirement_order": ["TARGET_EVENT"],
                "baseline": _execution(source_ref=noise, matched=False, final=False),
                "initial_requirement_state": {
                    "state_digest": "a" * 64,
                    "acquisition_capability_digest": "c" * 64,
                    "requirements": [{"requirement_id": "TARGET_EVENT", "status": "MISSING"}],
                },
                "decision": {
                    "selected_action": {
                        "action_digest": "b" * 64,
                        "target_requirement_id": "TARGET_EVENT",
                        "channel": "EVIDENCE_DENSE",
                    }
                },
                "proposal_audit": {
                    "proposal_count": 1,
                    "satisfied_target_count": 0,
                    "unsupported_proposal_count": 0,
                    "unsupported_execution_count": 0,
                    "stale_negative_count": 1,
                    "stale_rejected_count": 1,
                },
                "final": _execution(source_ref=answer, matched=True, final=True),
                "extra_pass_count": 1,
            }
        )
        labels.append(
            {
                "case_id": case_id,
                "atoms": [{"slot": "TARGET_EVENT", "source_turn_ref": answer}],
            }
        )
    return (
        {
            "schema": PRODUCT_SCHEMA,
            "status": "PRODUCT_POLICY_COMPLETE_UNSCORED",
            "run_id": "dg20-s2-unit",
            "formal_holdout_consumed": False,
            "labels_loaded": False,
            "label_fields_available": False,
            "provider_calls": 0,
            "automatic_retries": 0,
            "cases": cases,
        },
        {"cases": labels},
    )


def test_s2_seals_then_scores_policy_and_loss_ledger(tmp_path: Path) -> None:
    product, labels = _product_and_labels()
    sealed = tmp_path / "sealed.json"
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    seal_s2_product(product, sealed)
    score = score_s2_product(sealed, labels_path=labels_path)
    ledger = acquisition_loss_ledger(score)

    assert score["hard_gate"]["passed"] is True
    assert score["metrics"]["missing_requirement_improved_case_count"] == 10
    assert score["enter_s4"] is True
    assert ledger["record_count"] == 10
    assert ledger["all_records_have_exactly_one_first_loss"] is True


def test_s2_product_rejects_scorer_truth_before_seal(tmp_path: Path) -> None:
    product, _labels = _product_and_labels()
    product["atoms"] = []

    with pytest.raises(DG20S2EvaluationError, match="label-free product"):
        seal_s2_product(product, tmp_path / "sealed.json")
