from __future__ import annotations

from pathlib import Path

import pytest
from evals.dg20.product_faithful_eval import (
    PRODUCT_SCHEMA,
    DG20S4EvaluationError,
    score_s4_product,
    seal_s4_product,
)
from milai.application.evidence_acquisition import OFFICIAL_EXECUTOR_IDENTITY


def _execution() -> dict[str, object]:
    state = {
        "state_epoch": 0,
        "requirements": [{"requirement_id": "LOOKUP", "status": "SATISFIED"}],
    }
    return {
        "executor_identity": OFFICIAL_EXECUTOR_IDENTITY,
        "mode": "PRODUCT",
        "action_digest": None,
        "candidate_refs": ["case:s1:t1"],
        "binding_trace": {"LOOKUP": []},
        "requirement_state": state,
        "sufficiency_decision": {"status": "COMPLETE"},
    }


def _product() -> dict[str, object]:
    decision = {
        "decision_digest": "d" * 64,
        "reason_code": "DETERMINISTIC_COMPLETE",
        "selected_action": None,
    }
    initial = {
        "state_epoch": 0,
        "requirements": [{"requirement_id": "LOOKUP", "status": "SATISFIED"}],
    }
    recovery = {
        "initial_requirement_state": initial,
        "decision": decision,
        "final": _execution(),
        "extra_pass_count": 0,
        "provider_calls": 0,
        "automatic_retries": 0,
        "canonical_mutation": False,
    }
    return {
        "schema": PRODUCT_SCHEMA,
        "status": "PRODUCT_FAITHFUL_COMPLETE_UNSCORED",
        "run_id": "s4-test",
        "labels_loaded": False,
        "formal_holdout_consumed": False,
        "executor_identity": OFFICIAL_EXECUTOR_IDENTITY,
        "residual_assist": "DETERMINISTIC_ONLY",
        "case_count": 1,
        "cases": [
            {
                "case_id": "case",
                "baseline": _execution(),
                "shadow": recovery,
                "product": recovery,
                "runtime_candidate": {
                    "recovery": {
                        "decision": decision,
                        "extra_pass_count": 0,
                        "provider_calls": 0,
                        "automatic_retries": 0,
                        "canonical_mutation": False,
                    },
                    "evidence_source_refs": ["case:s1:t1"],
                },
                "ineligible_product_output_changed": False,
            }
        ],
    }


def test_s4_scorer_requires_full_product_shadow_identity(tmp_path: Path) -> None:
    sealed = tmp_path / "sealed.json"
    seal_s4_product(_product(), sealed)

    score = score_s4_product(sealed)

    assert score["disposition"] == "PASS_S4_ONE_PASS_PRODUCT_FAITHFUL_INTEGRATION"
    assert score["enter_s5"] is True
    assert all(gate["passed"] for gate in score["hard_gate"].values())


def test_s4_sealer_rejects_label_access(tmp_path: Path) -> None:
    product = _product()
    product["labels_loaded"] = True

    with pytest.raises(DG20S4EvaluationError, match="label-free"):
        seal_s4_product(product, tmp_path / "sealed.json")
