from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Operation = Literal[
    "CREATE",
    "SUPPORT",
    "WEAKEN",
    "REVALIDATE",
    "REGROUND",
    "SUPERSEDE",
    "CONTEXTUALIZE",
    "CONTRADICT",
    "NO_CHANGE",
    "SPLIT",
]
Authority = Literal["INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"]


class ProposalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    target_claim_id: UUID | None = None
    operation: Operation
    expected_version_id: UUID | None = None
    proposed_patch: dict[str, JsonValue]
    supporting_evidence_refs: list[UUID] = Field(default_factory=list, max_length=256)
    contradicting_evidence_refs: list[UUID] = Field(default_factory=list, max_length=256)
    scope_predicate: dict[str, JsonValue]
    requested_authority: Authority
    derivation_policy_id: str = Field(min_length=1, max_length=255)
    model_id: str | None = Field(default=None, max_length=255)
    template_id: str | None = Field(default=None, max_length=255)
    derivation_snapshot: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_operation_shape(self) -> Self:
        if len(set(self.supporting_evidence_refs)) != len(self.supporting_evidence_refs):
            raise ValueError("supporting_evidence_refs must be unique")
        if len(set(self.contradicting_evidence_refs)) != len(self.contradicting_evidence_refs):
            raise ValueError("contradicting_evidence_refs must be unique")
        if set(self.supporting_evidence_refs) & set(self.contradicting_evidence_refs):
            raise ValueError("an Evidence ref cannot be in both proposal branches")

        version_operations = {
            "CREATE",
            "SUPPORT",
            "WEAKEN",
            "REVALIDATE",
            "REGROUND",
            "SUPERSEDE",
            "CONTEXTUALIZE",
        }
        if self.operation == "CREATE":
            if self.target_claim_id is not None or self.expected_version_id is not None:
                raise ValueError("CREATE cannot target an existing ClaimVersion")
            required = {
                "subject_id",
                "predicate",
                "claim_type",
                "payload",
                "authority",
                "confidence",
            }
            if not required.issubset(self.proposed_patch):
                raise ValueError("CREATE proposed_patch is missing canonical fields")
        elif self.target_claim_id is None or self.expected_version_id is None:
            raise ValueError(
                "non-CREATE operations require target_claim_id and expected_version_id"
            )

        if self.operation in version_operations and not self.supporting_evidence_refs:
            raise ValueError("version operations require supporting Evidence")
        if self.operation == "CONTRADICT" and not self.contradicting_evidence_refs:
            raise ValueError("CONTRADICT requires contradicting Evidence")
        patch_authority = self.proposed_patch.get("authority")
        if patch_authority is not None and patch_authority != self.requested_authority:
            raise ValueError("proposed authority must equal requested_authority")
        resolution_fields = {
            "resolve_issue_id",
            "expected_issue_revision",
            "addressed_branches",
        }
        present_resolution_fields = resolution_fields & self.proposed_patch.keys()
        if present_resolution_fields:
            if present_resolution_fields != resolution_fields or self.operation != "SUPERSEDE":
                raise ValueError(
                    "OpenIssue resolution requires SUPERSEDE and all resolution fields"
                )
            try:
                UUID(str(self.proposed_patch["resolve_issue_id"]))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("resolve_issue_id must be a UUID") from exc
            expected_revision = self.proposed_patch["expected_issue_revision"]
            if (
                isinstance(expected_revision, bool)
                or not isinstance(expected_revision, int)
                or expected_revision < 1
            ):
                raise ValueError("expected_issue_revision must be a positive integer")
            addressed = self.proposed_patch["addressed_branches"]
            if not isinstance(addressed, list) or not addressed:
                raise ValueError("addressed_branches must be a non-empty list")
            if any(branch not in {"SUPPORT_BRANCH", "CONTRADICT_BRANCH"} for branch in addressed):
                raise ValueError("addressed_branches contains an unknown branch")
        return self


class ProposalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    decision: Literal["APPROVE", "REJECT"]
    policy_version: str = Field(min_length=1, max_length=255)
    reason_code: str = Field(min_length=1, max_length=255)
