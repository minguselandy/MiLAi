"""Public SQLite counters and cache contracts; no formal timing or provider network."""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any

import pytest
from test_v13_2_history_discovery import history, public_turn
from test_v13_2_packet import Embeddings, bound

from milai_lab.memory.service import MemoryService
from milai_lab.methods.grounded_memory import GroundedMemoryRecipe
from milai_lab.runners.v13_1_d0 import _recipe_settings


@pytest.fixture(autouse=True)
def no_provider_sockets(monkeypatch: pytest.MonkeyPatch) -> Any:
    attempts = []

    def blocked(*args: Any, **kwargs: Any) -> Any:
        attempts.append(1)
        raise AssertionError("engineering provider network forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    yield
    assert attempts == []


def recipe(service: MemoryService, embeddings: Any, **kwargs: Any) -> GroundedMemoryRecipe:
    return GroundedMemoryRecipe(
        service,
        lambda text: len(text) // 4,
        embeddings=embeddings,
        raw_index_storage="owner_bank_v1",
        **kwargs,
    )


def test_same_history_documents_vectors_rank_selection_and_old_inline_scan_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, _ = history(service)
        for index in range(20):
            bound.user(service, "unrelated-" + str(index), "unrelated " * 50)
        public_turn(service)
        original_embeddings, moved_embeddings = Embeddings(), Embeddings()
        original = GroundedMemoryRecipe(
            service, lambda text: len(text) // 4, embeddings=original_embeddings
        )
        def fixed_delivery(candidate: GroundedMemoryRecipe) -> dict[str, Any]:
            # Two storage layouts must produce identical material given the same issued IDs.
            ids = iter(uuid.UUID(int=i) for i in range(1, 100))
            with monkeypatch.context() as issue:
                issue.setattr(uuid, "uuid4", lambda: next(ids))
                return candidate.prepare_context(
                    "PINE_TOKEN", owner="alice", session="s1", turn_id="query"
                )

        first = fixed_delivery(original)
        index_before = service.store.get(original.namespace, "raw_index").value
        authority = {
            item.key: item.value
            for item in service.store.search(service.namespace, limit=100)
            if item.namespace == service.namespace
        }
        documents_before, _, _ = original._snapshot(service.event_id("s1", "query", "user"))
        counters = {"returned_rows": 0, "raw_index_rows": 0, "raw_index_bytes": 0}
        search = service.store.search

        def counted(namespace: tuple[str, ...], *args: Any, **kwargs: Any) -> Any:
            rows = search(namespace, *args, **kwargs)
            counters["returned_rows"] += len(rows)
            for row in rows:
                if row.key == "raw_index":
                    counters["raw_index_rows"] += 1
                    counters["raw_index_bytes"] += len(json.dumps(row.value).encode())
            return rows

        monkeypatch.setattr(service.store, "search", counted)
        cached = original.prepare_context(
            "PINE_TOKEN", owner="alice", session="s1", turn_id="query"
        )
        baseline_scan = dict(counters)
        assert cached["retrieval_calls"] == 0 and baseline_scan["raw_index_rows"] > 0
        # Only derived packet state in this new temporary bank is reset for exact-input comparison.
        for item in search(original.namespace, limit=100):
            if item.namespace == original.namespace and item.key != "raw_index":
                service.store.delete(item.namespace, item.key)
        events = []
        moved = recipe(service, moved_embeddings, observer=events.append)
        second = fixed_delivery(moved)
        assert service.store.get(original.namespace, "raw_index").value == index_before
        assert second["packet"] == first["packet"] and second["material"] == first["material"]
        assert second["selected"] == first["selected"]
        documents_after, _, _ = moved._snapshot(service.event_id("s1", "query", "user"))
        assert documents_after == documents_before
        envelope = service.store.get(moved.index_namespace, "raw_index").value
        assert envelope["status"] == "complete" and envelope["owner"] == "alice"
        assert envelope["bank_namespace"] == list(service.namespace)
        for key in ("chunks", "vectors", "index_version"):
            assert envelope["index"][key] == index_before[key]
        assert original._retrieve(documents_before, "PINE_TOKEN") == moved._retrieve(
            documents_before, "PINE_TOKEN"
        )
        assert any(row.get("reason") == "legacy_inline_ignored" for row in events)
        assert (
            service.store.get(original.namespace, "raw_index").value["chunks"]
            == index_before["chunks"]
        )
        for key in counters:
            counters[key] = 0
        moved.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        old_inline_scan = dict(counters)
        assert old_inline_scan["raw_index_rows"] > 0  # Existing inline rows were not migrated away.
        # Simulate a fresh bank with only the detached index, within this disposable test DB.
        service.store.delete(original.namespace, "raw_index")
        for key in counters:
            counters[key] = 0
        query_count = len(moved_embeddings.queries)
        fresh = moved.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        fresh_scan = dict(counters)
        assert fresh["retrieval_calls"] == 0 and len(moved_embeddings.queries) == query_count
        assert fresh_scan["raw_index_rows"] == fresh_scan["raw_index_bytes"] == 0
        # Issued source/history snapshots can add rows; the detached path must stop
        # scanning the large inline index, rather than assert a total Store-row speedup.
        assert fresh_scan["raw_index_bytes"] < old_inline_scan["raw_index_bytes"]
        assert {
            item.key: item.value
            for item in search(service.namespace, limit=100)
            if item.namespace == service.namespace
        } == authority
        old = [row for row in fresh["packet"]["items"] if row["type"] == "historical_record"]
        assert old and old[0]["record"]["id"] == memory_id and old[0]["record"]["revision"] == 1
        assert fresh["material_tokens"] <= 2048 and fresh["packet"]["candidate_count"] <= 6
        print(
            json.dumps(
                {
                    "engineering_scan_only": True,
                    "baseline_inline": baseline_scan,
                    "opt_in_with_old_inline_preserved": old_inline_scan,
                    "fresh_without_inline_test_only": fresh_scan,
                    "provider_socket_attempts": 0,
                }
            )
        )


def test_reopen_reuses_vectors_owner_bank_isolation_and_invalid_envelope_rebuild(
    tmp_path: Path,
) -> None:
    with bound.opened(tmp_path) as service:
        bound.user(service, "past", "PINE_TOKEN actual source")
        public_turn(service)
        first = recipe(service, Embeddings())
        documents, _, _ = first._snapshot(service.event_id("s1", "query", "user"))
        ranking = first._retrieve(documents, "PINE_TOKEN")
        namespace = first.index_namespace
        saved = service.store.get(namespace, "raw_index").value
        bob = MemoryService(
            service.store,
            ("bound", "bob"),
            "bob",
            tmp_path / "bob.lock",
            mutation_contract="event_bound_v1",
        )
        another = MemoryService(
            service.store,
            ("another", "alice"),
            "alice",
            tmp_path / "other.lock",
            mutation_contract="event_bound_v1",
        )
        assert (
            len(
                {
                    namespace,
                    recipe(bob, Embeddings()).index_namespace,
                    recipe(another, Embeddings()).index_namespace,
                }
            )
            == 3
        )
        assert all(item.namespace != namespace for item in service.store.search(service.namespace))
    with bound.opened(tmp_path) as reopened:
        embeddings = Embeddings()
        loaded = recipe(reopened, embeddings)
        assert loaded.index_namespace == namespace
        assert loaded._retrieve(documents, "PINE_TOKEN") == ranking
        assert embeddings.documents == [] and embeddings.queries == ["PINE_TOKEN"]
        for field, bad in (
            ("owner", "bob"),
            ("bank_namespace", ["other", "alice"]),
            ("schema", "unknown"),
            ("index", None),
        ):
            reopened.store.put(namespace, "raw_index", {**saved, field: bad}, index=False)
            rebuild = Embeddings()
            events = []
            candidate = recipe(reopened, rebuild, observer=events.append)
            assert candidate._retrieve(documents, "PINE_TOKEN") == ranking
            assert len(rebuild.documents) == 1
            assert reopened.store.get(namespace, "raw_index").value["status"] == "complete"
            assert any("invalid" in row.get("reason", "") for row in events), events


def test_failed_embedding_is_lexical_fallback_pending_and_reopens_to_rebuild(
    tmp_path: Path,
) -> None:
    class Failing(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("offline embedding failed")

    with bound.opened(tmp_path) as service:
        source = bound.user(service, "past", "PINE_TOKEN")
        public_turn(service)
        failed = recipe(service, Failing())
        result = failed.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        assert result["retrieval"] == "dense_unavailable:RuntimeError"
        assert result["selected"] and service.source(source)["content"] == "PINE_TOKEN"
        assert service.store.get(failed.index_namespace, "raw_index").value["status"] == "pending"
        namespace = failed.index_namespace
        documents, _, _ = failed._snapshot(service.event_id("s1", "query", "user"))
    with bound.opened(tmp_path) as service:
        embeddings = Embeddings()
        events = []
        recovered = recipe(service, embeddings, observer=events.append)
        assert recovered._retrieve(documents, "PINE_TOKEN")[1] == "bm25_dense_rrf60"
        assert len(embeddings.documents) == 1
        assert service.store.get(namespace, "raw_index").value["status"] == "complete"
        assert any(row.get("reason") == "pending_rebuild" for row in events)


def test_cache_and_dirty_selection_keep_read_cas_and_do_not_requery(tmp_path: Path) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, _ = history(service)
        public_turn(service)
        embeddings = Embeddings()
        candidate = recipe(service, embeddings)
        first = candidate.prepare_context(
            "PINE_TOKEN", owner="alice", session="s1", turn_id="query"
        )
        stale = service.read(memory_id)["candidate_handle"]
        current = bound.user(service, "change", "Actual third revision request")
        service.bind_source_boundary("s1", "change", [current])
        assert service.revise("s1", "change", stale, {"content": "third actual value"})["ok"]
        second = candidate.prepare_context(
            "PINE_TOKEN", owner="alice", session="s1", turn_id="query"
        )
        assert first["selected"] == second["selected"] and second["retrieval_calls"] == 0
        assert len(embeddings.queries) == 1
        assert not service.revise("s1", "stale", stale, {"content": "wrong"})["ok"]
        assert service.read(memory_id)["value"]["revision"] == 3


def test_default_storage_and_public_opt_in_config_are_explicit(tmp_path: Path) -> None:
    with bound.opened(tmp_path) as service:
        default = GroundedMemoryRecipe(service, lambda text: len(text) // 4)
        assert default.index_namespace == default.namespace
        assert "raw_index_storage" not in default.policy
    with bound.opened(tmp_path, contract="legacy") as service:
        with pytest.raises(ValueError, match="REQUIRES_EVENT_BOUND"):
            recipe(service, Embeddings())
    with pytest.raises(ValueError, match="REQUIRES_BOUND_READER"):
        _recipe_settings({"memory_derived_index_storage": "owner_bank_v1"})
    settings = json.loads(Path("configs/v13-2-e0-normal.json").read_text())
    assert "raw_index_storage" not in _recipe_settings(settings)
    enabled = _recipe_settings({**settings, "memory_derived_index_storage": "owner_bank_v1"})
    assert enabled["raw_index_storage"] == "owner_bank_v1"


@pytest.mark.parametrize(
    "namespace",
    [
        ("d", "alice"),
        ("D", "alice"),
        ("derived-raw-index-v1", "alice"),
        ("a_b", "alice"),
        ("a", "b", "alice"),
    ],
)
def test_detached_index_is_absent_from_public_sdk_text_prefix_scan(
    tmp_path: Path, namespace: tuple[str, ...]
) -> None:
    with bound.opened(tmp_path) as opened:
        service = MemoryService(
            opened.store, namespace, "alice", tmp_path / "prefix.lock",
            mutation_contract="event_bound_v1",
        )
        source = bound.user(service, "past", "PINE_TOKEN actual source")
        public_turn(service)
        candidate = recipe(service, Embeddings())
        documents, _, _ = candidate._snapshot(service.event_id("s1", "query", "user"))
        assert candidate._retrieve(documents, "PINE_TOKEN")[1] == "bm25_dense_rrf60"
        assert service.store.get(candidate.index_namespace, "raw_index") is not None
        assert service.source(source)["content"] == "PINE_TOKEN actual source"
        assert all(
            item.namespace != candidate.index_namespace
            for item in service.store.search(namespace, limit=100)
        )
        if namespace[0].casefold().startswith("d"):
            assert candidate.index_namespace[0] == "separate-raw-index-v1"


def test_document_contract_binding_mismatch_forces_rebuild(tmp_path: Path) -> None:
    with bound.opened(tmp_path) as service:
        bound.user(service, "past", "PINE_TOKEN actual source")
        public_turn(service)
        original = recipe(service, Embeddings())
        documents, _, _ = original._snapshot(service.event_id("s1", "query", "user"))
        ranking = original._retrieve(documents, "PINE_TOKEN")
        saved = service.store.get(original.index_namespace, "raw_index").value
        service.store.put(
            original.index_namespace, "raw_index",
            {**saved, "document_contract": "unknown"}, index=False,
        )
        embeddings, events = Embeddings(), []
        candidate = recipe(service, embeddings, observer=events.append)
        assert candidate._retrieve(documents, "PINE_TOKEN") == ranking
        assert len(embeddings.documents) == 1
        assert any(row.get("reason") == "binding_invalid_rebuild" for row in events)
        rebuilt = service.store.get(candidate.index_namespace, "raw_index").value
        assert rebuilt["status"] == "complete"
        assert rebuilt["document_contract"] == saved["document_contract"]
        for key in ("chunks", "vectors", "index_version"):
            assert rebuilt["index"][key] == saved["index"][key]


@pytest.mark.parametrize("prefix", ["%", "_"])
def test_opt_in_rejects_leading_sdk_wildcard_prefix(tmp_path: Path, prefix: str) -> None:
    with bound.opened(tmp_path) as opened:
        service = MemoryService(
            opened.store, (prefix, "alice"), "alice", tmp_path / "wildcard.lock",
            mutation_contract="event_bound_v1",
        )
        # This restriction belongs to the opt-in namespace separation guarantee.
        assert GroundedMemoryRecipe(service, lambda text: len(text) // 4).namespace
        with pytest.raises(ValueError, match="BANK_PREFIX_REQUIRES_LITERAL"):
            recipe(service, Embeddings())
