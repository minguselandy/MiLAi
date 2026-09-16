"""Pure, label-free DG-25 S4A E2 temporal all-arm generator.

The generator consumes only immutable input mappings supplied by its caller.
It does not read files, repositories, scorer registries, labels, or holdouts,
and it never invokes a Reader, model, Provider, or controller.  Retrieval is
not reimplemented here: every candidate row comes from the already-sealed
official ``TEMPORAL_EVENT`` range scan frozen in the E2 common input.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote

from milai.application.evidence_semantics import (
    bind_requirements,
    derive_non_temporal_applicability,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.memory_query import MemoryQueryCompiler
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    NonTemporalApplicability,
    RequirementBinding,
)
from milai.domain.temporal_proof import (
    BoundedRangeAccessClosureV02,
    BoundedRangeDedupClosureV02,
    BoundedRangeEventSetClosureV02,
    BoundedRangeProjectionClosureV02,
    BoundedRangeQueryClosureV02,
    BoundedRangeScanClosureV02,
    BoundedRangeScanProofV02,
    BoundedRangeSnapshotClosureV02,
    EventDeduplicationV01,
    EventIdentityV01,
    EventTimeBasisV02,
    EventTimeIntervalV02,
    EventTimePrecisionV02,
    LegacyBoundedRangeScanProofV01,
    RangeMembershipV01,
    build_bounded_range_scan_proof_v02,
    build_event_identity_v01,
    build_event_time_interval_v02,
    classify_range_membership,
    deduplicate_event_identities,
    read_legacy_bounded_range_scan_proof_v01,
)

from evals.dg14.contracts import (
    DG14HistoryEvent,
    deterministic_event_id,
    normalize_lme_timestamp,
)
from evals.dg25.arm_sealing import (
    COST_LEDGER_FIELDS,
    E2_ARM_ORDER,
    build_block_all_arm_seal,
    build_label_free_arm_output,
    validate_block_all_arm_seal,
)
from evals.dg25.routing_ablation import E2ArmConfigV01

_EXPECTED_REQUIREMENTS = 2
_EXPECTED_RAW_ROWS = 973
_RANGE_SCAN_MAX_ROWS = 2_000
_FINAL_K = 8
_SOURCE_PROXY_AMBIGUITY = "EVENT_TIME_UNRESOLVED_SOURCE_TIME_NOT_SUBSTITUTED"
_IDENTITY_POLICY = "event-identity-dedup-v0.1"

_ApplicabilityStatus = Literal["MATCH", "POSSIBLE"]
_BindingStatus = Literal["MATCH", "POSSIBLE", "NO_MATCH"]


@dataclass(frozen=True, slots=True)
class _TemporalCandidate:
    raw_rank: int
    raw_occurrence_id: str
    evidence_id: str
    source_turn_ref: str
    span: EvidenceSpan
    interpretation: EvidenceInterpretationCandidate
    applicability_status: _ApplicabilityStatus
    point_membership: RangeMembershipV01
    interval: EventTimeIntervalV02
    interval_membership: RangeMembershipV01


@dataclass(frozen=True, slots=True)
class _CaseAnalysis:
    query_id: str
    query_identity: str
    frozen_query_ir_digest: str
    compiled_query_semantics_digest: str
    requirement_id: str
    requirement: EvidenceRequirementV02
    query_interval: EventTimeIntervalV02
    common_requirement: Mapping[str, Any]
    proof_obligations: tuple[Mapping[str, Any], ...]
    legacy_proof: LegacyBoundedRangeScanProofV01
    candidates: tuple[_TemporalCandidate, ...]
    evidence_row_count: int


@dataclass(frozen=True, slots=True)
class _IdentityProjection:
    identity_by_interpretation: Mapping[str, EventIdentityV01]
    deduplication: EventDeduplicationV01 | None
    duplicate_candidate_count: int


def validate_s4a_authorization(
    *,
    authorization: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> None:
    """Require an exact, single-stage authorization with every later lane denied."""

    if authorization.get("schema") != "milai.dg25.s4a-independent-authorization.v0.1":
        raise ValueError("DG25_S4A_AUTHORIZATION_SCHEMA_INVALID")
    if authorization.get("authorized") is not True:
        raise ValueError("DG25_S4A_NOT_AUTHORIZED")
    if (
        authorization.get("scope")
        != "S4A_E2_LABEL_FREE_ALL_5_ARMS_E2_AND_COMBINED_SEALS"
    ):
        raise ValueError("DG25_S4A_AUTHORIZATION_SCOPE_INVALID")
    if authorization.get("readiness_bindings") != dict(expected_bindings):
        raise ValueError("DG25_S4A_AUTHORIZATION_BINDING_MISMATCH")
    if authorization.get("readiness_bindings_digest") != canonical_sha256(
        dict(expected_bindings)
    ):
        raise ValueError("DG25_S4A_AUTHORIZATION_BINDING_DIGEST_MISMATCH")
    boundaries = {
        "authorized_attempts": 1,
        "labels_authorized": False,
        "registry_content_authorized": False,
        "scoring_authorized": False,
        "s4b_authorized": False,
        "e3_authorized": False,
        "reader_model_provider_controller_calls_authorized": 0,
        "formal_holdout_authorized": False,
        "candidate_default_authorized": False,
        "automatic_retries": 0,
    }
    if any(authorization.get(key) != value for key, value in boundaries.items()):
        raise ValueError("DG25_S4A_AUTHORIZATION_BOUNDARY_INVALID")
    material = dict(authorization)
    observed = material.pop("authorization_digest", None)
    if observed != canonical_sha256(material):
        raise ValueError("DG25_S4A_AUTHORIZATION_DIGEST_MISMATCH")


def generate_e2_all_arm_bundle(
    *,
    configs: Sequence[E2ArmConfigV01],
    common_input: Mapping[str, Any],
    product_traces: Mapping[str, Any],
    label_free_inputs: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    common_execution_bindings: Mapping[str, Any],
    independent_authorization: Mapping[str, Any],
    expected_authorization_bindings: Mapping[str, Any],
    generator_source_sha256: str,
    sealer_source_sha256: str,
    runner_source_sha256: str,
) -> dict[str, Any]:
    """Generate all five temporal arms in memory and create one immutable E2 seal."""

    validate_s4a_authorization(
        authorization=independent_authorization,
        expected_bindings=expected_authorization_bindings,
    )
    _validate_configs(configs, common_input)
    _validate_common_input(common_input)
    analyses = _build_case_analyses(
        common_input=common_input,
        product_traces=product_traces,
        label_free_inputs=label_free_inputs,
        input_manifest=input_manifest,
    )
    analysis_digest = canonical_sha256(
        [
            {
                "query_id": item.query_id,
                "query_identity": item.query_identity,
                "frozen_query_ir_digest": item.frozen_query_ir_digest,
                "compiled_query_semantics_digest": item.compiled_query_semantics_digest,
                "requirement_id": item.requirement_id,
                "candidate_count": len(item.candidates),
                "evidence_row_count": item.evidence_row_count,
            }
            for item in analyses
        ]
    )
    shared_block_input = {
        "e2_common_input_digest": str(common_input["common_input_digest"]),
        "label_free_dataset_sha256": str(label_free_inputs["dataset_sha256"]),
        "input_manifest_digest": canonical_sha256(input_manifest),
        "target_product_trace_digest": canonical_sha256(
            [
                item
                for item in _mapping_sequence(
                    product_traces.get("records"), "product records"
                )
                if str(item.get("case_id")) in {value.query_id for value in analyses}
            ]
        ),
        "compiled_semantics_set_digest": analysis_digest,
        "t2_applicability_set_digest": canonical_sha256(
            [dict(item.common_requirement["t2_applicability"]) for item in analyses]
        ),
    }
    arm_outputs: dict[str, dict[str, Any]] = {}
    block_inputs: dict[str, dict[str, Any]] = {}
    for config in configs:
        records: list[dict[str, Any]] = []
        selected_count = 0
        bound_count = 0
        for analysis in analyses:
            record = _project_arm_record(analysis=analysis, config=config)
            records.append(record)
            requirement = _mapping_sequence(
                record.get("requirements"), "generated requirements"
            )[0]
            selected = _mapping_sequence(
                requirement.get("selected_occurrences"), "selected occurrences"
            )
            selected_count += len(selected)
            bound_count += sum(
                item.get("binding_status") == "MATCH" for item in selected
            )
        ledger: dict[str, Any] = {
            "logical_selected_actions": len(analyses),
            "physical_repository_calls": 0,
            "replayed_repository_calls": len(analyses),
            "returned_rows": sum(item.evidence_row_count for item in analyses),
            "range_rows_scanned": sum(item.evidence_row_count for item in analyses),
            "candidates_returned": sum(item.evidence_row_count for item in analyses),
            "candidates_hydrated": sum(item.evidence_row_count for item in analyses),
            "candidates_bound": bound_count,
            "candidates_shown_to_reader": 0,
            "state_passes": len(analyses),
            "reader_calls": 0,
            "latency_ms": None,
        }
        if set(ledger) != set(COST_LEDGER_FIELDS):
            raise AssertionError("DG25_S4A_INTERNAL_COST_LEDGER_SCHEMA_DRIFT")
        block_input = dict(shared_block_input)
        block_inputs[config.arm_id] = block_input
        arm_outputs[config.arm_id] = build_label_free_arm_output(
            block="E2",
            arm_id=config.arm_id,
            arm_config_digest=config.config_digest,
            common_execution_bindings=common_execution_bindings,
            block_input_identity=block_input,
            records=records,
            cost_ledger=ledger,
        )
        if selected_count > len(analyses) * _FINAL_K:
            raise AssertionError("DG25_S4A_FINAL_K_EXCEEDED")
    _validate_t1_t2_noop(arm_outputs)
    config_digests = {item.arm_id: item.config_digest for item in configs}
    seal = build_block_all_arm_seal(
        block="E2",
        arm_outputs=arm_outputs,
        arm_order=E2_ARM_ORDER,
        config_digests=config_digests,
        common_execution_bindings=common_execution_bindings,
        block_input_identities=block_inputs,
        generator_source_sha256=generator_source_sha256,
        sealer_source_sha256=sealer_source_sha256,
        runner_source_sha256=runner_source_sha256,
        independent_authorization_digest=str(
            independent_authorization["authorization_digest"]
        ),
    )
    validate_block_all_arm_seal(
        seal=seal,
        block="E2",
        arm_outputs=arm_outputs,
        arm_order=E2_ARM_ORDER,
        config_digests=config_digests,
        common_execution_bindings=common_execution_bindings,
        block_input_identities=block_inputs,
    )
    return {
        "schema": "milai.dg25.e2-label-free-all-arm-bundle.v0.1",
        "arm_order": list(E2_ARM_ORDER),
        "query_requirement_order": [
            {
                "query_id": item.query_id,
                "requirement_id": item.requirement_id,
            }
            for item in analyses
        ],
        "arm_outputs": arm_outputs,
        "e2_all_arm_seal": seal,
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
    }


def _validate_configs(
    configs: Sequence[E2ArmConfigV01],
    common_input: Mapping[str, Any],
) -> None:
    if [item.arm_id for item in configs] != list(E2_ARM_ORDER):
        raise ValueError("DG25_S4A_CONFIG_ORDER_MISMATCH")
    common_digest = common_input.get("common_input_digest")
    if any(item.common_input_digest != common_digest for item in configs):
        raise ValueError("DG25_S4A_CONFIG_COMMON_INPUT_DRIFT")
    expected_predecessors = {
        "T0": None,
        "T1": "T0",
        "T2": "T1",
        "T3": "T2",
        "T4": "T3",
    }
    if any(
        item.ordered_predecessor != expected_predecessors[item.arm_id]
        for item in configs
    ):
        raise ValueError("DG25_S4A_CONFIG_PREDECESSOR_DRIFT")


def _validate_common_input(common_input: Mapping[str, Any]) -> None:
    if common_input.get("schema") != "milai.dg25.e2-common-input.v0.1":
        raise ValueError("DG25_S4A_COMMON_INPUT_SCHEMA_INVALID")
    material = dict(common_input)
    observed_digest = material.pop("common_input_digest", None)
    if observed_digest != canonical_sha256(material):
        raise ValueError("DG25_S4A_COMMON_INPUT_DIGEST_MISMATCH")
    if (
        common_input.get("requirement_count") != _EXPECTED_REQUIREMENTS
        or common_input.get("raw_row_count") != _EXPECTED_RAW_ROWS
        or common_input.get("t2_applicability_frozen_before_labels") is not True
        or common_input.get("registry_content_loaded") is not False
        or common_input.get("formal_holdout_consumed") is not False
    ):
        raise ValueError("DG25_S4A_COMMON_INPUT_BOUNDARY_OR_DENOMINATOR_DRIFT")
    requirements = _mapping_sequence(
        common_input.get("requirements"), "common requirements"
    )
    if len(requirements) != _EXPECTED_REQUIREMENTS:
        raise ValueError("DG25_S4A_REQUIREMENT_DENOMINATOR_DRIFT")
    if [int(item["raw_row_count"]) for item in requirements] != [494, 479]:
        raise ValueError("DG25_S4A_RAW_ROW_DENOMINATOR_DRIFT")
    if len({str(item["query_id"]) for item in requirements}) != len(requirements):
        raise ValueError("DG25_S4A_QUERY_ID_DUPLICATE")
    for requirement in requirements:
        applicability = _mapping(
            requirement.get("t2_applicability"), "T2 applicability"
        )
        if applicability != {
            "disposition": "NOT_APPLICABLE",
            "reason_code": "NO_GROUNDED_UNIQUE_ANCHOR_RELATION_IN_SEALED_ROW_CONTRACT",
            "decided_before_labels": True,
        }:
            raise ValueError("DG25_S4A_T2_APPLICABILITY_DRIFT")
        rows = _mapping_sequence(
            requirement.get("raw_rows_in_order"), "common raw rows"
        )
        expected_count = int(requirement["raw_row_count"])
        if len(rows) != expected_count:
            raise ValueError("DG25_S4A_COMMON_RAW_ROW_COUNT_MISMATCH")
        if [int(item["ordinal"]) for item in rows] != list(
            range(1, expected_count + 1)
        ) or [int(item["raw_rank"]) for item in rows] != list(
            range(1, expected_count + 1)
        ):
            raise ValueError("DG25_S4A_COMMON_RAW_ROW_ORDER_DRIFT")
        if len({str(item["occurrence_id"]) for item in rows}) != len(rows):
            raise ValueError("DG25_S4A_COMMON_OCCURRENCE_DUPLICATE")


def _build_case_analyses(
    *,
    common_input: Mapping[str, Any],
    product_traces: Mapping[str, Any],
    label_free_inputs: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
) -> list[_CaseAnalysis]:
    _validate_source_boundaries(product_traces, label_free_inputs, input_manifest)
    raw_cases = {
        str(item["source_id"]): item
        for item in _mapping_sequence(
            label_free_inputs.get("cases"), "label-free cases"
        )
    }
    product_records = {
        str(item["case_id"]): item
        for item in _mapping_sequence(product_traces.get("records"), "product records")
    }
    manifest_requests = {
        str(item["case_id"]): item
        for item in _mapping_sequence(
            input_manifest.get("requests"), "input-manifest requests"
        )
    }
    requirements = _mapping_sequence(
        common_input.get("requirements"), "common requirements"
    )
    expected_query_ids = [str(item["query_id"]) for item in requirements]
    if any(query_id not in raw_cases for query_id in expected_query_ids):
        raise ValueError("DG25_S4A_LABEL_FREE_QUERY_MISSING")
    if any(query_id not in product_records for query_id in expected_query_ids):
        raise ValueError("DG25_S4A_PRODUCT_TRACE_QUERY_MISSING")
    if any(query_id not in manifest_requests for query_id in expected_query_ids):
        raise ValueError("DG25_S4A_INPUT_MANIFEST_QUERY_MISSING")
    analyses = [
        _build_case_analysis(
            common_requirement=common_requirement,
            raw_case=raw_cases[str(common_requirement["query_id"])],
            product_record=product_records[str(common_requirement["query_id"])],
            manifest_request=manifest_requests[str(common_requirement["query_id"])],
        )
        for common_requirement in requirements
    ]
    if [item.query_id for item in analyses] != expected_query_ids:
        raise ValueError("DG25_S4A_ANALYSIS_ORDER_DRIFT")
    return analyses


def _validate_source_boundaries(
    product_traces: Mapping[str, Any],
    label_free_inputs: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
) -> None:
    if (
        product_traces.get("schema")
        != "milai.dg24.sealed-product-trace-collection.v0.1"
        or product_traces.get("registry_content_loaded") is not False
        or product_traces.get("formal_holdout_consumed") is not False
        or product_traces.get("candidate_default") is not False
    ):
        raise ValueError("DG25_S4A_PRODUCT_TRACE_BOUNDARY_INVALID")
    execution_counts = _mapping(
        product_traces.get("execution_counts"), "product execution counts"
    )
    if (
        execution_counts.get("reader_calls") != 0
        or execution_counts.get("generative_provider_calls") != 0
        or execution_counts.get("automatic_retries") != 0
    ):
        raise ValueError("DG25_S4A_PRODUCT_TRACE_CALL_BOUNDARY_INVALID")
    if (
        label_free_inputs.get("schema") != "milai.dg11.paper-longmemeval-inputs.v1"
        or label_free_inputs.get("partition") != "LME-FULL-500-CHARACTERIZATION"
        or label_free_inputs.get("forbidden_label_fields_present") is not False
        or label_free_inputs.get("label_fields_accessed") is not False
        or label_free_inputs.get("paper_labels_opened") is not False
    ):
        raise ValueError("DG25_S4A_LABEL_FREE_INPUT_BOUNDARY_INVALID")
    cases = _mapping_sequence(label_free_inputs.get("cases"), "label-free cases")
    if label_free_inputs.get("case_count") != len(cases):
        raise ValueError("DG25_S4A_LABEL_FREE_CASE_COUNT_MISMATCH")
    forbidden_absent = _mapping(
        input_manifest.get("forbidden_fields_absent"),
        "input-manifest forbidden fields",
    )
    if (
        input_manifest.get("schema_version") != "input-only-case-manifest-v0.1"
        or not forbidden_absent
        or any(value is not True for value in forbidden_absent.values())
    ):
        raise ValueError("DG25_S4A_INPUT_MANIFEST_BOUNDARY_INVALID")


def _build_case_analysis(
    *,
    common_requirement: Mapping[str, Any],
    raw_case: Mapping[str, Any],
    product_record: Mapping[str, Any],
    manifest_request: Mapping[str, Any],
) -> _CaseAnalysis:
    query_id = str(common_requirement["query_id"])
    if (
        str(raw_case.get("source_id")) != query_id
        or str(product_record.get("case_id")) != query_id
    ):
        raise ValueError("DG25_S4A_CASE_IDENTITY_MISMATCH")
    events, evidence_by_source = _rebuild_label_free_evidence(raw_case)
    source_snapshot_digest = canonical_sha256([item.canonical() for item in events])
    if source_snapshot_digest != common_requirement.get(
        "source_snapshot_identity"
    ) or source_snapshot_digest != product_record.get("source_snapshot_digest"):
        raise ValueError("DG25_S4A_SOURCE_SNAPSHOT_MISMATCH")
    question = _required_text(raw_case, "question")
    if (
        manifest_request.get("case_id") != query_id
        or manifest_request.get("query_text") != question
        or manifest_request.get("request_payload_digest")
        != common_requirement.get("request_payload_digest")
        or str(manifest_request.get("source_snapshot_ref", "")).removeprefix("sha256:")
        != source_snapshot_digest
        or manifest_request.get("tenant_scope_digest")
        != common_requirement.get("input_tenant_scope_digest")
    ):
        raise ValueError("DG25_S4A_INPUT_MANIFEST_REQUEST_MISMATCH")
    question_at = normalize_lme_timestamp(_required_text(raw_case, "question_date"))
    trace = _mapping(product_record.get("trace"), "product trace")
    if (
        trace.get("query_identity") != common_requirement.get("query_identity")
        or trace.get("query_ir_digest") != common_requirement.get("query_ir_digest")
        or trace.get("request_identity") != common_requirement.get("request_identity")
    ):
        raise ValueError("DG25_S4A_QUERY_OR_REQUEST_IDENTITY_MISMATCH")
    temporal_rows = [
        item
        for item in _mapping_sequence(trace.get("occurrences"), "product occurrences")
        if item.get("channel") == "TEMPORAL_EVENT"
    ]
    common_rows = _mapping_sequence(
        common_requirement.get("raw_rows_in_order"), "common raw rows"
    )
    _validate_temporal_rows(
        temporal_rows=temporal_rows,
        common_rows=common_rows,
        common_requirement=common_requirement,
    )
    evidence_by_id: dict[str, dict[str, Any]] = {}
    raw_rank_by_evidence: dict[str, int] = {}
    raw_occurrence_by_evidence: dict[str, str] = {}
    for row in temporal_rows:
        evidence_identity = _mapping(
            row.get("evidence_record_identity"), "evidence identity"
        )
        source_ref = str(evidence_identity["source_ref"])
        evidence = evidence_by_source.get(source_ref)
        if evidence is None:
            raise ValueError("DG25_S4A_SOURCE_REF_NOT_IN_LABEL_FREE_INPUT")
        evidence_id = str(evidence_identity["evidence_id"])
        content = str(evidence["content"])
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != evidence_identity.get(
            "content_hash"
        ):
            raise ValueError("DG25_S4A_SOURCE_CONTENT_HASH_MISMATCH")
        if evidence.get("observed_at") != evidence_identity.get("observed_at"):
            raise ValueError("DG25_S4A_SOURCE_OBSERVED_AT_MISMATCH")
        evidence["evidence_id"] = evidence_id
        evidence["content_hash"] = str(evidence_identity["content_hash"])
        evidence_by_id[evidence_id] = evidence
        raw_rank_by_evidence[evidence_id] = int(row["raw_rank"])
        raw_occurrence_by_evidence[evidence_id] = str(row["occurrence_id"])
    expected_evidence_order = [str(item["evidence_id"]) for item in common_rows]
    if set(evidence_by_id) != set(expected_evidence_order) or len(
        evidence_by_source
    ) != len(expected_evidence_order):
        raise ValueError("DG25_S4A_LABEL_FREE_EVIDENCE_SET_MISMATCH")
    ordered_evidence = [
        evidence_by_id[evidence_id] for evidence_id in expected_evidence_order
    ]
    reference_time = datetime.fromisoformat(question_at.replace("Z", "+00:00"))
    query_ir = MemoryQueryCompiler().compile(
        question,
        reference_time=reference_time,
        scope={},
    )
    requirement_id = str(common_requirement["requirement_id"])
    matching_requirements = [
        item for item in query_ir.requirements if item.slot_id == requirement_id
    ]
    if (
        query_ir.completeness != "ALL_MATCHES_IN_RANGE"
        or len(matching_requirements) != 1
        or matching_requirements[0].interpretation_kind != "EVENT"
    ):
        raise ValueError("DG25_S4A_COMPILED_QUERY_SHAPE_INVALID")
    requirement = matching_requirements[0]
    query_interval = _query_interval(requirement)
    spans = project_evidence_spans(ordered_evidence)
    interpretations = interpret_evidence_spans(
        spans,
        allowed_kinds={"EVENT"},
        resolve_local_anchors=False,
    )
    bindings = bind_requirements(
        [requirement],
        interpretations,
        spans,
        type_compatible_only=True,
        compatibility_profile="dg22-v0.2",
    )
    applicability = derive_non_temporal_applicability(bindings, interpretations, spans)
    candidates = _temporal_candidates(
        requirement=requirement,
        query_interval=query_interval,
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        applicability=applicability,
        raw_rank_by_evidence=raw_rank_by_evidence,
        raw_occurrence_by_evidence=raw_occurrence_by_evidence,
    )
    proof_obligations = tuple(
        item
        for item in _mapping_sequence(
            trace.get("proof_obligations"), "proof obligations"
        )
        if str(item.get("requirement_id")) == requirement_id
    )
    if len(proof_obligations) != 7:
        raise ValueError("DG25_S4A_PROOF_OBLIGATION_COUNT_MISMATCH")
    legacy_row = next(
        (
            item
            for item in proof_obligations
            if str(item.get("kind")) == "BOUNDED_RANGE_SCAN"
        ),
        None,
    )
    if legacy_row is None:
        raise ValueError("DG25_S4A_LEGACY_RANGE_PROOF_MISSING")
    legacy_artifact = _mapping(
        legacy_row.get("proof_artifact"), "legacy proof artifact"
    )
    legacy_proof = read_legacy_bounded_range_scan_proof_v01(legacy_artifact)
    return _CaseAnalysis(
        query_id=query_id,
        query_identity=str(common_requirement["query_identity"]),
        frozen_query_ir_digest=str(common_requirement["query_ir_digest"]),
        compiled_query_semantics_digest=canonical_sha256(
            query_ir.model_dump(mode="json")
        ),
        requirement_id=requirement_id,
        requirement=requirement,
        query_interval=query_interval,
        common_requirement=common_requirement,
        proof_obligations=proof_obligations,
        legacy_proof=legacy_proof,
        candidates=tuple(candidates),
        evidence_row_count=len(ordered_evidence),
    )


def _rebuild_label_free_evidence(
    raw_case: Mapping[str, Any],
) -> tuple[list[DG14HistoryEvent], dict[str, dict[str, Any]]]:
    case_id = _required_text(raw_case, "source_id")
    sessions = _mapping_sequence(raw_case.get("sessions"), "label-free sessions")
    events: list[DG14HistoryEvent] = []
    evidence_by_source: dict[str, dict[str, Any]] = {}
    for session_ordinal, session in enumerate(sessions):
        session_id = _required_text(session, "session_id")
        observed_at = normalize_lme_timestamp(_required_text(session, "observed_at"))
        turns = _mapping_sequence(session.get("turns"), "label-free turns")
        for turn_ordinal, turn in enumerate(turns):
            event = DG14HistoryEvent.from_mapping(
                {
                    "case_id": case_id,
                    "session_ordinal": session_ordinal,
                    "original_session_id": session_id,
                    "turn_ordinal": turn_ordinal,
                    "role": _required_text(turn, "role"),
                    "content": _required_text(turn, "content"),
                    "observed_at": observed_at,
                }
            )
            events.append(event)
            event_id = deterministic_event_id(
                case_id,
                session_ordinal,
                session_id,
                turn_ordinal,
            )
            source_ref = (
                f"longmemeval://case/{quote(case_id, safe='')}/session/"
                f"{session_ordinal}/{quote(session_id, safe='')}/turn/"
                f"{turn_ordinal}?event_id={event_id}"
            )
            if source_ref in evidence_by_source:
                raise ValueError("DG25_S4A_SOURCE_REF_DUPLICATE")
            evidence_by_source[source_ref] = {
                "source_ref": source_ref,
                "content": f"{event.role}: {event.content}",
                "observed_at": observed_at.replace("Z", "+00:00"),
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "speaker": event.role,
                "speaker_source": "STRUCTURED_TURN_METADATA",
            }
    return events, evidence_by_source


def _validate_temporal_rows(
    *,
    temporal_rows: Sequence[Mapping[str, Any]],
    common_rows: Sequence[Mapping[str, Any]],
    common_requirement: Mapping[str, Any],
) -> None:
    if len(temporal_rows) != len(common_rows):
        raise ValueError("DG25_S4A_TEMPORAL_ROW_COUNT_MISMATCH")
    for raw, frozen in zip(temporal_rows, common_rows, strict=True):
        evidence = _mapping(raw.get("evidence_record_identity"), "evidence identity")
        retrieval = _mapping(
            raw.get("retrieval_document_identity"), "retrieval identity"
        )
        expected = {
            "ordinal": int(raw["raw_rank"]),
            "raw_rank": int(raw["raw_rank"]),
            "occurrence_id": str(raw["occurrence_id"]),
            "evidence_id": str(evidence["evidence_id"]),
            "evidence_record_identity_digest": canonical_sha256(evidence),
            "retrieval_document_identity_digest": canonical_sha256(retrieval),
        }
        if dict(frozen) != expected:
            raise ValueError("DG25_S4A_TEMPORAL_ROW_IDENTITY_MISMATCH")
        if (
            raw.get("request_identity") != common_requirement.get("request_identity")
            or raw.get("channel_query_digest")
            != common_requirement.get("channel_query_digest")
            or evidence.get("tenant_scope_digest")
            != common_requirement.get("evidence_tenant_scope_digest")
            or evidence.get("permission_snapshot_digest")
            != common_requirement.get("permission_snapshot_digest")
            or evidence.get("retention_snapshot_digest")
            != common_requirement.get("retention_snapshot_digest")
            or retrieval.get("index_identity")
            != common_requirement.get("index_identity")
        ):
            raise ValueError("DG25_S4A_TEMPORAL_ROW_SCOPE_OR_SNAPSHOT_DRIFT")


def _query_interval(requirement: EvidenceRequirementV02) -> EventTimeIntervalV02:
    constraint = requirement.temporal_constraints
    if (
        constraint is None
        or constraint.boundary != "CLOSED_OPEN"
        or constraint.start is None
        or constraint.end is None
        or constraint.time_axis != "EVENT_TIME"
    ):
        raise ValueError("DG25_S4A_QUERY_INTERVAL_INVALID")
    return build_event_time_interval_v02(
        interval_start=constraint.start,
        interval_end_exclusive=constraint.end,
        timezone=constraint.timezone or "UTC",
        precision="RELATIVE_RANGE",
        basis="SOURCE_RELATIVE",
    )


def _temporal_candidates(
    *,
    requirement: EvidenceRequirementV02,
    query_interval: EventTimeIntervalV02,
    spans: Sequence[EvidenceSpan],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    bindings: Sequence[RequirementBinding],
    applicability: Sequence[NonTemporalApplicability],
    raw_rank_by_evidence: Mapping[str, int],
    raw_occurrence_by_evidence: Mapping[str, str],
) -> list[_TemporalCandidate]:
    span_by_id = {item.span_id: item for item in spans}
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    binding_by_id = {item.interpretation_id: item for item in bindings}
    candidates: list[_TemporalCandidate] = []
    for item in applicability:
        if item.requirement_id != requirement.slot_id or item.status == "REJECTED":
            continue
        interpretation = interpretation_by_id[item.interpretation_id]
        binding = binding_by_id[item.interpretation_id]
        span = span_by_id[interpretation.span_id]
        if binding.compatibility.episode == "FAIL" or not _occurred_event(
            interpretation
        ):
            continue
        interval = _event_interval(interpretation, span)
        applicability_status = item.status
        candidates.append(
            _TemporalCandidate(
                raw_rank=raw_rank_by_evidence[span.source_evidence_id],
                raw_occurrence_id=raw_occurrence_by_evidence[span.source_evidence_id],
                evidence_id=span.source_evidence_id,
                source_turn_ref=span.source_turn_ref,
                span=span,
                interpretation=interpretation,
                applicability_status=applicability_status,
                point_membership=_point_membership(
                    interpretation,
                    query_interval,
                ),
                interval=interval,
                interval_membership=classify_range_membership(
                    interval,
                    query_interval,
                ),
            )
        )
    return sorted(
        candidates,
        key=lambda value: (
            value.raw_rank,
            value.source_turn_ref,
            value.span.start,
            value.interpretation.interpretation_id,
        ),
    )


def _occurred_event(interpretation: EvidenceInterpretationCandidate) -> bool:
    value = interpretation.value
    return isinstance(value, Mapping) and value.get("event_status") == "OCCURRED"


def _event_interval(
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
) -> EventTimeIntervalV02:
    event_time = interpretation.event_time
    if event_time is None or event_time.start is None:
        if span.source_timestamp is None:
            raise ValueError("DG25_S4A_EVENT_AND_SOURCE_TIME_UNAVAILABLE")
        return build_event_time_interval_v02(
            interval_start=span.source_timestamp,
            interval_end_exclusive=span.source_timestamp + timedelta(microseconds=1),
            timezone=_timezone_name(span.source_timestamp),
            precision="INSTANT",
            basis="SOURCE_OBSERVED_PROXY",
            grounded_span_ids=[span.span_id],
            ambiguity_reasons=[_SOURCE_PROXY_AMBIGUITY],
        )
    precision = _event_precision(interpretation)
    end = event_time.end
    if end is None or end <= event_time.start:
        end = event_time.start + (
            timedelta(days=1) if precision == "DAY" else timedelta(microseconds=1)
        )
    basis: EventTimeBasisV02 = (
        "EXPLICIT_CALENDAR"
        if interpretation.time_basis == "EXPLICIT_EVENT_TIME"
        else "SOURCE_RELATIVE"
    )
    return build_event_time_interval_v02(
        interval_start=event_time.start,
        interval_end_exclusive=end,
        timezone=_timezone_name(event_time.start),
        precision=precision,
        basis=basis,
        grounded_span_ids=[span.span_id],
    )


def _event_precision(
    interpretation: EvidenceInterpretationCandidate,
) -> EventTimePrecisionV02:
    event_time = interpretation.event_time
    if event_time is None or event_time.start is None:
        return "INSTANT"
    start = event_time.start
    normalized = (event_time.normalized_from or "").casefold()
    if "weekend" in normalized:
        return "WEEKEND"
    if "week" in normalized:
        return "WEEK"
    if any(month in normalized for month in _MONTH_NAMES):
        return (
            "MONTH" if event_time.end is not None and event_time.end > start else "DAY"
        )
    if event_time.end is not None and event_time.end > start:
        return "RELATIVE_RANGE"
    provenance = event_time.anchor_provenance
    if isinstance(provenance, Mapping) and provenance.get("precision") == "DAY":
        return "DAY"
    return "DAY" if interpretation.time_basis == "EXPLICIT_EVENT_TIME" else "INSTANT"


_MONTH_NAMES = frozenset(
    {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)


def _timezone_name(value: datetime) -> str:
    return value.tzname() or "UTC"


def _point_membership(
    interpretation: EvidenceInterpretationCandidate,
    query_interval: EventTimeIntervalV02,
) -> RangeMembershipV01:
    event_time = interpretation.event_time
    if event_time is None or event_time.start is None:
        return "EVENT_TIME_UNRESOLVED"
    if (
        query_interval.interval_start
        <= event_time.start
        < query_interval.interval_end_exclusive
    ):
        return "IN_RANGE"
    return "OUT_OF_RANGE"


def _project_arm_record(
    *,
    analysis: _CaseAnalysis,
    config: E2ArmConfigV01,
) -> dict[str, Any]:
    interval_enabled = config.interval_normalization_version is not None
    identity_enabled = config.event_identity_dedup_version is not None
    membership_by_interpretation = {
        item.interpretation.interpretation_id: (
            item.interval_membership if interval_enabled else item.point_membership
        )
        for item in analysis.candidates
    }
    identity_projection = _identity_projection(
        analysis=analysis,
        membership_by_interpretation=membership_by_interpretation,
        enabled=identity_enabled,
    )
    eligible: list[tuple[_TemporalCandidate, _BindingStatus]] = []
    for candidate in analysis.candidates:
        membership = membership_by_interpretation[
            candidate.interpretation.interpretation_id
        ]
        status = _binding_status(candidate, membership)
        if status != "NO_MATCH":
            eligible.append((candidate, status))
    eligible.sort(
        key=lambda value: (
            value[1] != "MATCH",
            value[0].raw_rank,
            value[0].source_turn_ref,
            value[0].interpretation.interpretation_id,
        )
    )
    eligible_with_duplicates = tuple(eligible)
    if identity_enabled:
        eligible = _deduplicated_eligible(eligible, identity_projection)
    selected = eligible[:_FINAL_K]
    selected_rows = [
        _selected_occurrence(
            candidate=candidate,
            status=status,
            membership=membership_by_interpretation[
                candidate.interpretation.interpretation_id
            ],
            requirement_id=analysis.requirement_id,
            identity=identity_projection.identity_by_interpretation.get(
                candidate.interpretation.interpretation_id
            ),
            lineage_candidates=_identity_lineage_candidates(
                representative=candidate,
                eligible=eligible_with_duplicates,
                projection=identity_projection,
            ),
            interval_enabled=interval_enabled,
            final_rank=final_rank,
        )
        for final_rank, (candidate, status) in enumerate(selected, start=1)
    ]
    metrics = _temporal_metrics(
        analysis.candidates,
        membership_by_interpretation,
        identity_projection,
    )
    proof_v02 = (
        _build_proof_v02(
            analysis=analysis,
            metrics=metrics,
            identity_projection=identity_projection,
        )
        if config.proof_writer_version == "bounded-range-scan-proof-v0.2"
        else None
    )
    proof_statuses = _proof_statuses(
        analysis=analysis,
        metrics=metrics,
        identity_projection=identity_projection,
        proof_v02=proof_v02,
        identity_enabled=identity_enabled,
    )
    complete = (
        bool(selected_rows)
        and all(item["binding_status"] == "MATCH" for item in selected_rows)
        and all(item["status"] == "SATISFIED" for item in proof_statuses)
    )
    return {
        "query_id": analysis.query_id,
        "query_identity": analysis.query_identity,
        "query_ir_digest": analysis.frozen_query_ir_digest,
        "requirements": [
            {
                "requirement_id": analysis.requirement_id,
                "selected_occurrences": selected_rows,
                "proof_obligations": proof_statuses,
                "sufficiency": "COMPLETE" if complete else "PARTIAL",
                "temporal_metrics": metrics,
                "t2_applicability": dict(
                    analysis.common_requirement["t2_applicability"]
                ),
                "bounded_range_scan_proof_v02": (
                    proof_v02.model_dump(mode="json") if proof_v02 is not None else None
                ),
            }
        ],
    }


def _binding_status(
    candidate: _TemporalCandidate,
    membership: RangeMembershipV01,
) -> _BindingStatus:
    if membership == "OUT_OF_RANGE":
        return "NO_MATCH"
    if candidate.applicability_status == "MATCH" and membership == "IN_RANGE":
        return "MATCH"
    return "POSSIBLE"


def _identity_projection(
    *,
    analysis: _CaseAnalysis,
    membership_by_interpretation: Mapping[str, RangeMembershipV01],
    enabled: bool,
) -> _IdentityProjection:
    if not enabled:
        return _IdentityProjection({}, None, 0)
    identities: dict[str, EventIdentityV01] = {}
    counts: defaultdict[str, int] = defaultdict(int)
    for candidate in analysis.candidates:
        membership = membership_by_interpretation[
            candidate.interpretation.interpretation_id
        ]
        if membership == "OUT_OF_RANGE":
            continue
        unresolved_reasons: list[str] = []
        if membership != "IN_RANGE":
            unresolved_reasons.append(membership)
        if candidate.applicability_status != "MATCH":
            unresolved_reasons.append("NON_TEMPORAL_APPLICABILITY_UNPROVEN")
        value = candidate.interpretation.value
        explicit_identity = (
            value.get("event_identity") if isinstance(value, Mapping) else None
        )
        participant = (
            f"explicit:{str(explicit_identity).casefold()}"
            if isinstance(explicit_identity, str) and explicit_identity
            else f"governed-episode:{candidate.span.session_id}"
        )
        actor = analysis.requirement.semantic_roles.actor
        if actor is None:
            actor = (
                candidate.span.speaker.upper()
                if candidate.span.speaker != "unknown"
                else "UNSPECIFIED_ACTOR"
            )
        identity = build_event_identity_v01(
            event_type=(
                "requirement-event:"
                + canonical_sha256(
                    {
                        "slot_id": analysis.requirement.slot_id,
                        "entities": analysis.requirement.entity_constraints,
                        "predicates": analysis.requirement.predicate_constraints,
                    }
                )[:32]
            ),
            actor_identity=actor,
            object_or_participant_identity=participant,
            occurrence_interval_digest=_identity_occurrence_interval_digest(
                candidate.interval
            ),
            source_evidence_ids=[candidate.evidence_id],
            identity_policy_version=_IDENTITY_POLICY,
            disposition="UNRESOLVED" if unresolved_reasons else "DISTINCT",
            unresolved_reasons=unresolved_reasons,
        )
        identities[candidate.interpretation.interpretation_id] = identity
        if identity.disposition != "UNRESOLVED":
            counts[identity.event_identity_digest] += 1
    deduplication = (
        deduplicate_event_identities(list(identities.values())) if identities else None
    )
    duplicate_candidate_count = sum(value - 1 for value in counts.values() if value > 1)
    return _IdentityProjection(
        identity_by_interpretation=identities,
        deduplication=deduplication,
        duplicate_candidate_count=duplicate_candidate_count,
    )


def _identity_occurrence_interval_digest(interval: EventTimeIntervalV02) -> str:
    """Return a semantic interval identity without Evidence-specific grounding."""

    return build_event_time_interval_v02(
        interval_start=interval.interval_start,
        interval_end_exclusive=interval.interval_end_exclusive,
        timezone=interval.timezone,
        precision=interval.precision,
        basis=interval.basis,
        ambiguity_reasons=interval.ambiguity_reasons,
    ).interval_digest


def _deduplicated_eligible(
    eligible: Sequence[tuple[_TemporalCandidate, _BindingStatus]],
    projection: _IdentityProjection,
) -> list[tuple[_TemporalCandidate, _BindingStatus]]:
    result: list[tuple[_TemporalCandidate, _BindingStatus]] = []
    seen: set[str] = set()
    for candidate, status in eligible:
        identity = projection.identity_by_interpretation[
            candidate.interpretation.interpretation_id
        ]
        if identity.disposition != "UNRESOLVED":
            if identity.event_identity_digest in seen:
                continue
            seen.add(identity.event_identity_digest)
        result.append((candidate, status))
    return result


def _identity_lineage_candidates(
    *,
    representative: _TemporalCandidate,
    eligible: Sequence[tuple[_TemporalCandidate, _BindingStatus]],
    projection: _IdentityProjection,
) -> tuple[_TemporalCandidate, ...]:
    identity = projection.identity_by_interpretation.get(
        representative.interpretation.interpretation_id
    )
    if identity is None or identity.disposition == "UNRESOLVED":
        return (representative,)
    return tuple(
        candidate
        for candidate, _ in eligible
        if (
            candidate_identity := projection.identity_by_interpretation.get(
                candidate.interpretation.interpretation_id
            )
        )
        is not None
        and candidate_identity.disposition != "UNRESOLVED"
        and candidate_identity.event_identity_digest == identity.event_identity_digest
    )


def _selected_occurrence(
    *,
    candidate: _TemporalCandidate,
    status: _BindingStatus,
    membership: RangeMembershipV01,
    requirement_id: str,
    identity: EventIdentityV01 | None,
    lineage_candidates: Sequence[_TemporalCandidate],
    interval_enabled: bool,
    final_rank: int,
) -> dict[str, Any]:
    resolved_identity = (
        identity.event_identity_digest
        if identity is not None and identity.disposition != "UNRESOLVED"
        else None
    )
    return {
        "occurrence_id": canonical_sha256(
            {
                "schema": "milai.dg25.e2-selected-occurrence.v0.1",
                "raw_occurrence_id": candidate.raw_occurrence_id,
                "interpretation_id": candidate.interpretation.interpretation_id,
            }
        ),
        "evidence_id": candidate.evidence_id,
        "source_turn_ref": candidate.source_turn_ref,
        "requirement_id": requirement_id,
        "binding_status": status,
        "matched_roles": [requirement_id] if status == "MATCH" else [],
        "discovery_lineage": [
            {
                "channel": "TEMPORAL_EVENT",
                "channel_rank": lineage.raw_rank,
                "occurrence_id": lineage.raw_occurrence_id,
                "interpretation_id": lineage.interpretation.interpretation_id,
            }
            for lineage in lineage_candidates
        ],
        "selected_by_reservation": final_rank == 1,
        "final_rank": final_rank,
        "legal": True,
        "range_membership": membership,
        "event_time_interval_digest": (
            candidate.interval.interval_digest if interval_enabled else None
        ),
        "event_identity_digest": resolved_identity,
        "event_identity_disposition": (
            identity.disposition if identity is not None else "NOT_ENABLED"
        ),
    }


def _temporal_metrics(
    candidates: Sequence[_TemporalCandidate],
    membership_by_interpretation: Mapping[str, RangeMembershipV01],
    identity_projection: _IdentityProjection,
) -> dict[str, Any]:
    memberships = [
        membership_by_interpretation[item.interpretation.interpretation_id]
        for item in candidates
    ]
    dedup = identity_projection.deduplication
    return {
        "candidate_event_count": len(candidates),
        "in_range_event_count": memberships.count("IN_RANGE"),
        "out_of_range_event_count": memberships.count("OUT_OF_RANGE"),
        "ambiguous_time_count": memberships.count("AMBIGUOUS_RANGE_MEMBERSHIP"),
        "unresolved_event_count": memberships.count("EVENT_TIME_UNRESOLVED"),
        "event_identity_policy_version": (
            _IDENTITY_POLICY if dedup is not None else "NOT_ENABLED"
        ),
        "distinct_event_count": (
            len(dedup.distinct_event_identity_digests) if dedup is not None else 0
        ),
        "duplicate_group_count": (
            len(dedup.duplicate_groups) if dedup is not None else 0
        ),
        "duplicate_candidate_count": identity_projection.duplicate_candidate_count,
        "unresolved_duplicate_group_count": (
            len(dedup.unresolved_event_identity_digests) if dedup is not None else 0
        ),
        "dedup_complete": dedup.dedup_complete if dedup is not None else False,
    }


def _build_proof_v02(
    *,
    analysis: _CaseAnalysis,
    metrics: Mapping[str, Any],
    identity_projection: _IdentityProjection,
) -> BoundedRangeScanProofV02:
    legacy = analysis.legacy_proof
    source_count = _required_int(legacy.source_count, "legacy source count")
    projected_count = _required_int(legacy.projected_count, "legacy projected count")
    target_watermark = _required_int(legacy.target_watermark, "legacy target watermark")
    projection_watermark = _required_int(
        legacy.projection_watermark, "legacy projection watermark"
    )
    max_items = _required_int(legacy.max_items, "legacy max items")
    if max_items != _RANGE_SCAN_MAX_ROWS:
        raise ValueError("DG25_S4A_RANGE_SCAN_MAX_ROWS_DRIFT")
    raw_fallback_closed = (
        legacy.source_partition_closed
        and legacy.returned_count == source_count
        and not legacy.dead_letter_gap
    )
    dedup = identity_projection.deduplication
    if dedup is None:
        raise ValueError("DG25_S4A_PROOF_V02_REQUIRES_IDENTITY_DEDUP")
    event_set = BoundedRangeEventSetClosureV02(
        candidate_event_count=int(metrics["candidate_event_count"]),
        in_range_event_count=int(metrics["in_range_event_count"]),
        out_of_range_event_count=int(metrics["out_of_range_event_count"]),
        ambiguous_time_count=int(metrics["ambiguous_time_count"]),
        unresolved_event_count=int(metrics["unresolved_event_count"]),
        event_identity_policy_version=_IDENTITY_POLICY,
    )
    distinct_in_range = {
        identity.event_identity_digest
        for interpretation_id, identity in identity_projection.identity_by_interpretation.items()
        if identity.disposition != "UNRESOLVED"
        and next(
            candidate.interval_membership
            for candidate in analysis.candidates
            if candidate.interpretation.interpretation_id == interpretation_id
        )
        == "IN_RANGE"
    }
    return build_bounded_range_scan_proof_v02(
        query_closure=BoundedRangeQueryClosureV02(
            query_ir_digest=analysis.frozen_query_ir_digest,
            requirement_state_digest=canonical_sha256(
                {
                    "schema": "milai.dg25.e2-requirement-state-input.v0.1",
                    "query_identity": analysis.query_identity,
                    "requirement_id": analysis.requirement_id,
                    "source_snapshot_identity": analysis.common_requirement.get(
                        "source_snapshot_identity"
                    ),
                }
            ),
            event_time_interval=analysis.query_interval,
            timezone=analysis.query_interval.timezone,
        ),
        snapshot_closure=BoundedRangeSnapshotClosureV02(
            transaction_snapshot_identity=str(
                analysis.common_requirement["source_snapshot_identity"]
            ),
            source_partition_snapshot_identity=str(
                analysis.common_requirement["source_snapshot_identity"]
            ),
            access_snapshot_identity=str(
                analysis.common_requirement["permission_snapshot_digest"]
            ),
            revocation_snapshot_identity=str(
                analysis.common_requirement["retention_snapshot_digest"]
            ),
            snapshot_stable=True,
        ),
        scan_closure=BoundedRangeScanClosureV02(
            source_partition_closed=legacy.source_partition_closed,
            range_scan_complete=(
                legacy.returned_count == source_count == analysis.evidence_row_count
            ),
            max_items=max_items,
            max_items_hit=legacy.returned_count >= max_items,
            unreadable_source_count=legacy.unreadable_evidence_count,
        ),
        projection_closure=BoundedRangeProjectionClosureV02(
            projection_version="official-runtime-current",
            temporal_normalizer_version="event-time-interval-v0.2",
            target_watermark=target_watermark,
            projection_watermark=projection_watermark,
            projection_watermark_covered=legacy.projection_watermark_covered,
            dead_letter_gap=legacy.dead_letter_gap,
            unprojected_source_count=max(0, source_count - projected_count),
            raw_fallback_closed=raw_fallback_closed,
        ),
        event_set_closure=event_set,
        dedup_closure=BoundedRangeDedupClosureV02(
            dedup_policy_version=_IDENTITY_POLICY,
            duplicate_group_count=len(dedup.duplicate_groups),
            unresolved_duplicate_group_count=len(
                dedup.unresolved_event_identity_digests
            ),
            distinct_event_count=len(distinct_in_range),
            dedup_complete=dedup.dedup_complete,
        ),
        access_closure=BoundedRangeAccessClosureV02(
            policy_digest=str(
                analysis.common_requirement["permission_snapshot_digest"]
            ),
            unreadable_evidence_count=legacy.unreadable_evidence_count,
            access_snapshot_valid=legacy.unreadable_evidence_count == 0,
        ),
    )


def _proof_statuses(
    *,
    analysis: _CaseAnalysis,
    metrics: Mapping[str, Any],
    identity_projection: _IdentityProjection,
    proof_v02: BoundedRangeScanProofV02 | None,
    identity_enabled: bool,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for obligation in analysis.proof_obligations:
        kind = str(obligation["kind"])
        if proof_v02 is None:
            satisfied = _legacy_obligation_satisfied(
                kind=kind,
                legacy=analysis.legacy_proof,
                metrics=metrics,
                identity_projection=identity_projection,
                identity_enabled=identity_enabled,
            )
        else:
            satisfied = _v02_obligation_satisfied(kind, proof_v02)
        result.append(
            {
                "obligation_id": str(obligation["obligation_id"]),
                "status": "SATISFIED" if satisfied else "NOT_SATISFIED",
            }
        )
    return result


def _legacy_obligation_satisfied(
    *,
    kind: str,
    legacy: LegacyBoundedRangeScanProofV01,
    metrics: Mapping[str, Any],
    identity_projection: _IdentityProjection,
    identity_enabled: bool,
) -> bool:
    if kind == "ACCESS_SNAPSHOT":
        return legacy.unreadable_evidence_count == 0
    if kind == "EVENT_TIME_RESOLUTION":
        return (
            int(metrics["ambiguous_time_count"]) == 0
            and int(metrics["unresolved_event_count"]) == 0
        )
    if kind == "DEDUP_COMPLETENESS" and identity_enabled:
        dedup = identity_projection.deduplication
        return dedup is not None and dedup.dedup_complete
    if legacy.status != "COMPLETE":
        return False
    if kind == "SOURCE_PARTITION_CLOSURE":
        return legacy.source_partition_closed
    if kind == "PROJECTION_CLOSURE":
        return legacy.projection_watermark_covered
    if kind == "RAW_FALLBACK_CLOSURE":
        return not legacy.dead_letter_gap
    if kind == "DEDUP_COMPLETENESS":
        return legacy.source_partition_closed
    return kind == "BOUNDED_RANGE_SCAN"


def _v02_obligation_satisfied(
    kind: str,
    proof: BoundedRangeScanProofV02,
) -> bool:
    if kind == "BOUNDED_RANGE_SCAN":
        return proof.status == "COMPLETE"
    if kind == "SOURCE_PARTITION_CLOSURE":
        return (
            proof.scan_closure.source_partition_closed
            and proof.scan_closure.range_scan_complete
            and not proof.scan_closure.max_items_hit
        )
    if kind == "EVENT_TIME_RESOLUTION":
        return (
            proof.event_set_closure.ambiguous_time_count == 0
            and proof.event_set_closure.unresolved_event_count == 0
        )
    if kind == "DEDUP_COMPLETENESS":
        return (
            proof.dedup_closure.dedup_complete
            and proof.dedup_closure.unresolved_duplicate_group_count == 0
        )
    if kind == "PROJECTION_CLOSURE":
        return (
            proof.projection_closure.projection_watermark_covered
            and not proof.projection_closure.dead_letter_gap
            and (
                proof.projection_closure.unprojected_source_count == 0
                or proof.projection_closure.raw_fallback_closed
            )
        )
    if kind == "RAW_FALLBACK_CLOSURE":
        return proof.projection_closure.raw_fallback_closed
    if kind == "ACCESS_SNAPSHOT":
        return (
            proof.access_closure.access_snapshot_valid
            and proof.access_closure.unreadable_evidence_count == 0
        )
    return False


def _validate_t1_t2_noop(
    arm_outputs: Mapping[str, Mapping[str, Any]],
) -> None:
    t1 = _mapping(arm_outputs.get("T1"), "T1 output")
    t2 = _mapping(arm_outputs.get("T2"), "T2 output")
    if t1.get("records") != t2.get("records"):
        raise ValueError("DG25_S4A_T2_NOT_APPLICABLE_SEMANTIC_DRIFT")
    if t1.get("cost_ledger") != t2.get("cost_ledger"):
        raise ValueError("DG25_S4A_T2_NOT_APPLICABLE_COST_DRIFT")


def _required_int(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"DG25_S4A_{label.upper().replace(' ', '_')}_MISSING")
    return value


def _required_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"DG25_S4A_REQUIRED_TEXT_MISSING:{key}")
    return item


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _mapping_sequence(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{label} items must be mappings")
        result.append(item)
    return result


__all__ = [
    "generate_e2_all_arm_bundle",
    "validate_s4a_authorization",
]
