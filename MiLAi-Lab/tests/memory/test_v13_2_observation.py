"""Zero-model actual Source/Store projection under public and unseen synthetic schemas."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.document_publication import DocumentPublicationWorld
from milai_lab.application.refs import observation_profile
from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.memory import ObservationField, ObservationProfile
from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.append_memory import AppendMemory
from milai_lab.methods.consolidation import consolidate
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import maintain_event
from milai_lab.methods.edit_memory import EditMemory


@contextmanager
def opened(root: Path, owner: str = "alice", **options: Any) -> Iterator[MemoryService]:
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        yield MemoryService(
            store,
            ("observations", owner),
            owner,
            root / "lock",
            mutation_contract="event_bound_v1",
            **options,
        )


def synthetic_profile(**options: Any) -> ObservationProfile:
    return ObservationProfile(
        profile_id="public_inventory",
        adapter_version="1",
        application="InventoryAPI",
        origins=("inspect_objects",),
        object_id_path=("identity",),
        objects_path=("objects",),
        owner_path=("owner",),
        resource_version_path=("revision",),
        resource_version_type="integer",
        valid_time_path=("valid_time",),
        fields=(
            ObservationField("label", ("data", "label"), "string", "inventory_revision"),
            ObservationField("enabled", ("data", "enabled"), "boolean", "inventory_revision"),
        ),
        **options,
    )


def capture(service: MemoryService, key: str, body: Any, origin: str = "inspect_objects") -> str:
    content = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return service.capture_tool("s1", key, origin, content, None)["source_ref"]


def item(key: str, revision: int | None, **data: Any) -> dict[str, Any]:
    return {
        "identity": key,
        "owner": "alice",
        "revision": revision,
        "valid_time": "2026-01-01T00:00:00Z",
        "data": data,
    }


def field_view(service: MemoryService, field: str, object_id: str = "A") -> dict[str, Any]:
    obj = next(
        row
        for row in service.observations()["objects"]
        if row["object_ref"]["external_id"] == object_id
    )
    return obj["fields"][field]


def test_single_real_event_supports_multiple_objects_fields_and_replay_reopen(
    tmp_path: Path,
) -> None:
    profile = synthetic_profile()
    with opened(tmp_path) as service:
        body = {
            "objects": [
                item("A", 1, label="small", enabled=False),
                item("B", 2, label="large", enabled=True),
            ]
        }
        source = capture(service, "actual", body)
        raw = dict(service.source(source))
        result = service.observe(source, profile)
        assert result["status"] == "projected" and result["observation_count"] == 4
        original = service.observations()
        assert len(original["observations"]) == 4 and len(original["objects"]) == 2
        assert {row["field_paths"][0] for row in original["observations"]} == {
            "/objects/0/data/label",
            "/objects/0/data/enabled",
            "/objects/1/data/label",
            "/objects/1/data/enabled",
        }
        assert all(
            row["source_revision"] == raw["source_revision"] for row in original["observations"]
        )
        assert service.records() == [] and service.source(source) == raw
        assert service.observe(source, profile)["status"] == "no_change"
        assert service.observations() == original
    with opened(tmp_path) as reopened:
        assert reopened.observe(source, profile)["replayed"]
        assert reopened.observations() == original


def test_missing_is_not_false_null_or_clear_and_older_arrival_cannot_replace_newer(
    tmp_path: Path,
) -> None:
    profile = synthetic_profile()
    with opened(tmp_path) as service:
        original = capture(service, "first", {"objects": [item("A", 1, label="old", enabled=True)]})
        service.observe(original, profile)
        newer = capture(service, "newer", {"objects": [item("A", 3, label="new")]})
        service.observe(newer, profile)
        stale = capture(service, "late-old", {"objects": [item("A", 2, label="stale")]})
        service.observe(stale, profile)
        view = field_view(service, "label")
        assert view["literal_value"] == "new" and view["selection"] == "comparable_latest"
        assert len(view["history"]) == 3 and view["candidates"][0]["resource_version"] == 3
        assert field_view(service, "enabled")["literal_value"] is True
        assert not view["current_verified"]
        missing = capture(service, "missing", {"objects": [item("A", 4)]})
        assert service.observe(missing, profile)["observation_count"] == 0
        assert field_view(service, "enabled")["literal_value"] is True


@pytest.mark.parametrize(
    "mode", ["unknown_version", "different_domain", "same_version", "opaque_version"]
)
def test_unordered_or_equal_version_disagreement_remains_conflict(
    tmp_path: Path, mode: str
) -> None:
    profile = synthetic_profile()
    with opened(tmp_path) as service:
        first = capture(service, "first", {"objects": [item("A", 2, label="first")]})
        service.observe(first, profile)
        other_profile = profile
        row = item("A", 2 if mode == "same_version" else 3, label="second")
        if mode == "unknown_version":
            row.pop("revision")
        elif mode == "different_domain":
            other_profile = replace(
                profile,
                adapter_version="2",
                fields=(replace(profile.fields[0], version_domain="other_version_domain"),),
            )
        elif mode == "opaque_version":
            row["revision"] = "opaque-tag"
            other_profile = replace(profile, adapter_version="2", resource_version_type="opaque")
        source = capture(service, "second", {"objects": [row]})
        assert service.observe(source, other_profile)["ok"]
        view = field_view(service, "label")
        assert view["status"] == "conflict" and "literal_value" not in view
        assert len(view["candidates"]) == 2 and len(view["history"]) == 2


def test_explicit_public_null_clear_only_and_additive_schema_mapping(tmp_path: Path) -> None:
    profile = synthetic_profile()
    with opened(tmp_path) as service:
        source = capture(
            service,
            "null",
            {"objects": [item("A", 1, label=None, enabled=False, extra="unmapped")]},
        )
        rejected = service.observe(source, profile)
        assert rejected["status"] == "pending" and rejected["reason"] == "field_type_mismatch:label"
        assert service.observations()["observations"] == []
        clear_profile = replace(
            profile,
            adapter_version="2",
            fields=(
                replace(profile.fields[0], allow_null_clear=True),
                profile.fields[1],
                ObservationField("extra", ("data", "extra"), "string", "inventory_revision"),
            ),
        )
        projected = service.observe(source, clear_profile)
        assert projected["observation_count"] == 3
        assert field_view(service, "label")["literal_value"] is None
        assert field_view(service, "label")["candidates"][0]["clears"]
        assert field_view(service, "enabled")["literal_value"] is False
        assert field_view(service, "extra")["literal_value"] == "unmapped"


def test_profile_origin_owner_revision_and_same_version_mapping_are_bound(tmp_path: Path) -> None:
    profile = synthetic_profile()
    with opened(tmp_path) as service:
        foreign = capture(
            service, "foreign", {"objects": [{**item("A", 1, label="x"), "owner": "bob"}]}
        )
        assert service.observe(foreign, profile)["reason"] == "object_owner_mismatch"
        wrong = capture(
            service, "wrong-origin", {"objects": [item("A", 1, label="x")]}, "other_tool"
        )
        assert service.observe(wrong, profile)["reason"] == "source_origin_profile_mismatch"
        source = capture(service, "actual", {"objects": [item("A", 1, label="x")]})
        assert service.observe(source, profile)["ok"]
        changed = replace(profile, fields=(replace(profile.fields[0], path=("data", "other")),))
        assert service.observe(source, changed)["reason"] == "projection_binding_changed"
        event = service.store.get(service.sources_namespace, source).value
        event["source_revision"] = 2
        service.store.put(service.sources_namespace, source, event, index=False)
        assert service.observe(source, profile)["reason"] == "projection_binding_changed"
        with pytest.raises(ValueError, match="OBSERVATION_SOURCE_CHANGED"):
            service.observations()


def test_mid_projection_failure_is_pending_not_visible_and_replays_after_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = synthetic_profile()
    with opened(tmp_path) as service:
        source = capture(service, "actual", {"objects": [item("A", 1, label="x", enabled=True)]})
        put = service.store.put
        writes = 0

        def fail_one(
            namespace: tuple[str, ...], key: str, value: dict[str, Any], **options: Any
        ) -> Any:
            nonlocal writes
            if namespace == service.observations_namespace:
                writes += 1
                if writes == 2:
                    raise RuntimeError("OFFLINE_INJECTED_SECOND_FACT_FAILURE")
            return put(namespace, key, value, **options)

        monkeypatch.setattr(service.store, "put", fail_one)
        result = service.observe(source, profile)
        assert not result["ok"] and result["status"] == "pending"
        assert result["error"] == "OFFLINE_INJECTED_SECOND_FACT_FAILURE"
        assert len(service._rows(service.observations_namespace)) == 1
        assert service.observations()["observations"] == []
        assert service.projection_receipt(source, profile)["status"] == "pending"
    with opened(tmp_path) as reopened:
        assert reopened.observations()["pending"][0]["status"] == "pending"
        assert reopened.observe(source, profile)["observation_count"] == 2
        assert len(reopened.observations()["observations"]) == 2
        assert reopened.observations()["pending"] == []
        assert reopened.observe(source, profile)["status"] == "no_change"


def test_unknown_does_not_clear_confirmed_history_or_invent_no_effect(tmp_path: Path) -> None:
    profile = synthetic_profile()
    with opened(tmp_path) as service:
        good = capture(service, "good", {"objects": [item("A", 1, label="confirmed")]})
        service.observe(good, profile)
        unknown = capture(
            service,
            "unknown",
            {
                "status": "ORIGINAL_CALL_OUTCOME_UNKNOWN",
                "objects": [item("A", 2, label="invented")],
            },
        )
        result = service.observe(unknown, profile)
        assert result["status"] == "observed_unknown" and result["observation_count"] == 0
        assert "no_effect" not in json.dumps(result)
        view = service.observations()
        assert view["unknown"][0]["source_ref"] == unknown
        assert field_view(service, "label")["literal_value"] == "confirmed"
        assert len(field_view(service, "label")["history"]) == 1


@pytest.mark.parametrize("maintenance_mode", ["legacy", "event_delta_v1"])
def test_real_reservation_literal_maintenance_keeps_source_and_unchanged_units(
    tmp_path: Path, maintenance_mode: str,
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path, candidate_contract="read_handle_v1") as service:
            body = world.reserve_and_label("alice", "public-item", 1, "desk", "box")
            source = capture(service, "actual", body, "reserve_and_label")
            assert (
                service.observe(source, observation_profile("reservation_v1"))["observation_count"]
                == 2
            )
            obj = service.observations()["objects"][0]
            assert obj["fields"]["label_status"]["literal_value"] == "not_created"
            assert obj["fields"]["status"]["literal_value"] == "reserved_label_failed"
            assert obj["fields"]["status"]["selection"] == "unordered_observations"
            assert service.records() == []
            raw = dict(service.source(source))
            profile = observation_profile("reservation_v1", maintenance=True)
            assert profile.adapter_version == "2"
            method = EditMemory(service, "M", interface_version="I2",
                                features=EditFeatures(True, True, True, True, True),
                                maintenance_mode=maintenance_mode)
            service.bind_source_boundary("s1", "save", [source])
            first = method.observation_delivery(
                method.prepare([source], "", selected_records=[]), [profile]
            )
            assert service.source(source) == raw and service.records() == []
            assert all(row["text"] == body[row["start"]:row["end"]]
                       for row in first["sources"])
            assert first["result_maintenance"]["extraction_source_ranges"] == []
            calls = []

            def model(stage, messages, schema):
                calls.append(stage)
                assert stage.startswith("edit:")  # Known fields never call Extractor.
                payload = json.loads(messages[1]["content"])
                candidates = {row["field"]: row for row in payload["delivery"].get(
                    "change_candidates", payload.get("change_candidates", []))}
                assert all(row["basis"] == "actual_source_literal"
                           and not row["current_verified"] for row in candidates.values())
                packet = payload["delivery"]

                def assertion(field):
                    row = candidates[field]
                    return {"text": "Reservation " + field + "=" + json.dumps(row["literal_value"]),
                            "evidence": row["evidence"],
                            "assertion": {"source": row["evidence"][-1], "kind": "observed"}}

                if not packet["records"]:
                    return {"creates": [{"action": "create", "matter": "Reservation result",
                            "clauses": [{**assertion(field), "conditions": []}
                                        for field in ("status", "label_status", "quantity")]}]}
                record = packet["records"][0]
                label = next(row for row in record["clauses"] if "label_status" in row["text"])
                appended = {**assertion("packing"), "operation": "append", "role": "content"}
                wrong = {"action": "edit", "target": record["id"],
                         "edits": [{**appended, "attach_to": [label["id"]]}]}
                assert not Draft202012Validator(schema).is_valid(
                    {"records": {record["id"]: {k: v for k, v in wrong.items() if k != "target"}}}
                )
                # An old invalid output still reaches the original rejection;
                # the new generation restriction never converts it to a condition.
                mapping = method.load_mapping("edit-map:" + stage.split(":", 1)[1])
                decoded = method.decode_proposal(wrong, mapping)
                with pytest.raises(FunctionalRejection, match="APPEND_CONDITION_TARGET_INVALID"):
                    method.apply("s1", "legacy-invalid", decoded)
                return {"records": {record["id"]: {"action": "edit", "edits": [
                    {**assertion("label_status"), "operation": "change_value",
                     "target_unit": label["id"]}, appended,
                ]}}}

            options = dict(session="s1", date="2026-10-08", recipe="extract_then_edit",
                           memory_view_mode="staged", model_call=model)
            saved = maintain_event(method, first, request_id="save", selected_record_ids=[],
                                   **options)
            assert saved["status"] == "completed" and len(saved["receipts"]) == 1
            record_id = saved["receipts"][0]["id"]
            baseline = service.read(record_id)["value"]["edit_state"]
            world.set_label_available("restore", True)
            assert json.loads(world.complete_label("alice", json.loads(body)["reservation_id"]))[
                "label_status"] == "created"
            final_source = capture(service, "query", world.get_reservation("alice", "public-item"),
                                   "get_reservation")
            service.bind_source_boundary("s1", "update", [final_source])
            current = method.observation_delivery(
                method.prepare([final_source], "", selected_records=[]), [profile]
            )
            updated = maintain_event(method, current, request_id="update",
                                     selected_record_ids=[record_id], **options)
            assert updated["status"] == "completed" and len(updated["receipts"]) == 1
            state = service.read(record_id)["value"]["edit_state"]
            assert state["units"][0] == baseline["units"][0]
            assert state["units"][2] == baseline["units"][2]
            assert state["units"][3]["role"] == "content" and state["relations"] == []
            assert service.read(record_id, 1)["value"]["edit_state"] == baseline
            assert len(calls) == 2
            assert world.snapshot()["attempts"][-1]["operation"] == "complete_label"
            append = AppendMemory(service, features=method.features)
            view = append.writer_request(current, request_id="append-interface")
            assert append.decode_envelope({"creates": [], "records": {}}, view["mapping"]) == []
            original_ranges = [{k: row[k] for k in ("source_ref", "start", "end")}
                               for row in current["sources"]]
        with opened(tmp_path, candidate_contract="read_handle_v1") as service:
            method = EditMemory(service, "M", interface_version="I2",
                                features=EditFeatures(True, True, True, True, True),
                                maintenance_mode=maintenance_mode)
            delivery = method.prepare([final_source], "", selected_records=[],
                                      source_ranges=original_ranges)
            replayed = maintain_event(method, delivery, request_id="update",
                                      selected_record_ids=[record_id], **options)
            assert replayed["status"] == "completed" and len(calls) == 2
            assert service.read(record_id)["value"]["edit_state"] == state
            assert service.source(source) == raw
    finally:
        world.close()


def test_event_scoped_tools_preserve_user_correction_and_replay_original_sources(
    tmp_path: Path,
) -> None:
    """Registered result structure, not status wording, controls this ordinary chain."""
    with opened(tmp_path, candidate_contract="read_handle_v1") as service:
        method = EditMemory(service, "M", interface_version="I2",
                            features=EditFeatures(True, True, True, True, True, True),
                            maintenance_mode="event_delta_v1")
        user = service.capture_user("s1", "seed", "Use paper labels. Keep box tracking.")[
            "source_ref"]
        service.bind_source_boundary("s1", "seed", [user])
        initial = method.writer_request(method.prepare([user], "", selected_records=[]))
        proposal = {"creates": [{"action": "create", "matter": "Label handling", "clauses": [
            {"text": text, "conditions": [], "evidence": ["e1"],
             "assertion": {"source_evidence": "e1", "kind": "reported"}}
            for text in ("Labels are paper.", "Box tracking is required.")
        ]}], "records": {}}
        receipt = method.apply("s1", "seed-record",
                               method.decode_envelope(proposal, initial["mapping"])[0])
        before = service.read(receipt["id"])["value"]

        def no_model(*args, **kwargs):
            raise AssertionError("Execution receipt must not reinterpret old User context")

        profile = synthetic_profile()
        for key, origin in (("read-receipt", "read_memory"), ("no-object", "inspect_objects")):
            ref = capture(service, key, {"status": "not_found", "objects": []}, origin)
            service.bind_source_boundary("s1", key, [ref])
            delivery = method.prepare([ref], "", selected_records=[])
            delivery["prior_context"] = method.prepare([user], "", selected_records=[])[
                "sources"]
            projected = method.observation_delivery(
                delivery, [profile], execution_only_origins=("read_memory",)
            )
            assert projected["sources"] == [] and service.source(ref) is not None
            result = maintain_event(method, projected, session="s1", request_id=key,
                                    date="2026-01-01", recipe="extract_then_edit",
                                    model_call=no_model)
            assert result["status"] == "completed" and result["outcome"] == "no_domain_observation"
            assert not result["semantic_write_performed"] and result["source_refs"] == [ref]
            assert service.read(receipt["id"])["value"] == before

        lookup = ObservationProfile(
            profile_id="inventory_lookup", adapter_version="1", application="InventoryLookup",
            origins=("inspect_objects",), object_id_path=("query",),
            fields=(ObservationField("exists", ("exists",), "boolean"),),
        )
        negative = service.capture_tool(
            "s1", "lookup", "inspect_objects", json.dumps({"query": "A", "exists": False}),
            None, occurred_at="2026-01-01", calendar_context="public-calendar",
        )["source_ref"]
        original = service.source(negative)
        projected = method.observation_delivery(
            method.prepare([negative], "", selected_records=[]), [profile, lookup]
        )
        change = projected["result_maintenance"]["literal_changes"][0]
        assert change["subject"] == "InventoryLookup A" and change["literal_value"] is False
        assert projected["result_maintenance"]["extraction_source_ranges"] == []
        assert "execution_source_refs" not in projected["result_maintenance"]
        service.bind_source_boundary("s1", "lookup", [negative])

        def save_lookup(stage, messages, schema):
            assert stage == "edit"  # A real negative field is not dropped or re-extracted.
            packet = json.loads(messages[1]["content"])["delivery"]
            cue = packet["change_candidates"][0]
            return {"creates": [{"action": "create", "matter": "Inventory lookup A",
                    "clauses": [{"text": "Inventory lookup reports A does not exist.",
                                 "conditions": [], "evidence": cue["evidence"],
                                 "assertion": {"source_evidence": cue["evidence"][-1],
                                               "kind": "observed"}}]}], "records": {}}

        saved = maintain_event(method, projected, session="s1", request_id="lookup",
                               date="2026-01-01", recipe="extract_then_edit",
                               model_call=save_lookup, selected_record_ids=[])
        assert saved["semantic_write_performed"] and service.source(negative) == original
        assert service.read(receipt["id"])["value"] == before

        correction = service.capture_user("s1", "change", "Use linen labels now.")["source_ref"]
        service.bind_source_boundary("s1", "change", [correction, ref])
        mixed = method.observation_delivery(
            method.prepare([correction, ref], "", selected_records=[]), [profile, lookup],
        )
        assert [row["source_ref"] for row in mixed["sources"]] == [correction]
        stages = []

        def correct(stage, messages, schema):
            stages.append(stage)
            packet = json.loads(messages[1]["content"])["delivery"]
            if stage == "extract":
                return {"changes": [{"subject": "Labels", "statement": "Use linen labels now.",
                                     "time": None, "scope": None, "evidence": ["e1"]}]}
            record = packet["records"][0]
            return {"creates": [], "records": {record["id"]: {"action": "edit", "edits": [{
                "operation": "replace", "target_unit": record["clauses"][0]["id"],
                "text": "Labels are linen.", "evidence": ["e1"],
                "assertion": {"source_evidence": "e1", "kind": "reported"},
            }]}}}

        changed = maintain_event(method, mixed, session="s1", request_id="change",
                                 date="2026-01-01", recipe="extract_then_edit", model_call=correct,
                                 selected_record_ids=[receipt["id"]])
        assert changed["semantic_write_performed"] and stages == ["extract", "edit"]
        state = service.read(receipt["id"])["value"]["edit_state"]
        assert state["units"][1] == before["edit_state"]["units"][1]
        unknown = capture(service, "external", {"status": "not_found"}, "unregistered_tool")
        unclassified = method.observation_delivery(
            method.prepare([unknown], "", selected_records=[]), [profile, lookup]
        )
        assert unclassified["sources"][0]["role"] == "tool"
        assert unclassified["result_maintenance"]["literal_changes"] == []

        index = EpisodeIndex(service)
        index.register("lookup-episode", [negative])
        replay_calls = []

        def replay(**kwargs):
            replay_calls.append(kwargs)
            delivery = kwargs["delivery"]
            assert delivery["replay"] and not delivery["new_independent_support"]
            source = delivery["sources"][0]
            assert source["source_ref"] == negative and source["origin"] == "inspect_objects"
            assert source["calendar_context"] == "public-calendar"
            return {"status": "completed", "receipts": [], "semantic_write_performed": False}

        options = {"request_id": "organize", "maintain": replay,
                   "episode_ids": ["lookup-episode"]}
        organized = consolidate(index, **options)
        assert organized["status"] == "completed" and not organized["semantic_write_performed"]
        assert consolidate(index, **options)["replayed"] and len(replay_calls) == 1
        assert service.source(negative) == original


def test_actual_document_content_version_does_not_order_approval_or_publication(
    tmp_path: Path,
) -> None:
    world = DocumentPublicationWorld(tmp_path / "world.sqlite", True)
    profile = observation_profile("document_publication_v1")
    try:
        with opened(tmp_path) as service:
            draft = world.create_or_update_draft("alice", "Public note", "Actual draft")
            body = json.loads(draft)
            before = capture(service, "draft", draft, "create_or_update_draft")
            service.observe(before, profile)
            approved = world.approve_document_version(
                "alice", "Public note", body["document_version"]
            )
            after = capture(service, "approval", approved, "approve_document_version")
            service.observe(after, profile)
            obj = service.observations()["objects"][0]
            assert obj["fields"]["document_version"]["status"] == "observed"
            assert obj["fields"]["document_version"]["selection"] == "comparable_latest"
            assert obj["fields"]["approval_status"]["status"] == "conflict"
            assert obj["fields"]["approval_status"]["selection"] == "unordered_observations"
            edit = world.create_or_update_draft(
                "alice",
                "Public note",
                "Changed draft",
                body["document_version"],
            )
            edit_source = capture(service, "edit", edit, "create_or_update_draft")
            service.observe(edit_source, profile)
            obj = service.observations()["objects"][0]
            assert (
                obj["fields"]["document_version"]["literal_value"]
                == json.loads(edit)["document_version"]
            )
            assert obj["fields"]["document_version"]["literal_value"] == 2
            assert obj["fields"]["approval_status"]["status"] == "conflict"
    finally:
        world.close()
