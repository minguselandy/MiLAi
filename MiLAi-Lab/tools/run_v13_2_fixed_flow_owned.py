"""Root-only controlled actual-source formation/delivery; never a free Host sample."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.refs import verified_reservation_ref
from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.read_protocol import profiles as read_profiles
from milai_lab.contracts.scope import FoundationScope
from milai_lab.contracts.tool_schema_communication import profile as communication_profile
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunLimits, Trace, entry_budget, http_budget_scope
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig, ownership_client_configs
from milai_lab.runners.v13_1_d0 import (
    _frozen,
    _make_recipe,
    _observe_captured,
    _receipt_contract,
    _service_options,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--stream", type=Path, required=True)
    parser.add_argument("--stream-index", type=int, required=True)
    parser.add_argument("--boundary", type=int, required=True)
    args = parser.parse_args()
    frozen = _frozen(args.run_root)
    settings = frozen["config"]
    with http_budget_scope(
        settings,
        RunLimits(**frozen["budget_limits"]),
        client_configs=ownership_client_configs(settings),
    ):
        _execute_boundary(args, frozen)


def _execute_boundary(args: argparse.Namespace, frozen: dict[str, Any]) -> None:
    """Execute one first controlled boundary inside the caller's owner lifetime."""
    driver_freeze = read_json(args.run_root / "controlled-flow-freeze.json")
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == driver_freeze["driver_sha256"]
    assert hashlib.sha256(args.stream.read_bytes()).hexdigest() == driver_freeze["stream_sha256"]
    if driver_freeze.get("http_ownership_profile", "legacy") != frozen.get(
        "http_ownership_profile", "legacy"
    ) or driver_freeze.get("http_ownership_binding", {}) != frozen.get(
        "http_ownership_binding", {}
    ):
        raise ValueError("CONTROLLED_FLOW_HTTP_OWNER_FREEZE_CHANGED")
    stream = read_json(args.stream)["streams"][args.stream_index]
    boundary = stream["boundaries"][args.boundary]
    settings = frozen["config"]
    case_root = args.run_root / hashlib.sha256(stream["case_id"].encode()).hexdigest()[:16]
    case_root.mkdir(parents=True, exist_ok=True)
    receipt_path = case_root / f"controlled-boundary-{args.boundary}.json"
    if receipt_path.exists():
        raise ValueError("CONTROLLED_FLOW_ALREADY_ATTEMPTED")
    if args.boundary and not (case_root / f"controlled-boundary-{args.boundary - 1}.json").exists():
        raise ValueError("CONTROLLED_FLOW_PRIOR_BOUNDARY_REQUIRED")
    user = next(event for event in boundary["events"] if event["role"] == "user")
    scope = FoundationScope(frozen["run_id"], frozen["mode"], stream["owner"], user["session_id"])
    config = cast(RunnableConfig, scope.config())
    config["configurable"].update(v13_session=user["session_id"], v13_turn_id=user["event_key"])
    trace = Trace(
        case_root / f"controlled-boundary-{args.boundary}.jsonl", "v13_2_actual_fixed_flow"
    )
    budget = entry_budget(RunLimits(**frozen["budget_limits"]), Path(settings["budget_path"]))
    output = {
        "kind": "V13_2_CONTROLLED_FORMATION_DELIVERY",
        "free_host_sample": False,
        "case_id": stream["case_id"],
        "boundary": args.boundary,
        "process_id": os.getpid(),
        "driver_sha256": driver_freeze["driver_sha256"],
        "status": "attempted",
        "phase": "actual_public_events_boundary",
        "actual_host_final": None,
        "http_ownership_profile": frozen.get("http_ownership_profile", "legacy"),
        "http_ownership_binding": frozen.get("http_ownership_binding", {}),
    }
    write_json(receipt_path, output)  # retain attempted denominator before model admission
    try:
        with ExitStack() as stack:
            store = stack.enter_context(
                SqliteStore.from_conn_string(str(case_root / "memory.sqlite"))
            )
            world_path = Path(stream["world_path_for_trusted_adapter_only"])
            assert world_path.is_file()
            world = ApplicationWorld(world_path, False)
            stack.callback(world.close)
            service = MemoryService(
                store,
                ("langmem", scope.run_id, scope.arm_id, scope.user_id),
                scope.user_id,
                case_root / "memory.lock",
                mode=frozen["mode"],
                receipt_contract=_receipt_contract(settings),
                mutation_contract="event_bound_v1",
                **_service_options(settings),
                observer=trace,
            )
            refs = []
            actual_user_ref = None
            for event in boundary["events"]:
                assert (
                    hashlib.sha256(event["content"].encode()).hexdigest() == event["content_sha256"]
                )
                if event["role"] == "user":
                    capture = service.capture_user(
                        event["session_id"], event["event_key"], event["content"]
                    )
                    if event["event_key"] == user["event_key"]:
                        actual_user_ref = capture["source_ref"]
                else:
                    source_ref = service.event_id(event["session_id"], event["event_key"], "tool")
                    object_ref = verified_reservation_ref(
                        world,
                        scope.user_id,
                        source_ref,
                        event["origin"],
                        event["content"],
                        observer=trace,
                    )
                    capture = service.capture_tool(
                        event["session_id"],
                        event["event_key"],
                        event["origin"],
                        event["content"],
                        object_ref,
                    )
                    _observe_captured(service, capture["source_ref"], settings, trace)
                refs.append(capture["source_ref"])
                trace(
                    {
                        "event": "v13_actual_fixed_flow_source",
                        "receipt": capture,
                        "role": event["role"],
                    }
                )
            service.bind_source_boundary(user["session_id"], user["event_key"], refs)
            if (
                service.support_contract == "direct_support_v1"
                or service.memory_read_protocol != "legacy"
            ):
                if actual_user_ref is None:
                    raise ValueError("CONTROLLED_FLOW_ACTUAL_USER_SOURCE_REQUIRED")
                service.bind_public_turn(
                    user["session_id"],
                    user["event_key"],
                    actual_user_ref,
                    config_sha256=frozen["config_sha256"],
                    phase="start",
                )
                config["configurable"]["v13_support_config_sha256"] = frozen["config_sha256"]
            client = stack.enter_context(
                VLLMClient(
                    VLLMConfig(**settings["host"]),
                    emit=trace,
                    budget=budget,
                    capacity=HostCapacity(settings["capacity"]),
                )
            )
            model = LangMemRecipeChatModel(
                client=client,
                capacity_path=case_root / "capacity.json",
                max_calls_per_message=settings["max_calls_per_message"],
                tool_save_communication=cast(
                    Any, read_profiles(settings)["tool_save_communication"]
                ),
                tool_schema_communication=communication_profile(
                    settings.get("tool_schema_communication", "legacy")
                ),
            )
            model.begin_public_message(user["event_key"])
            recipe = _make_recipe(service, settings, model, budget, trace, stack)
            assert recipe is not None
            trace({"event": "benchmark_phase", "phase": "controlled_delivery"})
            if settings["memory_prefetch"] == "enabled":
                output["delivery"] = recipe.prepare_context(
                    user["content"],
                    owner=scope.user_id,
                    session=user["session_id"],
                    turn_id=user["event_key"],
                )
            else:
                tools = {
                    t.name: t
                    for t in create_service_tools(service, recall_provider=recipe.recall_tool)
                }
                call = {
                    "name": "recall_context",
                    "args": {},
                    "id": "controlled-ordinary-read",
                    "type": "tool_call",
                }
                output["delivery"] = json.loads(
                    tools["recall_context"].invoke(call, config=config).content
                )
            # Both ordinary entrances are deliberately activated here to check SDK
            # delivery. Only the subsequent free Host cohort tests the choice to read.
            # Formation receives the same available prior candidates at this boundary.
            # Boundary0 never sees boundary1 request or receipt; no fake Host final.
            if settings["memory_formation_policy"] == "none":
                trace({"event": "benchmark_phase", "phase": "semantic_boundary"})
                output["formation"] = recipe.maintain(
                    model,
                    session=user["session_id"],
                    turn_id=user["event_key"],
                    source_refs=refs,
                    config=config,
                    instruction=settings["writer_system_prompt"],
                    repairs=0,
                )
            else:
                output["formation"] = {
                    "status": "deterministic_observation_only",
                    "generation_calls": 0,
                }
            trace({"event": "benchmark_phase", "phase": "controlled_delivery"})
            output["delivery_after_formation"] = recipe.prepare_context(
                user["content"],
                owner=scope.user_id,
                session=user["session_id"],
                turn_id=user["event_key"],
            )
            output.update(
                status="completed",
                records=service.records(),
                observations=service.observations(),
                sources=service.sources(),
                usage=trace.usage,
                budget=budget.state,
            )
    except Exception as error:
        output.update(
            status="interrupted",
            error_type=type(error).__name__,
            error=str(error),
            budget=budget.state,
            usage=trace.usage,
        )
    write_json(receipt_path, output)
    print(
        json.dumps(
            {key: output[key] for key in ("case_id", "boundary", "status", "free_host_sample")}
        )
    )
    if output["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
