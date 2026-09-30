"""Opt-in hard-exit/restart driver over the existing public D0 composition.

Crash controls are a driver side channel. Public text, prompts and tool inputs
never receive the window/selector. No scorer, rubric or hidden snapshot is read
by the Host. SQLite evidence is bounded to these cooperating serial processes;
this driver makes no universal transaction or exactly-once claim.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import inspect
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.store.sqlite import SqliteStore
from langgraph.types import Command

from milai_lab.application.document_publication import (
    DOCUMENT_MUTATIONS,
    DOCUMENT_NAMES,
    DocumentPublicationWorld,
    document_schemas,
)
from milai_lab.application.journal import BusinessActionJournal
from milai_lab.application.recovery import recover_pending_application_call
from milai_lab.application.refs import verified_document_ref, verified_reservation_ref
from milai_lab.application.tools import (
    BUSINESS_NAMES,
    BUSINESS_SCHEMAS,
    _business_tools,
    document_business_tools,
)
from milai_lab.application.world import ApplicationWorld
from milai_lab.baselines.langmem_agent import build_agent
from milai_lab.baselines.v13_1_controls import generation_cap
from milai_lab.contracts.memory import GroundingMode
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, Trace
from milai_lab.memory.service import MemoryService
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import v13_1_d0 as d0

LAB = d0.LAB
POLICY = {
    "checkpoint_durability": "sync",
    "application_protection": True,
    "memory_requested_replay": True,
    "recovery": "authorized_public_query_separate_from_unknown_original",
    "native_recovery_retry": "confirmed_no_effect_v1_explicit_permission_only",
    "max_concurrency": 1,
    "transport": "direct_existing_agent_tools",
    "windows": {
        "W1": "actual_native_return_before_journal_receipt_response_hook",
        "W2": "journal_receipt_and_source_capture_before_next_memory_proposal",
        "W3": "durable_memory_commit_before_tool_graph_delivery",
    },
}


def _sources() -> dict[str, str]:
    return {**d0._sources(), "tools/run_v13_1_p5.py": d0._sha(LAB / "tools/run_v13_1_p5.py")}


def case_path(root: Path, case_id: str) -> Path:
    return root / hashlib.sha256(case_id.encode()).hexdigest()[:16]


def _sdk() -> dict[str, Any]:
    return {
        "versions": {
            name: importlib.metadata.version(name)
            for name in (
                "langgraph",
                "langgraph-checkpoint",
                "langgraph-checkpoint-sqlite",
                "langchain-core",
            )
        },
        "sqlite_modules": {
            cls.__name__: {
                "path": inspect.getfile(cls),
                "sha256": d0._sha(Path(inspect.getfile(cls))),
            }
            for cls in (SqliteStore, SqliteSaver)
        },
    }


def _binding(frozen: dict[str, Any], case: dict[str, Any], index: int) -> dict[str, Any]:
    public = case["messages"][index]
    scope = FoundationScope(frozen["run_id"], frozen.get("scope_arm", frozen["mode"]),
                            case["owner"], public["session_id"])
    authorization = public.get("application_binding")
    if not isinstance(authorization, dict) or set(authorization) - {
        "task_id",
        "operations",
        "recovery",
    }:
        raise ValueError("V13_P5_PUBLIC_AUTHORIZATION_REQUIRED")
    return {
        **authorization,
        "run_id": scope.run_id,
        "arm_id": scope.arm_id,
        "owner": scope.user_id,
        "thread_id": scope.config()["configurable"]["thread_id"],
        "message_id": public["message_id"],
        "public_index": sum(
            row["session_id"] == public["session_id"] for row in case["messages"][:index]
        ),
    }


def application_workflow(settings: dict[str, Any]) -> str:
    value = settings.get("application_workflow", "reservation_v1")
    if type(value) is not str or value not in {"reservation_v1", "document_publication_v1"}:
        raise ValueError("V13_P5_APPLICATION_WORKFLOW_INVALID")
    return str(value)


def business_schemas(settings: dict[str, Any]) -> list[dict[str, Any]]:
    if application_workflow(settings) == "document_publication_v1":
        return document_schemas()
    return BUSINESS_SCHEMAS


def _catalog(root: Path, mode: GroundingMode, settings: dict[str, Any]) -> list[dict[str, Any]]:
    contract = d0._receipt_contract(settings)
    d0._observation_profile(settings)
    mutation_contract = d0._mutation_contract(settings)
    d0._recipe_settings(settings)
    if application_workflow(settings) == "reservation_v1":
        return d0._catalog(root, mode, receipt_contract=contract,
                           mutation_contract=mutation_contract,
                           service_options=d0._service_options(settings),
                           settings=settings)
    with SqliteStore.from_conn_string(":memory:") as store:
        service = MemoryService(
            store,
            ("schema", "owner"),
            "owner",
            root / "memory.lock",
            mode=mode,
            receipt_contract=contract,
            receipt_profile="document_publication_v1",
            mutation_contract=mutation_contract,
            **d0._service_options(settings),
        )
        return [*map(convert_to_openai_tool, d0._memory_tools(service, settings)),
                *document_schemas()]


def prepare(
    fixture_path: Path, config_path: Path, root: Path, mode: GroundingMode = "field_grounded"
) -> dict[str, Any]:
    """Validate/freeze without constructing a model, client or optional native SDK."""
    fixture, settings = read_json(fixture_path), read_json(config_path)
    if fixture.get("kind") != "MILAI_V13_1_D0_NORMAL_USE" or not fixture.get("cases"):
        raise ValueError("V13_P5_PUBLIC_FIXTURE_REQUIRED")
    if mode not in {"ref_only", "field_grounded"}:
        raise ValueError("V13_P5_MODE_INVALID")
    VLLMConfig(**settings["host"])
    try:
        cap = generation_cap(settings)
    except ValueError:
        if "generation_cap_profile" not in settings:
            raise ValueError("V13_P5_GENERATION_CAP_INVALID") from None
        raise
    workflow = application_workflow(settings)
    if not isinstance(settings.get("capacity"), dict):
        raise ValueError("V13_P5_CAPACITY_REQUIRED")
    budget_path = Path(settings["budget_path"])
    if not budget_path.is_file():
        raise ValueError("V13_P5_EXISTING_CONTINUOUS_BUDGET_REQUIRED")
    prompt = d0._system_prompt(settings)
    contract = d0._receipt_contract(settings)
    frozen: dict[str, Any] = {
        "kind": "MILAI_V13_1_P5_RUNTIME_FREEZE",
        "run_id": root.resolve().name,
        "mode": mode,
        "fixture": fixture,
        "fixture_path": str(fixture_path.resolve()),
        "fixture_sha256": d0._sha(fixture_path),
        "config": settings,
        "config_path": str(config_path.resolve()),
        "config_sha256": d0._sha(config_path),
        "source_sha256": _sources(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "memory_receipt_contract": contract,
        "budget_limits": read_json(budget_path)["limits"],
        "policy": POLICY,
        "backend": "public_sdk_sqlite",
        "memory_retrieval": "raw_keyword",
        "semantic_evidence": False,
        "runtime_sdk": _sdk(),
        "tool_catalog": _catalog(root, mode, settings),
    }
    if workflow != "reservation_v1":
        frozen["application_workflow"] = workflow
        frozen["receipt_profile"] = workflow
    if "generation_cap_profile" in settings:
        frozen["generation_cap_profile"] = settings["generation_cap_profile"]
        frozen["effective_generation_cap"] = cap
    if d0._mutation_contract(settings) != "legacy":
        frozen["memory_mutation_contract"] = d0._mutation_contract(settings)
    recipe_policy = d0._recipe_settings(settings)
    if recipe_policy is not None:
        frozen["memory_reader_policy"] = recipe_policy
    if d0._observation_profile(settings) is not None:
        frozen["policy"] = {**frozen["policy"], "windows": {
            **frozen["policy"]["windows"],
            "W2_projection": "actual_source_durable_before_projection_commit",
            "W3_projection": "projection_complete_marker_durable_before_delivery",
        }}
    seen: set[str] = set()
    with TemporaryDirectory() as temporary:
        for case in fixture["cases"]:
            if (
                type(case.get("case_id")) is not str
                or not case["case_id"]
                or case["case_id"] in seen
                or type(case.get("owner")) is not str
                or not case["owner"]
                or not case.get("messages")
            ):
                raise ValueError("V13_P5_CASE_IDENTITY_INVALID")
            seen.add(case["case_id"])
            journal = BusinessActionJournal(
                Path(temporary) / (str(len(seen)) + ".json"),
                DOCUMENT_NAMES if workflow == "document_publication_v1" else BUSINESS_NAMES,
                application_protection=True,
                application_workflow=workflow,
            )
            message_ids: set[str] = set()
            for index, public in enumerate(case["messages"]):
                if not all(
                    type(public.get(key)) is str and public[key]
                    for key in ("message_id", "session_id", "content")
                ):
                    raise ValueError("V13_P5_PUBLIC_MESSAGE_INVALID")
                if public["message_id"] in message_ids:
                    raise ValueError("V13_P5_MESSAGE_IDENTITY_DUPLICATE")
                message_ids.add(public["message_id"])
                journal.bind_request(_binding(frozen, case, index))
    frozen["tool_catalog_sha256"] = hashlib.sha256(
        json.dumps(frozen["tool_catalog"], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "input-freeze.json"
    if target.exists() and read_json(target) != frozen:
        raise ValueError("V13_P5_INPUT_FREEZE_CHANGED")
    write_json(target, frozen)
    return frozen


def _frozen(root: Path) -> dict[str, Any]:
    frozen = read_json(root / "input-freeze.json")
    if frozen["source_sha256"] != _sources():
        raise ValueError("V13_P5_SOURCE_CHANGED_AFTER_FREEZE")
    if frozen["runtime_sdk"] != _sdk():
        raise ValueError("V13_P5_SDK_CHANGED_AFTER_FREEZE")
    if frozen["fixture_sha256"] != d0._sha(Path(frozen["fixture_path"])) or frozen[
        "config_sha256"
    ] != d0._sha(Path(frozen["config_path"])):
        raise ValueError("V13_P5_INPUT_CHANGED_AFTER_FREEZE")
    return cast(dict[str, Any], frozen)


def make_model(
    settings: dict[str, Any], budget: RunBudget, trace: Trace, resource_root: Path
) -> LangMemRecipeChatModel:
    """Production uses exactly the existing accounted client/model bridge."""
    client = VLLMClient(
        VLLMConfig(**settings["host"]),
        emit=trace,
        budget=budget,
        capacity=HostCapacity(settings["capacity"]),
    )
    return LangMemRecipeChatModel(
        client=client,
        capacity_path=resource_root / "host-capacity.json",
        max_calls_per_message=settings.get("max_calls_per_message", 12),
    )


class _RecoveryCapture:
    """Capture only the actual separately executed public query, without wrapping its body."""

    def __init__(self, capture: Any, trace: Trace) -> None:
        self.capture, self.trace = capture, trace

    def begin_public_message(self, scope: FoundationScope, public_index: int, content: str) -> None:
        self.trace(
            {
                "event": "v13_p5_recovery_discovery",
                "owner": scope.user_id,
                "session": scope.episode_id,
                "public_index": public_index,
            }
        )

    def run_tool(self, request: ToolCallRequest, execute: Any, business_journal: Any = None) -> Any:
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        observation: dict[str, Any] = {
            "event": "v13_p5_program_discovery",
            "call": request.tool_call,
            "generation_requests": 0,
            "io_accounting": "public_query_only_partial",
        }
        try:
            response = execute(request)
            if isinstance(response, ToolMessage):
                observation["actual_query_result"] = response.model_dump(mode="json")
                self.capture(request, response, wrap=False)
            return response
        except Exception as error:
            observation["error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            observation.update(
                wall_ns=time.perf_counter_ns() - wall, cpu_ns=time.process_time_ns() - cpu
            )
            self.trace(observation)

    @property
    def observer(self) -> _RecoveryCapture:
        return self


def step(
    root: Path,
    case_id: str,
    message_index: int,
    *,
    phase: str = "start",
    window: str = "none",
    window_tool: str | None = None,
    hit: int = 1,
    attempt_id: str = "start",
    label_available: bool | None = None,
    world_event_id: str | None = None,
    publication_available: bool | None = None,
    document_edit: dict[str, str] | None = None,
    composition: Any = None,
) -> dict[str, Any]:
    """One process/attempt. Hard kill intentionally bypasses cleanup and final delivery."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    resource_root = case_path(root, case_id)
    resource_root.mkdir(parents=True, exist_ok=True)
    if not attempt_id or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for c in attempt_id
    ):
        raise ValueError("V13_P5_ATTEMPT_ID_INVALID")
    receipt_path = resource_root / f"attempt-{attempt_id}.json"
    if receipt_path.exists():
        raise ValueError("V13_P5_ATTEMPT_ALREADY_RECORDED")
    controls: dict[str, Any] = {
        "phase": phase,
        "window": window,
        "window_tool": window_tool,
        "hit": hit,
        "label_available": label_available,
        "world_event_id": world_event_id,
    }
    if publication_available is not None or document_edit is not None:
        controls.update(publication_available=publication_available, document_edit=document_edit)
    output: dict[str, Any] = {
        "case_id": case_id,
        "message_index": message_index,
        "process_id": os.getpid(),
        "attempt_id": attempt_id,
        "driver_controls": controls,
        "status": "initializing",
    }
    trace = Trace(resource_root / f"attempt-{attempt_id}.jsonl", "v13_1_p5")
    active: dict[str, Any] = {}

    def evidence() -> None:
        output.update(
            execution_wall_ns=time.perf_counter_ns() - wall,
            execution_cpu_ns=time.process_time_ns() - cpu,
            cost_scope="generation full via existing client; IO partial",
            usage=trace.usage,
            persistent_resource_bytes={
                p.name: p.stat().st_size for p in resource_root.glob("*.sqlite*")
            },
        )
        if "budget" in active:
            output["budget"] = active["budget"].state
        admission_path = resource_root / "host-capacity.json"
        output["generation_admissions"] = (
            read_json(admission_path) if admission_path.exists() else {}
        )
        if "service" in active:
            service = active["service"]
            output.update(
                records=service.records(),
                sources=service.sources(),
                bank=service._rows(service.namespace),
                attempts=service._rows(service.attempts_namespace),
            )
            if frozen["config"].get("memory_observation_profile") is not None:
                output["observations"] = service.observations()
        if "comparison" in active:
            output["comparison"] = active["comparison"].snapshot()
        if "world" in active:
            # Evaluator sidecar only. Never fed into graph, prompt or any tool input.
            output["world"] = active["world"].snapshot()
        if "journal" in active:
            output["action_journal"] = read_json(active["journal"].path)
            output["business_calls"] = active["journal"].calls_for_thread(active["thread_id"])
        if "agent" in active:
            state = active["agent"].get_state(active["config"])
            messages = state.values.get("messages", []) if state.values else []
            output["checkpoint"] = {
                "config": state.config,
                "next": list(state.next),
                "messages": [m.model_dump(mode="json") for m in messages],
            }
            output["checkpoint_history"] = [
                {
                    "config": s.config,
                    "parent_config": s.parent_config,
                    "next": list(s.next),
                    "metadata": s.metadata,
                    "messages": [m.model_dump(mode="json") for m in s.values.get("messages", [])],
                }
                for s in active["agent"].get_state_history(active["config"])
            ]
            current_start = next(
                (
                    i
                    for i, m in enumerate(messages)
                    if isinstance(m, HumanMessage) and m.id == output.get("message_id")
                ),
                len(messages),
            )
            output["final_answer"] = next(
                (
                    m.content
                    for m in reversed(messages[current_start + 1 :])
                    if isinstance(m, AIMessage) and not m.tool_calls
                ),
                None,
            )
        output["logical_source_snapshot_bytes"] = len(
            json.dumps(output.get("sources", []), ensure_ascii=False).encode()
        )
        output["logical_bank_snapshot_bytes"] = len(
            json.dumps(output.get("bank", []), ensure_ascii=False).encode()
        )
        output["material_trace_path"] = str(trace.path)
        output["cost_measurement_note"] = (
            "wall/CPU excludes imports; snapshots are not total Store IO; actual query and "
            "ref binder are traced separately; controls/evaluator world never enter Host"
        )

    matched = 0
    captured = False

    def crash_at(boundary: str, tool: str, actual: dict[str, Any]) -> None:
        nonlocal matched
        if window != boundary or (window_tool is not None and window_tool != tool):
            return
        matched += 1
        if matched != hit:
            return
        # This witness is driver evidence, not a SourceEvent or a replacement receipt.
        output.update(status="hard_exit_armed", boundary=boundary, boundary_witness=actual)
        evidence()
        write_json(receipt_path, output)
        trace(
            {
                "event": "v13_p5_hard_exit_armed",
                "boundary": boundary,
                "tool": tool,
                "process_id": os.getpid(),
            }
        )
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL_DID_NOT_TERMINATE")

    def evidence_before_close() -> None:
        try:
            evidence()
        except Exception as error:
            output["evidence_error"] = {"type": type(error).__name__, "error": str(error)}
        finally:
            active["evidence_collected_before_close"] = True

    try:
        if phase not in {"start", "resume"} or window not in {
            "none", "W1", "W2", "W3", "W2_projection", "W3_projection"
        }:
            raise ValueError("V13_P5_PHASE_OR_WINDOW_INVALID")
        if type(hit) is not int or hit < 1 or (phase == "resume" and window != "none"):
            raise ValueError("V13_P5_WINDOW_CONTROL_INVALID")
        if (
            publication_available is None
            and document_edit is None
            and (
                (label_available is None) != (world_event_id is None)
                or (
                    label_available is not None
                    and (
                        type(label_available) is not bool
                        or type(world_event_id) is not str
                        or not world_event_id
                    )
                )
            )
        ):
            raise ValueError("V13_P5_WORLD_EVENT_INVALID")
        frozen = _frozen(root) if composition is None else composition.frozen(root)
        case = next(row for row in frozen["fixture"]["cases"] if row["case_id"] == case_id)
        if not 0 <= message_index < len(case["messages"]):
            raise ValueError("V13_P5_MESSAGE_INDEX_INVALID")
        public, settings = case["messages"][message_index], frozen["config"]
        if (window in {"W2_projection", "W3_projection"}
                and d0._observation_profile(settings) is None):
            raise ValueError("V13_PROJECTION_WINDOW_REQUIRES_OPT_IN")
        workflow = application_workflow(settings)
        document_mode = workflow == "document_publication_v1"
        names = DOCUMENT_NAMES if document_mode else BUSINESS_NAMES
        if publication_available is not None or document_edit is not None:
            if not document_mode or label_available is not None or not world_event_id:
                raise ValueError("V13_P5_DOCUMENT_EVENT_INVALID")
        if document_mode and label_available is not None:
            raise ValueError("V13_P5_RESERVATION_EVENT_WRONG_WORKFLOW")
        scope = FoundationScope(
            frozen["run_id"],
            frozen.get("scope_arm", frozen["mode"]),
            case["owner"],
            public["session_id"],
        )
        config = scope.config()
        config["configurable"]["v13_session"] = scope.episode_id
        config["configurable"]["v13_turn_id"] = public["message_id"]
        active.update(config=config, thread_id=config["configurable"]["thread_id"])
        output.update(
            message_id=public["message_id"],
            session=scope.episode_id,
            owner=scope.user_id,
            source_sha256=frozen["source_sha256"],
            fixture_sha256=frozen["fixture_sha256"],
        )
        with ExitStack() as finalizers:
            # Evidence owns the outer lifetime. All current and subsequently
            # registered SDK/client/Store resources remain live for this one
            # readback, including when initialization or execution raises.
            stack = finalizers.enter_context(ExitStack())
            finalizers.callback(evidence_before_close)
            lock = stack.enter_context((root / "execution.lock").open("a+b"))
            fcntl.flock(lock, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**frozen["budget_limits"]), Path(settings["budget_path"]))
            active["budget"] = budget
            store = stack.enter_context(
                SqliteStore.from_conn_string(str(resource_root / "memory.sqlite"))
            )
            saver = stack.enter_context(
                SqliteSaver.from_conn_string(str(resource_root / "checkpoints.sqlite"))
            )
            world = (
                DocumentPublicationWorld(
                    resource_root / "world.sqlite",
                    case.get("initial_world", {}).get("publication_available", True),
                )
                if document_mode
                else ApplicationWorld(
                    resource_root / "world.sqlite",
                    case.get("initial_world", {}).get("label_available", True),
                )
            )
            active["world"] = world
            stack.callback(world.close)
            if world_event_id is not None:
                if document_mode:
                    event = cast(DocumentPublicationWorld, world).apply_backend_event(
                        world_event_id,
                        available=publication_available,
                        edit=document_edit,
                        owner=scope.user_id,
                    )
                    trace(
                        {
                            "event": "v13_p5_backend_event",
                            "event_id": world_event_id,
                            "actual": event,
                        }
                    )
                else:
                    world.set_label_available(world_event_id, cast(bool, label_available))
            if world_event_id is not None and not document_mode:
                trace(
                    {
                        "event": "v13_p5_backend_event",
                        "event_id": world_event_id,
                        "label_available": label_available,
                    }
                )
            def service_observer(event: dict[str, Any]) -> None:
                trace(event)
                if event.get("event") == "v13_observation_boundary":
                    boundary = {"source_persisted": "W2_projection",
                                "projection_committed": "W3_projection"}[event["phase"]]
                    crash_at(boundary, "observe", event)

            service = MemoryService(
                store,
                ("langmem", scope.run_id, scope.arm_id, scope.user_id),
                scope.user_id,
                resource_root / "memory.lock",
                mode=frozen["mode"],
                receipt_contract=d0._receipt_contract(settings),
                mutation_contract=d0._mutation_contract(settings),
                **d0._service_options(settings),
                observer=service_observer,
                **({"receipt_profile": "document_publication_v1"} if document_mode else {}),
                **({} if composition is None else composition.service_options(frozen)),
            )
            active["service"] = service

            def response_hook(row: dict[str, Any], response: ToolMessage) -> None:
                if row["name"] in (
                    DOCUMENT_MUTATIONS if document_mode else {"reserve_and_label", "complete_label"}
                ):
                    crash_at(
                        "W1",
                        row["name"],
                        {
                            "journal_row": row,
                            "actual_native_return": response.model_dump(mode="json"),
                        },
                    )

            journal = BusinessActionJournal(
                resource_root / "business-journal.json",
                names,
                application_protection=True,
                response_hook=response_hook,
                application_workflow=workflow,
            )
            active["journal"] = journal
            journal.bind_request(_binding(frozen, case, message_index))

            def capture(
                request: ToolCallRequest, response: ToolMessage, *, wrap: bool = True
            ) -> ToolMessage:
                nonlocal captured
                call, generating = request.tool_call, request.state["messages"][-1]
                call_id = call["id"]
                if not call_id or not generating.id:
                    raise ValueError("V13_P5_TOOL_CALL_IDENTITY_MISSING")
                row = journal.entry_for_call(active["thread_id"], generating.id, call_id)
                if row is None or not row.get("executed") or row["status"] != "complete":
                    return response
                body = str(response.content)
                identity = str(generating.id) + ":" + call_id
                source_ref = service.event_id(scope.episode_id, identity, "tool")
                binder = verified_document_ref if document_mode else verified_reservation_ref
                ref = binder(world, scope.user_id, source_ref, call["name"], body, observer=trace)
                receipt = service.capture_tool(scope.episode_id, identity, call["name"], body, ref)
                service.bind_source_boundary(scope.episode_id, str(generating.id),
                                             [receipt["source_ref"]], append=True)
                projection = d0._observe_captured(service, receipt["source_ref"], settings, trace)
                if not receipt["ok"]:
                    raise ValueError("V13_P5_TOOL_SOURCE_CAPTURE_REJECTED:" + receipt["status"])
                captured = True
                trace(
                    {
                        "event": "v13_source_capture",
                        "receipt": receipt,
                        "actual_tool_receipt": response.model_dump(mode="json"),
                        "origin": row["origin"],
                    }
                )
                if "comparison" in active:
                    active["comparison"].observed(receipt["source_ref"])
                if not wrap:
                    return response
                return response.model_copy(
                    update={
                        "content": json.dumps(
                            {
                                "receipt": json.loads(body),
                                "source_ref": receipt["source_ref"],
                                "object_ref": ref.id if ref else None,
                                "observation_only": True,
                                **(
                                    {"observation_capture": projection}
                                    if projection is not None else {}
                                ),
                            },
                            ensure_ascii=False,
                        )
                    }
                )

            def wrapper(request: ToolCallRequest, execute: Any) -> ToolMessage | Command[Any]:
                name = request.tool_call["name"]
                if name == "manage_memory" and captured:
                    crash_at("W2", name, {"requested_call": request.tool_call})
                response = journal(request, execute)
                if name in names and isinstance(response, ToolMessage):
                    response = capture(request, response)
                if name == "manage_memory" and isinstance(response, ToolMessage):
                    receipt = json.loads(str(response.content))
                    trace(
                        {
                            "event": "v13_p5_memory_receipt",
                            "call": request.tool_call,
                            "receipt": receipt,
                        }
                    )
                    if (
                        receipt.get("ok")
                        and receipt.get("status") == "committed"
                        and (
                            composition is None
                            or request.tool_call["args"].get("action") == "update"
                        )
                    ):
                        crash_at(
                            "W3", name, {"requested_call": request.tool_call, "receipt": receipt}
                        )
                return response

            model = make_model(settings, budget, trace, resource_root)
            stack.callback(model.client.close)
            recipe = d0._make_recipe(service, settings, model, budget, trace, stack)
            if recipe is not None and composition is not None:
                raise ValueError("V13_RECIPE_COMPARISON_HOOK_CONFLICT")
            comparison = None
            if composition is not None:
                comparison = active["comparison"] = composition.open(
                    frozen=frozen,
                    service=service,
                    store=store,
                    saver=saver,
                    scope=scope,
                    model=model,
                    budget=budget,
                    trace=trace,
                    resource_root=resource_root,
                    stack=stack,
                    crash_at=crash_at,
                    wrapper=wrapper,
                )
            agent = build_agent(
                model,
                store,
                saver,
                document_business_tools(world, scope.user_id)
                if document_mode
                else _business_tools(world, scope.user_id),
                business_call_wrapper=wrapper,
                memory_tools=(
                    d0._memory_tools(service, settings, replay_requested=True, recipe=recipe)
                    if comparison is None
                    else comparison.tools()
                ),
                system_prompt=d0._system_prompt(settings),
                benchmark_view_hook=(recipe.hook(d0._system_prompt(settings), prefetch=bool(
                    settings.get("memory_reader_policy")
                    and settings.get("memory_prefetch", "enabled") == "enabled"))
                    if recipe is not None else None if comparison is None else comparison.hook),
            )
            active["agent"] = agent
            state = agent.get_state(config)
            prior = state.values.get("messages", []) if state.values else []
            already = any(
                isinstance(m, HumanMessage) and m.id == public["message_id"] for m in prior
            )
            if phase == "resume" and not already:
                raise ValueError("V13_P5_RESUME_CHECKPOINT_MISSING")
            if phase == "start" and already:
                raise ValueError("V13_P5_PUBLIC_MESSAGE_ALREADY_STARTED")
            capture_receipt = service.capture_user(
                scope.episode_id, public["message_id"], public["content"]
            )
            service.bind_source_boundary(scope.episode_id, public["message_id"],
                                         [capture_receipt["source_ref"]])
            output["capture_receipt"] = capture_receipt
            if not capture_receipt["ok"]:
                raise ValueError("V13_P5_USER_SOURCE_CAPTURE_REJECTED")
            trace(
                {
                    "event": "v13_public_input",
                    "message_id": public["message_id"],
                    "content": public["content"],
                    "process_id": os.getpid(),
                    "owner": scope.user_id,
                    "session": scope.episode_id,
                }
            )
            public_start = next(
                (
                    i
                    for i, m in enumerate(prior)
                    if isinstance(m, HumanMessage) and m.id == public["message_id"]
                ),
                -1,
            )
            checkpoint_calls = (
                sum(isinstance(m, AIMessage) for m in prior[public_start + 1 :]) if already else 0
            )
            # Existing bridge admission file is written before client/provider dispatch.
            # Unknown provider outcomes consume this same per-message key on every attempt.
            model.begin_public_message(public["message_id"], checkpoint_calls=checkpoint_calls)
            if phase == "resume":
                recover_pending_application_call(
                    agent,
                    scope,
                    journal,
                    world,
                    _RecoveryCapture(capture, trace),
                    application_workflow=workflow,
                )
                state = agent.get_state(config)
                if comparison is not None:
                    comparison.recovered(state.values.get("messages", []))
            if phase == "start" or state.next:
                agent.invoke(
                    None
                    if phase == "resume"
                    else {
                        "messages": [
                            HumanMessage(content=public["content"], id=public["message_id"])
                        ]
                    },
                    config=config,
                    durability="sync",
                )
            if service.mutation_contract == "event_bound_v1":
                final_state = agent.get_state(config)
                d0._capture_final_assistant(
                    service, scope.episode_id, public["message_id"],
                    final_state.values.get("messages", []) if final_state.values else [], trace,
                )
                maintenance = d0._maintain_final(
                    recipe, model, service, settings, scope.episode_id, public["message_id"],
                    final_state.values.get("messages", []) if final_state.values else [],
                    config, trace,
                )
                if maintenance is not None:
                    output["semantic_maintenance"] = maintenance
            if comparison is not None:
                comparison.completed()
            output["status"] = "completed"
            if window != "none":
                output["window_status"] = "NOT_REACHED"
        if "evidence_error" in output:
            raise RuntimeError("V13_P5_EVIDENCE_CAPTURE_FAILED:" + str(output["evidence_error"]))
    except Exception as error:
        output.update(status="interrupted", error_type=type(error).__name__, error=str(error))
        first_path = resource_root / "first-error.json"
        if not first_path.exists():
            write_json(
                first_path,
                {"attempt_id": attempt_id, "error_type": type(error).__name__, "error": str(error)},
            )
        output["first_error"] = read_json(first_path)
        if not active.get("evidence_collected_before_close"):
            evidence_before_close()
    write_json(receipt_path, output)
    return output


def run(
    root: Path,
    case_id: str,
    message_index: int,
    *,
    window: str = "none",
    window_tool: str | None = None,
    hit: int = 1,
    label_available: bool | None = None,
    world_event_id: str | None = None,
    resume_label_available: bool | None = None,
    resume_world_event_id: str | None = None,
) -> list[dict[str, Any]]:
    """Launch the public message and, only after witnessed SIGKILL, a fresh resume process."""
    _frozen(root)
    process_path = case_path(root, case_id) / f"message-{message_index}-processes.json"
    if process_path.exists():
        raise ValueError("V13_P5_PROCESS_RESULTS_ALREADY_RECORDED")
    for available, event_id in (
        (label_available, world_event_id),
        (resume_label_available, resume_world_event_id),
    ):
        if (available is None) != (event_id is None):
            raise ValueError("V13_P5_WORLD_EVENT_INVALID")
    outcomes: list[dict[str, Any]] = []
    for phase in ("start", "resume"):
        attempt = f"m{message_index}-{phase}"
        command = [
            sys.executable,
            str(LAB / "tools/run_v13_1_p5.py"),
            "step",
            "--run-root",
            str(root),
            "--case-id",
            case_id,
            "--message-index",
            str(message_index),
            "--phase",
            phase,
            "--attempt-id",
            attempt,
            "--window",
            window if phase == "start" else "none",
            "--hit",
            str(hit),
        ]
        if window_tool is not None:
            command.extend(["--window-tool", window_tool])
        event_id = world_event_id if phase == "start" else resume_world_event_id
        available = label_available if phase == "start" else resume_label_available
        if event_id is not None:
            command.extend(
                [
                    "--world-event-id",
                    event_id,
                    "--label-available",
                    "true" if available else "false",
                ]
            )
        started = time.perf_counter_ns()
        process = subprocess.run(command, capture_output=True, text=True)  # noqa: S603
        process_wall = time.perf_counter_ns() - started
        path = case_path(root, case_id) / f"attempt-{attempt}.json"
        receipt = read_json(path) if path.exists() else None
        killed = (
            process.returncode == -signal.SIGKILL
            and receipt is not None
            and receipt.get("status") == "hard_exit_armed"
        )
        outcomes.append(
            {
                "phase": phase,
                "attempt_id": attempt,
                "returncode": process.returncode,
                "actual_hard_exit": killed,
                "process_wall_ns": process_wall,
                "receipt": receipt,
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
        )
        write_json(
            process_path,
            {"outcomes": outcomes},
        )
        if phase == "start" and not killed:
            break
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "step", "run"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--mode", choices=("ref_only", "field_grounded"), default="field_grounded")
    parser.add_argument("--case-id")
    parser.add_argument("--message-index", type=int)
    parser.add_argument("--phase", choices=("start", "resume"), default="start")
    parser.add_argument("--attempt-id", default="start")
    parser.add_argument("--window", choices=(
        "none", "W1", "W2", "W3", "W2_projection", "W3_projection"
    ), default="none")
    parser.add_argument("--window-tool", choices=(*BUSINESS_NAMES, "manage_memory"))
    parser.add_argument("--hit", type=int, default=1)
    parser.add_argument("--label-available", choices=("true", "false"))
    parser.add_argument("--world-event-id")
    parser.add_argument("--resume-label-available", choices=("true", "false"))
    parser.add_argument("--resume-world-event-id")
    args = parser.parse_args()
    if args.command == "prepare":
        if args.fixture is None or args.config is None:
            parser.error("prepare requires --fixture/--config")
        frozen = prepare(args.fixture, args.config, args.run_root, cast(GroundingMode, args.mode))
        print(json.dumps({"status": "prepared", "fixture_sha256": frozen["fixture_sha256"]}))
        return
    if args.case_id is None or args.message_index is None:
        parser.error("step/run requires --case-id/--message-index")
    controls = {
        "window": args.window,
        "window_tool": args.window_tool,
        "hit": args.hit,
        "label_available": None if args.label_available is None else args.label_available == "true",
        "world_event_id": args.world_event_id,
    }
    if args.command == "step":
        result = step(
            args.run_root,
            args.case_id,
            args.message_index,
            phase=args.phase,
            attempt_id=args.attempt_id,
            **controls,
        )
        print(json.dumps({key: result.get(key) for key in ("status", "attempt_id", "error")}))
        if result["status"] != "completed":
            raise SystemExit(1)
    else:
        outcomes = run(
            args.run_root,
            args.case_id,
            args.message_index,
            **controls,
            resume_label_available=None
            if args.resume_label_available is None
            else args.resume_label_available == "true",
            resume_world_event_id=args.resume_world_event_id,
        )
        final = outcomes[-1]
        print(json.dumps({"processes": len(outcomes), "last_returncode": final["returncode"]}))
        if final["returncode"] != 0:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
