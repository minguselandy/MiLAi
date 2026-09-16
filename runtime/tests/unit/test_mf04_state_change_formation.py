from __future__ import annotations

from milai.application.state_change_formation import build_state_change_sidecar


def _source(evidence_id: str, content: str, observed_at: str) -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://{evidence_id}",
        "content": content,
        "observed_at": observed_at,
    }


def test_explicit_states_and_changes_form_without_canonical_mutation() -> None:
    sidecar = build_state_change_sidecar(
        [
            _source(
                "move",
                "On August 12, 2026, I moved from Shanghai to Hangzhou for my new job.",
                "2026-08-13T08:00:00+08:00",
            ),
            _source(
                "correction",
                "Correction: I did not move to Hangzhou; I still live in Shanghai.",
                "2026-08-14T09:00:00+08:00",
            ),
            _source(
                "preference",
                "I prefer aisle seats to window seats when flying.",
                "2026-08-15T10:00:00+08:00",
            ),
            _source(
                "temporary",
                "Until September 5, 2026, I'm staying in Suzhou for a conference.",
                "2026-08-16T11:00:00+08:00",
            ),
        ]
    )

    assert len(sidecar.assertions) == 4
    assert {item.predicate for item in sidecar.assertions} == {
        "residence",
        "seat_preference",
        "temporary_location",
    }
    assert {item.relation for item in sidecar.transitions} == {
        "UPDATES",
        "CORRECTS",
        "TEMPORARILY_CONSTRAINS",
    }
    temporary = next(
        item for item in sidecar.assertions if item.predicate == "temporary_location"
    )
    assert temporary.valid_time is not None
    assert temporary.valid_time.end is not None
    assert temporary.valid_time.end.isoformat() == "2026-09-05T23:59:59.999999+08:00"
    assert sidecar.canonical is False
    assert sidecar.canonical_mutation is False


def test_query_local_interest_and_intent_are_not_promoted() -> None:
    sidecar = build_state_change_sidecar(
        [
            _source(
                "interest",
                "I realized how much I love the city's music scene.",
                "2026-08-15T10:00:00+00:00",
            ),
            _source(
                "intent",
                "I'm thinking of going back to Denver for another concert",
                "2026-08-15T10:00:00+00:00",
            ),
        ]
    )

    assert {item.predicate for item in sidecar.assertions} == {
        "music_interest",
        "current_intent",
    }
    assert all(
        item.promotion_disposition == "QUERY_LOCAL_ONLY"
        for item in sidecar.assertions
    )
