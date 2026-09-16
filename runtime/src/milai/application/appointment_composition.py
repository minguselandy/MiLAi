"""Minimal Q2 bounded temporal count over governed Raw Evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import JsonValue

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.evidence_source import evidence_source_turn_identity
from milai.domain.evidence_composition import (
    CompositionCompleteness,
    EvidenceApplicabilityResult,
    EvidenceCompositionResult,
    EvidenceSlot,
    OperatorTrace,
    QuerySpec,
    query_spec_from_plan,
)
from milai.domain.retrieval import QueryPlan
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceSpan,
)

_SENTENCE = re.compile(r"(?<!\bDr\.)(?<=[.!?])\s+|[\r\n]+", re.IGNORECASE)
_MONTH_DATE = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{4}))?\b",
    re.IGNORECASE,
)
_DOCTOR = re.compile(
    r"\b(?:doctor|physician|surgeon|gastroenterologist|neurologist|"
    r"orthopedist|cardiologist|dermatologist|pediatrician|psychiatrist)\b|"
    r"\bdr\.\s+[a-z]+",
    re.IGNORECASE,
)
_EVENT = re.compile(r"\bappointment\b|\bwent to see\b|\b(?:medical|emg) test\b", re.IGNORECASE)
_ATTENDED = re.compile(
    r"\b(?:went to see|finally went|recently had|had a follow-up appointment|"
    r"follow-up appointment with)\b",
    re.IGNORECASE,
)
_PLANNED = re.compile(
    r"\b(?:scheduled|schedule|scheduling|considering|upcoming|will see|"
    r"plan(?:ned|ning)? to see)\b",
    re.IGNORECASE,
)
_CANCELLED = re.compile(r"\b(?:cancelled|canceled|did not go|missed)\b", re.IGNORECASE)
_PROVIDER = re.compile(r"\bdr\.\s+(?P<name>[a-z]+)", re.IGNORECASE)
_MONTHS = {
    name: ordinal
    for ordinal, name in enumerate(
        (
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
        ),
        start=1,
    )
}

TemporalQueryAxis = Literal["SOURCE_OBSERVED_TIME", "EVENT_OCCURRENCE_TIME"]


def temporal_range(plan: QueryPlan) -> tuple[datetime, datetime] | None:
    if plan.operator != "TEMPORAL_COUNT_DISTINCT":
        return None
    raw = plan.operator_arguments.get("temporal_range")
    if not isinstance(raw, dict):
        return None
    start, end = raw.get("start"), raw.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        parsed_start = datetime.fromisoformat(start)
        parsed_end = datetime.fromisoformat(end)
    except ValueError:
        return None
    if (
        parsed_start.utcoffset() is None
        or parsed_end.utcoffset() is None
        or parsed_start >= parsed_end
    ):
        return None
    return parsed_start.astimezone(UTC), parsed_end.astimezone(UTC)


def temporal_query_axis(plan: QueryPlan) -> TemporalQueryAxis:
    """Return the typed query axis; never infer it from Evidence text."""

    query_ir = plan.memory_query_ir
    if query_ir is not None:
        temporal = query_ir.constraints.normalized_temporal
        if temporal is not None and temporal.time_axis == "SOURCE_OBSERVED_TIME":
            return "SOURCE_OBSERVED_TIME"
    raw = plan.operator_arguments.get("time_axis")
    if raw == "SOURCE_OBSERVED_TIME":
        return "SOURCE_OBSERVED_TIME"
    return "EVENT_OCCURRENCE_TIME"


def normalize_query_time_event_scan(
    plan: QueryPlan,
    source_scan: Mapping[str, Any],
    *,
    expected_range: tuple[datetime, datetime] | None = None,
) -> dict[str, Any]:
    """Validate a full governed snapshot before event-occurrence filtering."""

    result = dict(source_scan)
    interval = expected_range or temporal_range(plan)
    if interval is None or temporal_query_axis(plan) != "EVENT_OCCURRENCE_TIME":
        return _failed_event_normalization(result, "EVENT_RANGE_NOT_EXECUTABLE")
    start, end = interval
    declared_start = _aware_datetime(source_scan.get("event_range_start"))
    declared_end = _aware_datetime(source_scan.get("event_range_end"))
    items = source_scan.get("items")
    source_count = _optional_int(source_scan.get("source_count"))
    projected_count = _optional_int(source_scan.get("projected_count"))
    returned_count = _optional_int(source_scan.get("returned_count"))
    if returned_count is None and isinstance(items, list):
        returned_count = len(items)
    proof_complete = (
        source_scan.get("status") == "COMPLETE"
        and source_scan.get("scan_axis") == "SOURCE_OBSERVED_TIME"
        and source_scan.get("source_snapshot_axis") == "SOURCE_OBSERVED_TIME"
        and source_scan.get("partition_kind") == "FULL_GOVERNED_EVIDENCE_SNAPSHOT_AS_OF"
        and source_scan.get("event_normalization_owner") == "DETERMINISTIC_RUNTIME"
        and source_scan.get("event_normalization_version") == "query-time-event-v1"
        and source_scan.get("event_range_boundary") == "CLOSED_OPEN"
        and declared_start == start
        and declared_end == end
        and source_scan.get("source_partition_closed") is True
        and source_scan.get("projection_watermark_covered") is True
        and source_scan.get("dead_letter_gap") is not True
        and source_count is not None
        and projected_count == source_count
        and returned_count == source_count
    )
    if not proof_complete:
        return _failed_event_normalization(result, "SOURCE_SNAPSHOT_PROOF_INCOMPLETE")
    result.update(
        {
            "scan_axis": "EVENT_OCCURRENCE_TIME",
            "event_normalization_status": "COMPLETE",
            "event_range_predicate": "CLOSED_OPEN_OVERLAP",
            "temporal_domain_coverage": "EXACT_AXIS_RANGE",
            "time_axis_substitution": False,
        }
    )
    return result


def compose_appointment_count(plan: QueryPlan, scan: Mapping[str, Any]) -> dict[str, Any] | None:
    """Classify explicit dated appointments and count distinct attended events."""

    spec = query_spec_from_plan(plan)
    if spec is None or spec.operator != "TEMPORAL_COUNT_DISTINCT":
        return None
    interval = temporal_range(plan)
    if interval is None:
        return None
    start, end = interval
    items = scan.get("items")
    if not isinstance(items, list):
        return _partial(plan, spec, scan, "RANGE_SCAN_INVALID", [])
    axis_failure = _axis_failure(plan, scan)
    if axis_failure is not None:
        return _partial(plan, spec, scan, axis_failure, [])
    candidates: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        for sentence in _SENTENCE.split(content):
            if _DOCTOR.search(sentence) is None or _EVENT.search(sentence) is None:
                continue
            for date_match in _MONTH_DATE.finditer(sentence):
                event_at = _event_date(date_match, plan.time_reference.year)
                status = _attendance(sentence)
                disposition = (
                    "INCLUDE"
                    if start <= event_at < end and status == "ATTENDED"
                    else f"EXCLUDE_{status}"
                )
                range_disposition = "IN_RANGE" if start <= event_at < end else "OUT_OF_RANGE"
                provider = _provider_key(sentence)
                candidates.append(
                    {
                        "event_at": event_at.date().isoformat(),
                        "attendance_status": status,
                        "range_disposition": disposition,
                        "temporal_range_disposition": range_disposition,
                        "dedup_key": (
                            f"{event_at.date().isoformat()}|{provider}|{status.casefold()}"
                        ),
                        "provider_key": provider,
                        "evidence_id": str(item.get("evidence_id", "")),
                        "source_ref": str(item.get("source_ref", "")),
                        "span": sentence.strip()[:600],
                    }
                )
    accepted_by_key: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate["range_disposition"] == "INCLUDE":
            accepted_by_key.setdefault(candidate["dedup_key"], candidate)
    accepted = list(accepted_by_key.values())
    proof_failure = _complete_scan_proof_failure(scan)
    if proof_failure is not None:
        reason = proof_failure
        return _partial(plan, spec, scan, reason, candidates, accepted=accepted)
    count_trace: dict[str, JsonValue] = {
        "query_temporal_axis": temporal_query_axis(plan),
        "scan_temporal_axis": str(scan.get("scan_axis", "UNPROVEN")),
        "candidate_events": len(candidates),
        "accepted_events": sum(item["range_disposition"] == "INCLUDE" for item in candidates),
        "deduplicated_events": len(accepted),
        "excluded_planned": sum(
            item["range_disposition"] == "EXCLUDE_PLANNED" for item in candidates
        ),
        "excluded_cancelled": sum(
            item["range_disposition"] == "EXCLUDE_CANCELLED" for item in candidates
        ),
        "excluded_out_of_range": sum(
            item["temporal_range_disposition"] == "OUT_OF_RANGE" for item in candidates
        ),
        "unreadable_evidence_count": int(scan.get("unreadable_evidence_count", 0)),
        "source_count": _optional_int(scan.get("source_count")),
        "projected_count": _optional_int(scan.get("projected_count")),
    }
    return EvidenceCompositionResult(
        status="COMPLETE",
        operator=spec.operator,
        result=len(accepted),
        unit="APPOINTMENTS",
        display_value=str(len(accepted)),
        route_reason=str(plan.operator_arguments["route_reason"]),
        slot_schema_version=str(plan.operator_arguments["slot_schema_version"]),
        operands=accepted,
        evidence_refs=[item["evidence_id"] for item in accepted],
        source_turn_refs=[item["source_ref"] for item in accepted],
        completeness=CompositionCompleteness(
            required_slots=["MATCHING_EVENTS_IN_RANGE"],
            filled_slots=["MATCHING_EVENTS_IN_RANGE"],
            temporal_range_resolved=True,
            bounded_scan_complete=True,
            source_partition_closed=scan.get("source_partition_closed") is True,
            projection_watermark_covered=(scan.get("projection_watermark_covered") is True),
            projection_position=_optional_int(scan.get("projection_watermark")),
            target_position=_optional_int(scan.get("target_watermark")),
            query_temporal_axis=temporal_query_axis(plan),
            scan_temporal_axis=_validated_scan_axis(scan),
            temporal_domain_coverage="EXACT_AXIS_RANGE",
            deduplication_proven=True,
            unresolved_reasons=[],
        ),
        trace=_trace(spec, accepted, candidates, "COMPLETE", slot_complete=True),
        count_trace=count_trace,
    ).payload()


def compose_evidence_range_count(
    plan: QueryPlan,
    scan: Mapping[str, Any],
    *,
    compatibility_profile: Literal["legacy-v0.1", "dg22-v0.2"] = "legacy-v0.1",
) -> dict[str, Any] | None:
    """Execute a bounded distinct-event count for any typed event family."""

    event_type = plan.operator_arguments.get("event_type")
    if event_type == "DOCTOR_APPOINTMENT":
        return compose_appointment_count(plan, scan)
    spec = query_spec_from_plan(plan)
    if spec is None or spec.operator != "TEMPORAL_COUNT_DISTINCT" or event_type != "GENERIC_EVENT":
        return None
    interval = temporal_range(plan)
    if interval is None:
        return None
    items = scan.get("items")
    if not isinstance(items, list):
        return _partial(plan, spec, scan, "RANGE_SCAN_INVALID", [])
    axis_failure = _axis_failure(plan, scan)
    if axis_failure is not None:
        return _partial(plan, spec, scan, axis_failure, [])
    query_ir = plan.memory_query_ir
    if query_ir is None or query_ir.mode == "AMBIGUOUS":
        return None
    requirements = [
        requirement
        for requirement in query_ir.requirements
        if requirement.slot_id == "MATCHING_EVENTS_IN_RANGE"
    ]
    if len(requirements) != 1:
        return _partial(plan, spec, scan, "EVENT_REQUIREMENT_MISSING", [])
    source_items = [item for item in items if isinstance(item, Mapping)]
    spans = project_evidence_spans(source_items)
    span_by_id = {span.span_id: span for span in spans}
    interpretations = interpret_evidence_spans(
        spans,
        resolve_local_anchors=compatibility_profile == "dg22-v0.2",
    )
    bindings = bind_requirements(
        requirements,
        interpretations,
        spans,
        compatibility_profile=compatibility_profile,
    )
    binding_by_interpretation = {binding.interpretation_id: binding for binding in bindings}
    start, end = interval
    query_axis = temporal_query_axis(plan)
    candidates: list[dict[str, Any]] = []
    for interpretation in interpretations:
        if interpretation.kind != "EVENT":
            continue
        span = span_by_id[interpretation.span_id]
        binding = binding_by_interpretation[interpretation.interpretation_id]
        event_time = interpretation.event_time
        if query_axis == "SOURCE_OBSERVED_TIME":
            event_at = span.source_timestamp
            event_end = None
        else:
            event_at = event_time.start if event_time is not None else None
            event_end = event_time.end if event_time is not None else None
        status = _interpretation_event_status(interpretation)
        in_range = event_at is not None and (
            (event_at < end and event_end > start)
            if event_end is not None and event_end > event_at
            else start <= event_at < end
        )
        disposition = (
            "INCLUDE"
            if binding.status == "MATCH" and in_range and status == "OCCURRED"
            else f"EXCLUDE_BINDING_{binding.reason_code}"
            if binding.status != "MATCH"
            else f"EXCLUDE_{status}"
            if in_range
            else "EXCLUDE_OUT_OF_RANGE"
        )
        candidates.append(
            {
                "interpretation_id": interpretation.interpretation_id,
                "span_id": span.span_id,
                "event_at": event_at.isoformat() if event_at is not None else None,
                "event_time_basis": (
                    "SOURCE_OBSERVED_TIME"
                    if query_axis == "SOURCE_OBSERVED_TIME"
                    else interpretation.time_basis
                ),
                "source_timestamp": (
                    span.source_timestamp.isoformat() if span.source_timestamp is not None else None
                ),
                "system_timestamp": span.provenance.get("system_timestamp"),
                "event_status": status,
                "entity_compatibility": binding.compatibility.entity,
                "range_disposition": disposition,
                "temporal_range_disposition": "IN_RANGE" if in_range else "OUT_OF_RANGE",
                "dedup_key": _generic_event_identity(plan, interpretation, span),
                "episode_dedup_key": _generic_event_episode_key(
                    plan,
                    interpretation,
                    span,
                ),
                "evidence_id": span.source_evidence_id,
                "source_ref": span.source_turn_ref,
                "session_id": span.session_id,
                "speaker": span.speaker,
                "span_start": span.start,
                "span": span.text,
                "interpretation": interpretation.model_dump(mode="json"),
                "requirement_binding": binding.model_dump(mode="json"),
            }
        )
    accepted_by_key: dict[str, dict[str, Any]] = {}
    accepted_episode_keys: set[str] = set()
    for candidate in sorted(candidates, key=_generic_event_provenance_order):
        if candidate["range_disposition"] == "INCLUDE":
            dedup_key = str(candidate["dedup_key"])
            episode_key = candidate.get("episode_dedup_key")
            if dedup_key in accepted_by_key or (
                isinstance(episode_key, str) and episode_key in accepted_episode_keys
            ):
                continue
            accepted_by_key[dedup_key] = candidate
            if isinstance(episode_key, str):
                accepted_episode_keys.add(episode_key)
    accepted = list(accepted_by_key.values())
    unresolved_event_times = [
        item
        for item in candidates
        if item["event_at"] is None
        and item["event_status"] == "OCCURRED"
        and relevant_unresolved_event_binding(item["requirement_binding"])
    ]
    if unresolved_event_times:
        return _partial(
            plan,
            spec,
            scan,
            "EVENT_TIME_UNRESOLVED",
            candidates,
            accepted=accepted,
        )
    proof_failure = _complete_scan_proof_failure(scan)
    if proof_failure is not None:
        reason = proof_failure
        return _partial(plan, spec, scan, reason, candidates, accepted=accepted)
    count_trace: dict[str, JsonValue] = {
        "query_temporal_axis": query_axis,
        "scan_temporal_axis": str(scan.get("scan_axis", "UNPROVEN")),
        "candidate_events": len(candidates),
        "accepted_events": sum(item["range_disposition"] == "INCLUDE" for item in candidates),
        "deduplicated_events": len(accepted),
        "dedup_key_version": "generic-event-v0.2-binding",
        "excluded_planned": sum(
            item["range_disposition"] == "EXCLUDE_PLANNED" for item in candidates
        ),
        "excluded_cancelled": sum(
            item["range_disposition"] == "EXCLUDE_CANCELLED" for item in candidates
        ),
        "excluded_out_of_range": sum(
            item["temporal_range_disposition"] == "OUT_OF_RANGE" for item in candidates
        ),
        "unreadable_evidence_count": int(scan.get("unreadable_evidence_count", 0)),
        "source_count": _optional_int(scan.get("source_count")),
        "projected_count": _optional_int(scan.get("projected_count")),
    }
    return EvidenceCompositionResult(
        status="COMPLETE",
        operator=spec.operator,
        result=len(accepted),
        unit="EVENTS",
        display_value=str(len(accepted)),
        route_reason=str(plan.operator_arguments["route_reason"]),
        slot_schema_version=str(plan.operator_arguments["slot_schema_version"]),
        operands=accepted,
        evidence_refs=[str(item["evidence_id"]) for item in accepted],
        source_turn_refs=[str(item["source_ref"]) for item in accepted],
        completeness=CompositionCompleteness(
            required_slots=["MATCHING_EVENTS_IN_RANGE"],
            filled_slots=["MATCHING_EVENTS_IN_RANGE"],
            temporal_range_resolved=True,
            bounded_scan_complete=True,
            source_partition_closed=scan.get("source_partition_closed") is True,
            projection_watermark_covered=(scan.get("projection_watermark_covered") is True),
            projection_position=_optional_int(scan.get("projection_watermark")),
            target_position=_optional_int(scan.get("target_watermark")),
            query_temporal_axis=query_axis,
            scan_temporal_axis=_validated_scan_axis(scan),
            temporal_domain_coverage="EXACT_AXIS_RANGE",
            deduplication_proven=True,
            unresolved_reasons=[],
        ),
        trace=_trace(spec, accepted, candidates, "COMPLETE", slot_complete=True),
        count_trace=count_trace,
    ).payload()


def relevant_unresolved_event_binding(binding: object) -> bool:
    """MATCH or POSSIBLE non-temporal applicability may block COUNT completeness."""
    if not isinstance(binding, Mapping):
        return False
    compatibility = binding.get("compatibility")
    if not isinstance(compatibility, Mapping):
        return False
    required_axes = ("type", "entity", "predicate", "source", "role", "unit", "episode")
    values = [compatibility.get(axis) for axis in required_axes]
    return all(value in {"PASS", "UNKNOWN", "NOT_APPLICABLE"} for value in values)


def prioritize_temporal_evidence(
    scan: Mapping[str, Any], derived: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    items = [dict(item) for item in scan.get("items", []) if isinstance(item, dict)]
    if derived is None or derived.get("status") not in {"COMPLETE", "OK", "PARTIAL"}:
        return items
    refs = [str(value) for value in derived.get("evidence_refs", []) if isinstance(value, str)]
    operands = derived.get("operands")
    if isinstance(operands, list):
        for operand in operands:
            if not isinstance(operand, Mapping):
                continue
            evidence_id = operand.get("evidence_id")
            if isinstance(evidence_id, str):
                refs.append(evidence_id)
            evidence_ids = operand.get("evidence_ids")
            if isinstance(evidence_ids, list):
                refs.extend(str(value) for value in evidence_ids if isinstance(value, str))
    refs = list(dict.fromkeys(refs))
    if not refs:
        return items
    priority = {evidence_id: index for index, evidence_id in enumerate(refs)}
    return sorted(
        items,
        key=lambda item: (
            priority.get(str(item.get("evidence_id")), len(priority)),
            str(item.get("source_ref", "")),
        ),
    )


def _event_date(match: re.Match[str], reference_year: int) -> datetime:
    month = _MONTHS[match.group("month").casefold()]
    year = int(match.group("year") or reference_year)
    return datetime(year, month, int(match.group("day")), tzinfo=UTC)


def _attendance(sentence: str) -> str:
    if _CANCELLED.search(sentence):
        return "CANCELLED"
    if _PLANNED.search(sentence):
        return "PLANNED"
    if _ATTENDED.search(sentence):
        return "ATTENDED"
    return "UNRESOLVED"


def _provider_key(sentence: str) -> str:
    named = _PROVIDER.search(sentence)
    if named is not None:
        return f"dr-{named.group('name').casefold()}"
    for value in (
        "orthopedic surgeon",
        "primary care physician",
        "gastroenterologist",
        "neurologist",
        "doctor",
    ):
        if value in sentence.casefold():
            return value.replace(" ", "-")
    return "unknown-provider"


def _interpretation_event_status(
    interpretation: EvidenceInterpretationCandidate,
) -> str:
    value = interpretation.value
    if isinstance(value, dict):
        status = value.get("event_status")
        if status in {"OCCURRED", "PLANNED", "CANCELLED"}:
            return str(status)
    return "UNRESOLVED"


def _generic_event_identity(
    plan: QueryPlan,
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
) -> str:
    """Stable query-conditioned identity used only to deduplicate Evidence events."""

    event_at = interpretation.event_time.start if interpretation.event_time is not None else None
    date_key = event_at.date().isoformat() if event_at is not None else "unknown-date"
    raw_terms = plan.operator_arguments.get("event_terms")
    query_terms = (
        {str(value).casefold() for value in raw_terms if isinstance(value, str)}
        if isinstance(raw_terms, list)
        else set()
    )
    span_terms = {
        value.casefold()
        for value in re.findall(r"[^\W_]+", span.text, re.UNICODE)
        if len(value) > 2
    }
    distinctive = sorted(span_terms - query_terms - {"the", "and", "that", "this", "user"})
    semantic_fingerprint = "-".join(distinctive[:8]) or interpretation.predicate or "event"
    event_family = "-".join(sorted(query_terms)) or "generic-event"
    value = interpretation.value
    if isinstance(value, dict):
        event_identity = value.get("event_identity")
        if isinstance(event_identity, str) and event_identity:
            return f"{date_key}|{event_family}|identity:{event_identity.casefold()}"
    return f"{date_key}|{event_family}|{semantic_fingerprint}"


def _generic_event_episode_key(
    plan: QueryPlan,
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
) -> str | None:
    """Collapse unproven duplicates inside one dated source episode.

    Explicit event identities remain independently countable (for example,
    twins). Without one, paraphrases in the same session and on the same event
    date are evidence of one event, not proof of several distinct events.
    """

    value = interpretation.value
    if isinstance(value, dict) and value.get("event_identity"):
        return None
    event_at = interpretation.event_time.start if interpretation.event_time is not None else None
    date_key = event_at.date().isoformat() if event_at is not None else "unknown-date"
    raw_terms = plan.operator_arguments.get("event_terms")
    event_family = (
        "-".join(
            sorted(
                str(term).casefold()
                for term in raw_terms
                if isinstance(term, str) and term
            )
        )
        if isinstance(raw_terms, list)
        else "generic-event"
    )
    return f"{span.session_id}|{date_key}|{event_family or 'generic-event'}"


def _generic_event_provenance_order(candidate: Mapping[str, Any]) -> tuple[object, ...]:
    """Prefer direct user provenance and the earliest turn within an episode."""

    speaker_rank = {
        "user": 0,
        "assistant": 1,
        "tool": 2,
        "system": 3,
        "unknown": 4,
    }.get(str(candidate.get("speaker", "unknown")).casefold(), 4)
    source_ref = str(candidate.get("source_ref", ""))
    turn_identity = evidence_source_turn_identity(source_ref)
    episode = turn_identity[0] if turn_identity is not None else source_ref
    turn = turn_identity[1] if turn_identity is not None else 2**31 - 1
    return (
        str(candidate.get("source_timestamp") or ""),
        str(candidate.get("session_id") or episode),
        speaker_rank,
        turn,
        int(candidate.get("span_start") or 0),
        source_ref,
    )


def _partial(
    plan: QueryPlan,
    spec: QuerySpec,
    scan: Mapping[str, Any],
    reason: str,
    candidates: list[dict[str, Any]],
    *,
    accepted: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    retained = accepted or []
    count_trace: dict[str, JsonValue] = {
        "query_temporal_axis": temporal_query_axis(plan),
        "scan_temporal_axis": str(scan.get("scan_axis", "UNPROVEN")),
        "candidate_events": len(candidates),
        "accepted_events": sum(
            item.get("range_disposition") == "INCLUDE" for item in candidates
        ),
        "deduplicated_events": len(retained),
        "excluded_planned": sum(
            item.get("range_disposition") == "EXCLUDE_PLANNED" for item in candidates
        ),
        "excluded_cancelled": sum(
            item.get("range_disposition") == "EXCLUDE_CANCELLED" for item in candidates
        ),
        "unreadable_evidence_count": int(scan.get("unreadable_evidence_count", 0)),
    }
    return EvidenceCompositionResult(
        status="PARTIAL",
        operator=spec.operator,
        result=None,
        unit=None,
        reason=reason,
        route_reason=str(plan.operator_arguments.get("route_reason", "")),
        operands=retained,
        evidence_refs=[str(item["evidence_id"]) for item in retained],
        source_turn_refs=[str(item["source_ref"]) for item in retained],
        completeness=CompositionCompleteness(
            required_slots=["MATCHING_EVENTS_IN_RANGE"],
            filled_slots=[],
            temporal_range_resolved=temporal_range(plan) is not None,
            bounded_scan_complete=False,
            source_partition_closed=scan.get("source_partition_closed") is True,
            projection_watermark_covered=(scan.get("projection_watermark_covered") is True),
            projection_position=_optional_int(scan.get("projection_watermark")),
            target_position=_optional_int(scan.get("target_watermark")),
            query_temporal_axis=temporal_query_axis(plan),
            scan_temporal_axis=_validated_scan_axis(scan),
            temporal_domain_coverage="UNPROVEN",
            deduplication_proven=False,
            unresolved_reasons=[reason],
        ),
        trace=_trace(spec, retained, candidates, reason, slot_complete=False),
        count_trace=count_trace,
    ).payload()


def _trace(
    spec: QuerySpec,
    accepted: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    terminal_reason: str,
    *,
    slot_complete: bool,
) -> OperatorTrace:
    return OperatorTrace(
        query_spec=spec,
        slots=[
            EvidenceSlot(
                name="MATCHING_EVENTS_IN_RANGE",
                status="FILLED" if slot_complete else "INCOMPLETE",
                operands=accepted,
                unresolved_reason=None if slot_complete else terminal_reason,
            )
        ],
        applicability=[
            EvidenceApplicabilityResult(
                evidence_id=str(item["evidence_id"]),
                source_turn_ref=str(item["source_ref"]),
                slot="MATCHING_EVENTS_IN_RANGE",
                accepted=item["range_disposition"] == "INCLUDE",
                reason=str(item["range_disposition"]),
                span=str(item["span"]),
            )
            for item in candidates
        ],
        retrieval_attempts=1,
        expansion=["BOUNDED_TIME_RANGE_SCAN"],
        join="DISTINCT_EVENT_DEDUP",
        terminal_reason=terminal_reason,
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _validated_scan_axis(scan: Mapping[str, Any]) -> TemporalQueryAxis | None:
    value = scan.get("scan_axis")
    if value == "SOURCE_OBSERVED_TIME":
        return "SOURCE_OBSERVED_TIME"
    if value == "EVENT_OCCURRENCE_TIME":
        return "EVENT_OCCURRENCE_TIME"
    return None


def _complete_scan_proof_failure(scan: Mapping[str, Any]) -> str | None:
    if scan.get("status") != "COMPLETE":
        return (
            "PROJECTION_GAP"
            if scan.get("projection_watermark_covered") is not True
            else "BOUNDED_SCAN_INCOMPLETE"
        )
    if (
        scan.get("source_partition_closed") is not True
        or scan.get("projection_watermark_covered") is not True
        or scan.get("dead_letter_gap") is True
    ):
        return "PARTITION_OR_WATERMARK_PROOF_MISSING"
    items = scan.get("items")
    source_count = _optional_int(scan.get("source_count"))
    projected_count = _optional_int(scan.get("projected_count"))
    returned_count = _optional_int(scan.get("returned_count"))
    if returned_count is None and isinstance(items, list):
        returned_count = len(items)
    if source_count is not None and (
        projected_count != source_count or returned_count != source_count
    ):
        return "PARTITION_CARDINALITY_PROOF_MISMATCH"
    return None


def _failed_event_normalization(scan: dict[str, Any], reason: str) -> dict[str, Any]:
    scan.update(
        {
            "status": "PARTIAL" if scan.get("status") != "UNAVAILABLE" else "UNAVAILABLE",
            "event_normalization_status": "PARTIAL",
            "event_normalization_reason": reason,
            "time_axis_substitution": False,
        }
    )
    return scan


def _aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _axis_failure(plan: QueryPlan, scan: Mapping[str, Any]) -> str | None:
    expected = temporal_query_axis(plan)
    if _validated_scan_axis(scan) == expected:
        return None
    return (
        "SOURCE_TIME_DOMAIN_UNPROVEN"
        if expected == "SOURCE_OBSERVED_TIME"
        else "EVENT_TIME_DOMAIN_UNPROVEN"
    )
