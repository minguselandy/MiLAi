"""Static views of existing ordinary-memory dictionaries; no storage conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

GroundingMode = Literal["ref_only", "field_grounded"]

RECEIPT_PROFILES: dict[str, dict[str, Any]] = {
    "reservation_v1": {
        "application": "ApplicationWorld.reservation",
        "fields": {"status": "string", "label_status": "string"},
    },
    "document_publication_v1": {
        "application": "ApplicationWorld.document",
        "fields": {
            "status": "string",
            "document_version": "integer",
            "approval_status": "string",
            "approved_version": "integer",
            "publication_status": "string",
            "published_version": "integer",
            "audience": "string",
        },
    },
}


@dataclass(frozen=True)
class VerifiedObjectRef:
    """A trusted application observation; never an authorization or a live-state claim."""

    id: str
    owner: str
    source_ref: str
    external_id: str
    application: str
    fields: dict[str, str | int]


class SourceEvent(TypedDict):
    """Program-captured input with its original body, separate from semantic formation."""

    event_id: str
    owner: str
    session: str
    # Assistant capture is available only in opt-in event_bound_v1; historical
    # user/tool events keep their original dictionaries and identity bytes.
    role: Literal["user", "tool", "assistant"]
    origin: str
    content: Any
    source_revision: int
    capture_key: NotRequired[str]
    observed_at: str
    object_ref: dict[str, Any] | None


class MemoryRecord(TypedDict):
    """Material read from the Store or the MCP records resource."""

    id: str
    value: dict[str, Any]


class MemoryMutationReceipt(TypedDict):
    """Decoded strict CRUD receipt; invalid arguments can omit the target ID."""

    ok: bool
    status: str
    id: NotRequired[str]
    reason: NotRequired[str]


class MemoryReadResult(TypedDict):
    """Decoded exact-read receipt; a missing record has no value field."""

    ok: bool
    status: str
    id: str
    value: NotRequired[dict[str, Any]]


class MemorySourceRef(TypedDict):
    """An observed checkpoint event, without a claim of semantic support."""

    id: str
    kind: str
    checkpoint_position: int
    message_id: str | None
    source_revision: int
    observed_at: str | None


class MemoryObjectRef(TypedDict):
    """A current ordinary-memory record paired with its actual access receipt."""

    record_id: str
    access_receipt_ref: str


class CandidateBinding(TypedDict):
    """Opt-in server-issued read-time handle payload, never a live application ref."""

    owner: str
    namespace: list[str]
    record_id: str
    revision: int
    support_sources: list[dict[str, Any]]


@dataclass(frozen=True)
class ObservationField:
    """Public field mapping; an ordered version domain is declared per field."""

    name: str
    path: tuple[str, ...]
    dtype: Literal["string", "integer", "boolean", "number", "json"]
    version_domain: str | None = None
    allow_null_clear: bool = False


@dataclass(frozen=True)
class ObservationProfile:
    """A trusted adapter contract, without task plans, gold or hidden-world routing."""

    profile_id: str
    adapter_version: str
    application: str
    origins: tuple[str, ...]
    object_id_path: tuple[str, ...]
    fields: tuple[ObservationField, ...]
    objects_path: tuple[str, ...] = ()
    owner_path: tuple[str, ...] | None = None
    resource_version_path: tuple[str, ...] | None = None
    resource_version_type: Literal["integer", "opaque"] = "opaque"
    valid_time_path: tuple[str, ...] | None = None
    completeness: Literal["partial", "complete"] = "partial"
    unknown_path: tuple[str, ...] = ("status",)
    unknown_values: tuple[str, ...] = ("ORIGINAL_CALL_OUTCOME_UNKNOWN",)
