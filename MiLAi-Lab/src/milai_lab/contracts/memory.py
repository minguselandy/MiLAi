"""Static views of existing ordinary-memory dictionaries; no storage conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

GroundingMode = Literal["ref_only", "field_grounded"]


@dataclass(frozen=True)
class VerifiedObjectRef:
    """A trusted application observation; never an authorization or a live-state claim."""

    id: str
    owner: str
    source_ref: str
    external_id: str
    application: str
    fields: dict[str, str]


class SourceEvent(TypedDict):
    """Program-captured input with its original body, separate from semantic formation."""

    event_id: str
    owner: str
    session: str
    role: Literal["user", "tool"]
    origin: str
    content: Any
    content_sha256: str
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
    content_sha256: str
    observed_at: str | None


class MemoryObjectRef(TypedDict):
    """A current ordinary-memory record paired with its actual access receipt."""

    record_id: str
    access_receipt_ref: str
