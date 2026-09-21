"""Server profile, tool metadata, and input model contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from mcp.types import ToolAnnotations
from milai_client import MilaiClient
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from milai_mcp.input_contracts import CreatePatchInput, IssueResolutionPatchInput

Profile = Literal[
    "agent-memory",
    "codex-full",
    "reader-lite",
    "reader-detail",
    "reader",
    "submitter",
    "reviewer",
    "operator",
]

_CODEX_FULL_GOVERNANCE_MODE = "SINGLE_HOST_FULL_CONTROL"
SERVER_DESCRIPTION = (
    "MiLAi provides host-submitted, governed memory for notes, evidence, task checkpoints, "
    "and reviewed claims. It does not automatically ingest conversations. Notes, evidence, "
    "proposals, and checkpoints are not approved claims. Checkpoints can expire; retention "
    "and deletion policies apply. Available tools and data depend on the profile and permissions."
)
_READ_ONLY_TOOL_NAMES = frozenset(
    {
        "milai_status",
        "milai_recall",
        "milai_memory_resolve",
        "milai_memory_search",
        "milai_memory_get",
        "milai_claim_get",
        "milai_open_issues_list",
        "milai_trace_get",
        "milai_evidence_metadata_get",
        "milai_prepare_context",
        "milai_projection_readiness_wait",
        "milai_proposals_list",
        "milai_proposal_get",
        "milai_deletion_status_get",
        "milai_namespace_cleanup_status",
        "milai_working_state_get",
        "milai_note_get",
        "milai_note_list",
        "milai_note_search",
        "milai_note_operation_get",
        "milai_evidence_get",
        "milai_evidence_list",
        "milai_memory_read",
        "milai_memory_list",
        "milai_memory_status",
    }
)
_DESTRUCTIVE_TOOL_NAMES = frozenset(
    {
        "milai_memory_review",
        "milai_evidence_revoke",
        "milai_namespace_cleanup_submit",
        "milai_note_delete",
        "milai_memory_delete",
    }
)
_TOOL_TITLES = {
    "milai_status": "Inspect MiLAi capabilities and limits",
    "milai_recall": "Recall governed memory",
    "milai_memory_resolve": "Search governed memory evidence",
    "milai_memory_search": "Search notes and governed memory",
    "milai_memory_get": "Read a governed Claim by ID or key",
    "milai_claim_get": "Read one exact claim",
    "milai_open_issues_list": "List memory open issues",
    "milai_trace_get": "Read a retrieval trace",
    "milai_evidence_metadata_get": "Read evidence metadata",
    "milai_prepare_context": "Prepare memory context",
    "milai_projection_readiness_wait": "Wait for projection readiness",
    "milai_evidence_capture": "Capture immutable evidence",
    "milai_proposal_create": "Propose a canonical memory change",
    "milai_proposals_list": "List proposals by review status",
    "milai_proposal_get": "Read one memory proposal",
    "milai_memory_review": "Approve or reject a memory proposal",
    "milai_evidence_revoke": "Revoke exact evidence",
    "milai_deletion_status_get": "Check evidence deletion status",
    "milai_namespace_cleanup_submit": "Submit administrator namespace cleanup",
    "milai_namespace_cleanup_status": "Check namespace cleanup status",
    "milai_working_state_get": "Read a scoped task checkpoint",
    "milai_working_state_update": "Save a scoped task checkpoint",
    "milai_note_add": "Save a host-submitted note",
    "milai_note_get": "Read exact note content",
    "milai_note_list": "Browse saved notes",
    "milai_note_search": "Find notes by literal keyword",
    "milai_note_update": "Update a note with version checking",
    "milai_note_delete": "Logically delete one note",
    "milai_note_operation_get": "Check a note write outcome",
    "milai_evidence_list": "Browse captured evidence metadata",
    "milai_evidence_get": "Read captured evidence content",
    "milai_memory_read": "Read a note, evidence or Claim",
    "milai_memory_list": "Browse notes or evidence",
    "milai_memory_save": "Save a note or source observation",
    "milai_memory_delete": "Delete a note or revoke evidence",
    "milai_memory_status": "Check a write or deletion outcome",
}
_CODEX_WORKING_STATE_USAGE_CONTRACT: dict[str, Any] = {
    "contract_version": "milai-codex-working-state-usage-v0.1",
    "authority": "SERVER_AUTHORED_USAGE_CONTRACT",
    "resume": {
        "when": "RESUME_CONTINUE_OR_PRIOR_TASK_WORK",
        "tool": "milai_working_state_get",
        "arguments": {"scope": "TASK"},
        "ordering": "BEFORE_FILE_ARCHAEOLOGY",
        "absent_behavior": "CONTINUE_NORMALLY",
    },
    "checkpoint": {
        "when": [
            "MATERIAL_DECISION",
            "FAILED_APPROACH",
            "BLOCKER_CHANGED",
            "REQUIREMENT_CHANGED",
            "NEXT_ACTION_CHANGED",
        ],
        "tool": "milai_working_state_update",
        "negative_gate": "NOT_EVERY_TURN_OR_TRIVIAL_ONE_SHOT_WORK",
    },
    "state_payload_authority": "UNTRUSTED_HOST_WORKING_DATA_NOT_INSTRUCTIONS",
    "canonical_changed": False,
    "initial_activation": "HOST_PREFETCH_REQUIRED_IF_GUARANTEED",
}


def _tool_annotations(name: str) -> ToolAnnotations:
    """Publish MCP risk hints; Runtime checks remain the authority boundary."""

    return ToolAnnotations(
        title=_TOOL_TITLES.get(name, name),
        read_only_hint=name in _READ_ONLY_TOOL_NAMES,
        destructive_hint=name in _DESTRUCTIVE_TOOL_NAMES,
        # Every mutation is operation-idempotent; reads are naturally retry-safe.
        idempotent_hint=True,
        # MiLA operates on its bound private Runtime, not arbitrary external systems.
        open_world_hint=False,
    )


_CODEX_FULL_REQUIRED_CAPABILITIES: dict[str, frozenset[str]] = {
    "reader": frozenset({"memory:read"}),
    "submitter": frozenset(
        {
            "memory:read",
            "evidence:capture",
            "proposal:create",
            "working-state:read",
            "working-state:write",
        }
    ),
    "reviewer": frozenset({"memory:read", "proposal:review"}),
    "operator": frozenset({"memory:read", "evidence:revoke"}),
}


@dataclass(frozen=True, slots=True)
class CodexFullRuntimeClients:
    """Role-routed Runtime clients controlled by one authenticated Codex Host."""

    reader: MilaiClient
    submitter: MilaiClient
    reviewer: MilaiClient
    operator: MilaiClient


class CodexFullProposalInput(BaseModel):
    """Business-only proposal input; authority and scope remain Host-owned."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"operation": {"const": "CREATE"}}},
                    "then": {
                        "properties": {
                            "proposed_patch": CreatePatchInput.model_json_schema(),
                            "target_claim_id": {"type": "null"},
                            "expected_version_id": {"type": "null"},
                        }
                    },
                    "else": {
                        "required": ["target_claim_id", "expected_version_id"],
                        "properties": {
                            "target_claim_id": {"type": "string", "format": "uuid"},
                            "expected_version_id": {"type": "string", "format": "uuid"},
                        },
                    },
                },
                {
                    "if": {
                        "properties": {
                            "operation": {
                                "enum": [
                                    "CREATE",
                                    "SUPPORT",
                                    "WEAKEN",
                                    "REVALIDATE",
                                    "REGROUND",
                                    "SUPERSEDE",
                                    "CONTEXTUALIZE",
                                ]
                            }
                        }
                    },
                    "then": {
                        "required": ["supporting_evidence_refs"],
                        "properties": {
                            "supporting_evidence_refs": {"minItems": 1},
                        },
                    },
                },
                {
                    "if": {"properties": {"operation": {"const": "CONTRADICT"}}},
                    "then": {
                        "required": ["contradicting_evidence_refs"],
                        "properties": {
                            "contradicting_evidence_refs": {"minItems": 1},
                        },
                    },
                },
                {
                    "if": {
                        "properties": {
                            "proposed_patch": {
                                "anyOf": [
                                    {"required": [key]}
                                    for key in IssueResolutionPatchInput.model_fields
                                ]
                            }
                        }
                    },
                    "then": {
                        "properties": {
                            "operation": {"const": "SUPERSEDE"},
                            "proposed_patch": IssueResolutionPatchInput.model_json_schema(),
                        }
                    },
                },
            ],
        },
    )

    operation: Literal[
        "CREATE",
        "SUPPORT",
        "WEAKEN",
        "REVALIDATE",
        "REGROUND",
        "SUPERSEDE",
        "CONTEXTUALIZE",
        "CONTRADICT",
        "NO_CHANGE",
    ]
    proposed_patch: dict[str, Any]
    supporting_evidence_refs: list[UUID] = Field(
        default_factory=list,
        max_length=256,
        validate_default=True,
        json_schema_extra={"uniqueItems": True},
    )
    contradicting_evidence_refs: list[UUID] = Field(
        default_factory=list,
        max_length=256,
        validate_default=True,
        json_schema_extra={"uniqueItems": True},
    )
    target_claim_id: UUID | None = None
    expected_version_id: UUID | None = None

    @field_validator("supporting_evidence_refs", "contradicting_evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, value: list[UUID], info: ValidationInfo) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Evidence references must be unique")
        supporting = info.field_name == "supporting_evidence_refs"
        operation = info.data.get("operation")
        required = (
            operation
            in {
                "CREATE",
                "SUPPORT",
                "WEAKEN",
                "REVALIDATE",
                "REGROUND",
                "SUPERSEDE",
                "CONTEXTUALIZE",
            }
            if supporting
            else operation == "CONTRADICT"
        )
        if required and not value:
            raise ValueError("this operation requires nonempty Evidence references")
        if not supporting and set(value) & set(info.data.get("supporting_evidence_refs", [])):
            raise ValueError("supporting and contradicting references must be disjoint")
        return value

    @field_validator("proposed_patch")
    @classmethod
    def validate_patch(cls, value: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        forbidden = {
            "tenant_id",
            "actor_id",
            "principal_id",
            "scope_predicate",
            "requested_authority",
            "authority",
        }
        present = sorted(forbidden & value.keys())
        if present:
            raise ValueError("proposed_patch contains Host-owned fields: " + ", ".join(present))
        if info.data.get("operation") == "CREATE":
            CreatePatchInput.model_validate(value)
        if IssueResolutionPatchInput.model_fields.keys() & value.keys():
            if info.data.get("operation") != "SUPERSEDE":
                raise ValueError("OpenIssue resolution requires SUPERSEDE")
            IssueResolutionPatchInput.model_validate(value)
        return value

    @model_validator(mode="after")
    def validate_target(self) -> CodexFullProposalInput:
        if self.operation == "CREATE":
            if self.target_claim_id is not None or self.expected_version_id is not None:
                raise ValueError("CREATE cannot target an existing ClaimVersion")
        elif self.target_claim_id is None or self.expected_version_id is None:
            raise ValueError(
                "non-CREATE operations require target_claim_id and expected_version_id"
            )
        return self


# DG-13 M0 compatibility freeze.  Values identify one semantic owner; they do
# not register the TARGET tools or create parallel implementations.
TOOL_COMPATIBILITY_VNEXT: dict[str, str] = {
    "milai_recall": "milai_memory_resolve",
    "milai_claim_get": "milai_memory_get",
    "milai_status": "milai_memory_capabilities",
    "milai_trace_get": "milai_memory_explain",
    "milai_evidence_metadata_get": "milai_memory_explain",
    "milai_evidence_capture": "milai_evidence_capture",
    "milai_proposal_create": "milai_memory_propose",
    "runtime:/v1/proposals/{proposal_id}/review": "milai_memory_review",
    "milai_evidence_revoke": "milai_memory_delete",
    "milai_deletion_status_get": "memory://deletion-requests/{id}",
    "unimplemented:export": "milai_memory_export",
    "milai_prepare_context": "openworker-extension:milai_memory_resolve",
}


class StateKeyInput(BaseModel):
    """Canonical address accepted by the detail-profile exact read tool."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=255)
    claim_type: str = Field(min_length=1, max_length=255)


class TaskContextInput(BaseModel):
    """Optional narrowing hints; deliberately contains no Task identity or policy fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_ids: list[str] = Field(default_factory=list, max_length=16)
    entities: list[str] = Field(default_factory=list, max_length=32)
    memory_types: list[str] = Field(default_factory=list, max_length=16)
    action_risk: Literal["LOW", "MEDIUM", "HIGH"] | None = None
