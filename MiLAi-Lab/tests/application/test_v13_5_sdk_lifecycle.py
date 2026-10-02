"""Actual local SDK snapshot/close/reopen, without extraction, ranking or HTTP."""

from __future__ import annotations

import importlib.util
import socket
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from milai_lab.application.functional import FunctionalApplication


@pytest.mark.parametrize("workflow", ["reservation", "document"])
@pytest.mark.parametrize("fail_after_open", [False, True])
def test_actual_native_sdk_snapshot_before_close_and_independent_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workflow: str, fail_after_open: bool,
) -> None:
    if importlib.util.find_spec("mem0") is None:
        pytest.fail(
            "The pinned external SDK test environment is required; never download dependencies"
        )
    monkeypatch.setenv("MEM0_TELEMETRY", "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    from mem0 import Memory
    from mem0.memory.storage import SQLiteManager
    from qdrant_client import QdrantClient, models

    from milai_lab.integrations.memory.mem0 import Mem0NativeRuntime

    order, evidence = [], {}
    target = str(uuid.uuid4())
    qpath, hpath = tmp_path / "vectors", tmp_path / "history.sqlite"

    def exercise() -> None:
        with ExitStack() as finalizers:
            stack = finalizers.enter_context(ExitStack())
            app = stack.enter_context(
                FunctionalApplication.open(tmp_path / "app", workflow, "alice")
            )
            if workflow == "reservation":
                app.world.reserve_and_label("alice", "mechanical", 1, "local", "box")
            else:
                app.world.create_or_update_draft("alice", "mechanical", "body", 0, "")
            client = QdrantClient(path=str(qpath))
            history = SQLiteManager(str(hpath))
            # Actual SDK get_all/close with persistent Qdrant and SQLite. The
            # finite vector facade deliberately does not claim extraction tests.
            memory = Memory.__new__(Memory)
            memory.db, memory._entity_store = history, None
            memory.vector_store = SimpleNamespace(client=client, list=lambda filters, top_k:
                client.scroll("proof", limit=top_k, scroll_filter=models.Filter(must=[
                    models.FieldCondition(key=k, match=models.MatchValue(value=v))
                    for k, v in filters.items()])))
            native = Mem0NativeRuntime.__new__(Mem0NativeRuntime)
            native.memory, native.run_id, native.arm_id = memory, "run", "arm"

            def close() -> None:
                order.append("close")
                native.close()

            stack.callback(close)
            client.create_collection("proof", vectors_config=models.VectorParams(
                size=2, distance=models.Distance.COSINE))
            client.upsert("proof", points=[models.PointStruct(id=target, vector=[1.0, 0.0],
                payload={"data": "Native note", "user_id": native._user_id("alice"),
                         "hash": "original", "created_at": "2026-01-01T00:00:00Z",
                         "updated_at": "2026-01-01T00:00:00Z"})])
            history.add_history(target, None, "Native note", "ADD")

            def snapshot() -> None:
                order.append("snapshot")
                evidence.update(backend=native.snapshot("alice"), application=app.snapshot())

            finalizers.callback(snapshot)
            if fail_after_open:
                raise RuntimeError("PRIMARY_FAILURE_AFTER_OPEN")

    if fail_after_open:
        with pytest.raises(RuntimeError, match="PRIMARY_FAILURE_AFTER_OPEN"):
            exercise()
    else:
        exercise()
    assert order == ["snapshot", "close"]
    assert evidence["backend"][0]["memory"] == "Native note"
    with FunctionalApplication.open(tmp_path / "app", workflow, "alice") as reopened_app:
        assert reopened_app.snapshot()["world"] == evidence["application"]["world"]
    reopened = QdrantClient(path=str(qpath))
    history = SQLiteManager(str(hpath))
    try:
        assert reopened.retrieve("proof", ids=[target])[0].payload["data"] == "Native note"
        assert history.get_history(target)[0]["event"] == "ADD"
    finally:
        history.close()
        reopened.close()
