"""Mechanical SDK/ToolNode checks; no real model, embedding or scorer inputs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterator
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
    root: Path, owner: str = "alice", mode: GroundingMode = "field_grounded"
) -> Iterator[MemoryService]:
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        yield MemoryService(
            store, ("langmem", "run", mode, owner), owner, root / "memory.lock", mode=mode
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


def test_source_capture_is_immutable_unformed_and_hashes_actual_body(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        source = captured(service)
        assert service.sources()[0]["formation_status"] == "pending"
        event = service.source(source)
        assert event is not None
        assert event["content_sha256"] == hashlib.sha256(b"Keep short replies").hexdigest()
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


@pytest.mark.parametrize("wrong", ["nonexistent", "foreign"])
def test_source_and_object_refs_are_owner_bound(tmp_path: Path, wrong: str) -> None:
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
        with opened(tmp_path) as service:
            source = captured(service)
            bad = foreign_source if wrong == "foreign" else "src-nonexistent"
            rejected = service.commit("s1", "p1", proposal(bad))
            assert rejected["reason"] == "source_not_found_or_not_owned"
            rejected = service.commit(
                "s1",
                "p2",
                proposal(
                    source, object_ref=(foreign_ref if wrong == "foreign" else "imaginary-object")
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
        assert service.source(source)["content_sha256"] == hashlib.sha256(card.encode()).hexdigest()
