import re
from datetime import UTC, datetime

import pytest

from milai.application import evidence_semantics
from milai.application.evidence_semantics import (
    direct_event_time_expression_count,
    interpret_evidence_spans,
    project_evidence_spans,
    resolve_direct_event_time,
)


def _source(identity: str, text: str, observed: str) -> dict[str, object]:
    return {
        "evidence_id": identity,
        "subject_id": identity,
        "source_ref": f"memory://session/{identity}/turn/0",
        "source_context": {"session_id": identity, "turn_id": f"{identity}:turn:0"},
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "content": text,
        "observed_at": observed,
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
    }


@pytest.mark.parametrize(
    ("phrase", "expected_start", "expression_count"),
    [
        ("2026-09-01 and 2026-09-02", "2026-09-01T00:00:00+00:00", 2),
        ("March 4, 2026 and 2026-09-01", "2026-09-01T00:00:00+00:00", 2),
        ("03/04/26", "2026-03-04T00:00:00+00:00", 1),
        ("March 4", "2026-03-04T00:00:00+00:00", 1),
        ("two days ago", "2026-09-04T12:00:00+00:00", 1),
        ("yesterday", "2026-09-05T00:00:00+00:00", 1),
        ("last weekend", "2026-08-29T00:00:00+00:00", 1),
        ("last Monday", "2026-08-31T00:00:00+00:00", 1),
        ("in March 2026", "2026-03-01T00:00:00+00:00", 1),
        ("until 2026-09-07", "2026-09-06T12:00:00+00:00", 1),
        ("2026-02-30 and 2026-09-01", None, 2),
        ("without a stated date", None, 0),
    ],
)
def test_combined_interpretation_keeps_date_precedence_and_quantity_exclusion(
    phrase: str, expected_start: str | None, expression_count: int
) -> None:
    observed = datetime(2026, 9, 6, 12, tzinfo=UTC)
    text = f"We completed 7 repairs {phrase}"
    spans = project_evidence_spans(
        [_source("repairs", text, observed.isoformat())]
    )
    assert len(spans) == 1
    interpretations = interpret_evidence_spans(spans)
    events = [item for item in interpretations if item.kind == "EVENT"]
    assert len(events) == 1
    event = events[0]
    assert [item.value for item in interpretations if item.kind == "QUANTITY"] == [7]
    assert direct_event_time_expression_count(text) == expression_count
    # Standalone formation parsing still searches directly. Span interpretation
    # reuses its range scan, including pattern priority and an invalid first date.
    direct = resolve_direct_event_time(text, observed)
    if expected_start is None:
        assert direct is None
        assert event.event_time is None
    else:
        assert direct is not None
        assert event.event_time is not None
        assert event.event_time.start.isoformat() == expected_start
        assert event.event_time.start == direct[0].start
        assert event.event_time.end == direct[0].end
        assert event.event_time.normalized_from == direct[0].normalized_from
        assert event.time_basis == direct[1]


def test_repeated_text_keeps_each_source_time_anchor() -> None:
    spans = project_evidence_spans(
        [
            _source(
                f"source-{day}",
                "We completed 7 repairs yesterday",
                f"2026-09-{day:02d}T12:00:00+00:00",
            )
            for day in (5, 6)
        ]
    )
    events = [item for item in interpret_evidence_spans(spans) if item.kind == "EVENT"]
    assert sorted(item.event_time.start.day for item in events if item.event_time) == [4, 5]


@pytest.mark.parametrize(
    "text",
    [
        "x" * 8192,
        "Preserve the original sources and unfinished work. " * 160,
        "prefix２０２６-０９-０６suffix",  # noqa: RUF001 -- intentional Unicode decimal digits
        "prefix2026-09-06suffix",
        "MARCH 4, 2026; 03/04/26; 2026-09-06",
        "one week ago; around few months ago; ٢ days ago",
        "TODAY; yesterday; last weekend; Monday",
        "in March; during September 2026; until 2026-09-07",
        "frıday; ſaturday; during Aprıl 2026",  # noqa: RUF001 -- re.I Unicode equivalences
        "may; ago; 123; Mondayish; _yesterday; weekend_plan",
        "x" * 8192 + "\nMarch 4, 2026",
        "March 4, 2026\n" + "x" * 8192,
    ],
)
def test_date_signal_preserves_all_regex_ranges_and_first_matches(text: str) -> None:
    # Original rules are the oracle; a signal may admit false positives but
    # must never hide a supported expression or its Unicode/boundary behavior.
    expected = [
        match.span()
        for pattern in evidence_semantics._DATE_PATTERNS
        for match in pattern.finditer(text)
    ]
    first: dict[re.Pattern[str], re.Match[str] | None] = {}
    assert evidence_semantics._date_match_ranges(text, first_matches=first) == expected
    assert set(first) == set(evidence_semantics._DATE_PATTERNS)
    for pattern, matched in first.items():
        original = pattern.search(text)
        assert (matched.span() if matched else None) == (original.span() if original else None)
