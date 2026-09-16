from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from evals.dg25.artifacts import canonical_sha256
from evals.dg25.review_gate import (
    DG25ReviewGateError,
    build_exact_query_freeze,
    build_executor_feasibility,
    build_pre_treatment_arm_manifest,
    build_stop_rule_registry,
    load_and_validate_independent_review,
    validate_independent_review_payload,
)

ROOT = Path(__file__).resolve().parents[1]


def test_independent_review_authorizes_only_zero_call_s2() -> None:
    review = load_and_validate_independent_review(ROOT)

    assert review["verdict"] == "APPROVE_WITH_REQUIRED_EDITS"
    assert review["s2_authorized"] is True
    assert review["reader_stage_authorized"] is False
    assert review["model/provider/controller_calls_authorized"] == 0
    assert review["holdout_authorized"] is False


def test_review_rejects_a_new_provider_call_authorization() -> None:
    review = deepcopy(load_and_validate_independent_review(ROOT))
    review["provider_calls_authorized"] = 1

    with pytest.raises(DG25ReviewGateError, match="provider_calls_authorized"):
        validate_independent_review_payload(review)


def test_arm_manifest_freezes_exact_queries_k_caps_and_order() -> None:
    review = load_and_validate_independent_review(ROOT)
    manifest = build_pre_treatment_arm_manifest(ROOT, review)
    material = {key: value for key, value in manifest.items() if key != "manifest_digest"}

    assert manifest["manifest_digest"] == canonical_sha256(material)
    assert len(manifest["exact_channel_query_identities"]) == 75
    assert manifest["selection_and_budget"]["final_k"] == 8
    assert manifest["selection_and_budget"]["verified_dense_ceiling"] == 30
    assert manifest["selection_and_budget"]["max_actions_per_plan"] == 2
    assert manifest["arm_order"]["S2"] == ["R0", "R0P"]
    assert manifest["arm_order"]["E3"][0] == "C0_FRESH_CANDIDATE_OFF"
    assert manifest["authorization"]["E1_E2_effect_scoring"] is False
    assert manifest["authorization"]["E4_reader_calls"] is False
    assert manifest["label_boundary"]["formal_holdout_consumed"] is False


def test_query_and_stop_rule_denominators_are_exact() -> None:
    review = load_and_validate_independent_review(ROOT)
    queries = build_exact_query_freeze(ROOT)
    rules = build_stop_rule_registry(review)
    feasibility = build_executor_feasibility(review)

    assert len(queries) == 75
    assert len({(item["case_id"], item["requirement_id"], item["channel"]) for item in queries}) == 75
    assert len(rules["machine_rules"]) == 10
    assert rules["automatic_retries"] == 0
    assert feasibility["status"] == "FEASIBLE_S2_ONLY"
    assert feasibility["compute"]["S2_gpu_hours"] == 0
    assert feasibility["cuts"] == []
