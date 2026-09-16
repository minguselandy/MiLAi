"""Public Note receipt/version/pagination failures stay failures, not silent head recovery."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0218_memory import content_digest, read_note, save_note


def committed(text="saved text"):
    return {
        "memory_id": "opaque-id",
        "version": 3,
        "content_digest": content_digest(text),
        "status": "ACTIVE",
        "authority": "HOST_WORKING",
        "durable": True,
        "commit_status": "COMMITTED",
    }


def test_exact_read_uses_committed_version_and_preserves_unicode():
    text = "版本\n" * 4000
    receipt = committed(text)

    def public(_tool, arguments):
        target = arguments["target"]
        assert target["version"] == 3
        start = target["offset"]
        end = min(start + 8192, len(text))
        return {
            **receipt,
            "content": text[start:end],
            "offset": start,
            "next_offset": end if end < len(text) else None,
        }

    result = read_note(public, receipt)
    assert result["content"] == text and len(result["pages"]) == 2
    assert not result["presented"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 4),
        ("status", "DELETED"),
        ("authority", "CANONICAL"),
        ("memory_id", "other"),
        ("content_digest", "other"),
        ("offset", 5),
        ("content", None),
        ("mcp_error", True),
    ],
)
def test_bad_read_receipt_never_returns_text(field, value):
    receipt = committed()
    response = {**receipt, "content": "saved text", "offset": 0, "next_offset": None, field: value}
    with pytest.raises(ValueError, match="NOT_VERIFIED"):
        read_note(lambda *_: response, receipt)


def test_missing_bytes_and_nonprogress_pagination_fail():
    receipt = committed()
    response = {**receipt, "content": "saved", "offset": 0, "next_offset": None}
    with pytest.raises(ValueError, match="MISMATCH"):
        read_note(lambda *_: response, receipt)
    response["next_offset"] = 0
    with pytest.raises(ValueError, match="PAGINATION"):
        read_note(lambda *_: response, receipt)


@pytest.mark.parametrize(
    "field,value",
    [
        ("durable", False),
        ("commit_status", "UNKNOWN"),
        ("content_digest", "bad"),
        ("mcp_error", True),
    ],
)
def test_unknown_commit_stops_without_retry(field, value):
    calls = []

    def public(tool, arguments):
        calls.append((tool, arguments))
        return {**committed(), field: value}

    with pytest.raises(ValueError, match="COMMIT_NOT_VERIFIED"):
        save_note(public, "saved text", "operation")
    assert len(calls) == 1


def test_update_binds_prior_id_and_version():
    previous = committed()

    def public(_tool, arguments):
        assert arguments["options"] == {
            "action": "UPDATE_NOTE",
            "memory_id": "opaque-id",
            "expected_version": 3,
        }
        return {**committed("new"), "version": 4}

    assert save_note(public, "new", "operation", previous)["version"] == 4
