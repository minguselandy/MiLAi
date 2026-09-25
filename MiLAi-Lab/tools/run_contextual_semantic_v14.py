"""Run frozen, independent semantic diagnostics through the ordinary task runtime.

Inputs contain public messages and trusted local tool fixtures. Expected future use,
semantic labels and evaluation rubrics live in separate files this runner never opens.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.contextual_artifacts import digest, read_json, write_json
from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.runners.contextual_agent_tasks import (
    BusinessTool,
    BusinessToolResult,
    TaskTurn,
    run_task_session,
    task_runtime,
)

LAB = Path(__file__).resolve().parents[1]


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixtures(
    definitions: list[dict[str, Any]], calls: list[dict[str, Any]],
) -> dict[str, BusinessTool]:
    """Fixed trusted responses represent a local diagnostic world, not a scorer."""
    tools = {}
    for definition in definitions:
        schema = definition["schema"]
        name = schema["function"]["name"]

        def execute(arguments: dict[str, Any], call_id: str, *,
                    definition: dict[str, Any] = definition,
                    name: str = name) -> BusinessToolResult:
            status = definition["result"]["status"]
            output = copy.deepcopy(definition["result"]["output"])
            calls.append({"call_id": call_id, "name": name,
                          "arguments": copy.deepcopy(arguments), "status": status,
                          "output": copy.deepcopy(output)})
            return BusinessToolResult(call_id, status, output)

        tools[name] = BusinessTool(schema, execute)
    return tools


def verify(inputs: Path, config: Path, freeze: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = read_json(freeze)
    if file_sha(inputs) != frozen["inputs_file_sha256"]:
        raise ValueError("SEMANTIC_INPUT_IDENTITY_CHANGED")
    settings = read_json(config)
    if digest(settings) != frozen["config_digest"]:
        raise ValueError("SEMANTIC_CONFIG_IDENTITY_CHANGED")
    for name, expected in frozen["source_sha256"].items():
        if file_sha(LAB / name) != expected:
            raise ValueError(f"SEMANTIC_SOURCE_IDENTITY_CHANGED: {name}")
    if file_sha(Path(__file__)) != frozen["runner_sha256"]:
        raise ValueError("SEMANTIC_RUNNER_IDENTITY_CHANGED")
    if settings["config_version"] != "contextual-task-v14":
        raise ValueError("SEMANTIC_DIAGNOSTIC_REQUIRES_V14")
    return read_json(inputs), settings


def run_case(case: dict[str, Any], config: dict[str, Any], output: Path) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    tools = fixtures(case.get("tools", []), calls)
    result: dict[str, Any] = {"id": case["id"], "status": "RUNNING", "sessions": []}
    output.mkdir(parents=True)
    memory = None
    try:
        for declared in case["sessions"]:
            before = len(calls)
            with task_runtime(config, user_id=f"semantic:{case['id']}",
                              output=output / "runtime", business_tools=tools) as (memory, host, _):
                # No future-use labels, expected answers, forced persistence or scoring metadata.
                turns = [TaskTurn(
                    turn["id"], turn["text"], (Observation(
                        event_id=f"{case['id']}:{declared['id']}:{turn['id']}",
                        content=turn["text"], role="user",
                        artifact="independent-semantic-diagnostic",
                        session_id=declared["id"], actor_ref="current_user",
                    ),),
                ) for turn in declared["turns"]]
                session, host_results = run_task_session(
                    turns, memory=memory, host=host, session_id=declared["id"], close=True,
                )
                row = {"session_id": declared["id"],
                       "host_results": [asdict(value) for value in host_results],
                       "business_calls": copy.deepcopy(calls[before:]),
                       "session_closed": session.closed,
                       "memory_checkpoint": memory.checkpoint(include_task=not session.closed)}
                result["sessions"].append(row)
                write_json(output / f"session-{len(result['sessions'])}.json", row)
                if not host_results or host_results[-1].status != "complete":
                    raise RuntimeError("SEMANTIC_HOST_TURN_INCOMPLETE")
        result["status"] = "TERMINAL"
    except Exception as error:
        result.update(status="INTERRUPTED", error=type(error).__name__, detail=str(error))
        write_json(output / "interruption.json", {
            "error": type(error).__name__, "detail": str(error),
            "traceback": traceback.format_exc(), "business_calls": calls,
            "memory_checkpoint": memory.checkpoint() if memory is not None else None,
        })
    result["business_calls"] = calls
    result["budget"] = read_json(Path(config["budget_path"]))
    write_json(output / "result.json", result)
    return {"id": case["id"], "status": result["status"],
            "sessions": len(result["sessions"]), "business_calls": len(calls)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    specification, config = verify(args.inputs, args.config, args.freeze)
    available = {case["id"] for case in specification["cases"]}
    if set(args.case) - available:
        raise ValueError("SEMANTIC_CASE_NOT_IN_FROZEN_INPUTS")
    cases = [case for case in specification["cases"] if not args.case or case["id"] in args.case]
    if args.prepare_only:
        print(json.dumps({"status": "PREPARED_ZERO_MODEL", "cases": [c["id"] for c in cases]}))
        return
    if args.output.exists():
        raise ValueError("SEMANTIC_OUTPUT_EXISTS")
    args.output.mkdir(parents=True)
    manifest: dict[str, Any] = {
                "kind": "INDEPENDENT_V14_SEMANTIC_DIAGNOSTIC", "status": "RUNNING",
                "inputs_sha256": file_sha(args.inputs), "freeze_sha256": file_sha(args.freeze),
                "runner_sha256": file_sha(Path(__file__)), "cases": [],
                "rubric_read_by_runner": False, "native_benchmark_score": False}
    write_json(args.output / "manifest.json", manifest)
    try:
        for case in cases:
            row = run_case(case, config, args.output / case["id"])
            manifest["cases"].append(row)
            write_json(args.output / "manifest.json", manifest)
            print(json.dumps(row), flush=True)
        manifest["status"] = ("TERMINAL" if all(
            row["status"] == "TERMINAL" for row in manifest["cases"]
        ) else "TERMINAL_WITH_INTERRUPTED_CASES")
    finally:
        verify(args.inputs, args.config, args.freeze)
        manifest["source_config_inputs_unchanged"] = True
        write_json(args.output / "manifest.json", manifest)


if __name__ == "__main__":
    main()
