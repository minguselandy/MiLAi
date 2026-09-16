"""Non-canonical, independent Host notes. Content has no business schema."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_NOTE_BYTES = 65_536
NoteFormat = Literal["text", "markdown"]
Tag = Annotated[str, Field(min_length=1, max_length=128)]


class NoteBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_binding_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(min_length=1, max_length=512)


class EvidenceNoteSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["EVIDENCE"]
    evidence_id: UUID


class FileNoteSource(BaseModel):
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


NoteSource = Annotated[EvidenceNoteSource | FileNoteSource, Field(discriminator="kind")]


class NoteWrite(NoteBinding):
    operation: Literal["ADD", "UPDATE", "DELETE"]
    memory_id: UUID | None = None
    expected_version: int = Field(default=0, ge=0)
    content: str | None = Field(default=None, min_length=1)
    format: NoteFormat | None = None
    tags: list[Tag] | None = Field(default=None, max_length=32)
    source_refs: list[NoteSource] | None = Field(default=None, max_length=1024)
    observed_at: AwareDatetime | None = None

    @field_validator("content")
    @classmethod
    def bounded_content(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > MAX_NOTE_BYTES:
            raise ValueError("content exceeds 65536 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def valid_operation(self) -> Self:
        if self.operation == "ADD":
            if self.memory_id is not None or self.expected_version != 0:
                raise ValueError("ADD requires no memory_id and expected_version=0")
        elif self.memory_id is None or self.expected_version < 1:
            raise ValueError("UPDATE/DELETE require memory_id and expected_version >= 1")
        if self.operation == "DELETE":
            if self.model_fields_set & {"content", "format", "tags", "source_refs", "observed_at"}:
                raise ValueError("DELETE accepts identity and version only")
        elif self.content is None:
            raise ValueError("ADD/UPDATE require content")
        if self.tags is not None and len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must be unique")
        return self


class NoteGet(NoteBinding):
    memory_id: UUID
    version: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0, le=MAX_NOTE_BYTES)
    length: int = Field(default=8192, ge=1, le=8192)
    source_offset: int = Field(default=0, ge=0, le=1024)
    source_limit: int = Field(default=8, ge=1, le=32)


class NoteBrowse(NoteBinding):
    query: str | None = Field(default=None, min_length=1, max_length=2048)
    tags: list[Tag] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)


class NoteOperationGet(NoteBinding):
    operation_id: str = Field(min_length=1, max_length=128)
