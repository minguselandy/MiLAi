"""Passive, non-authoritative Formation first-loss observation primitives."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from milai.domain.requirement_state import canonical_sha256

StageOutcome = Literal[
    "SURVIVED",
    "FIRST_LOSS",
    "NOT_APPLICABLE",
    "NOT_IMPLEMENTED",
    "AUTHORIZED_REJECTION",
]

STAGES = (
    "F00_RAW_EVIDENCE_CAPTURED",
    "F10_EPISODE_FORMED",
    "F20_MENTION_FORMED",
    "F30_IDENTITY_RESOLVED",
    "F40_EVENT_TIME_GROUNDED",
    "F50_STATE_OR_CHANGE_FORMED",
    "F60_PROPOSAL_EMITTED",
    "F70_CANONICAL_DISPOSITION",
    "F80_RETRIEVAL_PROJECTION_BUILT",
)

_TARGET_STAGE = {
    "EPISODE_BOUNDARY": "F10_EPISODE_FORMED",
    "ENTITY_MENTION": "F20_MENTION_FORMED",
    "EVENT_MENTION": "F20_MENTION_FORMED",
    "ENTITY_IDENTITY": "F30_IDENTITY_RESOLVED",
    "EVENT_IDENTITY": "F30_IDENTITY_RESOLVED",
    "EVENT_OCCURRENCE_TIME": "F40_EVENT_TIME_GROUNDED",
    "STATE_ASSERTION": "F50_STATE_OR_CHANGE_FORMED",
    "STATE_TRANSITION": "F50_STATE_OR_CHANGE_FORMED",
    "CANONICAL_DISPOSITION": "F60_PROPOSAL_EMITTED",
    "RETRIEVAL_PROJECTION": "F80_RETRIEVAL_PROJECTION_BUILT",
}


class FormationAuditInput(BaseModel):
    """The scorer-sealed minimum needed to observe one obligation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    obligation_id: str = Field(min_length=1)
    obligation_kind: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    span_text: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    expected_canonical_disposition: str = Field(min_length=1)


class StageObservation(BaseModel):
    """One passive stage outcome plus its frozen implementation availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str
    availability: str
    outcome: StageOutcome


class FormationTraceRecord(BaseModel):
    """One lightweight terminal trace row; never a product or canonical object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    obligation_id: str
    obligation_kind: str
    source_span_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_surviving_stage: str | None
    first_loss_stage: str | None
    reason_code: str
    observed_object_ids: list[str]
    source_lineage_ok: bool
    stage_availability: list[StageObservation]
    audit_authority: Literal[False] = False
    canonical_mutation: Literal[False] = False
    provider_calls: Literal[0] = 0


class PassiveFormationAuditObserver:
    """Classify frozen objects without touching product control or data flow."""

    def __init__(self, stage_availability: Mapping[str, str]) -> None:
        if tuple(stage_availability) != STAGES:
            raise ValueError("MF01_STAGE_AVAILABILITY_ORDER_DRIFT")
        self._availability = dict(stage_availability)

    def observe(self, item: FormationAuditInput) -> FormationTraceRecord:
        target = _TARGET_STAGE.get(item.obligation_kind)
        if target is None:
            raise ValueError(f"MF01_OBLIGATION_KIND_UNSUPPORTED:{item.obligation_kind}")
        source_span_id = canonical_sha256(
            {
                "evidence_id": item.evidence_id,
                "source_ref": item.source_ref,
                "start": item.span_start,
                "end": item.span_end,
                "text": item.span_text,
            }
        )
        if item.obligation_kind == "RETRIEVAL_PROJECTION":
            return self._terminal_survival(
                item,
                source_span_id,
                observed=[item.evidence_id, item.source_ref],
                applicable_stages={STAGES[0], STAGES[-1]},
            )
        if (
            item.obligation_kind == "CANONICAL_DISPOSITION"
            and item.expected_canonical_disposition
            == "NOT_APPLICABLE_QUERY_EVIDENCE_ONLY"
        ):
            return self._terminal_survival(
                item,
                source_span_id,
                observed=[item.evidence_id],
                applicable_stages={STAGES[0]},
                authorized_stages={
                    "F60_PROPOSAL_EMITTED",
                    "F70_CANONICAL_DISPOSITION",
                },
            )

        reason = _first_loss_reason(item)
        observations: list[StageObservation] = []
        lost = False
        last_surviving: str | None = None
        for stage in STAGES:
            if stage == STAGES[0]:
                outcome: StageOutcome = "SURVIVED"
                last_surviving = stage
            elif stage == target:
                outcome = "FIRST_LOSS"
                lost = True
            elif lost:
                outcome = "NOT_APPLICABLE"
            else:
                outcome = "NOT_APPLICABLE"
            observations.append(
                StageObservation(
                    stage=stage,
                    availability=self._availability[stage],
                    outcome=outcome,
                )
            )
        return FormationTraceRecord(
            case_id=item.case_id,
            obligation_id=item.obligation_id,
            obligation_kind=item.obligation_kind,
            source_span_id=source_span_id,
            last_surviving_stage=last_surviving,
            first_loss_stage=target,
            reason_code=reason,
            observed_object_ids=[item.evidence_id],
            source_lineage_ok=True,
            stage_availability=observations,
        )

    def _terminal_survival(
        self,
        item: FormationAuditInput,
        source_span_id: str,
        *,
        observed: list[str],
        applicable_stages: set[str],
        authorized_stages: set[str] | None = None,
    ) -> FormationTraceRecord:
        authorized_stages = authorized_stages or set()
        observations = []
        for stage in STAGES:
            if stage in authorized_stages:
                outcome: StageOutcome = "AUTHORIZED_REJECTION"
            elif stage in applicable_stages:
                outcome = "SURVIVED"
            else:
                outcome = "NOT_APPLICABLE"
            observations.append(
                StageObservation(
                    stage=stage,
                    availability=self._availability[stage],
                    outcome=outcome,
                )
            )
        last = max(
            (value.stage for value in observations if value.outcome == "SURVIVED"),
            key=STAGES.index,
        )
        return FormationTraceRecord(
            case_id=item.case_id,
            obligation_id=item.obligation_id,
            obligation_kind=item.obligation_kind,
            source_span_id=source_span_id,
            last_surviving_stage=last,
            first_loss_stage=None,
            reason_code="TERMINAL_SURVIVAL",
            observed_object_ids=observed,
            source_lineage_ok=True,
            stage_availability=observations,
        )


T = TypeVar("T")


def observe_passthrough(
    value: T,
    *,
    observer: PassiveFormationAuditObserver,
    audit_input: FormationAuditInput,
) -> tuple[T, FormationTraceRecord]:
    """Return the exact product object unchanged while emitting an audit value."""

    return value, observer.observe(audit_input)


def _first_loss_reason(item: FormationAuditInput) -> str:
    if item.obligation_kind == "EPISODE_BOUNDARY":
        return "EPISODE_BOUNDARY_MISSED"
    if item.obligation_kind == "ENTITY_MENTION":
        return "ENTITY_MENTION_MISSED"
    if item.obligation_kind == "EVENT_MENTION":
        return "EVENT_MENTION_MISSED"
    if item.obligation_kind == "ENTITY_IDENTITY":
        return "ALIAS_UNRESOLVED"
    if item.obligation_kind == "EVENT_IDENTITY":
        return "EVENT_IDENTITY_DUPLICATED"
    if item.obligation_kind == "EVENT_OCCURRENCE_TIME":
        return "RELATIVE_TIME_UNRESOLVED"
    if item.obligation_kind == "STATE_ASSERTION":
        return "STATE_ASSERTION_NOT_FORMED"
    if item.obligation_kind == "STATE_TRANSITION":
        expected = item.expected.upper()
        if "RETRACT" in expected or "CORRECTION" in expected:
            return "CORRECTION_NOT_LINKED"
        if "TEMPORARY" in expected or "EXPIRES" in expected:
            return "TEMPORARY_CONSTRAINT_TREATED_AS_REPLACEMENT"
        return "UPDATE_RELATION_MISCLASSIFIED"
    if item.obligation_kind == "CANONICAL_DISPOSITION":
        return "PROPOSAL_NOT_EMITTED"
    raise ValueError(f"MF01_FIRST_LOSS_REASON_UNMAPPED:{item.obligation_kind}")


__all__ = [
    "STAGES",
    "FormationAuditInput",
    "FormationTraceRecord",
    "PassiveFormationAuditObserver",
    "StageObservation",
    "StageOutcome",
    "observe_passthrough",
]
