"""Finite, generated schemas for the compact facade; no business State schema."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from milai_mcp.input_contracts import (
    EvidenceSourceContextInput,
    RevocationReasonCode,
    SourceRef,
    SourceType,
    SubjectId,
)
from milai_mcp.memory_search import SearchQuery
from milai_mcp.ordinary_memory import NoteSources, NoteTags, OperationId, Version


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AddNote(Input):
    action: Literal["ADD_NOTE"] = "ADD_NOTE"
    format: Literal["text", "markdown"] = "text"
    tags: NoteTags | None = None
    source_refs: NoteSources | None = None
    observed_at: AwareDatetime | None = None


class UpdateNote(Input):
    action: Literal["UPDATE_NOTE"]
    memory_id: UUID
    expected_version: Version
    format: Literal["text", "markdown"] | None = None
    tags: NoteTags | None = None
    source_refs: NoteSources | None = None


class CaptureEvidence(Input):
    action: Literal["CAPTURE_EVIDENCE"]
    source_type: SourceType
    source_ref: SourceRef
    subject_id: SubjectId
    observed_at: AwareDatetime
    confirmation: Literal["CAPTURE"]
    speaker: Literal["user", "assistant", "system", "tool"] | None = None
    source_context: EvidenceSourceContextInput | None = None


SaveOptions = Annotated[AddNote | UpdateNote | CaptureEvidence, Field(discriminator="action")]


class NoteRead(Input):
    kind: Literal["NOTE"]
    id: UUID
    version: Version | None = None
    offset: int = Field(default=0, ge=0, le=65536)
    length: int = Field(default=8192, ge=1, le=8192)
    source_offset: int = Field(default=0, ge=0, le=1024)
    source_limit: int = Field(default=8, ge=1, le=32)


class EvidenceRead(Input):
    kind: Literal["EVIDENCE"]
    id: UUID
    offset: int = Field(default=0, ge=0)
    length: int = Field(default=8192, ge=1, le=8192)


class ClaimRead(Input):
    kind: Literal["CLAIM"]
    id: UUID
    valid_at: AwareDatetime | None = None
    known_at: AwareDatetime | None = None


ReadTarget = Annotated[NoteRead | EvidenceRead | ClaimRead, Field(discriminator="kind")]


class ListNotes(Input):
    kind: Literal["NOTE"] = "NOTE"
    query: SearchQuery | None = None
    tags: NoteTags | None = None


class ListEvidence(Input):
    kind: Literal["EVIDENCE"]
    source_type: SourceType | None = None
    subject_id: SubjectId | None = None


ListSelection = Annotated[ListNotes | ListEvidence, Field(discriminator="kind")]


class DeleteNote(Input):
    kind: Literal["NOTE"]
    id: UUID
    expected_version: Version
    confirmation: Literal["DELETE"]


class RevokeEvidence(Input):
    kind: Literal["EVIDENCE"]
    id: UUID
    reason_code: RevocationReasonCode
    confirmation: Literal["REVOKE"]


DeleteTarget = Annotated[DeleteNote | RevokeEvidence, Field(discriminator="kind")]


class NoteOperation(Input):
    kind: Literal["NOTE_WRITE"]
    operation_id: OperationId


class EvidenceDeletion(Input):
    kind: Literal["EVIDENCE_DELETION"]
    id: UUID


StatusTarget = Annotated[NoteOperation | EvidenceDeletion, Field(discriminator="kind")]
