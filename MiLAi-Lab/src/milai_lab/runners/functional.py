"""Opt-in persistent functional assistant over the existing Store and Agent loop.

Each public message has a resumable checkpoint. Earlier messages are available
through the owner-bound MemoryService, including captured raw fallback, instead
of an unaccounted conversation cache. Evaluation cases are caller inputs only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.functional import FunctionalApplication
from milai_lab.baselines.langmem_agent import build_agent
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import (
    BudgetExceeded,
    RunLimits,
    Trace,
    entry_budget,
    http_budget_scope,
)
from milai_lab.harness.functional_faults import FunctionalFaults
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.service import MemoryService
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.providers.functional_queue import FunctionalQueue, FunctionalVLLMClient

LAB = Path(__file__).resolve().parents[3]


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def sources() -> dict[str, str]:
    paths = [*sorted((LAB / "src").rglob("*.py")), LAB / "tools/run_functional.py"]
    return {
        str(path.relative_to(LAB)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def sdk_identity() -> dict[str, Any]:
    paths = [Path(inspect.getfile(SqliteStore)), Path(inspect.getfile(SqliteSaver))]
    return {
        "python": sys.version,
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "langmem",
                "langgraph",
                "langchain-core",
                "langgraph-checkpoint-sqlite",
                "transformers",
                "tokenizers",
                "httpx",
            )
        },
        "persistence_sources": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        },
        "uv_lock_sha256": hashlib.sha256((LAB / "uv.lock").read_bytes()).hexdigest(),
    }


def prepare(
    root: Path,
    settings_path: Path,
    fixture_path: Path | None = None,
    controls_path: Path | None = None,
) -> dict[str, Any]:
    settings = read_json(settings_path)
    if settings.get("profile") != "functional_v1":
        raise ValueError("FUNCTIONAL_PROFILE_REQUIRED")
    host = VLLMConfig(**settings["host"])
    if any(
        type(settings.get(key)) is not int or settings[key] <= 0
        for key in (
            "max_calls_per_message",
            "ordinary_material_tokens",
            "additional_reads",
        )
    ):
        raise ValueError("FUNCTIONAL_CAPACITY_POLICY_INVALID")
    if (
        settings.get("format_reproposals") not in {0, 1}
        or type(settings.get("format_reproposals")) is not int
        or host.max_calls != settings["max_calls_per_message"]
        or host.max_tokens != settings["capacity"]["output_tokens"]
    ):
        raise ValueError("FUNCTIONAL_CAPACITY_POLICY_INCONSISTENT")
    FunctionalQueue(root / "queue-admission.json", **settings["queue_limits"])
    # This validates pinned local identity without any model HTTP.
    capacity = HostCapacity(settings["capacity"])
    ledger = read_json(Path(settings["budget_path"]))
    config_sha = _hash(settings)
    fixture = read_json(fixture_path) if fixture_path else None
    controls = read_json(controls_path) if controls_path else None
    frozen = {
        "schema": "functional_input_freeze_v1",
        "config": settings,
        "config_sha256": config_sha,
        "source_sha256": sources(),
        "sdk_identity": sdk_identity(),
        "fixture": fixture,
        "evaluator_controls": controls,
        "evaluator_controls_sha256": _hash(controls),
        "fixture_sha256": _hash(fixture),
        "fixture_file_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        if fixture_path
        else None,
        "capacity_identity": capacity.identity,
        "budget_before": ledger,
        "run_id": root.resolve().name,
        "backend": "public_sdk_sqlite",
        "formation": "host_tool_commit_before_final",
        "format_reproposals": settings["format_reproposals"],
        "ordinary_material_tokens": settings["ordinary_material_tokens"],
        "additional_reads": settings["additional_reads"],
        "queue_limits": settings["queue_limits"],
        "semantic_correctness": "requires_separate_evaluation",
    }
    root.mkdir(parents=True, exist_ok=True)
    target = root / "input-freeze.json"
    if target.exists():
        existing = read_json(target)
        for name in (
            "config_sha256",
            "source_sha256",
            "fixture_sha256",
            "evaluator_controls_sha256",
            "sdk_identity",
        ):
            if existing[name] != frozen[name]:
                raise ValueError("FUNCTIONAL_EXISTING_FREEZE_CHANGED:" + name)
        return cast(dict[str, Any], existing)
    write_json(target, frozen)
    return frozen


def frozen(root: Path) -> dict[str, Any]:
    value = read_json(root / "input-freeze.json")
    if value["source_sha256"] != sources() or value["config_sha256"] != _hash(value["config"]):
        raise ValueError("FUNCTIONAL_SOURCE_OR_CONFIG_CHANGED_AFTER_FREEZE")
    if value["fixture_sha256"] != _hash(value["fixture"]):
        raise ValueError("FUNCTIONAL_FIXTURE_CHANGED_AFTER_FREEZE")
    if value["evaluator_controls_sha256"] != _hash(value["evaluator_controls"]):
        raise ValueError("FUNCTIONAL_EVALUATOR_CONTROLS_CHANGED_AFTER_FREEZE")
    if value["sdk_identity"] != sdk_identity():
        raise ValueError("FUNCTIONAL_SDK_CHANGED_AFTER_FREEZE")
    return cast(dict[str, Any], value)


def _status(error: Exception) -> tuple[str, str]:
    text = str(error).upper()
    if isinstance(error, BudgetExceeded) or "GENERATION_CAPACITY_EXCEEDED" in text:
        return "BUDGET_EXHAUSTED", "budget"
    if isinstance(error, httpx.HTTPError):
        return "PROVIDER_ERROR", "provider"
    if isinstance(error, CapacityExceeded):
        return "FAILED", "request_capacity"
    if "UNKNOWN" in text or isinstance(error, OSError):
        return "UNKNOWN", "storage_or_business_unknown"
    return "FAILED", "input_or_runtime"


def format_failures(messages: list[Any]) -> list[str]:
    """Count actual structural rejection receipts, never infer semantic correctness."""
    rejected = []
    for row in messages:
        if not isinstance(row, ToolMessage):
            continue
        try:
            body = json.loads(str(row.content))
        except ValueError:
            continue
        if isinstance(body, dict) and (
            body.get("origin") in {"jsonschema", "pydantic"}
            or body.get("error_category") == "schema"
        ):
            rejected.append(row.tool_call_id)
    return list(dict.fromkeys(rejected))


def seed_sources(
    service: MemoryService, rows: list[dict[str, Any]], path: Path
) -> list[dict[str, Any]]:
    """Capture supplied events once; a later import cannot resurrect forgotten text."""
    identity = _hash(rows)
    if path.exists():
        saved = read_json(path)
        if saved["input_sha256"] != identity:
            raise ValueError("FUNCTIONAL_IMPORTED_SOURCE_SET_CHANGED")
        return cast(list[dict[str, Any]], saved["receipts"])
    receipts = []
    for row in rows:
        if row.get("object_ref") is not None:
            raise ValueError("FUNCTIONAL_IMPORTED_OBJECT_AUTHORITY_FORBIDDEN")
        if row["role"] == "user":
            capture = service.capture_user(row["session_id"], row["event_key"], row["content"])
        elif row["role"] == "assistant":
            capture = service.capture_assistant(row["session_id"], row["event_key"], row["content"])
        elif row["role"] == "tool":
            capture = service.capture_tool(
                row["session_id"], row["event_key"], row["origin"], row["content"], None
            )
        else:
            raise ValueError("FUNCTIONAL_IMPORTED_ROLE_INVALID")
        if not capture.get("ok"):
            raise ValueError("FUNCTIONAL_IMPORTED_SOURCE_UNAVAILABLE")
        actual = service.source(capture["source_ref"])
        if actual is None or (
            row.get("content_sha256") and actual["content_sha256"] != row["content_sha256"]
        ):
            raise ValueError("FUNCTIONAL_IMPORTED_SOURCE_HASH_CHANGED")
        receipts.append(
            {
                "original_event_id": row.get("original_event_id"),
                "original_observed_at": row.get("observed_at"),
                "receipt": capture,
            }
        )
    write_json(path, {"input_sha256": identity, "receipts": receipts})
    return receipts


def message(
    root: Path,
    *,
    bank: str,
    owner: str,
    session: str,
    message_id: str,
    content: str,
    workflow: str = "reservation",
    initial_world: dict[str, Any] | None = None,
    initial_sources: list[dict[str, Any]] | None = None,
    retrieval_candidates: list[dict[str, Any]] | None = None,
    evaluator_control: dict[str, Any] | None = None,
    message_index: int = 0,
    resume: bool = False,
) -> dict[str, Any]:
    freeze = frozen(root)
    workflow = {"reservation_v1": "reservation", "document_publication_v1": "document"}.get(
        workflow, workflow
    )
    if workflow not in {"reservation", "document"}:
        raise ValueError("FUNCTIONAL_WORKFLOW_INVALID")
    profile_state = root / "profile-state.json"
    if profile_state.exists() and read_json(profile_state).get("disabled"):
        raise ValueError("FUNCTIONAL_PROFILE_DISABLED")
    settings = freeze["config"]
    bank_root = root / "banks" / _hash([bank, owner])[:24]
    bank_root.mkdir(parents=True, exist_ok=True)
    public = {
        "owner": owner,
        "session": session,
        "message_id": message_id,
        "content": content,
        "workflow": workflow,
    }
    identity = _hash([session, message_id])
    result_path = bank_root / (identity + "-result.json")
    input_path = bank_root / (identity + "-input.json")
    if input_path.exists() and read_json(input_path) != public:
        raise ValueError("FUNCTIONAL_PUBLIC_MESSAGE_IDENTITY_CHANGED")
    if result_path.exists() and not resume:
        return cast(dict[str, Any], read_json(result_path))
    write_json(input_path, public)
    attempt = len(list(bank_root.glob(identity + "-attempt-*.json")))
    trace = Trace(bank_root / f"{identity}-trace-{attempt}.jsonl", "functional_v1")
    output: dict[str, Any] = {
        **public,
        "bank": bank,
        "process_id": os.getpid(),
        "attempt": attempt,
        "status": "UNKNOWN",
    }
    namespace = ("functional", freeze["run_id"], bank, owner)
    scope = FoundationScope(freeze["run_id"], bank, owner, session + ":" + message_id)
    cfg = scope.config()
    cfg["configurable"].update(
        v13_session=session,
        v13_turn_id=message_id,
        v13_support_config_sha256=freeze["config_sha256"],
    )
    with ExitStack() as stack:
        stack.enter_context(
            http_budget_scope(
                settings,
                RunLimits(**freeze["budget_before"]["limits"]),
                client_configs=[asdict(VLLMConfig(**settings["host"]))],
            )
        )
        budget = entry_budget(
            RunLimits(**freeze["budget_before"]["limits"]), Path(settings["budget_path"])
        )
        before = json.loads(json.dumps(budget.state))
        try:
            store = stack.enter_context(
                SqliteStore.from_conn_string(str(bank_root / "memory.sqlite"))
            )
            saver = stack.enter_context(
                SqliteSaver.from_conn_string(str(bank_root / "checkpoints.sqlite"))
            )
            service = MemoryService(
                store,
                namespace,
                owner,
                bank_root / "memory.lock",
                functional_contract="functional_v1",
                receipt_profile=(
                    "document_publication_v1"
                    if workflow in {"document", "document_publication_v1"}
                    else "reservation_v1"
                ),
                observer=trace,
            )
            seed_receipts = (
                seed_sources(service, initial_sources, bank_root / "source-imports.json")
                if initial_sources
                else []
            )
            if seed_receipts:
                output["source_import_receipts"] = seed_receipts
            capture = service.capture_user(session, message_id, content)
            output["capture"] = capture
            trace({"event": "functional_capture", "receipt": capture})
            if not capture.get("ok"):
                raise ValueError("FUNCTIONAL_SOURCE_CAPTURE_UNAVAILABLE:" + str(capture))
            service.bind_source_boundary(session, message_id, [capture["source_ref"]])
            capacity = HostCapacity(settings["capacity"])
            memory = FunctionalMemory(
                service,
                capacity.text_tokens,
                read_limit=settings["additional_reads"],
                material_limit=settings["ordinary_material_tokens"],
                retrieval_candidates=[
                    {
                        **row,
                        "source_ref": next(
                            receipt["receipt"]["source_ref"]
                            for receipt in seed_receipts
                            if receipt["original_event_id"] == row["source_ref"]
                        ),
                    }
                    for row in retrieval_candidates
                ]
                if retrieval_candidates is not None
                else None,
            )
            world_settings = {
                "initial_" + key if not key.startswith("initial_") else key: value
                for key, value in (initial_world or {}).items()
            }
            faults = FunctionalFaults(
                bank_root / "evaluator-control-state.json", evaluator_control or {}, message_index
            )
            app = stack.enter_context(
                FunctionalApplication.open(
                    bank_root / "applications" / workflow,
                    workflow,
                    owner,
                    response_hook=faults.after_native,
                    **world_settings,
                )
            )
            faults.before_message(app)
            client = FunctionalVLLMClient(
                VLLMConfig(**settings["host"]), emit=trace, budget=budget, capacity=capacity
            )
            stack.enter_context(client)
            client.queue = FunctionalQueue(
                root / "queue-admission.json", **settings["queue_limits"]
            )
            model = LangMemRecipeChatModel(
                client=client,
                capacity_path=bank_root / "message-admission.json",
                max_calls_per_message=settings["max_calls_per_message"],
                generation_admission_profile="durable_shared_v1",
                tool_schema_communication="shape_feedback_v1",
            )
            admission_path = bank_root / "message-admission.json"
            prior_admission = next(
                (
                    row
                    for row in (
                        read_json(admission_path).get("messages", {}).values()
                        if admission_path.exists()
                        else []
                    )
                    if row["identity"]["owner"] == owner
                    and row["identity"]["bank"] == list(namespace)
                    and row["identity"]["session"] == session
                    and row["identity"]["public_message_id"] == message_id
                ),
                None,
            )
            model.begin_public_message(
                message_id,
                admission_phase="resume" if prior_admission else "start",
                admission_scope={
                    "owner": owner,
                    "bank": list(namespace),
                    "session": session,
                    "request_ref": capture["source_ref"],
                    "request_sha256": _hash(public),
                    "config_sha256": freeze["config_sha256"],
                },
            )
            tool_catalog = [convert_to_openai_tool(tool) for tool in [*memory.tools(), *app.tools]]
            trace({"event": "functional_tool_catalog", "tools": tool_catalog})

            def context_hook(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
                material = memory.context(
                    session, message_id, freeze["config_sha256"], query=content
                )
                messages = list(state["messages"])
                rejected = format_failures(messages)
                if len(rejected) > settings["format_reproposals"]:
                    trace({"event": "functional_format_budget_exhausted", "calls": rejected})
                    raise ValueError("FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED")
                # A successful forget invalidates previously delivered memory within
                # this public message too. Other public messages have distinct checkpoints.
                forgotten_at = None
                for index, row in enumerate(messages):
                    if isinstance(row, ToolMessage) and row.name == "forget_memory":
                        try:
                            receipt = json.loads(str(row.content))
                        except ValueError:
                            continue
                        if receipt.get("ok"):
                            forgotten_at = index
                if forgotten_at is not None:
                    forgotten = messages[forgotten_at]
                    # Keep only the matching forget call from a possible multi-call
                    # generation; unrelated arguments can contain revoked text.
                    matching = []
                    for generated in reversed(messages[:forgotten_at]):
                        if isinstance(generated, AIMessage):
                            calls = [
                                call
                                for call in generated.tool_calls
                                if call["id"] == forgotten.tool_call_id
                            ]
                            if calls:
                                matching = [
                                    AIMessage(content="", id=generated.id, tool_calls=calls)
                                ]
                                break
                    messages = [
                        HumanMessage(content=content, id=message_id),
                        *matching,
                        *messages[forgotten_at:],
                    ]
                trace({"event": "functional_material_delivery", "material": material})
                return {
                    "llm_input_messages": [
                        SystemMessage(
                            content=settings["system_prompt"]
                            + "\n"
                            + json.dumps(material, ensure_ascii=False)
                        ),
                        *messages,
                    ]
                }

            call_wrapper = app.call_wrapper(
                service, session, message_id, trace, cfg, boundary_hook=faults.boundary
            )

            def dispatch(request: Any, execute: Any) -> Any:
                def native(current: Any) -> Any:
                    faults.before_native(current)
                    return execute(current)

                return call_wrapper(request, native)

            agent = build_agent(
                model,
                store,
                saver,
                app.tools,
                memory_tools=memory.tools(),
                system_prompt=settings["system_prompt"],
                benchmark_view_hook=context_hook,
                tool_schema_communication="shape_feedback_v1",
                business_call_wrapper=dispatch,
            )
            app.recover_pending(agent, scope, call_wrapper)
            snapshot = agent.get_state(cfg)
            prior = snapshot.values.get("messages", []) if snapshot.values else []
            if prior and not snapshot.next:
                messages = prior
            else:
                result = agent.invoke(
                    None if prior else {"messages": [HumanMessage(content=content, id=message_id)]},
                    cfg,
                    durability="sync",
                )
                messages = result["messages"]
            output.update(
                status="COMPLETED",
                messages=[row.model_dump(mode="json") for row in messages],
                final_answer=next(
                    (
                        row.content
                        for row in reversed(messages)
                        if isinstance(row, AIMessage) and not row.tool_calls
                    ),
                    None,
                ),
                generation_calls=model.calls_in_message,
            )
            checkpointed_calls = {
                row.tool_call_id for row in messages if isinstance(row, ToolMessage)
            }
            for key, progress in app.progress.snapshot().items():
                if (
                    progress["identity"]["thread_id"] == cfg["configurable"]["thread_id"]
                    and progress["identity"]["call_id"] in checkpointed_calls
                    and "delivery_response" in progress
                ):
                    app.progress.acknowledge_delivery(key)
            mutation_receipts = []
            for position, row in enumerate(messages):
                if isinstance(row, ToolMessage) and row.name in {
                    "save_memory",
                    "update_memory",
                    "forget_memory",
                }:
                    mutation_receipts.append(
                        {
                            "position": position,
                            "tool": row.name,
                            "tool_call_id": row.tool_call_id,
                            "receipt": row.content,
                        }
                    )
            # Capture assistant speech as its real role, never as new user evidence.
            service.capture_assistant(session, message_id + ":final", output["final_answer"] or "")
            output.update(
                records=service.records(),
                sources=service.sources(),
                world=app.snapshot(),
                memory_mutation_receipts=mutation_receipts,
                formation_stage="host_tools_before_final",
                snapshot_before_close=True,
            )
        except Exception as error:
            status, category = _status(error)
            output.update(
                status=status,
                error_category=category,
                error_type=type(error).__name__,
                error=str(error),
            )
            trace(
                {
                    "event": "functional_failure",
                    "status": status,
                    "category": category,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
            if "service" in locals():
                try:
                    output.update(
                        records=service.records(),
                        sources=service.sources(),
                        snapshot_before_close=True,
                    )
                except Exception as snapshot_error:
                    output["snapshot_error"] = (
                        type(snapshot_error).__name__ + ":" + str(snapshot_error)
                    )
            if "app" in locals():
                try:
                    output["world"] = app.snapshot()
                except Exception as snapshot_error:
                    output["application_snapshot_error"] = (
                        type(snapshot_error).__name__ + ":" + str(snapshot_error)
                    )
            if "agent" in locals():
                try:
                    checkpoint = agent.get_state(cfg)
                    output["messages"] = [
                        row.model_dump(mode="json") for row in checkpoint.values.get("messages", [])
                    ]
                    output["pending_nodes"] = list(checkpoint.next)
                except Exception as checkpoint_error:
                    output["checkpoint_snapshot_error"] = (
                        type(checkpoint_error).__name__ + ":" + str(checkpoint_error)
                    )
            if "model" in locals():
                output["generation_calls"] = model.calls_in_message
        if "faults" in locals() and evaluator_control:
            output["evaluator_control_state"] = faults.state
        output.update(
            usage=trace.usage,
            budget_before=before,
            budget_after=json.loads(json.dumps(budget.state)),
        )
        write_json(bank_root / f"{identity}-attempt-{attempt}.json", output)
        write_json(result_path, output)
    return output


def step(root: Path, case_id: str, index: int, *, resume: bool = False) -> dict[str, Any]:
    freeze = frozen(root)
    case = next(row for row in freeze["fixture"]["cases"] if row["case_id"] == case_id)
    public = case["messages"][index]
    return message(
        root,
        bank=case_id,
        owner=case["owner"],
        session=public["session_id"],
        message_id=public["message_id"],
        content=public["content"],
        workflow=case.get("workflow", "reservation"),
        initial_world=case.get("initial_world"),
        initial_sources=case.get("initial_sources"),
        retrieval_candidates=case.get("retrieval_candidates"),
        evaluator_control=next(
            (
                row
                for row in (freeze.get("evaluator_controls") or {}).get("cases", [])
                if row["case_id"] == case_id
            ),
            None,
        ),
        message_index=index,
        resume=resume,
    )


def run(root: Path) -> list[dict[str, Any]]:
    results = []
    queue_blocked = False
    for case in frozen(root)["fixture"]["cases"]:
        blocked = False
        for index, _ in enumerate(case["messages"]):
            if blocked or queue_blocked:
                results.append(
                    {
                        "case_id": case["case_id"],
                        "message_index": index,
                        "status": "NOT_RUN",
                        "reason": "queue_budget_exhausted"
                        if queue_blocked
                        else "prior_message_incomplete",
                    }
                )
                continue
            child = subprocess.run(  # noqa: S603 -- fixed local executable and argv, no shell
                [
                    sys.executable,
                    str(LAB / "tools/run_functional.py"),
                    "step",
                    "--root",
                    str(root),
                    "--case-id",
                    case["case_id"],
                    "--index",
                    str(index),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            try:
                result = json.loads(child.stdout)
            except ValueError:
                result = {"status": "UNKNOWN", "stderr": child.stderr, "stdout": child.stdout}
            results.append(
                {
                    "case_id": case["case_id"],
                    "message_index": index,
                    "returncode": child.returncode,
                    **result,
                }
            )
            intended_interruption = (
                result["status"] == "UNKNOWN"
                and result.get("error_type") == "InjectedInterruption"
                and result.get("evaluator_control_state", {}).get("fault", {}).get("applied")
                and result["evaluator_control_state"]["fault"].get("message_index") == index
                if result.get("evaluator_control_state", {}).get("fault")
                else False
            )
            blocked = result["status"] != "COMPLETED" and not intended_interruption
            queue_blocked = result["status"] == "BUDGET_EXHAUSTED" and (
                "FUNCTIONAL_QUEUE" in result.get("error", "")
            )
            write_json(root / "results.json", {"results": results})
    write_json(root / "results.json", {"results": results})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "message", "step", "run", "inspect", "disable", "enable")
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--controls", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--index", type=int)
    parser.add_argument("--bank", default="personal")
    parser.add_argument("--owner")
    parser.add_argument("--session")
    parser.add_argument("--message-id")
    parser.add_argument("--text")
    parser.add_argument("--workflow", choices=("reservation", "document"), default="reservation")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.command in {"disable", "enable"}:
        if not (args.root / "input-freeze.json").exists():
            parser.error("profile root has not been prepared")
        result = {"disabled": args.command == "disable", "persistent_data_deleted": False}
        write_json(args.root / "profile-state.json", result)
    elif args.command == "prepare":
        if args.config is None:
            parser.error("prepare requires --config")
        result = prepare(args.root, args.config, args.fixture, args.controls)
        result = {
            "status": "PREPARED",
            "config_sha256": result["config_sha256"],
            "source_files": len(result["source_sha256"]),
        }
    elif args.command == "step":
        if args.case_id is None or args.index is None:
            parser.error("step requires --case-id and --index")
        result = step(args.root, args.case_id, args.index, resume=args.resume)
    elif args.command == "message":
        if not all((args.owner, args.session, args.message_id, args.text)):
            parser.error("message requires --owner --session --message-id --text")
        result = message(
            args.root,
            bank=args.bank,
            owner=args.owner,
            session=args.session,
            message_id=args.message_id,
            content=args.text,
            workflow=args.workflow,
            resume=args.resume,
        )
    elif args.command == "inspect":
        result = frozen(args.root)
    else:
        result = {"results": run(args.root)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
