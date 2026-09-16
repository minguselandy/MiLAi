from __future__ import annotations

from datetime import UTC, datetime

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.formation_identity import (
    select_event_identity_representatives,
)
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    RequirementCardinalityV02,
    RequirementSemanticRolesV02,
)


def test_repeated_singleton_event_keeps_earliest_source_representative() -> None:
    requirement = EvidenceRequirementV02(
        slot_id="WORKSHOP_EVENT",
        interpretation_kind="EVENT",
        entity_constraints=[
            "attend",
            "workshop",
            "effective",
            "communication",
            "workplace",
        ],
        predicate_constraints=["event_time"],
        semantic_roles=RequirementSemanticRolesV02(actor="USER"),
        value_type="DATETIME",
        cardinality=RequirementCardinalityV02(
            minimum=1,
            maximum=1,
            distinct=False,
        ),
    )
    records = [
        _source(
            "repeat",
            4,
            'I attended the workshop "Effective Communication in the Workplace" '
            "on January 10th and reflected on it again.",
        ),
        _source(
            "origin",
            0,
            'I attended the workshop "Effective Communication in the Workplace" '
            "on January 10th.",
        ),
    ]
    spans = project_evidence_spans(records)
    interpretations = interpret_evidence_spans(spans, resolve_local_anchors=True)
    bindings = bind_requirements(
        [requirement],
        interpretations,
        spans,
        type_compatible_only=True,
        compatibility_profile="dg22-v0.2",
    )

    selected, sidecar = select_event_identity_representatives(
        [requirement],
        bindings,
        interpretations,
        spans,
    )

    matched_interpretations = {
        item.interpretation_id for item in selected if item.status == "MATCH"
    }
    interpretation_by_id = {
        item.interpretation_id: item for item in interpretations
    }
    span_by_id = {item.span_id: item for item in spans}
    matched_evidence = {
        span_by_id[interpretation_by_id[item].span_id].source_evidence_id
        for item in matched_interpretations
    }
    assert matched_evidence == {"origin"}
    assert sidecar.duplicate_evidence_count == 1
    assert len(sidecar.clusters) == 1
    assert sidecar.clusters[0].source_evidence_ids == ["origin", "repeat"]
    assert sidecar.clusters[0].representative_evidence_id == "origin"
    assert sidecar.persisted is False
    assert sidecar.canonical is False
    assert sidecar.canonical_mutation is False


def _source(evidence_id: str, turn: int, content: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "subject_id": "fixture-user",
        "source_ref": f"memory://session/workshop/turn/{turn}",
        "session_id": "workshop",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": datetime(2026, 1, 11, tzinfo=UTC).isoformat(),
        "content": content,
        "content_hash": f"hash-{evidence_id}",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }
