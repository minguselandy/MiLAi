from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from milai_lab.product11 import (
    CAPABILITY_SHAPES,
    InstanceGroup,
    canonical_sha256,
    derive_x0_opportunity_assignments,
    validate_a0_trace_seal,
    validate_source_fixture,
    validate_x0_opportunity_assignments,
)

PROPOSAL_SCHEMA = "milai-product11-subagent-proposal-v0.1"
LABEL_SCHEMA = "milai-product11-subagent-instance-groups-v0.1"
PACKET_SCHEMA = "milai-product11-subagent-review-packet-v0.1"
ORCHESTRATION_SCHEMA = "milai-product11-subagent-orchestration-v0.1"
MERGE_SCHEMA = "milai-product11-subagent-merge-result-v0.2"
ANNOTATOR_ROLE = "SUBAGENT_ANNOTATOR"
REVIEWER_ROLE = "SUBAGENT_REVIEWER"

_PACKET_KEYS = {
    "schema_version",
    "packet_id",
    "role",
    "classification",
    "formal_source",
    "source_only",
    "contains_model_proposals",
    "contains_product_output",
    "contains_a0_trace",
    "contains_treatment_output",
    "source_fixture_file_sha256",
    "source_fixture_semantic_sha256",
    "case_order_sha256",
    "case_count",
    "instructions",
    "output_requirements",
    "cases",
}
_PACKET_CASE_KEYS = {"case_id", "question", "capability_shapes", "sessions"}
_FORBIDDEN_PACKET_KEYS = {
    "identity_sets",
    "continuation_opportunity",
    "intra_source_opportunity",
    "control_or_already_complete",
    "human_attestation",
    "human_adjudication_status",
    "instance_groups",
    "acceptable_evidence_ids",
    "acceptable_turn_refs",
    "a0_trace_sha256",
    "treatment_output",
    "product_output",
    "peer_output",
    "proposal_output",
}

_PROPOSAL_KEYS = {
    "schema_version",
    "role",
    "identity",
    "review_status",
    "source_packet_sha256",
    "cases",
}
_CASE_KEYS = {"case_id", "instance_groups"}
_GROUP_KEYS = {
    "group_id",
    "acceptable_evidence_ids",
    "acceptable_turn_refs",
    "source_ids",
    "session_ids",
    "required_for_answer",
    "notes",
}
_FORBIDDEN_PROPOSAL_KEYS = {
    "continuation_opportunity",
    "intra_source_opportunity",
    "control_or_already_complete",
    "human_attestation",
    "human_adjudication_status",
}
_ORCHESTRATION_KEYS = {
    "schema_version",
    "run_id",
    "created_at",
    "created_before_execution",
    "status",
    "classification",
    "source_fixture",
    "source_fixture_file_sha256",
    "source_fixture_semantic_sha256",
    "a0_trace",
    "a0_trace_sha256",
    "producers",
    "isolation",
    "formal_files_accessed",
    "formal_cases_scored",
}
_PRODUCER_KEYS = {
    "role",
    "orchestrator_assigned_agent_id",
    "invocation_id",
    "model_id",
    "packet",
    "packet_sha256",
    "expected_proposal",
}
_ISOLATION_KEYS = {
    "peer_output_supplied",
    "proposal_output_supplied",
    "a0_trace_supplied",
    "treatment_output_supplied",
}


def build_subagent_review_packet(
    fixture: Mapping[str, Any],
    *,
    role: str,
    packet_id: str,
    fixture_file_sha256: str,
) -> dict[str, Any]:
    """Build an immutable source-only packet for one independent subagent."""

    validate_source_fixture(fixture)
    if role not in {ANNOTATOR_ROLE, REVIEWER_ROLE}:
        raise ValueError("Product-11 subagent packet role is invalid")
    if not packet_id.strip() or not fixture_file_sha256.strip():
        raise ValueError("Product-11 subagent packet provenance is incomplete")
    cases = [
        {
            "case_id": str(case["case_id"]),
            "question": str(case["question"]),
            "capability_shapes": list(case["capability_shapes"]),
            "sessions": case["sessions"],
        }
        for case in fixture["cases"]
    ]
    case_ids = [str(case["case_id"]) for case in fixture["cases"]]
    packet = {
        "schema_version": PACKET_SCHEMA,
        "packet_id": packet_id,
        "role": role,
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "source_only": True,
        "contains_model_proposals": False,
        "contains_product_output": False,
        "contains_a0_trace": False,
        "contains_treatment_output": False,
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "case_order_sha256": canonical_sha256(case_ids),
        "case_count": len(cases),
        "instructions": [
            "Review every case independently using only this source packet.",
            "Partition answer-required real-world instances and cite exact turn_ref values.",
            "The same exact turn_ref cannot belong to two distinct groups.",
            "Source/session overlap across distinct groups is allowed.",
            "Do not inspect A0, treatment output, the peer packet, or any proposal output.",
            "acceptable_evidence_ids must be empty because this packet contains no "
            "Evidence-ID mapping.",
            "This is model-generated development judgment, never HUMAN adjudication "
            "or formal gold.",
        ],
        "output_requirements": [
            f"schema_version={PROPOSAL_SCHEMA}",
            f"role={role}",
            "review_status=COMPLETE",
            "preserve all 24 case IDs in packet order",
            "provide local group IDs, exact turn refs, required_for_answer=true, "
            "and optional notes",
        ],
        "cases": cases,
    }
    validate_subagent_review_packet(
        fixture,
        packet,
        expected_role=role,
        expected_fixture_file_sha256=fixture_file_sha256,
    )
    return packet


def validate_subagent_review_packet(
    fixture: Mapping[str, Any],
    packet: Mapping[str, Any],
    *,
    expected_role: str,
    expected_fixture_file_sha256: str,
) -> dict[str, Any]:
    """Validate that a subagent packet contains source data and no recursive result channel."""

    validate_source_fixture(fixture)
    if expected_role not in {ANNOTATOR_ROLE, REVIEWER_ROLE}:
        raise ValueError("Product-11 subagent packet role is invalid")
    if set(packet) != _PACKET_KEYS:
        raise ValueError("Product-11 subagent packet fields are invalid")
    forbidden = _FORBIDDEN_PACKET_KEYS.intersection(_recursive_keys(packet))
    if forbidden:
        raise ValueError(
            f"Product-11 subagent packet contains forbidden result fields: {sorted(forbidden)}"
        )
    expected_cases = [
        {
            "case_id": str(case["case_id"]),
            "question": str(case["question"]),
            "capability_shapes": list(case["capability_shapes"]),
            "sessions": case["sessions"],
        }
        for case in fixture["cases"]
    ]
    actual_cases = packet.get("cases")
    if not isinstance(actual_cases, list) or actual_cases != expected_cases:
        raise ValueError("Product-11 subagent packet source cases drifted")
    if any(
        not isinstance(case, Mapping) or set(case) != _PACKET_CASE_KEYS
        for case in actual_cases
    ):
        raise ValueError("Product-11 subagent packet case fields are invalid")
    expected_case_ids = [str(case["case_id"]) for case in fixture["cases"]]
    if (
        packet.get("schema_version") != PACKET_SCHEMA
        or packet.get("role") != expected_role
        or packet.get("classification") != "OPENED_DEVELOPMENT_ONLY"
        or packet.get("formal_source") is not False
        or packet.get("source_only") is not True
        or packet.get("contains_model_proposals") is not False
        or packet.get("contains_product_output") is not False
        or packet.get("contains_a0_trace") is not False
        or packet.get("contains_treatment_output") is not False
        or packet.get("source_fixture_file_sha256") != expected_fixture_file_sha256
        or packet.get("source_fixture_semantic_sha256") != canonical_sha256(fixture)
        or packet.get("case_order_sha256") != canonical_sha256(expected_case_ids)
        or packet.get("case_count") != 24
    ):
        raise ValueError("Product-11 subagent packet provenance is invalid")
    for key in ("packet_id",):
        if not isinstance(packet.get(key), str) or not str(packet[key]).strip():
            raise ValueError(f"Product-11 subagent packet {key} is invalid")
    if not isinstance(packet.get("instructions"), list) or not packet["instructions"]:
        raise ValueError("Product-11 subagent packet instructions are invalid")
    if not isinstance(packet.get("output_requirements"), list) or not packet[
        "output_requirements"
    ]:
        raise ValueError("Product-11 subagent packet output requirements are invalid")
    return {
        "schema_version": "milai-product11-subagent-packet-validation-v0.1",
        "status": "VALID_SOURCE_ONLY_SUBAGENT_PACKET",
        "role": expected_role,
        "case_count": 24,
        "case_order_sha256": canonical_sha256(expected_case_ids),
        "source_fixture_file_sha256": expected_fixture_file_sha256,
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "formal_files_accessed": False,
    }


def validate_subagent_orchestration_manifest(
    fixture: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    fixture_file_sha256: str,
    a0_trace_sha256: str,
    packet_sha256_by_role: Mapping[str, str],
) -> dict[str, Any]:
    """Validate the immutable pre-execution assignment and isolation contract."""

    validate_source_fixture(fixture)
    if set(manifest) != _ORCHESTRATION_KEYS:
        raise ValueError("Product-11 subagent orchestration fields are invalid")
    if (
        manifest.get("schema_version") != ORCHESTRATION_SCHEMA
        or manifest.get("created_before_execution") is not True
        or manifest.get("status") != "SEALED_BEFORE_SUBAGENT_EXECUTION"
        or manifest.get("classification") != "OPENED_DEVELOPMENT_ONLY"
        or manifest.get("source_fixture_file_sha256") != fixture_file_sha256
        or manifest.get("source_fixture_semantic_sha256") != canonical_sha256(fixture)
        or manifest.get("a0_trace_sha256") != a0_trace_sha256
        or manifest.get("formal_files_accessed") is not False
        or manifest.get("formal_cases_scored") != 0
    ):
        raise ValueError("Product-11 subagent orchestration provenance is invalid")
    for key in ("run_id", "created_at", "source_fixture", "a0_trace"):
        if not isinstance(manifest.get(key), str) or not str(manifest[key]).strip():
            raise ValueError(f"Product-11 subagent orchestration {key} is invalid")
    isolation = manifest.get("isolation")
    if not isinstance(isolation, Mapping) or set(isolation) != _ISOLATION_KEYS:
        raise ValueError("Product-11 subagent isolation declaration is invalid")
    if any(isolation.get(key) is not False for key in _ISOLATION_KEYS):
        raise ValueError("Product-11 subagent orchestration did not preserve isolation")
    producers = manifest.get("producers")
    if not isinstance(producers, Mapping) or set(producers) != {
        "annotator",
        "reviewer",
    }:
        raise ValueError("Product-11 subagent producer assignments are invalid")
    normalized: dict[str, dict[str, Any]] = {}
    for label, expected_role in (
        ("annotator", ANNOTATOR_ROLE),
        ("reviewer", REVIEWER_ROLE),
    ):
        producer = producers.get(label)
        if not isinstance(producer, Mapping) or set(producer) != _PRODUCER_KEYS:
            raise ValueError("Product-11 subagent producer assignment fields are invalid")
        if (
            producer.get("role") != expected_role
            or producer.get("packet_sha256") != packet_sha256_by_role.get(expected_role)
        ):
            raise ValueError("Product-11 subagent producer packet binding is invalid")
        for key in (
            "orchestrator_assigned_agent_id",
            "invocation_id",
            "model_id",
            "packet",
            "expected_proposal",
        ):
            if not isinstance(producer.get(key), str) or not str(producer[key]).strip():
                raise ValueError(f"Product-11 subagent producer {key} is invalid")
        normalized[label] = dict(producer)
    if normalized["annotator"]["orchestrator_assigned_agent_id"] == normalized[
        "reviewer"
    ]["orchestrator_assigned_agent_id"]:
        raise ValueError("Product-11 subagent identities are not distinct")
    if normalized["annotator"]["invocation_id"] == normalized["reviewer"][
        "invocation_id"
    ]:
        raise ValueError("Product-11 subagent invocation identities are not distinct")
    return {
        "schema_version": "milai-product11-subagent-orchestration-validation-v0.1",
        "status": "VALID_PREEXECUTION_SUBAGENT_ORCHESTRATION",
        "run_id": manifest["run_id"],
        "producers": normalized,
        "isolation": dict(isolation),
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }


def validate_subagent_proposal(
    fixture: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    expected_role: str,
    expected_identity: str,
    expected_packet_sha256: str,
) -> dict[str, Any]:
    """Validate one source-only subagent proposal without consulting its peer."""

    validate_source_fixture(fixture)
    if expected_role not in {ANNOTATOR_ROLE, REVIEWER_ROLE}:
        raise ValueError("Product-11 subagent role is invalid")
    if set(proposal) != _PROPOSAL_KEYS:
        raise ValueError("Product-11 subagent proposal fields are invalid")
    if _FORBIDDEN_PROPOSAL_KEYS.intersection(_recursive_keys(proposal)):
        raise ValueError("Product-11 subagent proposal contains adjudication-only fields")
    if (
        proposal.get("schema_version") != PROPOSAL_SCHEMA
        or proposal.get("role") != expected_role
        or proposal.get("identity") != expected_identity
        or proposal.get("review_status") != "COMPLETE"
        or proposal.get("source_packet_sha256") != expected_packet_sha256
    ):
        raise ValueError("Product-11 subagent proposal provenance is invalid")

    raw_cases = proposal.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 24:
        raise ValueError("Product-11 subagent proposal requires 24 cases")
    fixture_cases = fixture["cases"]
    expected_case_ids = [str(case["case_id"]) for case in fixture_cases]
    actual_case_ids = [str(case.get("case_id")) for case in raw_cases]
    if actual_case_ids != expected_case_ids:
        raise ValueError("Product-11 subagent proposal case order drifted")

    groups_by_case: dict[str, list[dict[str, Any]]] = {}
    for source_case, raw_case in zip(fixture_cases, raw_cases, strict=True):
        if not isinstance(raw_case, Mapping) or set(raw_case) != _CASE_KEYS:
            raise ValueError("Product-11 subagent case fields are invalid")
        case_id = str(source_case["case_id"])
        groups_by_case[case_id] = _normalize_groups(raw_case, source_case=source_case)
    return {
        "schema_version": "milai-product11-subagent-proposal-validation-v0.1",
        "status": "READY_FOR_INDEPENDENT_SUBAGENT_MERGE",
        "role": expected_role,
        "identity": expected_identity,
        "case_count": len(groups_by_case),
        "group_count": sum(len(groups) for groups in groups_by_case.values()),
        "source_packet_sha256": expected_packet_sha256,
        "groups_by_case": groups_by_case,
        "human_adjudication_status": "NOT_PERFORMED",
        "model_generated_judgment": True,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }


def merge_independent_subagent_proposals(
    fixture: Mapping[str, Any],
    trace_rows: Sequence[Mapping[str, Any]],
    annotator_proposal: Mapping[str, Any],
    reviewer_proposal: Mapping[str, Any],
    *,
    fixture_file_sha256: str,
    a0_trace_sha256: str,
    annotator_packet_sha256: str,
    reviewer_packet_sha256: str,
    annotator_proposal_sha256: str,
    reviewer_proposal_sha256: str,
    orchestration_manifest_sha256: str,
    annotator_envelope: Mapping[str, Any],
    reviewer_envelope: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge full exact agreement without representing model judgment as human gold."""

    fixture_summary = validate_source_fixture(fixture)
    trace_summary = validate_a0_trace_seal(trace_rows)
    annotator = validate_subagent_proposal(
        fixture,
        annotator_proposal,
        expected_role=ANNOTATOR_ROLE,
        expected_identity=str(annotator_envelope.get("orchestrator_assigned_agent_id")),
        expected_packet_sha256=annotator_packet_sha256,
    )
    reviewer = validate_subagent_proposal(
        fixture,
        reviewer_proposal,
        expected_role=REVIEWER_ROLE,
        expected_identity=str(reviewer_envelope.get("orchestrator_assigned_agent_id")),
        expected_packet_sha256=reviewer_packet_sha256,
    )
    left_envelope = _validate_envelope(
        annotator_envelope,
        expected_role=ANNOTATOR_ROLE,
        expected_input_sha256=annotator_packet_sha256,
        expected_output_sha256=annotator_proposal_sha256,
    )
    right_envelope = _validate_envelope(
        reviewer_envelope,
        expected_role=REVIEWER_ROLE,
        expected_input_sha256=reviewer_packet_sha256,
        expected_output_sha256=reviewer_proposal_sha256,
    )
    if left_envelope["orchestrator_assigned_agent_id"] == right_envelope[
        "orchestrator_assigned_agent_id"
    ]:
        raise ValueError("Product-11 subagent identities are not distinct")
    if left_envelope["invocation_id"] == right_envelope["invocation_id"]:
        raise ValueError("Product-11 subagent invocation identities are not distinct")

    conflicts: list[dict[str, str]] = []
    agreed_groups: dict[str, list[dict[str, Any]]] = {}
    for source_case in fixture["cases"]:
        case_id = str(source_case["case_id"])
        left = annotator["groups_by_case"][case_id]
        right = reviewer["groups_by_case"][case_id]
        if left != right:
            conflicts.append(
                {
                    "case_id": case_id,
                    "reason": "INSTANCE_GROUP_SEMANTICS_DISAGREE",
                    "annotator_semantic_sha256": canonical_sha256(left),
                    "reviewer_semantic_sha256": canonical_sha256(right),
                }
            )
            continue
        agreed_groups[case_id] = _materialize_groups(source_case, left)

    base: dict[str, Any] = {
        "schema_version": MERGE_SCHEMA,
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "adjudication_provenance": "SUBAGENT_SEALED",
        "human_adjudication_status": "NOT_PERFORMED",
        "model_generated_judgment": True,
        "seal_authority": "USER_AUTHORIZED_SUBAGENT_BRANCH",
        "claim_ceiling": "OPENED_DEVELOPMENT_MODEL_ADJUDICATED",
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "a0_trace_sha256": a0_trace_sha256,
        "orchestration_manifest_sha256": orchestration_manifest_sha256,
        "producer_a": left_envelope,
        "producer_b": right_envelope,
        "agreement_case_count": 24 - len(conflicts),
        "conflict_case_count": len(conflicts),
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "fixture": fixture_summary,
        "a0_trace": trace_summary,
    }
    if conflicts:
        return {
            **base,
            "status": "BLOCKED_PRODUCT11_SUBAGENT_SEMANTIC_DISAGREEMENT",
            "exact_semantic_agreement": False,
            "conflicts": conflicts,
            "adjudicated_rows": None,
        }

    rows: list[dict[str, Any]] = [
        {
            "record_type": "manifest",
            "schema_version": LABEL_SCHEMA,
            "classification": "OPENED_DEVELOPMENT_ONLY",
            "adjudication_provenance": "SUBAGENT_SEALED",
            "subagent_adjudication_status": "COMPLETE",
            "human_adjudication_status": "NOT_PERFORMED",
            "model_generated_judgment": True,
            "seal_authority": "USER_AUTHORIZED_SUBAGENT_BRANCH",
            "claim_ceiling": "OPENED_DEVELOPMENT_MODEL_ADJUDICATED",
            "case_count": 24,
            "producer_a": left_envelope,
            "producer_b": right_envelope,
            "exact_semantic_agreement": True,
            "source_fixture_file_sha256": fixture_file_sha256,
            "source_fixture_semantic_sha256": canonical_sha256(fixture),
            "a0_trace_sha256": a0_trace_sha256,
            "orchestration_manifest_sha256": orchestration_manifest_sha256,
            "formal_files_accessed": False,
            "formal_cases_scored": 0,
        }
    ]
    for source_case in fixture["cases"]:
        case_id = str(source_case["case_id"])
        rows.append(
            {
                "record_type": "case",
                "case_id": case_id,
                "capability_shapes": source_case["capability_shapes"],
                "instance_groups": agreed_groups[case_id],
                "continuation_opportunity": False,
                "intra_source_opportunity": False,
                "control_or_already_complete": False,
                "subagent_adjudication_status": "COMPLETE",
                "human_adjudication_status": "NOT_PERFORMED",
                "model_generated_judgment": True,
            }
        )
    derived = derive_x0_opportunity_assignments(fixture, rows, trace_rows)
    for row in rows[1:]:
        row.update(derived["case_assignments"][str(row["case_id"])])
    seal = validate_subagent_seal(fixture, rows, require_opportunity_gate=False)
    opportunity = validate_x0_opportunity_assignments(fixture, rows, trace_rows)
    gate_passed = bool(seal["opportunity_gate_passed"])
    return {
        **base,
        **opportunity,
        "subagent_group_count": seal["group_count"],
        "opportunity_gate_passed": gate_passed,
        "exact_semantic_agreement": True,
        "status": (
            "READY_FOR_X0_SUBAGENT_SEAL"
            if gate_passed
            else "READY_FOR_INSUFFICIENT_SUBAGENT_OPPORTUNITY_TERMINAL_SEAL"
        ),
        "conflicts": [],
        "adjudicated_rows": rows,
    }


def validate_subagent_seal(
    fixture: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    require_opportunity_gate: bool = True,
) -> dict[str, Any]:
    """Validate a model-adjudicated label seal on its own provenance path."""

    fixture_summary = validate_source_fixture(fixture)
    if len(rows) != 25:
        raise ValueError("Product-11 subagent seal requires one manifest and 24 cases")
    header = rows[0]
    if (
        header.get("record_type") != "manifest"
        or header.get("schema_version") != LABEL_SCHEMA
        or header.get("classification") != "OPENED_DEVELOPMENT_ONLY"
        or header.get("adjudication_provenance") != "SUBAGENT_SEALED"
        or header.get("subagent_adjudication_status") != "COMPLETE"
        or header.get("human_adjudication_status") != "NOT_PERFORMED"
        or header.get("model_generated_judgment") is not True
        or header.get("seal_authority") != "USER_AUTHORIZED_SUBAGENT_BRANCH"
        or header.get("claim_ceiling") != "OPENED_DEVELOPMENT_MODEL_ADJUDICATED"
        or header.get("case_count") != 24
        or header.get("exact_semantic_agreement") is not True
        or header.get("formal_files_accessed") is not False
        or header.get("formal_cases_scored") != 0
    ):
        raise ValueError("Product-11 subagent seal manifest is invalid")
    producer_a = _validate_sealed_envelope(header.get("producer_a"), ANNOTATOR_ROLE)
    producer_b = _validate_sealed_envelope(header.get("producer_b"), REVIEWER_ROLE)
    if producer_a["orchestrator_assigned_agent_id"] == producer_b[
        "orchestrator_assigned_agent_id"
    ] or producer_a["invocation_id"] == producer_b["invocation_id"]:
        raise ValueError("Product-11 sealed subagent producers are not distinct")

    fixture_cases = fixture["cases"]
    expected_case_ids = [str(case["case_id"]) for case in fixture_cases]
    actual_case_ids = [str(row.get("case_id")) for row in rows[1:]]
    if actual_case_ids != expected_case_ids:
        raise ValueError("Product-11 subagent seal case order drifted")
    counts: Counter[str] = Counter()
    capability_counts: Counter[str] = Counter()
    group_count = 0
    for source_case, row in zip(fixture_cases, rows[1:], strict=True):
        case_id = str(source_case["case_id"])
        if (
            row.get("record_type") != "case"
            or row.get("subagent_adjudication_status") != "COMPLETE"
            or row.get("human_adjudication_status") != "NOT_PERFORMED"
            or row.get("model_generated_judgment") is not True
        ):
            raise ValueError(f"Product-11 subagent case {case_id} is invalid")
        shapes = row.get("capability_shapes")
        if not isinstance(shapes, list) or tuple(shapes) != tuple(source_case["capability_shapes"]):
            raise ValueError(f"Product-11 subagent case {case_id} capability shapes drifted")
        capability_counts.update(str(shape) for shape in shapes)
        groups = _normalize_groups(row, source_case=source_case)
        group_count += len(groups)
        for key in (
            "continuation_opportunity",
            "intra_source_opportunity",
            "control_or_already_complete",
        ):
            value = row.get(key)
            if not isinstance(value, bool):
                raise ValueError(f"Product-11 subagent case {case_id} opportunity is invalid")
            counts[key] += int(value)
    missing_shapes = {
        shape: capability_counts[shape]
        for shape in CAPABILITY_SHAPES
        if capability_counts[shape] < 3
    }
    if missing_shapes:
        raise ValueError(
            f"Product-11 subagent capability coverage is insufficient: {missing_shapes}"
        )
    gate_passed = (
        counts["continuation_opportunity"] >= 8
        and counts["intra_source_opportunity"] >= 8
        and counts["control_or_already_complete"] >= 8
    )
    if require_opportunity_gate and not gate_passed:
        raise ValueError("Product-11 subagent-sealed opportunity/control counts are insufficient")
    return {
        **fixture_summary,
        "group_count": group_count,
        "continuation_opportunity_count": counts["continuation_opportunity"],
        "intra_source_opportunity_count": counts["intra_source_opportunity"],
        "control_or_already_complete_count": counts["control_or_already_complete"],
        "subagent_adjudication_complete_count": 24,
        "human_adjudication_status": "NOT_PERFORMED",
        "model_generated_judgment": True,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "opportunity_gate_passed": gate_passed,
        "status": (
            "PASS_PRODUCT11_X0_SUBAGENT_SEAL"
            if gate_passed
            else "COMPLETE_PRODUCT11_SUBAGENT_ADJUDICATION_OPPORTUNITY_INSUFFICIENT"
        ),
    }


def validate_subagent_merge_chain(
    fixture: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    trace_rows: Sequence[Mapping[str, Any]],
    merge_summary: Mapping[str, Any],
    annotator_proposal: Mapping[str, Any],
    reviewer_proposal: Mapping[str, Any],
    *,
    fixture_file_sha256: str,
    a0_trace_sha256: str,
    adjudicated_sha256: str,
    orchestration_manifest_sha256: str,
    annotator_packet_sha256: str,
    reviewer_packet_sha256: str,
    annotator_proposal_sha256: str,
    reviewer_proposal_sha256: str,
) -> dict[str, Any]:
    """Verify the immutable packet-to-proposal-to-merge chain before sealing."""

    if merge_summary.get("schema_version") != MERGE_SCHEMA:
        raise ValueError("Product-11 subagent merge summary schema is invalid")
    allowed_status = {
        "READY_FOR_X0_SUBAGENT_SEAL",
        "READY_FOR_INSUFFICIENT_SUBAGENT_OPPORTUNITY_TERMINAL_SEAL",
    }
    if (
        merge_summary.get("status") not in allowed_status
        or merge_summary.get("exact_semantic_agreement") is not True
        or merge_summary.get("agreement_case_count") != 24
        or merge_summary.get("conflict_case_count") != 0
        or merge_summary.get("conflicts") != []
        or not isinstance(merge_summary.get("adjudicated_output"), str)
        or merge_summary.get("adjudicated_output_sha256") != adjudicated_sha256
        or merge_summary.get("source_fixture_file_sha256") != fixture_file_sha256
        or merge_summary.get("source_fixture_semantic_sha256")
        != canonical_sha256(fixture)
        or merge_summary.get("a0_trace_sha256") != a0_trace_sha256
        or merge_summary.get("orchestration_manifest_sha256")
        != orchestration_manifest_sha256
        or merge_summary.get("annotator_packet_sha256") != annotator_packet_sha256
        or merge_summary.get("reviewer_packet_sha256") != reviewer_packet_sha256
        or merge_summary.get("annotator_proposal_sha256")
        != annotator_proposal_sha256
        or merge_summary.get("reviewer_proposal_sha256") != reviewer_proposal_sha256
        or merge_summary.get("formal_files_accessed") is not False
        or merge_summary.get("formal_cases_scored") != 0
    ):
        raise ValueError("Product-11 subagent merge summary chain is invalid")

    if len(rows) != 25 or not isinstance(rows[0], Mapping):
        raise ValueError("Product-11 subagent adjudicated artifact is invalid")
    header = rows[0]
    if (
        header.get("source_fixture_file_sha256") != fixture_file_sha256
        or header.get("source_fixture_semantic_sha256") != canonical_sha256(fixture)
        or header.get("a0_trace_sha256") != a0_trace_sha256
        or header.get("orchestration_manifest_sha256")
        != orchestration_manifest_sha256
    ):
        raise ValueError("Product-11 subagent adjudicated header chain is invalid")
    annotator_envelope = _validate_envelope(
        merge_summary.get("producer_a"),
        expected_role=ANNOTATOR_ROLE,
        expected_input_sha256=annotator_packet_sha256,
        expected_output_sha256=annotator_proposal_sha256,
    )
    reviewer_envelope = _validate_envelope(
        merge_summary.get("producer_b"),
        expected_role=REVIEWER_ROLE,
        expected_input_sha256=reviewer_packet_sha256,
        expected_output_sha256=reviewer_proposal_sha256,
    )
    if header.get("producer_a") != annotator_envelope or header.get(
        "producer_b"
    ) != reviewer_envelope:
        raise ValueError("Product-11 subagent adjudicated producer envelope drifted")
    if annotator_envelope["orchestrator_assigned_agent_id"] == reviewer_envelope[
        "orchestrator_assigned_agent_id"
    ]:
        raise ValueError("Product-11 sealed subagent producers are not distinct")
    if annotator_envelope["invocation_id"] == reviewer_envelope["invocation_id"]:
        raise ValueError("Product-11 sealed subagent invocations are not distinct")

    recomputed = merge_independent_subagent_proposals(
        fixture,
        trace_rows,
        annotator_proposal,
        reviewer_proposal,
        fixture_file_sha256=fixture_file_sha256,
        a0_trace_sha256=a0_trace_sha256,
        annotator_packet_sha256=annotator_packet_sha256,
        reviewer_packet_sha256=reviewer_packet_sha256,
        annotator_proposal_sha256=annotator_proposal_sha256,
        reviewer_proposal_sha256=reviewer_proposal_sha256,
        orchestration_manifest_sha256=orchestration_manifest_sha256,
        annotator_envelope=annotator_envelope,
        reviewer_envelope=reviewer_envelope,
    )
    recomputed_rows = recomputed.pop("adjudicated_rows")
    if recomputed_rows != list(rows):
        raise ValueError("Product-11 subagent adjudicated rows were not produced by proposals")
    for key, value in recomputed.items():
        if merge_summary.get(key) != value:
            raise ValueError(f"Product-11 subagent merge summary field {key} drifted")

    seal = validate_subagent_seal(fixture, rows, require_opportunity_gate=False)
    opportunity = validate_x0_opportunity_assignments(fixture, rows, trace_rows)
    for key in (
        "continuation_opportunity_count",
        "intra_source_opportunity_count",
        "control_or_already_complete_count",
        "opportunity_assignments_match_a0_trace",
    ):
        if merge_summary.get(key) != opportunity.get(key):
            raise ValueError("Product-11 subagent merge opportunity summary drifted")
    gate_passed = bool(seal["opportunity_gate_passed"])
    expected_status = (
        "READY_FOR_X0_SUBAGENT_SEAL"
        if gate_passed
        else "READY_FOR_INSUFFICIENT_SUBAGENT_OPPORTUNITY_TERMINAL_SEAL"
    )
    if merge_summary.get("status") != expected_status:
        raise ValueError("Product-11 subagent merge terminal status is inconsistent")
    return {
        "schema_version": "milai-product11-subagent-merge-chain-validation-v0.1",
        "status": "VALID_SUBAGENT_MERGE_CHAIN",
        "exact_semantic_agreement": True,
        "conflict_case_count": 0,
        "opportunity_gate_passed": gate_passed,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }


def _normalize_groups(
    row: Mapping[str, Any], *, source_case: Mapping[str, Any]
) -> list[dict[str, Any]]:
    case_id = str(source_case["case_id"])
    raw_groups = row.get("instance_groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError(f"Product-11 subagent case {case_id} has no groups")
    ref_to_scope = {
        str(turn["turn_ref"]): (str(session["source_id"]), str(session["session_id"]))
        for session in source_case["sessions"]
        for turn in session["turns"]
    }
    seen_ids: set[str] = set()
    seen_evidence: set[str] = set()
    seen_turns: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping) or not set(raw_group).issubset(_GROUP_KEYS):
            raise ValueError(f"Product-11 subagent case {case_id} has invalid group fields")
        if "notes" in raw_group and not isinstance(raw_group["notes"], str):
            raise ValueError(f"Product-11 subagent case {case_id} has invalid notes")
        evidence_ids = raw_group.get("acceptable_evidence_ids", [])
        if not isinstance(evidence_ids, list) or evidence_ids:
            raise ValueError(
                f"Product-11 subagent case {case_id} cannot assert Evidence IDs without a mapping"
            )
        group = InstanceGroup.from_mapping(
            {
                "group_id": raw_group.get("group_id"),
                "acceptable_evidence_ids": evidence_ids,
                "acceptable_turn_refs": raw_group.get("acceptable_turn_refs", []),
                "source_ids": [],
                "session_ids": [],
                "required_for_answer": raw_group.get("required_for_answer"),
            }
        )
        if group.group_id in seen_ids:
            raise ValueError(f"Product-11 subagent case {case_id} repeats a local group ID")
        seen_ids.add(group.group_id)
        if not group.required_for_answer:
            raise ValueError(f"Product-11 subagent group {group.group_id} must be required")
        if not group.acceptable_turn_refs:
            raise ValueError(f"Product-11 subagent group {group.group_id} needs an exact turn_ref")
        if not set(group.acceptable_turn_refs).issubset(ref_to_scope):
            raise ValueError(f"Product-11 subagent group {group.group_id} has an unknown turn_ref")
        derived_sources = sorted(
            {ref_to_scope[ref][0] for ref in group.acceptable_turn_refs}
        )
        derived_sessions = sorted(
            {ref_to_scope[ref][1] for ref in group.acceptable_turn_refs}
        )
        for field, expected in (
            ("source_ids", derived_sources),
            ("session_ids", derived_sessions),
        ):
            supplied = raw_group.get(field)
            if supplied is not None and (
                not isinstance(supplied, list)
                or sorted(str(item) for item in supplied) != expected
            ):
                raise ValueError(
                    f"Product-11 subagent group {group.group_id} has ungrounded {field}"
                )
        if seen_evidence.intersection(group.acceptable_evidence_ids):
            raise ValueError(f"case {case_id} has cross-group Evidence overlap")
        if seen_turns.intersection(group.acceptable_turn_refs):
            raise ValueError(f"case {case_id} has cross-group turn overlap")
        seen_evidence.update(group.acceptable_evidence_ids)
        seen_turns.update(group.acceptable_turn_refs)
        normalized.append(
            {
                "acceptable_evidence_ids": sorted(group.acceptable_evidence_ids),
                "acceptable_turn_refs": sorted(group.acceptable_turn_refs),
                "source_ids": derived_sources,
                "session_ids": derived_sessions,
                "required_for_answer": True,
            }
        )
    return sorted(normalized, key=canonical_sha256)


def _materialize_groups(
    source_case: Mapping[str, Any], signatures: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    case_id = str(source_case["case_id"])
    return [
        {"group_id": f"{case_id}:g{index:02d}", **dict(signature)}
        for index, signature in enumerate(signatures, start=1)
    ]


def _validate_envelope(
    value: object,
    *,
    expected_role: str,
    expected_input_sha256: str,
    expected_output_sha256: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Product-11 subagent producer envelope is absent")
    expected_keys = {
        "kind",
        "orchestrator_assigned_agent_id",
        "invocation_id",
        "model_id",
        "role",
        "input_bundle_sha256",
        "output_sha256",
        "peer_output_supplied",
        "proposal_output_supplied",
        "a0_trace_supplied",
        "treatment_output_supplied",
    }
    if set(value) != expected_keys:
        raise ValueError("Product-11 subagent producer envelope fields are invalid")
    if (
        value.get("kind") != "SUBAGENT"
        or value.get("role") != expected_role
        or value.get("input_bundle_sha256") != expected_input_sha256
        or value.get("output_sha256") != expected_output_sha256
        or value.get("peer_output_supplied") is not False
        or value.get("proposal_output_supplied") is not False
        or value.get("a0_trace_supplied") is not False
        or value.get("treatment_output_supplied") is not False
    ):
        raise ValueError("Product-11 subagent producer envelope is invalid")
    result = dict(value)
    for key in ("orchestrator_assigned_agent_id", "invocation_id", "model_id"):
        if not isinstance(result.get(key), str) or not str(result[key]).strip():
            raise ValueError(f"Product-11 subagent envelope {key} is invalid")
    return result


def _validate_sealed_envelope(value: object, expected_role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Product-11 sealed producer envelope is absent")
    return _validate_envelope(
        value,
        expected_role=expected_role,
        expected_input_sha256=str(value.get("input_bundle_sha256")),
        expected_output_sha256=str(value.get("output_sha256")),
    )


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        nested = (
            set().union(*(_recursive_keys(item) for item in value.values()))
            if value
            else set()
        )
        return {str(key) for key in value}.union(nested)
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value)) if value else set()
    return set()


__all__ = [
    "ANNOTATOR_ROLE",
    "LABEL_SCHEMA",
    "MERGE_SCHEMA",
    "ORCHESTRATION_SCHEMA",
    "PACKET_SCHEMA",
    "PROPOSAL_SCHEMA",
    "REVIEWER_ROLE",
    "build_subagent_review_packet",
    "merge_independent_subagent_proposals",
    "validate_subagent_merge_chain",
    "validate_subagent_orchestration_manifest",
    "validate_subagent_proposal",
    "validate_subagent_review_packet",
    "validate_subagent_seal",
]
