from collections.abc import Collection

import pytest

from milai.application.evidence_semantics import (
    _interpret_evidence_spans,
    project_evidence_spans,
)
from milai.domain.semantic_query import EvidenceSpan, InterpretationKind


def _spans() -> list[EvidenceSpan]:
    sources = []
    for index, (speaker, observed) in enumerate(
        [
            ("user", "2026-09-05T12:00:00+00:00"),
            ("assistant", "2026-09-06T12:00:00+08:00"),
            ("unknown", None),
            ("user", "2025-01-01T00:00:00+00:00"),
        ]
    ):
        identity = f"source-{index}"
        sources.append(
            {
                "evidence_id": identity,
                "subject_id": identity,
                "source_ref": f"memory://session/{identity}/turn/0",
                "source_context": {"session_id": identity, "turn_id": f"{identity}:turn:0"},
                "source_context_source": "STRUCTURED_TURN_METADATA",
                "speaker": speaker,
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "content": (
                    "We completed 7 repairs yesterday. I plan to visit the city. "
                    "I prefer tea. March 4; until 2026-09-07. "
                    "We paid $12.50 two days ago. 2026-02-30 and 2026-09-01."
                    "\nfirst\n" + "x" * 8192 + "\nlast"
                ),
                "observed_at": observed,
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
            }
        )
    return project_evidence_spans(sources)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "allowed", [None, [], ["STATE_OBSERVATION"], ["EVENT", "QUANTITY"], ["DECISION"]]
)
def test_batch_analysis_matches_independent_sources(
    reverse: bool, allowed: Collection[InterpretationKind] | None
) -> None:
    spans = _spans()
    if reverse:
        spans.reverse()
    actual, suppressed = _interpret_evidence_spans(spans, allowed_kinds=allowed)
    independently = [
        _interpret_evidence_spans([span], allowed_kinds=allowed) for span in spans
    ]
    expected = sorted(
        [item for items, _ in independently for item in items],
        key=lambda item: (item.span_id, item.kind, item.interpretation_id),
    )
    assert actual == expected
    assert suppressed == sum(count for _, count in independently)


def test_repeated_text_preserves_speaker_time_provenance_and_output_independence() -> None:
    spans = _spans()
    by_id = {span.span_id: span for span in spans}
    values, _ = _interpret_evidence_spans(spans, allowed_kinds=None)
    decisions = [item for item in values if item.kind == "DECISION"]
    assert len(decisions) == 2
    assert {by_id[item.span_id].source_evidence_id for item in decisions} == {
        "source-0", "source-3"
    }
    events = [
        item for item in values
        if item.kind == "EVENT" and "repairs yesterday" in by_id[item.span_id].text
    ]
    assert len(events) == 4
    expected = {
        "source-0": "2026-09-04T00:00:00+00:00",
        "source-1": "2026-09-05T00:00:00+08:00",
        "source-3": "2024-12-31T00:00:00+00:00",
    }
    for item in events:
        span = by_id[item.span_id]
        if span.source_evidence_id == "source-2":
            assert item.event_time is None
        else:
            assert item.event_time is not None
            assert item.event_time.start.isoformat() == expected[span.source_evidence_id]
            assert item.event_time.anchor_provenance["span_id"] == span.span_id
            assert item.event_time.anchor_provenance["source_turn_ref"] == span.source_turn_ref
    states = [
        item for item in values if item.kind == "STATE_OBSERVATION" and item.value == "first"
    ]
    assert len(states) == 4
    states[0].entities.append("mutation")
    assert all("mutation" not in item.entities for item in states[1:])
    again, _ = _interpret_evidence_spans(spans, allowed_kinds=None)
    assert all("mutation" not in item.entities for item in again)
