"""Minimal deterministic state/change Formation over exact Raw Evidence spans."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from milai.application.evidence_semantics import resolve_direct_event_time
from milai.domain.formation_artifact import FormationSourceSpanV01
from milai.domain.formation_state import (
    FormationStateAssertionV01,
    FormationStateChangeSidecarV01,
    FormationStateTransitionV01,
)
from milai.domain.requirement_state import canonical_sha256

_MOVE = re.compile(
    r"(?P<whole>moved\s+from\s+(?P<old>[A-Z][\w-]*)\s+to\s+(?P<new>[A-Z][\w-]*))",
    re.I,
)
_CORRECTION = re.compile(
    r"Correction:\s*I\s+did\s+not\s+move\s+to\s+(?P<retracted>[A-Z][\w-]*);\s*"
    r"(?P<state>I\s+still\s+live\s+in\s+(?P<current>[A-Z][\w-]*))",
    re.I,
)
_TEMPORARY = re.compile(
    r"(?P<whole>Until\s+.+?,\s*(?P<state>I['\u2019]m\s+staying\s+in\s+"
    r"(?P<location>[A-Z][\w-]*)))",
    re.I,
)
_PREFERENCE = re.compile(
    r"(?P<whole>prefer\s+(?P<preferred>.+?)\s+to\s+(?P<other>.+?))(?=\s+when\b|[.!?]|$)",
    re.I,
)
_INTEREST = re.compile(
    r"(?P<whole>I\s+realized\s+how\s+much\s+I\s+"
    r"(?P<sentiment>love|like|enjoy|dislike|hate)\s+(?P<topic>[^.!?]+))",
    re.I,
)
_INTENT = re.compile(
    r"(?P<whole>I['\u2019]m\s+thinking\s+of\s+(?P<action>[^.!?]+))",
    re.I,
)
_PRODUCER = "deterministic-state-change-formation-v0.1"


class StateChangeFormationError(ValueError):
    """A source record cannot support a deterministic Formation artifact."""


def build_state_change_sidecar(
    source_records: Sequence[Mapping[str, Any]],
) -> FormationStateChangeSidecarV01:
    """Form explicit state/change patterns without Canonical promotion."""

    assertions: list[FormationStateAssertionV01] = []
    transitions: list[FormationStateTransitionV01] = []
    source_rows: list[dict[str, Any]] = []
    for source in source_records:
        evidence_id, source_ref, content = _source_fields(source)
        source_rows.append(
            {
                "evidence_id": evidence_id,
                "source_ref": source_ref,
                "content_digest": canonical_sha256(content),
                "observed_at": str(source.get("observed_at")),
            }
        )
        source_time = _timestamp(source.get("observed_at"))
        direct = resolve_direct_event_time(content, source_time)
        valid_time = direct[0] if direct is not None else None

        correction = _CORRECTION.search(content)
        if correction is not None:
            assertion = _assertion(
                _span(evidence_id, source_ref, content, correction, "state"),
                predicate="residence",
                value={"location": correction.group("current")},
                modality="ASSERTED",
                valid_time=None,
                review=True,
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    _whole_span(evidence_id, source_ref, content),
                    predicate="residence",
                    relation="CORRECTS",
                    previous_value={"location": correction.group("retracted")},
                    new_value={"location": correction.group("current")},
                    assertion=assertion,
                    valid_time=None,
                )
            )
            continue

        temporary = _TEMPORARY.search(content)
        if temporary is not None:
            assertion = _assertion(
                _span(evidence_id, source_ref, content, temporary, "state"),
                predicate="temporary_location",
                value={"location": temporary.group("location")},
                modality="TEMPORARY",
                valid_time=valid_time,
                review=True,
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    _span(evidence_id, source_ref, content, temporary, "whole"),
                    predicate="temporary_location",
                    relation="TEMPORARILY_CONSTRAINS",
                    previous_value=None,
                    new_value={"location": temporary.group("location")},
                    assertion=assertion,
                    valid_time=valid_time,
                )
            )
            continue

        move = _MOVE.search(content)
        if move is not None:
            destination_start, destination_end = move.span("new")
            assertion = _assertion(
                FormationSourceSpanV01(
                    evidence_id=evidence_id,
                    source_ref=source_ref,
                    start=destination_start,
                    end=destination_end,
                    text=content[destination_start:destination_end],
                ),
                predicate="residence",
                value={"location": move.group("new")},
                modality="ASSERTED",
                valid_time=valid_time,
                review=True,
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    _span(evidence_id, source_ref, content, move, "whole"),
                    predicate="residence",
                    relation="UPDATES",
                    previous_value={"location": move.group("old")},
                    new_value={"location": move.group("new")},
                    assertion=assertion,
                    valid_time=valid_time,
                )
            )
            continue

        preference = _PREFERENCE.search(content)
        if preference is not None:
            assertions.append(
                _assertion(
                    _span(evidence_id, source_ref, content, preference, "whole"),
                    predicate="seat_preference",
                    value={
                        "preferred": preference.group("preferred").strip(),
                        "over": preference.group("other").strip(),
                    },
                    modality="PREFERENCE",
                    valid_time=None,
                    review=True,
                )
            )
            continue

        interest = _INTEREST.search(content)
        if interest is not None:
            assertions.append(
                _assertion(
                    _span(evidence_id, source_ref, content, interest, "whole"),
                    predicate="music_interest",
                    value={
                        "sentiment": interest.group("sentiment").upper(),
                        "topic": interest.group("topic").strip(),
                    },
                    modality="PREFERENCE",
                    valid_time=None,
                    review=False,
                )
            )
        intent = _INTENT.search(content)
        if intent is not None:
            assertions.append(
                _assertion(
                    _span(evidence_id, source_ref, content, intent, "whole"),
                    predicate="current_intent",
                    value={"action": intent.group("action").strip()},
                    modality="INTENT",
                    valid_time=None,
                    review=False,
                )
            )

    assertions.sort(key=lambda item: (item.span.source_ref, item.span.start, item.predicate))
    transitions.sort(key=lambda item: (item.span.source_ref, item.span.start, item.relation))
    provisional = FormationStateChangeSidecarV01.model_construct(
        sidecar_digest="0" * 64,
        source_snapshot_digest=canonical_sha256(
            sorted(source_rows, key=lambda item: item["evidence_id"])
        ),
        assertions=assertions,
        transitions=transitions,
        producer_identities=[_PRODUCER],
    )
    material = provisional.model_dump(mode="json", exclude={"sidecar_digest"})
    return FormationStateChangeSidecarV01(
        sidecar_digest=canonical_sha256(material),
        **material,
    )


def _assertion(
    span: FormationSourceSpanV01,
    *,
    predicate: str,
    value: Any,
    modality: str,
    valid_time: Any,
    review: bool,
) -> FormationStateAssertionV01:
    provisional = FormationStateAssertionV01.model_construct(
        artifact_digest="0" * 64,
        span=span,
        subject_identity="subject:self",
        predicate=predicate,
        value=value,
        modality=modality,
        valid_time=valid_time,
        producer_identity=_PRODUCER,
        promotion_disposition=(
            "GOVERNED_REVIEW_REQUIRED" if review else "QUERY_LOCAL_ONLY"
        ),
    )
    material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
    return FormationStateAssertionV01(
        artifact_digest=canonical_sha256(material),
        **material,
    )


def _transition(
    span: FormationSourceSpanV01,
    *,
    predicate: str,
    relation: str,
    previous_value: Any,
    new_value: Any,
    assertion: FormationStateAssertionV01,
    valid_time: Any,
) -> FormationStateTransitionV01:
    provisional = FormationStateTransitionV01.model_construct(
        artifact_digest="0" * 64,
        span=span,
        subject_identity="subject:self",
        predicate=predicate,
        relation=relation,
        previous_value=previous_value,
        new_value=new_value,
        resulting_assertion_digest=assertion.artifact_digest,
        valid_time=valid_time,
        producer_identity=_PRODUCER,
    )
    material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
    return FormationStateTransitionV01(
        artifact_digest=canonical_sha256(material),
        **material,
    )


def _source_fields(source: Mapping[str, Any]) -> tuple[str, str, str]:
    values = (source.get("evidence_id"), source.get("source_ref"), source.get("content"))
    if not all(isinstance(value, str) and value for value in values):
        raise StateChangeFormationError("FORMATION_STATE_SOURCE_INVALID")
    return str(values[0]), str(values[1]), str(values[2])


def _span(
    evidence_id: str,
    source_ref: str,
    content: str,
    match: re.Match[str],
    group: str,
) -> FormationSourceSpanV01:
    start, end = match.span(group)
    return FormationSourceSpanV01(
        evidence_id=evidence_id,
        source_ref=source_ref,
        start=start,
        end=end,
        text=content[start:end],
    )


def _whole_span(evidence_id: str, source_ref: str, content: str) -> FormationSourceSpanV01:
    return FormationSourceSpanV01(
        evidence_id=evidence_id,
        source_ref=source_ref,
        start=0,
        end=len(content),
        text=content,
    )


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return value if isinstance(value, datetime) else None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


__all__ = ["StateChangeFormationError", "build_state_change_sidecar"]
