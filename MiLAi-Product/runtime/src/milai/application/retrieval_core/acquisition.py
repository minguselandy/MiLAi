"""Acquisition result composition and query-local evidence material helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from milai.application.acquisition_state import build_evidence_reference_note
from milai.application.evidence_acquisition import EvidenceAcquisitionExecutionRef
from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.evidence_source import (
    structured_evidence_identity,
    structured_evidence_speaker,
)
from milai.application.lean_recall import lean_decision_mode
from milai.application.operator_binding_authority import (
    operator_operands_from_raw_bindings,
)
from milai.application.retrieval_core.candidates import _result_identity
from milai.domain.acquisition import CandidateEnvelope, EvidenceReferenceNote
from milai.domain.retrieval import QueryPlan
from milai.domain.semantic_query import EvidenceRequirementV02, RequirementBinding


def _merge_evidence_results(
    assembled: tuple[
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, Any]],
        list[str],
    ],
    evidence_results: list[dict[str, Any]],
    limit: int,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, Any]],
    list[str],
]:
    if not evidence_results:
        return assembled
    accepted, rejected, canonical_results, open_issue_ids = assembled
    evidence_accepted: list[dict[str, object]] = []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in evidence_results:
        evidence_id = raw.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        item = dict(raw)
        item["matched_by"] = ["evidence_fts"]
        normalized.append(item)
        evidence_accepted.append(
            {
                "candidate_kind": "EVIDENCE_OBSERVATION",
                "evidence_id": evidence_id,
                "evidence_ids": [evidence_id],
                "relevance_score": item.get("relevance_score"),
                "matched_by": ["evidence_fts"],
            }
        )
    combined = [*normalized, *canonical_results][:limit]
    selected = {_result_identity(item) for item in combined}
    selected.discard(None)
    combined_accepted = [
        item for item in [*evidence_accepted, *accepted] if _result_identity(item) in selected
    ]
    return combined_accepted, rejected, combined, open_issue_ids


def _formation_candidate_results(
    hydrated: Sequence[Mapping[str, Any]],
    *,
    projection_digest: str | None,
) -> list[dict[str, Any]]:
    """Attach bounded acquisition provenance to governed Formed source rows."""

    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    probe_id = f"formation:{projection_digest or 'ephemeral'}"
    for rank, raw in enumerate(hydrated, start=1):
        evidence_id = raw.get("evidence_id")
        source_ref = raw.get("source_ref")
        if (
            not isinstance(evidence_id, str)
            or not evidence_id
            or evidence_id in seen
            or not isinstance(source_ref, str)
            or not source_ref
        ):
            continue
        source_identity = structured_evidence_identity(raw, source_ref)
        if source_identity is None:
            continue
        speaker, speaker_source = structured_evidence_speaker(raw)
        envelope = CandidateEnvelope(
            candidate_id=evidence_id,
            source_evidence_id=evidence_id,
            source_turn_ref=source_ref,
            subject_id=source_identity.subject_id,
            session_id=source_identity.session_id,
            turn_id=source_identity.turn_id,
            identity_source=source_identity.identity_source,
            speaker=speaker,
            speaker_source=speaker_source,
            source_observed_at=raw.get("observed_at"),
            matched_probes=[probe_id],
            matched_slots=[],
            channel_ranks={"FTS_RAW": rank},
            channel_scores={"FTS_RAW": 0.0},
            probe_ranks={probe_id: rank},
            probe_scores={probe_id: 0.0},
            fusion_rank=rank,
            fusion_score=0.0,
            matched_fields=["formation_source_id"],
            body_ref=source_ref,
            body_hydrated=isinstance(raw.get("content"), str),
        )
        item = dict(raw)
        item["acquisition_candidate"] = envelope.model_dump(mode="json")
        item["formation_projection_digest"] = projection_digest
        values.append(item)
        seen.add(evidence_id)
    return values


def _union_formation_and_raw(
    formed: Sequence[Mapping[str, Any]],
    raw: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep every Raw result and append only newly found governed sources."""

    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (raw, formed):
        for item in source:
            evidence_id = item.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id or evidence_id in seen:
                continue
            values.append(dict(item))
            seen.add(evidence_id)
    return values


def _acquisition_candidate_envelopes(
    evidence_results: list[dict[str, Any]],
) -> list[CandidateEnvelope]:
    """Recover only Runtime-built acquisition envelopes for query-local state."""

    candidates: list[CandidateEnvelope] = []
    seen: set[str] = set()
    for result in evidence_results:
        raw = result.get("acquisition_candidate")
        if not isinstance(raw, dict):
            continue
        candidate = CandidateEnvelope.model_validate(raw)
        if candidate.candidate_id in seen:
            continue
        candidates.append(candidate)
        seen.add(candidate.candidate_id)
    return candidates


def _acquisition_reference_material(
    evidence_results: list[dict[str, Any]],
    requirements: list[EvidenceRequirementV02],
    *,
    execution: EvidenceAcquisitionExecutionRef | None = None,
) -> tuple[list[RequirementBinding], list[EvidenceReferenceNote]]:
    """Build Binding-backed query-local notes from exact governed source spans."""

    if execution is None:
        spans = project_evidence_spans(evidence_results)
        interpretations = interpret_evidence_spans(spans)
        bindings = bind_requirements(requirements, interpretations, spans)
    else:
        accepted_bindings = operator_operands_from_raw_bindings(execution.bindings)
        if not accepted_bindings:
            return [], []
        spans = list(execution.spans)
        interpretations = list(execution.interpretations)
        bindings = list(execution.bindings)
    bindings = list(operator_operands_from_raw_bindings(bindings))
    source_by_id = {
        str(item["evidence_id"]): item
        for item in evidence_results
        if isinstance(item.get("evidence_id"), str)
    }
    span_by_id = {span.span_id: span for span in spans}
    interpretation_by_id = {
        interpretation.interpretation_id: interpretation for interpretation in interpretations
    }
    notes: list[EvidenceReferenceNote] = []
    seen_notes: set[tuple[str, str]] = set()
    for binding in bindings:
        if binding.status != "MATCH":
            continue
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        if interpretation is None:
            continue
        span = span_by_id.get(interpretation.span_id)
        if span is None:
            continue
        source = source_by_id.get(span.source_evidence_id)
        identity = (binding.requirement_id, span.source_evidence_id)
        if source is None or identity in seen_notes:
            continue
        try:
            note = build_evidence_reference_note(
                source,
                span,
                interpretation,
                binding,
            )
        except ValueError:
            # An inconsistent projection is never converted into a query-local
            # Evidence note; Binding/Sufficiency still retain their own owner.
            continue
        notes.append(note)
        seen_notes.add(identity)
        if len(notes) >= 256:
            break
    return bindings, notes


def _use_acquisition_composition(
    plan: QueryPlan,
    evidence_composition: Mapping[str, Any] | None,
) -> bool:
    """Use raw-Evidence composition only for a genuinely strict operator.

    A CURRENT canonical-state query is an ordinary lookup even though its
    QueryPlan carries ``LATEST_VALID_STATE``.  Formation may independently
    produce an abstained Evidence result for that query; it must not replace a
    value already admitted by the Canonical Gate.
    """

    return (
        evidence_composition is not None
        and lean_decision_mode(plan) == "STRICT_OPERATOR"
    )
