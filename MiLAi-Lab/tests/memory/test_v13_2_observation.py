"""Zero-model actual Source/Store projection under public and unseen synthetic schemas."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.document_publication import DocumentPublicationWorld
from milai_lab.application.refs import observation_profile
from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.memory import ObservationField, ObservationProfile
from milai_lab.memory.service import MemoryService


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


def test_real_reservation_partial_failure_is_projected_from_actual_receipt_without_writer(
    tmp_path: Path,
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path) as service:
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
    finally:
        world.close()


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
