"""MD-02 query-independent BoundaryEvidenceV02 and Semantic Episode builder."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from milai.application.memory_formation import build_memory_formation_bundle
from milai.domain.formation_artifact import FormationSourceSpanV01
from milai.domain.memory_formation import (
    EpisodeBoundaryReason,
    MemoryFormationBundleV01,
    MemoryFormationReceiptV01,
    ParticipantRole,
    SemanticEpisodeCandidateV01,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_episode_shadow import (
    BoundaryContinuationSignalsV02,
    BoundaryEvidenceV02,
    BoundarySplitSignalsV02,
)

_PRODUCER = "deterministic-semantic-episode-boundary-v0.2"
_TIME_GAP = timedelta(hours=6)
_EXPLICIT_SHIFT = re.compile(
    r"(?:\bby\s+the\s+way\b|\bchanging\s+topics?\b|\bchange\s+of\s+topic\b|"
    r"\bon\s+another\s+topic\b|\bseparately\b|换个话题|另外一件事|说到别的)",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
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
        "did",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "my",
        "now",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "with",
        "you",
    }
)


@dataclass(frozen=True, slots=True)
class MemoryFormationBuildResultV02:
    bundle: MemoryFormationBundleV01
    receipt: MemoryFormationReceiptV01
    boundary_evidence: tuple[BoundaryEvidenceV02, ...]


@dataclass(frozen=True, slots=True)
class _Turn:
    evidence_id: str
    source_ref: str
    session_id: str
    speaker: ParticipantRole
    observed_at: datetime
    content: str


def build_memory_formation_bundle_v02(
    source_records: Sequence[Mapping[str, Any]],
) -> MemoryFormationBuildResultV02:
    """Build V02 episodes without changing the frozen MF-02 V01 implementation."""

    frozen = build_memory_formation_bundle(source_records)
    turns = tuple(_turn(source) for source in source_records)
    feature_map = _typed_features(frozen.bundle)
    episodes, boundaries = _build_episodes(turns, feature_map)
    provisional = MemoryFormationBundleV01.model_construct(
        bundle_digest="0" * 64,
        source_snapshot_digest=frozen.bundle.source_snapshot_digest,
        source_evidence_ids=list(frozen.bundle.source_evidence_ids),
        source_watermark=frozen.bundle.source_watermark,
        episode_candidates=episodes,
        semantic_sidecar=frozen.bundle.semantic_sidecar,
        state_change_sidecar=frozen.bundle.state_change_sidecar,
        producer_identity=_PRODUCER,
    )
    bundle_material = provisional.model_dump(mode="json", exclude={"bundle_digest"})
    bundle = MemoryFormationBundleV01(
        bundle_digest=canonical_sha256(bundle_material),
        **bundle_material,
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
    return MemoryFormationBuildResultV02(
        bundle=bundle,
        receipt=receipt,
        boundary_evidence=tuple(boundaries),
    )


class MemoryFormationBundleServiceV02:
    """Pre-query application service for a complete V02 Formation snapshot."""

    def build(
        self,
        source_records: Sequence[Mapping[str, Any]],
    ) -> MemoryFormationBuildResultV02:
        return build_memory_formation_bundle_v02(source_records)


def _build_episodes(
    turns: Sequence[_Turn],
    feature_map: Mapping[str, Mapping[str, frozenset[str]]],
) -> tuple[list[SemanticEpisodeCandidateV01], list[BoundaryEvidenceV02]]:
    groups: list[tuple[EpisodeBoundaryReason, list[_Turn]]] = []
    boundaries: list[BoundaryEvidenceV02] = []
    for turn in turns:
        if not groups:
            groups.append(("CONVERSATION_START", [turn]))
            continue
        current = groups[-1][1]
        boundary = _boundary_evidence(current, turn, feature_map)
        boundaries.append(boundary)
        if boundary.decision == "CONTINUE":
            current.append(turn)
        else:
            groups.append((_episode_reason(boundary.reason_code), [turn]))
    return (
        [_episode(reason, group) for reason, group in groups],
        boundaries,
    )


def _boundary_evidence(
    current: Sequence[_Turn],
    turn: _Turn,
    feature_map: Mapping[str, Mapping[str, frozenset[str]]],
) -> BoundaryEvidenceV02:
    previous = current[-1]
    prior_user = [item for item in current if item.speaker == "user"]
    prior_terms = {term for item in prior_user for term in _terms(item.content)}
    current_terms = set(_terms(turn.content))
    previous_terms = set(_terms(previous.content))
    session_change = turn.session_id != previous.session_id
    explicit_shift = turn.speaker == "user" and _EXPLICIT_SHIFT.search(turn.content) is not None
    correction = turn.speaker == "user" and _CORRECTION.search(turn.content) is not None
    question_marks = ("?", "\uff1f")
    assistant_question = previous.speaker == "assistant" and previous.content.rstrip().endswith(
        question_marks
    )
    assistant_follow_up_question = turn.speaker == "assistant" and turn.content.rstrip().endswith(
        question_marks
    )
    question_overlap = len(previous_terms & current_terms)
    dialogue = turn.speaker == "user" and assistant_question and question_overlap >= 2
    assistant_reply = turn.speaker == "assistant" and (
        assistant_follow_up_question
        or bool(previous_terms & current_terms)
        or turn.content.casefold().startswith(("that ", "this ", "its "))
    )
    entity = _feature_continuity(current, turn, feature_map, "entities")
    event = _feature_continuity(current, turn, feature_map, "events")
    state = _feature_continuity(current, turn, feature_map, "states")
    lexical = _lexical_cohesion(prior_terms, current_terms)
    continuation = BoundaryContinuationSignalsV02(
        dialogue_pair_continuity=dialogue or assistant_reply,
        correction_or_update_relation=correction,
        entity_continuity=entity,
        event_or_state_continuity=event or state,
        lexical_cohesion=lexical,
    )
    incompatible = _incompatible_state_context(current, turn, feature_map)
    any_continuation = any(continuation.model_dump().values())
    gap_without_continuity = (
        turn.observed_at - previous.observed_at >= _TIME_GAP and not any_continuation
    )
    subject_change = not any_continuation and not session_change and not explicit_shift
    split = BoundarySplitSignalsV02(
        session_change=session_change,
        explicit_topic_shift=explicit_shift,
        subject_or_event_change=subject_change,
        incompatible_predicate_context=incompatible,
        time_gap_without_continuity=gap_without_continuity,
    )
    if session_change:
        decision, reason = "SPLIT", "SESSION_CHANGE"
    elif explicit_shift:
        decision, reason = "SPLIT", "EXPLICIT_TOPIC_SHIFT"
    elif correction:
        decision, reason = "CONTINUE", "CORRECTION_OR_UPDATE_CONTINUATION"
    elif any_continuation:
        if dialogue or assistant_reply:
            reason = "DIALOGUE_PAIR_CONTINUATION"
        elif event or state:
            reason = "EVENT_OR_STATE_CONTINUATION"
        elif entity:
            reason = "ENTITY_CONTINUATION"
        else:
            reason = "LEXICAL_COHESION_CONTINUATION"
        decision = "CONTINUE"
    elif gap_without_continuity:
        decision, reason = "SPLIT", "TIME_GAP_WITHOUT_CONTINUITY"
    elif incompatible:
        decision, reason = "SPLIT", "INCOMPATIBLE_PREDICATE_CONTEXT"
    else:
        decision, reason = "SPLIT", "SUBJECT_OR_EVENT_CHANGE"
    provisional = BoundaryEvidenceV02.model_construct(
        boundary_evidence_digest="0" * 64,
        previous_episode_source_ids=[item.evidence_id for item in current],
        current_source_id=turn.evidence_id,
        continuation_signals=continuation,
        split_signals=split,
        decision=decision,
        reason_code=reason,
        producer_identity=_PRODUCER,
    )
    material = provisional.model_dump(mode="json", exclude={"boundary_evidence_digest"})
    return BoundaryEvidenceV02(
        boundary_evidence_digest=canonical_sha256(material),
        **material,
    )


def _typed_features(
    bundle: MemoryFormationBundleV01,
) -> dict[str, dict[str, frozenset[str]]]:
    source_ids = bundle.source_evidence_ids
    mutable: dict[str, dict[str, set[str]]] = {
        evidence_id: {"entities": set(), "events": set(), "states": set()}
        for evidence_id in source_ids
    }
    for entity in bundle.semantic_sidecar.entity_candidates:
        if entity.identity_key != "subject:self":
            mutable[entity.span.evidence_id]["entities"].add(entity.identity_key)
    for event in bundle.semantic_sidecar.event_candidates:
        if event.primary_subject:
            mutable[event.span.evidence_id]["events"].add(
                f"{event.event_type}:{event.primary_subject}"
            )
    for assertion in bundle.state_change_sidecar.assertions:
        mutable[assertion.span.evidence_id]["states"].add(assertion.predicate)
    return {
        evidence_id: {name: frozenset(values) for name, values in feature_sets.items()}
        for evidence_id, feature_sets in mutable.items()
    }


def _feature_continuity(
    current: Sequence[_Turn],
    turn: _Turn,
    feature_map: Mapping[str, Mapping[str, frozenset[str]]],
    name: str,
) -> bool:
    current_values = feature_map.get(turn.evidence_id, {}).get(name, frozenset())
    prior_values = {
        value
        for item in current
        for value in feature_map.get(item.evidence_id, {}).get(name, frozenset())
    }
    return bool(current_values & prior_values)


def _incompatible_state_context(
    current: Sequence[_Turn],
    turn: _Turn,
    feature_map: Mapping[str, Mapping[str, frozenset[str]]],
) -> bool:
    current_states = feature_map.get(turn.evidence_id, {}).get("states", frozenset())
    prior_states = {
        value
        for item in current
        for value in feature_map.get(item.evidence_id, {}).get("states", frozenset())
    }
    return bool(current_states and prior_states and not current_states & prior_states)


def _lexical_cohesion(prior_terms: set[str], current_terms: set[str]) -> bool:
    if not prior_terms or not current_terms:
        return False
    common = prior_terms & current_terms
    return len(common) >= 2 or len(common) / len(prior_terms | current_terms) >= 0.25


def _episode(
    reason: EpisodeBoundaryReason,
    turns: Sequence[_Turn],
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
    terms = sorted({term for item in turns for term in _terms(item.content)})[:64]
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


def _episode_reason(reason: str) -> EpisodeBoundaryReason:
    return cast(
        EpisodeBoundaryReason,
        reason
        if reason
        in {
            "SESSION_CHANGE",
            "EXPLICIT_TOPIC_SHIFT",
        }
        else "TIME_GAP"
        if reason == "TIME_GAP_WITHOUT_CONTINUITY"
        else "SEMANTIC_TOPIC_SHIFT",
    )


def _turn(source: Mapping[str, Any]) -> _Turn:
    observed = datetime.fromisoformat(str(source["observed_at"]).replace("Z", "+00:00"))
    speaker = str(source["speaker"]).casefold()
    return _Turn(
        evidence_id=str(source["evidence_id"]),
        source_ref=str(source["source_ref"]),
        session_id=str(source["session_id"]),
        speaker=cast(ParticipantRole, speaker),
        observed_at=observed,
        content=str(source["content"]),
    )


def _terms(text: str) -> tuple[str, ...]:
    return tuple(
        token for token in _WORD.findall(text.casefold()) if token not in _STOP and len(token) > 1
    )


__all__ = [
    "MemoryFormationBuildResultV02",
    "MemoryFormationBundleServiceV02",
    "build_memory_formation_bundle_v02",
]
