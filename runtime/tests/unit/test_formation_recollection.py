from __future__ import annotations

from milai.application.formation_generalization import build_generalized_formation
from milai.application.formation_recollection import recollect_with_formation


def test_current_state_consumes_all_grounded_user_assertions() -> None:
    sources = [
        _source("e0", "s0", "I currently live in Lisbon."),
        _source("e1", "s1", "You definitely live in Oslo.", speaker="assistant"),
        _source("e2", "s2", "I still call Lisbon home."),
    ]
    bundle = build_generalized_formation(sources)

    result = recollect_with_formation(
        query="Where do I currently live?",
        formation=bundle.formation,
        state_changes=bundle.state_changes,
        source_records=sources,
        raw_candidate_evidence_ids=["e1"],
        representation="FORMED_PLUS_RAW",
    )

    assert result.accepted_evidence_ids == ("e0", "e2")
    assert result.raw_fallback_evidence_ids == ()
    assert result.complete is True


def test_event_identity_and_time_preserve_both_source_turns() -> None:
    sources = [
        _source(
            "e0",
            "s0",
            "My colleague Alex Morgan and I attended the Atlas workshop on February 3, 2026.",
        ),
        _source(
            "e2",
            "s2",
            "Morgan and I attended that same Atlas workshop on February 3, 2026; "
            "my dentist Alex Rivera attended a different Atlas workshop on February 18, 2026.",
        ),
    ]
    bundle = build_generalized_formation(sources)

    result = recollect_with_formation(
        query="Did my colleague and dentist attend the same Atlas workshop?",
        formation=bundle.formation,
        state_changes=bundle.state_changes,
        source_records=sources,
        raw_candidate_evidence_ids=[],
        representation="FORMED_ONLY",
    )

    assert result.accepted_evidence_ids == ("e0", "e2")
    assert result.covered_facets == ("EVENT_IDENTITY",)
    assert result.complete is True


def test_preference_and_short_lived_state_are_separate_facets() -> None:
    sources = [
        _source("e0", "s0", "I prefer aisle seats over window seats."),
        _source(
            "e2",
            "s2",
            "Until October 10, 2026, I am staying in Bath while finishing a course.",
        ),
    ]
    bundle = build_generalized_formation(sources)

    result = recollect_with_formation(
        query="What preference and short-lived constraint should be recalled?",
        formation=bundle.formation,
        state_changes=bundle.state_changes,
        source_records=sources,
        raw_candidate_evidence_ids=[],
        representation="FORMED_PLUS_RAW",
    )

    assert result.accepted_evidence_ids == ("e0", "e2")
    assert result.covered_facets == ("PREFERENCE", "SHORT_LIVED_STATE")
    assert result.complete is True


def test_raw_fallback_is_user_readable_and_formed_only_never_uses_it() -> None:
    sources = [
        _source("e0", "s0", "A rare unstructured detail."),
        _source("e1", "s1", "Assistant echo.", speaker="assistant"),
    ]
    bundle = build_generalized_formation(sources)

    with_fallback = recollect_with_formation(
        query="What rare detail did I provide?",
        formation=bundle.formation,
        state_changes=bundle.state_changes,
        source_records=sources,
        raw_candidate_evidence_ids=["e0", "e1"],
        representation="FORMED_PLUS_RAW",
    )
    formed_only = recollect_with_formation(
        query="What rare detail did I provide?",
        formation=bundle.formation,
        state_changes=bundle.state_changes,
        source_records=sources,
        raw_candidate_evidence_ids=["e0", "e1"],
        representation="FORMED_ONLY",
    )

    assert with_fallback.accepted_evidence_ids == ("e0",)
    assert formed_only.accepted_evidence_ids == ()


def test_revoked_source_cannot_be_reintroduced_by_formed_or_raw_path() -> None:
    source = _source("e0", "s0", "I live in Lisbon.")
    bundle = build_generalized_formation([source])
    revoked = {**source, "revoked_at": "2026-08-30T00:00:00+00:00"}

    result = recollect_with_formation(
        query="Where do I currently live?",
        formation=bundle.formation,
        state_changes=bundle.state_changes,
        source_records=[revoked],
        raw_candidate_evidence_ids=["e0"],
        representation="FORMED_PLUS_RAW",
    )

    assert result.accepted_evidence_ids == ()
    assert result.complete is False


def test_generic_query_does_not_match_unrelated_state_or_event() -> None:
    sources = [
        _source("e0", "s0", "I live in Lisbon."),
        _source("e2", "s2", "I attended the Atlas gala on August 2, 2026."),
    ]
    bundle = build_generalized_formation(sources)

    result = recollect_with_formation(
        query="What is my passport number?",
        formation=bundle.formation,
        state_changes=bundle.state_changes,
        source_records=sources,
        raw_candidate_evidence_ids=[],
        representation="FORMED_PLUS_RAW",
    )

    assert result.accepted_evidence_ids == ()
    assert result.covered_facets == ()
    assert result.complete is False


def _source(
    evidence_id: str,
    source_ref: str,
    content: str,
    *,
    speaker: str = "user",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_ref": source_ref,
        "scope_id": "scope-a",
        "content": content,
        "speaker": speaker,
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
        "access_decision": "ALLOWED",
        "observed_at": "2026-08-16T11:00:00+08:00",
    }
