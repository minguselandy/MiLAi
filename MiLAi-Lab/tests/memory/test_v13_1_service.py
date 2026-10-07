"""Mechanical SDK/ToolNode checks; no real model, embedding or scorer inputs."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.refs import verified_reservation_ref
from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.memory import GroundingMode
from milai_lab.memory.mcp import MemoryMCP
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools


@contextmanager
def opened(
    root: Path,
    owner: str = "alice",
    mode: GroundingMode = "field_grounded",
    receipt_contract: str = "optional",
    observer: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[MemoryService]:
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        yield MemoryService(
            store,
            ("langmem", "run", mode, owner),
            owner,
            root / "memory.lock",
            mode=mode,
            receipt_contract=receipt_contract,
            observer=observer,
        )


def proposal(source: str, content: str = "I prefer short replies", **extra: Any) -> dict[str, Any]:
    return {
        "content": content,
        "kind": "semantic",
        "scope": {"subject": "personal"},
        "basis": "user_statement",
        "source_ref": source,
        "object_ref": None,
        "fields": {},
        "id": None,
        "expected_revision": 0,
        **extra,
    }


def captured(service: MemoryService, key: str = "m1", content: str = "Keep short replies") -> str:
    return str(service.capture_user("s1", key, content)["source_ref"])


def tool_event(
    service: MemoryService, world: ApplicationWorld, key: str = "call1"
) -> tuple[str, str, dict[str, Any]]:
    body = world.reserve_and_label(service.owner, key, 1, "desk", "box")
    source = service.event_id("s1", key, "tool")
    ref = verified_reservation_ref(world, service.owner, source, "reserve_and_label", body)
    assert ref is not None
    service.capture_tool("s1", key, "reserve_and_label", body, ref)
    return source, ref.id, json.loads(body)


def config(mode: str = "field_grounded") -> dict[str, Any]:
    return {
        "configurable": {
            "foundation_run_id": "run",
            "arm_id": mode,
            "user_id": "alice",
            "v13_session": "s1",
        }
    }


def call(name: str, arguments: dict[str, Any], identity: str = "proposal1") -> dict[str, Any]:
    return {"name": name, "args": arguments, "id": identity, "type": "tool_call"}


def test_source_capture_is_immutable_unformed_with_source_revision(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = captured(service)
        assert service.sources()[0]["formation_status"] == "pending"
        event = service.source(source)
        assert event is not None
        assert event["source_revision"] == 1 and "content_sha256" not in event
        assert service.records() == []
        assert service.search("short")["raw_events"][0]["event_id"] == source
        assert captured(service) == source
        with pytest.raises(ValueError, match="SOURCE_EVENT_CHANGED"):
            captured(service, content="A fabricated changed event")
        receipt = service.commit("s1", "p1", proposal(source))
        assert receipt["status"] == "committed" and receipt["content_verification"] == "unchecked"
        assert service.sources()[0]["formation_status"] == "formed"
        replayed = service.capture_user("s1", "m1", "Keep short replies")
        assert replayed["formation_status"] == "formed"


def test_declared_source_calendar_survives_replay_and_reopen(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        ref = service.capture_user(
            "s1", "calendar", "A reported local event.",
            occurred_at="Jan 06, 2026, 17:48:59", calendar_context="example-local-calendar",
        )["source_ref"]
        original = service.source(ref)
        assert original is not None
        assert original["occurred_at"] == "Jan 06, 2026, 17:48:59"
        assert original["calendar_context"] == "example-local-calendar"
        assert original["observed_at"].endswith("+00:00")
        service.capture_user("s1", "calendar", "A reported local event.")
        assert service.source(ref) == original
    with opened(tmp_path) as service:
        assert service.source(ref) == original
        with pytest.raises(ValueError, match="SOURCE_CALENDAR_CONTEXT_CHANGED"):
            service.capture_user(
                "s1", "calendar", "A reported local event.", calendar_context="other-calendar",
            )
        assert service.source(ref) == original


def test_old_source_without_calendar_is_not_reinterpreted(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        ref = service.capture_user(
            "s1", "old-calendar", "An event with no declared calendar.",
            occurred_at="Jan 06, 2026, 17:48:59",
        )["source_ref"]
        original = service.source(ref)
        assert original is not None and "calendar_context" not in original
        with pytest.raises(ValueError, match="SOURCE_CALENDAR_CONTEXT_CHANGED"):
            service.capture_user(
                "s1", "old-calendar", "An event with no declared calendar.",
                calendar_context="example-local-calendar",
            )
        assert service.source(ref) == original


@pytest.mark.parametrize("wrong", ["nonexistent", "foreign"])
@pytest.mark.parametrize("receipt_contract", ["optional", "explicit_receipt_v1"])
def test_source_and_object_refs_are_owner_bound(
    tmp_path: Path, wrong: str, receipt_contract: str
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path, "bob") as other:
            foreign_source, foreign_ref, body = tool_event(other, world)
            assert (
                verified_reservation_ref(
                    world, "alice", foreign_source, "reserve_and_label", json.dumps(body)
                )
                is None
            )
        with opened(tmp_path, receipt_contract=receipt_contract) as service:
            source, _, _ = tool_event(service, world, "owned-call")
            bad = foreign_source if wrong == "foreign" else "src-nonexistent"
            rejected = service.commit("s1", "p1", proposal(bad))
            assert rejected["reason"] == "source_not_found_or_not_owned"
            rejected = service.commit(
                "s1",
                "p2",
                proposal(
                    source,
                    basis="tool_observation",
                    object_ref=(foreign_ref if wrong == "foreign" else "imaginary-object"),
                ),
            )
            assert rejected["reason"] == "object_ref_not_found_or_not_owned"
            assert service.records() == []
    finally:
        world.close()


@pytest.mark.parametrize("mode", ["ref_only", "field_grounded"])
def test_real_ref_wrong_field_distinguishes_independent_modes(
    tmp_path: Path, mode: GroundingMode
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path, mode=mode) as service:
            source, ref, body = tool_event(service, world)
            assert (
                body["status"] == "reserved_label_failed" and body["label_status"] == "not_created"
            )
            raw = proposal(
                source,
                "MODEL_RAW: completed everything",
                basis="tool_observation",
                object_ref=ref,
                fields={"status": "label_created", "label_status": "created"},
            )
            receipt = service.commit("s1", "p1", raw)
            if mode == "field_grounded":
                assert receipt["reason"].startswith("field_conflict:")
                attempts = service.store.search(service.attempts_namespace)
                assert attempts[0].value["raw"] == raw
                assert service.records() == []
            else:
                assert receipt["status"] == "committed"
                record = service.read(receipt["id"])["value"]
                assert record["content"] == raw["content"]
                assert record["fields"] == raw["fields"]
                assert record["fields_verification"] == "unchecked"
                assert record["content_verification"] == "unchecked"
    finally:
        world.close()


def test_receipt_idempotence_partial_fields_and_prose_never_verified(tmp_path: Path) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path) as service:
            source, ref, body = tool_event(service, world)
            raw = proposal(
                source,
                "Unverified prose says all succeeded",
                basis="tool_observation",
                object_ref=ref,
                fields={key: body[key] for key in ("status", "label_status")},
            )
            receipt = service.commit("s1", "p1", raw)
            assert receipt["fields_verification"] == "receipt_matched"
            assert set(receipt) == {
                "ok",
                "status",
                "id",
                "revision",
                "source_ref",
                "formation_status",
                "content_verification",
                "fields_verification",
                "effect",
                "mode",
            }
            version = service.read(receipt["id"])["value"]
            assert set(version) == {
                "revision",
                "content",
                "kind",
                "scope",
                "basis",
                "source_ref",
                "object_ref",
                "fields",
                "mode",
                "content_verification",
                "source_status",
                "fields_verification",
                "observed_at",
                "committed_at",
                "session",
            }
            duplicate = service.commit("s1", "different-call", raw)
            assert duplicate["status"] == "no_change" and duplicate["id"] == receipt["id"]
            assert len(service.records()) == 1
            assert (
                len(service.store.get(service.namespace, receipt["id"]).value["_v13_1"]["history"])
                == 1
            )
            conflict = service.commit(
                "s1", "conflict", {**raw, "content": "conflicting projection"}
            )
            assert conflict["reason"] == "receipt_already_consumed"
            assert service.read(receipt["id"])["value"]["content"] == raw["content"]
            assert len(world.snapshot()["attempts"]) == 1
    finally:
        world.close()


@pytest.mark.parametrize("mode", ["ref_only", "field_grounded"])
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({}, "receipt_fields_required"),
        ({"status": "reserved_label_failed"}, "receipt_fields_required"),
        (
            {"status": "reserved_label_failed", "label_status": "not_created", "extra": "raw"},
            "unsupported_operational_field",
        ),
        ({"status": 1, "label_status": "not_created"}, "invalid_receipt_fields"),
    ],
)
def test_explicit_receipt_invalid_fields_reject_without_consuming_source(
    tmp_path: Path, mode: GroundingMode, fields: dict[str, Any], reason: str
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path, mode=mode, receipt_contract="explicit_receipt_v1") as service:
            source, ref, body = tool_event(service, world)
            claims = {key: body[key] for key in ("status", "label_status")}
            raw = proposal(
                source,
                json.dumps(claims),
                basis="tool_observation",
                object_ref=ref,
                fields=fields,
                content_format="receipt_json_v1",
            )
            rejected = service.commit("s1", "missing", raw)
            assert rejected["reason"] == reason
            assert service.store.search(service.attempts_namespace)[0].value["raw"] == raw
            assert service.sources()[0]["formation_status"] == "pending"
            assert service.records() == []
            if not fields:
                # Omitting the model ref cannot bypass a real reservation source's
                # contract (the public tool would discover this ref internally).
                omitted = service.commit("s1", "omitted-ref", {**raw, "object_ref": None})
                assert omitted["reason"] == "receipt_fields_required"
            accepted = service.commit("s1", "corrected-model-proposal", {**raw, "fields": claims})
            assert accepted["status"] == "committed"
            assert service.read(accepted["id"])["value"]["fields"] == claims
    finally:
        world.close()


@pytest.mark.parametrize("mode", ["ref_only", "field_grounded"])
@pytest.mark.parametrize("conflict", ["receipt", "body"])
def test_explicit_receipt_schema_does_not_turn_ref_only_into_field_grounding(
    tmp_path: Path, mode: GroundingMode, conflict: str
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path, mode=mode, receipt_contract="explicit_receipt_v1") as service:
            source, ref, body = tool_event(service, world)
            claims = {key: body[key] for key in ("status", "label_status")}
            false_claims = {"status": "label_created", "label_status": "created"}
            raw = proposal(
                source,
                json.dumps({**false_claims, "notes": "Unverified invented quotation."}),
                basis="tool_observation",
                object_ref=ref,
                fields=false_claims if conflict == "receipt" else claims,
                content_format="receipt_json_v1",
            )
            result = service.commit("s1", "wrong", raw)
            if mode == "field_grounded":
                prefix = "field_conflict:" if conflict == "receipt" else "receipt_body_conflict:"
                assert result["reason"].startswith(prefix)
                assert service.records() == []
                assert service.store.search(service.attempts_namespace)[0].value["raw"] == raw
            else:
                assert result["status"] == "committed"
                value = service.read(result["id"])["value"]
                assert value["content"] == raw["content"] and value["fields"] == raw["fields"]
                assert value["fields_verification"] == "unchecked"
                assert value["body_fields_verification"] == "unchecked"
                assert value["content_verification"] == value["notes_verification"] == "unchecked"
    finally:
        world.close()


@pytest.mark.parametrize(
    ("content", "content_format", "reason"),
    [
        (
            '{"status":"reserved_label_failed","label_status":"not_created"}',
            None,
            "receipt_content_format_required",
        ),
        (
            '{"status":"reserved_label_failed","label_status":"not_created"}',
            "plain",
            "receipt_content_format_required",
        ),
        ('{"status":', "receipt_json_v1", "receipt_body_invalid_json"),
        ("```json\n{}\n```", "receipt_json_v1", "receipt_body_invalid_json"),
        ("[]", "receipt_json_v1", "receipt_body_invalid_schema"),
        ('{"status":"reserved_label_failed"}', "receipt_json_v1", "receipt_body_invalid_schema"),
        (
            '{"status":1,"label_status":"not_created"}',
            "receipt_json_v1",
            "receipt_body_invalid_schema",
        ),
        (
            '{"status":"reserved_label_failed","label_status":"not_created","extra":"claim"}',
            "receipt_json_v1",
            "receipt_body_invalid_schema",
        ),
        (
            '{"status":"reserved_label_failed","label_status":"not_created","notes":null}',
            "receipt_json_v1",
            "receipt_body_invalid_schema",
        ),
        (
            '{"status":"reserved_label_failed","status":"other","label_status":"not_created"}',
            "receipt_json_v1",
            "receipt_body_invalid_json",
        ),
    ],
)
@pytest.mark.parametrize("mode", ["ref_only", "field_grounded"])
def test_explicit_receipt_invalid_body_preserved_across_store_reopening(
    tmp_path: Path, content: str, content_format: str | None, reason: str, mode: GroundingMode
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path, mode=mode, receipt_contract="explicit_receipt_v1") as service:
            source, ref, body = tool_event(service, world)
            raw = proposal(
                source,
                content,
                basis="tool_observation",
                object_ref=ref,
                fields={key: body[key] for key in ("status", "label_status")},
                content_format=content_format,
                requested={"content": content, "content_format": content_format},
            )
            first = service.commit("s1", "invalid-body", raw)
            assert first["reason"] == reason and first["effect"] == "none"
        with opened(tmp_path, mode=mode, receipt_contract="explicit_receipt_v1") as service:
            attempt = service.store.search(service.attempts_namespace)[0].value
            assert attempt == {"raw": raw, "receipt": first}
            replay = service.commit("s1", "invalid-body", raw)
            assert replay["replayed"] and replay["reason"] == reason
            assert service.records() == []
            assert service.sources()[0]["formation_status"] == "pending"
    finally:
        world.close()


def test_explicit_receipt_tool_binding_history_and_idempotence(tmp_path: Path) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with opened(tmp_path, receipt_contract="explicit_receipt_v1") as service:
            source, ref, body = tool_event(service, world)
            fields = {key: body[key] for key in ("status", "label_status")}
            content = json.dumps({**fields, "notes": "Invented quote and free prose unchecked."})
            arguments = {
                "content": content,
                "basis": "tool_observation",
                "fields": fields,
                "content_format": "receipt_json_v1",
            }
            node = ToolNode(create_service_tools(service))

            async def save() -> dict[str, Any]:
                result = await node.ainvoke(
                    [call("manage_memory", arguments)],
                    config=config(),
                    runtime=Runtime(store=service.store),
                )
                return json.loads(result["messages"][0].content)

            first = asyncio.run(save())
            assert first["status"] == "committed", first
            assert first["receipt_contract"] == "explicit_receipt_v1"
            assert first["body_fields_verification"] == "matches_proposed_fields"
            assert first["receipt_claim_fields"] == ["status", "label_status"]
            assert first["content_verification"] == first["notes_verification"] == "unchecked"
            stored = service.store.get(service.namespace, first["id"]).value["_v13_1"]
            raw = next(iter(stored["proposals"].values()))["raw"]
            assert raw["requested"] == {
                "content": content,
                "action": "create",
                "kind": "semantic",
                "scope": None,
                "basis": "tool_observation",
                "target_query": None,
                "id": None,
                "expected_revision": None,
                "source_ref": None,
                "object_ref": None,
                "fields": fields,
                "content_format": "receipt_json_v1",
            }
            assert raw["source_ref"] == source and raw["object_ref"] == ref
            assert asyncio.run(save())["status"] == "no_change"
            assert service.commit("s1", "different-id", raw)["status"] == "no_change"
            changed = {
                **raw,
                "content": json.dumps({**fields, "notes": "Different unchecked note"}),
            }
            assert service.commit("s1", "conflict", changed)["reason"] == "receipt_already_consumed"
            # A later real receipt can form a new revision; no live lookup edits
            # the earlier observed fields or raw body.
            world.set_label_available("availability", True)
            latest_body = world.complete_label("alice", body["reservation_id"])
            latest_source = service.event_id("s1", "complete", "tool")
            latest_ref = verified_reservation_ref(
                world, "alice", latest_source, "complete_label", latest_body
            )
            assert latest_ref is not None
            service.capture_tool("s1", "complete", "complete_label", latest_body, latest_ref)
            updated_fields = {key: json.loads(latest_body)[key] for key in fields}
            update = proposal(
                latest_source,
                json.dumps(updated_fields),
                basis="tool_observation",
                object_ref=latest_ref.id,
                fields=updated_fields,
                content_format="receipt_json_v1",
                id=first["id"],
                expected_revision=1,
            )
            assert service.commit("s1", "revision", update)["revision"] == 2
            assert service.commit("s1", "revision-replay", update)["reason"] == "revision_conflict"
            assert service.commit("s1", "revision", update)["status"] == "no_change"
            duplicate = service.commit("s1", "same-receipt", {**update, "expected_revision": 2})
            assert duplicate["status"] == "no_change" and duplicate["revision"] == 2
        with opened(tmp_path, receipt_contract="explicit_receipt_v1") as service:
            assert service.read(first["id"], 1)["value"]["content"] == content
            assert service.read(first["id"], 1)["value"]["fields"] == fields
            assert service.read(first["id"])["value"]["fields"] == updated_fields
            history = service.store.get(service.namespace, first["id"]).value["_v13_1"]["history"]
            assert len(history) == 2
    finally:
        world.close()


def test_explicit_receipt_leaves_preferences_and_unbound_tool_prose_unchanged(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, receipt_contract="explicit_receipt_v1") as service:
        preference = proposal(captured(service), "I prefer brief replies, unchecked prose.")
        result = service.commit("s1", "preference", preference)
        assert result["status"] == "committed" and "receipt_contract" not in result
        source = service.capture_tool("s1", "other", "other_public_tool", "Observed prose", None)
        unbound = proposal(source["source_ref"], "Unchecked tool prose", basis="tool_observation")
        result = service.commit("s1", "unbound", unbound)
        assert result["status"] == "committed" and "receipt_contract" not in result
        assert service.read(result["id"])["value"]["content_verification"] == "unchecked"


@pytest.mark.parametrize("mode", ["ref_only", "field_grounded"])
@pytest.mark.parametrize("receipt_contract", ["optional", "explicit_receipt_v1"])
def test_explicit_receipt_minimal_body_found_by_original_public_item(
    tmp_path: Path, mode: GroundingMode, receipt_contract: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    observed = []
    try:
        with opened(
            tmp_path, mode=mode, receipt_contract=receipt_contract, observer=observed.append
        ) as service:
            receipts = {}
            for item in ("parcel", "envelope"):
                source, ref, body = tool_event(service, world, item)
                fields = {key: body[key] for key in ("status", "label_status")}
                raw = proposal(
                    source,
                    json.dumps(fields),
                    basis="tool_observation",
                    object_ref=ref,
                    fields=fields,
                    content_format="receipt_json_v1",
                )
                receipts[item] = service.commit("s1", item, raw)
            assert len(service.records()) == 2
            before = service.records()
            original_get = service.store.get
            source_gets = []

            def get(namespace: tuple[str, ...], key: str, **kwargs: Any) -> Any:
                if namespace == service.sources_namespace:
                    source_gets.append(key)
                return original_get(namespace, key, **kwargs)

            monkeypatch.setattr(service.store, "get", get)
            result = service.search("parcel", include_raw=False)
            if receipt_contract == "optional":
                assert result["records"] == [] and "source_relation" not in result
                assert source_gets == [] and observed == []
                return
            assert [row["id"] for row in result["records"]] == [receipts["parcel"]["id"]]
            assert len(source_gets) == result["source_relation"]["store_get_calls"] == 2
            assert observed[-1]["query"] == "parcel" and observed[-1]["store_get_calls"] == 2
            assert observed[-1]["wall_ns"] > 0 and observed[-1]["cpu_ns"] > 0
            assert {
                json.loads(row["original_result"]["content"])["item_key"]
                for row in observed[-1]["lookups"]
            } == {"parcel", "envelope"}
            assert result["records"][0] == next(
                row for row in before if row["id"] == receipts["parcel"]["id"]
            )
            # A normal search reuses its already loaded raw sources and performs
            # no additional source gets for this relation.
            public = service.search("envelope")
            assert [row["id"] for row in public["records"]] == [receipts["envelope"]["id"]]
            assert public["source_relation"]["store_get_calls"] == 0
            assert observed[-1]["lookups"] == []
            assert service.records() == before
            tools = {tool.name: tool for tool in create_service_tools(service)}
            read = tools["read_memory"].invoke(
                call("read_memory", {"query": "envelope"}, "natural-read"), config=config(mode)
            )
            assert json.loads(read.content)["id"] == receipts["envelope"]["id"]
            assert service.search("missingparcel", include_raw=False)["records"] == []
            with opened(tmp_path, "bob", mode, receipt_contract) as other:
                source, ref, body = tool_event(other, world, "foreignparcel")
                fields = {key: body[key] for key in ("status", "label_status")}
                other.commit(
                    "s1",
                    "foreign",
                    proposal(
                        source,
                        json.dumps(fields),
                        basis="tool_observation",
                        object_ref=ref,
                        fields=fields,
                        content_format="receipt_json_v1",
                    ),
                )
            assert service.search("foreignparcel", include_raw=False)["records"] == []
            assert service.search("")["records"] == sorted(before, key=lambda row: row["id"])
            assert "source_relation" not in service.search("")
            # Public updates discover the exact target by original item, without
            # a user-supplied memory id or source/object ref.
            body_text = world.get_reservation("alice", "parcel")
            source = service.event_id("s1", "rediscovery", "tool")
            ref = verified_reservation_ref(world, "alice", source, "get_reservation", body_text)
            assert ref is not None
            service.capture_tool("s1", "rediscovery", "get_reservation", body_text, ref)
            fields = {key: json.loads(body_text)[key] for key in ("status", "label_status")}
            update = tools["manage_memory"].invoke(
                call(
                    "manage_memory",
                    {
                        "action": "update",
                        "target_query": "parcel",
                        "content": json.dumps(fields),
                        "basis": "tool_observation",
                        "fields": fields,
                        "content_format": "receipt_json_v1",
                    },
                    "natural-update",
                ),
                config=config(mode),
            )
            receipt = json.loads(update.content)
            assert receipt["id"] == receipts["parcel"]["id"] and receipt["revision"] == 2
            assert service.read(receipt["id"], 1)["value"]["source_ref"] != source
            assert observed[-1]["store_get_calls"] == 2

            # Failed actual source I/O is counted and its first error is preserved.
            def fail(namespace: tuple[str, ...], key: str, **kwargs: Any) -> Any:
                if namespace == service.sources_namespace:
                    raise OSError("source relation Store get failed")
                return original_get(namespace, key, **kwargs)

            monkeypatch.setattr(service.store, "get", fail)
            with pytest.raises(OSError, match="source relation Store get failed"):
                service.search("parcel", include_raw=False)
            assert observed[-1]["store_get_calls"] == 1
            assert observed[-1]["lookups"][0]["error"] == "source relation Store get failed"
    finally:
        world.close()


@pytest.mark.parametrize("invalid", [None, True, 1, [], {}, "", "explicit_receipt_v2"])
def test_explicit_receipt_configuration_rejects_unknown_types_and_values(
    tmp_path: Path, invalid: Any
) -> None:
    with pytest.raises(ValueError, match="V13_MEMORY_RECEIPT_CONTRACT_INVALID"):
        with opened(tmp_path, receipt_contract=invalid):
            pass


def test_revisions_conflicts_and_duplicate_proposals_preserve_history(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = captured(service)
        first = service.commit("s1", "p1", proposal(source))
        assert service.commit("s1", "p1", proposal(source))["status"] == "no_change"
        newer = captured(service, "m2", "Now prefer detailed replies")
        raw = proposal(newer, "I prefer detailed replies", id=first["id"], expected_revision=1)
        updated = service.commit("s1", "p2", raw)
        assert updated["revision"] == 2
        conflict = service.commit("s1", "p3", {**raw, "content": "racing stale update"})
        assert conflict["reason"] == "revision_conflict"
        assert service.read(first["id"], 1)["value"]["content"] == "I prefer short replies"
        assert service.read(first["id"])["value"]["content"] == "I prefer detailed replies"
        stored = service.store.get(service.namespace, first["id"]).value
        assert len(stored["_v13_1"]["proposals"]) == 3
        changed_identity = service.commit("s1", "p2", {**raw, "id": "another-record"})
        assert changed_identity["reason"] == "proposal_id_conflict"


def test_legacy_source_unknown_is_readable_and_not_silently_migrated(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        service.store.put(service.namespace, "legacy", {"content": "old preference"})
        assert service.read("legacy")["source_status"] == "unknown"
        rejected = service.commit("s1", "p1", proposal(captured(service), id="legacy"))
        assert rejected["reason"] == "legacy_record_requires_explicit_migration"
        assert service.store.get(service.namespace, "legacy").value == {"content": "old preference"}


def test_sdk_write_failure_returns_no_false_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened(tmp_path) as service:
        source = captured(service)

        def fail(*args: Any, **kwargs: Any) -> None:
            raise OSError("actual write unavailable")

        monkeypatch.setattr(service.store, "put", fail)
        with pytest.raises(OSError, match="actual write unavailable"):
            service.commit("s1", "p1", proposal(source))
        assert service.records() == [] and service.source(source) is not None


def test_embedding_failure_reads_durable_raw_events_and_formed_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened(tmp_path) as service:
        source = captured(service)
        receipt = service.commit("s1", "p1", proposal(source))
        original = service.store.search

        def search(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("query"):
                raise ConnectionError("embedding down")
            return original(*args, **kwargs)

        monkeypatch.setattr(service.store, "search", search)
        result = service.search("short", dense=True)
        assert result["degraded"] and result["retrieval"] == "raw_keyword"
        assert result["degradation_reason"] == "dense_unavailable:ConnectionError"
        assert result["records"][0]["id"] == receipt["id"]
        assert result["raw_events"][0]["content"] == "Keep short replies"


def test_actual_async_toolnode_discovers_update_and_historical_revision(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        captured(service)
        node = ToolNode(create_service_tools(service))

        async def execute() -> None:
            result = await node.ainvoke(
                [call("manage_memory", {"content": "short replies"})],
                config=config(),
                runtime=Runtime(store=service.store),
            )
            first = json.loads(result["messages"][0].content)
            assert first["status"] == "committed"
            captured(service, "m2", "Now detailed replies")
            result = await node.ainvoke(
                [
                    call(
                        "manage_memory",
                        {
                            "action": "update",
                            "content": "detailed replies",
                            "target_query": "short",
                        },
                        "p2",
                    )
                ],
                config=config(),
                runtime=Runtime(store=service.store),
            )
            second = json.loads(result["messages"][0].content)
            assert second["id"] == first["id"] and second["revision"] == 2
            result = await node.ainvoke(
                [call("read_memory", {"query": "detailed", "revision": 1}, "read")],
                config=config(),
                runtime=Runtime(store=service.store),
            )
            assert json.loads(result["messages"][0].content)["value"]["content"] == "short replies"

        asyncio.run(execute())


def test_service_mcp_uses_real_http_and_same_record_receipts(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        captured(service)
        with MemoryMCP(service.store, "run", "field_grounded", "alice", service=service) as peer:
            receipt = peer.call(
                "manage_memory", {"content": "short replies"}, "p1", origin="test", config=config()
            )
            first = json.loads(receipt.content)
            assert first["status"] == "committed"
            assert peer.records(config())[0]["value"]["revision"] == 1
            assert peer.retrieve("short", 10, config())[0]["id"] == first["id"]
            with pytest.raises(ValueError, match="SCOPE_CHANGED"):
                peer.call(
                    "read_memory",
                    {"id": first["id"]},
                    "wrong-owner",
                    origin="test",
                    config={"configurable": {"user_id": "bob"}},
                )


def test_real_process_reopening_and_competing_revision_writers(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = captured(service)
        receipt = service.commit("s1", "initial", proposal(source))
    script = """
import json,sys
from pathlib import Path
from langgraph.store.sqlite import SqliteStore
from milai_lab.memory.service import MemoryService
root=Path(sys.argv[1])
with SqliteStore.from_conn_string(str(root/'memory.sqlite')) as store:
    service=MemoryService(store,('langmem','run','field_grounded','alice'),'alice',root/'memory.lock')
    data=json.loads(sys.argv[2])
    print(json.dumps(service.commit('s1',sys.argv[3],data)))
"""
    raw = proposal(source, "one concurrent revision", id=receipt["id"], expected_revision=1)
    processes = [
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", script, str(tmp_path), json.dumps(raw), key],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for key in ("writer-a", "writer-b")
    ]
    outcomes = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        outcomes.append(json.loads(stdout))
    assert sorted(row["status"] for row in outcomes) == ["committed", "rejected"]
    with opened(tmp_path) as reopened:
        assert reopened.read(receipt["id"])["value"]["revision"] == 2
        assert reopened.read(receipt["id"], 1)["value"]["content"] == "I prefer short replies"
        assert reopened.source(source)["content"] == "Keep short replies"


@pytest.mark.parametrize("include_raw", [False, True])
def test_fixed_chinese_bank_retrieves_commuting_card_without_unrelated_or_foreign_records(
    tmp_path: Path, include_raw: bool
) -> None:
    card = "用户通勤时更喜欢选择火车。"
    distractor = "用户每天勤于阅读，通话只在周末。"  # noqa: RUF001 - original CJK punctuation
    with opened(tmp_path, "bob") as foreign:
        foreign_source = captured(foreign, content=card)
        foreign.commit("s1", "foreign", proposal(foreign_source, card))
    with opened(tmp_path) as service:
        source = captured(service, "commuting", card)
        target = service.commit("s1", "commuting", proposal(source, card))
        other = captured(service, "reading", distractor)
        service.commit("s1", "reading", proposal(other, distractor))
        before = service.records()

        result = service.search("通勤方式偏好", include_raw=include_raw)
        assert result["retrieval"] == "raw_keyword"
        assert [row["id"] for row in result["records"]] == [target["id"]]
        assert [row["event_id"] for row in result["raw_events"]] == (
            [source] if include_raw else []
        )
        assert service.search("天文学")["status"] == "no_results"
        # Only an explicit empty/whitespace query enumerates this owner's bank.
        assert service.search("！？")["status"] == "no_results"  # noqa: RUF001
        for empty in ("", " \t "):
            enumerated = service.search(empty, include_raw=False)["records"]
            assert [row["id"] for row in enumerated] == sorted(row["id"] for row in before)
        assert service.records() == before


@pytest.mark.parametrize(
    ("query", "card", "distractor"),
    [
        ("ART!", "I enjoy art exhibitions.", "I study cartography at weekends."),
        ("CAFÉ!", "I meet friends at Cafe\u0301 after work.", "I listen to piano music."),
        ("القراءة، المساء؟", "أفضل القراءة في المساء.", "أمارس السباحة صباحاً."),
        ("पसंदीदा, भोजन?", "मेरा पसंदीदा भोजन दाल है।", "मैं सुबह तैरता हूँ।"),
        ("配送状況", "配送の状況を確認しました。", "週末は映画を観ます。"),
        ("배송상태", "배송의 상태를 확인했습니다.", "주말에는 영화를 봅니다."),
        ("Python入门！", "我想阅读Python的入门教程。", "我喜欢徒步旅行。"),  # noqa: RUF001
        ("茶", "我喝茶。", "我喜欢散步。"),
    ],
)
def test_multilingual_fixed_bank_keyword_queries_preserve_original_content(
    tmp_path: Path, query: str, card: str, distractor: str
) -> None:
    with opened(tmp_path) as service:
        source = captured(service, "target", card)
        target = service.commit("s1", "target", proposal(source, card))
        other = captured(service, "unrelated", distractor)
        service.commit("s1", "unrelated", proposal(other, distractor))

        result = service.search(query)
        assert [row["id"] for row in result["records"]] == [target["id"]]
        assert [row["event_id"] for row in result["raw_events"]] == [source]
        assert result["records"][0]["value"]["content"] == card
        assert result["raw_events"][0]["content"] == card
        assert service.source(source)["source_revision"] == 1
        assert service.source(source)["content"] == card
