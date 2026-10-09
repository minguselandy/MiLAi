"""Exact Reader metadata sharing and actual SQLite page/delivery boundaries."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import ToolMessage
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional_state import canonical, namespace
from milai_lab.memory.reader_projection import (
    PROJECTION_INSTRUCTIONS,
    expand_host_packet,
    project_host_packet,
)
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.functional_edit_memory import FunctionalEditMemory


def _tokens(text: str) -> int:
    # A portable mechanical counter. The closed-artifact Qwen probe separately
    # verifies the production 8192-token boundary with its actual tokenizer.
    return (len(text) + 3) // 4


@pytest.fixture
def saved_memory(tmp_path: Path) -> Iterator[tuple[FunctionalEditMemory, dict[str, Any], str]]:
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(
            store, ("reader-projection", "alice"), "alice", tmp_path / "memory.lock",
            functional_contract="functional_v1", memory_profile="unified_v1",
            clock=lambda: datetime(2030, 1, 2, 12, 30, tzinfo=UTC),
        )
        memory = FunctionalEditMemory(
            service, _tokens, interface_version="I2", memory_view_mode="state_driven",
            material_limit=100000, fragment_chars=128,
            features=EditFeatures(source_metadata=True, temporal_scope=True),
            query_time="2030-01-03", query_calendar_context="Asia/Shanghai",
        )
        text = (
            "The club meets three times per week. Only during this quarter. "
            "Give one day's notice. No separate district counts are declared. "
            "Currently no separate count is stipulated.\n"
        ) * 10
        capture = service.capture_user("visit", "save", text)
        memory.context("visit", "save", "a" * 64)
        config = {"configurable": {
            "user_id": "alice", "v13_session": "visit", "v13_turn_id": "save",
            "v13_config_version": "a" * 64,
        }}
        handles = [part["fragment_handle"] for part in service.source_fragments(
            capture["source_ref"], max_chars=128,
        )]
        assertion = {
            "kind": "reported", "source_ref": capture["source_ref"], "source_revision": 1,
            "role": "user", "occurred_at": None, "observed_at": "2030-01-02T12:30:00+00:00",
            "calendar_context": None,
        }
        saved = memory.save_edit(
            config, "save-operation",
            units=[
                {"text": "The club meets three times per week.", "role": "content",
                 "evidence": handles},
                {"text": "Only during this quarter.", "role": "condition", "evidence": handles},
                {"text": "Give one day's notice.", "role": "condition", "evidence": handles},
                {"text": "No separate district counts are declared.", "role": "content",
                 "evidence": handles},
                {"text": "Currently no separate count is stipulated.", "role": "condition",
                 "evidence": handles},
            ],
            relations=[
                {"source": 1, "relation_type": "modifies", "target": 0, "evidence": handles},
                {"source": 2, "relation_type": "modifies", "target": 0, "evidence": handles},
                {"source": 4, "relation_type": "modifies", "target": 3, "evidence": handles},
            ],
            _edit_metadata={
                "unit_assertions": [copy.deepcopy(assertion) for _ in range(5)],
                "revision_evidence": handles,
            },
        )
        assert saved["ok"]
        query = service.capture_user("query", "read", "Read the club's saved arrangement.")
        service.bind_public_turn(
            "query", "read", query["source_ref"], config_version="a" * 64, phase="start",
        )
        config = {"configurable": {
            "user_id": "alice", "v13_session": "query", "v13_turn_id": "read",
            "v13_config_version": "a" * 64,
        }}
        yield memory, config, saved["id"]


def test_sqlite_page_counts_full_projection_and_keeps_all_five_semantic_units(
    saved_memory: tuple[FunctionalEditMemory, dict[str, Any], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory, config, record_id = saved_memory
    before = memory.service.read(record_id)
    units = memory._record_units(before)
    assert len(units) == 5
    memory.material_limit = memory.policy["material_limit"] = 8192
    bound = memory._binding(config)
    snapshot = memory._snapshot(bound, units, "record_read")
    with monkeypatch.context() as legacy_cost:
        legacy_cost.setattr(memory, "_project_read_packet", lambda packet: packet)
        expanded_page = memory._page(snapshot, 0, bound)
    assert expanded_page["delivered_units"] < 5
    page = memory._page(snapshot, 0, bound)
    assert page["delivered_units"] == page["total_units"] == 5
    assert page["delivery_status"] == "complete_snapshot"
    assert page["omitted_units"] == 0 and page["next_cursor"] is None
    assert _tokens(canonical(page)) <= 8192
    assert page["projection_instructions"] == PROJECTION_INSTRUCTIONS
    assert page["metadata_table"]
    assert expand_host_packet(page)["items"] == units
    assert memory.service.store.get(namespace(memory.service), snapshot).value["items"] == units
    assert memory.service.read(record_id)["value"] == before["value"]
    for original, projected in zip(units, page["items"], strict=True):
        assert projected["record_id"] == original["record_id"]
        assert projected["read_handle"] == original["read_handle"]
        assert projected["edit_unit"]["unit_id"] == original["edit_unit"]["unit_id"]
        assert projected["content"] == original["content"]
        assert projected["content_range"] == original["content_range"]
        if "revision_evidence" in original:
            assert projected["revision_evidence"][0]["read"] == \
                original["revision_evidence"][0]["read"]


def test_sqlite_writer_only_expands_delivered_page_and_resident_model_material(
    saved_memory: tuple[FunctionalEditMemory, dict[str, Any], str],
) -> None:
    memory, config, record_id = saved_memory
    units = memory._record_units(memory.service.read(record_id))
    memory.material_limit = memory.policy["material_limit"] = 6000
    bound = memory._binding(config)
    snapshot = memory._snapshot(bound, units, "record_read")
    page = memory._page(snapshot, 0, bound)
    assert 0 < page["delivered_units"] < len(units)
    assert page["next_cursor"] is not None
    memory._remember_page(config, page)
    memory._note_view_page(config, page)
    cached = memory.service.store.get(
        namespace(memory.service), memory._writer_key(config, "edit-writer-delivery:"),
    ).value["items"]
    actual_records = [item for item in cached if item["type"] == "record"]
    assert actual_records == expand_host_packet(page)["items"]
    assert actual_records == units[:page["delivered_units"]]
    material = memory.model_material(config)
    resident = [item for item in expand_host_packet(material)["items"] if item["type"] == "record"]
    assert resident == actual_records
    assert material["metadata_table"]
    assert all(ref["unit_index"] < page["delivered_units"]
               for ref in memory.view_state(config)["resident_refs"])
    projected_messages = memory.project_model_messages(config, [ToolMessage(
        content=canonical(page), name="read_memory", tool_call_id="actual-read",
    )])
    receipt = json.loads(projected_messages[0].content)
    assert receipt["items"] == []
    assert "metadata_table" not in receipt and "projection_instructions" not in receipt


def test_host_projection_keeps_conflicting_unknowns_raw_source_and_selectors() -> None:
    source = {"type": "fragment", "content": "Literal source body.", "start": 3, "end": 23,
              "source_ref": "literal-source", "fragment_handle": "literal-fragment"}
    item = {
        "type": "record", "record_id": "literal-record", "read_handle": "literal-read",
        "content": "Literal stored unit.", "content_range": [0, 20],
        "edit_unit": {"unit_id": "literal-unit", "role": "content", "evidence_refs": [{
            "evidence_id": "literal-fragment", "source_ref": "literal-source",
            "source_revision": 1, "start": 3, "end": 23,
        }], "assertion": {
            "kind": "reported", "source_ref": "literal-source", "source_revision": None,
            "role": None, "occurred_at": None, "observed_at": "2030-01-02T12:30:00+00:00",
            "calendar_context": None, "applicability": {"scope": {"meta": 0}},
        }},
        "applicability": {"temporal": {
            "reported_at": "2030-01-03", "captured_at": None, "query_time": None,
            "version_time": None, "query_calendar_context": None,
            "effective_from": None, "comparison_basis": {"effective_limits": None},
            "retrospective": None, "reported_after_query": None,
        }},
        "revision_evidence": [{"content": "An original witness.", "start": 3, "end": 23,
            "source_ref": "literal-source", "read": {"tool": "read_source", "arguments": {
                "source_ref": "literal-source", "query_time": "2030-01-03",
            }}}],
    }
    original = {"items": [item, copy.deepcopy(item), source], "material_limit": 8192}
    projected = project_host_packet(original)
    assert expand_host_packet(projected) == original
    assert projected["items"][-1] == source
    assert projected["items"][0]["revision_evidence"] == item["revision_evidence"]
    assert project_host_packet(projected) == projected
    assert original["items"][0]["edit_unit"]["assertion"]["role"] is None
