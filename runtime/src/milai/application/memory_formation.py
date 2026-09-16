"""Build one query-independent Memory Formation bundle from Raw Evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from milai.application.formation_extraction import build_formation_sidecar
from milai.application.state_change_formation import build_state_change_sidecar
from milai.domain.formation_artifact import FormationSourceSpanV01
from milai.domain.memory_formation import (
    EpisodeBoundaryReason,
    MemoryFormationBundleV01,
    MemoryFormationReceiptV01,
    ParticipantRole,
    SemanticEpisodeCandidateV01,
)
from milai.domain.requirement_state import canonical_sha256

_PRODUCER = "deterministic-memory-formation-bundle-v0.1"
_TIME_GAP = timedelta(hours=6)
_EXPLICIT_SHIFT = re.compile(
    r"(?:\bby\s+the\s+way\b|\bchanging\s+topics?\b|\bchange\s+of\s+topic\b|"
    r"\bon\s+another\s+topic\b|\bseparately\b|换个话题|另外一件事|说到别的)",
    re.IGNORECASE,
)
_CORRECTION_CONTINUATION = re.compile(
    r"^(?:correction|actually|to\s+correct\s+that|I\s+meant|更正|纠正一下|其实)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "for",
        "from",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "the",
        "that",
        "this",
        "to",
        "was",
        "were",
        "when",
        "with",
        "you",
        "我",
        "的",
        "了",
        "很",
        "在",
        "是",
    }
)


class MemoryFormationError(ValueError):
    """The Raw Evidence snapshot cannot support a complete Formation build."""


@dataclass(frozen=True, slots=True)
class MemoryFormationBuildResult:
    bundle: MemoryFormationBundleV01
    receipt: MemoryFormationReceiptV01


@dataclass(frozen=True, slots=True)
class _SourceTurn:
    raw: Mapping[str, Any]
    evidence_id: str
    source_ref: str
    session_id: str
    speaker: ParticipantRole
    observed_at: datetime
    content: str


class MemoryFormationBundleService:
    """Application service with no Provider, Reader, Retrieval, or DB dependency."""

    def build(self, source_records: Sequence[Mapping[str, Any]]) -> MemoryFormationBuildResult:
        turns = _validate_sources(source_records)
        episodes = _build_episodes(turns)
        user_sources = [dict(item.raw) for item in turns if item.speaker == "user"]
        semantic_sidecar = build_formation_sidecar(user_sources)
        state_sidecar = build_state_change_sidecar(user_sources)
        snapshot_digest = canonical_sha256([_snapshot_row(item) for item in turns])
        source_ids = [item.evidence_id for item in turns]
        source_watermark = max(item.observed_at for item in turns)
        provisional = MemoryFormationBundleV01.model_construct(
            bundle_digest="0" * 64,
            source_snapshot_digest=snapshot_digest,
            source_evidence_ids=source_ids,
            source_watermark=source_watermark,
            episode_candidates=episodes,
            semantic_sidecar=semantic_sidecar,
            state_change_sidecar=state_sidecar,
            producer_identity=_PRODUCER,
        )
        material = provisional.model_dump(mode="json", exclude={"bundle_digest"})
        bundle = MemoryFormationBundleV01(
            bundle_digest=canonical_sha256(material),
            **material,
        )
        receipt_provisional = MemoryFormationReceiptV01.model_construct(
            receipt_digest="0" * 64,
            bundle_digest=bundle.bundle_digest,
            source_snapshot_digest=bundle.source_snapshot_digest,
            source_watermark=bundle.source_watermark,
            source_evidence_ids=bundle.source_evidence_ids,
            episode_digests=[item.episode_digest for item in bundle.episode_candidates],
            semantic_sidecar_digest=bundle.semantic_sidecar.sidecar_digest,
            state_change_sidecar_digest=bundle.state_change_sidecar.sidecar_digest,
        )
        receipt_material = receipt_provisional.model_dump(mode="json", exclude={"receipt_digest"})
        receipt = MemoryFormationReceiptV01(
            receipt_digest=canonical_sha256(receipt_material),
            **receipt_material,
        )
        return MemoryFormationBuildResult(bundle=bundle, receipt=receipt)


def build_memory_formation_bundle(
    source_records: Sequence[Mapping[str, Any]],
) -> MemoryFormationBuildResult:
    """Convenience entry point for one deterministic, query-independent build."""

    return MemoryFormationBundleService().build(source_records)


def _validate_sources(
    source_records: Sequence[Mapping[str, Any]],
) -> list[_SourceTurn]:
    if not source_records:
        raise MemoryFormationError("FORMATION_SOURCE_SNAPSHOT_EMPTY")
    turns: list[_SourceTurn] = []
    evidence_ids: set[str] = set()
    source_refs: set[str] = set()
    for source in source_records:
        evidence_id = _text(source.get("evidence_id"), "EVIDENCE_ID")
        source_ref = _text(source.get("source_ref"), "SOURCE_REF")
        session_id = _text(source.get("session_id"), "SESSION_ID")
        content = _text(source.get("content"), "CONTENT")
        raw_speaker = _text(source.get("speaker"), "SPEAKER").casefold()
        if raw_speaker not in {"user", "assistant"}:
            raise MemoryFormationError("FORMATION_SOURCE_ROLE_INVALID")
        speaker: ParticipantRole = "user" if raw_speaker == "user" else "assistant"
        observed_at = _timestamp(source.get("observed_at"))
        if evidence_id in evidence_ids or source_ref in source_refs:
            raise MemoryFormationError("FORMATION_SOURCE_IDENTITY_DUPLICATED")
        if source.get("revoked_at") not in {None, ""}:
            raise MemoryFormationError("FORMATION_SOURCE_REVOKED")
        retention = source.get("retention_state")
        if retention is not None and retention != "READABLE":
            raise MemoryFormationError("FORMATION_SOURCE_RETENTION_BLOCKED")
        permission = source.get("permission_snapshot")
        if isinstance(permission, Mapping) and permission.get("readable") is not True:
            raise MemoryFormationError("FORMATION_SOURCE_PERMISSION_BLOCKED")
        turns.append(
            _SourceTurn(
                raw=source,
                evidence_id=evidence_id,
                source_ref=source_ref,
                session_id=session_id,
                speaker=speaker,
                observed_at=observed_at,
                content=content,
            )
        )
        evidence_ids.add(evidence_id)
        source_refs.add(source_ref)
    if any(right.observed_at < left.observed_at for left, right in pairwise(turns)):
        raise MemoryFormationError("FORMATION_SOURCE_ORDER_INVALID")
    if not any(item.speaker == "user" for item in turns):
        raise MemoryFormationError("FORMATION_USER_EVIDENCE_REQUIRED")
    return turns


def _build_episodes(turns: Sequence[_SourceTurn]) -> list[SemanticEpisodeCandidateV01]:
    groups: list[tuple[EpisodeBoundaryReason, list[_SourceTurn]]] = []
    for turn in turns:
        if not groups:
            groups.append(("CONVERSATION_START", [turn]))
            continue
        current = groups[-1][1]
        reason = _boundary_reason(current, turn)
        if reason is None:
            current.append(turn)
        else:
            groups.append((reason, [turn]))
    return [_episode(reason, group) for reason, group in groups]


def _boundary_reason(
    current: Sequence[_SourceTurn], turn: _SourceTurn
) -> EpisodeBoundaryReason | None:
    previous = current[-1]
    if turn.session_id != previous.session_id:
        return "SESSION_CHANGE"
    if turn.speaker == "assistant":
        return "TIME_GAP" if turn.observed_at - previous.observed_at >= _TIME_GAP else None
    if _EXPLICIT_SHIFT.search(turn.content) is not None:
        return "EXPLICIT_TOPIC_SHIFT"
    if _CORRECTION_CONTINUATION.search(turn.content) is not None:
        return None
    previous_content = previous.content.rstrip()
    if previous.speaker == "assistant" and (
        previous_content.endswith("?") or previous_content.endswith("\uff1f")
    ):
        return None
    prior_user_terms = {
        term for item in current if item.speaker == "user" for term in _topic_terms(item.content)
    }
    current_terms = set(_topic_terms(turn.content))
    if _semantically_related(prior_user_terms, current_terms):
        return None
    if turn.observed_at - previous.observed_at >= _TIME_GAP:
        return "TIME_GAP"
    return "SEMANTIC_TOPIC_SHIFT"


def _semantically_related(prior_terms: set[str], current_terms: set[str]) -> bool:
    """Require lexical cohesion, not a single ambiguous token, for continuation."""

    if not prior_terms or not current_terms:
        return True
    common = prior_terms & current_terms
    if len(common) >= 2:
        return True
    if len(common) == 1 and min(len(prior_terms), len(current_terms)) == 1:
        return True
    return len(common) / len(prior_terms | current_terms) >= 0.18


def _episode(
    reason: EpisodeBoundaryReason,
    turns: Sequence[_SourceTurn],
) -> SemanticEpisodeCandidateV01:
    spans = [
        FormationSourceSpanV01(
            evidence_id=item.evidence_id,
            source_ref=item.source_ref,
            start=0,
            end=len(item.content),
            text=item.content,
        )
        for item in turns
    ]
    terms = sorted({term for item in turns for term in _topic_terms(item.content)})[:64]
    provisional = SemanticEpisodeCandidateV01.model_construct(
        episode_digest="0" * 64,
        source_spans=spans,
        participant_roles=[item.speaker for item in turns],
        topic_terms=terms,
        boundary_reason=reason,
        source_time_start=min(item.observed_at for item in turns),
        source_time_end=max(item.observed_at for item in turns),
        producer_identity=_PRODUCER,
    )
    material = provisional.model_dump(mode="json", exclude={"episode_digest"})
    return SemanticEpisodeCandidateV01(
        episode_digest=canonical_sha256(material),
        **material,
    )


def _topic_terms(value: str) -> list[str]:
    return sorted(
        {
            item.casefold()
            for item in _WORD.findall(value)
            if len(item) > 1 and item.casefold() not in _STOP
        }
    )


def _snapshot_row(turn: _SourceTurn) -> dict[str, Any]:
    return {
        "evidence_id": turn.evidence_id,
        "source_ref": turn.source_ref,
        "session_id": turn.session_id,
        "speaker": turn.speaker,
        "observed_at": turn.observed_at.isoformat(),
        "content_digest": canonical_sha256(turn.content),
    }


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MemoryFormationError(f"FORMATION_SOURCE_{field}_INVALID")
    return value


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise MemoryFormationError("FORMATION_SOURCE_TIME_INVALID") from error
    else:
        raise MemoryFormationError("FORMATION_SOURCE_TIME_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryFormationError("FORMATION_SOURCE_TIME_MUST_BE_TIMEZONE_AWARE")
    return parsed


__all__ = [
    "MemoryFormationBuildResult",
    "MemoryFormationBundleService",
    "MemoryFormationError",
    "build_memory_formation_bundle",
]
