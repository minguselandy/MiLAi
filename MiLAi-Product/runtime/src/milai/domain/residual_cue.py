"""Expression-only residual cue and privacy-safe audit contracts.

ResidualCue is deliberately not an acquisition action.  Runtime has already
selected channel, scope, bounds, source policy, candidate cap, expansion and
completion policy before this value can be considered.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.requirement_state import canonical_sha256

_FORBIDDEN_CONTROL = re.compile(
    r"(?:"
    r"\bfinal\s+answer\b|\banswer\s*(?:is|[:=])|"
    r"\bcomplete(?:d|ness)?\b|"
    r"\b(?:accept|reject)(?:ed|ing)?\s+evidence\b|"
    r"\bevidence\s+(?:accept|reject)(?:ed|ion)?\b|"
    r"\b(?:change|expand|override|widen|ignore)\s+"
    r"(?:scope|authority|permission|principal|tenant|time(?:\s+bounds?)?)\b|"
    r"\b(?:scope|authority|permission|principal|tenant)\s*(?:[:=]|override)\b|"
    r"\b(?:use|select|switch|force)\s+(?:channel|fts|dense|vector|adjacent|episode)\b|"
    r"\b(?:channel|top[_ -]?k|candidate\s+cap|retry)\s*[:=]"
    r")",
    re.IGNORECASE,
)


def _validate_expression_group(name: str, values: list[str]) -> None:
    if values != sorted(set(values), key=lambda value: (value.casefold(), value)):
        raise ValueError(f"residual cue {name} must be unique and deterministically ordered")
    for value in values:
        if not value.strip() or value != value.strip() or len(value) > 128:
            raise ValueError(f"residual cue {name} contains an empty, padded, or long term")
        if _FORBIDDEN_CONTROL.search(value):
            raise ValueError("residual cue contains a forbidden answer or control assertion")


class ResidualCueV02(BaseModel):
    """A bounded expression hint for one already-selected requirement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["residual-cue-v0.2"] = "residual-cue-v0.2"
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_requirement_id: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    phrases: list[str] = Field(default_factory=list, max_length=8)
    morphological_variants: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_expression_only(self) -> Self:
        groups = {
            "aliases": self.aliases,
            "phrases": self.phrases,
            "morphological_variants": self.morphological_variants,
        }
        for name, values in groups.items():
            _validate_expression_group(name, values)
        flattened = [value.casefold() for values in groups.values() for value in values]
        if not flattened:
            raise ValueError("residual cue requires at least one expression")
        if len(flattened) != len(set(flattened)):
            raise ValueError("residual cue expressions must be unique across groups")
        return self

    @property
    def cue_digest(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


ResidualCueAuditReason = Literal[
    "ACCEPTED_EXPRESSION_ONLY",
    "REJECTED_SCHEMA",
    "REJECTED_STATE_MISMATCH",
    "REJECTED_TARGET_NOT_CURRENT_UNRESOLVED",
    "REJECTED_ENTITY_OUTSIDE_QUERY_STATE",
    "DISABLED_NOT_NEEDED",
]


class ResidualCuePublicDigestReceiptV02(BaseModel):
    """Public receipt: digest chain and counts, never exact cue text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["residual-cue-public-digest-v0.2"] = (
        "residual-cue-public-digest-v0.2"
    )
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    cue_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    alias_count: int = Field(ge=0, le=8)
    phrase_count: int = Field(ge=0, le=8)
    morphological_variant_count: int = Field(ge=0, le=8)
    reason_code: ResidualCueAuditReason

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        expression_count = (
            self.alias_count + self.phrase_count + self.morphological_variant_count
        )
        accepted = self.reason_code == "ACCEPTED_EXPRESSION_ONLY"
        if accepted and (self.cue_digest is None or expression_count == 0):
            raise ValueError("accepted public cue receipt requires digest and expression counts")
        if not accepted and (self.cue_digest is not None or expression_count):
            raise ValueError("rejected or disabled public cue receipt cannot claim cue content")
        return self


class ResidualCueRestrictedArtifactV02(BaseModel):
    """Restricted artifact metadata plus ciphertext; exact plaintext is excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["residual-cue-restricted-artifact-v0.2"] = (
        "residual-cue-restricted-artifact-v0.2"
    )
    cue_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ciphertext: str = Field(min_length=32)
    ciphertext_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    encryption_scheme: Literal["AES-256-GCM"] = "AES-256-GCM"
    encryption_key_ref: str = Field(min_length=1, max_length=160)
    created_at: datetime
    retention_until: datetime

    @model_validator(mode="after")
    def validate_retention(self) -> Self:
        if self.created_at.tzinfo is None or self.retention_until.tzinfo is None:
            raise ValueError("restricted cue timestamps must be timezone-aware")
        if self.retention_until <= self.created_at:
            raise ValueError("restricted cue retention must end after creation")
        return self


def build_residual_cue_public_receipt(
    cue: ResidualCueV02,
    *,
    acquisition_capability_digest: str,
) -> ResidualCuePublicDigestReceiptV02:
    return ResidualCuePublicDigestReceiptV02(
        requirement_state_digest=cue.requirement_state_digest,
        acquisition_capability_digest=acquisition_capability_digest,
        cue_digest=cue.cue_digest,
        alias_count=len(cue.aliases),
        phrase_count=len(cue.phrases),
        morphological_variant_count=len(cue.morphological_variants),
        reason_code="ACCEPTED_EXPRESSION_ONLY",
    )


__all__ = [
    "ResidualCueAuditReason",
    "ResidualCuePublicDigestReceiptV02",
    "ResidualCueRestrictedArtifactV02",
    "ResidualCueV02",
    "build_residual_cue_public_receipt",
]
