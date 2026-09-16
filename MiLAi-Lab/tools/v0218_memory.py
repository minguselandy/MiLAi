"""Thin public Note CRUD transport, preserving exact committed versions and bytes."""

from __future__ import annotations

import hashlib


def content_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def save_note(call, text: str, operation_id: str, previous: dict | None = None) -> dict:
    options = (
        {"action": "ADD_NOTE"}
        if previous is None
        else {
            "action": "UPDATE_NOTE",
            "memory_id": previous["memory_id"],
            "expected_version": previous["version"],
        }
    )
    receipt = call(
        "milai_memory_save", {"content": text, "operation_id": operation_id, "options": options}
    )
    if (
        receipt.get("mcp_error")
        or receipt.get("commit_status") != "COMMITTED"
        or receipt.get("durable") is not True
        or receipt.get("status") != "ACTIVE"
        or receipt.get("authority") != "HOST_WORKING"
        or receipt.get("content_digest") != content_digest(text)
    ):
        raise ValueError("PUBLIC_NOTE_COMMIT_NOT_VERIFIED_NO_AUTOMATIC_RETRY")
    if previous and (
        receipt["memory_id"] != previous["memory_id"]
        or receipt["version"] != previous["version"] + 1
    ):
        raise ValueError("PUBLIC_NOTE_VERSION_NOT_VERIFIED")
    return receipt


def read_note(call, committed: dict) -> dict:
    """Read the pinned Note version with full pagination, never substitute the current head."""
    offset, pieces, pages = 0, [], []
    while True:
        response = call(
            "milai_memory_read",
            {
                "target": {
                    "kind": "NOTE",
                    "id": committed["memory_id"],
                    "version": committed["version"],
                    "offset": offset,
                    "length": 8192,
                }
            },
        )
        if (
            response.get("mcp_error")
            or response.get("status") != "ACTIVE"
            or response.get("authority") != "HOST_WORKING"
            or response.get("memory_id") != committed["memory_id"]
            or response.get("version") != committed["version"]
            or response.get("content_digest") != committed["content_digest"]
            or response.get("offset") != offset
            or not isinstance(response.get("content"), str)
        ):
            raise ValueError("PUBLIC_NOTE_READ_IDENTITY_OR_VERSION_NOT_VERIFIED")
        pieces.append(response["content"])
        pages.append(response)
        next_offset = response.get("next_offset")
        if next_offset is None:
            break
        if type(next_offset) is not int or next_offset <= offset or len(pages) >= 16:
            raise ValueError("PUBLIC_NOTE_PAGINATION_INVALID_OR_LIMIT")
        offset = next_offset
    text = "".join(pieces)
    if content_digest(text) != committed["content_digest"]:
        raise ValueError("PUBLIC_NOTE_EXACT_CONTENT_MISMATCH")
    return {
        "content": text,
        "memory_id": committed["memory_id"],
        "version": committed["version"],
        "content_digest": committed["content_digest"],
        "pages": pages,
        "status": "PUBLIC_EXACT_READ_VERIFIED",
        "presented": False,
    }
