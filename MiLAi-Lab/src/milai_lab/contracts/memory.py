"""Static views of existing ordinary-memory dictionaries; no storage conversion."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


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
