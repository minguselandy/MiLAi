from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from milai.application.memory_formation import (
    MemoryFormationError,
    build_memory_formation_bundle,
)
from milai.domain.memory_formation import MemoryFormationBundleV01


def test_bundle_preserves_all_raw_turns_but_forms_only_user_sources() -> None:
    sources = [
        _source(
            "move",
            "user",
            "On August 12, 2026, I moved from Shanghai to Hangzhou for my new job.",
            "2026-08-12T09:00:00+08:00",
        ),
        _source(
            "assistant",
            "assistant",
            "I moved from Paris to Lyon last year and prefer window seats.",
            "2026-08-12T09:01:00+08:00",
        ),
        _source(
            "correction",
            "user",
            "Correction: I did not move to Hangzhou; I still live in Shanghai.",
            "2026-08-12T09:02:00+08:00",
        ),
    ]

    result = build_memory_formation_bundle(sources)

    assert result.bundle.source_evidence_ids == ["move", "assistant", "correction"]
    assert len(result.bundle.episode_candidates) == 1
    episode = result.bundle.episode_candidates[0]
    assert [item.text for item in episode.source_spans] == [source["content"] for source in sources]
    assert episode.participant_roles == ["user", "assistant", "user"]
    artifact_sources = {
        *[item.span.evidence_id for item in result.bundle.semantic_sidecar.entity_candidates],
        *[item.span.evidence_id for item in result.bundle.semantic_sidecar.event_candidates],
        *[item.span.evidence_id for item in result.bundle.state_change_sidecar.assertions],
        *[item.span.evidence_id for item in result.bundle.state_change_sidecar.transitions],
    }
    assert artifact_sources <= {"move", "correction"}
    assert "assistant" not in artifact_sources
    assert result.bundle.coverage_status == "COMPLETE"
    assert result.bundle.raw_fallback_required is True
    assert result.bundle.canonical_mutation is False
    assert result.receipt.provider_calls == 0
    assert result.receipt.reader_calls == 0
    assert result.receipt.retrieval_calls == 0
    assert result.receipt.database_calls == 0
    assert result.receipt.canonical_mutations == 0


def test_bundle_replay_is_byte_deterministic() -> None:
    sources = [
        _source(
            "preference",
            "user",
            "I prefer aisle seats to window seats when flying.",
            "2026-08-13T09:00:00+08:00",
        ),
        _source(
            "reply",
            "assistant",
            "That preference is noted.",
            "2026-08-13T09:01:00+08:00",
        ),
    ]

    first = build_memory_formation_bundle(sources)
    second = build_memory_formation_bundle(sources)

    assert first.bundle.model_dump_json() == second.bundle.model_dump_json()
    assert first.receipt.model_dump_json() == second.receipt.model_dump_json()


def test_episode_builder_distinguishes_general_boundary_reasons() -> None:
    sources = [
        _source(
            "topic-a",
            "user",
            "I prefer aisle seats when flying.",
            "2026-08-14T09:00:00+08:00",
            session_id="s1",
        ),
        _source(
            "topic-a-reply",
            "assistant",
            "That preference is noted.",
            "2026-08-14T09:01:00+08:00",
            session_id="s1",
        ),
        _source(
            "implicit-shift",
            "user",
            "My brother completed medical school yesterday.",
            "2026-08-14T09:02:00+08:00",
            session_id="s1",
        ),
        _source(
            "explicit-shift",
            "user",
            "Changing topic, I started a pottery class.",
            "2026-08-14T09:03:00+08:00",
            session_id="s1",
        ),
        _source(
            "session-shift",
            "user",
            "I adopted a cat named Miso.",
            "2026-08-14T09:04:00+08:00",
            session_id="s2",
        ),
        _source(
            "time-shift",
            "user",
            "My dentist appointment is on Friday.",
            "2026-08-15T09:04:00+08:00",
            session_id="s2",
        ),
    ]

    result = build_memory_formation_bundle(sources)

    assert [item.boundary_reason for item in result.bundle.episode_candidates] == [
        "CONVERSATION_START",
        "SEMANTIC_TOPIC_SHIFT",
        "EXPLICIT_TOPIC_SHIFT",
        "SESSION_CHANGE",
        "TIME_GAP",
    ]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("observed_at", "2026-08-12T09:00:00", "TIME_MUST_BE_TIMEZONE_AWARE"),
        ("revoked_at", "2026-08-12T10:00:00+08:00", "SOURCE_REVOKED"),
        ("retention_state", "PURGED", "RETENTION_BLOCKED"),
    ],
)
def test_bundle_fails_closed_on_unusable_raw_sources(field: str, value: str, reason: str) -> None:
    source = _source(
        "blocked",
        "user",
        "I prefer aisle seats.",
        "2026-08-12T09:00:00+08:00",
    )
    source[field] = value

    with pytest.raises(MemoryFormationError, match=reason):
        build_memory_formation_bundle([source])


def test_bundle_contract_rejects_digest_tampering() -> None:
    result = build_memory_formation_bundle(
        [
            _source(
                "one",
                "user",
                "I'm thinking of visiting Lisbon in October.",
                "2026-08-12T09:00:00+08:00",
            )
        ]
    )
    payload = result.bundle.model_dump(mode="json")
    payload["bundle_digest"] = "0" * 64

    with pytest.raises(ValidationError, match="bundle digest mismatch"):
        MemoryFormationBundleV01.model_validate(payload)


def test_builder_has_no_provider_reader_retrieval_or_database_dependency() -> None:
    source_path = Path(__file__).resolve().parents[2] / "src/milai/application/memory_formation.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    forbidden = {
        "milai.persistence",
        "milai.application.retrieval",
        "milai.application.chat",
        "milai.adapters.formation_extraction_v01",
    }
    assert imported_modules.isdisjoint(forbidden)


def _source(
    evidence_id: str,
    speaker: str,
    content: str,
    observed_at: str,
    *,
    session_id: str = "session-1",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://md01/{session_id}/{evidence_id}",
        "session_id": session_id,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": observed_at,
        "content": content,
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }
