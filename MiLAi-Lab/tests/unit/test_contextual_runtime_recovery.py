from __future__ import annotations

import json
import subprocess
import sys
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
from milai_lab.runners.contextual_maintenance import (
    REPAIR_MAINTENANCE_PROTOCOL,
    SEMANTIC_MAINTENANCE_PROTOCOL,
    failed_write,
    semantic_finish,
)
from milai_lab.runners.contextual_runtime_store import RuntimeIdentity, RuntimeStore
from milai_lab.runners.contextual_session import HostSession


def embed(texts: list[str]) -> list[list[float]]:
    return [[1.0, 0.0] for _ in texts]


def identity(maintenance_protocol: str = "turn-maintenance-v2") -> RuntimeIdentity:
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
            "maintenance_protocol": maintenance_protocol,
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


def test_resume_rejects_same_settled_business_action_without_new_intent(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    contract = identity()
    turn = TaskTurn("turn-1", "Do item A")
    executed: list[str] = []
    with RuntimeStore(tmp_path, contract) as store:
        memory = bank(contract)
        with client_with([tool_message()], []) as client:
            host = host_with(memory, store, client, executed)

            def crash_after_execution(*_: Any) -> Observation:
                raise RuntimeError("intake interrupted")

            monkeypatch.setattr(host, "_business_observation", crash_after_execution)
            with pytest.raises(RuntimeError, match="intake interrupted"):
                run_task_session([turn], memory=memory, host=host,
                                 session_id="session-1", close=False)
    assert len(executed) == 1
    with RuntimeStore(tmp_path, contract) as store:
        memory = store.restore_memory(embed)
        assert memory is not None
        session = store.restore_session(memory)
        assert session is not None
        with client_with([tool_message(), {"role": "assistant", "content": "Done."}], []) as client:
            host = host_with(memory, store, client, executed)
            _, results = run_task_session([turn], memory=memory, host=host,
                                          session_id="session-1", session=session,
                                          close=False)
        assert results[0].status == "complete"
        assert len(executed) == 1
        assert len(store.actions_for_turn("session-1", "turn-1")) == 1
        assert any(call.get("error") == "RECOVERED_ACTION_ALREADY_SETTLED"
                   for call in results[0].calls)
        assert any(call.get("prior_status") == "succeeded"
                   for call in results[0].calls)


@pytest.mark.parametrize("protocol", [SEMANTIC_MAINTENANCE_PROTOCOL,
                                     REPAIR_MAINTENANCE_PROTOCOL])
def test_raw_business_result_recovers_in_new_process_and_finishes(
    tmp_path: Path, protocol: str,
) -> None:
    state = tmp_path / "state"
    counter = tmp_path / "executions.txt"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    events = tmp_path / "events.jsonl"
    for phase, output in (("first", first), ("resume", second)):
        process = subprocess.run(  # noqa: S603 - fixed interpreter and local test paths
            [sys.executable, str(Path(__file__).resolve()), phase, str(state), str(counter),
             str(output), str(events), protocol],
            capture_output=True, text=True, check=False,
        )
        assert process.returncode == 0, process.stderr
    assert len(counter.read_text().splitlines()) == 1
    initial = json.loads(first.read_text())
    resumed = json.loads(second.read_text())
    assert initial["journal_status"] == "succeeded"
    assert resumed["status"] == "complete"
    assert resumed["maintenance"]["protocol"] == protocol
    assert resumed["maintenance"]["semantic_decision"] == "processed"
    assert resumed["maintenance"]["status"] == "complete"
    assert resumed["journal_count"] == 1
    assert resumed["business_calls"][0]["error"] == "RECOVERED_ACTION_ALREADY_SETTLED"
    assert resumed["business_calls"][0]["prior_call_id"] == initial["call_id"]
    assert resumed["memory_save_ok"] and resumed["session_closed"]
    assert json.loads((state / "state.json").read_text())["session"] is None
    trace = [json.loads(line) for line in events.read_text().splitlines()]
    coverage_refs = {item["ref"] for item in resumed["maintenance"]["review_coverage"]}
    assert any(event.get("event") == "observation_received"
               and event.get("source_ref") == resumed["source_ref"]
               and any(row.get("ref") in coverage_refs
                       for row in event["materials"].get("materials", []))
               for event in trace)
    record_alias = resumed["maintenance"]["committed_changes"][0]["record_ref"]
    assert any(event.get("event") == "material_visible"
               and event["bindings"].get(record_alias, {}).get("exact_ref")
               == resumed["record_ref"] for event in trace)


def test_v4_failed_attempt_survives_runtime_restore_and_blocks_false_finish(
    tmp_path: Path,
) -> None:
    contract = identity(REPAIR_MAINTENANCE_PROTOCOL)
    memory = bank(contract)
    memory.start_task("session-1", "Revise value")
    session = HostSession("session-1", memory)
    session.turn_id = "turn-1"
    session.maintenance["protocol"] = REPAIR_MAINTENANCE_PROTOCOL
    failed_write(session, "write-1", {}, "ABOUT_SOURCE_NOT_CITED")
    with RuntimeStore(tmp_path, contract) as store:
        store.persist(memory, session)
    with RuntimeStore(tmp_path, contract) as store:
        restored = store.restore_memory(embed)
        assert restored is not None
        resumed = store.restore_session(restored)
        assert resumed is not None
        assert list(resumed.maintenance["failed_attempts"]) == ["write-1"]
        with pytest.raises(ValueError, match="FAILED_WRITES_UNRESOLVED"):
            semantic_finish(resumed, {"decision": "processed", "remaining": []})


def _maintenance_subprocess_stage(
    phase: str, state_path: Path, counter_path: Path, output_path: Path, events_path: Path,
    protocol: str,
) -> None:
    from milai_lab.runners.contextual import memory_tools

    contract = identity(protocol)
    turn = TaskTurn("turn-1", "Do item A")

    def emit(event: dict[str, Any]) -> None:
        with events_path.open("a") as stream:
            stream.write(json.dumps(event) + "\n")

    def execute(args: dict[str, Any], call_id: str) -> BusinessToolResult:
        with counter_path.open("a") as stream:
            stream.write(call_id + "\n")
        return BusinessToolResult(call_id, "succeeded", {"item": args["item"], "done": True})

    responses = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal responses
        if phase == "first" or responses == 0:
            message = tool_message()
        elif responses == 1:
            wire = json.loads(request.content)
            recovered = next(item["content"] for item in wire["messages"]
                             if item.get("content", "").startswith("Recovered business result:"))
            projected = json.loads(recovered.split(": ", 1)[1])["result"]
            source_alias = next(item["ref"] for item in projected["materials"]
                                if item["kind"] == "source")
            message = tool_message("memory_save")
            message["tool_calls"][0]["function"]["arguments"] = json.dumps({
                "op": "CREATE", "content": "Item A completed", "about_ref": "unknown",
                "source_refs": [source_alias], "certainty": "explicit",
            })
        else:
            message = tool_message("finish_turn")
            message["tool_calls"][0]["function"]["arguments"] = json.dumps({
                "answer": "Done", "maintenance": {"decision": "processed", "remaining": []},
            })
        responses += 1
        return httpx.Response(200, json=response(message))

    with RuntimeStore(state_path, contract) as store:
        if phase == "first":
            memory, session = bank(contract), None
        else:
            memory = store.restore_memory(embed)
            assert memory is not None
            session = store.restore_session(memory)
            assert session is not None
        with VLLMClient(VLLMConfig("http://fixture/v1", "fixture", max_calls=3,
                                   tool_mode="native"),
                        transport=httpx.MockTransport(respond)) as client:
            host = ContextualHost(
                client, memory.dispatch, memory_tools("ordinary"), "Work", memory=memory,
                business_tools={"do_work": BusinessTool(SCHEMA, execute)},
                runtime_store=store, maintenance_policy="required",
                maintenance_protocol=protocol, emit=emit,
            )
            if phase == "first":
                def crash_after_raw_result(*_: Any) -> Observation:
                    raise RuntimeError("after raw result persist")

                host._business_observation = crash_after_raw_result  # type: ignore[method-assign]
                try:
                    run_task_session([turn], memory=memory, host=host,
                                     session_id="session-1", close=False)
                except RuntimeError as error:
                    assert str(error) == "after raw result persist"
                else:
                    raise AssertionError("raw result crash did not occur")
                journal = store.actions_for_turn("session-1", "turn-1")
                output_path.write_text(json.dumps({
                    "call_id": journal[0]["call_id"],
                    "journal_status": journal[0]["result"]["status"],
                }))
            else:
                assert session is not None
                session, results = run_task_session(
                    [turn], memory=memory, host=host, session_id="session-1", session=session,
                )
                current = next(iter(memory.workspace.cards.values()))
                result = results[0]
                output_path.write_text(json.dumps({
                    "status": result.status, "maintenance": result.maintenance,
                    "business_calls": [call for call in result.calls
                                       if call.get("name") == "do_work"],
                    "memory_save_ok": any(call.get("name") == "memory_save" and call["ok"]
                                          for call in result.calls),
                    "journal_count": len(store.actions_for_turn("session-1", "turn-1")),
                    "session_closed": session.closed,
                    "source_ref": current.source_refs[0],
                    "record_ref": memory._ref(current),
                }))


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
        same_memory = store.restore_memory(embed)
        assert same_memory is not None
        same_session = store.restore_session(same_memory)
        assert same_session is not None
        assert same_session.visible_bindings == session.visible_bindings
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


if __name__ == "__main__":
    _maintenance_subprocess_stage(sys.argv[1], *(Path(value) for value in sys.argv[2:6]),
                                  sys.argv[6])
