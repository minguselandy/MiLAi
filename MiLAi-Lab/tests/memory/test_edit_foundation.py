"""Real Store checks for ordinary identities and the retained functional boundaries."""

from __future__ import annotations

import copy
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import FunctionalRejection, namespace
from milai_lab.memory.service import MemoryService


@contextmanager
def opened(root: Path, owner: str = "alice"):
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        yield MemoryService(
            store,
            ("edit-foundation", owner),
            owner,
            root / "lock",
            functional_contract="functional_v1",
        )


def incoming(service: MemoryService, key: str, text: str, *, phase: str = "start"):
    ref = service.capture_user("session", key, text)["source_ref"]
    service.bind_source_boundary("session", key, [ref])
    service.bind_public_turn("session", key, ref, config_version="ordinary-v1", phase=phase)
    config = {
        "configurable": {
            "user_id": service.owner,
            "v13_session": "session",
            "v13_turn_id": key,
            "v13_config_version": "ordinary-v1",
        }
    }
    fragment = service.source_fragments(ref)[0]["fragment_handle"]
    return ref, fragment, config


def test_source_is_immutable_without_digest_and_reopens(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        ref, fragment, _ = incoming(service, "first", "A source with an unresolved start date.")
        source = copy.deepcopy(service.source(ref))
        assert source["source_revision"] == 1
        assert "content_sha256" not in source
        with pytest.raises(ValueError, match="V13_SOURCE_EVENT_CHANGED"):
            service.capture_user("session", "first", "Changed text under the same event ID.")
    with opened(tmp_path) as service:
        assert service.source(ref) == source
        assert service.source_fragment(fragment)["content"] == source["content"]
        incoming(service, "first", source["content"], phase="resume")


def test_equal_public_ids_are_isolated_across_owners_and_banks(tmp_path: Path) -> None:
    with opened(tmp_path, "alice") as alice, opened(tmp_path, "bob") as bob:
        alice_ref, alice_fragment, _ = incoming(alice, "same-id", "Same literal source.")
        bob_ref, bob_fragment, _ = incoming(bob, "same-id", "Same literal source.")
        assert alice_ref != bob_ref
        assert alice_fragment != bob_fragment
        assert alice.source(bob_ref) is None
        with pytest.raises(FunctionalRejection, match="FRAGMENT_NOT_ISSUED"):
            alice.source_fragment(bob_fragment)
        other_bank = MemoryService(
            alice.store,
            ("another-bank", "alice"),
            "alice",
            tmp_path / "another-lock",
            functional_contract="functional_v1",
        )
        other_ref, other_fragment, _ = incoming(other_bank, "same-id", "Same literal source.")
        assert other_ref != alice_ref
        with pytest.raises(FunctionalRejection, match="FRAGMENT_NOT_ISSUED"):
            alice.source_fragment(other_fragment)


def test_revision_conflict_history_and_fixed_snapshot_survive_reopen(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        _, fragment, config = incoming(service, "first", "Run twice weekly; start date unknown.")
        memory = FunctionalMemory(service, len, material_limit=24000)
        saved = memory.save(config, "save", "Run twice weekly; start date unknown.", [fragment])
        initial = service.read(saved["id"])
        history = service.history_index(saved["id"], limit=1)
        _, correction, config = incoming(
            service, "next", "Change to three times; date still unknown."
        )
        updated = memory.update(
            config,
            "update",
            initial["candidate_handle"],
            [
                {
                    "field": "content",
                    "op": "set",
                    "value": "Run three times; start date unknown.",
                    "fragment_handles": [correction],
                }
            ],
        )
        assert updated["revision"] == 2
        conflict = memory.update(
            config,
            "stale",
            initial["candidate_handle"],
            [
                {
                    "field": "content",
                    "op": "set",
                    "value": "Another correction.",
                    "fragment_handles": [correction],
                }
            ],
        )
        assert conflict["reason"] == "revision_conflict"
        assert service.read(saved["id"], 1)["value"] == initial["value"]
        assert history["revisions"] == [1]
    with opened(tmp_path) as service:
        assert service.candidate(initial["candidate_handle"])["revision"] == 1
        assert service.read(saved["id"])["value"]["revision"] == 2
        assert service.read(saved["id"], 1)["value"] == initial["value"]


def test_postcommit_exception_recovers_same_operation_without_second_revision(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as service:
        _, fragment, config = incoming(service, "first", "A durable fact.")
        memory = FunctionalMemory(service, len, material_limit=24000)
        original_put = service.store.put
        failed = False

        def put_then_raise(ns, key, value, **kwargs):
            nonlocal failed
            original_put(ns, key, value, **kwargs)
            if ns == service.namespace and not failed:
                failed = True
                raise OSError("connection lost after durable commit")

        service.store.put = put_then_raise
        with pytest.raises(Exception, match="semantic_commit"):
            memory.save(config, "actual-operation", "A durable fact.", [fragment])
    with opened(tmp_path) as service:
        incoming(service, "first", "A durable fact.", phase="resume")
        memory = FunctionalMemory(service, len, material_limit=24000)
        receipt = memory.save(config, "actual-operation", "A durable fact.", [fragment])
        assert receipt["replayed"] and receipt["original_status"] == "committed"
        records = [row for row in service.records() if row["ok"]]
        assert len(records) == 1 and records[0]["value"]["revision"] == 1


def test_legacy_identifiers_are_read_as_strings_after_actual_reopen(tmp_path: Path) -> None:
    old_source, old_record, old_handle = "src-" + "a" * 64, "b" * 64, "cand-" + "c" * 24
    version: dict[str, Any] = {
        "revision": 1,
        "content": "Preserved historical text.",
        "kind": "semantic",
        "scope": {},
        "basis": "user_statement",
        "fields": {},
        "source_ref": old_source,
        "source_refs": [old_source],
        "object_ref": None,
        "source_bindings": [
            {"source_ref": old_source, "role": "user", "content_sha256": "old archival field"}
        ],
    }
    with opened(tmp_path) as service:
        source = {
            "event_id": old_source,
            "owner": "alice",
            "session": "old-session",
            "role": "user",
            "origin": "public_user_message",
            "content": version["content"],
            "content_sha256": "old archival field",
            "observed_at": "2026-09-01",
            "object_ref": None,
        }
        service.store.put(service.sources_namespace, old_source, source, index=False)
        service.store.put(
            namespace(service),
            "capture:" + old_source,
            {"source_ref": old_source, "event_sha256": "historical only"},
            index=False,
        )
        service.store.put(
            service.namespace,
            old_record,
            {
                "content": version["content"],
                "_v13_1": {
                    "owner": "alice",
                    "revision": 1,
                    "current": version,
                    "history": [version],
                    "proposals": {},
                },
            },
            index=False,
        )
        service.store.put(
            service.candidates_namespace,
            old_handle,
            {
                "owner": "alice",
                "namespace": list(service.namespace),
                "record_id": old_record,
                "revision": 1,
                "support_sources": version["source_bindings"],
                "version_sha256": "historical only",
            },
            index=False,
        )
    with opened(tmp_path) as service:
        assert service.source(old_source)["content"] == version["content"]
        assert service.read(old_record)["value"] == version
        assert service.candidate(old_handle)["record_id"] == old_record
        assert service.read(old_record, 1)["value"] == version


def test_forget_revokes_issued_fragment_and_candidate_after_reopen(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        _, fragment, config = incoming(service, "first", "A selected private arrangement.")
        memory = FunctionalMemory(service, len, material_limit=24000)
        saved = memory.save(config, "save", "A selected private arrangement.", [fragment])
        handle = service.read(saved["id"])["candidate_handle"]
        receipt = service.forget("session", "forget", handle)
        assert receipt["effect"] == "visibility_only" and not receipt["physical_erasure"]
    with opened(tmp_path) as service:
        assert service.candidate(handle) is None
        assert service.read(saved["id"])["status"] == "visibility_revoked"
        with pytest.raises(FunctionalRejection, match="SOURCE_UNAVAILABLE"):
            service.source_fragment(fragment)
