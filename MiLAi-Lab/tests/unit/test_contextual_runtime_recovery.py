from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest

from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.contextual_agent_tasks import (
    BusinessTool,
    BusinessToolResult,
    TaskTurn,
    accept_observation,
    run_task_session,
    task_runtime,
)
from milai_lab.runners.contextual_host import ContextualHost
from milai_lab.runners.contextual_runtime_store import RuntimeIdentity, RuntimeStore
from milai_lab.runners.contextual_session import HostSession


def embed(texts: list[str]) -> list[list[float]]:
    return [[1.0, 0.0] for _ in texts]


def identity() -> RuntimeIdentity:
    return RuntimeIdentity.from_config(
        "owner",
        {
            "host": {"model": "fixture"},
            "embedding": {"model": "fixture-embed"},
            "embedding_dimension": 2,
            "embedding_window": {"max_tokens": 128},
            "model_identity": {
                "host": {"weights": "host-v1"},
                "embedding": {"weights": "embed-v1"},
            },
            "state_policy": "off",
            "source_protocol": "publish-retain-project-v1",
            "actor_protocol": "trusted-actor-v1",
        },
    )


def bank(contract: RuntimeIdentity) -> ContextualMemory:
    return ContextualMemory(
        contract.owner_id,
        host_id=contract.host_model,
        embed=embed,
        embedding_model=contract.embedding_model,
        embedding_dimension=contract.embedding_dimension,
        embedding_identity=contract.embedding_identity,
        state_policy=contract.state_policy,
    )


SCHEMA = {
    "type": "function",
    "function": {
        "name": "do_work",
        "description": "Do one business action",
        "parameters": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
            "additionalProperties": False,
        },
    },
}


def response(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def tool_message(name: str = "do_work", item: str = "A") -> dict[str, Any]:
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "native-call",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({"item": item})},
            }
        ],
    }


def client_with(messages: list[dict[str, Any]], requests: list[dict[str, Any]]) -> VLLMClient:
    def reply(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response(messages.pop(0)))

    return VLLMClient(
        VLLMConfig("http://fixture/v1", "fixture", max_calls=2, tool_mode="native"),
        transport=httpx.MockTransport(reply),
    )


def host_with(
    memory: ContextualMemory,
    store: RuntimeStore,
    client: VLLMClient,
    executed: list[str],
    *,
    status: Literal["succeeded", "failed", "unknown"] = "succeeded",
) -> ContextualHost:
    def execute(args: dict[str, Any], call_id: str) -> BusinessToolResult:
        executed.append(call_id)
        return BusinessToolResult(call_id, status, {"item": args["item"], "count": len(executed)})

    return ContextualHost(
        client,
        memory.dispatch,
        [],
        "Use the business tool when needed.",
        memory=memory,
        business_tools={"do_work": BusinessTool(SCHEMA, execute)},
        runtime_store=store,
    )


def test_reconciled_result_is_new_evidence_without_rewriting_unknown_source(tmp_path: Path) -> None:
    contract = identity()
    memory = bank(contract)
    memory.start_task("session-1", "Check execution")
    session = HostSession("session-1", memory)
    session.turn_id = "turn-1"
    call_id = RuntimeStore.call_id(session.session_id, session.turn_id, 0)
    with RuntimeStore(tmp_path, contract) as store:
        store.begin_action(call_id, "do_work", {"item": "A"}, memory=memory, session=session)
        store.finish_action(
            call_id,
            BusinessToolResult(call_id, "unknown", {"timeout": True}),
            memory=memory,
            session=session,
        )
        with client_with([], []) as client:
            host = host_with(memory, store, client, [])
            host.maintenance_policy = "required"
            host._recover_business_results(session)
            unknown_ref = next(iter(memory.sources))
            original = memory.sources[unknown_ref].content
            store.reconcile_action(
                call_id,
                BusinessToolResult(call_id, "succeeded", {"done": True}),
                evidence={"query": "get_actual_operation", "id": call_id},
            )
            host._recover_business_results(session)
            host._recover_business_results(session)
    assert len(memory.sources) == 2
    assert memory.sources[unknown_ref].content == original
    assert any(
        '"execution_status": "succeeded"' in item.content and '"verification"' in item.content
        for ref, item in memory.sources.items()
        if ref != unknown_ref
    )
    assert len(session.maintenance["pending"]) == 2


def test_settled_business_result_recovers_after_intake_crash_without_reexecution(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    contract = identity()
    turn = TaskTurn("turn-1", "Do item A")
    executed: list[str] = []
    first_requests: list[dict[str, Any]] = []
    with RuntimeStore(tmp_path, contract) as store:
        memory = bank(contract)
        with client_with([tool_message()], first_requests) as client:
            host = host_with(memory, store, client, executed)

            def crash_after_execution(*_: Any) -> Observation:
                raise RuntimeError("intake interrupted")

            monkeypatch.setattr(host, "_business_observation", crash_after_execution)
            with pytest.raises(RuntimeError, match="intake interrupted"):
                run_task_session(
                    [turn], memory=memory, host=host, session_id="session-1", close=False
                )
        assert len(executed) == 1
        journal = store.actions_for_turn("session-1", "turn-1")
        assert len(journal) == 1 and journal[0]["result"]["status"] == "succeeded"
        assert store.pending_actions() == []

    resumed_requests: list[dict[str, Any]] = []
    with RuntimeStore(tmp_path, contract) as store:
        restored = store.restore_memory(embed)
        assert restored is not None
        memory = restored
        session = store.restore_session(memory)
        assert session is not None
        with client_with([{"role": "assistant", "content": "Done."}], resumed_requests) as client:
            host = host_with(memory, store, client, executed)
            session, results = run_task_session(
                [turn],
                memory=memory,
                host=host,
                session_id="session-1",
                session=session,
                close=False,
            )
        assert results[0].status == "complete"
        assert len(executed) == 1
        assert len(resumed_requests) == 1
        transcript = resumed_requests[0]["messages"]
        native = next(item for item in transcript if item.get("tool_calls"))
        assert any(
            item.get("role") == "tool" and item.get("tool_call_id") == native["tool_calls"][0]["id"]
            for item in transcript
        )
        assert any("Recovered business result" in item.get("content", "") for item in transcript)
        assert store.completed_turn("session-1", "turn-1") is not None

        with client_with([], resumed_requests) as client:
            host = host_with(memory, store, client, executed)
            _, replay = run_task_session(
                [turn],
                memory=memory,
                host=host,
                session_id="session-1",
                session=session,
                close=False,
            )
        assert replay[0].answer == "Done."
        assert len(resumed_requests) == 1 and len(executed) == 1
        with pytest.raises(ValueError, match="RUNTIME_TURN_INPUT_CHANGED"):
            run_task_session(
                [TaskTurn("turn-1", "Do a different item")],
                memory=memory,
                host=host,
                session_id="session-1",
                session=session,
                close=False,
            )


def test_unknown_business_result_blocks_same_action_in_later_turn(tmp_path: Path) -> None:
    contract = identity()
    memory = bank(contract)
    executed: list[str] = []
    requests: list[dict[str, Any]] = []
    messages = [
        tool_message(),
        {"role": "assistant", "content": "Checking."},
        tool_message(),
        {"role": "assistant", "content": "Still unknown."},
    ]
    with RuntimeStore(tmp_path, contract) as store, client_with(messages, requests) as client:
        host = host_with(memory, store, client, executed, status="unknown")
        session, first = run_task_session(
            [TaskTurn("first", "Do item A")],
            memory=memory,
            host=host,
            session_id="session-1",
            close=False,
        )
        session, second = run_task_session(
            [TaskTurn("second", "Do item A again")],
            memory=memory,
            host=host,
            session_id="session-1",
            session=session,
            close=False,
        )
        assert first[0].status == second[0].status == "complete"
        assert len(executed) == 1
        assert len(store.pending_actions()) == 1
        assert second[0].calls[0]["execution_status"] == "unknown"
        assert "PRIOR_EXECUTION_UNRESOLVED" in json.dumps(second[0].calls[0])
        for result in (first[0], second[0]):
            assistant = next(item for item in result.transcript if item.get("tool_calls"))
            assert any(
                item.get("role") == "tool"
                and item.get("tool_call_id") == assistant["tool_calls"][0]["id"]
                for item in result.transcript
            )


def test_multiple_visible_ranges_restore_and_new_session_keeps_only_durable_bank(
    tmp_path: Path,
) -> None:
    contract = identity()
    memory = bank(contract)
    memory.start_task("session-1", "Remember this")
    session = HostSession("session-1", memory)
    source = accept_observation(
        memory,
        session,
        Observation(
            "basis", "An important durable fact", "user", "fixture", actor_ref="current_user"
        ),
        retention="durable",
    )["source_ref"]
    assert session.material_view is not None
    first = session.material_view.project(memory.read(source, start=0, length=6, _visible=False))
    second = session.material_view.project(memory.read(source, start=6, length=10, _visible=False))
    session.append_material(first)
    session.append_material(second)
    saved = memory.save(
        op="CREATE",
        content="An important durable fact",
        about_ref="current_user",
        source_refs=[source],
        dependencies=[],
        certainty="explicit",
    )["record"]["ref"]
    with RuntimeStore(tmp_path, contract) as store:
        store.persist(memory, session)
    with RuntimeStore(tmp_path, contract) as store:
        restored = store.restore_memory(embed)
        assert restored is not None
        resumed = store.restore_session(restored)
        assert resumed is not None
        assert len(resumed.deliveries) == len(session.deliveries)
        assert restored.visible_source_ranges[source] == memory.visible_source_ranges[source]
        assert resumed.visible_bindings == session.visible_bindings
        resumed.close()
        store.persist(restored, resumed)
    with RuntimeStore(tmp_path, contract) as store:
        restored = store.restore_memory(embed)
        assert restored is not None
        assert store.restore_session(restored) is None
        restored.start_task("session-2", "What was remembered?")
        assert source in restored.sources and restored.resolve(saved) == saved
        assert source not in restored.seen


def test_runtime_exit_keeps_primary_error_when_persistence_also_fails(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    from milai_lab.providers import contextual_capacity
    from milai_lab.runners import contextual

    class FixtureEmbedding:
        identity = "fixture"

        def __init__(self, *_: Any) -> None:
            pass

        def close(self) -> None:
            pass

        __call__ = staticmethod(embed)

    monkeypatch.setattr(contextual_capacity, "HostCapacity", lambda _: None)
    monkeypatch.setattr(contextual, "CachedEmbedding", FixtureEmbedding)

    def fail_persist(*_: Any, **__: Any) -> None:
        raise ValueError("persist failed")

    monkeypatch.setattr(RuntimeStore, "persist", fail_persist)
    config = {
        "host": {"base_url": "http://fixture/v1", "model": "fixture"},
        "embedding": {"base_url": "http://fixture/v1", "model": "embed"},
        "embedding_dimension": 2, "embedding_window": {},
        "model_identity": {"host": {}, "embedding": {}},
        "state_policy": "off", "source_protocol": "fixture", "actor_protocol": "fixture",
        "source_retention": "session", "material_bytes": 16000, "capacity": {},
        "budget": {}, "budget_path": str(tmp_path / "budget.json"),
    }
    with pytest.raises(RuntimeError, match="primary failed") as caught:
        with task_runtime(config, user_id="owner", output=tmp_path / "output",
                          state_path=tmp_path / "state", business_tools={}):
            raise RuntimeError("primary failed")
    assert any("persist failed" in note for note in caught.value.__notes__)
