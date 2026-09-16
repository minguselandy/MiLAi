from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from typing import Any

import pytest

from milai.application import prepared_evidence_spans as prepared
from milai.application.deferred_raw_semantics import DeferredRawSemantics
from milai.application.evidence_acquisition import _merge_grounded_spans
from milai.application.evidence_semantics import (
    _iter_source_offsets,
    _source_offsets,
    project_evidence_spans,
)


def _source(**changes: Any) -> dict[str, Any]:
    return {
        "evidence_id": "e-1", "source_ref": "turn-1", "subject_id": "subject-1",
        "content": "first\n正文\nlast", "observed_at": "2026-09-06T00:00:00+00:00",
        "permission_snapshot": {"readable": True}, "content_hash": {"nested": ["first", "last"]},
        **changes,
    }


@pytest.mark.parametrize("text,expected", [
    ("", []), ("?!", []), ("  ?!", [(2, 4)]),
    ("first\n正文\nlast", [(0, 5), (6, 8), (9, 13)]),
    ("Dr. Jones.\r\nLast!", [(0, 10), (12, 17)]),
    ("  first. last!  ", [(2, 8), (9, 14)]),
])
def test_source_offset_iterator_preserves_exact_boundaries(
    text: str, expected: list[tuple[int, int]],
) -> None:
    assert list(_iter_source_offsets(text)) == expected
    assert _source_offsets(text) == expected


def test_preparation_and_freeze_do_not_scan_remaining_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [_source()]
    expected = project_evidence_spans(sources)
    yielded: list[tuple[int, int]] = []
    full_scans: list[str] = []

    def first_offsets(content: str):  # type: ignore[no-untyped-def]
        for offset in _iter_source_offsets(content):
            yielded.append(offset)
            yield offset

    def all_offsets(content: str) -> list[tuple[int, int]]:
        full_scans.append(content)
        return _source_offsets(content)

    monkeypatch.setattr(prepared, "_iter_source_offsets", first_offsets)
    monkeypatch.setattr(prepared, "_source_offsets", all_offsets)
    spans = prepared.PreparedEvidenceSpans(sources)
    frozen = deepcopy(spans)
    assert bool(spans) and bool(frozen)
    assert yielded == [(0, 5)]
    assert full_scans == []
    sources[0]["content"] = "changed"
    assert frozen.materialize() == expected
    assert full_scans == ["first\n正文\nlast"]
    assert spans.materialize() == expected
    assert full_scans == ["first\n正文\nlast"] * 2


@pytest.mark.parametrize("text,count", [
    ("", 0), (" \t\n", 0), ("?!", 0), (".", 0), ("  ?!", 1),
    ("first\n正文\nlast", 3), ("Dr. Jones.\r\nLast!", 2), ("中文\uff1f\uff01", 1),
])
def test_preparation_keeps_exact_presence_and_full_projection(text: str, count: int) -> None:
    sources = [_source(content=text)]
    expected = project_evidence_spans(sources)
    spans = prepared.PreparedEvidenceSpans(sources)
    assert bool(spans) == bool(count)
    assert spans._values is None
    assert len(spans) == count
    assert spans[:] == expected
    assert [span.model_fields_set for span in spans] == [span.model_fields_set for span in expected]
    assert [span.model_dump(mode="json") for span in spans] == [
        span.model_dump(mode="json") for span in expected
    ]


@pytest.mark.parametrize("change", [
    {"subject_id": ""}, {"evidence_id": None}, {"source_ref": 4},
    {"observed_at": datetime(2026, 1, 1)}, {"content_hash": object()},
    {"permission_snapshot": {"readable": False}}, {"revoked_at": "revoked"},
    {"deleted_at": "deleted"}, {"retention_state": "EXPIRED"}, {"access_decision": "DENIED"},
    {"observed_at": "bad-date"},
])
def test_preparation_keeps_eligibility_and_early_metadata_validation(
    change: dict[str, Any],
) -> None:
    for content in ["first\nlast", ".", ""]:
        sources = [_source(content=content, **change)]
        try:
            expected = project_evidence_spans(sources)
        except Exception as exc:
            with pytest.raises(type(exc)):
                prepared.PreparedEvidenceSpans(sources)
        else:
            assert list(prepared.PreparedEvidenceSpans(sources)) == expected


@pytest.mark.parametrize("first_time", [
    None, "2026-09-06T00:00:00+14:00", "2025-09-06T00:00:00-08:00",
])
@pytest.mark.parametrize("second_time", [
    None, "2026-09-06T00:00:00+14:00", "2025-09-06T00:00:00-08:00",
])
def test_deduplication_preserves_post_projection_order_and_timezone(
    first_time: str | None, second_time: str | None,
) -> None:
    sources = [_source(observed_at=first_time), _source(observed_at=second_time)]
    spans = prepared.PreparedEvidenceSpans(sources, deduplicate=True)
    assert list(spans) == _merge_grounded_spans(project_evidence_spans(sources), None)
    known = [datetime.fromisoformat(stamp) for stamp in [first_time, second_time] if stamp]
    assert [span.source_timestamp for span in spans] == [max(known) if known else None] * 3


@pytest.mark.parametrize("already_materialized", [False, True])
def test_prepared_ownership_and_snapshot_copy_survive_mutation(
    already_materialized: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [_source()]
    expected = project_evidence_spans(sources)
    spans = prepared.PreparedEvidenceSpans(sources)
    if already_materialized:
        spans.materialize()
    frozen = deepcopy(spans)
    sources[0]["content_hash"]["nested"].clear()
    sources[0]["content"] = "changed"
    assert list(spans) == expected
    spans[0].provenance.clear()
    calls: list[bool] = []
    original = prepared._project_evidence_span

    def project(*args: Any, **kwargs: Any) -> Any:
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(prepared, "_project_evidence_span", project)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: frozen.materialize(), range(8)))
    assert all(value is values[0] for value in values)
    assert values[0] == expected
    assert len(calls) == (0 if already_materialized else 2)


@pytest.mark.parametrize("mutation", ["clear", "whitespace"])
def test_materialized_mutations_preserve_sequence_and_frozen_diagnostic_presence(
    mutation: str,
) -> None:
    spans = prepared.PreparedEvidenceSpans([_source()])
    owner = DeferredRawSemantics([], spans, compatibility_profile="dg22-v0.2")
    values = spans.materialize()
    if mutation == "clear":
        values.clear()
    else:
        for span in values:
            span.text = " " * len(span.text)
    assert bool(spans) == bool(values)
    assert spans.has_nonblank == any(span.text.strip() for span in values)
    frozen = owner.freeze()
    assert bool(frozen.interpretations) is False
