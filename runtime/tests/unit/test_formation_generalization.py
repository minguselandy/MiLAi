from __future__ import annotations

from milai.application.formation_generalization import build_generalized_formation


def _source(
    evidence_id: str,
    content: str,
    *,
    scope: str = "scope:test",
    observed_at: str = "2026-03-20T09:00:00+00:00",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://test/session-0:{evidence_id}",
        "scope_id": scope,
        "speaker": "user",
        "content": content,
        "observed_at": observed_at,
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "access_decision": "ALLOWED",
        "revoked_at": None,
    }


def test_entities_are_scope_bound_and_unambiguous_surname_aliases_link() -> None:
    first = build_generalized_formation(
        [
            _source(
                "a", "My colleague Alex Morgan and I attended the Atlas workshop on March 2, 2026."
            ),
            _source("b", "Morgan and I attended that same Atlas workshop on March 2, 2026."),
        ]
    )
    second = build_generalized_formation(
        [_source("c", "I currently live in Oslo.", scope="scope:other")]
    )

    named = [
        item
        for item in first.formation.entity_candidates
        if item.mention_type in {"NAMED_PERSON", "UNAMBIGUOUS_SURNAME_ALIAS"}
    ]
    assert len(named) == 2
    assert named[0].identity_key == named[1].identity_key
    first_self = next(item for item in first.formation.entity_candidates if item.span.text == "I")
    second_self = next(item for item in second.formation.entity_candidates if item.span.text == "I")
    assert first_self.identity_key != second_self.identity_key


def test_event_identity_time_interval_and_ambiguity_are_separate() -> None:
    bundle = build_generalized_formation(
        [
            _source("anchor", "I attended the Orion workshop on March 4, 2026."),
            _source(
                "later",
                "Two days after the Orion workshop, I visited the Orion museum. "
                "For clarity, I attended that same Orion workshop on March 4, 2026. "
                "I also worked at the Orion expo from June 3, 2026 through June 8, 2026.",
            ),
            _source(
                "unknown", "I may attend the gala sometime next spring, but its date is unresolved."
            ),
        ]
    )

    events = bundle.formation.event_candidates
    workshop = [item for item in events if "orion-workshop" in item.event_identity_key]
    assert len(workshop) == 2
    assert workshop[0].event_identity_key == workshop[1].event_identity_key
    visit = next(item for item in events if item.event_type == "visit")
    assert visit.time_basis == "INFERRED_EVENT_TIME"
    assert visit.occurrence_time is not None
    assert visit.occurrence_time.start.date().isoformat() == "2026-03-06"
    interval = next(item for item in events if item.event_type == "work")
    assert interval.occurrence_time is not None
    assert interval.occurrence_time.start.date().isoformat() == "2026-06-03"
    assert interval.occurrence_time.end.date().isoformat() == "2026-06-08"
    unknown = next(item for item in events if "gala" in item.event_identity_key)
    assert unknown.time_basis == "UNRESOLVED"
    assert unknown.occurrence_time is None


def test_current_state_changes_cover_each_governed_relation_without_promotion() -> None:
    bundle = build_generalized_formation(
        [
            _source("establish", "I live in Riga."),
            _source("update", "On January 10, 2026, I moved from Riga to Vilnius."),
            _source("correct", "Correction: I do not live in Vilnius; I live in Riga."),
            _source("allergy", "I am allergic to peanuts."),
            _source("revoke", "That peanuts allergy was incorrect; I revoke it."),
            _source("temporary", "Until October 10, 2026, I am staying in Bath."),
        ]
    )

    assert {item.relation for item in bundle.state_changes.transitions} == {
        "ESTABLISHES",
        "UPDATES",
        "CORRECTS",
        "REVOKES",
        "TEMPORARILY_CONSTRAINS",
    }
    assert bundle.formation.model_calls == 0
    assert bundle.formation.canonical_mutation is False
    assert bundle.state_changes.canonical_mutation is False


def test_assistant_and_revoked_sources_are_not_formed() -> None:
    assistant = _source("assistant", "I attended the Atlas workshop on March 2, 2026.")
    assistant["speaker"] = "assistant"
    revoked = _source("revoked", "I live in Oslo.")
    revoked["revoked_at"] = "2026-03-21T09:00:00+00:00"

    bundle = build_generalized_formation([assistant, revoked])

    assert bundle.formation.entity_candidates == []
    assert bundle.formation.event_candidates == []
    assert bundle.state_changes.assertions == []
    assert bundle.state_changes.transitions == []
