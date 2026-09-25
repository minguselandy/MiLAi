"""Trusted observation intake and a small business-tool boundary for the same Host."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from milai_lab.methods.contextual_memory.models import Observation, receipt_outcome
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.providers.contextual_vllm import Emit
from milai_lab.runners.contextual_session import HostSession

if TYPE_CHECKING:
    from milai_lab.runners.contextual_host import ContextualHost, HostResult

Retention = Literal["session", "durable"]


@dataclass(frozen=True)
class BusinessToolResult:
    """A trusted executor's observation, not a model assertion of success."""

    call_id: str
    status: Literal["succeeded", "failed", "unknown"]
    output: Any
    observation: Observation | None = None


@dataclass(frozen=True)
class BusinessTool:
    schema: dict[str, Any]
    execute: Callable[[dict[str, Any], str], BusinessToolResult]


def dispatch_action(
    name: str, arguments: dict[str, Any], *,
    memory_dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
    business_tools: Mapping[str, BusinessTool], call_id: str,
) -> dict[str, Any] | BusinessToolResult:
    if name in business_tools:
        result = business_tools[name].execute(arguments, call_id)
        if not isinstance(result, BusinessToolResult) or result.call_id != call_id:
            raise ValueError("BUSINESS_RESULT_CALL_MISMATCH")
        return result
    return memory_dispatch(name, arguments)


def accept_observation(
    memory: ContextualMemory, session: HostSession, observation: Observation, *,
    retention: Retention = "session", max_bytes: int = 16000,
    emit: Emit | None = None, label: str = "Acquired observation",
    deliver: bool = True,
) -> dict[str, Any]:
    """Publish and retain under trusted policy; only transcript delivery grants visibility."""
    if session.memory is not memory or session.closed:
        raise ValueError("OBSERVATION_SESSION_MISMATCH")
    if retention not in {"session", "durable"}:
        raise ValueError("UNKNOWN_SOURCE_RETENTION")
    ref = memory.publish(observation)
    if ref not in memory.sources:
        return {"status": "SOURCE_UNAVAILABLE", "source_ref": ref, "delivered": False}
    duplicate = ref in session.observations
    retained = memory.save(
        op="RETAIN_SOURCE", source_ref=ref,
        persistence="durable" if retention == "durable" else "task",
    )
    outcome = receipt_outcome("memory_save", retained)
    if not outcome.ok:
        raise ValueError("OBSERVATION_RETENTION_FAILED")
    session.read_cache.clear()
    session.refresh_visibility()
    view = session.material_view
    assert view is not None
    if duplicate and ref in memory.seen:
        projected = session.observations[ref]
    else:
        page = memory.read(ref, include_sources=False, length=len(observation.content),
                           _visible=False)
        projected = view.project(page, max_bytes=max_bytes)
        if deliver:
            session.append_material(projected, label=label)
            session.observations[ref] = projected
    if emit:
        emit({
            "event": "observation_received", "session_id": session.session_id,
            "turn_id": session.turn_id, "event_id": observation.event_id,
            "source_ref": ref, "role": observation.role, "actor_ref": observation.actor_ref,
            "retention": retention, "duplicate_in_session": duplicate,
            "decision": outcome.decision, "memory_changes": list(outcome.memory_changes),
            "delivered": deliver, "materials": projected,
        })
    from milai_lab.runners.contextual_maintenance import observe

    observe(session, ref, projected, observation.role)
    return {"source_ref": ref, "duplicate": duplicate, "material": projected,
            "retention": retained, "delivered": deliver}


@dataclass(frozen=True)
class TaskTurn:
    turn_id: str
    question: str
    observations: tuple[Observation, ...] = ()
    conditions: dict[str, str] | None = None
    valid_at: str = ""


def run_task_session(
    turns: Sequence[TaskTurn], *, memory: ContextualMemory, host: ContextualHost,
    session_id: str, retention: Retention | None = None, max_bytes: int | None = None,
    handoff: dict[str, Any] | None = None,
    session: HostSession | None = None, close: bool = True,
) -> tuple[HostSession, list[HostResult]]:
    """Run public incremental turns; the environment and scorer remain caller-owned."""
    if host.memory is not memory:
        raise ValueError("HOST_MEMORY_MISMATCH")
    if not turns:
        raise ValueError("TASK_SESSION_REQUIRES_TURNS")
    from milai_lab.harness.contextual_artifacts import digest
    from milai_lab.runners.contextual_host import HostResult

    store = host.runtime_store
    retention = retention or host.observation_retention
    max_bytes = host.observation_bytes if max_bytes is None else max_bytes
    first = turns[0]
    if session is None and host.last_session is not None and not host.last_session.closed:
        if host.last_session.session_id == session_id:
            session = host.last_session
        elif host.maintenance_policy == "required" and (
            host.last_session.maintenance.get("pending") or
            host.last_session.maintenance.get("unsettled_operations")
        ):
            raise ValueError("PREVIOUS_SESSION_MAINTENANCE_PENDING")
    # Completed turn replay must not reset an unrelated active task or ingest twice.
    if store and len(turns) == 1 and store.completed_turn(session_id, first.turn_id) is not None:
        replay_session = session or HostSession(session_id, memory)
        reserved = store.reserve_turn(session_id, first.turn_id,
                                      input_sha256=digest(asdict(first)), memory=memory,
                                      session=replay_session)
        return replay_session, [HostResult(**reserved["result"])]
    continuing = session is not None
    if session is None:
        memory.start_task(session_id, first.question, handoff=handoff,
                          task_conditions=first.conditions, task_valid_at=first.valid_at)
        session = HostSession(session_id, memory)
    elif session.session_id != session_id or session.memory is not memory or session.closed:
        raise ValueError("TASK_SESSION_MISMATCH")
    host.last_session = session
    results = []
    for index, turn in enumerate(turns):
        reservation = (store.reserve_turn(
            session_id, turn.turn_id, input_sha256=digest(asdict(turn)),
            memory=memory, session=session,
        ) if store else None)
        if reservation and reservation["status"] == "complete":
            results.append(HostResult(**reservation["result"]))
            continue
        resume = bool(reservation and reservation["status"] == "in_progress"
                      and session.turn_id == turn.turn_id
                      and session.turn_index == reservation["turn_index"])
        if not resume and (index or continuing):
            memory.advance_turn(turn.question, conditions=turn.conditions, valid_at=turn.valid_at)
        session.turn_id = turn.turn_id
        if not resume:
            host.prime_session(session, turn.question)
        for observation in (() if resume else turn.observations):
            accept_observation(memory, session, observation, retention=retention,
                               max_bytes=max_bytes, emit=host.emit,
                               label="Current user request" if observation.content == turn.question
                               else "Acquired observation")
        # Avoid a second full copy when the current request was already delivered as a source.
        request_visible = any(
            observation.content == turn.question and any(
                row.get("content") == turn.question
                for material in session.observations.values()
                for row in material.get("materials", [])
            ) for observation in turn.observations
        )
        messages = ([] if request_visible or resume else
                    [{"role": "user", "content": turn.question}])
        results.append(host.run(messages, session=session,
                                turn_id=turn.turn_id, resume=resume))
        if store and results[-1].status == "complete":
            store.complete_turn(session_id, turn.turn_id, results[-1],
                                memory=memory, session=session)
        if results[-1].status != "complete":
            break
    if close and results[-1].status == "complete":
        session.close()
    if store:
        store.persist(memory, session)
    return session, results


@contextmanager
def task_runtime(
    config: dict[str, Any], *, user_id: str, output: Path,
    business_tools: Mapping[str, BusinessTool],
    state_path: Path | None = None,
) -> Iterator[tuple[ContextualMemory, ContextualHost, dict[str, Any]]]:
    """Open a bank and optional live-session store with continuous Host/embedding accounting."""
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, Trace, digest
    from milai_lab.providers.contextual_capacity import HostCapacity
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
    from milai_lab.runners.contextual import (
        COMMON_PROMPT,
        CONTEXT_PROMPT,
        CachedEmbedding,
        memory_tools,
    )
    from milai_lab.runners.contextual_host import ContextualHost
    from milai_lab.runners.contextual_runtime_store import RuntimeIdentity, RuntimeStore

    for artifact in config.get("model_identity", {}).get("artifacts", []):
        if hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError("PINNED_MODEL_IDENTITY_CHANGED")
    output.mkdir(parents=True, exist_ok=True)
    trace = Trace(output / "trace.jsonl", "host")
    budget = RunBudget(RunLimits(**config["budget"]), Path(config["budget_path"]))
    if state_path is None and config.get("runtime_store"):
        state_path = output / config["runtime_store"]
    store_context = (RuntimeStore(state_path, RuntimeIdentity.from_config(user_id, config))
                     if state_path is not None else nullcontext(None))
    with store_context as store, VLLMClient(VLLMConfig(**config["host"]), emit=trace, budget=budget,
                    capacity=HostCapacity(config["capacity"])) as client, VLLMClient(
        VLLMConfig(**config["embedding"]), emit=trace, budget=budget,
    ) as embedding:
        embed = CachedEmbedding(embedding, config, output / "embeddings.sqlite")
        try:
            memory = (store.restore_memory(embed) if store else None) or ContextualMemory(
                user_id, host_id=config["host"]["model"], embed=embed,
                embedding_model=config["embedding"]["model"],
                embedding_dimension=config["embedding_dimension"],
                embedding_identity=embed.identity, state_policy=config["state_policy"],
            )
            profile = {"off": "ordinary", "optional": "state_optional",
                       "forced_legacy": "state"}[config["state_policy"]]
            host = ContextualHost(
                client, memory.dispatch, memory_tools(profile),
                COMMON_PROMPT + (CONTEXT_PROMPT if config["state_policy"] != "off" else ""),
                emit=trace, memory=memory, business_tools=business_tools,
                observation_retention=config["source_retention"],
                observation_bytes=config["material_bytes"],
                initial_context_bytes=config.get("initial_context_bytes", 0),
                initial_context_limit=config.get("initial_context_limit", 4),
                maintenance_policy=config.get("maintenance_policy", "off"),
                runtime_store=store,
            )
            host.last_session = store.restore_session(memory) if store else None
            try:
                yield memory, host, {"config_sha256": digest(config), "budget": budget.state,
                                    "state_path": str(state_path) if state_path else None,
                                    "resumed_session": (host.last_session.session_id
                                                        if host.last_session else None)}
            finally:
                if store:
                    primary_error = sys.exc_info()[1]
                    try:
                        store.persist(memory, host.last_session)
                    except Exception as persistence_error:
                        if primary_error is None:
                            raise
                        primary_error.add_note(
                            "Runtime persistence during failure also failed: "
                            f"{type(persistence_error).__name__}: {persistence_error}"
                        )
        finally:
            embed.close()
