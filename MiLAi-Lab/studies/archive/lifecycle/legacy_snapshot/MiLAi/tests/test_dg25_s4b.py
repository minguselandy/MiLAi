from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from evals.dg25.arm_sealing import (
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    validate_combined_all_arm_seal,
)
from evals.dg25.effect_scorer import canonical_sha256
from evals.dg25.s4b_readiness import (
    CURRENT_SCORER_SHA256,
    FIXED_INPUT_PATHS,
    build_s4b_source_manifest,
    build_scorer_source_amendment,
    file_identity,
    observe_registry_without_opening,
    read_json,
    validate_label_free_bundle,
)
from evals.dg25.s4b_scoring import (
    AUTHORIZATION_FIELDS,
    S4B_OFFICIAL_RUN_ID,
    build_scored_reports,
    validate_scoring_review,
)
from scripts.run_dg25_s4b import _score_gate_observations, run_once

ROOT = Path(__file__).resolve().parents[1]


def test_scorer_source_amendment_reconstructs_exact_frozen_source() -> None:
    combined = read_json(ROOT / FIXED_INPUT_PATHS["combined_seal"])
    scorer_envelope = read_json(ROOT / FIXED_INPUT_PATHS["effect_scorer_contract"])
    s4a_execution = read_json(ROOT / FIXED_INPUT_PATHS["s4a_execution_manifest"])
    s4a_review = read_json(ROOT / FIXED_INPUT_PATHS["s4a_independent_review"])
    identities = {
        "combined_seal": file_identity(ROOT, ROOT / FIXED_INPUT_PATHS["combined_seal"]),
        "s4a_independent_review": file_identity(
            ROOT, ROOT / FIXED_INPUT_PATHS["s4a_independent_review"]
        ),
    }
    amendment = build_scorer_source_amendment(
        root=ROOT,
        combined_seal=combined,
        scorer_envelope=scorer_envelope,
        s4a_execution=s4a_execution,
        s4a_review=s4a_review,
        identities=identities,
    )
    assert amendment["base_scorer_source"]["sha256"] == (
        "ee8929e4feb95246a258d49555b7dd8b8ac83872576e7af2f678218d1303a929"
    )
    assert amendment["effective_scorer_source"]["sha256"] == CURRENT_SCORER_SHA256
    assert amendment["allowed_delta"]["other_top_level_ast_delta_count"] == 0
    material = dict(amendment)
    assert material.pop("amendment_digest") == canonical_sha256(material)


def test_official_label_free_bundles_and_combined_seal_recompute() -> None:
    e1_bundle = read_json(ROOT / FIXED_INPUT_PATHS["e1_bundle"])
    e1_seal = read_json(ROOT / FIXED_INPUT_PATHS["e1_seal"])
    e2_bundle = read_json(ROOT / FIXED_INPUT_PATHS["e2_bundle"])
    e2_seal = read_json(ROOT / FIXED_INPUT_PATHS["e2_seal"])
    combined = read_json(ROOT / FIXED_INPUT_PATHS["combined_seal"])
    e1 = validate_label_free_bundle(
        bundle=e1_bundle,
        seal=e1_seal,
        block="E1",
        arm_order=E1_ARM_ORDER,
    )
    e2 = validate_label_free_bundle(
        bundle=e2_bundle,
        seal=e2_seal,
        block="E2",
        arm_order=E2_ARM_ORDER,
    )
    validate_combined_all_arm_seal(
        seal=combined,
        e1_seal=e1_seal,
        e2_seal=e2_seal,
        arm_outputs={**e1, **e2},
        readiness_bindings=combined["readiness_bindings"],
    )


def test_registry_pre_authorization_check_uses_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = read_json(ROOT / FIXED_INPUT_PATHS["effect_scorer_contract"])
    reference = envelope["registry_identity_references"]["gold_equivalence_registry"]
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if "scorer-only" in path.as_posix():
            raise AssertionError("registry content opened before authorization")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    observation = observe_registry_without_opening(ROOT, reference)
    assert observation["content_opened"] is False
    assert observation["sha256_computed"] is False
    assert observation["size_matches_expected"] is True


def test_s4b_source_manifest_has_no_forbidden_product_imports() -> None:
    manifest = build_s4b_source_manifest(ROOT)
    assert manifest["source_scan"]["passed"] is True
    assert manifest["source_scan"]["findings"] == []
    assert {item["path"] for item in manifest["files"]} >= {
        "evals/dg25/effect_scorer.py",
        "evals/dg25/s4b_readiness.py",
        "evals/dg25/s4b_scoring.py",
        "scripts/run_dg25_s4b.py",
        "tests/test_dg25_s4b.py",
    }


def test_scoring_review_requires_exact_fresh_request_and_scope() -> None:
    bindings = _authorization_bindings()
    receipt_identity = {
        "path": "var/dg25/s4b-readiness/readiness/receipt.json",
        "sha256": "a" * 64,
        "size": 100,
    }
    review = _review(
        request_digest="b" * 64,
        bindings=bindings,
        receipt_identity=receipt_identity,
    )
    authorization = validate_scoring_review(
        review,
        expected_request_digest="b" * 64,
        expected_authorization_bindings=bindings,
        reviewed_readiness_receipt=receipt_identity,
    )
    assert authorization["authorized"] is True
    assert set(dict(authorization)) == AUTHORIZATION_FIELDS | {"authorization_digest"}

    tampered = deepcopy(review)
    tampered["authorization"]["official_s4b_run_id"] = "replay-run"
    auth_material = dict(tampered["authorization"])
    auth_material.pop("authorization_digest")
    tampered["authorization"]["authorization_digest"] = canonical_sha256(auth_material)
    review_material = dict(tampered)
    review_material.pop("review_digest")
    tampered["review_digest"] = canonical_sha256(review_material)
    with pytest.raises(ValueError, match="SCOPE_OR_BINDING"):
        validate_scoring_review(
            tampered,
            expected_request_digest="b" * 64,
            expected_authorization_bindings=bindings,
            reviewed_readiness_receipt=receipt_identity,
        )


def test_scored_report_projection_is_preregistered_and_fail_closed() -> None:
    score = _joint_score()
    reports = build_scored_reports(score)
    policy = reports["final_minimal_policy"]
    assert policy["post_score_adaptation"] is False
    assert "UNIQUE_ANCHOR_RELATIVE_RESOLUTION" in policy["removed_components"]
    assert "EVENT_IDENTITY_DEDUP_V01" in policy["retained_components"]
    assert "BOUNDED_RANGE_SCAN_PROOF_V02" in policy["retained_components"]
    assert reports["temporal_ablation_report"]["t2_preregistered_applicability"] == (
        "NOT_APPLICABLE_FOR_BOTH_FROZEN_INPUTS"
    )
    assert reports["routing_selection_report"]["inference"] == (
        "PAIRED_OPENED_DEVELOPMENT_DESCRIPTIVE_ONLY"
    )


def test_score_gate_observations_keep_labels_closed_until_pre_gate() -> None:
    bindings = {"field": "value"}
    pre = _score_gate_observations(bindings, phase="PRE_SCORE", all_arm_count=16)
    post = _score_gate_observations(bindings, phase="POST_SCORE", all_arm_count=16)
    assert pre["labels_loaded"] is False
    assert pre["scoring_executed"] is False
    assert post["labels_loaded"] is True
    assert post["score_execution_count"] == 1


def test_wrong_official_run_id_rejected_before_any_registry_open(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="OFFICIAL_RUN_ID_MISMATCH"):
        run_once(
            run_id="cross-run-replay",
            readiness_run_id="unused",
            authorization_review=Path("unused.json"),
            root=tmp_path,
        )


def _authorization_bindings() -> dict[str, Any]:
    return {
        "combined_all_arm_seal_digest": "c" * 64,
        "readiness_bindings_digest": "d" * 64,
        "scorer_source_amendment_digest": "e" * 64,
        "effect_scorer_contract_digest": "f" * 64,
        "effect_scorer_source_sha256": "1" * 64,
        "gold_registry_sha256": "2" * 64,
        "proof_registry_sha256": "3" * 64,
        "failure_index_sha256": "4" * 64,
        "failure_index_line_count": 113,
        "extra_frozen_binding": "5" * 64,
    }


def _review(
    *,
    request_digest: str,
    bindings: dict[str, Any],
    receipt_identity: dict[str, Any],
) -> dict[str, Any]:
    authorization_material: dict[str, Any] = {
        "schema": "milai.dg25.independent-scoring-authorization.v0.1",
        "authorized": True,
        "scope": "S4B_JOINT_E1_E2_POST_SEAL_SCORE",
        "official_s4b_run_id": S4B_OFFICIAL_RUN_ID,
        "combined_all_arm_seal_digest": bindings["combined_all_arm_seal_digest"],
        "readiness_bindings_digest": bindings["readiness_bindings_digest"],
        "readiness_request_digest": request_digest,
        "readiness_receipt_sha256": receipt_identity["sha256"],
        "scorer_source_amendment_digest": bindings[
            "scorer_source_amendment_digest"
        ],
        "effect_scorer_contract_digest": bindings[
            "effect_scorer_contract_digest"
        ],
        "effect_scorer_source_sha256": bindings["effect_scorer_source_sha256"],
        "gold_registry_sha256": bindings["gold_registry_sha256"],
        "proof_registry_sha256": bindings["proof_registry_sha256"],
        "failure_index_sha256": bindings["failure_index_sha256"],
        "failure_index_line_count": bindings["failure_index_line_count"],
        "readiness_bindings": bindings,
        "authorized_attempts": 1,
        "automatic_retries": 0,
        "labels_authorized_after_pre_score_gate": True,
        "registry_content_authorized_after_pre_score_gate": True,
        "scoring_authorized": True,
        "e3_authorized": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_authorized": False,
        "candidate_default_authorized": False,
    }
    authorization = {
        **authorization_material,
        "authorization_digest": canonical_sha256(authorization_material),
    }
    review_material: dict[str, Any] = {
        "schema": "milai.dg25.s4b-independent-review.v0.1",
        "reviewer_role": "INDEPENDENT_SECONDARY_CODEX_REVIEWER",
        "verdict": "AUTHORIZE_S4B_JOINT_E1_E2_POST_SEAL_SCORE",
        "reviewed_readiness_receipt": receipt_identity,
        "authorization_request_digest": request_digest,
        "findings": [],
        "authorization": authorization,
    }
    return {**review_material, "review_digest": canonical_sha256(review_material)}


def _joint_score() -> dict[str, Any]:
    arm_scores: dict[str, dict[str, Any]] = {}
    for arm in (*E1_ARM_ORDER, *E2_ARM_ORDER):
        arm_scores[arm] = {
            "arm_id": arm,
            "covered_groups": 23,
            "proof_obligations_satisfied": 37,
            "accepted_binding_precision": 1.0,
            "wrong_complete": 0,
            "first_loss_distribution": {"TERMINAL_SURVIVAL": 23},
            "cost_ledger": {
                "logical_selected_actions": 1,
                "replayed_repository_calls": 1,
                "candidates_hydrated": 8,
            },
        }
    sequential_pairs = [
        ("R0P", "R1"),
        ("R1", "R2"),
        ("R2", "R3"),
        ("R3", "R4"),
        ("R4", "R5_NO_SYNONYM_NORMALIZATION"),
        ("T0", "T1"),
        ("T1", "T2"),
        ("T2", "T3"),
        ("T3", "T4"),
    ]
    sequential = [_delta(before, after) for before, after in sequential_pairs]
    unique = [
        _delta(arm, "R5_NO_SYNONYM_NORMALIZATION")
        for arm in (
            "R_FINAL_DROP_UNIFIED_PROOF_FIRST",
            "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
            "R_FINAL_DROP_ROLE_RESERVATION",
            "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
        )
    ]
    material: dict[str, Any] = {
        "schema": "milai.dg25.e1-e2-effect-score.v0.1",
        "scorer_identity": "synthetic",
        "scorer_contract_digest": "a" * 64,
        "combined_all_arm_seal_digest": "b" * 64,
        "independent_authorization_digest": "c" * 64,
        "denominators": {"queries": 10, "groups": 23, "proofs": 37},
        "arm_scores": arm_scores,
        "order_conditional_contributions": sequential,
        "full_minus_one_contributions": unique,
        "final_minimal_policy": {
            "base_arm": "R5_NO_SYNONYM_NORMALIZATION",
            "retained_components": [],
            "removed_components": [
                "OPTIONAL_CHANNEL_UNION",
                "ROLE_RESERVATION",
                "SOFT_LEXICAL_FEATURES",
                "SYNONYM_NORMALIZATION",
                "UNIFIED_PROOF_FIRST",
            ],
            "synonym_generality_parked": False,
            "selection_uses_only_preregistered_pairs": True,
            "post_score_adaptation": False,
        },
        "post_score_adaptation": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
    }
    return {**material, "score_digest": canonical_sha256(material)}


def _delta(predecessor: str, arm: str) -> dict[str, Any]:
    return {
        "predecessor": predecessor,
        "arm_id": arm,
        "covered_group_delta": 0,
        "proof_satisfied_delta": 0,
        "logical_action_delta": 0,
        "replayed_call_delta": 0,
        "hydrated_delta": 0,
        "precision_preserved": True,
        "wrong_complete_zero": True,
    }
