from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.dg20.official_channel_oracle import (
    CHANNELS,
    PRODUCT_SCHEMA,
    DG20S1OracleError,
    score_sealed_oracle,
    seal_product_oracle,
)
from milai.application.evidence_acquisition import OFFICIAL_EXECUTOR_IDENTITY


def _execution(case_id: str, source_ref: str) -> dict[str, object]:
    return {
        "executor_identity": OFFICIAL_EXECUTOR_IDENTITY,
        "acquisition_capability_digest": "a" * 64,
        "candidate_refs": [source_ref],
        "binding_trace": {
            "TARGET_EVENT": [
                {
                    "source_turn_ref": source_ref,
                    "status": "MATCH",
                    "reason_code": "MATCH",
                }
            ]
        },
        "probe_candidate_traces": [
            {
                "requirement_id": "TARGET_EVENT",
                "raw_source_refs": [source_ref],
            }
        ],
        "candidate_requirement_attribution": {"TARGET_EVENT": {"candidate_count": 1}},
        "operator_ready": True,
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
        source_ref = f"{case_id}:s0:session-{index}:t0"
        arms = []
        for channel in CHANNELS:
            executed = channel == "FTS_RAW"
            arms.append(
                {
                    "channel": channel,
                    "capability": {
                        "status": "ENABLED" if executed else "UNAVAILABLE",
                        "reason": "READY" if executed else "NOT_IMPLEMENTED",
                    },
                    "capability_digest": "a" * 64,
                    "execution_status": "EXECUTED" if executed else "CAPABILITY_UNAVAILABLE",
                    "execution": _execution(case_id, source_ref) if executed else None,
                    "combined_execution": (_execution(case_id, source_ref) if executed else None),
                    **(
                        {
                            "action": {
                                "capability_digest": "a" * 64,
                                "target_requirement_id": "TARGET_EVENT",
                            }
                        }
                        if executed
                        else {}
                    ),
                }
            )
        baseline = _execution(case_id, f"{case_id}:s1:session-noise:t0")
        cases.append(
            {
                "case_id": case_id,
                "baseline": baseline,
                "baseline_capability_set": {"capability_digest": "a" * 64},
                "oracle_capability_set": {"capability_digest": "a" * 64},
                "runtime_requirement_order": ["TARGET_EVENT"],
                "requirements": [
                    {
                        "requirement_id": "TARGET_EVENT",
                        "requirement_kind": "EVENT_SLOT",
                        "arms": arms,
                    }
                ],
            }
        )
        labels.append(
            {
                "case_id": case_id,
                "atoms": [{"slot": "TARGET_EVENT", "source_turn_ref": source_ref}],
            }
        )
    product: dict[str, object] = {
        "schema": PRODUCT_SCHEMA,
        "status": "PRODUCT_ORACLE_COMPLETE_UNSCORED",
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "label_fields_available": False,
        "executor_identity": OFFICIAL_EXECUTOR_IDENTITY,
        "eval_owned_ranking_filter_expansion": 0,
        "run_id": "dg20-s1-unit",
        "cases": cases,
    }
    label_envelope: dict[str, object] = {"cases": labels}
    return product, label_envelope


def test_s1_scores_only_after_sealing_and_classifies_every_channel(tmp_path: Path) -> None:
    product, labels = _product_and_labels()
    sealed = tmp_path / "sealed.json"
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    seal_product_oracle(product, sealed)
    score = score_sealed_oracle(sealed, labels_path=labels_path)

    assert score["hard_gate"]["passed"] is True
    assert score["minimum_mechanism_signal"]["observed_case_count"] == 10
    assert score["enter_s2"] is True
    for case in score["cases"]:
        arms = case["requirements"][0]["arms"]
        assert len(arms) == len(CHANNELS)
        assert all(arm["first_loss_stage"] for arm in arms)


def test_s1_product_phase_rejects_scorer_truth(tmp_path: Path) -> None:
    product, _labels = _product_and_labels()
    product["atoms"] = []

    with pytest.raises(DG20S1OracleError, match="label-free product"):
        seal_product_oracle(product, tmp_path / "sealed.json")
