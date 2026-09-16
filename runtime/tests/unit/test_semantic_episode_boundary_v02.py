from __future__ import annotations

import ast
import inspect
from pathlib import Path

from milai.application.semantic_episode_boundary_v02 import (
    MemoryFormationBundleServiceV02,
    build_memory_formation_bundle_v02,
)


def test_v02_repairs_dialogue_continuity_without_merging_unrelated_assistant_turn() -> None:
    sources = [
        _source("piano", "user", "A technician adjusted my old piano yesterday.", 0),
        _source("question", "assistant", "Does the middle register sound stable now?", 1),
        _source("answer", "user", "The middle register sounds steady during scales.", 2),
        _source("shift", "assistant", "My grocery delivery arrives at six.", 3),
    ]

    result = MemoryFormationBundleServiceV02().build(sources)

    assert _groups(result) == [["piano", "question", "answer"], ["shift"]]
    assert [item.decision for item in result.boundary_evidence] == [
        "CONTINUE",
        "CONTINUE",
        "SPLIT",
    ]
    assert result.boundary_evidence[0].continuation_signals.dialogue_pair_continuity
    assert result.boundary_evidence[2].reason_code == "SUBJECT_OR_EVENT_CHANGE"


def test_v02_single_shared_name_does_not_merge_distinct_predicates() -> None:
    sources = [
        _source("garden", "user", "The copper watering can is beside my garden.", 0),
        _source("garden-reply", "assistant", "Is the copper can still by the garden?", 1),
        _source("software", "user", "The Copper release checklist needs review.", 2),
        _source("software-reply", "assistant", "That checklist is due Friday.", 3),
    ]

    result = build_memory_formation_bundle_v02(sources)

    assert _groups(result) == [
        ["garden", "garden-reply"],
        ["software", "software-reply"],
    ]
    boundary = result.boundary_evidence[1]
    assert boundary.decision == "SPLIT"
    assert boundary.split_signals.subject_or_event_change
    assert not boundary.continuation_signals.lexical_cohesion


def test_v02_is_query_independent_complete_and_byte_deterministic() -> None:
    sources = [
        _source("one", "user", "I still live in Wuxi.", 0),
        _source("two", "assistant", "Should I update your residence note?", 1),
        _source("three", "user", "Correction: I still live in Suzhou.", 2),
    ]

    first = build_memory_formation_bundle_v02(sources)
    second = build_memory_formation_bundle_v02(sources)

    assert first.bundle.model_dump_json() == second.bundle.model_dump_json()
    assert first.receipt.model_dump_json() == second.receipt.model_dump_json()
    assert [item.model_dump_json() for item in first.boundary_evidence] == [
        item.model_dump_json() for item in second.boundary_evidence
    ]
    assert [
        span.evidence_id
        for episode in first.bundle.episode_candidates
        for span in episode.source_spans
    ] == [
        "one",
        "two",
        "three",
    ]
    artifact_ids = {
        *[item.span.evidence_id for item in first.bundle.semantic_sidecar.entity_candidates],
        *[item.span.evidence_id for item in first.bundle.semantic_sidecar.event_candidates],
        *[item.span.evidence_id for item in first.bundle.state_change_sidecar.assertions],
        *[item.span.evidence_id for item in first.bundle.state_change_sidecar.transitions],
    }
    assert artifact_ids <= {"one", "three"}


def test_v02_runtime_policy_cannot_receive_eval_labels_or_call_external_layers() -> None:
    assert tuple(inspect.signature(build_memory_formation_bundle_v02).parameters) == (
        "source_records",
    )
    source_path = (
        Path(__file__).resolve().parents[2]
        / "src/milai/application/semantic_episode_boundary_v02.py"
    )
    source = source_path.read_text(encoding="utf-8")
    lowered = source.casefold()
    for forbidden_label in (
        "query_text",
        "conversation_id",
        "case_id",
        "gold",
        "expected_episodes",
        "required_support_evidence_ids",
        "distractor_evidence_ids",
    ):
        assert forbidden_label not in lowered
    imported_modules = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert imported_modules.isdisjoint(
        {
            "milai.persistence",
            "milai.application.retrieval",
            "milai.application.chat",
            "milai.adapters",
        }
    )


def _groups(result: object) -> list[list[str]]:
    bundle = result.bundle  # type: ignore[attr-defined]
    return [
        [span.evidence_id for span in episode.source_spans] for episode in bundle.episode_candidates
    ]


def _source(evidence_id: str, speaker: str, content: str, minute: int) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://md02/unit/{evidence_id}",
        "session_id": "session-1",
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": f"2026-08-30T09:{minute:02d}:00+08:00",
        "content": content,
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }
