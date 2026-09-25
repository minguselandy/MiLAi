"""Run the pinned first MERIT D1 hard arc through the selected task runtime.

The external package supplies the world, tools, arc and checkers. This file only
adapts its public messages and business results to the Lab's existing Host loop.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import inspect
import json
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from milai_lab.harness.contextual_artifacts import digest, read_json, write_json
from milai_lab.methods.contextual_memory.material_view import VIEW_PROTOCOL
from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.runners.contextual_agent_tasks import (
    BusinessTool,
    BusinessToolResult,
    TaskTurn,
    run_task_session,
    task_runtime,
)

LAB = Path(__file__).resolve().parents[1]
DEFAULT_SELECTION = LAB / "data/manifests/contextual-memory-v7-e0-selection.json"
DEFAULT_CONFIG = LAB / "configs/contextual-memory-v7-off.json"
DEFAULT_FREEZE = LAB / "artifacts/contextual-user-memory/v7-development/freeze.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned_merit(selection: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    root = Path(selection["external_root"]).resolve()
    for relative, expected in selection["source_sha256"].items():
        if sha256(root / relative) != expected:
            raise ValueError(f"MERIT_SOURCE_CHANGED: {relative}")
    sys.path.insert(0, str(root))
    modules = [
        importlib.import_module(f"merit.{name}") for name in ("arcs", "tools", "metrics", "runner")
    ]
    if any(
        module.__file__ is None or not Path(module.__file__).resolve().is_relative_to(root)
        for module in modules
    ):
        raise ValueError("MERIT_IMPORT_OUTSIDE_PINNED_ROOT")
    return modules[0], modules[1], modules[2], modules[3]


def prepared_inputs(
    selection_path: Path,
    config_path: Path,
    freeze_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    Any,
    Any,
    Any,
    Any,
    dict[str, Any],
    dict[str, Any],
]:
    selection = read_json(selection_path)
    config = read_json(config_path)
    freeze = read_json(freeze_path)
    plan = selection["execution_plan"]
    arms = plan["arms"]
    if (
        selection["dataset"] != "MERIT"
        or selection["arc_id"] != "arc0-000"
        or arms not in (["ordinary_v7_off"], ["ordinary_v8_off"], ["ordinary_v9_off"],
                        ["react_notes_v10_off"], ["decision_basis_v10_off"])
    ):
        raise ValueError("MERIT_SELECTION_CHANGED")
    declared_config = plan.get("config")
    if declared_config is not None and not isinstance(declared_config, dict):
        raise ValueError("MERIT_SELECTION_CONFIG_INVALID")
    declared_config = declared_config or {}
    selected_path = selection.get("config_path", declared_config.get("path"))
    selected_sha = selection.get("config_sha256", declared_config.get("sha256"))
    if ((selection.get("config_path") and declared_config.get("path")
         and selection["config_path"] != declared_config["path"])
            or (selection.get("config_sha256") and declared_config.get("sha256")
                and selection["config_sha256"] != declared_config["sha256"])):
        raise ValueError("MERIT_SELECTION_CONFIG_CONFLICT")
    if selected_path is None and selected_sha is None:
        # An old selection can only run with its original v7 configuration.
        if arms != ["ordinary_v7_off"]:
            raise ValueError("MERIT_SELECTION_CONFIG_REQUIRED")
        selected_path = str(DEFAULT_CONFIG.relative_to(LAB))
    elif not isinstance(selected_path, str) or not isinstance(selected_sha, str):
        raise ValueError("MERIT_SELECTION_CONFIG_INVALID")
    expected_path = (LAB / selected_path).resolve()
    try:
        config_key = str(expected_path.relative_to(LAB))
    except ValueError as error:
        raise ValueError("MERIT_SELECTION_CONFIG_OUTSIDE_LAB") from error
    if config_path.resolve() != expected_path or (
        selected_sha is not None and sha256(config_path) != selected_sha
    ):
        raise ValueError("MERIT_CONTROLLER_CONFIG_CHANGED")
    if arms == ["ordinary_v8_off"] and config_key != "configs/contextual-memory-v8-off.json":
        raise ValueError("MERIT_ARM_CONFIG_MISMATCH")
    if arms == ["ordinary_v7_off"] and config_key != "configs/contextual-memory-v7-off.json":
        raise ValueError("MERIT_ARM_CONFIG_MISMATCH")
    if arms == ["ordinary_v9_off"] and (
        not config_key.startswith("artifacts/contextual-user-memory/")
        or config.get("config_version") != "contextual-task-v9"
        or config.get("maintenance_protocol") != "turn-maintenance-v3"
    ):
        raise ValueError("MERIT_ARM_CONFIG_MISMATCH")
    if arms in (["react_notes_v10_off"], ["decision_basis_v10_off"]):
        expected_policy = ("notes" if arms == ["react_notes_v10_off"] else "basis")
        if (
            not config_key.startswith("artifacts/contextual-user-memory/")
            or config.get("config_version") != "contextual-task-v10"
            or config.get("decision_policy") != expected_policy
            or config.get("maintenance_protocol") != "turn-maintenance-v3"
            or config.get("host", {}).get("tool_mode") != "json_action"
            or type(config.get("decision_feedback")) is not bool
            or type(config.get("decision_gap_focus")) is not bool
            or (expected_policy == "notes" and
                (config["decision_feedback"] or config["decision_gap_focus"]))
        ):
            raise ValueError("MERIT_ARM_CONFIG_MISMATCH")
    if (
        config["profile"] != "ordinary"
        or config["state_policy"] != "off"
        or config["source_retention"] != "session"
        or config["host"]["max_calls"] != plan["per_message_model_capacity"]
    ):
        raise ValueError("MERIT_CONTROLLER_CONFIG_CHANGED")
    selected_mapping = selection.get("repair_freeze_sha256",
                                     selection.get("development_freeze_sha256"))
    if not isinstance(selected_mapping, str) or selected_mapping != freeze.get(
        "source_mapping_sha256"
    ):
        raise ValueError("MERIT_SELECTED_FREEZE_MISMATCH")
    if "repair_freeze_sha256" in selection:
        initial_path = selection.get("development_freeze_path")
        if initial_path is None and arms == ["ordinary_v7_off"]:
            initial_path = "artifacts/contextual-user-memory/v7-development/freeze-initial.json"
        if not isinstance(initial_path, str) or read_json(LAB / initial_path).get(
            "source_mapping_sha256"
        ) != selection.get("development_freeze_sha256"):
            raise ValueError("MERIT_REPAIR_LINEAGE_MISMATCH")
        previous_path = selection.get("previous_selection_path")
        if previous_path is None and arms == ["ordinary_v7_off"]:
            previous_path = "data/manifests/contextual-memory-v7-e0-selection.json"
        if selection.get("previous_selection_sha256") and (
            not isinstance(previous_path, str)
            or sha256(LAB / previous_path) != selection["previous_selection_sha256"]
            or read_json(LAB / previous_path).get("development_freeze_sha256")
            != selection["development_freeze_sha256"]
        ):
            raise ValueError("MERIT_REPAIR_LINEAGE_MISMATCH")
    if (
        freeze["status"] != "DEVELOPMENT_COMPLETE_READY_FOR_BENCHMARK_SELECTION"
        or digest(freeze["source_sha256"]) != freeze["source_mapping_sha256"]
        or freeze["config_sha256"].get(config_key) != sha256(config_path)
    ):
        raise ValueError("MERIT_FREEZE_IDENTITY_MISMATCH")
    for relative, expected in freeze["source_sha256"].items():
        if sha256(LAB / relative) != expected:
            raise ValueError(f"MERIT_FROZEN_SOURCE_CHANGED: {relative}")
    for artifact in config["model_identity"]["artifacts"]:
        if sha256(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError("MERIT_MODEL_IDENTITY_CHANGED")

    arcs, tools, metrics, runner = pinned_merit(selection)
    (arc,) = arcs.generate_suite(**selection["generator_arguments"])
    serialized = json.dumps(
        asdict(arc), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    pinned = selection["private_artifacts"]
    if (
        arc.arc_id != selection["arc_id"]
        or arc.seed != selection["arc_seed"]
        or hashlib.sha256(serialized).hexdigest() != pinned["arc_sha256"]
        or serialized != Path(pinned["arc"]).read_bytes()
    ):
        raise ValueError("MERIT_ARC_IDENTITY_MISMATCH")
    world = arc.make_world()
    try:
        initial = world.dump_json().encode()
        if (
            hashlib.sha256(initial).hexdigest() != pinned["initial_world_sha256"]
            or initial != Path(pinned["initial_world"]).read_bytes()
        ):
            raise ValueError("MERIT_INITIAL_WORLD_CHANGED")
        checker_before = []
        for episode, declared in zip(arc.episodes, selection["episodes"], strict=True):
            task = episode.task
            if {
                "index": episode.index,
                "task_id": task.task_id,
                "kind": task.kind,
                "dependent": task.dependent,
                "user_message_count": len(task.user_messages),
                "checker": task.checker,
                "plant_episode": task.plant_episode,
            } != declared:
                raise ValueError("MERIT_EPISODE_SELECTION_CHANGED")
            checker = getattr(metrics, task.checker)
            checker_before.append(bool(checker(world.snapshot(), **task.checker_args)))
    finally:
        world.conn.close()
    if (
        len(arc.episodes) != selection["episode_count"]
        or sum(episode.task.dependent for episode in arc.episodes)
        != selection["dependent_episode_count"]
        or sum(len(episode.task.user_messages) for episode in arc.episodes)
        != selection["user_message_count"]
    ):
        raise ValueError("MERIT_SELECTION_COUNTS_CHANGED")
    native_schemas = {item["function"]["name"]: item for item in tools.TOOL_SCHEMAS}
    if set(native_schemas) != set(tools.TOOL_FUNCS):
        raise ValueError("MERIT_TOOL_REGISTRY_MISMATCH")
    for name, tool in tools.TOOL_FUNCS.items():
        parameters = set(inspect.signature(tool).parameters) - {"world"}
        if set(native_schemas[name]["function"]["parameters"]["required"]) != parameters:
            raise ValueError(f"MERIT_TOOL_SCHEMA_MISMATCH: {name}")
    identity = {
        "selection_sha256": sha256(selection_path),
        "config_sha256": sha256(config_path),
        "selected_config_path": config_key,
        "selected_config_sha256": selected_sha or sha256(config_path),
        "freeze_sha256": sha256(freeze_path),
        "freeze_source_mapping_sha256": freeze["source_mapping_sha256"],
        "selected_development_freeze_sha256": selection["development_freeze_sha256"],
        "selected_execution_freeze_mapping_sha256": selected_mapping,
        "adapter_sha256": sha256(Path(__file__)),
        "external_root": selection["external_root"],
        "external_source_sha256": selection["source_sha256"],
        "arc_sha256": pinned["arc_sha256"],
        "initial_world_sha256": pinned["initial_world_sha256"],
    }
    diagnostic = {
        "arc_id": arc.arc_id,
        "episode_count": len(arc.episodes),
        "dependent_episode_count": sum(ep.task.dependent for ep in arc.episodes),
        "user_message_count": sum(len(ep.task.user_messages) for ep in arc.episodes),
        "native_denominator": selection["scoring_contract"]["native_denominator"],
        "checker_before_initial_world": checker_before,
        "tool_names": sorted(native_schemas),
        "host_capacity_per_message": config["host"]["max_calls"],
        "source_actor_ref": "",
    }
    return selection, config, identity, arc, tools, metrics, runner, diagnostic, native_schemas


def business_tools(
    world: Any, native_tools: Any, calls: list[dict[str, Any]]
) -> dict[str, BusinessTool]:
    """Keep upstream schemas/functions and original JSON tool output intact."""
    result = {}
    for schema in native_tools.TOOL_SCHEMAS:
        name = schema["function"]["name"]
        function = native_tools.TOOL_FUNCS[name]

        def execute(
            arguments: dict[str, Any], call_id: str, *, name: str = name, function: Any = function
        ) -> BusinessToolResult:
            try:
                output = function(world, **arguments)
            except TypeError as error:
                output = json.dumps({"error": f"invalid arguments: {error}"})
            decoded = json.loads(output)
            status: Literal["succeeded", "failed"] = (
                "failed" if isinstance(decoded, dict) and "error" in decoded else "succeeded"
            )
            calls.append(
                {
                    "name": name,
                    "args": copy.deepcopy(arguments),
                    "out": output,
                    "call_id": call_id,
                    "status": status,
                }
            )
            observation = Observation(
                event_id=call_id,
                content=output,
                role="tool",
                artifact=f"merit:{name}",
                session_id=call_id.rsplit(":", 2)[0],
                actor_ref=f"tool:{name}",
            )
            return BusinessToolResult(call_id, status, output, observation)

        result[name] = BusinessTool(schema, execute)
    return result


def visible_memory_bodies(transcript: list[dict[str, Any]]) -> list[str]:
    """Count projected memory bodies delivered before a later Host response."""
    bodies = []
    for index, message in enumerate(transcript):
        if not any(item.get("role") == "assistant" for item in transcript[index + 1 :]):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        primed = (message.get("role") == "user"
                  and content.startswith("Relevant current memory: "))
        if primed:
            content = content.removeprefix("Relevant current memory: ")
        elif message.get("role") == "user" and content.startswith("json_action tool result: "):
            content = content.removeprefix("json_action tool result: ")
        elif message.get("role") != "tool":
            continue
        try:
            outcome = json.loads(content)
        except json.JSONDecodeError:
            continue
        if not isinstance(outcome, dict):
            continue
        if primed:
            projected = outcome if outcome.get("view") == VIEW_PROTOCOL else None
        else:
            projected = outcome.get("result") if "operation_receipt" in outcome else None
        if not isinstance(projected, dict):
            continue
        for section in ("materials", "expanded_materials"):
            for row in projected.get(section, []):
                if not isinstance(row, dict) or row.get("kind") not in {"source", "interpretation"}:
                    continue
                for part in [row, *row.get("excerpts", [])]:
                    if isinstance(part, dict):
                        for key in ("content", "text"):
                            if isinstance(part.get(key), str):
                                bodies.append(part[key])
    return bodies


def maintenance_pending(session: Any, results: list[Any]) -> bool:
    state = getattr(session, "maintenance", {}) if session is not None else {}
    return any(item.status == "maintenance_pending" for item in results) or bool(
        state.get("pending") or state.get("unsettled_operations")
    )


def run_arc(
    output: Path,
    selection: dict[str, Any],
    config: dict[str, Any],
    arc: Any,
    native_tools: Any,
    metrics: Any,
    native_runner: Any,
) -> None:
    world: Any = None
    business_calls: list[dict[str, Any]] = []
    memory: Any = None
    host: Any = None
    runtime: dict[str, Any] | None = None
    session: Any = None
    host_results: list[Any] = []
    episode_index: int | None = None
    public_turn_index: int | None = None
    task_id: str | None = None
    phase = "runtime_start"
    before: dict[str, Any] | None = None
    first_business = 0
    failed = False
    try:
        world = arc.make_world()
        business = business_tools(world, native_tools, business_calls)
        with task_runtime(
            config,
            user_id=f"merit:{arc.arc_id}",
            output=output / "runtime",
            business_tools=business,
        ) as (
            memory,
            host,
            runtime,
        ):
            host.prompt += "\n" + native_runner.SYSTEM_PROMPT.split("{memory_block}", 1)[0].strip()
            rows = []
            for episode in arc.episodes:
                episode_index = episode.index
                task_id = episode.task.task_id
                public_turn_index = None
                phase = "episode_start"
                before = None
                session = None
                host_results = []
                first_business = len(business_calls)
                task = episode.task
                before = world.snapshot()
                checker = getattr(metrics, task.checker)
                pre_satisfied = bool(checker(before, **task.checker_args))
                budget_before = copy.deepcopy(runtime["budget"])
                session_id = f"{arc.arc_id}:episode:{episode.index}"
                for index, message in enumerate(task.user_messages):
                    public_turn_index = index
                    phase = "public_turn"
                    turn = TaskTurn(
                        turn_id=f"message-{index}",
                        question=message,
                        observations=(
                            Observation(
                                event_id=f"{task.task_id}:message:{index}",
                                content=message,
                                role="user",
                                artifact=f"merit:{arc.arc_id}",
                                session_id=session_id,
                                actor_ref="",
                            ),
                        ),
                    )
                    session, result = run_task_session(
                        [turn],
                        memory=memory,
                        host=host,
                        session_id=session_id,
                        session=session,
                        close=False,
                    )
                    host_results.extend(result)
                    if not result or result[-1].status != "complete":
                        phase = "public_turn_incomplete"
                        status = result[-1].status if result else "missing_host_result"
                        raise RuntimeError(f"PUBLIC_TURN_INCOMPLETE: {status}")
                assert session is not None
                phase = "episode_close"
                session.close()
                after = world.snapshot()
                native_success = not pre_satisfied and bool(checker(after, **task.checker_args))
                episode_calls = business_calls[first_business:]
                golds = task.golds()
                bodies = visible_memory_bodies(host_results[-1].transcript)
                memory_had_fact = bool(
                    task.dependent and golds and all(gold in "\n".join(bodies) for gold in golds)
                )
                argument_value_match = bool(golds and metrics.memory_utilized(episode_calls, golds))
                row = {
                    "episode_index": episode.index,
                    "task_id": task.task_id,
                    "kind": task.kind,
                    "dependent": task.dependent,
                    "public_message_count": len(task.user_messages),
                    "before_world": before,
                    "after_world": after,
                    "host_results": [
                        {key: value for key, value in asdict(result).items() if key != "transcript"}
                        for result in host_results
                    ],
                    "transcript": host_results[-1].transcript,
                    "maintenance_pending": maintenance_pending(session, host_results),
                    "memory_checkpoint": memory.checkpoint(include_task=False),
                    "business_calls": copy.deepcopy(episode_calls),
                    "native_score": {
                        "pre_satisfied": pre_satisfied,
                        "checker_after": bool(checker(after, **task.checker_args)),
                        "success": native_success,
                        "memory_had_fact": memory_had_fact,
                        "argument_value_match": argument_value_match,
                        "memory_utilized": bool(memory_had_fact and argument_value_match),
                    },
                    "budget_before": budget_before,
                    "budget_after": copy.deepcopy(runtime["budget"]),
                    "trace_path": "runtime/trace.jsonl",
                }
                phase = "episode_write"
                write_json(output / "episodes" / f"episode-{episode.index}.json", row)
                rows.append(
                    {
                        "episode_index": episode.index,
                        "task_id": task.task_id,
                        "dependent": task.dependent,
                        "success": native_success,
                        "memory_utilized": row["native_score"]["memory_utilized"],
                        "host_statuses": [item.status for item in host_results],
                    }
                )
            phase = "result_write"
            write_json(
                output / "result.json",
                {
                    "arc_id": arc.arc_id,
                    "native_denominator": selection["episode_count"],
                    "dependent_denominator": selection["dependent_episode_count"],
                    "native_successes": sum(row["success"] for row in rows),
                    "dependent_successes": sum(row["success"] for row in rows if row["dependent"]),
                    "episodes": rows,
                    "final_budget": copy.deepcopy(runtime["budget"]),
                    "trace_path": "runtime/trace.jsonl",
                },
            )
    except Exception as error:
        failed = True
        def capture(label: str, operation: Any) -> Any:
            try:
                return operation()
            except Exception as capture_error:
                problem = f"{label}: {type(capture_error).__name__}: {capture_error}"
                return {"capture_error": problem}

        live_session = session or getattr(host, "last_session", None)
        diagnostic: dict[str, Any] = {
            "status": "interrupted",
            "native_score": {"status": "unscored"},
            "arc_id": arc.arc_id,
            "episode_index": episode_index,
            "task_id": task_id,
            "public_turn_index": public_turn_index,
            "phase": phase,
            "before_world": copy.deepcopy(before),
            "after_world": capture("world", world.snapshot) if world is not None else None,
            "memory_checkpoint": (
                capture("memory", lambda: memory.checkpoint(include_task=True))
                if memory is not None else None
            ),
            "session": capture(
                "session",
                lambda: {
                    "session_id": getattr(live_session, "session_id", None),
                    "turn_id": getattr(live_session, "turn_id", None),
                    "transcript": copy.deepcopy(getattr(live_session, "transcript", [])),
                    "maintenance": copy.deepcopy(getattr(live_session, "maintenance", {})),
                } if live_session is not None else None,
            ),
            "host_results": capture(
                "host_results",
                lambda: [
                    {key: value for key, value in asdict(result).items() if key != "transcript"}
                    for result in host_results
                ],
            ),
            "maintenance_pending": maintenance_pending(live_session, host_results),
            "business_calls": copy.deepcopy(business_calls),
            "episode_business_calls": copy.deepcopy(business_calls[first_business:]),
            "runtime_budget": copy.deepcopy(runtime.get("budget")) if runtime else None,
            "trace_path": "runtime/trace.jsonl",
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": "".join(traceback.format_exception(error)),
            },
        }
        try:
            write_json(output / "interruption.json", diagnostic)
        except Exception as artifact_error:
            error.add_note(f"Interruption artifact could not be written: {artifact_error}")
        raise
    finally:
        if world is not None:
            try:
                world.conn.close()
            except Exception:
                if not failed:
                    raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    (selection, config, identity, arc, native_tools, metrics, native_runner, diagnostic, _) = (
        prepared_inputs(args.selection, args.config, args.freeze)
    )
    manifest = {
        "kind": "CONTEXTUAL_MERIT_E1",
        "identity": identity,
        "config": config,
        "selection": selection,
    }
    if output.exists():
        existing = {item.name for item in output.iterdir()}
        if existing - {"manifest.json", "prepare.json"}:
            raise ValueError("MERIT_OUTPUT_ALREADY_HAS_RUN_DATA")
        if "manifest.json" in existing and read_json(output / "manifest.json") != manifest:
            raise ValueError("MERIT_OUTPUT_IDENTITY_MISMATCH")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "manifest.json", manifest)
    write_json(output / "prepare.json", diagnostic)
    if args.prepare_only:
        print(json.dumps({"status": "PREPARED_ZERO_MODEL", **diagnostic}, ensure_ascii=False))
        return
    write_json(output / "started.json", {"identity": identity, "status": "RUNNING"})
    run_arc(output, selection, config, arc, native_tools, metrics, native_runner)
    print(json.dumps(read_json(output / "result.json"), ensure_ascii=False))


if __name__ == "__main__":
    main()
