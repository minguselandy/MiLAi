"""Actual graph/ToolNode and local SQLite evidence for the v3 opt-in recipe."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import FoundationScope, invoke_public_message
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.memory_result import RESPONSIBILITY_PROMPT
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import IncompleteChatResponse, VLLMChatModel
from milai_lab.runners import persistent_memory as runner
from milai_lab.runners.langmem_application import BUSINESS_NAMES, ApplicationWorld, _business_tools
from milai_lab.runners.langmem_application_runtime import ApplicationRuntime
from milai_lab.runners.langmem_foundation import BusinessActionJournal

LAB = Path(__file__).resolve().parents[2]


def _config(root: Path, history: str = "retained") -> dict[str, Any]:
    return {
        "recipe_id": "synthetic-v3",
        "memory_contract": "strict",
        "history_mode": history,
        "memory_result": {"correction_entries": 1},
        "host": {
            "base_url": "http://mock/v1/",
            "model": "mock",
            "temperature": 0,
            "max_tokens": 4096,
            "tool_mode": "json_action",
            "max_calls": 12,
            "enable_thinking": False,
        },
        "embedding": {"base_url": "http://mock/v1/", "model": "mock"},
        "history": {"enabled": history == "archive", "page_max_bytes": 16384},
        "capacity": {"enable_thinking": False},
        "budget_path": str(root / "budget.json"),
    }


@contextmanager
def _runtime(
    root: Path,
    store: InMemoryStore,
    wires: list[dict[str, Any]],
    respond: Any,
    *,
    max_calls: int = 12,
) -> Any:
    def transport(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.read())
        wires.append(wire)
        return httpx.Response(
            200,
            json={
                "id": f"generation-{len(wires)}",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(respond(wire, len(wires))),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
            },
        )

    budget = RunBudget(RunLimits(1, 3, None, None, None), root / "budget.json")
    with VLLMClient(
        VLLMConfig(**_config(root)["host"]),
        transport=httpx.MockTransport(transport),
        emit=Trace(root / "trace.jsonl", "mock"),
        budget=budget,
    ) as client:
        with SqliteSaver.from_conn_string(str(root / "checkpoints.sqlite")) as saver:
            observer = SimpleNamespace(
                assert_healthy=lambda: None,
                run_tool=lambda request, execute, _wrapper: execute(request),
            )
            yield ApplicationRuntime(
                VLLMChatModel(
                    client=client,
                    capacity_path=root / "message-capacity.json",
                    max_calls_per_message=max_calls,
                ),
                store,
                saver,
                observer,
            )


def _agent(
    runtime: ApplicationRuntime,
    root: Path,
    arm: str = "C",
    *,
    history: str = "retained",
    business: Any = (),
    wrapper: Any = None,
) -> Any:
    write_json(root / "run_manifest.json", {"identity": {"run_id": "run", "arm_id": arm}})
    factory, _ = runner._adapters(
        runtime, LocalStateBank(runtime.store), root, "run", arm, _config(root, history)
    )
    return factory(
        runtime.model,
        runtime.store,
        runtime.checkpointer,
        business,
        user_id="alice",
        business_call_wrapper=wrapper,
    )


def _final(status: str, refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "answer": "actual final",
        "memory_result": {"status": status, "receipt_refs": refs or []},
    }


def _scope(arm: str = "C", session: str = "one") -> FoundationScope:
    return FoundationScope("run", arm, "alice", "application:" + session)


def test_same_graph_correction_uses_visible_refs_preserves_originals_and_capacity(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []

    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return _final("committed")
        if call == 2:
            return {
                "calls": [
                    {
                        "name": "manage_memory",
                        "arguments": {"action": "create", "content": "actual retained content"},
                    }
                ]
            }
        return _final("committed", ["generation-2:tool:0"])

    with _runtime(tmp_path, store, wires, respond) as runtime:
        agent = _agent(runtime, tmp_path)
        result = invoke_public_message(agent, runtime.model, _scope(), "keep this for later")
        checkpoint = agent.get_state(_scope().config()).values["messages"]
        assert runtime.model.calls_in_message == 3
        assert sum(isinstance(row, HumanMessage) for row in checkpoint) == 1
        assert (
            len([row for row in checkpoint if isinstance(row, AIMessage) and not row.tool_calls])
            == 2
        )
        assert checkpoint[1].id == "generation-1" and checkpoint[1].content == "actual final"
        assert checkpoint[1].response_metadata["memory_result"]["receipt_refs"] == []
        assert result[-1].response_metadata["memory_result_verification"]["declaration_supported"]
        original_tool = next(row for row in checkpoint if isinstance(row, ToolMessage))
        assert "receipt_ref" not in original_tool.content
        assert json.loads(original_tool.content)["status"] == "created"
        actual_copy = next(row for row in wires[-1]["messages"] if row["role"] == "tool")
        assert '"receipt_ref": "generation-2:tool:0"' in actual_copy["content"]
        assert actual_copy["content"].endswith(original_tool.content)
        assert all(row["role"] != "system" for row in wires[1]["messages"][1:])
        assert "reserve_and_label" not in wires[1]["messages"][0]["content"]
        assert len(store.search(("langmem", "run", "C", "alice"))) == 1
        capture = os.environ.get("MILAI_P1_WIRE_CAPTURE")
        if capture:
            write_json(
                Path(capture),
                {"wires": wires, "original_tool": original_tool.model_dump(mode="json")},
            )


def test_existing_record_read_nochange_never_forces_create_or_reads_foreign_owner(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []
    own_id, other_id = str(uuid.uuid4()), str(uuid.uuid4())
    store.put(("langmem", "run", "C", "alice"), own_id, {"content": "existing content"})
    store.put(("langmem", "run", "C", "bob"), other_id, {"content": "PRIVATE_OTHER"})

    def respond(_wire: Any, call: int) -> Any:
        return (
            {"calls": [{"name": "read_memory", "arguments": {"id": own_id}}]}
            if call == 1
            else _final("no_change", ["generation-1:tool:0"])
        )

    with _runtime(tmp_path, store, wires, respond) as runtime:
        result = invoke_public_message(
            _agent(runtime, tmp_path), runtime.model, _scope(), "read it"
        )
        assert len(wires) == 2
        assert (
            result[-1].response_metadata["memory_result_verification"]["successful_change_refs"]
            == []
        )
        assert store.get(("langmem", "run", "C", "alice"), own_id).value == {
            "content": "existing content"
        }
        assert "PRIVATE_OTHER" not in json.dumps(wires)


def test_partial_operations_keep_real_commits_errors_and_no_semantic_certification(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []

    def respond(_wire: Any, call: int) -> Any:
        return (
            {
                "calls": [
                    {"name": "manage_memory", "arguments": {"action": "create", "content": "kept"}},
                    {
                        "name": "manage_memory",
                        "arguments": {
                            "action": "update",
                            "content": "x",
                            "id": str(uuid.UUID(int=2)),
                        },
                    },
                ]
            }
            if call == 1
            else _final("committed", ["generation-1:tool:0"])
        )

    with _runtime(tmp_path, store, wires, respond) as runtime:
        result = invoke_public_message(_agent(runtime, tmp_path), runtime.model, _scope(), "save")
        verdict = result[-1].response_metadata["memory_result_verification"]
        assert len(wires) == 2 and verdict["declaration_supported"]
        assert verdict["partial_operations_observed"] and verdict["semantic_completion"] is None
        assert verdict["failed_operation_refs"] == ["generation-1:tool:1"]
        assert len(store.search(("langmem", "run", "C", "alice"))) == 1


def test_nochange_contradiction_gets_only_one_entry_and_invalid_second_final_is_preserved(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []

    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return {"calls": [{"name": "manage_memory", "arguments": {"content": "actual"}}]}
        return _final("no_change") if call == 2 else {"answer": "raw invalid second final"}

    with _runtime(tmp_path, store, wires, respond) as runtime:
        result = invoke_public_message(_agent(runtime, tmp_path), runtime.model, _scope(), "save")
        assert len(wires) == 3
        assert result[-1].content == "raw invalid second final"
        assert not result[-1].response_metadata["memory_result_verification"][
            "declaration_supported"
        ]
        assert len(store.search(("langmem", "run", "C", "alice"))) == 1


def test_semantically_wrong_nochange_is_not_auto_corrected_and_cap_is_not_extended(
    tmp_path: Path,
) -> None:
    for status in ("no_change", "unresolved"):
        root = tmp_path / status
        root.mkdir()
        wires: list[dict[str, Any]] = []
        store = InMemoryStore()
        with _runtime(
            root, store, wires, lambda _wire, _call, value=status: _final(value), max_calls=1
        ) as runtime:
            result = invoke_public_message(_agent(runtime, root), runtime.model, _scope(), "save")
            assert len(wires) == 1 and runtime.model.calls_in_message == 1
            assert (
                result[-1].response_metadata["memory_result_verification"]["semantic_completion"]
                is None
            )
            assert store.search(("langmem", "run", "C", "alice")) == []


def test_business_partial_effect_is_never_replayed_by_memory_correction(tmp_path: Path) -> None:
    store, wires = InMemoryStore(), []
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    journal = BusinessActionJournal(tmp_path / "business.json", BUSINESS_NAMES)
    args = {"item_key": "parcel", "quantity": 2, "destination": "bay", "packing": "box"}

    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return {
                "calls": [
                    {"name": "reserve_and_label", "arguments": args},
                    {
                        "name": "manage_memory",
                        "arguments": {
                            "action": "update",
                            "id": str(uuid.UUID(int=2)),
                            "content": "proposal that cannot be saved",
                        },
                    },
                ]
            }
        if call == 3:
            return {"calls": [{"name": "reserve_and_label", "arguments": args}]}
        return _final("unresolved")

    try:
        with _runtime(tmp_path, store, wires, respond) as runtime:
            agent = _agent(
                runtime, tmp_path, business=_business_tools(world, "alice"), wrapper=journal
            )
            with pytest.raises(IncompleteChatResponse, match="JSON_ACTION_SCHEMA_INVALID"):
                invoke_public_message(agent, runtime.model, _scope(), "reserve then maintain")
            assert len(world.snapshot()["attempts"]) == 1
            assert len(world.snapshot()["reservations"]) == 1
            tools = [
                row
                for row in agent.get_state(_scope().config()).values["messages"]
                if isinstance(row, ToolMessage)
            ]
            assert len(tools) == 2
            assert json.loads(tools[0].content)["ok"] is False
            assert tools[1].name == "manage_memory" and tools[1].status == "error"
            assert json.loads(tools[1].content)["status"] == "not_found"
            assert store.search(("langmem", "run", "C", "alice")) == []
            projected_tools = [row for row in wires[1]["messages"] if row["role"] == "tool"]
            assert all(projected["content"].endswith(original.content)
                       for projected, original in zip(projected_tools, tools, strict=True))
    finally:
        world.close()


def test_unknown_business_side_effect_propagates_without_correction_or_replay(
    tmp_path: Path,
) -> None:
    store, wires = InMemoryStore(), []
    world = ApplicationWorld(tmp_path / "world.sqlite", False)
    tools = _business_tools(world, "alice")
    actual = tools[0].func

    def unknown(**kwargs: Any) -> Any:
        actual(**kwargs)
        raise httpx.ReadTimeout("synthetic unknown outcome")

    tools[0].func = unknown
    journal = BusinessActionJournal(tmp_path / "business.json", BUSINESS_NAMES)
    try:
        with _runtime(
            tmp_path,
            store,
            wires,
            lambda _wire, _call: {
                "calls": [
                    {
                        "name": "reserve_and_label",
                        "arguments": {
                            "item_key": "parcel",
                            "quantity": 2,
                            "destination": "bay",
                            "packing": "box",
                        },
                    }
                ]
            },
        ) as runtime:
            agent = _agent(runtime, tmp_path, business=tools, wrapper=journal)
            with pytest.raises(httpx.ReadTimeout):
                invoke_public_message(agent, runtime.model, _scope(), "act")
            assert len(wires) == 1 and len(world.snapshot()["attempts"]) == 1
            assert not any(
                isinstance(row, ToolMessage)
                for row in agent.get_state(_scope().config()).values["messages"]
            )
    finally:
        world.close()


@pytest.mark.parametrize("history", ["archive", "retained"])
def test_actual_history_permission_and_owner_isolation(tmp_path: Path, history: str) -> None:
    store, wires = InMemoryStore(), []
    with _runtime(tmp_path, store, wires, lambda _wire, _call: {"answer": "done"}) as runtime:
        agent = _agent(runtime, tmp_path, "B1", history=history)
        agent.update_state(
            _scope("B1", "old").config(),
            {
                "messages": [
                    HumanMessage(id="past-user", content="PAST_ARCHIVE_ONLY"),
                    AIMessage(id="past-final", content="past final"),
                ]
            },
            as_node="agent",
        )
        write_json(
            tmp_path / "phase-progress.json",
            {
                "messages": {
                    "past": {
                        "message_id": "past",
                        "session_id": "old",
                        "user_id": "alice",
                        "public_index": 0,
                        "visited_ordinal": 0,
                        "status": "COMPLETED",
                    }
                }
            },
        )
        bank = LocalStateBank(store)
        bank.record_event(
            StateScope("run", "B1", "alice"),
            {
                "id": "audit-source",
                "kind": "user",
                "actor": "alice",
                "content": "SOURCE_ARCHIVE_ONLY",
            },
        )
        store.put(("langmem", "run", "B1", "alice"), str(uuid.uuid4()), {"content": "KEPT_BODY"})
        store.put(("langmem", "run", "B1", "bob"), str(uuid.uuid4()), {"content": "OTHER_OWNER"})
        invoke_public_message(agent, runtime.model, _scope("B1", "new"), "CURRENT")
        text = json.dumps(wires)
        assert ("PAST_ARCHIVE_ONLY" in text) == (history == "archive")
        assert ("read_history" in text) == (history == "archive")
        assert (
            "KEPT_BODY" in text and "SOURCE_ARCHIVE_ONLY" not in text and "OTHER_OWNER" not in text
        )
        assert RESPONSIBILITY_PROMPT in wires[0]["messages"][0]["content"]


def test_prepared_phase_entry_reopens_retained_records_records_costs_and_refuses_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = {
        "kind": "MILAI_PERSISTENT_MEMORY_INPUTS",
        "workload": "application",
        "rubric_path": str(tmp_path / "never-read.json"),
        "script": {
            "users": ["alice"],
            "initial_label_available": False,
            "phases": [
                {
                    "id": index,
                    "operator_memory": [],
                    "world_events": [],
                    "messages": [
                        {
                            "message_id": str(index),
                            "user_id": "alice",
                            "session_id": str(index),
                            "public_index": 0,
                            "text": text,
                        }
                    ],
                }
                for index, text in enumerate(("OLD_SESSION_USER", "CURRENT_SESSION_USER"))
            ],
        },
    }
    args = SimpleNamespace(
        config=tmp_path / "config.json",
        inputs=tmp_path / "inputs.json",
        runtime_root=tmp_path / "runtime",
        output=tmp_path / "prepared.json",
        prepared=tmp_path / "prepared.json",
        run="run",
        arm="C",
        phase=0,
        stage="synthetic",
    )
    write_json(args.config, _config(args.runtime_root))
    write_json(args.inputs, inputs)
    store, wires = InMemoryStore(), []

    def respond(_wire: Any, call: int) -> Any:
        if call == 1:
            return _final("committed")
        if call == 2:
            return {"calls": [{"name": "manage_memory", "arguments": {"content": "KEPT_BODY"}}]}
        return _final("committed", ["generation-2:tool:0"]) if call == 3 else _final("no_change")

    @contextmanager
    def open_runtime(
        _config: Any, _run: str, _arm: str, root: Path, _stage: str, **kwargs: Any
    ) -> Any:
        assert kwargs == {"enable_projection": False}
        with _runtime(root, store, wires, respond) as runtime:
            yield runtime

    monkeypatch.setattr(runner, "open_application_runtime", open_runtime)
    prepared = runner.prepare(args, lab_root=LAB)
    assert prepared["public_messages"] == 2
    identity = read_json(args.runtime_root / "run_manifest.json")["identity"]
    assert identity["correction_entries"] == 1 and not identity["automatic_maintenance"]
    args.phase = 1
    with pytest.raises(ValueError, match="PERSISTENT_MEMORY_PHASE_OUT_OF_ORDER"):
        runner.run(args, lab_root=LAB)
    args.phase = 0
    runner.run(args, lab_root=LAB)
    assert read_json(args.runtime_root / "run_manifest.json")["status"] == "PHASE_COMPLETED"
    args.phase = 1
    result = runner.run(args, lab_root=LAB)
    assert result["world"]["attempts"] == []
    assert len(wires) == 4
    assert "KEPT_BODY" in json.dumps(wires[-1]) and "OLD_SESSION_USER" not in json.dumps(wires[-1])
    turns = [read_json(path) for path in (args.runtime_root / "turns").glob("*.json")]
    assert len(turns) == 2 and all(row["status"] == "COMPLETED" for row in turns)
    assert all(row["ordinary_records"][0]["value"]["content"] == "KEPT_BODY" for row in turns)
    manifest = read_json(args.runtime_root / "run_manifest.json")
    accounting = manifest["accounting"]
    assert manifest["status"] == "TERMINAL"
    assert accounting["by_role"]["task_host"]["requests"] == 4
    assert accounting["by_control_stage"] == {}
    assert accounting["v3_checkpoint_costs"]["persistent_memory_checkpoint_read"]["calls"] == 2
    assert accounting["v3_checkpoint_costs"]["correction_checkpoint_write"]["calls"] == 1
    assert accounting["v3_checkpoint_costs"]["correction_checkpoint_write"]["logical_bytes"] > 0
    assert accounting["physical_store_io"] is None
    with pytest.raises(ValueError, match="PERSISTENT_MEMORY_ATTEMPT_ALREADY_STARTED"):
        runner.run(args, lab_root=LAB)
    assert len(wires) == 4
