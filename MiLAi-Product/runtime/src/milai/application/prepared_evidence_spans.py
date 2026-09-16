"""Owned exact source geometry; remaining span DTOs are created on consumption."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from typing import Any, overload

from milai.application.evidence_semantics import (
    _iter_source_offsets,
    _project_evidence_span,
    _source_offsets,
    _source_span_inputs,
    deduplicate_projected_spans,
)
from milai.domain.semantic_query import EvidenceSpan


class PreparedEvidenceSpans(Sequence[EvidenceSpan]):
    """Validate each source on its first real span, preserving exact split rules.

    The shared splitter stops after the first real span during preparation.
    Shared metadata is validated immediately; full source geometry is computed
    on consumption. No source or eligibility result is cached across requests.
    """

    def __init__(self, sources: Sequence[Mapping[str, Any]], *, deduplicate: bool = False) -> None:
        self._records: list[tuple[EvidenceSpan, str, dict[str, Any]]] = []
        self._values: list[EvidenceSpan] | None = None
        self._deduplicate = deduplicate
        self._lock = Lock()
        for item in sources:
            prepared = _source_span_inputs(item)
            if prepared is None:
                continue
            content, metadata = prepared
            first_offset = next(_iter_source_offsets(content), None)
            if first_offset is None:
                continue
            first = _project_evidence_span(content, metadata, *first_offset)
            # Pydantic owns the validated JSON provenance; caller mappings are not retained.
            owned_metadata = {key: getattr(first, key) for key in metadata}
            self._records.append((first, content, owned_metadata))

    def __bool__(self) -> bool:
        return bool(self._values) if self._values is not None else bool(self._records)

    @property
    def has_nonblank(self) -> bool:
        if self._values is not None:
            return any(span.text.strip() for span in self._values)
        return bool(self._records)

    def __len__(self) -> int:
        return len(self.materialize())

    def __iter__(self) -> Iterator[EvidenceSpan]:
        return iter(self.materialize())

    @overload
    def __getitem__(self, index: int) -> EvidenceSpan: ...

    @overload
    def __getitem__(self, index: slice) -> list[EvidenceSpan]: ...

    def __getitem__(self, index: int | slice) -> EvidenceSpan | list[EvidenceSpan]:
        return self.materialize()[index]

    def __deepcopy__(self, memo: dict[int, Any]) -> PreparedEvidenceSpans:
        with self._lock:
            clone = object.__new__(type(self))
            memo[id(self)] = clone
            clone._records = deepcopy(self._records, memo)
            clone._values = deepcopy(self._values, memo)
            clone._deduplicate = self._deduplicate
            clone._lock = Lock()
            return clone

    def materialize(self) -> list[EvidenceSpan]:
        with self._lock:
            if self._values is None:
                spans: list[EvidenceSpan] = []
                for first, content, metadata in self._records:
                    spans.append(first)
                    spans.extend(
                        _project_evidence_span(content, metadata, start, end)
                        for start, end in _source_offsets(content)[1:]
                    )
                ordered = sorted(spans, key=lambda span: (
                    span.source_timestamp or datetime.min.replace(tzinfo=UTC),
                    span.source_turn_ref, span.start, span.span_id,
                ))
                self._values = (
                    deduplicate_projected_spans(ordered) if self._deduplicate else ordered
                )
            return self._values
