"""Presealed, label-free DG-25 S3A E1 all-arm generator.

This module is deliberately filesystem-free.  It consumes only already-sealed
channel occurrences, label-free predecessor lifecycle traces, exact arm/action
contracts, and an independent authorization mapping supplied by the runner.
It has no repository, Reader, Provider, model, controller, scorer, or label
entry point.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from milai.domain.requirement_state import canonical_sha256

from evals.dg25.arm_sealing import (
    COST_LEDGER_FIELDS,
    E1_ARM_ORDER,
    build_block_all_arm_seal,
    build_label_free_arm_output,
    validate_block_all_arm_seal,
)
from evals.dg25.routing_ablation import (
    E1ArmConfigV01,
    E1RequirementActionPlanV01,
    ReplayOccurrenceV01,
    build_e1_requirement_action_plan,
    build_replay_action,
    select_label_free_occurrences,
    validate_e1_requirement_action_plan,
)


def build_e1_action_manifest(
    *,
    configs: Sequence[E1ArmConfigV01],
    exact_channel_query_identities: Sequence[Mapping[str, Any]],
    official_probe_collection: Mapping[str, Any],
    official_probe_identity: Mapping[str, Any],
    product_traces: Mapping[str, Any],
    product_trace_identity: Mapping[str, Any],
    pool_binding_digest: str,
    frozen_case_order: Sequence[str],
) -> dict[str, Any]:
    """Freeze all 11 x 15 action vectors without selecting occurrences."""

    if [item.arm_id for item in configs] != list(E1_ARM_ORDER):
        raise ValueError("DG25_E1_ACTION_MANIFEST_CONFIG_ORDER_MISMATCH")
    case_order = _validate_frozen_case_order(frozen_case_order)
    _validate_source_case_orders(
        case_order=case_order,
        channel_query_identities=exact_channel_query_identities,
        official_probe_collection=official_probe_collection,
        product_traces=product_traces,
    )
    identity_index = _channel_identity_index(exact_channel_query_identities)
    probe_index = _probe_index(official_probe_collection)
    requirement_rows = _requirement_rows(product_traces, case_order=case_order)
    plans: list[dict[str, Any]] = []
    for config in configs:
        for row in requirement_rows:
            case_id = str(row["case_id"])
            requirement_id = str(row["requirement_id"])
            channel_rows = {
                channel: identity_index[(case_id, requirement_id, channel)]
                for channel in (
                    "FTS_RAW",
                    "FTS_ENRICHED",
                    "EVIDENCE_DENSE",
                    "SOURCE_OBSERVED_RANGE_SCAN",
                    "TEMPORAL_EVENT",
                )
            }
            baseline_probe = probe_index[(case_id, requirement_id, "FTS_RAW")]
            baseline = _action_from_identity(
                identity=channel_rows["FTS_RAW"],
                action_kind="BASELINE_DISCOVERY",
                returned_occurrence_count=len(
                    _mapping_sequence(
                        baseline_probe.get("returned_occurrences"),
                        "baseline returned occurrences",
                    )
                ),
            )
            proof_required = bool(row["proof_required"])
            available_proof = [
                channel
                for channel in config.proof_channel_priority
                if _identity_executable(channel_rows[channel])
            ]
            available_optional = [
                channel
                for channel in config.optional_channel_priority
                if _identity_executable(channel_rows[channel])
            ]
            proof = None
            if proof_required and config.unified_proof_first:
                if not available_proof:
                    raise ValueError("DG25_REQUIRED_PROOF_CHANNEL_UNAVAILABLE")
                proof_probe = probe_index[
                    (case_id, requirement_id, available_proof[0])
                ]
                proof = _action_from_identity(
                    identity=channel_rows[available_proof[0]],
                    action_kind="REQUIRED_PROOF_CLOSURE",
                    returned_occurrence_count=len(
                        _mapping_sequence(
                            proof_probe.get("returned_occurrences"),
                            "proof returned occurrences",
                        )
                    ),
                )
            occupied = {baseline.channel, *([proof.channel] if proof is not None else [])}
            eligible_optional = [
                channel for channel in available_optional if channel not in occupied
            ]
            remaining_budget = config.max_actions_per_plan - (1 + (proof is not None))
            optional = None
            if not config.optional_channel_union:
                optional_disposition = "OPTIONAL_CHANNEL_UNION_DISABLED"
            elif remaining_budget == 0 and eligible_optional:
                optional_disposition = "BUDGET_NOT_AUTHORIZED"
            elif eligible_optional:
                optional_disposition = "SELECTED"
                optional_probe = probe_index[
                    (case_id, requirement_id, eligible_optional[0])
                ]
                optional = _action_from_identity(
                    identity=channel_rows[eligible_optional[0]],
                    action_kind="OPTIONAL_DISCOVERY",
                    returned_occurrence_count=len(
                        _mapping_sequence(
                            optional_probe.get("returned_occurrences"),
                            "optional returned occurrences",
                        )
                    ),
                )
            else:
                optional_disposition = "NO_EXECUTABLE_OPTIONAL_CHANNEL"
            active = [baseline, *([proof] if proof is not None else [])]
            if optional is not None:
                active.append(optional)
            plan = build_e1_requirement_action_plan(
                arm_id=config.arm_id,
                arm_config_digest=config.config_digest,
                case_id=case_id,
                query_identity=str(row["query_identity"]),
                requirement_id=requirement_id,
                required_roles=[requirement_id],
                proof_required=proof_required,
                available_proof_channels=available_proof,
                available_optional_channels=available_optional,
                baseline_action=baseline,
                proof_action=proof,
                optional_action=optional,
                optional_action_disposition=optional_disposition,
                active_action_digests=[item.action_digest for item in active],
            )
            validate_e1_requirement_action_plan(
                plan=plan,
                config=config,
                expected_plan_digest=plan.plan_digest,
            )
            plans.append(plan.model_dump(mode="json"))

    plan_index = {
        _plan_key(item): str(item["plan_digest"])
        for item in plans
    }
    if len(plan_index) != len(plans):
        raise ValueError("DG25_E1_ACTION_MANIFEST_DUPLICATE_PLAN_KEY")
    material: dict[str, Any] = {
        "schema": "milai.dg25.e1-action-role-manifest.v0.1",
        "arm_order": list(E1_ARM_ORDER),
        "arm_config_digests": {
            item.arm_id: item.config_digest for item in configs
        },
        "case_order": case_order,
        "case_order_digest": canonical_sha256(case_order),
        "query_requirement_order": [
            {
                "case_id": str(item["case_id"]),
                "requirement_id": str(item["requirement_id"]),
            }
            for item in requirement_rows
        ],
        "query_requirement_order_digest": canonical_sha256(
            [
                {
                    "case_id": str(item["case_id"]),
                    "requirement_id": str(item["requirement_id"]),
                }
                for item in requirement_rows
            ]
        ),
        "pool_binding_digest": pool_binding_digest,
        "official_probe_collection": dict(official_probe_identity),
        "product_trace_collection": dict(product_trace_identity),
        "query_requirement_count": len(requirement_rows),
        "plan_count": len(plans),
        "expected_plan_count": len(E1_ARM_ORDER) * len(requirement_rows),
        "plans": plans,
        "plan_index": plan_index,
        "plan_index_digest": canonical_sha256(plan_index),
        "role_derivation": {
            "BASELINE_DISCOVERY": "EVIDENCE_DISCOVERY",
            "REQUIRED_PROOF_CLOSURE": "PROOF_CLOSURE",
            "OPTIONAL_DISCOVERY": "EVIDENCE_DISCOVERY",
            "caller_supplied_action_role": False,
        },
        "proof_required_source": "SEALED_PRODUCT_BOUNDED_RANGE_SCAN_OBLIGATION",
        "optional_selection": "FIRST_EXECUTABLE_PREREGISTERED_PRIORITY_WITHIN_BUDGET",
        "labels_loaded": False,
        "occurrence_selection_executed": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "automatic_retries": 0,
    }
    material["manifest_digest"] = canonical_sha256(material)
    validate_e1_action_manifest(
        manifest=material,
        configs=configs,
        pool_binding_digest=pool_binding_digest,
        expected_case_order=case_order,
    )
    return material


def validate_e1_action_manifest(
    *,
    manifest: Mapping[str, Any],
    configs: Sequence[E1ArmConfigV01],
    pool_binding_digest: str,
    expected_case_order: Sequence[str],
) -> None:
    if manifest.get("schema") != "milai.dg25.e1-action-role-manifest.v0.1":
        raise ValueError("DG25_E1_ACTION_MANIFEST_SCHEMA_INVALID")
    if manifest.get("arm_order") != list(E1_ARM_ORDER):
        raise ValueError("DG25_E1_ACTION_MANIFEST_ARM_ORDER_DRIFT")
    expected_configs = {item.arm_id: item.config_digest for item in configs}
    if manifest.get("arm_config_digests") != expected_configs:
        raise ValueError("DG25_E1_ACTION_MANIFEST_CONFIG_DRIFT")
    if manifest.get("pool_binding_digest") != pool_binding_digest:
        raise ValueError("DG25_E1_ACTION_MANIFEST_POOL_DRIFT")
    case_order = _validate_frozen_case_order(expected_case_order)
    if manifest.get("case_order") != case_order:
        raise ValueError("DG25_E1_ACTION_MANIFEST_CASE_ORDER_DRIFT")
    if manifest.get("case_order_digest") != canonical_sha256(case_order):
        raise ValueError("DG25_E1_ACTION_MANIFEST_CASE_ORDER_DIGEST_MISMATCH")
    for field in ("official_probe_collection", "product_trace_collection"):
        source = _mapping(manifest.get(field), f"{field} identity")
        if (
            not isinstance(source.get("path"), str)
            or not isinstance(source.get("sha256"), str)
            or len(str(source["sha256"])) != 64
            or not isinstance(source.get("size"), int)
        ):
            raise ValueError("DG25_E1_ACTION_MANIFEST_SOURCE_IDENTITY_INVALID")
    plans = _mapping_sequence(manifest.get("plans"), "E1 action plans")
    expected_plan_count = len(E1_ARM_ORDER) * int(manifest["query_requirement_count"])
    if len(plans) != expected_plan_count or manifest.get("plan_count") != len(plans):
        raise ValueError("DG25_E1_ACTION_MANIFEST_PLAN_COUNT_MISMATCH")
    config_by_id = {item.arm_id: item for item in configs}
    observed_index: dict[str, str] = {}
    identities_by_arm: dict[str, set[tuple[str, str]]] = {
        arm_id: set() for arm_id in E1_ARM_ORDER
    }
    ordered_identities_by_arm: dict[str, list[tuple[str, str]]] = {
        arm_id: [] for arm_id in E1_ARM_ORDER
    }
    for raw in plans:
        plan = E1RequirementActionPlanV01.model_validate(raw)
        config = config_by_id.get(plan.arm_id)
        if config is None:
            raise ValueError("DG25_E1_ACTION_MANIFEST_UNKNOWN_ARM")
        validate_e1_requirement_action_plan(
            plan=plan,
            config=config,
            expected_plan_digest=plan.plan_digest,
        )
        key = _plan_key(raw)
        if key in observed_index:
            raise ValueError("DG25_E1_ACTION_MANIFEST_DUPLICATE_PLAN_KEY")
        observed_index[key] = plan.plan_digest
        arm_identities = identities_by_arm[plan.arm_id]
        arm_identities.add((plan.case_id, plan.requirement_id))
        ordered_arm_identities = ordered_identities_by_arm[plan.arm_id]
        ordered_arm_identities.append((plan.case_id, plan.requirement_id))
    baseline_identities = identities_by_arm["R0"]
    if any(values != baseline_identities for values in identities_by_arm.values()):
        raise ValueError("DG25_E1_ACTION_MANIFEST_UNMATCHED_REQUIREMENT_SET")
    declared_order = _mapping_sequence(
        manifest.get("query_requirement_order"), "query-requirement order"
    )
    ordered_pairs = [
        (str(item["case_id"]), str(item["requirement_id"]))
        for item in declared_order
    ]
    if any(values != ordered_pairs for values in ordered_identities_by_arm.values()):
        raise ValueError("DG25_E1_ACTION_MANIFEST_PLAN_ORDER_DRIFT")
    if _first_seen([case_id for case_id, _ in ordered_pairs]) != case_order:
        raise ValueError("DG25_E1_ACTION_MANIFEST_CASE_ORDER_DRIFT")
    for case_id in case_order:
        requirement_ids = [
            requirement_id
            for observed_case_id, requirement_id in ordered_pairs
            if observed_case_id == case_id
        ]
        if requirement_ids != sorted(requirement_ids):
            raise ValueError("DG25_E1_ACTION_MANIFEST_REQUIREMENT_ORDER_DRIFT")
    if manifest.get("query_requirement_order_digest") != canonical_sha256(
        [dict(item) for item in declared_order]
    ):
        raise ValueError("DG25_E1_ACTION_MANIFEST_QUERY_ORDER_DIGEST_MISMATCH")
    if manifest.get("plan_index") != observed_index:
        raise ValueError("DG25_E1_ACTION_MANIFEST_INDEX_MISMATCH")
    if manifest.get("plan_index_digest") != canonical_sha256(observed_index):
        raise ValueError("DG25_E1_ACTION_MANIFEST_INDEX_DIGEST_MISMATCH")
    material = dict(manifest)
    observed_digest = material.pop("manifest_digest", None)
    if observed_digest != canonical_sha256(material):
        raise ValueError("DG25_E1_ACTION_MANIFEST_DIGEST_MISMATCH")


def generate_e1_all_arm_bundle(
    *,
    configs: Sequence[E1ArmConfigV01],
    action_manifest: Mapping[str, Any],
    official_probe_collection: Mapping[str, Any],
    product_traces: Mapping[str, Any],
    common_execution_bindings: Mapping[str, Any],
    independent_authorization: Mapping[str, Any],
    expected_authorization_bindings: Mapping[str, Any],
    frozen_case_order: Sequence[str],
    generator_source_sha256: str,
    sealer_source_sha256: str,
    runner_source_sha256: str,
) -> dict[str, Any]:
    """Generate exactly 11 outputs in memory, then create one E1 seal."""

    validate_s3a_authorization(
        authorization=independent_authorization,
        expected_bindings=expected_authorization_bindings,
    )
    case_order = _validate_frozen_case_order(frozen_case_order)
    case_order_digest = canonical_sha256(case_order)
    if common_execution_bindings.get("case_order_digest") != case_order_digest:
        raise ValueError("DG25_S3A_COMMON_BINDING_CASE_ORDER_DRIFT")
    _validate_source_case_orders(
        case_order=case_order,
        channel_query_identities=None,
        official_probe_collection=official_probe_collection,
        product_traces=product_traces,
    )
    validate_e1_action_manifest(
        manifest=action_manifest,
        configs=configs,
        pool_binding_digest=str(common_execution_bindings["input_binding_digest"]),
        expected_case_order=case_order,
    )
    probe_index = _probe_index(official_probe_collection)
    lifecycle_index = _lifecycle_index(product_traces)
    proof_index = _proof_index(product_traces)
    plans_by_arm = _plans_by_arm(action_manifest)
    arm_outputs: dict[str, dict[str, Any]] = {}
    block_inputs: dict[str, dict[str, Any]] = {}
    for config in configs:
        records, ledger = _generate_one_arm(
            config=config,
            plans=plans_by_arm[config.arm_id],
            probe_index=probe_index,
            lifecycle_index=lifecycle_index,
            proof_index=proof_index,
        )
        plan_digest_map = {
            f"{plan.case_id}::{plan.requirement_id}": plan.plan_digest
            for plan in plans_by_arm[config.arm_id]
        }
        block_input = {
            "e1_action_manifest_digest": str(action_manifest["manifest_digest"]),
            "arm_action_plan_set_digest": canonical_sha256(plan_digest_map),
            "case_order_digest": case_order_digest,
        }
        block_inputs[config.arm_id] = block_input
        arm_outputs[config.arm_id] = build_label_free_arm_output(
            block="E1",
            arm_id=config.arm_id,
            arm_config_digest=config.config_digest,
            common_execution_bindings=common_execution_bindings,
            block_input_identity=block_input,
            records=records,
            cost_ledger=ledger,
        )
    _validate_r0_r0p_compatibility(arm_outputs)
    _validate_all_arm_case_order(arm_outputs, expected_case_order=case_order)
    config_digests = {item.arm_id: item.config_digest for item in configs}
    authorization_digest = str(independent_authorization["authorization_digest"])
    seal = build_block_all_arm_seal(
        block="E1",
        arm_outputs=arm_outputs,
        arm_order=E1_ARM_ORDER,
        config_digests=config_digests,
        common_execution_bindings=common_execution_bindings,
        block_input_identities=block_inputs,
        generator_source_sha256=generator_source_sha256,
        sealer_source_sha256=sealer_source_sha256,
        runner_source_sha256=runner_source_sha256,
        independent_authorization_digest=authorization_digest,
    )
    validate_block_all_arm_seal(
        seal=seal,
        block="E1",
        arm_outputs=arm_outputs,
        arm_order=E1_ARM_ORDER,
        config_digests=config_digests,
        common_execution_bindings=common_execution_bindings,
        block_input_identities=block_inputs,
    )
    return {
        "schema": "milai.dg25.e1-label-free-all-arm-bundle.v0.1",
        "arm_order": list(E1_ARM_ORDER),
        "case_order": case_order,
        "case_order_digest": case_order_digest,
        "arm_outputs": arm_outputs,
        "e1_all_arm_seal": seal,
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "automatic_retries": 0,
    }


def _validate_r0_r0p_compatibility(
    arm_outputs: Mapping[str, Mapping[str, Any]],
) -> None:
    """Require semantic equality while preserving arm-bound plan provenance."""

    r0 = _mapping(arm_outputs.get("R0"), "R0 arm output")
    r0p = _mapping(arm_outputs.get("R0P"), "R0P arm output")
    if _semantic_record_projection(r0) != _semantic_record_projection(r0p):
        raise ValueError("DG25_R0_R0P_SEMANTIC_EQUIVALENCE_MISMATCH")
    if r0.get("cost_ledger") != r0p.get("cost_ledger"):
        raise ValueError("DG25_R0_R0P_COST_EQUIVALENCE_MISMATCH")

    r0_records = _mapping_sequence(r0.get("records"), "R0 records")
    r0p_records = _mapping_sequence(r0p.get("records"), "R0P records")
    for baseline_record, plan_record in zip(r0_records, r0p_records, strict=True):
        baseline_requirements = _mapping_sequence(
            baseline_record.get("requirements"), "R0 requirements"
        )
        plan_requirements = _mapping_sequence(
            plan_record.get("requirements"), "R0P requirements"
        )
        for baseline, planned in zip(
            baseline_requirements, plan_requirements, strict=True
        ):
            if baseline.get("active_action_digests") != planned.get(
                "active_action_digests"
            ):
                raise ValueError("DG25_R0_R0P_ACTION_DIGEST_MISMATCH")
            if baseline.get("action_plan_digest") == planned.get(
                "action_plan_digest"
            ):
                raise ValueError("DG25_R0_R0P_ARM_PLAN_BINDING_MISSING")


def _semantic_record_projection(output: Mapping[str, Any]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for record in _mapping_sequence(output.get("records"), "arm records"):
        requirements: list[dict[str, Any]] = []
        for requirement in _mapping_sequence(
            record.get("requirements"), "arm requirements"
        ):
            requirements.append(
                {
                    "requirement_id": requirement.get("requirement_id"),
                    "selected_occurrences": requirement.get("selected_occurrences"),
                    "proof_obligations": requirement.get("proof_obligations"),
                    "sufficiency": requirement.get("sufficiency"),
                }
            )
        projected.append(
            {
                "query_id": record.get("query_id"),
                "query_identity": record.get("query_identity"),
                "requirements": requirements,
            }
        )
    return projected


def validate_s3a_authorization(
    *,
    authorization: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> None:
    if authorization.get("schema") != "milai.dg25.s3a-independent-authorization.v0.1":
        raise ValueError("DG25_S3A_AUTHORIZATION_SCHEMA_INVALID")
    if authorization.get("authorized") is not True:
        raise ValueError("DG25_S3A_NOT_AUTHORIZED")
    if authorization.get("scope") != "S3A_E1_LABEL_FREE_ALL_11_ARMS_AND_ONE_SEAL":
        raise ValueError("DG25_S3A_AUTHORIZATION_SCOPE_INVALID")
    if authorization.get("readiness_bindings") != dict(expected_bindings):
        raise ValueError("DG25_S3A_AUTHORIZATION_BINDING_MISMATCH")
    if authorization.get("readiness_bindings_digest") != canonical_sha256(
        dict(expected_bindings)
    ):
        raise ValueError("DG25_S3A_AUTHORIZATION_BINDING_DIGEST_MISMATCH")
    authorization_boundaries = {
        "labels_authorized": False,
        "scoring_authorized": False,
        "s4a_authorized": False,
        "s4b_authorized": False,
        "e3_authorized": False,
        "reader_model_provider_controller_calls_authorized": 0,
        "formal_holdout_authorized": False,
        "automatic_retries": 0,
    }
    for field, expected in authorization_boundaries.items():
        if authorization.get(field) != expected:
            raise ValueError("DG25_S3A_AUTHORIZATION_BOUNDARY_INVALID")
    material = dict(authorization)
    observed = material.pop("authorization_digest", None)
    if observed != canonical_sha256(material):
        raise ValueError("DG25_S3A_AUTHORIZATION_DIGEST_MISMATCH")


def _generate_one_arm(
    *,
    config: E1ArmConfigV01,
    plans: Sequence[E1RequirementActionPlanV01],
    probe_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    lifecycle_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    proof_index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records_by_query: dict[str, dict[str, Any]] = {}
    logical_actions = 0
    returned_rows = 0
    selected_count = 0
    bound_count = 0
    range_rows = 0
    for plan in plans:
        per_channel: dict[str, list[ReplayOccurrenceV01]] = {}
        raw_evidence = _evidence_ids(
            probe_index[(plan.case_id, plan.requirement_id, "FTS_RAW")]
        )
        enriched_evidence = _evidence_ids(
            probe_index[(plan.case_id, plan.requirement_id, "FTS_ENRICHED")]
        )
        for action in plan.active_actions:
            trace = probe_index[(plan.case_id, plan.requirement_id, action.channel)]
            occurrences = _mapping_sequence(
                trace.get("returned_occurrences"), "probe returned occurrences"
            )
            per_channel[action.channel] = [
                _project_occurrence(
                    case_id=plan.case_id,
                    requirement_id=plan.requirement_id,
                    raw=item,
                    raw_evidence=raw_evidence,
                    enriched_evidence=enriched_evidence,
                    lifecycle_index=lifecycle_index,
                )
                for item in occurrences
            ]
            returned_rows += len(occurrences)
            if action.action_kind == "REQUIRED_PROOF_CLOSURE":
                range_rows += len(occurrences)
        selected = select_label_free_occurrences(
            per_channel=per_channel,
            action_plan=plan,
            expected_action_plan_digest=plan.plan_digest,
            config=config,
        )
        proof_statuses = _proof_statuses(
            proof_index.get((plan.case_id, plan.requirement_id), []),
            proof_action_present=plan.proof_action is not None,
        )
        selected_rows = [
            {
                **item.model_dump(mode="json"),
                "legal": True,
                "range_membership": None,
                "event_identity_digest": None,
            }
            for item in selected
        ]
        selected_count += len(selected_rows)
        bound_count += sum(item["binding_status"] == "MATCH" for item in selected_rows)
        complete = bool(selected_rows) and all(
            item["status"] == "SATISFIED" for item in proof_statuses
        )
        query = records_by_query.setdefault(
            plan.case_id,
            {
                "query_id": plan.case_id,
                "query_identity": plan.query_identity,
                "requirements": [],
            },
        )
        query_requirements = query["requirements"]
        query_requirements.append(
            {
                "requirement_id": plan.requirement_id,
                "action_plan_digest": plan.plan_digest,
                "active_action_digests": plan.active_action_digests,
                "selected_occurrences": selected_rows,
                "proof_obligations": proof_statuses,
                "sufficiency": "COMPLETE" if complete else "PARTIAL",
            }
        )
        logical_actions += len(plan.active_actions)
    records = list(records_by_query.values())
    for record in records:
        record_requirements = record["requirements"]
        record_requirements.sort(key=lambda item: str(item["requirement_id"]))
    ledger: dict[str, Any] = {
        "logical_selected_actions": logical_actions,
        "physical_repository_calls": 0,
        "replayed_repository_calls": logical_actions,
        "returned_rows": returned_rows,
        "range_rows_scanned": range_rows,
        "candidates_returned": returned_rows,
        "candidates_hydrated": selected_count,
        "candidates_bound": bound_count,
        "candidates_shown_to_reader": 0,
        "state_passes": len(records),
        "reader_calls": 0,
        "latency_ms": None,
    }
    if set(ledger) != set(COST_LEDGER_FIELDS):
        raise AssertionError("DG25_INTERNAL_COST_LEDGER_SCHEMA_DRIFT")
    return records, ledger


def _project_occurrence(
    *,
    case_id: str,
    requirement_id: str,
    raw: Mapping[str, Any],
    raw_evidence: set[str],
    enriched_evidence: set[str],
    lifecycle_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> ReplayOccurrenceV01:
    evidence = _mapping(raw.get("evidence_record_identity"), "evidence identity")
    evidence_id = str(evidence["evidence_id"])
    lifecycle = lifecycle_index.get((case_id, requirement_id, evidence_id))
    binding_status: Literal["MATCH", "POSSIBLE", "NO_MATCH", "NOT_EVALUATED"] = (
        "NOT_EVALUATED"
    )
    legal = True
    matched_roles: list[str] = []
    if lifecycle is not None:
        candidates = [str(item) for item in lifecycle.get("requirement_candidates", [])]
        if requirement_id in candidates:
            matched_roles = [requirement_id]
        steps = _mapping_sequence(lifecycle.get("lifecycle"), "candidate lifecycle")
        gate = next((item for item in steps if item.get("stage_id") == "S31"), None)
        if gate is not None and gate.get("disposition") == "DROPPED":
            legal = False
        binding = next((item for item in steps if item.get("stage_id") == "S42"), None)
        if binding is not None:
            binding_status = (
                "MATCH" if binding.get("disposition") == "KEPT" else "NO_MATCH"
            )
    direct = evidence_id in raw_evidence
    synonym = evidence_id in enriched_evidence and not direct
    return ReplayOccurrenceV01(
        occurrence_id=str(raw["occurrence_id"]),
        evidence_id=evidence_id,
        source_turn_ref=str(evidence["source_ref"]),
        requirement_id=requirement_id,
        channel=str(raw["channel"]),
        channel_rank=int(raw["raw_rank"]),
        legal=legal,
        direct_lexical_match=direct,
        synonym_lexical_match=synonym,
        matched_roles=matched_roles,
        binding_status=binding_status,
    )


def _proof_statuses(
    obligations: Sequence[Mapping[str, Any]],
    *,
    proof_action_present: bool,
) -> list[dict[str, str]]:
    result = []
    for item in obligations:
        artifact = item.get("proof_artifact")
        satisfied = (
            proof_action_present
            and isinstance(artifact, Mapping)
            and artifact.get("status") == "COMPLETE"
        )
        result.append(
            {
                "obligation_id": str(item["obligation_id"]),
                "status": "SATISFIED" if satisfied else "NOT_SATISFIED",
            }
        )
    return result


def _validate_frozen_case_order(case_order: Sequence[str]) -> list[str]:
    frozen = [str(case_id) for case_id in case_order]
    if len(frozen) != 10 or len(set(frozen)) != len(frozen):
        raise ValueError("DG25_FROZEN_CASE_ORDER_INVALID")
    return frozen


def _validate_source_case_orders(
    *,
    case_order: Sequence[str],
    channel_query_identities: Sequence[Mapping[str, Any]] | None,
    official_probe_collection: Mapping[str, Any],
    product_traces: Mapping[str, Any],
) -> None:
    expected = list(case_order)
    product_order = [
        str(item["case_id"])
        for item in _mapping_sequence(product_traces.get("records"), "product records")
    ]
    if product_order != expected:
        raise ValueError("DG25_PRODUCT_TRACE_CASE_ORDER_DRIFT")
    probe_order = _first_seen(
        [
            str(item["case_id"])
            for item in _mapping_sequence(
                official_probe_collection.get("records"), "probe records"
            )
        ]
    )
    if probe_order != expected:
        raise ValueError("DG25_OFFICIAL_PROBE_CASE_ORDER_DRIFT")
    if channel_query_identities is not None:
        identity_order = _first_seen(
            [str(item["case_id"]) for item in channel_query_identities]
        )
        if identity_order != expected:
            raise ValueError("DG25_CHANNEL_QUERY_IDENTITY_CASE_ORDER_DRIFT")


def _validate_all_arm_case_order(
    arm_outputs: Mapping[str, Mapping[str, Any]],
    *,
    expected_case_order: Sequence[str],
) -> None:
    expected = list(expected_case_order)
    for arm_id in E1_ARM_ORDER:
        output = _mapping(arm_outputs.get(arm_id), f"{arm_id} arm output")
        observed = [
            str(item["query_id"])
            for item in _mapping_sequence(output.get("records"), f"{arm_id} records")
        ]
        if observed != expected:
            raise ValueError("DG25_E1_ARM_OUTPUT_CASE_ORDER_DRIFT")


def _first_seen(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _channel_identity_index(
    identities: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for item in identities:
        key = (str(item["case_id"]), str(item["requirement_id"]), str(item["channel"]))
        if key in result:
            raise ValueError("DG25_DUPLICATE_CHANNEL_QUERY_IDENTITY")
        result[key] = item
    if len(result) != 75:
        raise ValueError("DG25_CHANNEL_QUERY_IDENTITY_COUNT_MISMATCH")
    return result


def _requirement_rows(
    product_traces: Mapping[str, Any],
    *,
    case_order: Sequence[str],
) -> list[dict[str, Any]]:
    rows = []
    for record in _mapping_sequence(product_traces.get("records"), "product records"):
        trace = _mapping(record.get("trace"), "product trace")
        obligations = _mapping_sequence(trace.get("proof_obligations"), "proof obligations")
        proof_by_requirement: dict[str, bool] = {}
        for item in obligations:
            requirement_id = str(item["requirement_id"])
            proof_by_requirement[requirement_id] = proof_by_requirement.get(
                requirement_id, False
            ) or str(item["kind"]) == "BOUNDED_RANGE_SCAN"
        required_requirements = [
            item
            for item in _mapping_sequence(trace.get("requirements"), "requirements")
            if item.get("required") is True
        ]
        required_requirements.sort(key=lambda item: str(item["requirement_id"]))
        for requirement in required_requirements:
            requirement_id = str(requirement["requirement_id"])
            rows.append(
                {
                    "case_id": str(record["case_id"]),
                    "query_identity": str(trace["query_identity"]),
                    "requirement_id": requirement_id,
                    "proof_required": proof_by_requirement.get(requirement_id, False),
                }
            )
    if _first_seen([str(item["case_id"]) for item in rows]) != list(case_order):
        raise ValueError("DG25_E1_REQUIREMENT_CASE_ORDER_DRIFT")
    if len(rows) != 15:
        raise ValueError("DG25_E1_REQUIREMENT_DENOMINATOR_MISMATCH")
    return rows


def _action_from_identity(
    *,
    identity: Mapping[str, Any],
    action_kind: str,
    returned_occurrence_count: int,
) -> Any:
    if not _identity_executable(identity):
        raise ValueError("DG25_ACTION_CHANNEL_NOT_EXECUTABLE")
    return build_replay_action(
        case_id=str(identity["case_id"]),
        requirement_id=str(identity["requirement_id"]),
        channel=str(identity["channel"]),
        action_kind=action_kind,
        channel_query_identity_digest=canonical_sha256(dict(identity)),
        returned_occurrence_count=returned_occurrence_count,
    )


def _identity_executable(identity: Mapping[str, Any]) -> bool:
    return identity.get("disposition") in {"EXECUTED", "PARTIAL"}


def _probe_index(
    collection: Mapping[str, Any],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for record in _mapping_sequence(collection.get("records"), "probe records"):
        trace = _mapping(record.get("trace"), "probe trace")
        key = (
            str(record["case_id"]),
            str(trace["requirement_id"]),
            str(trace["channel"]),
        )
        if key in result:
            raise ValueError("DG25_DUPLICATE_OFFICIAL_PROBE_IDENTITY")
        result[key] = trace
    if len(result) != 75:
        raise ValueError("DG25_OFFICIAL_PROBE_IDENTITY_COUNT_MISMATCH")
    return result


def _lifecycle_index(
    product_traces: Mapping[str, Any],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for record in _mapping_sequence(product_traces.get("records"), "product records"):
        trace = _mapping(record.get("trace"), "product trace")
        for lifecycle in _mapping_sequence(
            trace.get("candidate_lifecycles"), "candidate lifecycles"
        ):
            evidence_id = str(lifecycle["candidate_identity"])
            for requirement_id in lifecycle.get("requirement_candidates", []):
                key = (str(record["case_id"]), str(requirement_id), evidence_id)
                result.setdefault(key, lifecycle)
    return result


def _proof_index(
    product_traces: Mapping[str, Any],
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    result: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in _mapping_sequence(product_traces.get("records"), "product records"):
        trace = _mapping(record.get("trace"), "product trace")
        for item in _mapping_sequence(trace.get("proof_obligations"), "proof obligations"):
            key = (str(record["case_id"]), str(item["requirement_id"]))
            proof_rows = result.setdefault(key, [])
            proof_rows.append(item)
    return result


def _plans_by_arm(
    manifest: Mapping[str, Any],
) -> dict[str, list[E1RequirementActionPlanV01]]:
    result: dict[str, list[E1RequirementActionPlanV01]] = {
        arm_id: [] for arm_id in E1_ARM_ORDER
    }
    for raw in _mapping_sequence(manifest.get("plans"), "action plans"):
        plan = E1RequirementActionPlanV01.model_validate(raw)
        arm_plans = result[plan.arm_id]
        arm_plans.append(plan)
    return result


def _evidence_ids(trace: Mapping[str, Any]) -> set[str]:
    return {
        str(_mapping(item.get("evidence_record_identity"), "evidence identity")["evidence_id"])
        for item in _mapping_sequence(trace.get("returned_occurrences"), "occurrences")
    }


def _plan_key(item: Mapping[str, Any]) -> str:
    return f"{item['arm_id']}::{item['case_id']}::{item['requirement_id']}"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _mapping_sequence(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{label} items must be mappings")
        result.append(item)
    return result


__all__ = [
    "build_e1_action_manifest",
    "generate_e1_all_arm_bundle",
    "validate_e1_action_manifest",
    "validate_s3a_authorization",
]
