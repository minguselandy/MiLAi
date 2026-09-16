from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from milai_lab.context_preflight import source_session_instance_keys

CapabilityShape = Literal[
    "ENUMERATION",
    "COUNTING",
    "REPEATED_MENTION",
    "SAME_TYPE_DIFFERENT_INSTANCE",
    "CROSS_SESSION_AGGREGATION",
    "UPDATE_COLLECTION",
    "CONTINUATION",
]

CAPABILITY_SHAPES: tuple[CapabilityShape, ...] = (
    "ENUMERATION",
    "COUNTING",
    "REPEATED_MENTION",
    "SAME_TYPE_DIFFERENT_INSTANCE",
    "CROSS_SESSION_AGGREGATION",
    "UPDATE_COLLECTION",
    "CONTINUATION",
)

FirstLoss = Literal[
    "NOT_DISCOVERED",
    "INSTANCE_DESTROYING_COLLAPSE",
    "DISCOVERED_NOT_ADMITTED",
    "ADMITTED_NOT_RENDERED",
    "VISIBLE_BUT_HOST_MISSED",
]


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def stable_component(value: str, *, length: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def runtime_source_turn_ref(
    record: Mapping[str, Any], *, session_ordinal: int, turn_ordinal: int
) -> str:
    case_id = _nonempty_string(record.get("question_id"), "question_id")
    session_ids = record.get("haystack_session_ids")
    sessions = record.get("haystack_sessions")
    if not isinstance(session_ids, list) or not isinstance(sessions, list):
        raise ValueError("LongMemEval session material is invalid")
    if not 0 <= session_ordinal < len(session_ids) or len(session_ids) != len(sessions):
        raise ValueError("LongMemEval session ordinal is invalid")
    if not isinstance(turn_ordinal, int) or isinstance(turn_ordinal, bool):
        raise ValueError("LongMemEval turn ordinal is invalid")
    instances = source_session_instance_keys(session_ids)
    session = sessions[session_ordinal]
    if not isinstance(session, list) or not 0 <= turn_ordinal < len(session):
        raise ValueError("LongMemEval turn ordinal is invalid")
    turn = session[turn_ordinal]
    if not isinstance(turn, Mapping) or not isinstance(turn.get("content"), str):
        raise ValueError("LongMemEval turn material is invalid")
    return (
        f"lme://{stable_component(case_id, length=12)}/"
        f"{stable_component(instances[session_ordinal], length=20)}/turn/{turn_ordinal}"
    )


def structural_capability_shapes(
    *,
    question_type: str,
    question: str,
    group_member_counts: Sequence[int],
    reference_session_count: int,
    model_shapes: Sequence[str],
) -> tuple[CapabilityShape, ...]:
    """Combine transparent structural rules with a frozen model-assisted classification."""

    shapes = {value for value in model_shapes if value in CAPABILITY_SHAPES}
    normalized = re.sub(r"\s+", " ", question.casefold())
    group_count = len(group_member_counts)
    if re.search(r"\b(?:how many|how much|total|percentage|page count|combined)\b", normalized):
        shapes.add("COUNTING")
    if group_count >= 2:
        shapes.update(
            {
                "ENUMERATION",
                "SAME_TYPE_DIFFERENT_INSTANCE",
                "CONTINUATION",
            }
        )
    if any(count >= 2 for count in group_member_counts):
        shapes.add("REPEATED_MENTION")
    if reference_session_count >= 2 or question_type == "multi-session":
        shapes.add("CROSS_SESSION_AGGREGATION")
    if question_type == "knowledge-update" or (
        group_count >= 2 and "current" in normalized
    ):
        shapes.add("UPDATE_COLLECTION")
    return tuple(value for value in CAPABILITY_SHAPES if value in shapes)


@dataclass(frozen=True, slots=True)
class InstanceGroup:
    group_id: str
    acceptable_evidence_ids: tuple[str, ...]
    acceptable_turn_refs: tuple[str, ...]
    required_for_answer: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> InstanceGroup:
        group_id = _nonempty_string(value.get("group_id"), "group_id")
        evidence_ids = _string_tuple(value.get("acceptable_evidence_ids", []))
        turn_refs = _string_tuple(value.get("acceptable_turn_refs", []))
        required = value.get("required_for_answer")
        if not isinstance(required, bool):
            raise ValueError("required_for_answer must be Boolean")
        if not evidence_ids and not turn_refs:
            raise ValueError("instance group has no acceptable Product identity")
        return cls(group_id, evidence_ids, turn_refs, required)


def validate_label_case(value: Mapping[str, Any]) -> tuple[InstanceGroup, ...]:
    case_id = _nonempty_string(value.get("case_id"), "case_id")
    raw_groups = value.get("instance_groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError(f"case {case_id} has no instance groups")
    groups = tuple(
        InstanceGroup.from_mapping(group)
        for group in raw_groups
        if isinstance(group, Mapping)
    )
    if len(groups) != len(raw_groups) or len({group.group_id for group in groups}) != len(groups):
        raise ValueError(f"case {case_id} has invalid group cardinality")
    seen_evidence: set[str] = set()
    seen_turns: set[str] = set()
    for group in groups:
        if not group.required_for_answer:
            continue
        if seen_evidence.intersection(group.acceptable_evidence_ids):
            raise ValueError(f"case {case_id} assigns one Evidence ID to multiple groups")
        if seen_turns.intersection(group.acceptable_turn_refs):
            raise ValueError(f"case {case_id} assigns one turn ref to multiple groups")
        seen_evidence.update(group.acceptable_evidence_ids)
        seen_turns.update(group.acceptable_turn_refs)
    shapes = value.get("capability_shapes")
    if (
        not isinstance(shapes, list)
        or not shapes
        or any(shape not in CAPABILITY_SHAPES for shape in shapes)
        or len(shapes) != len(set(shapes))
    ):
        raise ValueError(f"case {case_id} has invalid capability shapes")
    return groups


def validate_label_bundle(rows: Sequence[Mapping[str, Any]]) -> None:
    if len(rows) != 25:
        raise ValueError("Product-10 label bundle must contain one header and 24 cases")
    header = rows[0]
    if (
        header.get("record_type") != "manifest"
        or header.get("schema_version") != "milai-product10-instance-groups-v0.1"
        or header.get("case_count") != 24
    ):
        raise ValueError("Product-10 label manifest header is invalid")
    cases = rows[1:]
    case_ids = [_nonempty_string(row.get("case_id"), "case_id") for row in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Product-10 label case identities are not unique")
    counts: Counter[str] = Counter()
    for row in cases:
        validate_label_case(row)
        counts.update(str(value) for value in row["capability_shapes"])
    missing = {shape: counts[shape] for shape in CAPABILITY_SHAPES if counts[shape] < 3}
    if missing:
        raise ValueError(f"Product-10 capability coverage is insufficient: {missing}")


def distinct_instance_coverage(
    groups: Sequence[InstanceGroup],
    *,
    visible_evidence_ids: Sequence[str],
    visible_turn_refs: Sequence[str],
) -> dict[str, int | float]:
    required = [group for group in groups if group.required_for_answer]
    if not required:
        raise ValueError("DistinctInstanceCoverage requires a non-empty denominator")
    evidence = set(visible_evidence_ids)
    turns = set(visible_turn_refs)
    covered = sum(
        bool(evidence.intersection(group.acceptable_evidence_ids))
        or bool(turns.intersection(group.acceptable_turn_refs))
        for group in required
    )
    return {
        "numerator": covered,
        "denominator": len(required),
        "value": covered / len(required),
    }


def duplicate_instance_rate(
    groups: Sequence[InstanceGroup],
    *,
    visible_evidence_ids: Sequence[str],
    visible_turn_refs: Sequence[str],
) -> dict[str, int | float | bool]:
    required = [group for group in groups if group.required_for_answer]
    evidence = set(visible_evidence_ids)
    turns = set(visible_turn_refs)
    counts = [
        len(evidence.intersection(group.acceptable_evidence_ids))
        + len(turns.intersection(group.acceptable_turn_refs))
        for group in required
    ]
    denominator = sum(counts)
    numerator = sum(max(0, count - 1) for count in counts)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else 0.0,
        "empty_eligible_set": denominator == 0,
    }


def first_loss(
    group: InstanceGroup,
    *,
    raw_evidence_ids: Sequence[str],
    raw_turn_refs: Sequence[str],
    post_identity_evidence_ids: Sequence[str],
    post_identity_turn_refs: Sequence[str],
    admitted_evidence_ids: Sequence[str],
    admitted_turn_refs: Sequence[str],
    rendered_evidence_ids: Sequence[str],
    rendered_turn_refs: Sequence[str],
    host_used: bool | None = None,
) -> FirstLoss | None:
    def covered(evidence_ids: Sequence[str], turn_refs: Sequence[str]) -> bool:
        return bool(set(evidence_ids).intersection(group.acceptable_evidence_ids)) or bool(
            set(turn_refs).intersection(group.acceptable_turn_refs)
        )

    # Runtime may hydrate an adjacent governed turn while compiling Context even
    # when that turn was not a direct official-search occurrence.  Observed
    # downstream visibility is definitive and must not be contradicted by an
    # upstream NOT_DISCOVERED classification.
    if covered(rendered_evidence_ids, rendered_turn_refs):
        return "VISIBLE_BUT_HOST_MISSED" if host_used is False else None
    if not covered(raw_evidence_ids, raw_turn_refs):
        return "NOT_DISCOVERED"
    if not covered(post_identity_evidence_ids, post_identity_turn_refs):
        return "INSTANCE_DESTROYING_COLLAPSE"
    if not covered(admitted_evidence_ids, admitted_turn_refs):
        return "DISCOVERED_NOT_ADMITTED"
    return "ADMITTED_NOT_RENDERED"


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("identity list is invalid")
    return tuple(dict.fromkeys(value))


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


__all__ = [
    "CAPABILITY_SHAPES",
    "CapabilityShape",
    "FirstLoss",
    "InstanceGroup",
    "canonical_sha256",
    "distinct_instance_coverage",
    "duplicate_instance_rate",
    "first_loss",
    "runtime_source_turn_ref",
    "structural_capability_shapes",
    "validate_label_bundle",
    "validate_label_case",
]
