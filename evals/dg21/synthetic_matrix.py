"""Content-free DG-21 S1 selector and safety matrix."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from milai.application.acquisition_execution_policy import (
    AcquisitionExecutionPolicyError,
    acquisition_execution_policy_safe_summary,
    default_acquisition_execution_policy,
    load_acquisition_execution_policy,
    select_acquisition_execution_profile,
)
from milai.config.settings import RuntimeSettings
from milai.domain.acquisition_capability import (
    AcquisitionCapability,
    AcquisitionCapabilityName,
    AcquisitionCapabilitySet,
    AcquisitionCapabilityStatus,
)
from milai.domain.acquisition_execution_policy import AcquisitionExecutionPolicy
from milai.domain.acquisition_observation import (
    AcquisitionObservationGlobalV02,
    AcquisitionObservationV02,
    RequirementAcquisitionObservationV02,
)
from milai.domain.requirement_state import (
    RequirementCardinalityState,
    RequirementDisposition,
    RequirementDispositionStatus,
    RequirementState,
    canonical_sha256,
)
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    MemoryPlannerTrace,
    MemoryQueryConstraints,
    MemoryQueryIRV02,
    MemoryQueryStep,
    NormalizedTemporalConstraint,
    RequirementCardinalityV02,
)
from milai.domain.sufficiency import SufficiencyDecision

_REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)
_CAPABILITY_NAMES: tuple[AcquisitionCapabilityName, ...] = (
    "FTS_RAW",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "SOURCE_OBSERVED_RANGE_SCAN",
    "TEMPORAL_EVENT",
    "CANONICAL_STATE",
    "ADJACENT_TURNS",
    "SAME_EPISODE",
)
CapabilityClass = Literal["ENABLED", "CONDITIONAL", "UNAVAILABLE", "DISABLED"]
ObservationClass = Literal[
    "CHANNEL_MISS",
    "CANDIDATE_PRESENT_NO_INTERPRETATION",
    "LOCAL_OPERAND_MISSING",
    "COMPLETENESS_PROOF_MISSING",
    "NO_TARGETABLE_REQUIREMENT",
    "COMPLETE",
]
Axis = Literal["NONE", "SOURCE_OBSERVED_TIME", "EVENT_TIME"]
Boundary = Literal["NONE", "POINT", "CLOSED_OPEN"]


@dataclass(frozen=True, slots=True)
class _Cell:
    profile: str
    requirement_kind: str
    axis: str
    boundary: str
    capability: str
    observation: str
    expected_terminal: str
    expected_channel: str | None
    precision_proven: bool = True


def run_synthetic_matrix() -> dict[str, Any]:
    policy = default_acquisition_execution_policy()
    records = [
        _execute_cell(index, cell, policy) for index, cell in enumerate(_cells(), 1)
    ]
    profile_coverage: dict[str, dict[str, int]] = {}
    for name in sorted(type(policy.profiles).model_fields):
        rows = [record for record in records if record["profile_under_test"] == name]
        profile_coverage[name] = {
            "positive": sum(
                record["actual_terminal"] in {"ACTIONABLE", "COMPLETE"}
                for record in rows
            ),
            "negative": sum(
                record["actual_terminal"] not in {"ACTIONABLE", "COMPLETE"}
                for record in rows
            ),
        }
    coverage = {
        "requirement_kinds": sorted({record["requirement_kind"] for record in records}),
        "temporal_axes": sorted({record["temporal_axis"] for record in records}),
        "boundaries": sorted({record["boundary"] for record in records}),
        "capability_classes": sorted(
            {record["capability_class"] for record in records}
        ),
        "observations": sorted({record["observation"] for record in records}),
        "profiles": profile_coverage,
    }
    checks = {
        "synthetic_cell_count_at_least_36": len(records) >= 36,
        "selector_expectation_100_percent": all(record["passed"] for record in records),
        "five_requirement_kinds_covered": set(coverage["requirement_kinds"])
        == {
            "EVENT_SLOT",
            "VALUE_SLOT",
            "SET_MEMBERS",
            "CARDINALITY",
            "RANGE_COMPLETENESS",
        },
        "three_temporal_axes_covered": set(coverage["temporal_axes"])
        == {"NONE", "SOURCE_OBSERVED_TIME", "EVENT_TIME"},
        "three_boundaries_covered": set(coverage["boundaries"])
        == {"NONE", "POINT", "CLOSED_OPEN"},
        "four_capability_classes_covered": set(coverage["capability_classes"])
        == {"ENABLED", "CONDITIONAL", "UNAVAILABLE", "DISABLED"},
        "six_observations_covered": len(coverage["observations"]) == 6,
        "profile_positive_and_negative_coverage": all(
            value["positive"] >= 1 and value["negative"] >= 1
            for value in profile_coverage.values()
        ),
        "provider_calls_zero": all(record["provider_calls"] == 0 for record in records),
        "automatic_retries_zero": all(
            record["automatic_retries"] == 0 for record in records
        ),
        "canonical_mutation_zero": all(
            record["canonical_mutation"] is False for record in records
        ),
        "selector_content_free": all(
            not {"case_id", "gold", "answer", "content", "question"}.intersection(
                record
            )
            for record in records
        ),
        "default_disabled": policy.default_enabled is False,
        "runtime_setting_default_disabled": (
            RuntimeSettings.model_fields[
                "retrieval_type_directed_acquisition_enabled"
            ].default
            is False
        ),
        "unknown_policy_version_fails_closed": _invalid_policy_rejected(
            {**policy.model_dump(mode="json"), "policy_version": "unknown"}
        ),
        "unknown_policy_key_fails_closed": _invalid_policy_rejected(
            {**policy.model_dump(mode="json"), "unknown_profile": {}}
        ),
        "policy_version_rollback_loads_exact_digest": (
            load_acquisition_execution_policy(
                policy.model_dump(mode="json")
            ).policy_digest
            == policy.policy_digest
        ),
    }
    return {
        "schema": "milai.dg21.s1-synthetic-selector-matrix.v0.1",
        "status": "PASS_POLICY_SYNTHETIC_MATRIX" if all(checks.values()) else "FAIL",
        "classification": "SYNTHETIC_ONLY / CONTENT_FREE / EVALUATION_PLANE",
        "policy": acquisition_execution_policy_safe_summary(policy),
        "cell_count": len(records),
        "records": records,
        "coverage": coverage,
        "terminal_distribution": dict(
            sorted(Counter(record["actual_terminal"] for record in records).items())
        ),
        "safety": {
            "provider_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
            "formal_holdout_consumed": False,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def _invalid_policy_rejected(payload: Mapping[str, Any]) -> bool:
    try:
        load_acquisition_execution_policy(payload)
    except AcquisitionExecutionPolicyError:
        return True
    return False


def _execute_cell(
    index: int, cell: _Cell, policy: AcquisitionExecutionPolicy
) -> dict[str, Any]:
    capabilities = _capability_set(cell.capability)
    query_ir, target_id = _query_ir(cell)
    state, sufficiency = _state_and_sufficiency(
        cell,
        query_ir,
        capabilities.capability_digest,
        target_id,
    )
    observation = _observation(cell, state, capabilities, target_id)
    selection = select_acquisition_execution_profile(
        policy=policy,
        query_ir=query_ir,
        requirement_state=state,
        sufficiency=sufficiency,
        capability_set=capabilities,
        remaining_budget={"acquisition_passes": 1, "candidate_count": 2_000},
        observation=observation,
    )
    passed = (
        selection.terminal_disposition == cell.expected_terminal
        and selection.selected_channel == cell.expected_channel
    )
    return {
        "cell_id": f"S1-{index:02d}",
        "profile_under_test": cell.profile,
        "requirement_kind": cell.requirement_kind,
        "temporal_axis": cell.axis,
        "boundary": cell.boundary,
        "capability_class": cell.capability,
        "observation": cell.observation,
        "expected_terminal": cell.expected_terminal,
        "actual_terminal": selection.terminal_disposition,
        "expected_channel": cell.expected_channel,
        "actual_channel": selection.selected_channel,
        "selected_profile": selection.selected_profile,
        "target_requirement_id": selection.target_requirement_id,
        "declared_budget": selection.declared_budget.model_dump(mode="json"),
        "effective_budget": selection.effective_budget.model_dump(mode="json"),
        "budget_clamp_owner": selection.budget_clamp_owner,
        "budget_clamp_reason": selection.budget_clamp_reason,
        "policy_digest": selection.policy_digest,
        "selector_inputs_digest": selection.selector_inputs_digest,
        "selection_digest": selection.selection_digest,
        "targeted_only": selection.targeted_only,
        "include_global_probe": selection.include_global_probe,
        "provider_calls": selection.provider_calls_authorized,
        "automatic_retries": selection.automatic_retries_authorized,
        "canonical_mutation": selection.canonical_mutation,
        "passed": passed,
    }


def _cells() -> list[_Cell]:
    values: list[_Cell] = []
    values.extend(
        [
            _Cell(
                "complete_fast_path",
                "VALUE_SLOT",
                "NONE",
                "NONE",
                capability,
                observation,
                terminal,
                None,
            )
            for capability, observation, terminal in (
                ("ENABLED", "COMPLETE", "COMPLETE"),
                ("CONDITIONAL", "COMPLETE", "COMPLETE"),
                ("UNAVAILABLE", "COMPLETE", "COMPLETE"),
                ("DISABLED", "NO_TARGETABLE_REQUIREMENT", "NO_TARGETABLE_REQUIREMENT"),
                ("ENABLED", "NO_TARGETABLE_REQUIREMENT", "NO_TARGETABLE_REQUIREMENT"),
                ("DISABLED", "COMPLETE", "COMPLETE"),
            )
        ]
    )
    values.extend(
        [
            _Cell(
                "semantic_slot",
                "EVENT_SLOT",
                "NONE",
                "NONE",
                capability,
                observation,
                terminal,
                channel,
            )
            for capability, observation, terminal, channel in (
                ("ENABLED", "CHANNEL_MISS", "ACTIONABLE", "FTS_ENRICHED"),
                ("CONDITIONAL", "CHANNEL_MISS", "ACTIONABLE", "FTS_ENRICHED"),
                (
                    "UNAVAILABLE",
                    "CHANNEL_MISS",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
                ("DISABLED", "CHANNEL_MISS", "CAPABILITY_REQUIRED_UNAVAILABLE", None),
                (
                    "ENABLED",
                    "CANDIDATE_PRESENT_NO_INTERPRETATION",
                    "ACTIONABLE",
                    "EVIDENCE_DENSE",
                ),
                ("ENABLED", "LOCAL_OPERAND_MISSING", "ACTIONABLE", "ADJACENT_TURNS"),
            )
        ]
    )
    values.extend(
        [
            _Cell(
                "source_time_point",
                "EVENT_SLOT",
                "SOURCE_OBSERVED_TIME",
                boundary,
                capability,
                observation,
                terminal,
                channel,
                precision,
            )
            for boundary, capability, observation, terminal, channel, precision in (
                (
                    "POINT",
                    "ENABLED",
                    "CHANNEL_MISS",
                    "ACTIONABLE",
                    "SOURCE_OBSERVED_RANGE_SCAN",
                    True,
                ),
                (
                    "POINT",
                    "CONDITIONAL",
                    "CHANNEL_MISS",
                    "ACTIONABLE",
                    "SOURCE_OBSERVED_RANGE_SCAN",
                    True,
                ),
                (
                    "POINT",
                    "UNAVAILABLE",
                    "CHANNEL_MISS",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                    True,
                ),
                (
                    "POINT",
                    "DISABLED",
                    "CHANNEL_MISS",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                    True,
                ),
                (
                    "POINT",
                    "ENABLED",
                    "CHANNEL_MISS",
                    "SOURCE_POINT_BUCKET_UNPROVEN",
                    None,
                    False,
                ),
                (
                    "CLOSED_OPEN",
                    "ENABLED",
                    "CHANNEL_MISS",
                    "ACTIONABLE",
                    "SOURCE_OBSERVED_RANGE_SCAN",
                    True,
                ),
            )
        ]
    )
    values.extend(
        [
            _Cell(
                "event_time_point",
                "EVENT_SLOT",
                "EVENT_TIME",
                "POINT",
                capability,
                observation,
                terminal,
                channel,
            )
            for capability, observation, terminal, channel in (
                ("ENABLED", "CHANNEL_MISS", "ACTIONABLE", "TEMPORAL_EVENT"),
                ("CONDITIONAL", "CHANNEL_MISS", "ACTIONABLE", "TEMPORAL_EVENT"),
                (
                    "UNAVAILABLE",
                    "CHANNEL_MISS",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
                ("DISABLED", "CHANNEL_MISS", "CAPABILITY_REQUIRED_UNAVAILABLE", None),
                (
                    "ENABLED",
                    "CANDIDATE_PRESENT_NO_INTERPRETATION",
                    "ACTIONABLE",
                    "TEMPORAL_EVENT",
                ),
                (
                    "UNAVAILABLE",
                    "LOCAL_OPERAND_MISSING",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
            )
        ]
    )
    values.extend(
        [
            _Cell(
                "event_range_enumeration",
                kind,
                "EVENT_TIME",
                "CLOSED_OPEN",
                capability,
                observation,
                terminal,
                channel,
            )
            for kind, capability, observation, terminal, channel in (
                (
                    "CARDINALITY",
                    "ENABLED",
                    "COMPLETENESS_PROOF_MISSING",
                    "ACTIONABLE",
                    "TEMPORAL_EVENT",
                ),
                (
                    "RANGE_COMPLETENESS",
                    "CONDITIONAL",
                    "COMPLETENESS_PROOF_MISSING",
                    "ACTIONABLE",
                    "TEMPORAL_EVENT",
                ),
                (
                    "SET_MEMBERS",
                    "UNAVAILABLE",
                    "COMPLETENESS_PROOF_MISSING",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
                (
                    "CARDINALITY",
                    "DISABLED",
                    "COMPLETENESS_PROOF_MISSING",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
                (
                    "RANGE_COMPLETENESS",
                    "ENABLED",
                    "CANDIDATE_PRESENT_NO_INTERPRETATION",
                    "ACTIONABLE",
                    "TEMPORAL_EVENT",
                ),
                (
                    "SET_MEMBERS",
                    "UNAVAILABLE",
                    "CHANNEL_MISS",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
            )
        ]
    )
    values.extend(
        [
            _Cell(
                "preference_local",
                "VALUE_SLOT",
                "NONE",
                "NONE",
                capability,
                observation,
                terminal,
                channel,
            )
            for capability, observation, terminal, channel in (
                ("ENABLED", "LOCAL_OPERAND_MISSING", "ACTIONABLE", "ADJACENT_TURNS"),
                (
                    "CONDITIONAL",
                    "LOCAL_OPERAND_MISSING",
                    "ACTIONABLE",
                    "ADJACENT_TURNS",
                ),
                (
                    "UNAVAILABLE",
                    "LOCAL_OPERAND_MISSING",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
                (
                    "DISABLED",
                    "LOCAL_OPERAND_MISSING",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
                ("ENABLED", "CHANNEL_MISS", "CAPABILITY_REQUIRED_UNAVAILABLE", None),
                (
                    "UNAVAILABLE",
                    "CHANNEL_MISS",
                    "CAPABILITY_REQUIRED_UNAVAILABLE",
                    None,
                ),
            )
        ]
    )
    if len(values) != 36:
        raise AssertionError("DG-21 S1 matrix must contain exactly 36 declared cells")
    return values


def _query_ir(cell: _Cell) -> tuple[MemoryQueryIRV02, str]:
    target_id = "CURRENT_INTENT" if cell.profile == "preference_local" else "TARGET"
    interpretation = (
        "STATE_OBSERVATION"
        if cell.requirement_kind == "VALUE_SLOT"
        else "PREFERENCE_SIGNAL"
        if cell.requirement_kind == "SET_MEMBERS" and cell.profile == "preference_local"
        else "EVENT"
    )
    temporal = _temporal(cell)
    requirement = EvidenceRequirementV02(
        slot_id=target_id,
        interpretation_kind=cast(Any, interpretation),
        temporal_constraints=temporal,
        cardinality=RequirementCardinalityV02(
            minimum=1,
            maximum=None
            if cell.requirement_kind in {"SET_MEMBERS", "CARDINALITY"}
            else 1,
            distinct=cell.requirement_kind in {"SET_MEMBERS", "CARDINALITY"},
        ),
    )
    operator = (
        "PREFERENCE_RESOLVE"
        if cell.profile == "preference_local"
        else "COUNT"
        if cell.requirement_kind in {"CARDINALITY", "RANGE_COMPLETENESS"}
        else "TEMPORAL_FILTER"
        if temporal is not None
        else "LOOKUP"
    )
    completeness = (
        "ALL_MATCHES_IN_RANGE"
        if cell.requirement_kind in {"CARDINALITY", "RANGE_COMPLETENESS"}
        else "ALL_REQUIRED_BINDINGS"
    )
    query_ir = MemoryQueryIRV02(
        mode="COMPOSE",
        answer_shape="SCALAR",
        constraints=MemoryQueryConstraints(normalized_temporal=temporal),
        requirements=[requirement],
        steps=[
            MemoryQueryStep(
                kind="RETRIEVE",
                outputs=["candidate_spans"],
                constraints={"operator_family": operator},
            ),
            MemoryQueryStep(
                kind="BIND_SLOT",
                inputs=["candidate_spans"],
                outputs=[target_id],
            ),
        ],
        completeness=cast(Any, completeness),
        planner_trace=MemoryPlannerTrace(
            source="DETERMINISTIC",
            compiler_version="dg21-synthetic-v0.1",
            auxiliary_model_calls=0,
            reason_code="SYNTHETIC_SELECTOR_CELL",
        ),
    )
    return query_ir, target_id


def _temporal(cell: _Cell) -> NormalizedTemporalConstraint | None:
    if cell.axis == "NONE":
        return None
    if cell.boundary == "POINT":
        return NormalizedTemporalConstraint(
            reference_time=_REFERENCE,
            start=_REFERENCE,
            end=_REFERENCE,
            boundary="POINT",
            time_axis=cast(Any, cell.axis),
            precision="DAY" if cell.precision_proven else None,
            timezone="UTC" if cell.precision_proven else None,
        )
    return NormalizedTemporalConstraint(
        reference_time=_REFERENCE,
        start=_REFERENCE,
        end=_REFERENCE.replace(day=29),
        boundary="CLOSED_OPEN",
        time_axis=cast(Any, cell.axis),
    )


def _state_and_sufficiency(
    cell: _Cell,
    query_ir: MemoryQueryIRV02,
    capability_digest: str,
    target_id: str,
) -> tuple[RequirementState, SufficiencyDecision]:
    satisfied = cell.observation in {"COMPLETE", "NO_TARGETABLE_REQUIREMENT"}
    status: RequirementDispositionStatus = (
        "SATISFIED"
        if satisfied
        else "COMPLETENESS_PROOF_MISSING"
        if cell.observation == "COMPLETENESS_PROOF_MISSING"
        else "MISSING"
    )
    disposition = RequirementDisposition(
        requirement_id=target_id,
        kind=cast(Any, cell.requirement_kind),
        status=status,
        required_cardinality=RequirementCardinalityState(minimum=1, maximum=1),
        observed_cardinality=1 if satisfied else 0,
        proof_status="NOT_REQUIRED" if satisfied else "MISSING",
        accepted_binding_refs=["a" * 64] if satisfied else [],
        accepted_evidence_refs=["synthetic:evidence"] if satisfied else [],
        rejection_summary={},
    )
    sufficiency = SufficiencyDecision(
        status="COMPLETE" if cell.observation == "COMPLETE" else "PARTIAL",
        covered_slots=[target_id] if satisfied else [],
        missing_slots=[] if satisfied else [target_id],
        stop_reason=(
            "REQUIREMENT_SATISFIED"
            if cell.observation == "COMPLETE"
            else "SEARCH_SPACE_EXHAUSTED"
        ),
    )
    material = {
        "schema_version": "requirement-state-v0.1",
        "query_ir_digest": canonical_sha256(query_ir.model_dump(mode="json")),
        "acquisition_plan_digest": "1" * 64,
        "acquisition_capability_digest": capability_digest,
        "candidate_snapshot_digest": "2" * 64,
        "binding_digest": "3" * 64,
        "sufficiency_decision_digest": canonical_sha256(
            sufficiency.model_dump(mode="json")
        ),
        "sufficiency_policy_version": "dg21-synthetic-v0.1",
        "state_epoch": 0,
        "requirements": [disposition.model_dump(mode="json")],
        "lifetime": "MEMORY_RESOLVE",
        "canonical": False,
        "canonical_mutation": False,
    }
    return RequirementState.model_validate(
        {"state_digest": canonical_sha256(material), **material}
    ), sufficiency


def _observation(
    cell: _Cell,
    state: RequirementState,
    capabilities: AcquisitionCapabilitySet,
    target_id: str,
) -> AcquisitionObservationV02:
    rows: list[RequirementAcquisitionObservationV02] = []
    if cell.observation not in {"COMPLETE", "NO_TARGETABLE_REQUIREMENT"}:
        first_loss = {
            "CHANNEL_MISS": "CHANNEL_RETRIEVAL_BOUND_MISS",
            "CANDIDATE_PRESENT_NO_INTERPRETATION": (
                "CANDIDATES_WITHOUT_ACCEPTED_BINDING"
            ),
            "LOCAL_OPERAND_MISSING": "CHANNEL_RETRIEVAL_BOUND_MISS",
            "COMPLETENESS_PROOF_MISSING": "COMPLETENESS_PROOF_MISSING",
        }[cell.observation]
        disposition = state.requirements[0]
        rows.append(
            RequirementAcquisitionObservationV02(
                requirement_id=target_id,
                kind=disposition.kind,
                status=disposition.status,
                first_loss_reason=cast(Any, first_loss),
                matched_evidence_refs=(
                    ["synthetic:anchor"]
                    if cell.observation == "LOCAL_OPERAND_MISSING"
                    else []
                ),
            )
        )
    global_observation = AcquisitionObservationGlobalV02(
        seen_region_digests=[],
        exhausted_region_digests=[],
        valid_adjacency_anchor_count=(
            1 if cell.observation == "LOCAL_OPERAND_MISSING" else 0
        ),
        remaining_budget={"acquisition_passes": 1, "candidate_count": 2_000},
    )
    material = {
        "schema_version": "acquisition-observation-v0.2",
        "requirement_state_digest": state.state_digest,
        "requirement_state_epoch": state.state_epoch,
        "acquisition_capability_digest": capabilities.capability_digest,
        "policy_digest": capabilities.policy_digest,
        "requirements": [item.model_dump(mode="json") for item in rows],
        "global_observation": global_observation.model_dump(mode="json"),
        "canonical": False,
        "canonical_mutation": False,
    }
    return AcquisitionObservationV02.model_validate(
        {"observation_digest": canonical_sha256(material), **material}
    )


def _capability_set(status: str) -> AcquisitionCapabilitySet:
    capabilities: dict[str, AcquisitionCapability] = {}
    for name in _CAPABILITY_NAMES:
        kind: Literal["CHANNEL", "EXPANSION"] = (
            "EXPANSION" if name in {"ADJACENT_TURNS", "SAME_EPISODE"} else "CHANNEL"
        )
        raw_status: AcquisitionCapabilityStatus = cast(
            AcquisitionCapabilityStatus, status
        )
        capabilities[name] = AcquisitionCapability(
            capability_id=f"{kind.casefold()}:{name}",
            name=name,
            capability_kind=kind,
            status=raw_status,
            reason=f"SYNTHETIC_{status}",
        )
    channels = {
        name: capabilities[name]
        for name in _CAPABILITY_NAMES
        if name not in {"ADJACENT_TURNS", "SAME_EPISODE"}
    }
    expansions = {
        name: capabilities[name] for name in ("ADJACENT_TURNS", "SAME_EPISODE")
    }
    material = {
        "schema_version": "acquisition-capability-set-v0.1",
        "config_digest": "4" * 64,
        "projection_snapshot_digest": "5" * 64,
        "policy_digest": "6" * 64,
        "channels": {
            key: value.model_dump(mode="json") for key, value in channels.items()
        },
        "expansions": {
            key: value.model_dump(mode="json") for key, value in expansions.items()
        },
    }
    return AcquisitionCapabilitySet.model_validate(
        {
            **material,
            "capability_digest": canonical_sha256(material),
            "generated_at": _REFERENCE,
        }
    )


__all__ = ["run_synthetic_matrix"]
