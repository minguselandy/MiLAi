from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from milai.domain.requirement_state import canonical_sha256
from pydantic import ValidationError

from evals.dg25.arm_sealing import (
    COST_LEDGER_FIELDS,
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    ArmBlock,
    build_block_all_arm_seal,
    build_combined_all_arm_seal,
    build_label_free_arm_output,
    cost_ledger_schema,
)
from evals.dg25.effect_scorer import (
    score_all_arms,
    scorer_contract,
)
from evals.dg25.routing_ablation import (
    E1ArmConfigV01,
    E1RequirementActionPlanV01,
    ReplayActionV01,
    ReplayOccurrenceV01,
    build_e1_requirement_action_plan,
    build_replay_action,
    select_label_free_occurrences,
    validate_e1_requirement_action_plan,
)
from evals.dg25.s3_readiness import (
    _s3a_call_target_contract,
    _s3a_execution_surface_findings,
    build_readiness_artifacts,
)
from evals.dg25.s3a_generator import (
    build_e1_action_manifest,
    generate_e1_all_arm_bundle,
    validate_e1_action_manifest,
)
from evals.dg25.stop_gate import evaluate_generation_gate, evaluate_score_gate
from scripts import run_dg25_s3a

ROOT = Path(__file__).resolve().parents[1]


def test_readiness_package_freezes_review_edits_without_effect() -> None:
    artifacts = build_readiness_artifacts(ROOT)
    validation = artifacts["readiness-validation-report.json"]
    delta = artifacts["execution-delta-manifest.json"]
    assert validation["hard_gate"]["passed"] is True
    assert all(validation["checks"].values())
    assert delta["E1"]["arm_order"] == list(E1_ARM_ORDER)
    assert delta["E2"]["arm_order"] == list(E2_ARM_ORDER)
    assert artifacts["e1-action-role-manifest.json"]["plan_count"] == 165
    frozen_case_order = [
        "gpt4_8279ba03",
        "9a707b82",
        "2a1811e2",
        "0bb5a684",
        "2e6d26dc",
        "4dfccbf7",
        "gpt4_88806d6e",
        "a89d7624",
        "a82c026e",
        "88432d0a",
    ]
    assert artifacts["e1-action-role-manifest.json"]["case_order"] == (
        frozen_case_order
    )
    assert delta["case_order_digest"] == canonical_sha256(frozen_case_order)
    assert (
        artifacts["quality-evidence-binding.json"]["disposition"]
        == "EXPLICITLY_NON_AUTHORITATIVE_TEST_ONLY"
    )
    assert delta["presealed_s3a_implementation"]["output_schema"] == (
        "milai.dg25.label-free-arm-output.v0.2"
    )
    assert delta["authorization"] == {
        "readiness_only": True,
        "e1_official_pool_replay": False,
        "e2_official_row_transformation": False,
        "effect_scoring": False,
        "registry_content_load": False,
        "e3_product_treatment": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "latency_repeats": False,
        "automatic_retries": 0,
    }


def test_self_consistent_action_manifest_with_wrong_case_order_is_rejected() -> None:
    artifacts = build_readiness_artifacts(ROOT)
    delta = artifacts["execution-delta-manifest.json"]
    manifest = deepcopy(artifacts["e1-action-role-manifest.json"])
    frozen_case_order = list(manifest["case_order"])
    wrong_order = list(reversed(frozen_case_order))
    manifest["case_order"] = wrong_order
    manifest["case_order_digest"] = canonical_sha256(wrong_order)
    material = dict(manifest)
    material.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_sha256(material)
    configs = [
        E1ArmConfigV01.model_validate(item) for item in delta["E1"]["arm_configs"]
    ]
    with pytest.raises(ValueError, match="CASE_ORDER_DRIFT"):
        validate_e1_action_manifest(
            manifest=manifest,
            configs=configs,
            pool_binding_digest=delta["e1_common_pool"]["pool_binding_digest"],
            expected_case_order=frozen_case_order,
        )


def test_e2_common_input_is_exact_and_t2_applicability_is_prelabel() -> None:
    common = build_readiness_artifacts(ROOT)["e2-common-input.json"]
    assert common["requirement_count"] == 2
    assert common["raw_row_count"] == 973
    assert [item["raw_row_count"] for item in common["requirements"]] == [494, 479]
    assert all(
        item["t2_applicability"] == {
            "disposition": "NOT_APPLICABLE",
            "reason_code": "NO_GROUNDED_UNIQUE_ANCHOR_RELATION_IN_SEALED_ROW_CONTRACT",
            "decided_before_labels": True,
        }
        for item in common["requirements"]
    )
    material = dict(common)
    observed = material.pop("common_input_digest")
    assert observed == canonical_sha256(material)


def test_rank_replay_uses_channel_rank_reservation_and_preserves_lineage() -> None:
    artifacts = build_readiness_artifacts(ROOT)
    delta = artifacts["execution-delta-manifest.json"]
    config = E1ArmConfigV01.model_validate(delta["E1"]["arm_configs"][4])
    plan = next(
        E1RequirementActionPlanV01.model_validate(item)
        for item in artifacts["e1-action-role-manifest.json"]["plans"]
        if item["arm_id"] == "R3" and item["optional_action"] is not None
    )
    optional_channel = plan.optional_action.channel if plan.optional_action else ""
    required_role = plan.required_roles[0]
    raw = [
        _occurrence(
            "raw-1", "evidence-a", "FTS_RAW", 1, roles=[], requirement_id=plan.requirement_id
        ),
        _occurrence(
            "raw-2", "evidence-b", "FTS_RAW", 2, roles=[], requirement_id=plan.requirement_id
        ),
    ]
    optional = [
        _occurrence(
            "optional-1",
            "evidence-a",
            optional_channel,
            1,
            roles=[],
            requirement_id=plan.requirement_id,
        ),
        _occurrence(
            "optional-2",
            "evidence-c",
            optional_channel,
            2,
            roles=[required_role],
            requirement_id=plan.requirement_id,
        ),
    ]
    selected = select_label_free_occurrences(
        per_channel={"FTS_RAW": raw, optional_channel: optional},
        action_plan=plan,
        expected_action_plan_digest=plan.plan_digest,
        config=config,
    )
    assert selected[0].evidence_id == "evidence-c"
    evidence_a = next(item for item in selected if item.evidence_id == "evidence-a")
    assert [item["channel"] for item in evidence_a.discovery_lineage] == [
        "FTS_RAW",
        optional_channel,
    ]
    assert all(item.final_rank <= 8 for item in selected)


def test_r1_required_proof_composition_is_not_optional_union() -> None:
    artifacts = build_readiness_artifacts(ROOT)
    delta = artifacts["execution-delta-manifest.json"]
    config = E1ArmConfigV01.model_validate(delta["E1"]["arm_configs"][2])
    plan = next(
        E1RequirementActionPlanV01.model_validate(item)
        for item in artifacts["e1-action-role-manifest.json"]["plans"]
        if item["arm_id"] == "R1" and item["proof_required"] is True
    )
    assert [item.action_kind for item in plan.active_actions] == [
        "BASELINE_DISCOVERY",
        "REQUIRED_PROOF_CLOSURE",
    ]
    assert plan.optional_action is None
    selected = select_label_free_occurrences(
        per_channel={
            "FTS_RAW": [
                _occurrence(
                    "raw-1",
                    "evidence-a",
                    "FTS_RAW",
                    1,
                    roles=[],
                    requirement_id=plan.requirement_id,
                )
            ],
            "TEMPORAL_EVENT": [
                _occurrence(
                    "temporal-1",
                    "evidence-b",
                    "TEMPORAL_EVENT",
                    1,
                    roles=[],
                    requirement_id=plan.requirement_id,
                )
            ],
        },
        action_plan=plan,
        expected_action_plan_digest=plan.plan_digest,
        config=config,
    )
    assert [item.evidence_id for item in selected] == ["evidence-a", "evidence-b"]


def test_action_vector_rejects_omitted_mislabeled_wrong_channel_and_budget_escape() -> None:
    artifacts = build_readiness_artifacts(ROOT)
    delta = artifacts["execution-delta-manifest.json"]
    manifest = artifacts["e1-action-role-manifest.json"]
    r1_config = E1ArmConfigV01.model_validate(delta["E1"]["arm_configs"][2])
    r1_plan = next(
        E1RequirementActionPlanV01.model_validate(item)
        for item in manifest["plans"]
        if item["arm_id"] == "R1" and item["proof_required"] is True
    )
    omitted = build_e1_requirement_action_plan(
        **{
            **r1_plan.model_dump(
                mode="json",
                exclude={
                    "plan_digest",
                    "baseline_action",
                    "proof_action",
                    "active_action_digests",
                },
            ),
            "baseline_action": r1_plan.baseline_action,
            "proof_action": None,
            "active_action_digests": [r1_plan.baseline_action.action_digest],
        }
    )
    with pytest.raises(ValueError, match="REQUIRED_PROOF_ACTION_OMITTED"):
        validate_e1_requirement_action_plan(
            plan=omitted,
            config=r1_config,
            expected_plan_digest=omitted.plan_digest,
        )
    with pytest.raises(ValueError, match="NOT_FROZEN_MANIFEST_MEMBER"):
        validate_e1_requirement_action_plan(
            plan=omitted,
            config=r1_config,
            expected_plan_digest=r1_plan.plan_digest,
        )

    assert r1_plan.proof_action is not None
    mislabeled = build_replay_action(
        case_id=r1_plan.case_id,
        requirement_id=r1_plan.requirement_id,
        channel=r1_plan.proof_action.channel,
        action_kind="OPTIONAL_DISCOVERY",
        channel_query_identity_digest=r1_plan.proof_action.channel_query_identity_digest,
        returned_occurrence_count=r1_plan.proof_action.returned_occurrence_count,
    )
    mislabeled_plan = build_e1_requirement_action_plan(
        **{
            **r1_plan.model_dump(
                mode="json",
                exclude={
                    "plan_digest",
                    "baseline_action",
                    "proof_action",
                    "active_action_digests",
                },
            ),
            "baseline_action": r1_plan.baseline_action,
            "proof_action": mislabeled,
            "active_action_digests": [
                r1_plan.baseline_action.action_digest,
                mislabeled.action_digest,
            ],
        }
    )
    with pytest.raises(ValueError, match="MISLABELED_OR_WRONG_CHANNEL"):
        validate_e1_requirement_action_plan(
            plan=mislabeled_plan,
            config=r1_config,
            expected_plan_digest=mislabeled_plan.plan_digest,
        )
    with pytest.raises(ValidationError, match="PROOF_ACTION_CHANNEL_INVALID"):
        build_replay_action(
            case_id=r1_plan.case_id,
            requirement_id=r1_plan.requirement_id,
            channel="EVIDENCE_DENSE",
            action_kind="REQUIRED_PROOF_CLOSURE",
            channel_query_identity_digest="a" * 64,
            returned_occurrence_count=1,
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ReplayActionV01.model_validate(
            {**r1_plan.baseline_action.model_dump(mode="json"), "action_role": "PROOF_CLOSURE"}
        )

    r2_range = next(
        E1RequirementActionPlanV01.model_validate(item)
        for item in manifest["plans"]
        if item["arm_id"] == "R2"
        and item["proof_required"] is True
        and item["available_optional_channels"]
    )
    assert len(r2_range.active_actions) == 2
    assert r2_range.optional_action is None
    assert r2_range.optional_action_disposition == "BUDGET_NOT_AUTHORIZED"


def test_stop_gate_rejects_s3_labels_and_missing_e2_seal() -> None:
    artifacts = build_readiness_artifacts(ROOT)
    stop = artifacts["stop-evaluation-contract.json"]
    expected = stop["s3a_generation_bindings"]
    generation_observations = {
        **expected,
        "labels_loaded": True,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
        "output_directory_exists": False,
        "arm_output_count": 0,
        "all_arm_seal_present": False,
    }
    generation = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="PRE_GENERATION",
        observations=generation_observations,
        expected_bindings=expected,
    )
    assert generation["passed"] is False
    score_expected = dict(stop["readiness_bindings"])
    score_expected.update(
        {field: "a" * 64 for field in stop["future_exact_bindings_required"]}
    )
    observations = _positive_pre_score_observations(score_expected)
    observations["e2_all_arm_seal_present"] = False
    score_gate = evaluate_score_gate(
        phase="PRE_SCORE",
        observations=observations,
        expected_bindings=score_expected,
    )
    assert score_gate["passed"] is False
    assert score_gate["schedule_checks"]["e2_all_arm_seal_present"] is False
    wrong_digest = _positive_pre_score_observations(score_expected)
    wrong_digest["execution_delta_manifest_digest"] = "f" * 64
    score_gate = evaluate_score_gate(
        phase="PRE_SCORE",
        observations=wrong_digest,
        expected_bindings=score_expected,
    )
    assert score_gate["passed"] is False
    assert score_gate["binding_checks"]["execution_delta_manifest_digest"]["passed"] is False
    post_generation = {
        **expected,
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
        "arm_output_count": 11,
        "all_arm_seal_present": True,
        "arm_order_exact": True,
        "output_content_digests_recomputed": True,
        "execution_bindings_recomputed": True,
        "all_arm_seal_recomputed": True,
        "partial_duplicate_or_reordered_outputs": 0,
        "case_order_exact": False,
    }
    post_gate = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="POST_GENERATION",
        observations=post_generation,
        expected_bindings=expected,
    )
    assert post_gate["passed"] is False
    assert post_gate["checks"]["case_order_exact"] is False


def test_effect_scorer_accepts_only_joint_sealed_synthetic_arm_set() -> None:
    gold, proof = _synthetic_registries()
    arm_outputs, combined, readiness_bindings = _synthetic_sealed_outputs(gold, proof)
    authorization_material = {
        "schema": "milai.dg25.independent-scoring-authorization.v0.1",
        "authorized": True,
        "combined_all_arm_seal_digest": combined["seal_digest"],
        "readiness_bindings_digest": combined["readiness_bindings_digest"],
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_authorized": False,
    }
    authorization = {
        **authorization_material,
        "authorization_digest": canonical_sha256(authorization_material),
    }
    score = score_all_arms(
        combined_seal=combined,
        arm_outputs=arm_outputs,
        gold_registry=gold,
        proof_registry=proof,
        authorization=authorization,
        expected_contract_digest=scorer_contract()["contract_digest"],
        expected_readiness_bindings=readiness_bindings,
    )
    assert score["denominators"] == {"queries": 10, "groups": 23, "proofs": 37}
    assert all(item["covered_groups"] == 23 for item in score["arm_scores"].values())
    assert all(
        item["proof_obligations_satisfied"] == 37
        for item in score["arm_scores"].values()
    )
    assert score["post_score_adaptation"] is False

    wrong_expected = dict(readiness_bindings)
    wrong_expected["execution_delta_manifest_digest"] = "f" * 64
    with pytest.raises(ValueError, match="READINESS_BINDING_MISMATCH"):
        score_all_arms(
            combined_seal=combined,
            arm_outputs=arm_outputs,
            gold_registry=gold,
            proof_registry=proof,
            authorization=authorization,
            expected_contract_digest=scorer_contract()["contract_digest"],
            expected_readiness_bindings=wrong_expected,
        )


def test_effect_scorer_rejects_self_consistent_execution_binding_drift() -> None:
    gold, proof = _synthetic_registries()
    arm_outputs, combined, readiness_bindings = _synthetic_sealed_outputs(gold, proof)
    tampered_outputs = deepcopy(arm_outputs)
    tampered = tampered_outputs["R0"]
    binding = tampered["execution_binding"]
    binding["execution_delta_manifest_digest"] = "f" * 64
    binding_material = dict(binding)
    binding_material.pop("execution_binding_digest")
    binding["execution_binding_digest"] = canonical_sha256(binding_material)
    output_material = dict(tampered)
    output_material.pop("output_digest")
    tampered["output_digest"] = canonical_sha256(output_material)

    tampered_combined = deepcopy(combined)
    tampered_combined["arm_execution_binding_digests"]["R0"] = binding[
        "execution_binding_digest"
    ]
    tampered_combined["arm_output_content_digests"]["R0"] = tampered[
        "output_digest"
    ]
    tampered_combined["arm_output_set_digest"] = canonical_sha256(
        tampered_combined["arm_output_content_digests"]
    )
    combined_material = dict(tampered_combined)
    combined_material.pop("seal_digest")
    tampered_combined["seal_digest"] = canonical_sha256(combined_material)
    authorization_material = {
        "schema": "milai.dg25.independent-scoring-authorization.v0.1",
        "authorized": True,
        "combined_all_arm_seal_digest": tampered_combined["seal_digest"],
        "readiness_bindings_digest": tampered_combined[
            "readiness_bindings_digest"
        ],
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_authorized": False,
    }
    authorization = {
        **authorization_material,
        "authorization_digest": canonical_sha256(authorization_material),
    }
    with pytest.raises(
        ValueError, match="ARM_PREREGISTERED_EXECUTION_BINDING_MISMATCH"
    ):
        score_all_arms(
            combined_seal=tampered_combined,
            arm_outputs=tampered_outputs,
            gold_registry=gold,
            proof_registry=proof,
            authorization=authorization,
            expected_contract_digest=scorer_contract()["contract_digest"],
            expected_readiness_bindings=readiness_bindings,
        )


def test_e1_sealer_rejects_partial_and_reordered_arm_sets() -> None:
    gold, proof = _synthetic_registries()
    arm_outputs, _, _ = _synthetic_sealed_outputs(gold, proof)
    e1_outputs = {arm_id: arm_outputs[arm_id] for arm_id in E1_ARM_ORDER}
    config_digests = {
        arm_id: str(e1_outputs[arm_id]["arm_config_digest"])
        for arm_id in E1_ARM_ORDER
    }
    common = dict(e1_outputs[E1_ARM_ORDER[0]]["execution_binding"])
    for field in (
        "schema",
        "block",
        "arm_id",
        "arm_config_digest",
        "block_input_identity",
        "execution_binding_digest",
    ):
        common.pop(field)
    inputs = {
        arm_id: dict(e1_outputs[arm_id]["execution_binding"]["block_input_identity"])
        for arm_id in E1_ARM_ORDER
    }
    invalid_sets = (
        {arm_id: e1_outputs[arm_id] for arm_id in E1_ARM_ORDER[:-1]},
        {arm_id: e1_outputs[arm_id] for arm_id in reversed(E1_ARM_ORDER)},
    )
    for invalid in invalid_sets:
        with pytest.raises(ValueError, match="OUTPUT_SET_OR_ORDER_MISMATCH"):
            build_block_all_arm_seal(
                block="E1",
                arm_outputs=invalid,
                arm_order=E1_ARM_ORDER,
                config_digests=config_digests,
                common_execution_bindings=common,
                block_input_identities=inputs,
                generator_source_sha256="1" * 64,
                sealer_source_sha256="2" * 64,
                runner_source_sha256="3" * 64,
                independent_authorization_digest="4" * 64,
            )


@pytest.mark.parametrize(
    ("gate_id", "failure_kind"),
    [
        ("DG25_S3A_OUTPUT_DIRECTORY_PRECHECK", "existing-output"),
        ("DG25_S3A_POST_GENERATION_STOP_GATE", "post-gate"),
    ],
)
def test_official_s3a_failure_wrapper_appends_exactly_one_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_id: str,
    failure_kind: str,
) -> None:
    run_id = f"synthetic-{failure_kind}"
    args = _synthetic_official_s3a_attempt(
        tmp_path,
        run_id=run_id,
        existing_output=failure_kind == "existing-output",
    )
    generation_calls = 0

    def fail_closed_bundle(**_kwargs: object) -> dict[str, Any]:
        nonlocal generation_calls
        generation_calls += 1
        return {"arm_outputs": {}, "e1_all_arm_seal": {}}

    monkeypatch.setattr(
        run_dg25_s3a,
        "generate_e1_all_arm_bundle",
        fail_closed_bundle,
    )

    with pytest.raises((FileExistsError, ValueError)):
        run_dg25_s3a._run_s3a_once(
            args,
            root=tmp_path,
            argv=("run_dg25_s3a.py", "--run-id", run_id),
        )
    index_path = tmp_path / "var/dg25/failure-index.jsonl"
    index_lines = index_path.read_text(encoding="utf-8").splitlines()
    assert len(index_lines) == 1
    index_record = json.loads(index_lines[0])
    receipt_identity = index_record["receipt"]
    receipt_path = tmp_path / receipt_identity["path"]
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == (
        receipt_identity["sha256"]
    )
    assert receipt_path.stat().st_size == receipt_identity["size"]
    raw_receipt: object = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert isinstance(raw_receipt, dict)
    receipt = {str(key): value for key, value in raw_receipt.items()}
    assert receipt["first_failing_gate"] == gate_id
    assert receipt["automatic_retries"] == 0
    assert receipt["command"]["argv"][-1] == run_id
    envelope = dict(receipt["attempt_identity_envelope"])
    envelope_digest = envelope.pop("envelope_digest")
    assert envelope_digest == canonical_sha256(envelope)
    assert receipt["attempt_identity_envelope_digest"] == envelope_digest
    assert envelope["frozen_before_covered_prechecks"] is True
    assert envelope["complete_inventory_frozen"] is True
    assert len(receipt["snapshot_identities"]) == 2
    assert len(receipt["source_identities"]) == 18
    assert len(receipt["input_identities"]) == 12
    assert receipt["snapshot_identities"] == envelope["snapshot_identities"]
    assert receipt["source_identities"] == envelope["source_identities"]
    assert receipt["input_identities"] == envelope["input_identities"]
    assert all(
        item["observed_identity"] is not None
        for item in receipt["snapshot_identities"]
    )
    assert all(
        item["expected_identity"].get("sha256")
        and item["observed_identity"] is not None
        and item["disposition"] == "MATCH"
        for item in receipt["source_identities"] + receipt["input_identities"]
    )
    assert set(envelope["capture_diagnostics"].values()) == {None}
    assert receipt["stdout"]["size"] == 0
    assert receipt["stderr"]["size"] > 0
    for stream in ("stdout", "stderr"):
        stream_identity = receipt[stream]
        stream_path = tmp_path / stream_identity["path"]
        assert hashlib.sha256(stream_path.read_bytes()).hexdigest() == (
            stream_identity["sha256"]
        )
        assert stream_path.stat().st_size == stream_identity["size"]
    assert len(list((tmp_path / "var/dg25/failures").iterdir())) == 1
    assert generation_calls == (0 if failure_kind == "existing-output" else 1)


def _synthetic_official_s3a_attempt(
    root: Path,
    *,
    run_id: str,
    existing_output: bool,
) -> argparse.Namespace:
    artifacts = build_readiness_artifacts(ROOT)
    readiness_run_id = "synthetic-readiness"
    readiness_dir = root / "var/dg25/readiness" / readiness_run_id
    readiness_dir.mkdir(parents=True)
    artifact_identities: dict[str, dict[str, Any]] = {}
    for filename, value in artifacts.items():
        path = readiness_dir / filename
        _write_test_json(path, value)
        key = filename.removesuffix(".json").replace("-", "_")
        artifact_identities[key] = _test_file_identity(root, path)

    receipt_path = readiness_dir / "receipt.json"
    _write_test_json(
        receipt_path,
        {
            "schema": "milai.dg25.s3-readiness-receipt.v0.1",
            "run_id": readiness_run_id,
            "status": (
                "PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION"
            ),
            "artifacts": artifact_identities,
        },
    )
    source_manifest = artifacts["source-manifest.json"]
    for item in source_manifest["files"]:
        _copy_repository_file(root, Path(str(item["path"])))
    action_manifest = artifacts["e1-action-role-manifest.json"]
    for key in ("official_probe_collection", "product_trace_collection"):
        _copy_repository_file(
            root,
            Path(str(action_manifest[key]["path"])),
        )

    expected = artifacts["stop-evaluation-contract.json"][
        "s3a_generation_bindings"
    ]
    authorization_material = {
        "schema": "milai.dg25.s3a-independent-authorization.v0.1",
        "authorized": True,
        "scope": "S3A_E1_LABEL_FREE_ALL_11_ARMS_AND_ONE_SEAL",
        "readiness_bindings": expected,
        "readiness_bindings_digest": canonical_sha256(expected),
        "labels_authorized": False,
        "scoring_authorized": False,
        "s4a_authorized": False,
        "s4b_authorized": False,
        "e3_authorized": False,
        "reader_model_provider_controller_calls_authorized": 0,
        "formal_holdout_authorized": False,
        "automatic_retries": 0,
    }
    authorization = {
        **authorization_material,
        "authorization_digest": canonical_sha256(authorization_material),
    }
    readiness_identity = _test_file_identity(root, receipt_path)
    review_relative_path = Path("var/dg25/reviews/synthetic-review.json")
    review_path = root / review_relative_path
    _write_test_json(
        review_path,
        {
            "schema": "milai.dg25.s3-readiness-independent-review.v0.test",
            "verdict": "AUTHORIZE_S3A_E1_LABEL_FREE_ALL_ARM_GENERATION",
            "reviewed_readiness_receipt_sha256": readiness_identity["sha256"],
            "reviewed_inputs": [readiness_identity],
            "s3a_execution_authorization": authorization,
        },
    )
    args = argparse.Namespace(
        run_id=run_id,
        readiness_run_id=readiness_run_id,
        authorization_review=review_relative_path,
    )
    if existing_output:
        (root / "var/dg25/s3a" / run_id).mkdir(parents=True)
    return args


def _test_file_identity(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _write_test_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy_repository_file(root: Path, relative_path: Path) -> None:
    destination = root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / relative_path, destination)
    assert destination.is_symlink() is False
    assert destination.resolve().is_relative_to(root.resolve())


def _latest_failure_receipt(
    root: Path,
    *,
    previous_index_count: int,
    expected_gate: str,
) -> dict[str, Any]:
    index_path = root / "var/dg25/failure-index.jsonl"
    index_lines = index_path.read_text(encoding="utf-8").splitlines()
    assert len(index_lines) == previous_index_count + 1
    index_record = json.loads(index_lines[-1])
    receipt_identity = index_record["receipt"]
    receipt_path = root / receipt_identity["path"]
    assert _test_file_identity(root, receipt_path) == receipt_identity
    raw_receipt: object = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert isinstance(raw_receipt, dict)
    receipt = {str(key): value for key, value in raw_receipt.items()}
    assert receipt["first_failing_gate"] == expected_gate
    assert receipt["automatic_retries"] == 0
    envelope = dict(receipt["attempt_identity_envelope"])
    digest = envelope.pop("envelope_digest")
    assert canonical_sha256(envelope) == digest
    assert envelope["complete_inventory_frozen"] is True
    assert len(envelope["snapshot_identities"]) == 2
    assert len(envelope["readiness_artifact_identities"]) == 10
    assert len(envelope["source_identities"]) == 18
    assert len(envelope["predecessor_input_identities"]) == 2
    assert len(envelope["input_identities"]) == 12
    assert all(
        isinstance(item["disposition"], str)
        for group in (
            "snapshot_identities",
            "readiness_artifact_identities",
            "source_identities",
            "predecessor_input_identities",
        )
        for item in envelope[group]
    )
    assert receipt["stdout"]["size"] == 0
    assert receipt["stderr"]["size"] > 0
    return receipt


def _restore_test_files(baseline: Mapping[Path, bytes]) -> None:
    for path, content in baseline.items():
        if path.is_symlink() or path.exists():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _rebind_synthetic_receipt_and_review(
    root: Path,
    *,
    artifact_key: str | None = None,
) -> None:
    readiness_dir = root / "var/dg25/readiness/synthetic-readiness"
    receipt_path = readiness_dir / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if artifact_key is not None:
        filename = run_dg25_s3a.READINESS_ARTIFACT_FILENAMES[artifact_key]
        receipt["artifacts"][artifact_key] = _test_file_identity(
            root,
            readiness_dir / filename,
        )
        _write_test_json(receipt_path, receipt)
    readiness_identity = _test_file_identity(root, receipt_path)
    review_path = root / "var/dg25/reviews/synthetic-review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["reviewed_readiness_receipt_sha256"] = readiness_identity["sha256"]
    review["reviewed_inputs"] = [readiness_identity]
    _write_test_json(review_path, review)


def test_official_s3a_capture_failures_are_total_and_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    base_args = _synthetic_official_s3a_attempt(
        root,
        run_id="capture-base",
        existing_output=False,
    )
    readiness_dir = root / "var/dg25/readiness/synthetic-readiness"
    targets = {
        "readiness_receipt": readiness_dir / "receipt.json",
        "authorization_review": root / "var/dg25/reviews/synthetic-review.json",
        "source_manifest": readiness_dir / "source-manifest.json",
        "e1_action_role_manifest": readiness_dir / "e1-action-role-manifest.json",
    }
    baseline = {path: path.read_bytes() for path in targets.values()}
    original_read_json = run_dg25_s3a._read_json
    generation_calls = 0

    def forbidden_generation(**_kwargs: object) -> dict[str, Any]:
        nonlocal generation_calls
        generation_calls += 1
        raise AssertionError("generation must not run after capture failure")

    monkeypatch.setattr(
        run_dg25_s3a,
        "generate_e1_all_arm_bundle",
        forbidden_generation,
    )
    attempt_number = 0
    for document_key, target in targets.items():
        for failure_mode in ("invalid-utf8", "invalid-json", "unreadable"):
            _restore_test_files(baseline)
            monkeypatch.setattr(run_dg25_s3a, "_read_json", original_read_json)
            run_id = f"capture-{document_key}-{failure_mode}"
            args = argparse.Namespace(
                run_id=run_id,
                readiness_run_id=base_args.readiness_run_id,
                authorization_review=base_args.authorization_review,
            )
            if failure_mode in {"invalid-utf8", "invalid-json"}:
                target.write_bytes(
                    b"\xff\xfeDG25-invalid-utf8"
                    if failure_mode == "invalid-utf8"
                    else b'{"DG25":'
                )
                if document_key == "source_manifest":
                    _rebind_synthetic_receipt_and_review(
                        root,
                        artifact_key="source_manifest",
                    )
                elif document_key == "e1_action_role_manifest":
                    _rebind_synthetic_receipt_and_review(
                        root,
                        artifact_key="e1_action_role_manifest",
                    )
            else:
                def unreadable_json(
                    path: Path,
                    *,
                    blocked: Path = target,
                ) -> dict[str, Any]:
                    if path == blocked:
                        raise PermissionError("synthetic unreadable capture input")
                    return original_read_json(path)

                monkeypatch.setattr(run_dg25_s3a, "_read_json", unreadable_json)

            index_path = root / "var/dg25/failure-index.jsonl"
            previous_count = (
                len(index_path.read_text(encoding="utf-8").splitlines())
                if index_path.exists()
                else 0
            )
            with pytest.raises(ValueError, match="ATTEMPT_CAPTURE_INCOMPLETE"):
                run_dg25_s3a._run_s3a_once(
                    args,
                    root=root,
                    argv=("run_dg25_s3a.py", "--run-id", run_id),
                )
            receipt = _latest_failure_receipt(
                root,
                previous_index_count=previous_count,
                expected_gate="DG25_S3A_ATTEMPT_IDENTITY_ENVELOPE_PRECHECK",
            )
            diagnostic_types = {
                value.get("type")
                for value in receipt["attempt_identity_envelope"][
                    "capture_diagnostics"
                ].values()
                if isinstance(value, Mapping)
            }
            assert (
                "UnicodeDecodeError"
                if failure_mode == "invalid-utf8"
                else "JSONDecodeError"
                if failure_mode == "invalid-json"
                else "PermissionError"
            ) in diagnostic_types
            assert receipt["attempt_identity_envelope"][
                "capture_frozen_before_execute"
            ] is True
            assert receipt["attempt_identity_envelope"]["capture_complete"] is False
            attempt_number += 1
            assert len(list((root / "var/dg25/failures").iterdir())) == attempt_number
    assert generation_calls == 0


def test_official_s3a_path_negatives_reject_before_read_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "forbidden.json"
    outside_payload = b"\xffDG25-forbidden-outside-content"
    outside_file.write_bytes(outside_payload)
    base_args = _synthetic_official_s3a_attempt(
        root,
        run_id="path-base",
        existing_output=False,
    )
    readiness_dir = root / "var/dg25/readiness/synthetic-readiness"
    receipt_path = readiness_dir / "receipt.json"
    review_path = root / "var/dg25/reviews/synthetic-review.json"
    source_manifest_path = readiness_dir / "source-manifest.json"
    action_manifest_path = readiness_dir / "e1-action-role-manifest.json"
    source_path = root / run_dg25_s3a.READINESS_SOURCE_PATHS[0]
    predecessor_path = root / run_dg25_s3a.PREDECESSOR_INPUT_PATHS[
        "official_probe_collection"
    ]
    baseline = {
        path: path.read_bytes()
        for path in (
            receipt_path,
            review_path,
            source_manifest_path,
            action_manifest_path,
            source_path,
            predecessor_path,
        )
    }
    original_read_json = run_dg25_s3a._read_json
    read_paths: list[Path] = []
    generation_calls = 0

    def tracked_read_json(path: Path) -> dict[str, Any]:
        read_paths.append(path)
        return original_read_json(path)

    def forbidden_generation(**_kwargs: object) -> dict[str, Any]:
        nonlocal generation_calls
        generation_calls += 1
        raise AssertionError("generation must not run after path failure")

    monkeypatch.setattr(run_dg25_s3a, "_read_json", tracked_read_json)
    monkeypatch.setattr(
        run_dg25_s3a,
        "generate_e1_all_arm_bundle",
        forbidden_generation,
    )
    cases = (
        "run-absolute",
        "run-traversal",
        "readiness-absolute",
        "readiness-traversal",
        "authorization-absolute",
        "authorization-traversal",
        "authorization-external-symlink",
        "readiness-receipt-external-symlink",
        "readiness-directory-external-symlink",
        "output-root-external-symlink",
        "artifact-absolute",
        "artifact-traversal",
        "source-absolute",
        "source-traversal",
        "predecessor-absolute",
        "predecessor-traversal",
        "artifact-external-symlink",
        "source-external-symlink",
        "predecessor-external-symlink",
    )
    for attempt_number, failure_kind in enumerate(cases, start=1):
        _restore_test_files(baseline)
        output_root = root / "var/dg25/s3a"
        if output_root.is_symlink():
            output_root.unlink()
        symlink_readiness = root / "var/dg25/readiness/symlink-readiness"
        if symlink_readiness.is_symlink():
            symlink_readiness.unlink()
        read_paths.clear()
        args = argparse.Namespace(
            run_id=f"path-negative-{attempt_number}",
            readiness_run_id=base_args.readiness_run_id,
            authorization_review=base_args.authorization_review,
        )
        expected_gate = "DG25_S3A_ATTEMPT_IDENTITY_ENVELOPE_PRECHECK"
        if failure_kind == "run-absolute":
            args.run_id = str(outside / "absolute-run")
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind == "run-traversal":
            args.run_id = "../traversal-run"
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind == "readiness-absolute":
            args.readiness_run_id = str(outside / "absolute-readiness")
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind == "readiness-traversal":
            args.readiness_run_id = "../traversal-readiness"
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind == "authorization-absolute":
            args.authorization_review = review_path.resolve()
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind == "authorization-traversal":
            args.authorization_review = Path(
                "var/dg25/reviews/../synthetic-review.json"
            )
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind == "authorization-external-symlink":
            review_path.unlink()
            review_path.symlink_to(outside_file)
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind == "readiness-receipt-external-symlink":
            receipt_path.unlink()
            receipt_path.symlink_to(outside_file)
        elif failure_kind == "readiness-directory-external-symlink":
            symlink_readiness.symlink_to(outside, target_is_directory=True)
            args.readiness_run_id = "symlink-readiness"
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind == "output-root-external-symlink":
            output_root.parent.mkdir(parents=True, exist_ok=True)
            output_root.symlink_to(outside, target_is_directory=True)
            expected_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
        elif failure_kind.startswith("artifact-") and not failure_kind.endswith(
            "symlink"
        ):
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["artifacts"]["source_manifest"]["path"] = (
                str(outside_file.resolve())
                if failure_kind.endswith("absolute")
                else "../forbidden-artifact.json"
            )
            _write_test_json(receipt_path, receipt)
            _rebind_synthetic_receipt_and_review(root)
        elif failure_kind.startswith("source-") and not failure_kind.endswith(
            "symlink"
        ):
            source_manifest = json.loads(
                source_manifest_path.read_text(encoding="utf-8")
            )
            source_manifest["files"][0]["path"] = (
                str(outside_file.resolve())
                if failure_kind.endswith("absolute")
                else "../forbidden-source.py"
            )
            _write_test_json(source_manifest_path, source_manifest)
            _rebind_synthetic_receipt_and_review(
                root,
                artifact_key="source_manifest",
            )
        elif failure_kind.startswith("predecessor-") and not failure_kind.endswith(
            "symlink"
        ):
            action_manifest = json.loads(
                action_manifest_path.read_text(encoding="utf-8")
            )
            action_manifest["official_probe_collection"]["path"] = (
                str(outside_file.resolve())
                if failure_kind.endswith("absolute")
                else "../forbidden-predecessor.json"
            )
            _write_test_json(action_manifest_path, action_manifest)
            _rebind_synthetic_receipt_and_review(
                root,
                artifact_key="e1_action_role_manifest",
            )
        elif failure_kind == "artifact-external-symlink":
            source_manifest_path.unlink()
            source_manifest_path.symlink_to(outside_file)
        elif failure_kind == "source-external-symlink":
            source_path.unlink()
            source_path.symlink_to(outside_file)
        elif failure_kind == "predecessor-external-symlink":
            predecessor_path.unlink()
            predecessor_path.symlink_to(outside_file)

        index_path = root / "var/dg25/failure-index.jsonl"
        previous_count = (
            len(index_path.read_text(encoding="utf-8").splitlines())
            if index_path.exists()
            else 0
        )
        with pytest.raises(ValueError):
            run_dg25_s3a._run_s3a_once(
                args,
                root=root,
                argv=("run_dg25_s3a.py", "--run-id", str(args.run_id)),
            )
        receipt = _latest_failure_receipt(
            root,
            previous_index_count=previous_count,
            expected_gate=expected_gate,
        )
        assert receipt["automatic_retries"] == 0
        assert outside_file not in read_paths
        assert outside_file.read_bytes() == outside_payload
        assert len(list((root / "var/dg25/failures").iterdir())) == attempt_number
        if failure_kind == "output-root-external-symlink":
            assert output_root.is_symlink()
        else:
            assert not output_root.exists() or not any(output_root.iterdir())
        if failure_kind.startswith("artifact-"):
            assert source_manifest_path not in read_paths
            assert action_manifest_path not in read_paths
    assert generation_calls == 0


def test_official_s3a_remaining_capture_exception_is_still_recorded_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    args = _synthetic_official_s3a_attempt(
        root,
        run_id="unexpected-capture-exception",
        existing_output=False,
    )

    def unexpected_capture(
        _args: argparse.Namespace,
        _context: run_dg25_s3a.S3AFailureContext,
        *,
        root: Path,
    ) -> None:
        assert root.is_dir()
        raise RuntimeError("synthetic unexpected capture failure")

    monkeypatch.setattr(
        run_dg25_s3a,
        "_capture_attempt_identity_envelope",
        unexpected_capture,
    )
    with pytest.raises(RuntimeError, match="unexpected capture failure"):
        run_dg25_s3a._run_s3a_once(
            args,
            root=root,
            argv=("run_dg25_s3a.py", "--run-id", str(args.run_id)),
        )
    receipt = _latest_failure_receipt(
        root,
        previous_index_count=0,
        expected_gate="DG25_S3A_ATTEMPT_IDENTITY_CAPTURE",
    )
    envelope = receipt["attempt_identity_envelope"]
    assert envelope["inventory_preallocated_before_reads"] is True
    assert envelope["capture_frozen_before_execute"] is False
    assert envelope["capture_complete"] is False
    assert len(list((root / "var/dg25/failures").iterdir())) == 1


def test_official_s3a_capture_dispositions_cover_missing_hash_and_stat_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    base_args = _synthetic_official_s3a_attempt(
        root,
        run_id="capture-disposition-base",
        existing_output=False,
    )
    readiness_dir = root / "var/dg25/readiness/synthetic-readiness"
    receipt_path = readiness_dir / "receipt.json"
    review_path = root / "var/dg25/reviews/synthetic-review.json"
    source_path = root / run_dg25_s3a.READINESS_SOURCE_PATHS[0]
    predecessor_path = root / run_dg25_s3a.PREDECESSOR_INPUT_PATHS[
        "official_probe_collection"
    ]
    baseline = {
        receipt_path: receipt_path.read_bytes(),
        review_path: review_path.read_bytes(),
    }
    original_sha256 = run_dg25_s3a._sha256
    original_stat = Path.stat
    cases = ("missing-expected-field", "hash-failure", "stat-failure")
    for attempt_number, failure_kind in enumerate(cases, start=1):
        _restore_test_files(baseline)
        monkeypatch.setattr(run_dg25_s3a, "_sha256", original_sha256)
        monkeypatch.setattr(Path, "stat", original_stat)
        if failure_kind == "missing-expected-field":
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["artifacts"]["source_manifest"].pop("sha256")
            _write_test_json(receipt_path, receipt)
            _rebind_synthetic_receipt_and_review(root)
        elif failure_kind == "hash-failure":
            def failing_sha256(path: Path) -> str:
                if path.absolute() == source_path.absolute():
                    raise OSError("synthetic source hash failure")
                return original_sha256(path)

            monkeypatch.setattr(run_dg25_s3a, "_sha256", failing_sha256)
        else:
            def failing_stat(
                path: Path,
                *,
                follow_symlinks: bool = True,
            ) -> os.stat_result:
                if path.absolute() == predecessor_path.absolute():
                    raise OSError("synthetic predecessor stat failure")
                return original_stat(path, follow_symlinks=follow_symlinks)

            monkeypatch.setattr(Path, "stat", failing_stat)

        index_path = root / "var/dg25/failure-index.jsonl"
        previous_count = (
            len(index_path.read_text(encoding="utf-8").splitlines())
            if index_path.exists()
            else 0
        )
        args = argparse.Namespace(
            run_id=f"capture-disposition-{attempt_number}",
            readiness_run_id=base_args.readiness_run_id,
            authorization_review=base_args.authorization_review,
        )
        with pytest.raises(ValueError, match="ATTEMPT_CAPTURE_INCOMPLETE"):
            run_dg25_s3a._run_s3a_once(
                args,
                root=root,
                argv=("run_dg25_s3a.py", "--run-id", str(args.run_id)),
            )
        receipt = _latest_failure_receipt(
            root,
            previous_index_count=previous_count,
            expected_gate="DG25_S3A_ATTEMPT_IDENTITY_ENVELOPE_PRECHECK",
        )
        envelope = receipt["attempt_identity_envelope"]
        assert envelope["capture_frozen_before_execute"] is True
        assert envelope["capture_complete"] is False
        serialized = json.dumps(envelope, sort_keys=True)
        if failure_kind == "missing-expected-field":
            assert "IDENTITY_NOT_EXACT" in serialized
        else:
            assert "OSError" in serialized
        assert len(list((root / "var/dg25/failures").iterdir())) == attempt_number


def test_s3a_ast_execution_surface_is_exact_source_bound_and_fail_closed() -> None:
    honest_sources = {
        "runner": (ROOT / "scripts/run_dg25_s3a.py").read_text(encoding="utf-8"),
        "generator": (ROOT / "evals/dg25/s3a_generator.py").read_text(
            encoding="utf-8"
        ),
    }
    for role, source in honest_sources.items():
        assert not _s3a_execution_surface_findings(source, role=role)

    bypasses = (
        (
            "AST-BYPASS-01-UNKNOWN-NAME-CALL",
            "runner",
            "def _bypass_01():\n    mystery_callable()\n",
            "UNRESOLVED_NAME_CALL_TARGET",
        ),
        (
            "AST-BYPASS-02-FORBIDDEN-ATTRIBUTE-ALIASED",
            "runner",
            "def _bypass_02(obj):\n    fn = obj.score_all_arms\n    fn()\n",
            "CALLABLE_ASSIGNMENT_ALIAS_FORBIDDEN",
        ),
        (
            "AST-BYPASS-03-SYS-MODULES-SUBSCRIPT-ROOT",
            "runner",
            (
                "def _bypass_03():\n"
                "    sys.modules['evals.dg25.effect_scorer'].score_all_arms()\n"
            ),
            "FORBIDDEN_DYNAMIC_ATTRIBUTE_ACCESS",
        ),
        (
            "AST-BYPASS-04-CALL-ROOT-ATTRIBUTE",
            "runner",
            "def _bypass_04(factory):\n    factory().score_all_arms()\n",
            "ATTRIBUTE_CALL_ROOT_NOT_NAME",
        ),
        (
            "AST-BYPASS-05-GETATTR-ALIASED",
            "runner",
            (
                "def _bypass_05(obj):\n"
                "    hidden = getattr\n"
                "    fn = hidden(obj, 'score_all_arms')\n"
                "    fn()\n"
            ),
            "FORBIDDEN_DYNAMIC_REFERENCE",
        ),
        (
            "AST-BYPASS-06-DUNDER-IMPORT-ALIASED",
            "runner",
            (
                "def _bypass_06():\n"
                "    hidden = __import__\n"
                "    module = hidden('evals.dg25.effect_scorer')\n"
                "    fn = module.score_all_arms\n"
                "    fn()\n"
            ),
            "FORBIDDEN_DYNAMIC_REFERENCE",
        ),
        (
            "AST-BYPASS-07-EVAL-ALIASED",
            "runner",
            (
                "def _bypass_07():\n"
                "    hidden = eval\n"
                "    fn = hidden('lambda: None')\n"
                "    fn()\n"
            ),
            "FORBIDDEN_DYNAMIC_REFERENCE",
        ),
        (
            "AST-BYPASS-08-SUBSCRIPT-TO-NAME-ALIAS",
            "generator",
            "def _bypass_08(dispatch):\n    fn = dispatch['score']\n    fn()\n",
            "CALLABLE_ASSIGNMENT_ALIAS_FORBIDDEN",
        ),
    )
    for bypass_id, role, payload, required_code in bypasses:
        findings = _s3a_execution_surface_findings(
            honest_sources[role] + "\n\n" + payload,
            role=role,
        )
        codes = {str(item["code"]) for item in findings}
        assert required_code in codes, (bypass_id, findings)
        assert "CALL_TARGET_ALLOWLIST_EXACT_MISMATCH" in codes, (
            bypass_id,
            findings,
        )


@pytest.mark.parametrize(
    "dynamic_name",
    ("compile", "exec", "globals", "locals", "vars", "setattr", "delattr"),
)
def test_s3a_ast_execution_surface_rejects_every_dynamic_builtin_alias(
    dynamic_name: str,
) -> None:
    source = (ROOT / "scripts/run_dg25_s3a.py").read_text(encoding="utf-8")
    payload = (
        "def _dynamic_alias_bypass():\n"
        f"    hidden = {dynamic_name}\n"
        "    hidden()\n"
    )
    findings = _s3a_execution_surface_findings(
        source + "\n\n" + payload,
        role="runner",
    )
    codes = {str(item["code"]) for item in findings}
    assert "FORBIDDEN_DYNAMIC_REFERENCE" in codes
    assert "CALLABLE_ASSIGNMENT_ALIAS_FORBIDDEN" in codes


def test_s3a_ast_execution_surface_rejects_dynamic_modules_and_expression_roots() -> None:
    source = (ROOT / "scripts/run_dg25_s3a.py").read_text(encoding="utf-8")
    payloads = (
        "def _builtins_bypass():\n    builtins.eval('1')\n",
        "def _importlib_bypass():\n    importlib.import_module('evals.dg25')\n",
        "def _lambda_root_bypass(obj):\n    (lambda: obj)().read_text()\n",
        "def _unresolved_attribute_bypass():\n    mystery.read_text()\n",
    )
    for payload in payloads:
        findings = _s3a_execution_surface_findings(
            source + "\n\n" + payload,
            role="runner",
        )
        assert findings, payload
        assert any(
            str(item["code"])
            in {
                "FORBIDDEN_DYNAMIC_REFERENCE",
                "ATTRIBUTE_CALL_ROOT_NOT_NAME",
                "ATTRIBUTE_CALL_ROOT_UNRESOLVED",
                "ATTRIBUTE_CALL_TARGET_NOT_ALLOWLISTED",
            }
            for item in findings
        ), (payload, findings)


def test_s3a_ast_runner_rejects_target_preserving_callback_transport_mutations() -> None:
    source = (ROOT / "scripts/run_dg25_s3a.py").read_text(encoding="utf-8")
    exact_executor = (
        "execute=lambda: _capture_and_execute(args, context, root=root),"
    )
    context_binding = "    context = _build_s3a_failure_context(args, root=root)"
    parser_anchor = (
        '    parser.add_argument("--authorization-review", type=Path, required=True)'
    )

    def mutate_executor(
        executor: str,
        *,
        parser_default: str | None = None,
    ) -> str:
        assert source.count(exact_executor) == 1
        assert source.count(context_binding) == 1
        mutated = source.replace(exact_executor, f"execute={executor},", 1)
        mutated = mutated.replace(
            context_binding,
            (
                context_binding
                + "\n    if False:\n"
                + "        _capture_and_execute(args, context, root=root)"
            ),
            1,
        )
        if parser_default is not None:
            assert mutated.count(parser_anchor) == 1
            mutated = mutated.replace(
                parser_anchor,
                parser_anchor
                + "\n"
                + (
                    '    parser.add_argument("--executor", '
                    f"default={parser_default})"
                ),
                1,
            )
        return mutated

    mutations = (
        (
            "ARGPARSE-DEFAULT-INT",
            mutate_executor("args.executor", parser_default="int"),
            {"RUNNER_EXECUTOR_BINDING_CONTRACT_MISMATCH"},
        ),
        (
            "ARGPARSE-DEFAULT-BUILTINS-GLOBALS",
            mutate_executor(
                "args.executor",
                parser_default="__builtins__.globals",
            ),
            {
                "RUNNER_EXECUTOR_BINDING_CONTRACT_MISMATCH",
                "FORBIDDEN_DYNAMIC_REFERENCE",
            },
        ),
        (
            "ARGPARSE-SCORER-ATTRIBUTE",
            mutate_executor("args.score_all_arms"),
            {
                "RUNNER_EXECUTOR_BINDING_CONTRACT_MISMATCH",
                "FORBIDDEN_EXECUTION_SURFACE_ATTRIBUTE_REFERENCE",
            },
        ),
        (
            "REQUIRED-EXECUTOR-MOVED-TO-IF-FALSE",
            mutate_executor("lambda: len(())"),
            {
                "RUNNER_EXECUTOR_BINDING_CONTRACT_MISMATCH",
                "STATICALLY_UNREACHABLE_CALL_FORBIDDEN",
            },
        ),
    )
    for mutation_id, mutated, required_codes in mutations:
        contract = _s3a_call_target_contract(mutated, role="runner")
        assert contract["exact_match"] is True, mutation_id
        assert contract["observed_target_count"] == 185, mutation_id
        findings = _s3a_execution_surface_findings(mutated, role="runner")
        codes = {str(item["code"]) for item in findings}
        assert "CALL_TARGET_ALLOWLIST_EXACT_MISMATCH" not in codes, mutation_id
        assert required_codes <= codes, (mutation_id, findings)


def test_s3a_ast_generator_rejects_target_preserving_callback_transports() -> None:
    source = (ROOT / "evals/dg25/s3a_generator.py").read_text(encoding="utf-8")
    exact_callback = (
        'record_requirements.sort(key=lambda item: str(item["requirement_id"]))'
    )
    assert source.count(exact_callback) == 1
    mutations = (
        (
            "SCORER-ATTRIBUTE-DATA",
            "record_requirements.sort(key=config.score_all_arms)",
            {
                "GENERATOR_CALLBACK_BINDING_CONTRACT_MISMATCH",
                "FORBIDDEN_EXECUTION_SURFACE_ATTRIBUTE_REFERENCE",
            },
        ),
        (
            "UNREVIEWED-BOUND-METHOD-DATA",
            "record_requirements.sort(key=record.get)",
            {"GENERATOR_CALLBACK_BINDING_CONTRACT_MISMATCH"},
        ),
        (
            "BUILTINS-GLOBALS-DATA",
            "record_requirements.sort(key=__builtins__.globals)",
            {
                "GENERATOR_CALLBACK_BINDING_CONTRACT_MISMATCH",
                "FORBIDDEN_DYNAMIC_REFERENCE",
            },
        ),
    )
    for mutation_id, replacement, required_codes in mutations:
        mutated = source.replace(exact_callback, replacement, 1)
        contract = _s3a_call_target_contract(mutated, role="generator")
        assert contract["exact_match"] is True, mutation_id
        assert contract["observed_target_count"] == 105, mutation_id
        findings = _s3a_execution_surface_findings(mutated, role="generator")
        codes = {str(item["code"]) for item in findings}
        assert "CALL_TARGET_ALLOWLIST_EXACT_MISMATCH" not in codes, mutation_id
        assert required_codes <= codes, (mutation_id, findings)


def test_presealed_s3a_generator_creates_all_11_synthetic_outputs_and_one_seal() -> None:
    artifacts = build_readiness_artifacts(ROOT)
    delta = artifacts["execution-delta-manifest.json"]
    configs = [
        E1ArmConfigV01.model_validate(item) for item in delta["E1"]["arm_configs"]
    ]
    identities, probes, product = _synthetic_s3a_inputs()
    synthetic_case_order = [str(item["case_id"]) for item in product["records"]]
    action_manifest = build_e1_action_manifest(
        configs=configs,
        exact_channel_query_identities=identities,
        official_probe_collection=probes,
        official_probe_identity={"path": "synthetic://probes", "sha256": "1" * 64, "size": 1},
        product_traces=product,
        product_trace_identity={"path": "synthetic://product", "sha256": "2" * 64, "size": 1},
        pool_binding_digest=configs[0].pool_binding_digest,
        frozen_case_order=synthetic_case_order,
    )
    expected = dict(
        artifacts["stop-evaluation-contract.json"]["s3a_generation_bindings"]
    )
    expected["case_order_digest"] = canonical_sha256(synthetic_case_order)
    authorization_material = {
        "schema": "milai.dg25.s3a-independent-authorization.v0.1",
        "authorized": True,
        "scope": "S3A_E1_LABEL_FREE_ALL_11_ARMS_AND_ONE_SEAL",
        "readiness_bindings": expected,
        "readiness_bindings_digest": canonical_sha256(expected),
        "labels_authorized": False,
        "scoring_authorized": False,
        "s4a_authorized": False,
        "s4b_authorized": False,
        "e3_authorized": False,
        "reader_model_provider_controller_calls_authorized": 0,
        "formal_holdout_authorized": False,
        "automatic_retries": 0,
    }
    authorization = {
        **authorization_material,
        "authorization_digest": canonical_sha256(authorization_material),
    }
    common = {
        "execution_delta_manifest_digest": expected["execution_delta_manifest_digest"],
        "all_arm_seal_protocol_digest": expected["all_arm_seal_protocol_digest"],
        "readiness_source_manifest_digest": expected[
            "readiness_source_manifest_digest"
        ],
        "case_order_digest": expected["case_order_digest"],
        "config_set_digest": expected["e1_config_set_digest"],
        "input_binding_digest": expected["e1_common_pool_binding_digest"],
        "caps_digest": expected["e1_caps_digest"],
        "cost_ledger_schema_digest": expected["cost_ledger_schema_digest"],
        "final_k": 8,
    }
    bundle = generate_e1_all_arm_bundle(
        configs=configs,
        action_manifest=action_manifest,
        official_probe_collection=probes,
        product_traces=product,
        common_execution_bindings=common,
        independent_authorization=authorization,
        expected_authorization_bindings=expected,
        frozen_case_order=synthetic_case_order,
        generator_source_sha256=expected["s3a_generator_source_sha256"],
        sealer_source_sha256=expected["s3a_sealer_source_sha256"],
        runner_source_sha256=expected["s3a_runner_source_sha256"],
    )
    assert list(bundle["arm_outputs"]) == list(E1_ARM_ORDER)
    assert len(bundle["arm_outputs"]) == 11
    assert bundle["e1_all_arm_seal"]["schema"] == "milai.dg25.e1-all-arm-seal.v0.2"
    assert bundle["e1_all_arm_seal"]["arm_output_set_digest"] == canonical_sha256(
        bundle["e1_all_arm_seal"]["arm_output_content_digests"]
    )
    r0 = bundle["arm_outputs"]["R0"]
    r0p = bundle["arm_outputs"]["R0P"]
    for baseline_record, plan_record in zip(
        r0["records"], r0p["records"], strict=True
    ):
        assert baseline_record["query_id"] == plan_record["query_id"]
        assert baseline_record["query_identity"] == plan_record["query_identity"]
        for baseline, planned in zip(
            baseline_record["requirements"],
            plan_record["requirements"],
            strict=True,
        ):
            assert baseline["requirement_id"] == planned["requirement_id"]
            assert baseline["active_action_digests"] == planned[
                "active_action_digests"
            ]
            assert baseline["action_plan_digest"] != planned["action_plan_digest"]
            for field in (
                "selected_occurrences",
                "proof_obligations",
                "sufficiency",
            ):
                assert baseline[field] == planned[field]
    assert r0["cost_ledger"] == r0p["cost_ledger"]


def _occurrence(
    occurrence_id: str,
    evidence_id: str,
    channel: str,
    rank: int,
    *,
    roles: list[str],
    requirement_id: str = "REQ",
) -> ReplayOccurrenceV01:
    return ReplayOccurrenceV01(
        occurrence_id=occurrence_id,
        evidence_id=evidence_id,
        source_turn_ref=f"synthetic://{evidence_id}",
        requirement_id=requirement_id,
        channel=channel,
        channel_rank=rank,
        legal=True,
        direct_lexical_match=True,
        synonym_lexical_match=False,
        matched_roles=roles,
        binding_status="MATCH",
    )


def _positive_pre_score_observations(
    expected_bindings: dict[str, Any],
) -> dict[str, Any]:
    values: dict[str, Any] = dict(expected_bindings)
    values.update(
        {
            "identity_drift": 0,
            "label_before_seal": 0,
            "pool_k_mismatch": 0,
            "invalid_plan_count": 0,
            "budget_overflow": 0,
            "boundary_drift": 0,
            "forbidden_calls": 0,
            "post_score_adaptation": 0,
            "accepted_binding_precision": None,
            "wrong_complete": None,
            "e1_all_arm_seal_present": True,
            "e2_all_arm_seal_present": True,
            "combined_all_arm_seal_present": True,
            "all_arm_output_count": 16,
            "independent_scoring_authorized": True,
            "automatic_retries": 0,
            "stage": "S4B_PRE_SCORE",
            "labels_loaded": False,
            "scoring_executed": False,
        }
    )
    return values


def _synthetic_registries() -> tuple[dict[str, Any], dict[str, Any]]:
    gold_queries = []
    proof_queries = []
    group_index = 0
    proof_index = 0
    for query_index in range(10):
        group_count = 3 if query_index < 3 else 2
        proof_count = 4 if query_index < 7 else 3
        groups = []
        for _ in range(group_count):
            groups.append(
                {
                    "equivalence_group_id": f"group-{group_index}",
                    "source_turn_ref": f"synthetic://source-{group_index}",
                }
            )
            group_index += 1
        obligations = []
        for _ in range(proof_count):
            obligations.append(
                {
                    "obligation_id": f"REQ:proof-{proof_index}",
                    "kind": "ACCESS_SNAPSHOT",
                    "required": True,
                }
            )
            proof_index += 1
        gold_queries.append(
            {
                "query_id": f"query-{query_index}",
                "requirements": [
                    {
                        "requirement_id": "REQ",
                        "evidence_roles": [
                            {"role": "ROLE", "equivalence_groups": groups}
                        ],
                    }
                ],
            }
        )
        proof_queries.append(
            {
                "query_id": f"query-{query_index}",
                "requirements": [
                    {"requirement_id": "REQ", "obligations": obligations}
                ],
            }
        )
    assert group_index == 23
    assert proof_index == 37
    return (
        {
            "schema_version": "gold-equivalence-registry-v0.1",
            "scorer_only": True,
            "queries": gold_queries,
        },
        {
            "schema_version": "proof-obligation-registry-v0.1",
            "scorer_only": True,
            "queries": proof_queries,
        },
    )


def _synthetic_arm_records(
    gold: dict[str, Any],
    proof: dict[str, Any],
) -> list[dict[str, Any]]:
    proof_by_query = {
        item["query_id"]: item["requirements"][0]["obligations"]
        for item in proof["queries"]
    }
    records = []
    for query in gold["queries"]:
        groups = query["requirements"][0]["evidence_roles"][0]["equivalence_groups"]
        records.append(
            {
                "query_id": query["query_id"],
                "requirements": [
                    {
                        "requirement_id": "REQ",
                        "selected_occurrences": [
                            {
                                "occurrence_id": f"occ-{group['equivalence_group_id']}",
                                "evidence_id": f"evidence-{group['equivalence_group_id']}",
                                "source_turn_ref": group["source_turn_ref"],
                                "legal": True,
                                "binding_status": "MATCH",
                                "range_membership": "IN_RANGE",
                                "event_identity_digest": canonical_sha256(
                                    group["equivalence_group_id"]
                                ),
                            }
                            for group in groups
                        ],
                        "proof_obligations": [
                            {"obligation_id": item["obligation_id"], "status": "SATISFIED"}
                            for item in proof_by_query[query["query_id"]]
                        ],
                        "sufficiency": "COMPLETE",
                    }
                ],
            }
        )
    return records


def _synthetic_s3a_inputs() -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    identities: list[dict[str, Any]] = []
    probe_records: list[dict[str, Any]] = []
    requirements_by_case: dict[str, list[dict[str, Any]]] = {
        f"synthetic-case-{index:02d}": [] for index in range(10)
    }
    obligations_by_case: dict[str, list[dict[str, Any]]] = {
        case_id: [] for case_id in requirements_by_case
    }
    lifecycles_by_case: dict[str, list[dict[str, Any]]] = {
        case_id: [] for case_id in requirements_by_case
    }
    channels = (
        "FTS_RAW",
        "FTS_ENRICHED",
        "EVIDENCE_DENSE",
        "SOURCE_OBSERVED_RANGE_SCAN",
        "TEMPORAL_EVENT",
    )
    for index in range(15):
        case_id = f"synthetic-case-{index % 10:02d}"
        requirement_id = f"REQ_{index:02d}"
        proof_required = index < 2
        lifecycles = []
        for channel in channels:
            executable = channel in {"FTS_RAW", "EVIDENCE_DENSE"} or (
                proof_required and channel == "TEMPORAL_EVENT"
            )
            disposition = "EXECUTED" if executable else "NOT_INVOKED"
            identities.append(
                {
                    "case_id": case_id,
                    "requirement_id": requirement_id,
                    "channel": channel,
                    "disposition": disposition,
                    "query_digest": canonical_sha256(
                        f"{case_id}:{requirement_id}:{channel}:query"
                    ),
                    "request_identity": canonical_sha256(f"{case_id}:request"),
                    "snapshot_identity": canonical_sha256(f"{case_id}:snapshot"),
                    "scope_digest": canonical_sha256(f"{case_id}:scope"),
                }
            )
            returned = []
            if executable:
                evidence_id = f"{case_id}-{channel}-evidence"
                occurrence_id = canonical_sha256(f"{case_id}:{channel}:occurrence")
                returned = [
                    {
                        "occurrence_id": occurrence_id,
                        "requirement_id": requirement_id,
                        "channel": channel,
                        "raw_rank": 1,
                        "evidence_record_identity": {
                            "evidence_id": evidence_id,
                            "source_ref": f"synthetic://{case_id}/{channel}",
                        },
                    }
                ]
                lifecycles.append(
                    {
                        "candidate_identity": evidence_id,
                        "requirement_candidates": [requirement_id],
                        "lifecycle": [
                            {"stage_id": "S31", "disposition": "KEPT"},
                            {"stage_id": "S42", "disposition": "KEPT"},
                        ],
                    }
                )
            probe_records.append(
                {
                    "case_id": case_id,
                    "trace": {
                        "requirement_id": requirement_id,
                        "channel": channel,
                        "disposition": disposition,
                        "returned_occurrences": returned,
                    },
                }
            )
        proof_obligations = [
            {
                "requirement_id": requirement_id,
                "obligation_id": f"{requirement_id}:"
                + ("BOUNDED_RANGE_SCAN" if proof_required else "ACCESS_SNAPSHOT"),
                "kind": "BOUNDED_RANGE_SCAN" if proof_required else "ACCESS_SNAPSHOT",
                "proof_artifact": (
                    {"status": "COMPLETE"} if proof_required else None
                ),
            }
        ]
        requirements_by_case[case_id].append(
            {
                "requirement_id": requirement_id,
                "kind": "EVENT",
                "required": True,
            }
        )
        obligations_by_case[case_id].extend(proof_obligations)
        lifecycles_by_case[case_id].extend(lifecycles)
    product_records = [
        {
            "case_id": case_id,
            "trace": {
                "query_identity": canonical_sha256(f"{case_id}:query-identity"),
                "requirements": requirements_by_case[case_id],
                "proof_obligations": obligations_by_case[case_id],
                "candidate_lifecycles": lifecycles_by_case[case_id],
            },
        }
        for case_id in requirements_by_case
    ]
    return (
        identities,
        {"schema": "synthetic-probes", "records": probe_records},
        {"schema": "synthetic-product", "records": product_records},
    )


def _synthetic_sealed_outputs(
    gold: dict[str, Any],
    proof: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    e1_configs = {arm_id: canonical_sha256(f"config:{arm_id}") for arm_id in E1_ARM_ORDER}
    e2_configs = {arm_id: canonical_sha256(f"config:{arm_id}") for arm_id in E2_ARM_ORDER}
    ledger_contract = cost_ledger_schema()
    readiness: dict[str, Any] = {
        field: canonical_sha256(f"binding:{field}")
        for field in scorer_contract()["required_execution_bindings"]
        if field != "final_k"
    }
    readiness.update(
        {
            "e1_config_set_digest": canonical_sha256(e1_configs),
            "e2_config_set_digest": canonical_sha256(e2_configs),
            "cost_ledger_schema_digest": ledger_contract["cost_ledger_schema_digest"],
            "final_k": 8,
        }
    )
    ledger: dict[str, Any] = {field: 0 for field in COST_LEDGER_FIELDS}
    ledger["latency_ms"] = None
    records = _synthetic_arm_records(gold, proof)
    outputs: dict[str, dict[str, Any]] = {}
    e1_inputs: dict[str, dict[str, Any]] = {}
    e2_inputs: dict[str, dict[str, Any]] = {}
    block_configs: tuple[tuple[ArmBlock, dict[str, str]], ...] = (
        ("E1", e1_configs),
        ("E2", e2_configs),
    )
    for block, config_map in block_configs:
        common = {
            "execution_delta_manifest_digest": readiness[
                "execution_delta_manifest_digest"
            ],
            "all_arm_seal_protocol_digest": readiness[
                "all_arm_seal_protocol_digest"
            ],
            "readiness_source_manifest_digest": readiness[
                "readiness_source_manifest_digest"
            ],
            "case_order_digest": readiness["case_order_digest"],
            "config_set_digest": readiness[
                "e1_config_set_digest" if block == "E1" else "e2_config_set_digest"
            ],
            "input_binding_digest": readiness[
                "e1_common_pool_binding_digest"
                if block == "E1"
                else "e2_common_input_digest"
            ],
            "caps_digest": readiness[
                "e1_caps_digest" if block == "E1" else "e2_caps_digest"
            ],
            "cost_ledger_schema_digest": readiness["cost_ledger_schema_digest"],
            "final_k": 8,
        }
        for arm_id, config_digest in config_map.items():
            block_input = (
                {"e1_action_manifest_digest": readiness["e1_action_manifest_digest"]}
                if block == "E1"
                else {"e2_common_input_digest": readiness["e2_common_input_digest"]}
            )
            (e1_inputs if block == "E1" else e2_inputs)[arm_id] = block_input
            outputs[arm_id] = build_label_free_arm_output(
                block=block,
                arm_id=arm_id,
                arm_config_digest=config_digest,
                common_execution_bindings=common,
                block_input_identity=block_input,
                records=records,
                cost_ledger=ledger,
            )
    e1_common = dict(outputs[E1_ARM_ORDER[0]]["execution_binding"])
    for field in (
        "schema",
        "block",
        "arm_id",
        "arm_config_digest",
        "block_input_identity",
        "execution_binding_digest",
    ):
        e1_common.pop(field)
    e2_common = dict(outputs[E2_ARM_ORDER[0]]["execution_binding"])
    for field in (
        "schema",
        "block",
        "arm_id",
        "arm_config_digest",
        "block_input_identity",
        "execution_binding_digest",
    ):
        e2_common.pop(field)
    e1_seal = build_block_all_arm_seal(
        block="E1",
        arm_outputs={arm_id: outputs[arm_id] for arm_id in E1_ARM_ORDER},
        arm_order=E1_ARM_ORDER,
        config_digests=e1_configs,
        common_execution_bindings=e1_common,
        block_input_identities=e1_inputs,
        generator_source_sha256="1" * 64,
        sealer_source_sha256="2" * 64,
        runner_source_sha256="3" * 64,
        independent_authorization_digest="4" * 64,
    )
    e2_seal = build_block_all_arm_seal(
        block="E2",
        arm_outputs={arm_id: outputs[arm_id] for arm_id in E2_ARM_ORDER},
        arm_order=E2_ARM_ORDER,
        config_digests=e2_configs,
        common_execution_bindings=e2_common,
        block_input_identities=e2_inputs,
        generator_source_sha256="5" * 64,
        sealer_source_sha256="2" * 64,
        runner_source_sha256="6" * 64,
        independent_authorization_digest="7" * 64,
    )
    ordered_outputs = {
        arm_id: outputs[arm_id] for arm_id in (*E1_ARM_ORDER, *E2_ARM_ORDER)
    }
    combined = build_combined_all_arm_seal(
        e1_seal=e1_seal,
        e2_seal=e2_seal,
        arm_outputs=ordered_outputs,
        readiness_bindings=readiness,
    )
    return ordered_outputs, combined, readiness
