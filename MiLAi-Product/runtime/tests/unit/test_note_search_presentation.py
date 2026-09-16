from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from milai.application.host_note import HostNoteService
from milai.domain.host_note import NoteBrowse


def browse(content, query=None):
    row = {
        "memory_id": uuid4(), "version": 1, "created_at": datetime.now(UTC),
        "body": {"content": content, "source_refs": [],
                 "recorded_at": "2026-09-08T00:00:00Z", "observed_at": None},
    }
    repository = SimpleNamespace(browse=lambda *a, **k: ([row], "2026-09-08T01:00:00Z"))
    service = HostNoteService(repository, "synthetic-note-cursor-key-for-unit-tests")
    request = NoteBrowse(principal_binding_digest="a" * 64, project_id="private-one", query=query)
    return service.browse(SimpleNamespace(tenant_id=uuid4(), actor_id=uuid4()), request)


@pytest.mark.parametrize("prefix,query,hit", [
    ("unrelated material " * 80, "会议", "会议不在本周举行"),
    ("İ" * 300, "meeting", "MEETING is next month, not this week"),
    ("prefix " * 100, "a.b[1]", "a.b[1] is a literal phrase"),
], ids=["chinese-late-match", "unicode-original-offset", "literal-not-regex"])
def test_search_snippet_contains_late_literal_match_and_exact_offsets(prefix, query, hit):
    content = prefix + hit + " end " * 100
    result = browse(content, query)
    item = result["items"][0]
    assert hit in item["snippet"]
    assert len(item["snippet"]) <= 256
    assert content[item["snippet_offset"]:item["snippet_end"]] == item["snippet"]
    assert item["match_in_snippet"] is True
    assert item["read_arguments"]["version"] == 1
    assert item["recorded_at"] == "2026-09-08T00:00:00Z"
    assert item["observed_at"] is None
    assert result["absence_confirmed"] is False
    assert result["search_scope"]["object_types"] == ["HOST_NOTE"]


def test_browse_still_uses_prefix_and_does_not_invent_a_query_match():
    content = "begin " + "x" * 500
    result = browse(content)
    item = result["items"][0]
    assert item["snippet"] == content[:256]
    assert item["snippet_offset"] == 0
    assert item["match_in_snippet"] is False
    assert result["search_scope"]["mode"] == "BROWSE"


def test_unmatched_projection_does_not_invent_match_or_history_absence():
    result = browse("a permitted row", "absent phrase")
    assert result["items"][0]["match_in_snippet"] is False
    assert result["absence_confirmed"] is False


def test_long_query_snippet_explicitly_remains_partial():
    query = "long literal " * 40
    item = browse("prefix " * 100 + query, query)["items"][0]
    assert len(item["snippet"]) <= 256
    assert item["snippet_only"] is True
    assert item["match_complete"] is False
