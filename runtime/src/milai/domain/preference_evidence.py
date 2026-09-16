"""Non-canonical evidence views for query-time preference synthesis."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue

PreferenceRequirementSlot: TypeAlias = Literal[
    "PREFERENCE_SIGNAL_SET",
    "CURRENT_INTENT",
]


def _preference_slots() -> list[PreferenceRequirementSlot]:
    return ["PREFERENCE_SIGNAL_SET"]


class PreferenceEvidenceSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    stance: Literal["POSITIVE", "NEGATIVE"]
    text: str = Field(min_length=1)
    observed_at: str | None = None
    span: dict[str, JsonValue]
    interpretation: dict[str, JsonValue]
    requirement_binding: dict[str, JsonValue]


class PreferenceViewCompleteness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_slots: list[PreferenceRequirementSlot] = Field(default_factory=_preference_slots)
    filled_slots: list[PreferenceRequirementSlot] = Field(default_factory=list)
    support_threshold_met: bool
    bounded_scan_complete: Literal[False] = False
    currentness_proven: Literal[False] = False
    unresolved_reasons: list[str] = Field(default_factory=list)


class PreferenceEvidenceView(BaseModel):
    """Rebuildable support view; never a current preference or ClaimVersion."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["preference-evidence-view-v0.1"] = "preference-evidence-view-v0.1"
    kind: Literal["PREFERENCE_EVIDENCE_VIEW"] = "PREFERENCE_EVIDENCE_VIEW"
    view_class: Literal["DERIVED_VIEW"] = "DERIVED_VIEW"
    authority_class: Literal["EVIDENCE_ONLY"] = "EVIDENCE_ONLY"
    operator: Literal["PREFERENCE_RESOLVE"] = "PREFERENCE_RESOLVE"
    status: Literal["PARTIAL", "ABSENT", "CONTESTED"]
    value: list[PreferenceEvidenceSignal]
    display_value: str
    reason: str
    subject_terms: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_turn_refs: list[str] = Field(default_factory=list)
    current_intent_evidence_refs: list[str] = Field(default_factory=list)
    current_intent_source_turn_refs: list[str] = Field(default_factory=list)
    completeness: PreferenceViewCompleteness
    hidden_model_calls: Literal[0] = 0
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False
    persisted: Literal[False] = False

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = [
    "PreferenceEvidenceSignal",
    "PreferenceEvidenceView",
    "PreferenceRequirementSlot",
    "PreferenceViewCompleteness",
]
