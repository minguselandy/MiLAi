from __future__ import annotations

from datetime import UTC, datetime

from milai.adapters.formation_extraction_v01 import _temporal_anchor_pairs
from milai.application.formation_extraction import build_formation_sidecar
from milai.domain.formation_artifact import (
    FormationModelEventProposalV01,
    FormationTemporalRelationProposalV01,
)


def test_deterministic_formation_preserves_self_twins_and_month_time() -> None:
    source = _source(
        "twins",
        "I bought gifts for my aunt's twins, Ava and Lily, who were born in April.",
    )

    sidecar = build_formation_sidecar([source])

    assert any(item.identity_key == "subject:self" for item in sidecar.entity_candidates)
    births = [item for item in sidecar.event_candidates if item.event_type == "birth"]
    assert {item.primary_subject for item in births} == {"ava", "lily"}
    assert all(item.occurrence_time is not None for item in births)
    assert all(item.occurrence_time.start.month == 4 for item in births if item.occurrence_time)
    assert sidecar.persisted is False
    assert sidecar.canonical is False
    assert sidecar.canonical_mutation is False


def test_model_proposal_adds_grounded_negated_event_without_authority() -> None:
    source = _source(
        "correction",
        "Correction: I did not move to Hangzhou; I still live in Shanghai.",
    )
    proposal = FormationModelEventProposalV01(
        evidence_id="correction",
        grounded_quote="did not move to Hangzhou",
        event_type="move",
        primary_subject="self",
        context_participants=["Hangzhou"],
        event_identity_hint="negated-move-self-hangzhou",
        negated=True,
        confidence_feature=0.9,
    )

    sidecar = build_formation_sidecar(
        [source],
        model_event_proposals=[proposal],
        model_identity="test-model:revision-1",
        model_calls=1,
    )

    event = next(item for item in sidecar.event_candidates if item.event_type == "move")
    assert event.span.text == "did not move to Hangzhou"
    assert event.negated is True
    assert event.canonical is False
    assert sidecar.model_calls == 1
    assert sidecar.rejected_model_outputs == []


def test_cross_evidence_relation_is_runtime_grounded_and_normalized() -> None:
    anchor = _source(
        "max",
        "My cousin Rachel had Max in March; I attended her baby shower in February.",
    )
    target = _source(
        "charlotte",
        "Mike and Emma welcomed Charlotte a few weeks after Rachel's baby shower.",
    )
    proposal = FormationModelEventProposalV01(
        evidence_id="charlotte",
        grounded_quote=(
            "Mike and Emma welcomed Charlotte a few weeks after Rachel's baby shower"
        ),
        event_type="birth",
        primary_subject="Charlotte",
        context_participants=["Mike", "Emma"],
        event_identity_hint="birth-charlotte",
        temporal_relation=FormationTemporalRelationProposalV01(
            relation="AFTER",
            amount=3,
            unit="WEEK",
            anchor_evidence_id="max",
            anchor_quote="I attended her baby shower in February",
            normalized_from="a few weeks after Rachel's baby shower",
        ),
        confidence_feature=0.9,
    )

    sidecar = build_formation_sidecar(
        [anchor, target],
        model_event_proposals=[proposal],
        model_identity="test-model:revision-1",
        model_calls=1,
    )

    event = next(
        item
        for item in sidecar.event_candidates
        if item.primary_subject and item.primary_subject.casefold() == "charlotte"
    )
    assert event.time_basis == "INFERRED_EVENT_TIME"
    assert event.occurrence_time is not None
    assert event.occurrence_time.start == datetime(2023, 2, 22, tzinfo=UTC)
    assert event.occurrence_time.end == datetime(2023, 3, 22, tzinfo=UTC)
    assert len(event.temporal_anchor_spans) == 1
    assert event.temporal_anchor_spans[0].evidence_id == "max"
    assert event.provenance["source_time_substitution"] is False


def test_multi_date_sentence_exposes_only_unambiguous_clause_anchors() -> None:
    anchor = _source(
        "max",
        "My cousin Rachel had Max in March, and I attended her baby shower in February, "
        "so I know how exciting it is.",
    )
    target = _source(
        "charlotte",
        "Mike and Emma welcomed Charlotte a few weeks after Rachel's baby shower.",
    )

    anchors = _temporal_anchor_pairs([anchor, target], ["charlotte"])

    assert ("max", "My cousin Rachel had Max in March") in anchors
    assert ("max", "I attended her baby shower in February") in anchors
    assert all("March" not in quote or "February" not in quote for _, quote in anchors)


def test_multi_date_anchor_proposal_is_rejected_fail_closed() -> None:
    anchor = _source(
        "max",
        "My cousin Rachel had Max in March, and I attended her baby shower in February.",
    )
    target = _source(
        "charlotte",
        "Mike and Emma welcomed Charlotte a few weeks after Rachel's baby shower.",
    )
    proposal = FormationModelEventProposalV01(
        evidence_id="charlotte",
        grounded_quote=(
            "Mike and Emma welcomed Charlotte a few weeks after Rachel's baby shower"
        ),
        event_type="birth",
        primary_subject="Charlotte",
        event_identity_hint="birth-charlotte",
        temporal_relation=FormationTemporalRelationProposalV01(
            relation="AFTER",
            amount=3,
            unit="WEEK",
            anchor_evidence_id="max",
            anchor_quote=anchor["content"],
            normalized_from="a few weeks after Rachel's baby shower",
        ),
    )

    sidecar = build_formation_sidecar(
        [anchor, target],
        model_event_proposals=[proposal],
        model_identity="test-model:revision-1",
        model_calls=1,
    )

    assert sidecar.rejected_model_outputs == [
        "proposal:0:TEMPORAL_ANCHOR_TIME_AMBIGUOUS"
    ]


def test_invalid_model_quote_is_rejected_without_losing_raw_formation() -> None:
    source = _source("one", "I attended a workshop on January 10th.")
    proposal = FormationModelEventProposalV01(
        evidence_id="one",
        grounded_quote="quote that is absent",
        event_type="workshop",
        primary_subject="self",
        event_identity_hint="workshop-self",
    )

    sidecar = build_formation_sidecar(
        [source],
        model_event_proposals=[proposal],
        model_identity="test-model:revision-1",
        model_calls=1,
    )

    assert sidecar.event_candidates
    assert sidecar.rejected_model_outputs == [
        "proposal:0:MODEL_EVENT_QUOTE_NOT_UNIQUE_EXACT"
    ]


def _source(evidence_id: str, content: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "subject_id": "fixture-user",
        "source_ref": f"memory://formation/{evidence_id}/turn/0",
        "session_id": evidence_id,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": datetime(2023, 5, 13, tzinfo=UTC).isoformat(),
        "content": content,
        "content_hash": f"hash-{evidence_id}",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }
