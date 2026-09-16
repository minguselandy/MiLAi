"""Request-local, unfiltered Raw diagnostics; never operator authority."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from copy import deepcopy
from threading import Lock
from typing import Any, Generic, Literal, TypeVar, overload

from milai.application.evidence_semantics import bind_requirements, interpret_evidence_spans
from milai.application.prepared_evidence_spans import PreparedEvidenceSpans
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    RequirementBinding,
)

T = TypeVar("T")


class _DiagnosticSequence(Sequence[T], Generic[T]):
    def __init__(self, owner: DeferredRawSemantics, field: int, present: bool) -> None:
        self._owner = owner
        self._field = field
        self._present = present

    def __bool__(self) -> bool:
        if self._owner._values is not None:
            return bool(self._owner._values[self._field])
        return self._present

    def __len__(self) -> int:
        return len(self._values())

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice) -> T | list[T]:
        return self._values()[index]

    def __iter__(self) -> Iterator[T]:
        return iter(self._values())

    def _values(self) -> list[Any]:
        return self._owner.materialize()[self._field]


class DeferredRawSemantics:
    """Own newly projected spans and freeze caller-owned query requirements.

    With no kind filter, each nonblank span emits STATE_OBSERVATION. Unfiltered
    binding retains every requirement/interpretation pair, including REJECTED.
    Thus presence is known without computing compatibility. All other list
    operations execute the original functions and retain their full results.
    """

    def __init__(
        self,
        requirements: Sequence[EvidenceRequirementV02],
        owned_spans: Sequence[EvidenceSpan],
        *,
        compatibility_profile: Literal["legacy-v0.1", "dg22-v0.2"],
    ) -> None:
        self._requirements = deepcopy(list(requirements))
        self.spans = owned_spans
        self._profile = compatibility_profile
        self._values: tuple[
            list[EvidenceInterpretationCandidate], list[RequirementBinding]
        ] | None = None
        self._lock = Lock()
        present = (
            owned_spans.has_nonblank if isinstance(owned_spans, PreparedEvidenceSpans)
            else any(span.text.strip() for span in owned_spans)
        )
        self.interpretations: Sequence[EvidenceInterpretationCandidate] = _DiagnosticSequence(
            self, 0, present,
        )
        self.bindings: Sequence[RequirementBinding] = _DiagnosticSequence(
            self, 1, bool(self._requirements) and present,
        )

    def materialize(
        self,
    ) -> tuple[list[EvidenceInterpretationCandidate], list[RequirementBinding]]:
        with self._lock:
            if self._values is None:
                interpretations = interpret_evidence_spans(self.spans)
                bindings = bind_requirements(
                    self._requirements, interpretations, self.spans,
                    compatibility_profile=self._profile,
                )
                self._values = interpretations, bindings
            return self._values

    def freeze(self) -> DeferredRawSemantics:
        """Snapshot ownership includes any already materialized diagnostics."""
        with self._lock:
            frozen = DeferredRawSemantics(
                self._requirements, deepcopy(self.spans), compatibility_profile=self._profile,
            )
            frozen._values = deepcopy(self._values)
            return frozen

    def binding_material(self) -> dict[str, Any]:
        interpretations, bindings = self.materialize()
        return {
            "spans": self.spans,
            "interpretations": interpretations,
            "bindings": bindings,
            "semantic_audit": None,
        }
