"""Zero-network comparison mechanics over the real Store, journal and checkpoints."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.refs import verified_reservation_ref
from milai_lab.application.world import ApplicationWorld
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import v13_1_controls as controls
from milai_lab.runners import v13_1_p5 as p5
from milai_lab.runners import v13_1_p5_compare as compare


def helper(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


shared = helper("compare_controls_helpers", "unit/test_v13_1_controls.py")
old = helper("compare_p5_helpers", "memory/test_v13_1_p5.py")
service_helpers = helper("compare_service_helpers", "memory/test_v13_1_service.py")


@pytest.mark.parametrize("projection", ["enabled", "disabled"])
def test_projection_preserves_exact_semantics_validation_history_and_raw(
    tmp_path: Path, projection: str
) -> None:
    path = tmp_path / "memory.sqlite"
    with SqliteStore.from_conn_string(str(path)) as store:
        service = MemoryService(
            store,
            ("compare", "alice"),
            "alice",
            tmp_path / "lock",
            receipt_contract="explicit_receipt_v1",
            operational_projection=projection,
        )
        world = ApplicationWorld(tmp_path / "world.sqlite", False)
        try:
            source, ref, body = service_helpers.tool_event(service, world)
            fields = {key: body[key] for key in ("status", "label_status")}
            content = json.dumps({**fields, "notes": "Original unchecked parcel note."})
            raw = service_helpers.proposal(
                source,
                content,
                basis="tool_observation",
                object_ref=ref,
                fields=fields,
                content_format="receipt_json_v1",
            )
            rejected = service.commit(
                "s1", "bad", {**raw, "fields": {**fields, "status": "invented"}}
            )
            assert not rejected["ok"] and rejected["reason"] != "operational_projection_disabled"
            first = service.commit("s1", "good", raw)
            assert first["status"] == "committed" and first["revision"] == 1
            query_body = world.get_reservation("alice", "call1")
            query_source = service.event_id("s1", "actual-query", "tool")
            query_ref = verified_reservation_ref(
                world, "alice", query_source, "get_reservation", query_body
            )
            service.capture_tool("s1", "actual-query", "get_reservation", query_body, query_ref)
            second_fields = {key: json.loads(query_body)[key] for key in ("status", "label_status")}
            changed = {
                **raw,
                "id": first["id"],
                "expected_revision": 1,
                "action": "update",
                "source_ref": query_source,
                "object_ref": query_ref.id,
                "fields": second_fields,
                "content": json.dumps(second_fields),
            }
            assert service.commit("s1", "actual-update", changed)["revision"] == 2
            source2 = service.capture_user("s1", "preference", "I prefer short answers.")[
                "source_ref"
            ]
            preference = service.commit("s1", "preference", service_helpers.proposal(source2))
            assert preference["ok"] and preference["content_verification"] == "unchecked"
        finally:
            world.close()
    with SqliteStore.from_conn_string(str(path)) as store:
        service = MemoryService(
            store,
            ("compare", "alice"),
            "alice",
            tmp_path / "lock",
            receipt_contract="explicit_receipt_v1",
            operational_projection=projection,
        )
        view = service.read(first["id"], 1)["value"]
        assert view["content"] == content and view["scope"] == raw["scope"]
        assert view["source_ref"] == source and view["revision"] == 1
        assert view["fields"] == (fields if projection == "enabled" else {})
        assert view["fields_verification"] == (
            "receipt_matched" if projection == "enabled" else "checked_proposal_no_projection"
        )
        assert service.read(first["id"])["value"]["content"] == changed["content"]
        assert service.read(first["id"])["value"]["fields"] == (
            second_fields if projection == "enabled" else {}
        )
        stored = store.get(service.namespace, first["id"]).value
        assert any(p["raw"] == raw for p in stored["_v13_1"]["proposals"].values())
        assert service.commit("s1", "good", raw)["status"] == "no_change"
        assert len(stored["_v13_1"]["history"]) == 2


@pytest.mark.parametrize("arm", ["B2", "B6"])
def test_real_open_tool_source_material_update_reopen_has_no_fake_final(
    tmp_path: Path, arm: str
) -> None:
    config = shared.settings(tmp_path)
    model, embeddings, wires = shared.runtime(tmp_path, config, [])
    path = tmp_path / "bank.sqlite"
    with (
        SqliteStore.from_conn_string(str(path)) as store,
        SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver,
    ):
        service = MemoryService(store, ("compare", "alice"), "alice", tmp_path / "lock")
        world = ApplicationWorld(tmp_path / "world.sqlite", False)
        try:
            source, _, _ = service_helpers.tool_event(service, world)
            original = service.source(source)
            backend = compare.ObservedControls(
                store, saver, "r", arm, "alice", config, model, embeddings
            )
            with pytest.raises(ValueError, match="UNCLOSED"):
                backend.ingest("alice", "cannot_fake_closed_turn", [original])
            assert backend.commit_observed([original])["operation"] == "CREATE"
            query = world.get_reservation("alice", "call1")
            observed = service.capture_tool("s1", "actual-query", "get_reservation", query, None)
            second = service.source(observed["source_ref"])
            assert backend.commit_observed([original, second])["operation"] == "UPDATE"
            assert backend.commit_observed([original, second])["operation"] == "NONE"
            assert backend.snapshot("alice")["archive"] == [original, second]
            assert all("future_question" not in wire[1] for wire in wires)
        finally:
            world.close()
    with (
        SqliteStore.from_conn_string(str(path)) as store,
        SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver,
    ):
        backend = compare.ObservedControls(
            store, saver, "r", arm, "alice", config, model, embeddings
        )
        snapshot = backend.snapshot("alice")
        assert snapshot["revision"] == 2 and len(snapshot["material_history"]) == 2
        assert all(row["role"] == "tool" for row in snapshot["archive"])
        assert "call1" in backend.recall("alice", "call1")["material"]


def prepared(tmp_path: Path, arm: str = "B2") -> Path:
    old.prepared(tmp_path)
    config = shared.settings(tmp_path)
    config.update(cadence="matched_observation_v1", system_prompt="Same public reader.")
    write_json(tmp_path / "compare-config.json", config)
    root = tmp_path / "compare"
    compare.prepare(tmp_path / "public.json", tmp_path / "compare-config.json", root, arm)
    return root


def child(
    root: Path,
    index: int,
    phase: str = "start",
    window: str = "none",
    label: bool | None = None,
    script: str = "reserve",
) -> tuple[Any, Any]:
    attempt = f"{index}-{phase}-{window}"
    process = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(Path(__file__)),
            str(root),
            str(index),
            phase,
            window,
            attempt,
            str(label),
        ],
        capture_output=True,
        text=True,
        timeout=45,
        env={**os.environ, "P5_TEST_SCRIPT": script},
    )
    path = p5.case_path(root, "mechanical") / f"attempt-{attempt}.json"
    assert path.exists(), process.stderr
    return process, read_json(path)


@pytest.mark.parametrize("arm", ["B2", "B6"])
def test_real_subprocess_w2_and_actual_material_update_w3(tmp_path: Path, arm: str) -> None:
    root = prepared(tmp_path, arm)
    initial_ledger = read_json(tmp_path / "budget.json")["generation_requests"]
    killed, boundary = child(root, 0, window="W2")
    assert killed.returncode == -signal.SIGKILL, boundary
    assert boundary["sources"] and not boundary["comparison"]["backend"]["archive"]
    assert read_json(tmp_path / "budget.json")["generation_requests"] == initial_ledger
    resumed, first = child(root, 0, phase="resume")
    assert resumed.returncode == 0, first
    killed, updated = child(root, 1, window="W3", label=True, script="label")
    assert killed.returncode == -signal.SIGKILL, updated
    assert updated["boundary_witness"]["receipt"]["operation"] == "UPDATE"
    revision = updated["comparison"]["backend"]["revision"]
    resumed, final = child(root, 1, phase="resume", script="label")
    assert resumed.returncode == 0, final
    assert final["comparison"]["backend"]["revision"] == revision
    assert final["process_id"] != updated["process_id"]
    assert final["world"]["reservations"][0]["label_status"] == "created"


@pytest.mark.parametrize("available", [True, False])
def test_w1_unknown_preserves_original_and_independent_actual_query(
    tmp_path: Path, available: bool
) -> None:
    root = prepared(tmp_path, "B6")
    assert child(root, 0)[0].returncode == 0
    killed, before = child(root, 1, window="W1", label=available, script="label")
    assert killed.returncode == -signal.SIGKILL, before
    resumed, final = child(root, 1, phase="resume", script="label")
    assert resumed.returncode == 0, final
    sources = final["sources"]
    unknown = [row for row in sources if "ORIGINAL_CALL_OUTCOME_UNKNOWN" in str(row["content"])]
    assert len(unknown) == 1
    body = json.loads(unknown[0]["content"])
    assert body["original_receipt"] is None
    query_sources = [row for row in sources if row["origin"] == "get_reservation"]
    assert any(
        json.loads(row["content"])["label_status"] == ("created" if available else "not_created")
        for row in query_sources
    )
    projection = final["comparison"]["backend"]["projection"]
    assert len(projection["unknown"]) == 1
    assert any(
        h["source_id"] in {row["event_id"] for row in query_sources}
        for obj in projection["objects"].values()
        for h in obj["history"]
    )


@pytest.mark.parametrize(
    "effect", ["update", "no_effect", "same_text", "missing_history", "bad_readback"]
)
def test_mem0_native_update_is_real_owner_lookup_not_add_and_replays(
    tmp_path: Path, effect: str
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        calls = []
        record = {
            "id": "actual",
            "memory": "Original parcel note",
            "user_id": "scoped:alice",
            "hash": "before",
            "updated_at": "before",
        }
        history = [
            {
                "id": "h0",
                "memory_id": "actual",
                "event": "ADD",
                "old_memory": None,
                "new_memory": record["memory"],
            }
        ]

        def update(**args: Any) -> dict[str, str]:
            calls.append(args)
            before = record["memory"]
            if effect != "no_effect":
                record.update(memory=args["text"], hash="after", updated_at="after")
                if effect != "missing_history":
                    history.append(
                        {
                            "id": "h1",
                            "memory_id": "actual",
                            "event": "UPDATE",
                            "old_memory": before,
                            "new_memory": args["text"],
                        }
                    )
            return {"message": "updated"}

        def get(_: str) -> Any:
            return None if calls and effect == "bad_readback" else dict(record)

        memory = SimpleNamespace(update=update, get=get, history=lambda _: list(history))
        native = SimpleNamespace(
            memory=memory,
            search_archive=lambda owner, query: {"results": [{"id": "actual"}]},
            snapshot=lambda owner: [dict(record)],
            _user_id=lambda owner: "scoped:" + owner,
        )
        runtime = compare.ComparisonRuntime.__new__(compare.ComparisonRuntime)
        runtime.store, runtime.backend, runtime.arm = store, native, "mem0_trace_equal"
        runtime.scope = SimpleNamespace(user_id="alice", episode_id="actual-session")
        runtime.formation_namespace = ("p5_compare", "alice")
        runtime.parameters = {"mem0_update_interface": "manual_update_v1"}
        runtime.trace = lambda event: None
        raw = {
            "content": "Original parcel note" if effect == "same_text" else "New proposed content",
            "target_query": "parcel",
            "action": "update",
        }
        receipt = runtime.native_update("same-call", raw)
        if effect == "update":
            assert receipt["status"] == "committed" and receipt["operation"] == "UPDATE"
        elif effect in {"no_effect", "same_text"}:
            assert receipt["status"] == "no_change" and receipt["operation"] != "UPDATE"
        else:
            assert not receipt["ok"] and receipt["status"] == "unknown"
        replay = runtime.native_update("same-call", raw)
        if receipt["ok"]:
            assert replay["replayed"]
        else:
            assert replay["reason"] == "native_update_outcome_unknown"
        assert calls == [{"memory_id": "actual", "text": raw["content"]}]
        assert not runtime.native_update("same-call", {**raw, "content": "changed"})["ok"]
        attempt = store.get(
            runtime.formation_namespace,
            "native-proposal:" + compare.digest(["actual-session", "same-call"]),
        ).value
        assert attempt["requested"] == raw and attempt["before"]["record"]["hash"] == "before"
        assert attempt["before"]["record"]["memory"] == "Original parcel note"
        if not receipt["ok"]:
            assert attempt["status"] == "UNKNOWN" and attempt["first_error"]


def test_prepare_freezes_actual_catalog_and_rejects_changed_source_and_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = prepared(tmp_path)
    frozen = compare._frozen(root)
    public = [row for row in frozen["tool_catalog"] if row["function"]["name"] in p5.BUSINESS_NAMES]
    assert public == compare.BUSINESS_SCHEMAS
    assert frozen["comparison_parameters"]["cadence"] == "matched_observation_v1"
    assert (
        frozen["prompt_sha256"]
        == hashlib.sha256(frozen["config"]["reader_system_prompt"].encode()).hexdigest()
    )
    actual = compare._sources()
    monkeypatch.setattr(compare, "_sources", lambda: {**actual, "changed": "changed"})
    with pytest.raises(ValueError, match="SOURCE_OR_SDK_CHANGED"):
        compare._frozen(root)
    config = frozen["config"]
    for value in (None, [], True, "unsupported"):
        with pytest.raises(ValueError, match="PROJECTION_INVALID"):
            compare._parameters({**config, "operational_projection": value}, "field_grounded")
    with pytest.raises(ValueError, match="NATIVE_T3_IS_ADD_ONLY"):
        compare._parameters(
            {**config, "cadence": "t3_native", "mem0_update_interface": "manual_update_v1"}, "B2"
        )


def test_actual_mem0_sdk_update_get_history_with_mock_embedding_and_persistent_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    import threading
    import uuid

    if importlib.util.find_spec("mem0") is None:
        pytest.skip("Run this SDK target in the existing audited native interpreter")
    monkeypatch.setenv("MEM0_TELEMETRY", "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    import spacy

    if not spacy.util.is_package("en_core_web_sm"):
        pytest.skip("No installed spaCy model; downloads are forbidden")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    from mem0 import Memory
    from mem0.configs.embeddings.base import BaseEmbedderConfig
    from mem0.embeddings.openai import OpenAIEmbedding
    from mem0.memory.storage import SQLiteManager
    from qdrant_client import QdrantClient, models

    from milai_lab.integrations.memory.mem0 import _Embeddings

    config = shared.settings(tmp_path)
    model, embeddings, wires = shared.runtime(tmp_path, config, [])
    embedder = OpenAIEmbedding(BaseEmbedderConfig(model="bge-m3", api_key="local"))
    embedder.client.close()
    embedder.client = SimpleNamespace(
        embeddings=_Embeddings(compare._EmbeddingBridge(embeddings), threading.Lock())
    )
    target = str(uuid.uuid4())
    qpath, hpath = tmp_path / "native-qdrant", tmp_path / "native-history.sqlite"

    def memory_at(client: Any, history: Any) -> Any:
        # Actual pinned SDK methods and SQLite history over real local Qdrant.
        # The finite vector facade does not test native extraction/ranking.
        memory = Memory.__new__(Memory)
        memory.embedding_model, memory.db, memory._entity_store = embedder, history, None
        memory.vector_store = SimpleNamespace(
            get=lambda vector_id: next(iter(client.retrieve("proof", ids=[vector_id])), None),
            update=lambda vector_id, vector, payload: client.upsert(
                "proof", points=[models.PointStruct(id=vector_id, vector=vector, payload=payload)]
            ),
            list=lambda filters, top_k: client.scroll(
                "proof",
                limit=top_k,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(key=key, match=models.MatchValue(value=value))
                        for key, value in filters.items()
                    ]
                ),
            ),
        )
        return memory

    client = QdrantClient(path=str(qpath))
    history = SQLiteManager(str(hpath))
    try:
        client.create_collection(
            "proof", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE)
        )
        client.upsert(
            "proof",
            points=[
                models.PointStruct(
                    id=target,
                    vector=[1.0, 0.0],
                    payload={
                        "data": "parcel note",
                        "user_id": "scoped:alice",
                        "hash": "before",
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                    },
                )
            ],
        )
        history.add_history(target, None, "parcel note", "ADD")
        memory = memory_at(client, history)
        native = SimpleNamespace(
            memory=memory,
            _user_id=lambda owner: "scoped:" + owner,
            search_archive=lambda owner, query: {"results": [{"id": target}]},
            snapshot=lambda owner: memory.get_all(filters={"user_id": "scoped:" + owner})[
                "results"
            ],
        )
        with SqliteStore.from_conn_string(str(tmp_path / "proposals.sqlite")) as store:
            runtime = compare.ComparisonRuntime.__new__(compare.ComparisonRuntime)
            runtime.store, runtime.backend, runtime.arm = store, native, "mem0_trace_equal"
            runtime.scope = SimpleNamespace(user_id="alice", episode_id="real-sdk-session")
            runtime.formation_namespace = ("native-proposals", "alice")
            runtime.parameters, runtime.trace = (
                {"mem0_update_interface": "manual_update_v1"},
                lambda e: None,
            )
            raw = {"content": "parcel note revised", "target_query": "parcel", "action": "update"}
            proof = runtime.native_update("update", raw)
            assert proof["status"] == "committed" and proof["operation"] == "UPDATE"
            assert proof["readback"]["new_update_rows"][0]["new_memory"] == raw["content"]
            same = runtime.native_update("same-text", raw)
            assert same["status"] == "no_change" and same["operation"] == "NONE"
            assert runtime.native_update("update", raw)["replayed"]
            assert sum(wire[1]["input"] == [raw["content"]] for wire in wires) == 2
            # Native entity maintenance may embed again. Every actual wire is
            # charged; this finite facade does not claim entity-store coverage.
            assert model.client.budget.state["embedding"]["known_tokens"] == 4 * len(wires)
    finally:
        history.close()
        client.close()
    reopened = QdrantClient(path=str(qpath))
    history = SQLiteManager(str(hpath))
    try:
        memory = memory_at(reopened, history)
        assert memory.get(target)["memory"] == "parcel note revised"
        assert len([row for row in memory.history(target) if row["event"] == "UPDATE"]) == 2
    finally:
        history.close()
        reopened.close()


@pytest.mark.parametrize("fail_after_open", [False, True])
def test_p5_evidence_precedes_actual_mem0_sdk_close_on_success_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_after_open: bool
) -> None:
    import socket
    import uuid

    if importlib.util.find_spec("mem0") is None:
        pytest.skip("Run this SDK target in the existing audited native interpreter")
    monkeypatch.setenv("MEM0_TELEMETRY", "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    import spacy

    if not spacy.util.is_package("en_core_web_sm"):
        pytest.skip("No installed spaCy model; downloads are forbidden")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    from mem0 import Memory
    from mem0.memory.storage import SQLiteManager
    from qdrant_client import QdrantClient, models

    from milai_lab.integrations.memory.mem0 import Mem0NativeRuntime
    from milai_lab.memory.service_tools import create_service_tools

    root = old.prepared(tmp_path)
    monkeypatch.setattr(p5, "make_model", old.local_model)
    target = str(uuid.uuid4())
    order: list[str] = []
    wires: list[Any] = []
    qpath, hpath = tmp_path / "native-qdrant", tmp_path / "native-history.sqlite"

    class NativeEvidenceComposition:
        frozen = staticmethod(p5._frozen)
        service_options = staticmethod(lambda frozen: {})

        @staticmethod
        def open(**context: Any) -> Any:
            stack, scope = context["stack"], context["scope"]

            def respond(request: httpx.Request) -> httpx.Response:
                wires.append(json.loads(request.read()))
                return httpx.Response(
                    200,
                    json={
                        "data": [{"index": 0, "embedding": [1.0, 0.0]}],
                        "usage": {"total_tokens": 4},
                    },
                )

            embed = stack.enter_context(
                VLLMClient(
                    VLLMConfig(base_url="http://mock/v1", model="bge-m3"),
                    budget=context["budget"],
                    transport=httpx.MockTransport(respond),
                )
            )
            client = QdrantClient(path=str(qpath))
            history = SQLiteManager(str(hpath))
            # Actual SDK get_all/close and persistent Qdrant/SQLite. This finite
            # vector facade does not exercise native extraction or ranking.
            memory = Memory.__new__(Memory)
            memory.db, memory._entity_store = history, None
            memory.vector_store = SimpleNamespace(
                client=client,
                list=lambda filters, top_k: client.scroll(
                    "proof",
                    limit=top_k,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(key=k, match=models.MatchValue(value=v))
                            for k, v in filters.items()
                        ]
                    ),
                ),
            )
            native = Mem0NativeRuntime.__new__(Mem0NativeRuntime)
            native.memory, native.run_id, native.arm_id = memory, scope.run_id, scope.arm_id

            def close() -> None:
                order.append("close")
                native.close()

            stack.callback(close)
            client.create_collection(
                "proof",
                vectors_config=models.VectorParams(
                    size=2,
                    distance=models.Distance.COSINE,
                ),
            )
            vector = embed.embed(["Original native note"], "bge-m3")[0]
            client.upsert(
                "proof",
                points=[
                    models.PointStruct(
                        id=target,
                        vector=vector,
                        payload={
                            "data": "Original native note",
                            "user_id": native._user_id(scope.user_id),
                            "hash": "original",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-01T00:00:00Z",
                        },
                    )
                ],
            )
            history.add_history(target, None, "Original native note", "ADD")

            def snapshot() -> dict[str, Any]:
                order.append("snapshot")
                return {"backend": native.snapshot(scope.user_id)}

            def completed() -> None:
                if fail_after_open:
                    raise RuntimeError("ORIGINAL_FAILURE_AFTER_NATIVE_OPEN")

            return SimpleNamespace(
                hook=None,
                observed=lambda source: None,
                completed=completed,
                tools=lambda: create_service_tools(context["service"], replay_requested=True),
                snapshot=snapshot,
            )

    result = p5.step(root, "mechanical", 0, composition=NativeEvidenceComposition())
    assert "evidence_error" not in result, result
    assert order == ["snapshot", "close"]  # one readback, then one close
    assert result["comparison"]["backend"][0]["memory"] == "Original native note"
    assert result["status"] == ("interrupted" if fail_after_open else "completed")
    if fail_after_open:
        assert result["first_error"]["error"] == "ORIGINAL_FAILURE_AFTER_NATIVE_OPEN"
    assert len(wires) == 1
    assert result["budget"]["embedding"]["known_tokens"] == 4
    reopened = QdrantClient(path=str(qpath))
    history = SQLiteManager(str(hpath))
    try:
        assert reopened.retrieve("proof", ids=[target])[0].payload["data"] == "Original native note"
        assert history.get_history(target)[0]["event"] == "ADD"
    finally:
        history.close()
        reopened.close()


@pytest.mark.parametrize("observed", [False, True])
def test_actual_mem0_sdk_carrier_wire_preserves_legacy_and_open_observed_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, observed: bool
) -> None:
    import socket
    import threading

    if importlib.util.find_spec("mem0") is None:
        pytest.skip("Run this SDK target in the existing audited native interpreter")
    monkeypatch.setenv("MEM0_TELEMETRY", "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    import spacy

    if not spacy.util.is_package("en_core_web_sm"):
        pytest.skip("No installed spaCy model; downloads are forbidden")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    from mem0 import Memory
    from mem0.configs.embeddings.base import BaseEmbedderConfig
    from mem0.embeddings.openai import OpenAIEmbedding
    from mem0.llms.vllm import VllmLLM
    from mem0.memory.storage import SQLiteManager
    from qdrant_client import QdrantClient, models

    from milai_lab.contracts.scope import FoundationScope
    from milai_lab.integrations.memory.mem0 import (
        Mem0NativeRuntime,
        _ChatCompletions,
        _Embeddings,
    )

    config = shared.settings(tmp_path)
    model, embeddings, wires = shared.runtime(tmp_path, config, [{"memory": []}, {"memory": []}])

    def native_response(request: httpx.Request) -> httpx.Response:
        wires.append((request.url.path, json.loads(request.read())))
        return httpx.Response(
            200,
            json={
                "id": "mock-native-generation",
                "object": "chat.completion",
                "created": 0,
                "model": model.client.config.model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"memory": []}',
                        },
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            },
        )

    model.client._client.close()
    model.client._client = httpx.Client(
        base_url=model.client.config.base_url,
        transport=httpx.MockTransport(native_response),
    )
    model.begin_public_message("actual-current-public-request")
    embedder = OpenAIEmbedding(BaseEmbedderConfig(model="bge-m3", api_key="local"))
    embedder.client.close()
    lock = threading.Lock()
    embedder.client = SimpleNamespace(
        embeddings=_Embeddings(compare._EmbeddingBridge(embeddings), lock)
    )
    llm = VllmLLM(
        {
            "model": model.client.config.model,
            "temperature": model.client.config.temperature,
            "max_tokens": model.client.config.max_tokens,
            "api_key": "local",
            "top_p": 1.0,
        }
    )
    llm.client.close()
    rejections: list[str] = []
    llm.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=_ChatCompletions(
                model.client,
                lock,
                model._reserve_request,
                rejections,
            )
        )
    )
    client = QdrantClient(path=str(tmp_path / "native-qdrant"))
    client.create_collection(
        "carrier",
        vectors_config=models.VectorParams(
            size=2,
            distance=models.Distance.COSINE,
        ),
    )
    native = Mem0NativeRuntime.__new__(Mem0NativeRuntime)
    memory = native.memory = Memory.__new__(Memory)
    memory.db = SQLiteManager(str(tmp_path / "native-history.sqlite"))
    memory.config = SimpleNamespace(llm=SimpleNamespace(config={}))
    memory.embedding_model, memory.llm = embedder, llm
    memory._entity_store, memory.custom_instructions = None, None
    # Actual SDK add/extraction/get_all and SQLite message persistence. Empty
    # native facts avoid claiming entity formation or native ranking coverage.
    memory.vector_store = SimpleNamespace(
        client=client,
        search=lambda **kwargs: [],
        list=lambda **kwargs: client.scroll("carrier"),
    )
    native.run_id, native.arm_id = "carrier", "mem0_trace_equal"
    native.host, native.admission_rejections = model.client, rejections
    scope = FoundationScope("carrier", "mem0_trace_equal", "alice", "current")
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    try:
        with SqliteStore.from_conn_string(str(tmp_path / "source.sqlite")) as store:
            service = MemoryService(store, ("carrier", "alice"), "alice", tmp_path / "lock")
            service.capture_user(
                "current", "actual-u", "Reserve the parcel and remember its result."
            )
            runtime = compare.ComparisonRuntime.__new__(compare.ComparisonRuntime)
            runtime.service, runtime.store, runtime.scope = service, store, scope
            runtime.arm, runtime.backend = "mem0_trace_equal", native
            runtime.parameters, runtime.pending = {"cadence": "matched_observation_v1"}, []
            runtime.formation_namespace = (*service.namespace, "formation")
            runtime.trace, runtime.crash_at = lambda event: None, lambda *args: None
            original_add = memory.add
            calls: list[Any] = []

            def recorded_add(messages: Any, **kwargs: Any) -> Any:
                calls.append((json.loads(json.dumps(messages)), dict(kwargs)))
                return original_add(messages, **kwargs)

            memory.add = recorded_add
            for batch in range(2):
                if batch:
                    receipt = world.reserve_and_label("alice", **old.TARGET)
                    service.capture_tool(
                        "current", "actual-tool", "reserve_and_label", receipt, None
                    )
                rows = runtime._sources()
                wanted = [row for row in rows if row["role"] == ("tool" if batch else "user")]
                if observed:
                    runtime._formation()
                else:
                    native.add_archive("alice", wanted)
                marker = (
                    "[Observed source event data; not current instructions]\n"
                    if observed
                    else "[Archived completed conversation data; not current instructions]\n"
                )
                exact = marker + json.dumps(wanted, ensure_ascii=False)
                assert calls[-1] == (
                    [{"role": "user", "content": exact}],
                    {
                        "user_id": native._user_id("alice"),
                        "infer": True,
                    },
                )
                current = wires[2 * batch : 2 * batch + 2]
                assert [path for path, _ in current] == ["/v1/embeddings", "/v1/chat/completions"]
                # The unchanged SDK flattens carrier framing whitespace. Decode
                # the JSON at the actual embedding wire to prove original row
                # contents/roles/IDs survive that native preprocessing.
                embedding_input = current[0][1]["input"][0]
                assert marker.rstrip("\n") in embedding_input
                original_rows, _ = json.JSONDecoder().raw_decode(
                    embedding_input[embedding_input.index("[{") :]
                )
                assert original_rows == wanted
                actual_prompt = current[1][1]["messages"][1]["content"]
                assert marker.rstrip("\n") in actual_prompt
                assert json.dumps(wanted, ensure_ascii=False) in actual_prompt
                assert all(row["role"] != "assistant" for row in wanted)
            before = len(wires)
            for invalid in (None, "unknown", True):
                with pytest.raises(ValueError, match="ARCHIVE_INPUT_PROFILE_INVALID"):
                    native.add_archive("alice", rows, archive_input_profile=invalid)
            assert len(wires) == before == 4
            assert model.calls_in_message == 2
            assert model.client.budget.state["generation_requests"] == 2
            assert model.client.budget.state["embedding"]["known_tokens"] == 8
            # Source IDs/bodies remain original and independently readable;
            # the carrier claims neither a closed conversation nor native IDs.
            assert [service.source(row["event_id"]) for row in rows] == rows
            parameters = compare._parameters(
                {**config, "cadence": "matched_observation_v1", "embedding_dimension": 1024},
                "mem0_trace_equal",
            )
            assert parameters["mem0_archive_input_profile"] == "observed_events_v1"
    finally:
        world.close()
        native.close()
        model.client.close()


def test_configured_common_reader_is_on_actual_wire_with_lawful_current_thread(
    tmp_path: Path,
) -> None:
    from milai_lab.contracts.scope import FoundationScope

    config = shared.settings(tmp_path)
    model, _, wires = shared.runtime(tmp_path, config, [{"answer": "mechanical"}])
    runtime = compare.ComparisonRuntime.__new__(compare.ComparisonRuntime)
    runtime.scope = FoundationScope("r", "B2", "alice", "current-episode")
    runtime.settings, runtime.model = config, model
    runtime.common_profiles = compare.profiles(config)
    runtime.parameters, runtime.arm = {"cadence": "t3_native"}, "B2"
    runtime.service = SimpleNamespace(sources=lambda: [])
    runtime.trace = lambda event: None
    runtime._recall = lambda query: {"material": "past original data", "query": query}
    current = [
        HumanMessage(id="u1", content="Earlier public turn"),
        AIMessage(
            id="a1",
            content="",
            tool_calls=[
                {"name": "get_reservation", "args": {"item_key": "parcel"}, "id": "actual-call"}
            ],
        ),
        ToolMessage(
            name="get_reservation", tool_call_id="actual-call", content="Actual public tool"
        ),
        AIMessage(id="a2", content="Previous response"),
        HumanMessage(id="u2", content="Current public question"),
    ]
    outgoing = runtime.hook({"messages": current}, runtime.scope.config())["llm_input_messages"]
    model._reserve_request()
    model.client.chat(
        [
            {
                "role": "system"
                if m.type == "system"
                else "user"
                if m.type == "human"
                else "tool"
                if m.type == "tool"
                else "assistant",
                "content": m.content,
            }
            for m in outgoing
        ]
    )
    wire = wires[-1][1]["messages"]
    assert wire[0]["content"] == config["reader_system_prompt"] + "\npast original data"
    assert [row["content"] for row in wire[1:]] == [m.content for m in current]
    assert runtime.last_material["query"] == "Current public question"


def test_field_matched_actual_update_replay_shares_writer_reader_admissions(tmp_path: Path) -> None:
    root = prepared(tmp_path, "field_grounded")
    assert child(root, 0)[0].returncode == 0
    killed, updated = child(root, 1, window="W3", label=True, script="label")
    assert killed.returncode == -signal.SIGKILL, updated
    assert updated["boundary_witness"]["requested_call"]["args"]["action"] == "update"
    revision = updated["boundary_witness"]["receipt"]["revision"]
    assert updated["comparison"]["writer_checkpoint"]["next"] == ["tools"]
    resumed, final = child(root, 1, phase="resume", script="label")
    assert resumed.returncode == 0, final
    assert final["records"][0]["value"]["revision"] == revision
    state = final["generation_admissions"]
    assert 4 < state["m2"] <= 12
    reader_calls = sum(m["type"] == "ai" for m in final["checkpoint"]["messages"])
    assert state["m2"] > reader_calls  # writer and reader share the same persisted key
    # Same key includes admissions before kill and after re-opening; no reset.
    assert state["m2"] >= updated["generation_admissions"]["m2"]


def test_metered_native_embedding_bridge_admits_specials_before_any_http(tmp_path: Path) -> None:
    import threading

    from milai_lab.integrations.memory.mem0 import _Embeddings

    config = shared.settings(tmp_path)
    model, embed, wires = shared.runtime(tmp_path, config, [])
    bridge = _Embeddings(compare._EmbeddingBridge(embed), threading.Lock())
    result = bridge.create(model="bge-m3", input=["x"], encoding_format="float")
    assert result.data[0].embedding and len(wires) == 1
    with pytest.raises(ValueError, match="EMBEDDING_CONTEXT_CAPACITY_EXCEEDED"):
        bridge.create(model="bge-m3", input=["x " * 8191], encoding_format="float")
    assert len(wires) == 1
    assert model.client.budget.state["embedding"]["known_tokens"] == 4


@pytest.mark.parametrize("failure", [False, True])
def test_accounting_counts_actual_http_outcomes_and_not_admission_refusals(
    tmp_path: Path, failure: bool
) -> None:
    config = shared.settings(tmp_path)
    model, _, _ = shared.runtime(tmp_path, config, [])
    model.client.budget.reserve("chat/completions", {"messages": [], "max_tokens": 1})
    write_json(tmp_path / "config.json", config)
    root = tmp_path / "control-run"
    controls.prepare(tmp_path / "config.json", root, "r", "B2", "alice")

    def response(request: httpx.Request) -> httpx.Response:
        if failure:
            return httpx.Response(500, text="actual HTTP failure")
        if request.url.path.endswith("embeddings"):
            value = json.loads(request.read())
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(value["input"])
                    ],
                    "usage": {"total_tokens": 2},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "actual reader"},
                    }
                ],
                "usage": {"total_tokens": 2},
            },
        )

    transport = httpx.MockTransport(response)
    formed = controls.operation(
        root,
        "formed",
        "ingest",
        {"owner": "alice", "boundary_id": "past", "records": shared.archive()},
        admission_key="public",
        embedding_transport=transport,
    )
    assert formed["request_attempts"]["embedding"] == 1
    if failure:
        assert formed["status"] == "INTERRUPTED"
        return
    read = controls.operation(
        root,
        "reader",
        "read",
        {"owner": "alice", "question": "Cobalt"},
        admission_key="public",
        host_transport=transport,
        embedding_transport=transport,
    )
    assert read["request_attempts"] == {"generation": 1, "embedding": 1}
    refused = controls.operation(
        root,
        "capacity",
        "read",
        {"owner": "alice", "question": "x " * 8193},
        admission_key="public",
        host_transport=transport,
        embedding_transport=transport,
    )
    assert refused["request_attempts"] == {"generation": 0, "embedding": 0}
    assert refused["status"] == "CAPACITY_REJECTED"


if __name__ == "__main__":
    from milai_lab.providers.embedding_capacity import MeteredEmbeddings

    class WriterModel(old.ScriptModel):
        def _generate(
            self, messages: list[Any], stop: Any = None, run_manager: Any = None, **kwargs: Any
        ) -> Any:
            human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
            if not str(human.id).startswith("formation:"):
                return super()._generate(messages, stop, run_manager, **kwargs)
            self._reserve_request()
            current = messages[messages.index(human) + 1 :]
            calls = []
            if not any(isinstance(m, ToolMessage) for m in current):
                rows = json.loads(str(human.content).split("\n", 1)[1])
                source = next(row for row in reversed(rows) if row["role"] == "tool")
                native = json.loads(source["content"])
                fields = {key: native[key] for key in ("status", "label_status")}
                calls = [
                    {
                        "name": "manage_memory",
                        "id": str(human.id) + ":memory",
                        "args": {
                            "content": json.dumps({**fields, "notes": "parcel"}),
                            "kind": "episodic",
                            "basis": "tool_observation",
                            "fields": fields,
                            "source_ref": source["event_id"],
                            "object_ref": source["object_ref"]["id"],
                            "action": "create"
                            if source["origin"] == "reserve_and_label"
                            else "update",
                            "target_query": "parcel",
                        },
                    }
                ]
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="" if calls else "Writer completed.",
                            tool_calls=calls,
                            id=str(human.id) + f":ai:{len(current)}",
                        )
                    )
                ]
            )

    def local_model(settings: Any, budget: Any, trace: Any, resource_root: Path) -> Any:
        original = old.local_model(settings, budget, trace, resource_root)
        model = WriterModel(
            client=original.client,
            capacity_path=original.capacity_path,
            max_calls_per_message=original.max_calls_per_message,
            script=original.script,
            wire_path=original.wire_path,
        )
        model.client.capacity = HostCapacity(settings["capacity"])
        return model

    def mock_open(**context: Any) -> Any:
        frozen = context["frozen"]
        if frozen["comparison_parameters"]["arm"] == "field_grounded":
            return compare.ComparisonRuntime(**context)
        runtime = compare.ComparisonRuntime.__new__(compare.ComparisonRuntime)
        runtime.__dict__.update(context)
        runtime.settings, runtime.parameters = frozen["config"], frozen["comparison_parameters"]
        runtime.arm, runtime.pending, runtime.last_material = runtime.parameters["arm"], [], {}
        runtime.formation_namespace = (*runtime.service.namespace, "p5_compare_formation")

        def embedding(request: httpx.Request) -> httpx.Response:
            wire = json.loads(request.read())
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(wire["input"])
                    ],
                    "usage": {"total_tokens": 4},
                },
            )

        client = context["stack"].enter_context(
            VLLMClient(
                VLLMConfig(**runtime.settings["embedding"]),
                budget=runtime.budget,
                emit=runtime.trace,
                transport=httpx.MockTransport(embedding),
            )
        )
        embed = MeteredEmbeddings(
            client,
            runtime.settings["embedding"]["model"],
            runtime.settings["embedding_capacity"],
            dimension=2,
            batch_size=2,
        )
        runtime.backend = compare.ObservedControls(
            runtime.store,
            runtime.saver,
            runtime.scope.run_id,
            runtime.arm,
            runtime.scope.user_id,
            runtime.settings,
            runtime.model,
            embed,
        )
        return runtime

    p5.make_model = local_model
    compare.Composition.open = staticmethod(mock_open)
    root, index, phase, window, attempt, label = sys.argv[1:]
    output = compare.step(
        Path(root),
        "mechanical",
        int(index),
        phase=phase,
        window=window,
        hit=2 if window == "W3" else 1,
        attempt_id=attempt,
        window_tool="complete_label" if window == "W1" else None,
        label_available=None if label == "None" else label == "True",
        world_event_id=None if label == "None" else attempt,
    )
    raise SystemExit(0 if output["status"] == "completed" else 1)
