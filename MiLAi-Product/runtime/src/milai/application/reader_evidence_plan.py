"""DG-23 internal decision snapshot and Reader evidence planning helpers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from threading import Lock
from typing import Any, Literal, overload

from pydantic import BaseModel

from milai.application.deferred_raw_semantics import DeferredRawSemantics
from milai.domain.lean_recall import EvidenceSet, LeanRecallMode
from milai.domain.reader_evidence_plan import (
    AcceptedBindingSpan,
    DecisionFacts,
    DecisionSnapshot,
    canonical_digest,
)


class DeferredDecisionSnapshot:
    """Request-local frozen material; complete snapshots are derived on demand."""

    def __init__(self, facts: DecisionFacts, materials: dict[str, Any]) -> None:
        self._facts = facts.model_copy(deep=True)
        # The builder owns these freshly normalized containers. They are never exposed.
        self._materials = materials
        self._snapshot: DecisionSnapshot | None = None
        self._lock = Lock()

    @property
    def lean_recall_mode(self) -> LeanRecallMode:
        return self._facts.lean_recall_mode

    @property
    def evidence_set(self) -> EvidenceSet:
        return self._facts.evidence_set

    @property
    def accepted_evidence_ids(self) -> tuple[str, ...]:
        return self._facts.accepted_evidence_ids

    @property
    def snapshot_digest(self) -> str:
        return self.materialize().snapshot_digest

    def materialize(self) -> DecisionSnapshot:
        with self._lock:
            if self._snapshot is None:
                self._snapshot = _complete_snapshot(self._facts, self._materials)
                self._materials = {}
            return self._snapshot


DecisionSnapshotRef = DecisionSnapshot | DeferredDecisionSnapshot


def materialize_decision_snapshot(snapshot: DecisionSnapshotRef) -> DecisionSnapshot:
    return snapshot.materialize() if isinstance(snapshot, DeferredDecisionSnapshot) else snapshot


def _complete_snapshot(facts: DecisionFacts, materials: dict[str, Any]) -> DecisionSnapshot:
    values = facts.model_dump(mode="python")
    values.update({
        name: canonical_digest(
            _json_value(value.binding_material())
            if isinstance(value, DeferredRawSemantics) else value
        )
        for name, value in materials.items()
    })
    return DecisionSnapshot.model_validate(values)


@overload
def build_decision_snapshot(
    *,
    source_snapshot_material: object,
    query_ir_material: object,
    acquisition_plan_material: object,
    candidate_snapshot_material: object,
    gate_material: object,
    binding_material: object,
    requirement_state_material: object,
    sufficiency_material: object,
    operator_result_material: object,
    lean_recall_mode: LeanRecallMode = "LOOKUP",
    lean_recall_plan_material: object | None = None,
    evidence_set: EvidenceSet | None = None,
    accepted_evidence_ids: Sequence[str] = (),
    accepted_binding_spans: Sequence[AcceptedBindingSpan] = (),
    rejected_reasons: Sequence[str] = (),
    required_requirement_ids: Sequence[str] = (),
    unresolved_requirement_ids: Sequence[str] = (),
    defer_digests: Literal[False] = False,
) -> DecisionSnapshot:
    ...


@overload
def build_decision_snapshot(
    *,
    source_snapshot_material: object,
    query_ir_material: object,
    acquisition_plan_material: object,
    candidate_snapshot_material: object,
    gate_material: object,
    binding_material: object,
    requirement_state_material: object,
    sufficiency_material: object,
    operator_result_material: object,
    lean_recall_mode: LeanRecallMode = "LOOKUP",
    lean_recall_plan_material: object | None = None,
    evidence_set: EvidenceSet | None = None,
    accepted_evidence_ids: Sequence[str] = (),
    accepted_binding_spans: Sequence[AcceptedBindingSpan] = (),
    rejected_reasons: Sequence[str] = (),
    required_requirement_ids: Sequence[str] = (),
    unresolved_requirement_ids: Sequence[str] = (),
    defer_digests: Literal[True],
) -> DeferredDecisionSnapshot:
    ...


@overload
def build_decision_snapshot(
    *,
    source_snapshot_material: object,
    query_ir_material: object,
    acquisition_plan_material: object,
    candidate_snapshot_material: object,
    gate_material: object,
    binding_material: object,
    requirement_state_material: object,
    sufficiency_material: object,
    operator_result_material: object,
    lean_recall_mode: LeanRecallMode = "LOOKUP",
    lean_recall_plan_material: object | None = None,
    evidence_set: EvidenceSet | None = None,
    accepted_evidence_ids: Sequence[str] = (),
    accepted_binding_spans: Sequence[AcceptedBindingSpan] = (),
    rejected_reasons: Sequence[str] = (),
    required_requirement_ids: Sequence[str] = (),
    unresolved_requirement_ids: Sequence[str] = (),
    defer_digests: bool,
) -> DecisionSnapshotRef:
    ...


def build_decision_snapshot(
    *,
    source_snapshot_material: object,
    query_ir_material: object,
    acquisition_plan_material: object,
    candidate_snapshot_material: object,
    gate_material: object,
    binding_material: object,
    requirement_state_material: object,
    sufficiency_material: object,
    operator_result_material: object,
    lean_recall_mode: LeanRecallMode = "LOOKUP",
    lean_recall_plan_material: object | None = None,
    evidence_set: EvidenceSet | None = None,
    accepted_evidence_ids: Sequence[str] = (),
    accepted_binding_spans: Sequence[AcceptedBindingSpan] = (),
    rejected_reasons: Sequence[str] = (),
    required_requirement_ids: Sequence[str] = (),
    unresolved_requirement_ids: Sequence[str] = (),
    defer_digests: bool = False,
) -> DecisionSnapshotRef:
    """Compile immutable decision material with no presentation-budget input."""
    required = tuple(sorted(set(required_requirement_ids)))
    unresolved = tuple(sorted(set(unresolved_requirement_ids)))
    if not set(unresolved).issubset(required):
        raise ValueError("unresolved requirements must be drawn from required requirements")
    rejected = dict(sorted(Counter(rejected_reasons).items()))
    selected_evidence_set = evidence_set or EvidenceSet(
        required_requirement_ids=required,
    )
    materials = {
        "source_snapshot_digest": _json_value(source_snapshot_material),
        "query_ir_digest": _json_value(query_ir_material),
        "acquisition_plan_digest": _json_value(acquisition_plan_material),
        "candidate_snapshot_digest": _json_value(candidate_snapshot_material),
        "gate_digest": _json_value(gate_material),
        "binding_digest": (
            binding_material.freeze()
            if defer_digests and isinstance(binding_material, DeferredRawSemantics)
            else _json_value(
                binding_material.binding_material()
                if isinstance(binding_material, DeferredRawSemantics) else binding_material
            )
        ),
        "requirement_state_digest": _json_value(requirement_state_material),
        "sufficiency_digest": _json_value(sufficiency_material),
        "operator_result_digest": _json_value(operator_result_material),
        "lean_recall_plan_digest": _json_value(
            lean_recall_plan_material
            if lean_recall_plan_material is not None
            else {"mode": lean_recall_mode, "requirements": required}
        ),
    }
    facts = DecisionFacts(
        lean_recall_mode=lean_recall_mode,
        evidence_set=selected_evidence_set,
        accepted_evidence_ids=tuple(sorted(set(accepted_evidence_ids))),
        accepted_binding_spans=tuple(
            sorted(
                accepted_binding_spans,
                key=lambda item: (
                    str(getattr(item, "source_turn_ref", "")),
                    int(getattr(item, "start", 0)),
                    int(getattr(item, "end", 0)),
                    tuple(getattr(item, "requirement_ids", ())),
                    str(getattr(item, "evidence_id", "")),
                ),
            )
        ),
        rejected_evidence_summary=rejected,
        required_requirement_ids=required,
        unresolved_requirement_ids=unresolved,
    )
    if defer_digests:
        return DeferredDecisionSnapshot(facts, materials)
    return _complete_snapshot(facts, materials)


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        dump = value.model_dump
        result = dump(mode="json")
        # Pydantic's JSON serializer owns its output. Overrides and duck-typed
        # serializers can return aliases into the source; freeze those explicitly.
        return (
            result
            if getattr(dump, "__func__", None) is BaseModel.model_dump
            else deepcopy(result)
        )
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return value


__all__ = [
    "DecisionSnapshotRef", "DeferredDecisionSnapshot", "build_decision_snapshot",
    "materialize_decision_snapshot",
]
