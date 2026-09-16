"""Public Evidence input constraints, mirrored from the Runtime ingress boundary.

Keep free-form content untouched. These models contain no identity or authority.
"""

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

SourceType = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                           pattern=r"^[A-Z][A-Z0-9_]*$")
]
SourceRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]
SubjectId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
EvidenceContent = Annotated[str, StringConstraints(strip_whitespace=False, min_length=1)]
RevocationReasonCode = Literal[
    "USER_REQUEST", "SOURCE_REMOVED", "PERMISSION_REVOKED", "RETENTION_EXPIRED", "CORRECTION",
]


class EvidenceSourceContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: SubjectId
    turn_id: SubjectId
    turn_ordinal: int = Field(ge=0)
    round_id: SubjectId
    round_ordinal: int = Field(ge=0)
    previous_turn_id: SubjectId | None = None
    next_turn_id: SubjectId | None = None

    @model_validator(mode="after")
    def validate_adjacency(self) -> Self:
        if self.turn_id in {self.previous_turn_id, self.next_turn_id}:
            raise ValueError("a source turn cannot be adjacent to itself")
        if self.previous_turn_id is not None and self.previous_turn_id == self.next_turn_id:
            raise ValueError("previous and next source turns must be distinct")
        return self


class EvidenceCaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=1)
    source_type: SourceType
    source_ref: SourceRef
    subject_id: SubjectId
    observed_at: AwareDatetime
    content: EvidenceContent
    confirmation: Literal["CAPTURE"]
    speaker: Literal["user", "assistant", "system", "tool"] | None = None
    source_context: EvidenceSourceContextInput | None = None


class CreatePatchInput(BaseModel):
    """Canonical envelope only; business payload and optional patch fields stay open."""

    model_config = ConfigDict(extra="allow")

    subject_id: SubjectId
    predicate: str = Field(min_length=1, max_length=255)
    claim_type: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any]
    confidence: float = Field(ge=0, le=1)


class IssueResolutionPatchInput(BaseModel):
    """Optional SUPERSEDE resolution envelope; unrelated business fields stay open."""

    model_config = ConfigDict(extra="allow")

    resolve_issue_id: UUID
    expected_issue_revision: int = Field(ge=1, strict=True)
    addressed_branches: list[Literal["SUPPORT_BRANCH", "CONTRADICT_BRANCH"]] = Field(min_length=1)


def safe_validation_fields(
    issues: Sequence[Mapping[str, Any]], *, working_state: bool = False, compact: bool = False,
) -> list[dict[str, str]]:
    """Keep field locations and fixed guidance; never copy input, msg, or ctx."""
    expected = {
        "source_type": "uppercase identifier matching ^[A-Z][A-Z0-9_]*$; length 1..64",
        "source_ref": "non-empty source locator; length 1..2048",
        "subject_id": "non-empty business identifier; length 1..512 (not an OAuth subject)",
        "observed_at": "date-time with an explicit timezone",
        "content": "non-empty string; whitespace preserved; Notes allow at most 65536 UTF-8 bytes",
        "source_context": "complete source turn/round context; distinct non-self neighbours",
        "turn_ordinal": "integer >= 0",
        "round_ordinal": "integer >= 0",
        "operation_id": "non-empty stable operation identifier",
        "confirmation": "the declared confirmation literal",
        "speaker": "user, assistant, system, tool, or null",
        "proposal": "CREATE needs a complete patch; other operations need target and version",
        "proposed_patch": "CREATE requires subject_id, predicate, claim_type, payload, confidence",
        "predicate": "non-empty predicate; length 1..255",
        "claim_type": "non-empty claim type; length 1..255",
        "payload": (
            "Working State JSON object; max 65536 canonical UTF-8 bytes, "
            "at most 1024 distinct reserved Evidence UUID references"
        ) if working_state else "business JSON object",
        "confidence": "number in 0..1",
        "target_claim_id": "existing Claim ID; required for non-CREATE operations",
        "expected_version_id": "expected Claim version; required for non-CREATE operations",
        "supporting_evidence_refs": (
            "unique Evidence UUIDs, max 256; nonempty for version operations"
        ),
        "contradicting_evidence_refs": (
            "unique Evidence UUIDs, max 256; disjoint from support; nonempty for CONTRADICT"
        ),
        "resolve_issue_id": "OpenIssue UUID; resolution requires SUPERSEDE and all three fields",
        "expected_issue_revision": "positive integer current OpenIssue revision",
        "addressed_branches": "nonempty list of SUPPORT_BRANCH or CONTRADICT_BRANCH",
        "operation": "declared proposal operation",
        "memory_id": "Note UUID returned by add/list/search",
        "expected_version": (
            "Note: integer >= 1; Working State: 0 without state_id for create, "
            "positive current version with state_id for update"
        ),
        "state_id": "Working State UUID from the same scope GET; omit only with expected_version=0",
        "scope": "SESSION, TASK (default), or PROJECT; preserve the intended binding",
        "version": "integer >= 1",
        "tags": "at most 32 unique strings; each length 1..128",
        "format": "text or markdown",
        "source_refs": "at most 1024 typed Evidence or versioned file references",
        "kind": "EVIDENCE or FILE",
        "evidence_id": "Evidence UUID",
        "locator": "source file locator; length 1..2048",
        "revision": "source file revision; length 1..512",
        "content_digest": "sha256: followed by 64 lowercase hex digits",
        "cursor": "cursor returned for the same authenticated scope and filter",
        "limit": "integer 1..100",
        "offset": "nonnegative content character offset",
        "length": "integer 1..8192",
        "source_offset": "integer 0..1024",
        "source_limit": "integer 1..32",
    }
    identifiers = {"session_id", "turn_id", "round_id", "previous_turn_id", "next_turn_id"}
    allowed = set(expected) | identifiers
    if compact:
        expected.update({
            "options": "typed save options; omit for a new Note",
            "action": "ADD_NOTE, UPDATE_NOTE or CAPTURE_EVIDENCE; Evidence cannot be updated",
            "target": "typed exact target matching the declared operation schema",
            "selection": "NOTE or EVIDENCE browse selection with type-specific filters",
            "kind": "the kind allowed by this tool's selected target/selection schema",
            "id": "exact UUID of the declared Note, Evidence or Claim, never an inferred type",
            "reason_code": "USER_REQUEST, SOURCE_REMOVED, PERMISSION_REVOKED, "
                           "RETENTION_EXPIRED or CORRECTION",
        })
        allowed |= set(expected) | {
            "ADD_NOTE", "UPDATE_NOTE", "CAPTURE_EVIDENCE", "NOTE", "EVIDENCE", "CLAIM",
            "NOTE_WRITE", "EVIDENCE_DELETION",
        }
    fields = []
    for issue in issues[:32]:
        raw_path = issue.get("loc", ())
        if not raw_path and isinstance(issue.get("path"), str):
            raw_path = issue["path"].split(".")
        path = [str(part) if isinstance(part, int) and part >= 0 else
                part if isinstance(part, str) and part in allowed else "<field>"
                for part in raw_path]
        leaf = next((part for part in reversed(path) if part in allowed), "")
        constraint = str(issue.get("type", "invalid_argument"))
        # Only Pydantic's code vocabulary, never arbitrary backend strings.
        if constraint not in {
            "missing", "string_type", "string_too_short", "string_too_long",
            "string_pattern_mismatch", "datetime_parsing", "datetime_from_date_parsing",
            "timezone_aware", "int_parsing", "int_type", "greater_than_equal",
            "literal_error", "extra_forbidden", "model_type", "value_error",
            "union_tag_invalid", "union_tag_not_found",
            "float_parsing", "less_than_equal", "dict_type", "uuid_parsing", "uuid_type",
            "too_short", "too_long",
        }:
            constraint = "invalid_argument"
        fields.append({
            "path": ".".join(path),
            "type": constraint[:64],
            "expected": expected.get(
                leaf, "non-empty source identifier; length 1..512"
                if leaf in identifiers else "value matching the public schema",
            ),
        })
    return fields


CAPTURE_EXAMPLE = {
    "operation_id": "capture-example-001",
    "source_type": "AGENT_TURN",
    "source_ref": "manual://mcp-example/turn-1",
    "subject_id": "example-subject",
    "observed_at": "2026-09-08T00:00:00Z",
    "content": "Synthetic example: runtime.port is 6432.",
    "confirmation": "CAPTURE",
}

CREATE_EXAMPLE = {
    "operation_id": "proposal-example-001",
    "proposal": {
        "operation": "CREATE",
        "supporting_evidence_refs": ["00000000-0000-4000-8000-000000000001"],
        "proposed_patch": {
            "subject_id": "example-subject",
            "predicate": "runtime.port",
            "claim_type": "FACT",
            "payload": {"port": 6432},
            "confidence": 0.99,
        },
    },
    "confirmation": "SUBMIT",
}

# Executable synthetic envelopes, not permission to submit or review a Proposal.
PROPOSAL_EXAMPLES = {"CREATE": CREATE_EXAMPLE}
for _operation in (
    "SUPPORT", "WEAKEN", "REVALIDATE", "REGROUND", "SUPERSEDE", "CONTEXTUALIZE",
    "CONTRADICT", "NO_CHANGE",
):
    PROPOSAL_EXAMPLES[_operation] = {
        "operation_id": "proposal-example-" + _operation.lower(),
        "proposal": {
            "operation": _operation,
            "target_claim_id": "00000000-0000-4000-8000-000000000002",
            "expected_version_id": "00000000-0000-4000-8000-000000000003",
            "proposed_patch": {},
            **({"contradicting_evidence_refs": ["00000000-0000-4000-8000-000000000001"]}
               if _operation == "CONTRADICT" else {} if _operation == "NO_CHANGE" else
               {"supporting_evidence_refs": ["00000000-0000-4000-8000-000000000001"]}),
        },
        "confirmation": "SUBMIT",
    }


class NoteEvidenceSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["EVIDENCE"]
    evidence_id: UUID


class NoteFileSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "anyOf": [
            {"required": ["revision"], "properties": {"revision": {"type": "string"}}},
            {"required": ["content_digest"],
             "properties": {"content_digest": {"type": "string"}}},
        ],
    })
    kind: Literal["FILE"]
    locator: str = Field(min_length=1, max_length=2048)
    revision: str | None = Field(default=None, min_length=1, max_length=512)
    content_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def stable_reference(self) -> Self:
        if self.revision is None and self.content_digest is None:
            raise ValueError("file source requires revision or content_digest")
        return self


NoteSourceInput = Annotated[
    NoteEvidenceSourceInput | NoteFileSourceInput, Field(discriminator="kind"),
]
