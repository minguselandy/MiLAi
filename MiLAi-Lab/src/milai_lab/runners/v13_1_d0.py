"""Frozen public D0 inputs, one real Host invocation process per public message.

There is no scorer/rubric input here. Preparation does no HTTP. The caller must
explicitly invoke step/run to spend the existing continuous generation budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.store.sqlite import SqliteStore
from langgraph.types import Command

from milai_lab.application.journal import BusinessActionJournal
from milai_lab.application.refs import verified_reservation_ref
from milai_lab.application.tools import BUSINESS_NAMES, BUSINESS_SCHEMAS, _business_tools
from milai_lab.application.world import ApplicationWorld
from milai_lab.baselines.langmem_agent import SYSTEM_PROMPT, build_agent
from milai_lab.contracts.memory import GroundingMode
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, Trace
from milai_lab.memory.mcp import MemoryMCP
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

LAB = Path(__file__).resolve().parents[3]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources() -> dict[str, str]:
    # This run-level freeze deliberately covers the whole Lab Python source tree,
    # including imported observers/hooks that are dormant in this opt-in recipe.
    # Hash bytes only: never import scorer code or open its rubric/data inputs.
    paths = [*sorted((LAB / "src/milai_lab").rglob("*.py")), LAB / "tools/run_v13_1_d0.py"]
    return {path.relative_to(LAB).as_posix(): _sha(path) for path in paths}


def _system_prompt(config: dict[str, Any]) -> str:
    prompt = config.get("system_prompt", SYSTEM_PROMPT)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("V13_D0_SYSTEM_PROMPT_INVALID")
    return prompt


def _receipt_contract(config: dict[str, Any]) -> str:
    return MemoryService.validate_receipt_contract(
        config.get("memory_receipt_contract", "optional")
    )


def _catalog(
    root: Path, mode: GroundingMode, *, receipt_contract: str = "optional"
) -> list[dict[str, Any]]:
    with SqliteStore.from_conn_string(":memory:") as store:
        service = MemoryService(
            store,
            ("langmem", "schema", mode, "schema-owner"),
            "schema-owner",
            root / "memory.lock",
            mode=mode,
            receipt_contract=receipt_contract,
        )
        return [
            *[convert_to_openai_tool(tool) for tool in create_service_tools(service)],
            *BUSINESS_SCHEMAS,
        ]


def prepare(
    fixture_path: Path,
    config_path: Path,
    root: Path,
    mode: GroundingMode = "field_grounded",
    transport: str = "direct",
) -> dict[str, Any]:
    fixture, config = read_json(fixture_path), read_json(config_path)
    if fixture.get("kind") != "MILAI_V13_1_D0_NORMAL_USE" or not fixture.get("cases"):
        raise ValueError("V13_D0_PUBLIC_FIXTURE_REQUIRED")
    if mode not in {"ref_only", "field_grounded"} or transport not in {"direct", "mcp_http"}:
        raise ValueError("V13_D0_MODE_OR_TRANSPORT_INVALID")
    seen = set()
    for case in fixture["cases"]:
        if not case["case_id"] or case["case_id"] in seen or not case["owner"]:
            raise ValueError("V13_D0_CASE_IDENTITY_INVALID")
        seen.add(case["case_id"])
        for message in case["messages"]:
            if not all(
                isinstance(message.get(key), str) and message[key]
                for key in ("message_id", "session_id", "content")
            ):
                raise ValueError("V13_D0_PUBLIC_MESSAGE_INVALID")
    # Instantiate only the config DTO here, never a client or model service.
    VLLMConfig(**config["host"])
    system_prompt = _system_prompt(config)
    receipt_contract = _receipt_contract(config)
    if "capacity" not in config or "budget_path" not in config:
        raise ValueError("V13_D0_CAPACITY_AND_CONTINUOUS_BUDGET_REQUIRED")
    budget_path = Path(config["budget_path"])
    if not budget_path.is_file():
        raise ValueError("V13_D0_EXISTING_CONTINUOUS_BUDGET_REQUIRED")
    budget_limits = read_json(budget_path)["limits"]
    catalog = _catalog(root, mode, receipt_contract=receipt_contract)
    frozen = {
        "kind": "MILAI_V13_1_D0_RUNTIME_FREEZE",
        "fixture": fixture,
        "fixture_sha256": _sha(fixture_path),
        "fixture_path": str(fixture_path.resolve()),
        "config": config,
        "config_sha256": _sha(config_path),
        "config_path": str(config_path.resolve()),
        "budget_limits": budget_limits,
        "mode": mode,
        "memory_receipt_contract": receipt_contract,
        "transport": transport,
        "run_id": root.resolve().name,
        "source_sha256": _sources(),
        "prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
        "tool_catalog": catalog,
        "tool_catalog_sha256": hashlib.sha256(
            json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "backend": "public_sdk_sqlite",
        "memory_retrieval": "raw_keyword",
        "semantic_evidence": False,
    }
    root.mkdir(parents=True, exist_ok=True)
    target = root / "input-freeze.json"
    if target.exists() and read_json(target) != frozen:
        raise ValueError("V13_D0_INPUT_FREEZE_CHANGED")
    write_json(target, frozen)
    return frozen


def _frozen(root: Path) -> dict[str, Any]:
    frozen = read_json(root / "input-freeze.json")
    if frozen["source_sha256"] != _sources():
        raise ValueError("V13_D0_SOURCE_CHANGED_AFTER_FREEZE")
    if frozen["fixture_sha256"] != _sha(Path(frozen["fixture_path"])) or (
        frozen["config_sha256"] != _sha(Path(frozen["config_path"]))
    ):
        raise ValueError("V13_D0_INPUT_CHANGED_AFTER_FREEZE")
    return cast(dict[str, Any], frozen)


def _execute_step(root: Path, case_id: str, message_index: int) -> dict[str, Any]:
    frozen = _frozen(root)
    case = next(row for row in frozen["fixture"]["cases"] if row["case_id"] == case_id)
    if not 0 <= message_index < len(case["messages"]):
        raise ValueError("V13_D0_MESSAGE_INDEX_INVALID")
    case_root = root / hashlib.sha256(case_id.encode()).hexdigest()[:16]
    case_root.mkdir(parents=True, exist_ok=True)
    receipt_path = case_root / f"message-{message_index}.json"
    if receipt_path.exists():
        return cast(dict[str, Any], read_json(receipt_path))
    if message_index and not (case_root / f"message-{message_index - 1}.json").exists():
        raise ValueError("V13_D0_PRIOR_MESSAGE_REQUIRED")
    public = case["messages"][message_index]
    settings = frozen["config"]
    scope = FoundationScope(frozen["run_id"], frozen["mode"], case["owner"], public["session_id"])
    config = scope.config()
    config["configurable"]["v13_session"] = public["session_id"]
    namespace = ("langmem", scope.run_id, scope.arm_id, scope.user_id)
    trace = Trace(case_root / f"message-{message_index}.jsonl", "v13_1_d0")
    trace(
        {
            "event": "v13_public_input",
            "case_id": case_id,
            "owner": scope.user_id,
            "session": public["session_id"],
            "message_id": public["message_id"],
            "content_sha256": hashlib.sha256(public["content"].encode()).hexdigest(),
            "process_id": os.getpid(),
            "source_sha256": frozen["source_sha256"],
            "fixture_sha256": frozen["fixture_sha256"],
            "transport": frozen["transport"],
        }
    )
    budget = RunBudget(RunLimits(**frozen["budget_limits"]), Path(settings["budget_path"]))
    output: dict[str, Any] = {
        "case_id": case_id,
        "message_id": public["message_id"],
        "message_index": message_index,
        "process_id": os.getpid(),
        "owner": scope.user_id,
        "session": public["session_id"],
    }
    with ExitStack() as stack:
        store = stack.enter_context(SqliteStore.from_conn_string(str(case_root / "memory.sqlite")))
        saver = stack.enter_context(
            SqliteSaver.from_conn_string(str(case_root / "checkpoints.sqlite"))
        )
        world = ApplicationWorld(
            case_root / "world.sqlite", case.get("initial_world", {}).get("label_available", True)
        )
        stack.callback(world.close)
        service = MemoryService(
            store,
            namespace,
            scope.user_id,
            case_root / "memory.lock",
            mode=frozen["mode"],
            receipt_contract=_receipt_contract(settings),
            observer=trace,
        )
        source_receipt = service.capture_user(
            public["session_id"], public["message_id"], public["content"]
        )
        write_json(case_root / f"message-{message_index}-capture.json", source_receipt)
        trace({"event": "v13_source_capture", "receipt": source_receipt})
        journal = BusinessActionJournal(case_root / "business-journal.json", BUSINESS_NAMES)

        def business_wrapper(request: ToolCallRequest, execute: Any) -> ToolMessage | Command[Any]:
            response = journal(request, execute)
            if request.tool_call["name"] not in BUSINESS_NAMES or not isinstance(
                response, ToolMessage
            ):
                return response
            generating = request.state["messages"][-1]
            identity = str(generating.id) + ":" + str(request.tool_call["id"])
            source_ref = service.event_id(public["session_id"], identity, "tool")
            # response was produced by the actual owner-bound tool or redelivered
            # from its durable journal; no Host body is interpreted as a receipt.
            body = str(response.content)
            ref = verified_reservation_ref(
                world, scope.user_id, source_ref, request.tool_call["name"], body, observer=trace
            )
            capture = service.capture_tool(
                public["session_id"], identity, request.tool_call["name"], body, ref
            )
            trace(
                {
                    "event": "v13_business_receipt",
                    "call": request.tool_call,
                    "original_receipt": response.model_dump(mode="json"),
                    "capture": capture,
                }
            )
            # Deliver binding alongside, while the stored original tool receipt
            # and old public business schema stay unchanged.
            return response.model_copy(
                update={
                    "content": json.dumps(
                        {
                            "receipt": json.loads(body),
                            "source_ref": source_ref,
                            "object_ref": ref.id if ref else None,
                            "observation_only": True,
                        },
                        ensure_ascii=False,
                    )
                }
            )

        tools = create_service_tools(service)
        if frozen["transport"] == "mcp_http":
            peer = stack.enter_context(
                MemoryMCP(
                    store, scope.run_id, scope.arm_id, scope.user_id, service=service, emit=trace
                )
            )
            tools = peer.tools
        try:
            host_config = VLLMConfig(**settings["host"])
            with VLLMClient(
                host_config, emit=trace, budget=budget, capacity=HostCapacity(settings["capacity"])
            ) as client:
                model = LangMemRecipeChatModel(
                    client=client,
                    capacity_path=case_root / "host-capacity.json",
                    max_calls_per_message=settings.get("max_calls_per_message", 12),
                )
                # Explicit reuse of the existing Agent loop and provider protocol.
                agent = build_agent(
                    model,
                    store,
                    saver,
                    _business_tools(world, scope.user_id),
                    business_call_wrapper=business_wrapper,
                    memory_tools=tools,
                    system_prompt=_system_prompt(settings),
                )
                key = public["message_id"]
                model.begin_public_message(key)
                snapshot = agent.get_state(config)
                prior = snapshot.values.get("messages", []) if snapshot.values else []
                already_added = any(
                    isinstance(row, HumanMessage) and row.id == key for row in prior
                )
                if already_added and not snapshot.next:
                    messages = prior
                else:
                    result = agent.invoke(
                        None
                        if already_added
                        else {"messages": [HumanMessage(content=public["content"], id=key)]},
                        config=config,
                    )
                    messages = result["messages"]
                output.update(
                    status="completed",
                    messages=[row.model_dump(mode="json") for row in messages],
                    final_answer=next(
                        (
                            row.content
                            for row in reversed(messages)
                            if isinstance(row, AIMessage) and not row.tool_calls
                        ),
                        None,
                    ),
                )
        except Exception as error:
            output.update(status="interrupted", error_type=type(error).__name__, error=str(error))
        output.update(
            records=service.records(),
            sources=service.sources(),
            world=world.snapshot(),
            business_calls=journal.calls_for_thread(config["configurable"]["thread_id"]),
            usage=trace.usage,
            budget=budget.state,
        )
    write_json(receipt_path, output)
    return output


def step(root: Path, case_id: str, message_index: int) -> dict[str, Any]:
    """Keep the first terminal failure even when setup fails before Host admission."""
    case_root = root / hashlib.sha256(case_id.encode()).hexdigest()[:16]
    receipt_path = case_root / f"message-{message_index}.json"
    if receipt_path.exists():
        _frozen(root)
        return cast(dict[str, Any], read_json(receipt_path))
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        output = _execute_step(root, case_id, message_index)
    except Exception as error:
        capture_path = case_root / f"message-{message_index}-capture.json"
        output = {
            "case_id": case_id,
            "message_id": None,
            "message_index": message_index,
            "process_id": os.getpid(),
            "status": "interrupted",
            "error_type": type(error).__name__,
            "error": str(error),
            "failure_stage": "setup_or_capture_or_finalization",
            "capture_receipt": read_json(capture_path) if capture_path.exists() else None,
            "capture_status": "raw_captured" if capture_path.exists() else "unconfirmed",
        }
        case_root.mkdir(parents=True, exist_ok=True)
        if receipt_path.exists():
            return cast(dict[str, Any], read_json(receipt_path))
    output["cost_scope"] = "generation full via existing client; IO partial"
    output["execution_wall_ns"] = time.perf_counter_ns() - wall
    output["execution_cpu_ns"] = time.process_time_ns() - cpu
    output["persistent_resource_bytes"] = {
        path.name: path.stat().st_size for path in case_root.glob("*.sqlite*")
    }
    output["logical_source_snapshot_bytes"] = len(
        json.dumps(output.get("sources", []), ensure_ascii=False).encode()
    )
    output["logical_record_snapshot_bytes"] = len(
        json.dumps(output.get("records", []), ensure_ascii=False).encode()
    )
    output["cost_measurement_note"] = (
        "step execution excluding interpreter/import and final metrics write; "
        "snapshot byte counts are not total Store IO; program ref lookups are in trace"
    )
    write_json(receipt_path, output)
    return output


def run(root: Path, case_ids: list[str] | None = None) -> list[dict[str, Any]]:
    frozen = _frozen(root)
    results = []
    for case in frozen["fixture"]["cases"]:
        if case_ids is not None and case["case_id"] not in case_ids:
            continue
        blocked = False
        for index in range(len(case["messages"])):
            if blocked:
                results.append(
                    {
                        "case_id": case["case_id"],
                        "message_index": index,
                        "status": "not_run",
                        "reason": "prior_public_message_interrupted",
                        "returncode": None,
                    }
                )
                continue
            process = subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    str(LAB / "tools/run_v13_1_d0.py"),
                    "step",
                    "--run-root",
                    str(root),
                    "--case-id",
                    case["case_id"],
                    "--message-index",
                    str(index),
                ],
                capture_output=True,
                text=True,
            )
            results.append(
                {
                    "case_id": case["case_id"],
                    "message_index": index,
                    "status": "executed" if process.returncode == 0 else "interrupted",
                    "returncode": process.returncode,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                }
            )
            if process.returncode:
                blocked = True
    write_json(root / "process-results.json", {"results": results})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "step", "run"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--mode", choices=("ref_only", "field_grounded"), default="field_grounded")
    parser.add_argument("--transport", choices=("direct", "mcp_http"), default="direct")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--message-index", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.fixture is None or args.config is None:
            parser.error("prepare requires --fixture and --config")
        result = prepare(
            args.fixture, args.config, args.run_root, cast(GroundingMode, args.mode), args.transport
        )
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "cases": len(result["fixture"]["cases"]),
                    "fixture_sha256": result["fixture_sha256"],
                }
            )
        )
    elif args.command == "step":
        if not args.case_id or len(args.case_id) != 1 or args.message_index is None:
            parser.error("step requires one --case-id and --message-index")
        result = step(args.run_root, args.case_id[0], args.message_index)
        print(
            json.dumps(
                {key: result[key] for key in ("case_id", "message_id", "process_id", "status")}
            )
        )
        if result["status"] != "completed":
            raise SystemExit(1)
    else:
        outcomes = run(args.run_root, args.case_id)
        print(
            json.dumps(
                {
                    "messages": len(outcomes),
                    "failed_or_not_run": sum(row["returncode"] != 0 for row in outcomes),
                }
            )
        )
        if any(row["returncode"] for row in outcomes):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
