import pytest

from milai.application.formation_engine import (
    FORMATION_ENGINE_IDENTITY,
    FormationEngine,
)
from milai.application.memory_formation import MemoryFormationError


def test_product_and_eval_share_one_formation_builder_contract() -> None:
    sources = [
        {
            "evidence_id": "u1",
            "source_ref": "memory://session/s1/turn/0",
            "session_id": "s1",
            "scope_id": "milai",
            "speaker": "user",
            "content": "I live in Riga.",
            "observed_at": "2026-03-20T09:00:00+00:00",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "access_decision": "ALLOWED",
            "revoked_at": None,
        },
        {
            "evidence_id": "a1",
            "source_ref": "memory://session/s1/turn/1",
            "session_id": "s1",
            "scope_id": "milai",
            "speaker": "assistant",
            "content": "Thanks, I will remember Riga.",
            "observed_at": "2026-03-20T09:01:00+00:00",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "access_decision": "ALLOWED",
            "revoked_at": None,
        },
    ]

    result = FormationEngine().build(sources)

    assert result.builder_identity == FORMATION_ENGINE_IDENTITY
    assert result.canonical_mutation is False
    assert result.episode.bundle.source_evidence_ids == ["u1", "a1"]
    assert all(
        item.span.evidence_id != "a1"
        for item in result.generalized.state_changes.assertions
    )


def test_unified_formation_engine_fails_closed_on_revoked_sources() -> None:
    source = {
        "evidence_id": "revoked-1",
        "source_ref": "memory://session/s1/turn/0",
        "session_id": "s1",
        "scope_id": "milai",
        "speaker": "user",
        "content": "This source must not survive revocation.",
        "observed_at": "2026-03-20T09:00:00+00:00",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "access_decision": "ALLOWED",
        "revoked_at": "2026-03-21T09:00:00+00:00",
    }

    with pytest.raises(MemoryFormationError, match="FORMATION_SOURCE_SNAPSHOT_EMPTY"):
        FormationEngine().build([source])
