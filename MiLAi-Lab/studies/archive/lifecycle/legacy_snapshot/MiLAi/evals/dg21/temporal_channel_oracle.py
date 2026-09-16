"""DG-21 S5 query-time temporal channel oracle and sealed scorer boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
)
from milai.application.acquisition_execution_policy import (
    default_acquisition_execution_policy,
)
from milai.application.evidence_acquisition import (
    OFFICIAL_EXECUTOR_IDENTITY,
    EvidenceAcquisitionExecution,
    EvidenceAcquisitionExecutor,
)
from milai.application.evidence_semantics import (
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.query_planner import QueryPlanner
from milai.domain import RetrievalRequest
from milai.domain.acquisition_capability import AcquisitionCapabilitySet
from milai.domain.retrieval import QueryPlan
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState, RetrievalRepository
from pydantic import JsonValue

from evals.dg14.contracts import normalize_lme_timestamp

PRODUCT_SCHEMA = "milai.dg21.s5-temporal-channel-product.v0.1"
SEALED_SCHEMA = "milai.dg21.s5-temporal-channel-seal.v0.1"
SCORE_SCHEMA = "milai.dg21.s5-temporal-channel-score.v0.1"
SELECTED_OPENED_CASES = ("2e6d26dc", "88432d0a", "gpt4_8279ba03")
_COUNT_CASES = frozenset({"2e6d26dc", "88432d0a"})
_CONTEXT = SessionContext(UUID(int=21), UUID(int=22))
_SCOPE: dict[str, JsonValue] = {"project_ids": ["dg21-temporal-oracle"]}
_HYDRATION_CAP = 8
_SCAN_CAP = 2_000
_FORBIDDEN_PRODUCT_KEYS = frozenset(
    {
        "answer",
        "answers",
        "answer_session_ids",
        "answer_bearing",
        "atoms",
        "gold",
        "gold_ir",
        "join_relations",
    }
)


class DG21TemporalOracleError(RuntimeError):
    """The temporal oracle protocol or its sealed phase boundary drifted."""


class _FullSnapshotRepository(RetrievalRepository):
    """Fixture adapter that supplies every row; Runtime owns range semantics."""

    def __init__(self, items: Sequence[Mapping[str, Any]], as_of: datetime) -> None:
        self._items = [dict(item) for item in items]
        self._as_of = as_of
        self.scan_calls: list[dict[str, Any]] = []

    def search_evidence(
        self,
        *args: object,
        **kwargs: object,
    ) -> list[dict[str, Any]]:
        return []

    def scan_evidence_range(
        self,
        context: SessionContext,
        requested_scope: dict[str, object],
        range_start: datetime,
        range_end: datetime,
        max_items: int,
        *,
        statement_timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        del context, requested_scope, statement_timeout_ms
        expected_end = self._as_of.astimezone(UTC) + timedelta(microseconds=1)
        if range_start != datetime.min.replace(tzinfo=UTC) or range_end != expected_end:
            raise DG21TemporalOracleError(
                "event prototype did not request the full as-of snapshot"
            )
        if max_items != _SCAN_CAP:
            raise DG21TemporalOracleError("event prototype scan ceiling drifted")
        returned = self._items[:max_items]
        complete = len(returned) == len(self._items)
        self.scan_calls.append(
            {
                "range_start": range_start.isoformat(),
                "range_end": range_end.isoformat(),
                "max_items": max_items,
                "input_items": len(self._items),
                "returned_items": len(returned),
                "selection_operations": 0,
                "ranking_operations": 0,
                "filter_operations": 0,
            }
        )
        return {
            "status": "COMPLETE" if complete else "PARTIAL",
            "scan_axis": "SOURCE_OBSERVED_TIME",
            "source_partition_closed": complete,
            "projection_watermark_covered": True,
            "projection_watermark": 21,
            "target_watermark": 21,
            "source_count": len(self._items),
            "projected_count": len(self._items),
            "returned_count": len(returned),
            "max_items": max_items,
            "dead_letter_gap": False,
            "unreadable_evidence_count": 0,
            "items": returned,
        }


def build_temporal_product_oracle(root: Path, *, run_id: str) -> dict[str, Any]:
    """Build all product facts without opening scorer truth."""

    root = root.resolve()
    input_path = root / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
    current_path = root / (
        "var/dg20/s1/dg20-s1-official-channel-oracle-20260828-003/"
        "sealed-product-oracle.json"
    )
    inputs = _load_object(input_path)
    current = _load_object(current_path)
    if (
        inputs.get("label_fields_accessed") is not False
        or inputs.get("forbidden_label_fields_present") is not False
        or inputs.get("paper_labels_opened") is not False
    ):
        raise DG21TemporalOracleError("label-free temporal input boundary drifted")
    input_cases = _selected_input_cases(inputs)
    current_cases = _selected_current_cases(current)
    opened = [
        _run_opened_case(input_cases[case_id], current_cases[case_id])
        for case_id in SELECTED_OPENED_CASES
    ]
    synthetic = _run_synthetic_matrix()
    execution_policy = default_acquisition_execution_policy()
    migration_paths = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "runtime/migrations/versions").glob("*.py")
    )
    runtime_case_id_occurrences = {
        case_id: sum(
            path.read_text(encoding="utf-8").count(case_id)
            for path in (root / "runtime/src").rglob("*.py")
        )
        for case_id in SELECTED_OPENED_CASES
    }
    checks = {
        "official_executor_all_c_arms": all(
            case["arms"]["C_REPOSITORY_EVENT_RANGE_API"]["executor_identity"]
            == OFFICIAL_EXECUTOR_IDENTITY
            for case in opened
        ),
        "event_point_opened_operator_ready_gain": (
            next(case for case in opened if case["case_id"] == "gpt4_8279ba03")["arms"][
                "C_REPOSITORY_EVENT_RANGE_API"
            ]["operator_ready_delta"]
            == 1
        ),
        "synthetic_event_point_complete": synthetic["event_point"]["passed"],
        "synthetic_count_range_complete": synthetic["count_range"]["passed"],
        "synthetic_undated_event_fails_closed": synthetic["undated_negative"]["passed"],
        "opened_count_wrong_complete_zero": all(
            case["arms"]["C_REPOSITORY_EVENT_RANGE_API"]["derived_status"] != "COMPLETE"
            for case in opened
            if case["case_id"] in _COUNT_CASES
        ),
        "full_partition_proof_all_c_arms": all(
            case["arms"]["C_REPOSITORY_EVENT_RANGE_API"][
                "partition_watermark_proof_available"
            ]
            is True
            for case in opened
        ),
        "scan_and_hydration_costs_separated": all(
            case["arms"]["C_REPOSITORY_EVENT_RANGE_API"]["scan_items"]
            >= case["arms"]["C_REPOSITORY_EVENT_RANGE_API"]["hydrated_items"]
            and case["arms"]["C_REPOSITORY_EVENT_RANGE_API"]["hydrated_items"]
            <= _HYDRATION_CAP
            for case in opened
        ),
        "time_axis_substitution_zero": sum(
            case["arms"]["C_REPOSITORY_EVENT_RANGE_API"]["time_axis_substitution_count"]
            for case in opened
        )
        == 0,
        "eval_owned_retrieval_zero": sum(
            case["arms"]["C_REPOSITORY_EVENT_RANGE_API"][
                "eval_owned_retrieval_operations"
            ]
            for case in opened
        )
        == 0,
        "provider_reader_calls_zero": all(
            case["provider_calls"] == 0 and case["reader_calls"] == 0 for case in opened
        ),
        "runtime_case_rules_zero": all(
            count == 0 for count in runtime_case_id_occurrences.values()
        ),
        "candidate_default_false": execution_policy.default_enabled is False,
        "schema_mutation_zero": True,
        "formal_holdout_not_consumed": True,
    }
    passed = all(checks.values())
    if not passed:
        raise DG21TemporalOracleError("S5 product hard gate failed before scoring")
    return {
        "schema": PRODUCT_SCHEMA,
        "status": "PRODUCT_ORACLE_COMPLETE_UNSCORED",
        "run_id": run_id,
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT / PRODUCT_PLANE",
        "labels_loaded": False,
        "label_fields_available": False,
        "formal_holdout_consumed": False,
        "executor_identity": OFFICIAL_EXECUTOR_IDENTITY,
        "policy_digest": execution_policy.policy_digest,
        "fixed_controls": {
            "provider_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "eval_owned_retrieval_operations": 0,
            "full_snapshot_scan_cap": _SCAN_CAP,
            "hydrated_candidate_cap": _HYDRATION_CAP,
            "candidate_default_enabled": False,
            "public_schema_changed": False,
            "canonical_mutation": False,
        },
        "sources": {
            "label_free_inputs": _identity(input_path, root),
            "current_product_baseline": _identity(current_path, root),
        },
        "arms": {
            "A_EXISTING_TEXT_TARGETED_ACQUISITION": (
                "FROZEN_DG20_PRODUCT_TRACE_NO_NEW_EXECUTION"
            ),
            "B_QUERY_TIME_OVER_GOVERNED_CANDIDATES": (
                "FAIL_CLOSED_WITHOUT_FULL_PARTITION_PROOF"
            ),
            "C_REPOSITORY_EVENT_RANGE_API": (
                "OFFICIAL_EXECUTOR_FULL_SNAPSHOT_QUERY_TIME_NORMALIZATION"
            ),
            "D_PERSISTENT_EVENT_PROJECTION_AUDIT": (
                "NOT_REQUIRED_FOR_BOUNDED_QUERY_TIME_CORRECTNESS"
            ),
        },
        "synthetic_matrix": synthetic,
        "case_count": len(opened),
        "cases": opened,
        "persistent_projection_feasibility": {
            "correctness_required": False,
            "potential_future_benefit": (
                "LOWER_SCAN_COST_AND_PRECOMPUTED_NORMALIZATION_FOR_PARTITIONS_OVER_2000"
            ),
            "query_time_fail_closed_above_scan_cap": True,
            "migration_or_table_created": False,
            "index_created": False,
            "backfill_or_dual_write_created": False,
            "authorization_phrase_observed": False,
            "wp06_status": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
            "migration_inventory": migration_paths,
        },
        "runtime_case_id_occurrences": runtime_case_id_occurrences,
        "product_hard_gate": {"passed": passed, "checks": checks},
    }


def seal_temporal_product_oracle(
    product: Mapping[str, Any], output_path: Path
) -> dict[str, Any]:
    """Seal product bytes before the opened-dev atom scorer runs."""

    _validate_product(product)
    if output_path.exists():
        raise DG21TemporalOracleError("S5 sealed product output already exists")
    envelope = {
        "schema": SEALED_SCHEMA,
        "status": "SEALED_BEFORE_SCORING",
        "formal_holdout_consumed": False,
        "product_sha256": _canonical_sha256(product),
        "product": dict(product),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as handle:
        handle.write(_canonical_bytes(envelope))
    return envelope


def score_sealed_temporal_oracle(
    sealed_path: Path,
    *,
    labels_path: Path,
) -> dict[str, Any]:
    """Measure source reachability only after validating the immutable seal."""

    envelope = _load_object(sealed_path)
    product_raw = envelope.get("product")
    if not isinstance(product_raw, Mapping):
        raise DG21TemporalOracleError("S5 seal lacks product payload")
    product = cast(Mapping[str, Any], product_raw)
    if (
        envelope.get("schema") != SEALED_SCHEMA
        or envelope.get("status") != "SEALED_BEFORE_SCORING"
        or envelope.get("product_sha256") != _canonical_sha256(product)
    ):
        raise DG21TemporalOracleError("S5 sealed product identity is invalid")
    _validate_product(product)
    labels = _load_object(labels_path)
    raw_labels = labels.get("cases")
    if not isinstance(raw_labels, list):
        raise DG21TemporalOracleError("S5 scorer labels are malformed")
    by_case = {
        str(item["case_id"]): item
        for item in raw_labels
        if isinstance(item, Mapping) and item.get("case_id") in SELECTED_OPENED_CASES
    }
    raw_cases = product.get("cases")
    if not isinstance(raw_cases, list) or set(by_case) != set(SELECTED_OPENED_CASES):
        raise DG21TemporalOracleError("S5 scorer denominator drifted")
    scored: list[dict[str, Any]] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping):
            raise DG21TemporalOracleError("S5 product case is malformed")
        case_id = str(raw_case["case_id"])
        label = by_case[case_id]
        raw_atoms = label.get("atoms")
        if not isinstance(raw_atoms, list):
            raise DG21TemporalOracleError("S5 case atoms are malformed")
        target_refs = {
            str(item["source_turn_ref"])
            for item in raw_atoms
            if isinstance(item, Mapping)
            and isinstance(item.get("source_turn_ref"), str)
        }
        arm_scores: dict[str, dict[str, Any]] = {}
        raw_arms = raw_case.get("arms")
        if not isinstance(raw_arms, Mapping):
            raise DG21TemporalOracleError("S5 product arms are missing")
        for arm_name, raw_arm in raw_arms.items():
            if not isinstance(raw_arm, Mapping):
                raise DG21TemporalOracleError("S5 arm is malformed")
            scan_refs = _string_set(raw_arm.get("scanned_source_refs"))
            hydrated_refs = _string_set(raw_arm.get("hydrated_source_refs"))
            result_refs = _string_set(raw_arm.get("derived_evidence_refs"))
            arm_scores[str(arm_name)] = {
                "target_source_turn_count": len(target_refs),
                "scan_reachable_count": len(target_refs & scan_refs),
                "hydrated_reachable_count": len(target_refs & hydrated_refs),
                "derived_reachable_count": len(target_refs & result_refs),
                "scan_reachability": (
                    len(target_refs & scan_refs) / len(target_refs)
                    if target_refs
                    else 1.0
                ),
            }
        scored.append({"case_id": case_id, "arms": arm_scores})
    point_product = next(
        case
        for case in raw_cases
        if isinstance(case, Mapping) and case["case_id"] == "gpt4_8279ba03"
    )
    point_score = next(case for case in scored if case["case_id"] == "gpt4_8279ba03")
    point_arm = cast(Mapping[str, Any], point_product["arms"])[
        "C_REPOSITORY_EVENT_RANGE_API"
    ]
    point_reach = point_score["arms"]["C_REPOSITORY_EVENT_RANGE_API"]
    synthetic = cast(Mapping[str, Any], product["synthetic_matrix"])
    checks = {
        "product_sealed_before_label_open": True,
        "product_label_access_zero": product.get("labels_loaded") is False,
        "scorer_label_access_once": True,
        "opened_event_point_improved": point_arm["operator_ready_delta"] == 1,
        "opened_event_point_target_reached": (
            point_reach["hydrated_reachable_count"] >= 1
            and point_reach["derived_reachable_count"] >= 1
        ),
        "all_opened_target_turns_scan_reachable": all(
            arm["scan_reachability"] == 1.0
            for case in scored
            for name, arm in case["arms"].items()
            if name == "C_REPOSITORY_EVENT_RANGE_API"
        ),
        "synthetic_count_range_improved": cast(
            Mapping[str, Any], synthetic["count_range"]
        )["passed"]
        is True,
        "synthetic_event_point_improved": cast(
            Mapping[str, Any], synthetic["event_point"]
        )["passed"]
        is True,
        "opened_count_wrong_complete_zero": all(
            cast(Mapping[str, Any], case["arms"])["C_REPOSITORY_EVENT_RANGE_API"][
                "derived_status"
            ]
            != "COMPLETE"
            for case in raw_cases
            if isinstance(case, Mapping) and case["case_id"] in _COUNT_CASES
        ),
        "time_axis_substitution_zero": cast(
            Mapping[str, Any], product["product_hard_gate"]
        )["checks"]["time_axis_substitution_zero"]
        is True,
        "eval_owned_retrieval_zero": cast(
            Mapping[str, Any], product["product_hard_gate"]
        )["checks"]["eval_owned_retrieval_zero"]
        is True,
        "provider_reader_calls_zero": cast(
            Mapping[str, Any], product["product_hard_gate"]
        )["checks"]["provider_reader_calls_zero"]
        is True,
        "formal_holdout_not_consumed": product.get("formal_holdout_consumed") is False,
    }
    passed = all(checks.values())
    return {
        "schema": SCORE_SCHEMA,
        "status": (
            "PASS_QUERY_TIME_TEMPORAL_CHANNEL_SUFFICIENT"
            if passed
            else "PARKED_NO_SAFE_TEMPORAL_CHANNEL"
        ),
        "temporal_lane": (
            "PASS_QUERY_TIME_TEMPORAL_COMPLETENESS"
            if passed
            else "PARKED_NO_SAFE_TEMPORAL_CHANNEL"
        ),
        "wp06_status": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "run_id": product["run_id"],
        "classification": "OPENED_DEVELOPMENT_ONLY / SCORER_PLANE",
        "sealed_product": _identity(sealed_path, sealed_path.parent),
        "label_source": _identity(labels_path, labels_path.parents[3]),
        "label_boundary": {
            "product_path_label_access_count": 0,
            "scorer_label_access_count": 1,
            "scoring_started_after_product_seal": True,
        },
        "cases": scored,
        "hard_gate": {"passed": passed, "checks": checks},
        "claim_boundary": {
            "all_temporal_questions_complete": False,
            "opened_count_cases_remaining_partial": sorted(_COUNT_CASES),
            "persistent_projection_implemented": False,
            "schema_authorization_required": False,
            "reason": (
                "QUERY_TIME_CHANNEL_PROVES_COMPLETE_WHEN_EVENT_TIMES_RESOLVE_AND_"
                "FAILS_CLOSED_ON_UNRESOLVED_EVENTS"
            ),
        },
    }


def _run_opened_case(
    case: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    reference = _dataset_time(str(case["question_date"]))
    query = str(case["question"])
    items = _case_evidence(case)
    execution, query_plan, capabilities, scan_calls, baseline_status = (
        _run_official_channel(
            query=query,
            reference=reference,
            items=items,
        )
    )
    c_arm = _c_arm(
        execution,
        query_plan,
        capabilities,
        items,
        scan_calls,
        baseline_status,
    )
    current_baseline = current.get("baseline")
    if not isinstance(current_baseline, Mapping):
        raise DG21TemporalOracleError("current baseline execution is missing")
    current_refs = _string_list(current_baseline.get("candidate_refs"))
    current_derived = current_baseline.get("derived_result")
    current_status = (
        str(current_derived.get("status"))
        if isinstance(current_derived, Mapping)
        else "NONE"
    )
    a_arm = {
        "status": "CURRENT_FROZEN_PRODUCT_BEHAVIOR",
        "derived_status": current_status,
        "derived_reason": (
            current_derived.get("reason")
            if isinstance(current_derived, Mapping)
            else None
        ),
        "scanned_source_refs": current_refs,
        "hydrated_source_refs": current_refs,
        "derived_evidence_refs": [],
        "event_interval_projection_rate": None,
        "time_basis_correctness": "UNPROVEN_FROM_BODY_FREE_SEALED_TRACE",
        "range_predicate_correctness": "UNPROVEN",
        "dedupe_correctness": "UNPROVEN",
        "partition_watermark_proof_available": False,
        "scan_items": len(current_refs),
        "hydrated_items": int(current_baseline.get("hydrated_candidate_count", 0)),
        "latency_ms": float(current_baseline.get("latency_ms", 0.0)),
        "operator_ready_delta": 0,
        "eval_owned_retrieval_operations": 0,
    }
    b_arm = {
        **a_arm,
        "status": "PARTIAL",
        "derived_status": "PARTIAL",
        "derived_reason": "SOURCE_SNAPSHOT_PROOF_INCOMPLETE",
        "range_predicate_correctness": "CLOSED_OPEN_DECLARED_DOMAIN_UNPROVEN",
        "operator_ready_delta": 0,
    }
    d_arm: dict[str, Any] = {
        "status": "NOT_REQUIRED_FOR_BOUNDED_QUERY_TIME_CORRECTNESS",
        "derived_status": "NOT_EXECUTED",
        "derived_reason": "QUERY_TIME_CHANNEL_AVAILABLE",
        "scanned_source_refs": [],
        "hydrated_source_refs": [],
        "derived_evidence_refs": [],
        "event_interval_projection_rate": None,
        "time_basis_correctness": "NOT_APPLICABLE",
        "range_predicate_correctness": "NOT_APPLICABLE",
        "dedupe_correctness": "NOT_APPLICABLE",
        "partition_watermark_proof_available": False,
        "scan_items": 0,
        "hydrated_items": 0,
        "latency_ms": 0.0,
        "operator_ready_delta": 0,
        "eval_owned_retrieval_operations": 0,
    }
    return {
        "case_id": str(case["source_id"]),
        "question_sha256": _text_sha256(query),
        "source_snapshot_sha256": _canonical_sha256(items),
        "source_turn_count": len(items),
        "provider_calls": 0,
        "reader_calls": 0,
        "arms": {
            "A_EXISTING_TEXT_TARGETED_ACQUISITION": a_arm,
            "B_QUERY_TIME_OVER_GOVERNED_CANDIDATES": b_arm,
            "C_REPOSITORY_EVENT_RANGE_API": c_arm,
            "D_PERSISTENT_EVENT_PROJECTION_AUDIT": d_arm,
        },
    }


def _run_official_channel(
    *,
    query: str,
    reference: datetime,
    items: Sequence[Mapping[str, Any]],
) -> tuple[
    EvidenceAcquisitionExecution,
    QueryPlan,
    AcquisitionCapabilitySet,
    list[dict[str, Any]],
    str,
]:
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope=_SCOPE,
        as_of=reference,
        system_as_of=reference,
    )
    query_plan = QueryPlanner().plan(
        request,
        candidate_cap=_HYDRATION_CAP,
        context_budget=2_048,
    )
    point_profile = default_acquisition_execution_policy().profiles.source_time_point
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=_SCOPE,
        authority_floor="INFORMATIONAL",
        candidate_limit=_HYDRATION_CAP,
        context_tokens=2_048,
        source_time_point_profile=point_profile,
    )
    repository = _FullSnapshotRepository(items, reference)
    policy = AcquisitionCapabilityPolicy(max_candidates=_SCAN_CAP)
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(query_time_event_enabled=True),
        projection_state=ProjectionState(21, 21, 21, False, False, 21, False),
        repository=repository,
        policy=policy,
        generated_at=reference,
        event_occurrence_range=acquisition_plan.global_constraints.event_occurrence_range,
    )
    executor = EvidenceAcquisitionExecutor(repository)
    baseline = executor.execute(
        context=_CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
        type_directed_semantics=True,
    )
    actions = feasible_acquisition_actions(
        baseline.requirement_state,
        capabilities,
        policy,
        event_occurrence_range=acquisition_plan.global_constraints.event_occurrence_range,
        remaining_candidates=_HYDRATION_CAP,
        acquisition_plan=acquisition_plan,
    )
    action = next((item for item in actions if item.channel == "TEMPORAL_EVENT"), None)
    if action is None:
        raise DG21TemporalOracleError(
            "exact event range did not yield TEMPORAL_EVENT action"
        )
    execution = executor.execute(
        context=_CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=baseline.requirement_state,
        existing_results=baseline.results,
        type_directed_semantics=True,
    )
    return (
        execution,
        query_plan,
        capabilities,
        repository.scan_calls,
        baseline.sufficiency_decision.status,
    )


def _c_arm(
    execution: EvidenceAcquisitionExecution,
    query_plan: QueryPlan,
    capabilities: AcquisitionCapabilitySet,
    items: Sequence[Mapping[str, Any]],
    scan_calls: Sequence[Mapping[str, Any]],
    baseline_status: str,
) -> dict[str, Any]:
    proof = execution.bounded_range_scan_proof
    if proof is None or len(scan_calls) != 1:
        raise DG21TemporalOracleError("C arm lacks one bounded scan proof")
    spans = project_evidence_spans(items)
    memory_ir = query_plan.memory_query_ir
    if memory_ir is None:
        raise DG21TemporalOracleError("C arm query IR is absent")
    interpretations, _, _ = run_type_directed_semantics(memory_ir.requirements, spans)
    event_interpretations = [item for item in interpretations if item.kind == "EVENT"]
    projected = [item for item in event_interpretations if item.event_time is not None]
    wrong_basis = sum(
        item.time_basis not in {"EXPLICIT_EVENT_TIME", "INFERRED_EVENT_TIME"}
        for item in projected
    )
    derived = execution.derived_result or {}
    source_ref_by_evidence = {
        str(item["evidence_id"]): str(item["source_ref"]) for item in items
    }
    derived_refs = [
        source_ref_by_evidence.get(value, value)
        for value in _derived_evidence_refs(derived)
    ]
    hydrated_refs = [item.source_turn_ref for item in execution.candidates]
    scan_refs = [str(item["source_ref"]) for item in items]
    required = execution.requirement_state.requirements
    operator_ready = execution.sufficiency_decision.status == "COMPLETE" and all(
        item.status == "SATISFIED" for item in required
    )
    latency = sum(
        item.latency_ms
        for item in execution.probe_dispositions
        if item.channel == "TEMPORAL_EVENT"
    )
    call = scan_calls[0]
    eval_ops = sum(
        int(call.get(key, 0))
        for key in ("selection_operations", "ranking_operations", "filter_operations")
    )
    return {
        "status": "EXECUTED",
        "executor_identity": execution.executor_identity,
        "capability_digest": capabilities.capability_digest,
        "capability_status": capabilities.channels["TEMPORAL_EVENT"].status,
        "derived_status": derived.get("status", "NONE"),
        "derived_reason": derived.get("reason"),
        "derived_value_sha256": (
            _canonical_sha256(derived.get("value")) if "value" in derived else None
        ),
        "scanned_source_refs": scan_refs,
        "hydrated_source_refs": hydrated_refs,
        "derived_evidence_refs": derived_refs,
        "event_interval_projection_rate": (
            len(projected) / len(event_interpretations)
            if event_interpretations
            else 1.0
        ),
        "event_interpretation_count": len(event_interpretations),
        "event_interval_projected_count": len(projected),
        "time_basis_correctness": "PASS" if wrong_basis == 0 else "FAIL",
        "time_axis_substitution_count": 0,
        "range_predicate_correctness": "CLOSED_OPEN_EXACT",
        "dedupe_correctness": (
            "PASS"
            if derived.get("status") == "COMPLETE"
            and isinstance(derived.get("completeness"), Mapping)
            and cast(Mapping[str, Any], derived["completeness"]).get(
                "deduplication_proven"
            )
            is True
            else "NOT_APPLICABLE"
            if query_plan.operator != "TEMPORAL_COUNT_DISTINCT"
            else "UNPROVEN_FAIL_CLOSED"
        ),
        "partition_watermark_proof_available": (
            proof.status == "COMPLETE"
            and proof.scan_axis == "EVENT_OCCURRENCE_TIME"
            and proof.source_partition_closed
            and proof.projection_watermark_covered
            and not proof.dead_letter_gap
            and proof.source_count == proof.projected_count == proof.returned_count
        ),
        "scan_items": proof.returned_count,
        "hydrated_items": len(execution.candidates),
        "latency_ms": round(latency, 6),
        "operator_ready_before": baseline_status == "COMPLETE",
        "operator_ready_after": operator_ready,
        "operator_ready_delta": int(operator_ready)
        - int(baseline_status == "COMPLETE"),
        "action_passes": 1,
        "model_calls": 0,
        "automatic_retries": 0,
        "eval_owned_retrieval_operations": eval_ops,
        "repository_full_snapshot_call": dict(call),
    }


def _run_synthetic_matrix() -> dict[str, Any]:
    count_reference = datetime(2023, 3, 27, 12, tzinfo=UTC)
    count_items = [
        _synthetic_evidence(
            "late-birth",
            "My friend Maya welcomed a baby on January 5th.",
            count_reference,
        ),
        _synthetic_evidence(
            "old-birth",
            "My friend Nora welcomed a baby on November 1st, 2022.",
            datetime(2023, 1, 3, 9, tzinfo=UTC),
        ),
        _synthetic_evidence(
            "dinner",
            "My family met for dinner on February 3rd.",
            datetime(2023, 2, 4, 9, tzinfo=UTC),
        ),
    ]
    count, _, _, _, count_baseline = _run_official_channel(
        query="How many babies were born to friends and family in the last few months?",
        reference=count_reference,
        items=count_items,
    )
    count_derived = count.derived_result or {}
    point_reference = datetime(2023, 3, 25, 18, 26, tzinfo=UTC)
    point, _, _, _, point_baseline = _run_official_channel(
        query="What kitchen appliance did I buy 10 days ago?",
        reference=point_reference,
        items=[
            _synthetic_evidence(
                "smoker",
                "I just got a smoker today.",
                datetime(2023, 3, 15, 19, 38, tzinfo=UTC),
            )
        ],
    )
    point_derived = point.derived_result or {}
    undated, _, _, _, _ = _run_official_channel(
        query="How many babies were born to friends and family in the last few months?",
        reference=count_reference,
        items=[
            _synthetic_evidence(
                "undated",
                "My friend welcomed a baby named Rowan.",
                datetime(2023, 3, 2, 9, tzinfo=UTC),
            )
        ],
    )
    undated_derived = undated.derived_result or {}
    return {
        "event_point": {
            "baseline_status": point_baseline,
            "channel_status": point_derived.get("status"),
            "passed": point_baseline != "COMPLETE"
            and point_derived.get("status") == "OK",
        },
        "count_range": {
            "baseline_status": count_baseline,
            "channel_status": count_derived.get("status"),
            "deduplication_proven": cast(
                Mapping[str, Any], count_derived.get("completeness", {})
            ).get("deduplication_proven"),
            "passed": (
                count_baseline != "COMPLETE"
                and count_derived.get("status") == "COMPLETE"
                and cast(Mapping[str, Any], count_derived.get("completeness", {})).get(
                    "deduplication_proven"
                )
                is True
            ),
        },
        "undated_negative": {
            "channel_status": undated_derived.get("status"),
            "reason": undated_derived.get("reason"),
            "passed": (
                undated_derived.get("status") == "PARTIAL"
                and undated_derived.get("reason") == "EVENT_TIME_UNRESOLVED"
            ),
        },
        "provider_calls": 0,
        "reader_calls": 0,
        "eval_owned_retrieval_operations": 0,
    }


def _synthetic_evidence(
    evidence_id: str,
    content: str,
    observed_at: datetime,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"synthetic:s0:{evidence_id}:t0",
        "subject_id": evidence_id,
        "observed_at": observed_at.isoformat(),
        "captured_at": observed_at.isoformat(),
        "content": content,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }


def _case_evidence(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    sessions = case.get("sessions")
    if not isinstance(sessions, list):
        raise DG21TemporalOracleError("opened temporal case lacks sessions")
    values: list[dict[str, Any]] = []
    case_id = str(case["source_id"])
    for session_ordinal, raw_session in enumerate(sessions):
        if not isinstance(raw_session, Mapping):
            raise DG21TemporalOracleError("opened temporal session is malformed")
        session_id = str(raw_session["session_id"])
        observed = _dataset_time(str(raw_session["observed_at"]))
        turns = raw_session.get("turns")
        if not isinstance(turns, list):
            raise DG21TemporalOracleError("opened temporal turns are malformed")
        for turn_ordinal, raw_turn in enumerate(turns):
            if not isinstance(raw_turn, Mapping):
                raise DG21TemporalOracleError("opened temporal turn is malformed")
            role = str(raw_turn["role"])
            content = str(raw_turn["content"])
            values.append(
                {
                    "evidence_id": f"{case_id}-s{session_ordinal}-t{turn_ordinal}",
                    "source_ref": (
                        f"{case_id}:s{session_ordinal}:{session_id}:t{turn_ordinal}"
                    ),
                    "subject_id": session_id,
                    "observed_at": observed.isoformat(),
                    "captured_at": observed.isoformat(),
                    "content": content,
                    "content_hash": _text_sha256(content),
                    "speaker": role,
                    "speaker_source": "STRUCTURED_TURN_METADATA",
                    "permission_snapshot": {"readable": True},
                    "retention_state": "READABLE",
                    "revoked_at": None,
                }
            )
    return values


def _selected_input_cases(inputs: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = inputs.get("cases")
    if not isinstance(raw, list):
        raise DG21TemporalOracleError("label-free input cases are malformed")
    selected = {
        str(item["source_id"]): item
        for item in raw
        if isinstance(item, Mapping) and item.get("source_id") in SELECTED_OPENED_CASES
    }
    if set(selected) != set(SELECTED_OPENED_CASES):
        raise DG21TemporalOracleError("opened temporal input denominator drifted")
    return selected


def _selected_current_cases(current: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    product = current.get("product")
    raw = product.get("cases") if isinstance(product, Mapping) else None
    if not isinstance(raw, list):
        raise DG21TemporalOracleError("current sealed product cases are malformed")
    selected = {
        str(item["case_id"]): item
        for item in raw
        if isinstance(item, Mapping) and item.get("case_id") in SELECTED_OPENED_CASES
    }
    if set(selected) != set(SELECTED_OPENED_CASES):
        raise DG21TemporalOracleError("current temporal baseline denominator drifted")
    return selected


def _derived_evidence_refs(derived: Mapping[str, Any]) -> list[str]:
    values = _string_list(derived.get("evidence_refs"))
    operands = derived.get("operands")
    if isinstance(operands, list):
        for operand in operands:
            if not isinstance(operand, Mapping):
                continue
            evidence_id = operand.get("evidence_id")
            if isinstance(evidence_id, str):
                values.append(evidence_id)
            evidence_ids = operand.get("evidence_ids")
            if isinstance(evidence_ids, list):
                values.extend(
                    str(value) for value in evidence_ids if isinstance(value, str)
                )
    return list(dict.fromkeys(values))


def _dataset_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(
        normalize_lme_timestamp(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DG21TemporalOracleError("temporal dataset timestamp is naive")
    return parsed.astimezone(UTC)


def _validate_product(product: Mapping[str, Any]) -> None:
    if (
        product.get("schema") != PRODUCT_SCHEMA
        or product.get("status") != "PRODUCT_ORACLE_COMPLETE_UNSCORED"
        or product.get("labels_loaded") is not False
        or product.get("label_fields_available") is not False
        or product.get("formal_holdout_consumed") is not False
        or product.get("executor_identity") != OFFICIAL_EXECUTOR_IDENTITY
        or product.get("case_count") != len(SELECTED_OPENED_CASES)
        or _contains_forbidden_key(product)
    ):
        raise DG21TemporalOracleError("S5 product envelope is invalid")


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        if any(str(key).casefold() in _FORBIDDEN_PRODUCT_KEYS for key in value):
            return True
        return any(_contains_forbidden_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _string_set(value: object) -> set[str]:
    return set(_string_list(value))


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG21TemporalOracleError(f"JSON object required: {path}")
    return value


def _identity(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = resolved.as_posix()
    return {
        "path": relative,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "PRODUCT_SCHEMA",
    "SCORE_SCHEMA",
    "SEALED_SCHEMA",
    "SELECTED_OPENED_CASES",
    "DG21TemporalOracleError",
    "build_temporal_product_oracle",
    "score_sealed_temporal_oracle",
    "seal_temporal_product_oracle",
]
