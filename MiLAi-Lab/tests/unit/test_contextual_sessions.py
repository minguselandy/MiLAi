"""The new session/observation/business boundaries; deterministic, no model usage."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.contextual import memory_tools
from milai_lab.runners.contextual_agent_tasks import (
    BusinessTool,
    BusinessToolResult,
    TaskTurn,
    accept_observation,
    run_task_session,
)
from milai_lab.runners.contextual_host import ContextualHost
from milai_lab.runners.contextual_session import HostSession


def bank(policy: str = "off") -> ContextualMemory:
    return ContextualMemory(
        "owner",
        host_id="fixture",
        state_policy=policy,
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2,
    )


def test_incremental_session_uses_explicit_binding_and_never_caches_business_execution() -> None:
    memory = bank("optional")
    requests: list[dict[str, Any]] = []
    executed: list[str] = []

    def executor(args: dict[str, Any], call_id: str) -> BusinessToolResult:
        executed.append(call_id)
        return BusinessToolResult(
            call_id,
            "unknown" if len(executed) == 1 else "succeeded",
            {"status": "UNKNOWN_MEMORY_TOOL", "actual_count": len(executed)},
        )

    schema = {
        "type": "function",
        "function": {
            "name": "do_work",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }
    actions = [
        {"tool": "do_work", "arguments": {}},
        {"answer": "First turn ended."},
        {"tool": "do_work", "arguments": {}},
        {"answer": "Next turn ended."},
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(actions.pop(0)),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    with VLLMClient(
        VLLMConfig("http://fixture/v1", "fixture", max_calls=2),
        transport=httpx.MockTransport(respond),
    ) as client:
        host = ContextualHost(
            client,
            lambda name, args: memory.dispatch(name, args),
            memory_tools("state_optional"),
            "Do the task.",
            memory=memory,
            business_tools={"do_work": BusinessTool(schema, executor)},
        )
        session, first = run_task_session(
            [
                TaskTurn(
                    "first",
                    "Work once",
                    observations=(
                        Observation(
                            "request", "Work once", "user", "fixture", actor_ref="operator"
                        ),
                    ),
                )
            ],
            memory=memory,
            host=host,
            session_id="work",
            close=False,
        )
        first_transcript = json.dumps(first[0].transcript)
        session, second = run_task_session(
            [TaskTurn("second", "Work again")],
            memory=memory,
            host=host,
            session_id="work",
            session=session,
        )
    assert len(executed) == 2 and executed[0] != executed[1]
    assert first[0].calls[0]["execution_status"] == "unknown"
    assert second[0].calls[0]["execution_status"] == "succeeded"
    assert all("operation_receipt" not in result.calls[0] for result in [*first, *second])
    assert memory.workspace.frame.question == "Work again" and not memory.state_used
    assert first_transcript == json.dumps(first[0].transcript)
    # Final-turn controls exist only in their own provider request.
    assert len(requests[2]["messages"]) == len(first[0].transcript) + 1
    assert not memory.retained and len(memory.task_sources) == 3
    assert sum(source.role == "tool" for source in memory.sources.values()) == 2
    assert requests[0]["messages"][-1]["content"].startswith("Current user request:")
    assert requests[0]["messages"][-1]["content"].count("Work once") == 1
    assert session.closed
    memory.start_task("next", "Independent task")
    assert not memory.sources and not memory.seen


def test_actor_delivery_duplicate_and_removed_message_visibility() -> None:
    memory = bank()
    memory.start_task("session", "Inspect")
    session = HostSession("session", memory)
    unknown = Observation("unknown", "I prefer tea", "user", "fixture")
    acquired = accept_observation(memory, session, unknown)
    assert acquired["material"]["materials"][0]["retention"] == "session"
    ref = acquired["source_ref"]
    row = acquired["material"]["materials"][0]
    assert row["speaker_ref"] != "u0" and memory.source_subject(ref) == "speaker:" + ref
    assert session.material_view is not None
    assert "u0" not in {item["ref"] for item in session.material_view.subject_catalogue()}
    with pytest.raises(ValueError, match="MATERIAL_REF_NOT_DELIVERED"):
        session.material_view.binding("u0")
    size = len(session.transcript)
    repeated = accept_observation(memory, session, unknown)
    assert repeated["duplicate"] and len(session.transcript) == size
    actor = Observation("actor", "I prefer coffee", "user", "fixture", actor_ref="person-a")
    later = accept_observation(memory, session, actor)
    actor_row = later["material"]["materials"][0]
    assert memory.source_subject(later["source_ref"]) == "actor:person-a"
    assert actor_row["speaker_ref"] != row["speaker_ref"]
    session.transcript.remove(session.transcript[-1])
    session.refresh_visibility()
    assert later["source_ref"] not in memory.seen
    assert ref in memory.seen
    assert session.material_view is not None
    with pytest.raises(ValueError, match="MATERIAL_REF_NOT_DELIVERED"):
        session.material_view.binding(actor_row["ref"])
    hidden = accept_observation(
        memory, session, Observation("hidden", "Long text " * 1000, "tool", "fixture"), max_bytes=1
    )
    assert hidden["source_ref"] not in memory.seen
    assert hidden["material"]["status"] == "INSUFFICIENT_MATERIAL_BUDGET"


def test_source_needed_by_durable_record_survives_new_task_only_after_actual_delivery() -> None:
    memory = bank()
    memory.start_task("one", "Learn")
    session = HostSession("one", memory)
    acquired = accept_observation(
        memory,
        session,
        Observation(
            "fact", "Use short document headings.", "user", "fixture", actor_ref="current_user"
        ),
    )
    record = memory.save(
        op="CREATE",
        content="Use short document headings.",
        about_ref="current_user",
        source_refs=[acquired["source_ref"]],
        certainty="explicit",
        dependencies=[],
    )["record"]["ref"]
    accept_observation(
        memory, session, Observation("unused", "Transient result", "tool", "fixture")
    )
    checkpoint = memory.checkpoint(include_task=False)
    restored = ContextualMemory.restore(
        checkpoint, user_id="owner", embed=memory.embed, state_policy="optional"
    )
    restored.start_task("two", "Edit another document")
    assert not restored.seen
    assert set(restored.sources) == {acquired["source_ref"]}
    next_session = HostSession("two", restored)
    assert next_session.material_view is not None
    material = next_session.material_view.project(restored.read(record, _visible=False))
    assert record not in restored.seen
    next_session.append_material(material)
    assert record in restored.seen


def test_disabled_memory_names_remain_reserved_for_dispatch() -> None:
    memory = bank()
    schema = {"type": "function", "function": {"name": "memory_state", "parameters": {}}}
    with VLLMClient(VLLMConfig("http://fixture/v1", "fixture")) as client:
        with pytest.raises(ValueError, match="BUSINESS_MEMORY_TOOL_NAME_CONFLICT"):
            ContextualHost(client, memory.dispatch, memory_tools("ordinary"), "Work",
                           memory=memory, business_tools={"memory_state": BusinessTool(
                               schema, lambda args, call: BusinessToolResult(call, "unknown", {}))})
