from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from milai.application.retrieval import _temporal_rerank


def _candidate(text: str, observed_at: str) -> dict[str, object]:
    return {
        "claim_version_id": str(uuid4()),
        "payload": {"memory_text": text},
        "valid_time_from": observed_at,
    }


def test_temporal_rerank_surfaces_related_state_before_anchor() -> None:
    unrelated = _candidate(
        "I bought a vase as a present and discussed markets and anniversaries.",
        "2023-05-21T13:25:00+00:00",
    )
    anchor = _candidate(
        "I got an Air Fryer yesterday for healthy meals, recipes, cooking, and fries.",
        "2023-05-21T22:54:00+00:00",
    )
    previous = _candidate(
        "I use my new Instant Pot for healthy meals, recipes, cooking, soups, and stews.",
        "2023-05-21T05:48:00+00:00",
    )

    ranked = _temporal_rerank(
        [unrelated, anchor, previous],
        "What new kitchen gadget did I invest in before getting the Air Fryer?",
    )

    assert ranked[:2] == [previous, anchor]


def test_temporal_rerank_is_inert_without_explicit_relation_or_valid_time() -> None:
    first = _candidate("Air Fryer cooking", "2023-05-21T22:54:00+00:00")
    second = _candidate("Instant Pot cooking", "2023-05-21T05:48:00+00:00")
    candidates = [first, second]

    assert _temporal_rerank(candidates, "What kitchen gadget do I use?") == candidates
    first["valid_time_from"] = None
    assert _temporal_rerank(candidates, "What did I use before the Air Fryer?") == candidates


def test_temporal_rerank_uses_latest_matching_alternative() -> None:
    old_bus = _candidate("user: I got back from a bus ride today.", "2023-02-27T06:17:00+00:00")
    unrelated = _candidate("user: I bought a new desk today.", "2023-04-01T06:17:00+00:00")
    new_train = _candidate("user: I took a train ride today.", "2023-03-03T19:17:00+00:00")

    ranked = _temporal_rerank(
        [old_bus, unrelated, new_train],
        "Which mode of transport did I use most recently, a bus or a train?",
        reference_time=datetime.fromisoformat("2023-05-02T08:12:00+00:00"),
    )

    assert ranked[:2] == [new_train, old_bus]


def test_temporal_rerank_uses_relative_query_time() -> None:
    recent_bike = _candidate(
        'user: I completed the "24-Hour Bike Ride" charity event.',
        "2023-04-10T15:44:00+00:00",
    )
    walk = _candidate(
        'user: I completed the "Walk for Hunger" charity event.',
        "2023-03-19T15:44:00+00:00",
    )
    unrelated = _candidate("user: I attended a work event.", "2023-03-19T15:44:00+00:00")

    ranked = _temporal_rerank(
        [recent_bike, unrelated, walk],
        "What charity event did I participate in a month ago?",
        reference_time=datetime.fromisoformat("2023-04-18T18:34:00+00:00"),
    )

    assert ranked[0] == walk


def test_relative_time_rerank_lets_date_cover_weak_generic_subject_terms() -> None:
    generic_match = _candidate(
        "user: I ordered a modern lamp about a week ago.",
        "2023-03-15T17:07:00+00:00",
    )
    concrete_event = _candidate(
        "user: Today I got an espresso machine.",
        "2023-03-15T11:56:00+00:00",
    )
    unrelated = _candidate(
        "user: I discussed lighting for the living room.",
        "2023-03-07T16:21:00+00:00",
    )

    ranked = _temporal_rerank(
        [generic_match, unrelated, concrete_event],
        "Which espresso machine did I get 10 days ago?",
        reference_time=datetime.fromisoformat("2023-03-25T18:26:00+00:00"),
    )

    assert ranked[0] == concrete_event
