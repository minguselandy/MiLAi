"""Structured Evidence-source metadata validation.

Speaker identity is lineage supplied by ingest/projection.  It is never
reconstructed from Evidence body text.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

EvidenceSpeaker = Literal["user", "assistant", "system", "tool", "unknown"]
EvidenceSpeakerSource = Literal[
    "STRUCTURED_TURN_METADATA",
    "AUTHORITATIVE_BACKFILL",
    "UNKNOWN",
]
EvidenceIdentitySource = Literal[
    "STRUCTURED_TURN_METADATA",
    "AUTHORITATIVE_BACKFILL",
    "UNKNOWN",
]


@dataclass(frozen=True, slots=True)
class EvidenceSourceIdentity:
    """Distinct subject/session/turn identities carried by one Evidence row."""

    subject_id: str
    session_id: str
    turn_id: str
    identity_source: EvidenceIdentitySource

_KNOWN_SPEAKERS = frozenset({"user", "assistant", "system", "tool"})
_AUTHORITATIVE_SOURCES = frozenset(
    {"STRUCTURED_TURN_METADATA", "AUTHORITATIVE_BACKFILL"}
)
_SOURCE_TURN = re.compile(
    r"^(?P<episode>.+?)(?:(?::t)|(?:/(?:turn|t)[/-]))"
    r"(?P<turn>\d+)(?=$|[?#])",
    re.IGNORECASE,
)


def structured_evidence_speaker(
    item: Mapping[str, Any],
) -> tuple[EvidenceSpeaker, EvidenceSpeakerSource]:
    """Return validated lineage or a neutral unknown value.

    A speaker value without authoritative source metadata is intentionally
    treated as unknown.  Body prefixes are outside this ownership boundary.
    """

    speaker = item.get("speaker")
    source = item.get("speaker_source")
    if speaker not in _KNOWN_SPEAKERS or source not in _AUTHORITATIVE_SOURCES:
        return "unknown", "UNKNOWN"
    return cast(EvidenceSpeaker, speaker), cast(EvidenceSpeakerSource, source)


def evidence_source_turn_identity(source_ref: str) -> tuple[str, int] | None:
    """Parse an episode prefix and turn ordinal from an opaque source reference.

    Turn references may use compact ``:tN`` notation or path-based
    ``/turn/N`` and ``/turn-N`` notation.  Query strings and fragments are
    provenance qualifiers, not part of the turn ordinal.  Callers retain the
    full episode prefix instead of guessing a provider-specific session path.
    """

    matched = _SOURCE_TURN.search(source_ref)
    if matched is None:
        return None
    return matched.group("episode"), int(matched.group("turn"))


def structured_evidence_identity(
    item: Mapping[str, Any],
    source_ref: str,
) -> EvidenceSourceIdentity | None:
    """Resolve identity without conflating the remembered subject and session.

    Legacy source-reference parsing remains available for replay, but it is
    explicitly marked ``UNKNOWN`` and therefore cannot satisfy the structured
    identity-integrity gate.
    """

    subject_id = item.get("subject_id")
    if not isinstance(subject_id, str) or not subject_id:
        return None
    source_context = item.get("source_context")
    source = item.get("source_context_source")
    if source in _AUTHORITATIVE_SOURCES and isinstance(source_context, Mapping):
        session_id = source_context.get("session_id")
        turn_id = source_context.get("turn_id")
        if (
            isinstance(session_id, str)
            and session_id
            and isinstance(turn_id, str)
            and turn_id
        ):
            return EvidenceSourceIdentity(
                subject_id=subject_id,
                session_id=session_id,
                turn_id=turn_id,
                identity_source=cast(EvidenceIdentitySource, source),
            )
    parsed = evidence_source_turn_identity(source_ref)
    if parsed is not None:
        session_id, turn_ordinal = parsed
        return EvidenceSourceIdentity(
            subject_id=subject_id,
            session_id=session_id,
            turn_id=f"{session_id}:t{turn_ordinal}",
            identity_source="UNKNOWN",
        )
    return EvidenceSourceIdentity(
        subject_id=subject_id,
        session_id=subject_id,
        turn_id=source_ref,
        identity_source="UNKNOWN",
    )


__all__ = [
    "EvidenceIdentitySource",
    "EvidenceSourceIdentity",
    "EvidenceSpeaker",
    "EvidenceSpeakerSource",
    "evidence_source_turn_identity",
    "structured_evidence_identity",
    "structured_evidence_speaker",
]
