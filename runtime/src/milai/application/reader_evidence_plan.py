"""DG-23 internal decision snapshot and Reader evidence planning helpers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from milai.domain.reader_evidence_plan import (
    AcceptedBindingSpan,
    DecisionSnapshot,
    canonical_digest,
)


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
    accepted_evidence_ids: Sequence[str] = (),
    accepted_binding_spans: Sequence[AcceptedBindingSpan] = (),
    rejected_reasons: Sequence[str] = (),
    required_requirement_ids: Sequence[str] = (),
    unresolved_requirement_ids: Sequence[str] = (),
) -> DecisionSnapshot:
    """Compile immutable decision material with no presentation-budget input."""
    required = tuple(sorted(set(required_requirement_ids)))
    unresolved = tuple(sorted(set(unresolved_requirement_ids)))
    if not set(unresolved).issubset(required):
        raise ValueError("unresolved requirements must be drawn from required requirements")
    rejected = dict(sorted(Counter(rejected_reasons).items()))
    return DecisionSnapshot(
        source_snapshot_digest=canonical_digest(_json_value(source_snapshot_material)),
        query_ir_digest=canonical_digest(_json_value(query_ir_material)),
        acquisition_plan_digest=canonical_digest(
            _json_value(acquisition_plan_material)
        ),
        candidate_snapshot_digest=canonical_digest(
            _json_value(candidate_snapshot_material)
        ),
        gate_digest=canonical_digest(_json_value(gate_material)),
        binding_digest=canonical_digest(_json_value(binding_material)),
        requirement_state_digest=canonical_digest(
            _json_value(requirement_state_material)
        ),
        sufficiency_digest=canonical_digest(_json_value(sufficiency_material)),
        operator_result_digest=canonical_digest(
            _json_value(operator_result_material)
        ),
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


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return value


__all__ = ["build_decision_snapshot"]
