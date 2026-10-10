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

from milai_lab.memory.functional_state import (
    FunctionalRejection,
    canonical,
    namespace,
    project_request_targets,
    request_target_mapping,
)
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
    page = memory.bind_request_targets(config, memory._page(snapshot, 0, bound))
    assert page["delivered_units"] == page["total_units"] == 5
    assert page["delivery_status"] == "complete_snapshot"
    assert page["omitted_units"] == 0 and page["next_cursor"] is None
    assert _tokens(canonical(page)) <= 8192
    assert page["projection_instructions"] == PROJECTION_INSTRUCTIONS
    assert page["metadata_table"]
    # Navigation is projected before metadata sharing; preview signs nothing.
    expected, planned = project_request_targets(request_target_mapping(memory.service, bound),
        {"items": units, "forget_epoch": memory.forget_epoch})
    assert expand_host_packet(page)["items"] == expected["items"]
    assert memory.service.store.get(namespace(memory.service), snapshot).value["items"] == units
    assert memory.service.read(record_id)["value"] == before["value"]
    for original, projected in zip(units, page["items"], strict=True):
        assert projected["record_id"] == original["record_id"]
        assert projected["read_handle"] == original["read_handle"]
        assert projected["edit_unit"]["unit_id"] == original["edit_unit"]["unit_id"]
        assert projected["content"] == original["content"]
        assert projected["content_range"] == original["content_range"]
        if "revision_evidence" in original:
            navigation = planned["targets"][projected["revision_evidence"][0]["target"]]
            assert navigation["identity"]["read"] == original["revision_evidence"][0]["read"]
            assert navigation["kind"] == "read_only_navigation" and navigation["credentials"] == {}


def test_sqlite_writer_only_expands_delivered_page_and_resident_model_material(
    saved_memory: tuple[FunctionalEditMemory, dict[str, Any], str],
) -> None:
    memory, config, record_id = saved_memory
    units = memory._record_units(memory.service.read(record_id))
    # Keep a partial snapshot with room for the resident wrapper after exact
    # relation sharing. This test still requires a real unread continuation.
    memory.material_limit = memory.policy["material_limit"] = 5600
    bound = memory._binding(config)
    snapshot = memory._snapshot(bound, units, "record_read")
    page = memory.bind_request_targets(config, memory._page(snapshot, 0, bound))
    assert 0 < page["delivered_units"] < len(units)
    assert page["next_cursor"] is not None
    memory._remember_page(config, page)
    memory._note_view_page(config, page)
    cached = memory.service.store.get(
        namespace(memory.service), memory._writer_key(config, "edit-writer-delivery:"),
    ).value["items"]
    actual_records = [item for item in cached if item["type"] == "record"]
    assert actual_records == expand_host_packet(page)["items"]
    expected, _ = project_request_targets(request_target_mapping(memory.service, bound),
        {"items": units[:page["delivered_units"]], "forget_epoch": memory.forget_epoch})
    assert actual_records == expected["items"]
    material = memory.model_material(config)
    assert _tokens(canonical(material)) <= memory.material_limit
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


def test_sqlite_resident_capacity_counts_current_source_targets_and_full_wrapper(
    saved_memory: tuple[FunctionalEditMemory, dict[str, Any], str],
) -> None:
    memory, config, record_id = saved_memory
    before = memory.service.read(record_id)
    units = memory._record_units(before)
    memory.material_limit = memory.policy["material_limit"] = 8192
    bound = memory._binding(config)
    current = [{"type": "fragment", **part} for part in memory.service.source_fragments(
        bound["source_ref"], max_chars=memory.fragment_chars,
    )]
    source_snapshot = memory._snapshot(bound, current, "current_input")
    source_page = memory.bind_request_targets(config, memory._page(source_snapshot, 0, bound))
    memory._remember_page(config, source_page)
    memory._note_view_page(config, source_page)
    record_snapshot = memory._snapshot(bound, units, "record_read")
    page = memory.bind_request_targets(config, memory._page(record_snapshot, 0, bound))
    assert page["delivered_units"] == len(units)
    memory._remember_page(config, page)
    memory._note_view_page(config, page)

    material = memory.model_material(config)
    expanded = expand_host_packet(material)
    cost = _tokens(canonical(material))
    assert cost <= 8192 < _tokens(canonical(expanded))
    source_item = {"type": "fragment", **memory.service.source_fragment(
        current[0]["fragment_handle"],
    ), **{field: source_page["items"][0][field] for field in ("target", "target_kind")}}
    assert expanded["items"] == [source_item,
                                 *expand_host_packet(page)["items"]]
    assert material["memory_view"]["resident_refs"] and material["read_progress"]
    assert material["target_scope"] == page["target_scope"] == source_page["target_scope"]
    assert material["items"][0] == source_item
    for projected, original in zip(material["items"][1:], expanded["items"][1:], strict=True):
        for field in ("record_id", "read_handle", "revision", "content", "content_range",
                      "target", "target_kind"):
            assert projected[field] == original[field]
        assert projected["edit_unit"]["unit_id"] == original["edit_unit"]["unit_id"]
    items_cost = _tokens(canonical({key: material[key] for key in (
        "items", "metadata_table", "projection_instructions",
    )}))
    memory.material_limit = memory.policy["material_limit"] = cost - 1
    assert items_cost < memory.material_limit
    with pytest.raises(FunctionalRejection, match="V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT"):
        memory.model_material(config)
    assert memory.service.read(record_id)["value"] == before["value"]


def test_host_projection_keeps_conflicting_unknowns_raw_source_and_selectors() -> None:
    source = {"type": "fragment", "content": "Literal source body.", "start": 3, "end": 23,
              "source_ref": "literal-source", "fragment_handle": "literal-fragment"}
    item = {
        "type": "record", "record_id": "literal-record", "read_handle": "literal-read",
        "content": "Literal stored unit.", "content_range": [0, 20], "revision_context": None,
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


def test_host_relation_sharing_keeps_direction_type_unknown_fields_and_literal_handles() -> None:
    forward = {
        "relation_id": "actual-relation-identity-0123456789",
        "source_unit": "actual-source-unit-identity-0123456789",
        "target_unit": "actual-target-unit-identity-0123456789",
        "relation_type": "modifies", "evidence_refs": [{
            "evidence_id": "actual-fragment-identity-0123456789", "start": 0, "end": 20,
        }], "unknown_relation_field": {"meaning": None},
    }
    backward = {**copy.deepcopy(forward), "source_unit": forward["target_unit"],
                "target_unit": forward["source_unit"]}
    exception = {**copy.deepcopy(forward), "relation_type": "overrides"}
    relations = [forward, backward, exception]
    record = {
        "type": "record", "record_id": "literal-record", "read_handle": "literal-read",
        "revision": 2, "target": "q0123456789abc:1", "target_kind": "delivered_record",
        "content": "Literal unit body.", "content_range": [0, 18],
        "edit_unit": {"unit_id": "literal-unit", "role": "content"},
        "edit_relations": copy.deepcopy(relations),
        "revision_context": {"relations": copy.deepcopy(relations)},
        "stored_history": {"read": {"tool": "read_memory_revision", "arguments": {
            "target": "q0123456789abc:2", "revision": 1,
        }}},
    }
    source = {"type": "fragment", "content": "Literal original body.", "start": 4, "end": 26,
              "fragment_handle": "literal-fragment", "target": "q0123456789abc:3"}
    original = {"ok": True, "kind": "resident", "items": [record, source],
                "memory_view": {"read_goal": "Read the applicable saved version."},
                "read_progress": {"read": 2}, "continuations": [{
                    "tool": "read_page", "arguments": {"target": "q0123456789abc:4"},
                }], "target_scope": "q0123456789abc", "material_limit": 8192}
    before = copy.deepcopy(original)
    projected = project_host_packet(original)
    assert original == before and expand_host_packet(projected) == original
    assert _tokens(canonical(projected)) < _tokens(canonical(original))
    row = projected["items"][0]
    for field in ("record_id", "read_handle", "revision", "target", "target_kind",
                  "content", "content_range", "edit_unit", "stored_history"):
        assert row[field] == record[field]
    assert projected["items"][1] == source
    assert projected["continuations"] == original["continuations"]
    references = [relation["relation_metadata"] for relation in row["edit_relations"]]
    assert len({reference["meta"] for reference in references}) == 3
    assert references == [relation["relation_metadata"]
                          for relation in row["revision_context"]["relations"]]
    for relation, reference in zip(relations, references, strict=True):
        assert projected["metadata_table"][str(reference["meta"])] == {
            field: relation[field] for field in (
                "relation_id", "source_unit", "target_unit", "relation_type",
            )
        }

    def has_reference(value: Any) -> bool:
        if isinstance(value, dict):
            return set(value) == {"meta"} or any(has_reference(v) for v in value.values())
        return isinstance(value, list) and any(has_reference(v) for v in value)

    assert not has_reference(list(projected["metadata_table"].values()))
    assert project_host_packet(projected) == projected


@pytest.mark.parametrize("location", ["edit_relations", "revision_context"])
@pytest.mark.parametrize("literal", [{"meta": 0}, {"relation_type": None}, None])
def test_host_relation_metadata_name_collision_stays_literal(
    location: str, literal: Any,
) -> None:
    relation = {"relation_id": "literal-relation", "source_unit": "literal-source-unit",
                "target_unit": "literal-target-unit", "relation_type": "modifies",
                "relation_metadata": copy.deepcopy(literal)}
    record = {"type": "record", "record_id": "literal-record", "read_handle": "literal-read",
              "edit_unit": {"unit_id": "literal-unit"}, "content": "Original body."}
    if location == "edit_relations":
        record[location] = [relation]
    else:
        record[location] = {"relations": [relation]}
    original = {"items": [record, copy.deepcopy(record)]}
    before = copy.deepcopy(original)
    assert project_host_packet(original) == before
    assert expand_host_packet(original) == before
    assert original == before
