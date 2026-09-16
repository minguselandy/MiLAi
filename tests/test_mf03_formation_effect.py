from __future__ import annotations

from pathlib import Path

from milai.application.formation_extraction import build_formation_sidecar
from milai.domain.formation_artifact import (
    FormationModelEventProposalV01,
    FormationTemporalRelationProposalV01,
)

from evals.mf01.labels import build_label_seal
from evals.mf03.formation_effect import (
    _score_sidecar,
    derive_residual_batches,
    load_formation_sources,
)

ROOT = Path(__file__).resolve().parents[1]


def test_deterministic_formation_localizes_only_two_residual_model_calls() -> None:
    seal = build_label_seal(ROOT)
    sources = load_formation_sources(ROOT, seal)
    deterministic = build_formation_sidecar(sources)

    batches = derive_residual_batches(sources, deterministic)

    assert len(sources) == 24
    assert len(batches) == 2
    assert {item.reason for item in batches} == {
        "NO_DETERMINISTIC_EVENT",
        "CROSS_EVIDENCE_TIME_UNRESOLVED",
    }
    baseline = _score_sidecar(seal, deterministic)
    assert baseline["ENTITY_IDENTITY"]["recall"] == 1.0
    assert baseline["EVENT_MENTION"]["covered"] == 23
    assert baseline["EVENT_IDENTITY"]["covered"] == 23
    assert baseline["EVENT_OCCURRENCE_TIME"]["recall"] == 1.0


def test_valid_residual_proposals_close_all_mf03_direct_obligations() -> None:
    seal = build_label_seal(ROOT)
    sources = load_formation_sources(ROOT, seal)
    correction = next(
        item for item in sources if item["case_id"] == "mf01-synthetic-correction-01"
    )
    charlotte = next(
        item
        for item in sources
        if item["source_ref"]
        == "2e6d26dc:s34:session-eb9648ee4cde14df8db879b9:t0"
    )
    max_source = next(
        item
        for item in sources
        if item["source_ref"]
        == "2e6d26dc:s23:session-dce024feb8aa4472bd06b87b:t0"
    )
    proposals = [
        FormationModelEventProposalV01(
            evidence_id=str(correction["evidence_id"]),
            grounded_quote="did not move to Hangzhou",
            event_type="move",
            primary_subject="self",
            context_participants=["Hangzhou"],
            event_identity_hint="negated-move-self-hangzhou",
            negated=True,
            confidence_feature=0.9,
        ),
        FormationModelEventProposalV01(
            evidence_id=str(charlotte["evidence_id"]),
            grounded_quote=(
                "our friends Mike and Emma welcomed their first baby, a girl named "
                "Charlotte, a few weeks after Rachel's baby shower"
            ),
            event_type="birth",
            primary_subject="Charlotte",
            context_participants=["Mike", "Emma"],
            event_identity_hint="birth-charlotte",
            temporal_relation=FormationTemporalRelationProposalV01(
                relation="AFTER",
                amount=3,
                unit="WEEK",
                anchor_evidence_id=str(max_source["evidence_id"]),
                anchor_quote="I attended her baby shower in February",
                normalized_from="a few weeks after Rachel's baby shower",
            ),
            confidence_feature=0.9,
        ),
    ]

    sidecar = build_formation_sidecar(
        sources,
        model_event_proposals=proposals,
        model_identity="test-model:revision-1",
        model_calls=2,
    )
    score = _score_sidecar(seal, sidecar)

    assert all(score[kind]["recall"] == 1.0 for kind in score)
    assert score["EVENT_IDENTITY"]["identity_collisions"] == 0
    assert sidecar.rejected_model_outputs == []
    assert sidecar.canonical_mutation is False
    charlotte_event = next(
        item for item in sidecar.event_candidates if item.primary_subject == "Charlotte"
    )
    assert charlotte_event.occurrence_time is not None
    assert charlotte_event.occurrence_time.start.isoformat() == "2023-02-22T00:00:00+00:00"
    assert charlotte_event.occurrence_time.end.isoformat() == "2023-03-22T00:00:00+00:00"
    assert charlotte_event.occurrence_time.anchor_provenance is not None
    assert charlotte_event.occurrence_time.anchor_provenance["amount"] == 3
