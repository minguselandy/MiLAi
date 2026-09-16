"""Minimal raw-preserving Formation sidecar for identity and event time."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from milai.application.evidence_semantics import (
    direct_event_time_expression_count,
    interpret_evidence_spans,
    project_evidence_spans,
    resolve_direct_event_time,
)
from milai.domain.formation_artifact import (
    FormationArtifactSidecarV01,
    FormationEntityCandidateV01,
    FormationEventCandidateV01,
    FormationModelEventProposalV01,
    FormationSourceSpanV01,
    FormationTemporalRelationProposalV01,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import InterpretationEventTime

_SELF = re.compile(r"(?<![\w'])I(?!\w)")
_BIRTH = re.compile(r"\b(?:bab(?:y|ies)|born|twins?|welcomed)\b", re.I)
_TEMPORAL_RELATION_TEXT = re.compile(
    r"\b(?P<count>a few|a|an|few|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?P<unit>days?|weeks?|months?)\s+(?P<relation>after|before)\b",
    re.I,
)
_SAME_TIME_TEXT = re.compile(r"\b(?:at\s+the\s+same\s+time|same\s+time\s+as)\b", re.I)
_RELATION_COUNTS = {
    "a": 1,
    "an": 1,
    "a few": 3,
    "few": 3,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "for",
        "from",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "the",
        "to",
        "was",
        "with",
    }
)
_DETERMINISTIC_PRODUCER = "deterministic-formation-v0.1"


class FormationExtractionError(ValueError):
    """A model proposal or source identity failed Formation validation."""


def build_formation_sidecar(
    source_records: Sequence[Mapping[str, Any]],
    *,
    model_event_proposals: Sequence[FormationModelEventProposalV01] = (),
    model_identity: str | None = None,
    model_calls: int = 0,
) -> FormationArtifactSidecarV01:
    """Build deterministic artifacts and add only Runtime-valid model proposals."""

    source_by_id = _source_index(source_records)
    spans = project_evidence_spans(source_records)
    interpretations = interpret_evidence_spans(spans, resolve_local_anchors=True)
    span_by_id = {item.span_id: item for item in spans}

    entities = _deterministic_entities(source_by_id)
    events: list[FormationEventCandidateV01] = []
    for interpretation in interpretations:
        if interpretation.kind != "EVENT":
            continue
        span = span_by_id[interpretation.span_id]
        value = interpretation.value if isinstance(interpretation.value, Mapping) else {}
        explicit_identity = value.get("event_identity")
        primary_subject = (
            str(explicit_identity)
            if isinstance(explicit_identity, str) and explicit_identity
            else None
        )
        event_type = "birth" if _BIRTH.search(span.text) is not None else "event"
        identity_key = _event_identity_key(
            event_type=event_type,
            primary_subject=primary_subject,
            span_text=span.text,
            occurrence_time=interpretation.event_time,
            source_evidence_id=span.source_evidence_id,
        )
        events.append(
            _event_candidate(
                span=FormationSourceSpanV01(
                    evidence_id=span.source_evidence_id,
                    source_ref=span.source_turn_ref,
                    start=span.start,
                    end=span.end,
                    text=span.text,
                ),
                event_type=event_type,
                primary_subject=primary_subject,
                context_participants=[],
                event_identity_key=identity_key,
                occurrence_time=interpretation.event_time,
                time_basis=interpretation.time_basis,
                temporal_anchor_spans=[],
                negated=value.get("event_status") == "NEGATED",
                confidence_feature=interpretation.confidence,
                producer_identity=_DETERMINISTIC_PRODUCER,
                provenance={
                    "source_interpretation_id": interpretation.interpretation_id,
                    "source_time_substitution": False,
                },
            )
        )

    rejected: list[str] = []
    model_events: list[FormationEventCandidateV01] = []
    if model_event_proposals and not model_identity:
        raise FormationExtractionError("MODEL_IDENTITY_REQUIRED_FOR_MODEL_PROPOSALS")
    for index, proposal in enumerate(model_event_proposals):
        try:
            model_events.append(
                _materialize_model_event(
                    proposal,
                    source_by_id,
                    model_identity=str(model_identity),
                )
            )
        except FormationExtractionError as error:
            rejected.append(f"proposal:{index}:{error}")
    events = _merge_events(events, model_events)
    entities.sort(key=lambda item: (item.span.source_ref, item.span.start, item.identity_key))
    events.sort(
        key=lambda item: (
            item.span.source_ref,
            item.span.start,
            item.event_identity_key,
        )
    )
    producer_identities = {_DETERMINISTIC_PRODUCER}
    if model_event_proposals and model_identity is not None:
        producer_identities.add(model_identity)
    source_snapshot_digest = canonical_sha256(
        [
            _source_snapshot_row(evidence_id, source)
            for evidence_id, source in sorted(source_by_id.items())
        ]
    )
    provisional = FormationArtifactSidecarV01.model_construct(
        sidecar_digest="0" * 64,
        source_snapshot_digest=source_snapshot_digest,
        entity_candidates=entities,
        event_candidates=events,
        rejected_model_outputs=sorted(set(rejected)),
        producer_identities=sorted(producer_identities),
        model_calls=model_calls,
    )
    material = provisional.model_dump(mode="json", exclude={"sidecar_digest"})
    return FormationArtifactSidecarV01(
        sidecar_digest=canonical_sha256(material),
        **material,
    )


def _deterministic_entities(
    source_by_id: Mapping[str, Mapping[str, Any]],
) -> list[FormationEntityCandidateV01]:
    output: list[FormationEntityCandidateV01] = []
    for evidence_id, source in sorted(source_by_id.items()):
        if str(source.get("speaker", "")).casefold() != "user":
            continue
        content = str(source["content"])
        for matched in _SELF.finditer(content):
            span = FormationSourceSpanV01(
                evidence_id=evidence_id,
                source_ref=str(source["source_ref"]),
                start=matched.start(),
                end=matched.end(),
                text=matched.group(0),
            )
            provisional = FormationEntityCandidateV01.model_construct(
                artifact_digest="0" * 64,
                span=span,
                identity_key="subject:self",
                mention_type="SELF_MENTION",
                producer_identity=_DETERMINISTIC_PRODUCER,
            )
            material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
            output.append(
                FormationEntityCandidateV01(
                    artifact_digest=canonical_sha256(material),
                    **material,
                )
            )
    return output


def _materialize_model_event(
    proposal: FormationModelEventProposalV01,
    source_by_id: Mapping[str, Mapping[str, Any]],
    *,
    model_identity: str,
) -> FormationEventCandidateV01:
    source = source_by_id.get(proposal.evidence_id)
    if source is None:
        raise FormationExtractionError("MODEL_EVENT_SOURCE_MISSING")
    content = str(source["content"])
    if content.count(proposal.grounded_quote) != 1:
        raise FormationExtractionError("MODEL_EVENT_QUOTE_NOT_UNIQUE_EXACT")
    start = content.index(proposal.grounded_quote)
    span = FormationSourceSpanV01(
        evidence_id=proposal.evidence_id,
        source_ref=str(source["source_ref"]),
        start=start,
        end=start + len(proposal.grounded_quote),
        text=proposal.grounded_quote,
    )
    source_timestamp = _timestamp(source.get("observed_at"))
    direct = resolve_direct_event_time(proposal.grounded_quote, source_timestamp)
    anchor_spans: list[FormationSourceSpanV01] = []
    if direct is not None:
        occurrence_time, time_basis = direct
        provenance: dict[str, Any] = {
            "normalizer": "deterministic-event-time-v0.2",
            "source_time_substitution": False,
            "model_proposed_relation_used": False,
        }
    elif proposal.temporal_relation is not None:
        occurrence_time, anchor_span = _resolve_temporal_relation(
            proposal.temporal_relation,
            proposal.grounded_quote,
            source_by_id,
        )
        time_basis = "INFERRED_EVENT_TIME"
        anchor_spans = [anchor_span]
        provenance = {
            "normalizer": "formation-cross-evidence-temporal-v0.1",
            "source_time_substitution": False,
            "model_proposed_relation_used": True,
        }
    else:
        occurrence_time = None
        time_basis = "UNRESOLVED"
        provenance = {
            "normalizer": "deterministic-event-time-v0.2",
            "source_time_substitution": False,
            "model_proposed_relation_used": False,
        }
    identity_key = _event_identity_key(
        event_type=proposal.event_type,
        primary_subject=proposal.primary_subject,
        span_text=proposal.grounded_quote,
        occurrence_time=occurrence_time,
        source_evidence_id=proposal.evidence_id,
    )
    return _event_candidate(
        span=span,
        event_type=proposal.event_type,
        primary_subject=proposal.primary_subject,
        context_participants=sorted(set(proposal.context_participants)),
        event_identity_key=identity_key,
        occurrence_time=occurrence_time,
        time_basis=time_basis,
        temporal_anchor_spans=anchor_spans,
        negated=proposal.negated,
        confidence_feature=proposal.confidence_feature,
        producer_identity=model_identity,
        provenance=provenance,
    )


def _resolve_temporal_relation(
    relation: FormationTemporalRelationProposalV01,
    target_quote: str,
    source_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[InterpretationEventTime, FormationSourceSpanV01]:
    normalized = relation.normalized_from.casefold()
    if relation.normalized_from not in target_quote:
        raise FormationExtractionError("TEMPORAL_RELATION_NOT_TARGET_GROUNDED")
    parsed_relation, parsed_amount, parsed_unit = _parse_temporal_relation(normalized)
    if relation.relation != parsed_relation:
        raise FormationExtractionError("TEMPORAL_RELATION_WORD_MISMATCH")
    anchor = source_by_id.get(relation.anchor_evidence_id)
    if anchor is None:
        raise FormationExtractionError("TEMPORAL_ANCHOR_SOURCE_MISSING")
    content = str(anchor["content"])
    if content.count(relation.anchor_quote) != 1:
        raise FormationExtractionError("TEMPORAL_ANCHOR_QUOTE_NOT_UNIQUE_EXACT")
    anchor_start = content.index(relation.anchor_quote)
    anchor_span = FormationSourceSpanV01(
        evidence_id=relation.anchor_evidence_id,
        source_ref=str(anchor["source_ref"]),
        start=anchor_start,
        end=anchor_start + len(relation.anchor_quote),
        text=relation.anchor_quote,
    )
    if direct_event_time_expression_count(relation.anchor_quote) > 1:
        raise FormationExtractionError("TEMPORAL_ANCHOR_TIME_AMBIGUOUS")
    direct = resolve_direct_event_time(
        relation.anchor_quote,
        _timestamp(anchor.get("observed_at")),
    )
    if direct is None or direct[0].start is None:
        raise FormationExtractionError("TEMPORAL_ANCHOR_TIME_UNRESOLVED")
    anchor_time = direct[0]
    anchor_start_time = anchor_time.start
    assert anchor_start_time is not None
    anchor_end_time = anchor_time.end or anchor_start_time
    delta = _relation_delta(parsed_amount, parsed_unit)
    if parsed_relation == "AFTER":
        start = anchor_start_time + delta
        end = anchor_end_time + delta
    elif parsed_relation == "BEFORE":
        start = anchor_start_time - delta
        end = anchor_end_time - delta
    else:
        start = anchor_start_time
        end = anchor_end_time
    return (
        InterpretationEventTime(
            start=start,
            end=end,
            normalized_from=relation.normalized_from,
            anchor_provenance={
                "anchor_kind": "MODEL_PROPOSED_RUNTIME_VALIDATED_CROSS_EVIDENCE",
                "anchor_evidence_id": relation.anchor_evidence_id,
                "anchor_source_ref": str(anchor["source_ref"]),
                "anchor_start": anchor_span.start,
                "anchor_end": anchor_span.end,
                "relation": parsed_relation,
                "amount": parsed_amount,
                "unit": parsed_unit,
                "model_amount_advisory": relation.amount,
                "model_unit_advisory": relation.unit,
                "source_time_substitution": False,
            },
        ),
        anchor_span,
    )


def _parse_temporal_relation(value: str) -> tuple[str, int, str]:
    matched = _TEMPORAL_RELATION_TEXT.search(value)
    if matched is not None:
        raw_count = matched.group("count").casefold()
        count = int(raw_count) if raw_count.isdecimal() else _RELATION_COUNTS[raw_count]
        unit = matched.group("unit").upper().rstrip("S")
        return matched.group("relation").upper(), count, unit
    if _SAME_TIME_TEXT.search(value) is not None:
        return "SAME_TIME", 0, "DAY"
    raise FormationExtractionError("TEMPORAL_RELATION_NOT_RUNTIME_PARSEABLE")


def _relation_delta(amount: int, unit: str) -> timedelta:
    if unit == "DAY":
        return timedelta(days=amount)
    if unit == "WEEK":
        return timedelta(weeks=amount)
    return timedelta(days=30 * amount)


def _merge_events(
    deterministic: Sequence[FormationEventCandidateV01],
    model: Sequence[FormationEventCandidateV01],
) -> list[FormationEventCandidateV01]:
    output = list(deterministic)
    for candidate in model:
        replacements = [
            item
            for item in output
            if item.span.evidence_id == candidate.span.evidence_id
            and _overlap(item.span, candidate.span)
            and (
                candidate.primary_subject is None
                or item.primary_subject is None
                or item.primary_subject.casefold() == candidate.primary_subject.casefold()
            )
        ]
        if replacements and candidate.occurrence_time is None and all(
            item.occurrence_time is not None for item in replacements
        ):
            continue
        output = [item for item in output if item not in replacements]
        output.append(candidate)
    unique = {item.artifact_digest: item for item in output}
    return list(unique.values())


def _overlap(left: FormationSourceSpanV01, right: FormationSourceSpanV01) -> bool:
    return left.start < right.end and right.start < left.end


def _event_identity_key(
    *,
    event_type: str,
    primary_subject: str | None,
    span_text: str,
    occurrence_time: InterpretationEventTime | None,
    source_evidence_id: str,
) -> str:
    if primary_subject:
        subject = primary_subject.casefold().strip()
    else:
        terms = sorted(
            {
                item.casefold()
                for item in _WORD.findall(span_text)
                if len(item) > 2 and item.casefold() not in _STOP
            }
        )
        subject = "-".join(terms[:12]) or "event"
    time_key = (
        occurrence_time.start.isoformat()
        if occurrence_time is not None and occurrence_time.start is not None
        else "time-unresolved"
    )
    material = {
        "event_type": event_type.casefold(),
        "subject": subject,
        "time": time_key,
        "source_fallback": None if primary_subject else source_evidence_id,
    }
    return f"event:{canonical_sha256(material)}"


def _event_candidate(**values: Any) -> FormationEventCandidateV01:
    provisional = FormationEventCandidateV01.model_construct(
        artifact_digest="0" * 64,
        **values,
    )
    material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
    return FormationEventCandidateV01(
        artifact_digest=canonical_sha256(material),
        **material,
    )


def _source_index(
    source_records: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for source in source_records:
        evidence_id = source.get("evidence_id")
        content = source.get("content")
        source_ref = source.get("source_ref")
        if not all(
            isinstance(value, str) and value
            for value in (evidence_id, content, source_ref)
        ):
            raise FormationExtractionError("FORMATION_SOURCE_IDENTITY_INVALID")
        assert isinstance(evidence_id, str)
        if evidence_id in result:
            raise FormationExtractionError("FORMATION_SOURCE_DUPLICATED")
        result[evidence_id] = source
    return result


def _timestamp(value: object) -> datetime | None:
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
    return parsed


def _source_snapshot_row(
    evidence_id: str,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    observed_at = _timestamp(source.get("observed_at"))
    return {
        "evidence_id": evidence_id,
        "source_ref": source["source_ref"],
        "content_digest": canonical_sha256(source["content"]),
        "observed_at": observed_at.isoformat() if observed_at is not None else None,
    }


__all__ = [
    "FormationExtractionError",
    "build_formation_sidecar",
]
