from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from milai_lab.product11 import (
    InstanceGroup,
    canonical_sha256,
    derive_x0_opportunity_assignments,
    validate_a0_trace_seal,
    validate_human_seal,
    validate_source_fixture,
    validate_x0_opportunity_assignments,
)

SUBMISSION_SCHEMA = "milai-product11-independent-human-submission-v0.1"
REVIEW_VIEW_SCHEMA = "milai-product11-source-review-view-v0.1"
ANNOTATOR_ROLE = "ANNOTATOR"
REVIEWER_ROLE = "INDEPENDENT_REVIEWER"


def build_submission_rows(
    fixture: Mapping[str, Any],
    *,
    role: str,
    fixture_file_sha256: str,
    a0_trace_sha256: str,
) -> list[dict[str, Any]]:
    """Build a source-only, proposal-free independent-human submission template."""

    fixture_summary = validate_source_fixture(fixture)
    if role not in {ANNOTATOR_ROLE, REVIEWER_ROLE}:
        raise ValueError("Product-11 independent submission role is invalid")
    rows: list[dict[str, Any]] = [
        {
            "record_type": "manifest",
            "schema_version": SUBMISSION_SCHEMA,
            "role": role,
            "classification": "OPENED_DEVELOPMENT_ONLY",
            "case_count": 24,
            "human_review_status": "PENDING",
            "model_assisted_proxy": False,
            "formal_files_accessed": False,
            "formal_cases_scored": 0,
            "source_fixture_file_sha256": fixture_file_sha256,
            "source_fixture_semantic_sha256": canonical_sha256(fixture),
            "a0_trace_sha256": a0_trace_sha256,
            "case_order_sha256": fixture_summary["case_order_sha256"],
            "human_attestation": {
                "kind": "PENDING_HUMAN",
                "id": "",
                "signed_at": "",
                "attestation": "",
            },
            "instructions": [
                "Work independently from the other role and only from the source review packet.",
                "Do not inspect model proposals, A0 retrieval output, or the other submission.",
                "Replace PENDING with COMPLETE only after all 24 cases are reviewed.",
                "For each real-world instance group, list every acceptable exact turn_ref.",
                "Repeated mentions of one real-world instance belong to one group.",
                "The same exact turn_ref cannot belong to two distinct required groups.",
                "Source/session provenance is derived from turn_ref by the merger.",
            ],
        }
    ]
    cases = fixture["cases"]
    for raw_case in cases:
        rows.append(
            {
                "record_type": "case",
                "case_id": raw_case["case_id"],
                "capability_shapes": raw_case["capability_shapes"],
                "instance_groups": [],
                "human_review_status": "PENDING",
                "model_assisted_proxy": False,
                "notes": "",
            }
        )
    return rows


def build_source_review_view(
    fixture: Mapping[str, Any],
    *,
    fixture_file_sha256: str,
    a0_trace_sha256: str,
    authoritative_packets: Sequence[str],
) -> dict[str, Any]:
    """Build a compact source-only view without Product output or proposed gold groups."""

    validate_source_fixture(fixture)
    compact_cases: list[dict[str, Any]] = []
    compacted_turns = 0
    full_turns = 0
    for raw_case in fixture["cases"]:
        sessions: list[dict[str, Any]] = []
        for raw_session in raw_case["sessions"]:
            turns: list[dict[str, Any]] = []
            for raw_turn in raw_session["turns"]:
                text = str(raw_turn["text"])
                turn = {
                    "turn_ref": raw_turn["turn_ref"],
                    "observed_at": raw_turn.get("observed_at"),
                    "speaker": raw_turn.get("speaker"),
                }
                if text.startswith("Index-only distractor "):
                    compacted_turns += 1
                    turn.update(
                        {
                            "presentation": "DETERMINISTIC_INDEX_ONLY_DISTRACTOR_COMPACTED",
                            "text_preview": text[:160],
                            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        }
                    )
                else:
                    full_turns += 1
                    turn.update({"presentation": "FULL_SOURCE_TEXT", "text": text})
                turns.append(turn)
            sessions.append(
                {
                    "source_id": raw_session["source_id"],
                    "session_id": raw_session["session_id"],
                    "turns": turns,
                }
            )
        compact_cases.append(
            {
                "case_id": raw_case["case_id"],
                "question": raw_case["question"],
                "capability_shapes": raw_case["capability_shapes"],
                "sessions": sessions,
            }
        )
    return {
        "schema_version": REVIEW_VIEW_SCHEMA,
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_source": False,
        "source_only": True,
        "contains_model_proposals": False,
        "contains_product_output": False,
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "a0_trace_sha256_pin_only": a0_trace_sha256,
        "authoritative_full_source_packets": list(authoritative_packets),
        "instructions": [
            "Use this compact view for source review; it contains no Product retrieval output.",
            "Consult an authoritative full-source packet if a compacted distractor "
            "needs inspection.",
            "Write judgments only into your role-specific independent submission file.",
        ],
        "full_source_turn_count": full_turns,
        "compacted_distractor_turn_count": compacted_turns,
        "cases": compact_cases,
    }


def merge_independent_submissions(
    fixture: Mapping[str, Any],
    trace_rows: Sequence[Mapping[str, Any]],
    annotator_rows: Sequence[Mapping[str, Any]],
    reviewer_rows: Sequence[Mapping[str, Any]],
    *,
    fixture_file_sha256: str,
    a0_trace_sha256: str,
) -> dict[str, Any]:
    """Merge exact independent agreement; emit conflicts without adjudicating them."""

    fixture_summary = validate_source_fixture(fixture)
    trace_summary = validate_a0_trace_seal(trace_rows)
    annotator = _validate_submission(
        fixture,
        annotator_rows,
        expected_role=ANNOTATOR_ROLE,
        fixture_file_sha256=fixture_file_sha256,
        a0_trace_sha256=a0_trace_sha256,
    )
    reviewer = _validate_submission(
        fixture,
        reviewer_rows,
        expected_role=REVIEWER_ROLE,
        fixture_file_sha256=fixture_file_sha256,
        a0_trace_sha256=a0_trace_sha256,
    )
    if annotator["identity"] == reviewer["identity"]:
        raise ValueError("Product-11 annotator and reviewer identities are not independent")

    conflicts: list[dict[str, Any]] = []
    agreed_groups: dict[str, list[dict[str, Any]]] = {}
    for raw_case in fixture["cases"]:
        case_id = str(raw_case["case_id"])
        left = annotator["groups_by_case"][case_id]
        right = reviewer["groups_by_case"][case_id]
        if left != right:
            conflicts.append(
                {
                    "case_id": case_id,
                    "reason": "INSTANCE_GROUP_SEMANTICS_DISAGREE",
                    "annotator_group_signatures": left,
                    "reviewer_group_signatures": right,
                }
            )
            continue
        agreed_groups[case_id] = _materialize_groups(raw_case, left)

    base = {
        "schema_version": "milai-product11-human-merge-result-v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "a0_trace_sha256": a0_trace_sha256,
        "annotator_id": annotator["identity"],
        "reviewer_id": reviewer["identity"],
        "independent_human_identities": True,
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
            "status": "BLOCKED_HUMAN_RECONCILIATION_REQUIRED",
            "conflicts": conflicts,
            "adjudicated_rows": None,
        }

    header: dict[str, Any] = {
        "record_type": "manifest",
        "schema_version": "milai-product11-human-instance-groups-v0.1",
        "case_count": 24,
        "human_adjudication_status": "COMPLETE",
        "model_assisted_proxy": False,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "source_fixture_file_sha256": fixture_file_sha256,
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "a0_trace_sha256": a0_trace_sha256,
    }
    combined_rows: list[dict[str, Any]] = [header]
    for raw_case in fixture["cases"]:
        case_id = str(raw_case["case_id"])
        combined_rows.append(
            {
                "record_type": "case",
                "case_id": case_id,
                "capability_shapes": raw_case["capability_shapes"],
                "instance_groups": agreed_groups[case_id],
                "continuation_opportunity": False,
                "intra_source_opportunity": False,
                "control_or_already_complete": False,
                "human_adjudication_status": "COMPLETE",
                "model_assisted_proxy": False,
                "annotator": annotator["attestation"],
                "reviewer": reviewer["attestation"],
            }
        )
    derived = derive_x0_opportunity_assignments(fixture, combined_rows, trace_rows)
    for row in combined_rows[1:]:
        row.update(derived["case_assignments"][str(row["case_id"])])
    seal = validate_human_seal(fixture, combined_rows, require_opportunity_gate=False)
    opportunity = validate_x0_opportunity_assignments(fixture, combined_rows, trace_rows)
    gate_passed = bool(seal["opportunity_gate_passed"])
    return {
        **base,
        **opportunity,
        "human_group_count": seal["group_count"],
        "opportunity_gate_passed": gate_passed,
        "status": (
            "READY_FOR_X0_SEAL"
            if gate_passed
            else "READY_FOR_INSUFFICIENT_OPPORTUNITY_TERMINAL_SEAL"
        ),
        "conflicts": [],
        "adjudicated_rows": combined_rows,
    }


def validate_independent_submission(
    fixture: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_role: str,
    fixture_file_sha256: str,
    a0_trace_sha256: str,
) -> dict[str, Any]:
    """Validate one human file without inspecting the other role's submission."""

    result = _validate_submission(
        fixture,
        rows,
        expected_role=expected_role,
        fixture_file_sha256=fixture_file_sha256,
        a0_trace_sha256=a0_trace_sha256,
    )
    groups_by_case = result["groups_by_case"]
    if not isinstance(groups_by_case, Mapping):
        raise ValueError("Product-11 independent submission group index is invalid")
    return {
        "schema_version": "milai-product11-independent-human-validation-v0.1",
        "status": "READY_FOR_INDEPENDENT_MERGE",
        "role": expected_role,
        "human_id": result["identity"],
        "case_count": len(groups_by_case),
        "group_count": sum(
            len(groups) for groups in groups_by_case.values() if isinstance(groups, list)
        ),
        "source_fixture_file_sha256": fixture_file_sha256,
        "a0_trace_sha256": a0_trace_sha256,
        "other_submission_accessed": False,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
    }


def _validate_submission(
    fixture: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_role: str,
    fixture_file_sha256: str,
    a0_trace_sha256: str,
) -> dict[str, Any]:
    if len(rows) != 25:
        raise ValueError(f"Product-11 {expected_role} submission requires 25 rows")
    header = rows[0]
    fixture_case_ids = [str(case["case_id"]) for case in fixture["cases"]]
    if (
        header.get("record_type") != "manifest"
        or header.get("schema_version") != SUBMISSION_SCHEMA
        or header.get("role") != expected_role
        or header.get("classification") != "OPENED_DEVELOPMENT_ONLY"
        or header.get("case_count") != 24
        or header.get("case_order_sha256") != canonical_sha256(fixture_case_ids)
        or header.get("human_review_status") != "COMPLETE"
        or header.get("model_assisted_proxy") is not False
        or header.get("formal_files_accessed") is not False
        or header.get("formal_cases_scored") != 0
        or header.get("source_fixture_file_sha256") != fixture_file_sha256
        or header.get("source_fixture_semantic_sha256") != canonical_sha256(fixture)
        or header.get("a0_trace_sha256") != a0_trace_sha256
    ):
        raise ValueError(f"Product-11 {expected_role} submission manifest is invalid")
    attestation = _human_attestation(header.get("human_attestation"), role=expected_role)
    fixture_cases = fixture["cases"]
    actual_case_ids = [str(row.get("case_id")) for row in rows[1:]]
    if actual_case_ids != fixture_case_ids:
        raise ValueError(f"Product-11 {expected_role} submission case order drifted")
    groups_by_case: dict[str, list[dict[str, Any]]] = {}
    for source_case, row in zip(fixture_cases, rows[1:], strict=True):
        case_id = str(source_case["case_id"])
        if (
            row.get("record_type") != "case"
            or row.get("human_review_status") != "COMPLETE"
            or row.get("model_assisted_proxy") is not False
            or tuple(row.get("capability_shapes", []))
            != tuple(source_case["capability_shapes"])
        ):
            raise ValueError(f"Product-11 {expected_role} case {case_id} is incomplete")
        groups_by_case[case_id] = _normalize_submission_groups(row, source_case=source_case)
    return {
        "identity": attestation["id"],
        "attestation": attestation,
        "groups_by_case": groups_by_case,
    }


def _normalize_submission_groups(
    row: Mapping[str, Any], *, source_case: Mapping[str, Any]
) -> list[dict[str, Any]]:
    case_id = str(source_case["case_id"])
    raw_groups = row.get("instance_groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError(f"Product-11 human submission case {case_id} has no groups")
    ref_to_scope = {
        str(turn["turn_ref"]): (str(session["source_id"]), str(session["session_id"]))
        for session in source_case["sessions"]
        for turn in session["turns"]
    }
    seen_evidence: set[str] = set()
    seen_turns: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            raise ValueError(f"Product-11 human submission case {case_id} has invalid group")
        group = InstanceGroup.from_mapping(
            {
                "group_id": raw_group.get("group_id"),
                "acceptable_evidence_ids": raw_group.get("acceptable_evidence_ids", []),
                "acceptable_turn_refs": raw_group.get("acceptable_turn_refs", []),
                "source_ids": raw_group.get("source_ids", []),
                "session_ids": raw_group.get("session_ids", []),
                "required_for_answer": raw_group.get("required_for_answer"),
            }
        )
        if not group.acceptable_turn_refs:
            raise ValueError(f"Product-11 human group {group.group_id} needs an exact turn_ref")
        if not set(group.acceptable_turn_refs).issubset(ref_to_scope):
            raise ValueError(f"Product-11 human group {group.group_id} references unknown turn_ref")
        if group.required_for_answer:
            if seen_evidence.intersection(group.acceptable_evidence_ids):
                raise ValueError(f"case {case_id} has cross-group Evidence overlap")
            if seen_turns.intersection(group.acceptable_turn_refs):
                raise ValueError(f"case {case_id} has cross-group turn overlap")
            seen_evidence.update(group.acceptable_evidence_ids)
            seen_turns.update(group.acceptable_turn_refs)
        sources = sorted({ref_to_scope[ref][0] for ref in group.acceptable_turn_refs})
        sessions = sorted({ref_to_scope[ref][1] for ref in group.acceptable_turn_refs})
        normalized.append(
            {
                "acceptable_evidence_ids": sorted(group.acceptable_evidence_ids),
                "acceptable_turn_refs": sorted(group.acceptable_turn_refs),
                "source_ids": sources,
                "session_ids": sessions,
                "required_for_answer": group.required_for_answer,
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


def _human_attestation(value: object, *, role: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or value.get("kind") != "HUMAN":
        raise ValueError(f"Product-11 {role} must attest as HUMAN")
    identity = _nonempty(value.get("id"), f"{role}.id")
    signed_at = _nonempty(value.get("signed_at"), f"{role}.signed_at")
    attestation = _nonempty(value.get("attestation"), f"{role}.attestation")
    return {
        "kind": "HUMAN",
        "id": identity,
        "signed_at": signed_at,
        "attestation": attestation,
    }


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()
