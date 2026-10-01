"""Opt-in public baseline micro steps; no scorer, rubric, or native algorithm changes.

Preparation hashes bytes and installed dependency metadata without HTTP or native
SDK instances. Execution is serial, one interpreter process per fixture step.
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

from milai_lab.baselines.benchmark_memories import GenerationAdmission
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import (
    BudgetExceeded,
    RunBudget,
    RunLimits,
    Trace,
    entry_budget,
    http_budget_scope,
)
from milai_lab.harness.http_ownership import (
    check_frozen as check_http_frozen,
)
from milai_lab.harness.http_ownership import (
    freeze_fields as http_freeze_fields,
)
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig, ownership_client_configs

LAB = Path(__file__).resolve().parents[3]
CLI = LAB / "tools/run_v13_1_baseline_micro.py"
BACKENDS = ("mem0_oss", "simplemem_text")
ARCHIVE_INPUT_MODE = "trace_equal_v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources() -> dict[str, str]:
    paths = [*sorted((LAB / "src/milai_lab").rglob("*.py")), CLI]
    return {path.relative_to(LAB).as_posix(): _sha(path) for path in paths}


def _policy(config: dict[str, Any]) -> dict[str, Any]:
    from milai_lab.integrations.memory.simplemem import POLICY

    source = config.get("simplemem_source_root")
    if not isinstance(source, str) or not Path(source).is_absolute():
        raise ValueError("V13_MICRO_SIMPLEMEM_SOURCE_ROOT_REQUIRED")
    return {**POLICY, "source_root": source}


def _dependency_identity(backend: str, config: dict[str, Any]) -> dict[str, Any]:
    # These helpers read installed distribution metadata/source bytes, not SDKs.
    if backend == "mem0_oss":
        from milai_lab.integrations.memory.mem0 import mem0_dependency_identity

        return mem0_dependency_identity()
    from milai_lab.integrations.memory.simplemem import dependency_identity

    return dependency_identity(_policy(config))


def _interpreter() -> dict[str, str]:
    return {"executable": sys.executable, "prefix": sys.prefix, "version": sys.version}


def _validate(fixture: Any, config: Any, backend: str) -> None:
    if backend not in BACKENDS or not isinstance(fixture, dict) or not fixture.get("cases"):
        raise ValueError("V13_MICRO_PUBLIC_FIXTURE_AND_BACKEND_REQUIRED")
    seen: set[str] = set()
    for case in fixture["cases"]:
        if (
            not isinstance(case, dict)
            or not all(isinstance(case.get(key), str) and case[key] for key in ("case_id", "owner"))
            or case["case_id"] in seen
            or not case.get("steps")
        ):
            raise ValueError("V13_MICRO_CASE_INVALID")
        seen.add(case["case_id"])
        step_ids: set[str] = set()
        for item in case["steps"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("step_id"), str)
                or (not item["step_id"] or item["step_id"] in step_ids)
            ):
                raise ValueError("V13_MICRO_STEP_ID_INVALID")
            step_ids.add(item["step_id"])
            if "owner" in item and (not isinstance(item["owner"], str) or not item["owner"]):
                raise ValueError("V13_MICRO_CALLER_OWNER_INVALID")
            cap = item.get("generation_cap", 12)
            if type(cap) is not int or cap < 0:
                raise ValueError("V13_MICRO_GENERATION_CAP_INVALID")
            operation = item.get("operation")
            if operation == "archive":
                if (
                    not isinstance(item.get("records"), list)
                    or not item["records"]
                    or any(not isinstance(row, dict) for row in item["records"])
                    or "query" in item
                    or "reader_question" in item
                ):
                    raise ValueError("V13_MICRO_ARCHIVE_RECORDS_ONLY")
            elif operation == "search":
                if (
                    not isinstance(item.get("query"), str)
                    or not item["query"]
                    or ("records" in item)
                    or (
                        "reader_question" in item
                        and (
                            not isinstance(item["reader_question"], str)
                            or not item["reader_question"]
                        )
                    )
                ):
                    raise ValueError("V13_MICRO_SEARCH_INVALID")
            elif operation != "snapshot" or any(
                key in item for key in ("records", "query", "reader_question")
            ):
                raise ValueError("V13_MICRO_OPERATION_INVALID")
    if not isinstance(config, dict) or not isinstance(config.get("capacity"), dict):
        raise ValueError("V13_MICRO_CONFIG_INVALID")
    host, embedding = VLLMConfig(**config["host"]), VLLMConfig(**config["embedding"])
    if (
        host.temperature != 0
        or embedding.model != "bge-m3"
        or (config.get("embedding_dimension", 1024) != 1024)
    ):
        raise ValueError("V13_MICRO_PROVIDER_SETTINGS_INVALID")
    prompt = config.get("reader_system_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("V13_MICRO_READER_SYSTEM_PROMPT_INVALID")
    context = config.get("embedding_context_tokens")
    if context is not None and (type(context) is not int or context <= 0):
        raise ValueError("V13_MICRO_EMBEDDING_CONTEXT_METADATA_INVALID")
    budget_path = Path(config["budget_path"])
    if not budget_path.is_absolute() or not budget_path.is_file():
        raise ValueError("V13_MICRO_EXISTING_CONTINUOUS_BUDGET_REQUIRED")
    if backend == "simplemem_text":
        _policy(config)
        if config.get("simplemem_archive_input_mode", ARCHIVE_INPUT_MODE) != ARCHIVE_INPUT_MODE:
            raise ValueError("V13_MICRO_SIMPLEMEM_MODE_INVALID")


def prepare(fixture_path: Path, config_path: Path, root: Path, backend: str) -> dict[str, Any]:
    fixture, config = read_json(fixture_path), read_json(config_path)
    with http_budget_scope(config, client_configs=ownership_client_configs(config)):
        _validate(fixture, config, backend)
        budget_limits = read_json(Path(config["budget_path"]))["limits"]
        RunLimits(**budget_limits)
        native: dict[str, Any]
        if backend == "simplemem_text":
            native = {"policy": _policy(config), "archive_input_mode": ARCHIVE_INPUT_MODE}
        else:
            from milai_lab.integrations.memory.mem0 import MEM0_POLICY

            native = {"policy": MEM0_POLICY, "ingestion": "existing_marked_add_archive"}
        frozen = {
            "kind": "MILAI_V13_1_BASELINE_MICRO_FREEZE",
            **http_freeze_fields(config),
            "fixture": fixture,
            "fixture_path": str(fixture_path.resolve()),
            "fixture_sha256": _sha(fixture_path),
            "config": config,
            "config_path": str(config_path.resolve()),
            "config_sha256": _sha(config_path),
            "source_sha256": _sources(),
            "reader_prompt_sha256": hashlib.sha256(
                config["reader_system_prompt"].encode()
            ).hexdigest(),
            "reader_wire": (
                "system=verbatim configured prompt; user=JSON question+native search results"
            ),
            "reader_temperature": 0,
            "native_stage_temperatures": "existing adapter/SDK policy",
            "backend": backend,
            "native": native,
            "dependency": _dependency_identity(backend, config),
            "interpreter": _interpreter(),
            "budget_limits": budget_limits,
            "run_id": root.resolve().name,
            "embedding_context": {
                "configured_tokens": config.get("embedding_context_tokens"),
                "admission_enforced": False,
            },
            "provider_concurrency": (
                "serial phases; existing native generation/embedding bridge locks"
            ),
        }
        target = root / "input-freeze.json"
        if target.exists() and read_json(target) != frozen:
            raise ValueError("V13_MICRO_INPUT_FREEZE_CHANGED")
        write_json(target, frozen)
        return frozen


def _frozen(root: Path, http_stack: ExitStack | None = None) -> dict[str, Any]:
    frozen = cast(dict[str, Any], read_json(root / "input-freeze.json"))
    if frozen["source_sha256"] != _sources():
        raise ValueError("V13_MICRO_SOURCE_CHANGED_AFTER_FREEZE")
    if (
        frozen["fixture_sha256"] != _sha(Path(frozen["fixture_path"]))
        or (frozen["config_sha256"] != _sha(Path(frozen["config_path"])))
        or frozen["fixture"] != read_json(Path(frozen["fixture_path"]))
        or (frozen["config"] != read_json(Path(frozen["config_path"])))
    ):
        raise ValueError("V13_MICRO_INPUT_CHANGED_AFTER_FREEZE")
    if frozen["reader_prompt_sha256"] != hashlib.sha256(
        frozen["config"]["reader_system_prompt"].encode()
    ).hexdigest() or (
        frozen["backend"] == "simplemem_text"
        and frozen["native"]
        != {
            "policy": _policy(frozen["config"]),
            "archive_input_mode": ARCHIVE_INPUT_MODE,
        }
    ):
        raise ValueError("V13_MICRO_EFFECTIVE_PARAMETERS_CHANGED")
    if frozen["interpreter"] != _interpreter() or frozen["dependency"] != (
        _dependency_identity(frozen["backend"], frozen["config"])
    ):
        raise ValueError("V13_MICRO_INTERPRETER_OR_DEPENDENCY_CHANGED")
    check_http_frozen(frozen)
    with ExitStack() as ownership:
        (http_stack if http_stack is not None else ownership).enter_context(
            http_budget_scope(
                frozen["config"],
                RunLimits(**frozen["budget_limits"]),
                client_configs=ownership_client_configs(frozen["config"]),
            )
        )
        if read_json(Path(frozen["config"]["budget_path"]))["limits"] != frozen["budget_limits"]:
            raise ValueError("V13_MICRO_BUDGET_LIMITS_CHANGED")
    return frozen


def _native_runtime(
    backend: str,
    config: dict[str, Any],
    resource: Path,
    run_id: str,
    primary_owner: str,
    host: VLLMClient,
    embed: VLLMClient,
    admit: Any,
) -> Any:
    if backend == "mem0_oss":
        from milai_lab.integrations.memory.mem0 import Mem0NativeRuntime

        return Mem0NativeRuntime(resource, run_id, backend, host, embed, admit_generation=admit)
    from milai_lab.integrations.memory.simplemem import SimpleMemTextRuntime

    return SimpleMemTextRuntime(
        resource,
        run_id,
        backend,
        primary_owner,
        host,
        embed,
        _policy(config),
        admit_generation=admit,
        archive_input_mode=ARCHIVE_INPUT_MODE,
    )


def _paths(root: Path, case_id: str, step_id: str) -> tuple[Path, Path]:
    case_root = root / hashlib.sha256(case_id.encode()).hexdigest()
    return case_root, case_root / f"step-{hashlib.sha256(step_id.encode()).hexdigest()}.json"


def _is_cap(error: BaseException) -> bool:
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, (BudgetExceeded, CapacityExceeded)) or (
            "BENCHMARK_ARCHIVE_GENERATION_CAPACITY_EXCEEDED" in str(cause)
        ):
            return True
        cause = cause.__cause__
    return False


def step(root: Path, case_id: str, step_id: str) -> dict[str, Any]:
    case_root, receipt_path = _paths(root, case_id, step_id)
    if receipt_path.exists():
        _frozen(root)
        return cast(dict[str, Any], read_json(receipt_path))
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    output: dict[str, Any] = {
        "case_id": case_id,
        "step_id": step_id,
        "process_id": os.getpid(),
        "status": "INTERRUPTED",
        "stop_case": True,
        "first_error": None,
    }
    events: list[dict[str, Any]] = []
    trace = Trace(receipt_path.with_suffix(".jsonl"), "v13_1_baseline_micro")
    phase = "freeze"
    budget: RunBudget | None = None
    cap: GenerationAdmission | None = None
    rejected: list[str] = []

    def emit(event: dict[str, Any]) -> None:
        events.append(event)
        if output["first_error"] is None and (
            event["event"]
            in {
                "vllm_error",
                "vllm_capacity_rejected",
                "vllm_budget_rejected",
                "micro_generation_cap_rejected",
            }
            or (event["event"] == "simplemem_observation" and event.get("outcome") == "error")
        ):
            output["first_error"] = {"stage": phase, "event": event}
        trace(event)

    with ExitStack() as http_stack:
        try:
            frozen = _frozen(root, http_stack)
            case = next(row for row in frozen["fixture"]["cases"] if row["case_id"] == case_id)
            index = next(i for i, row in enumerate(case["steps"]) if row["step_id"] == step_id)
            item, config = case["steps"][index], frozen["config"]
            if index:
                prior_path = _paths(root, case_id, case["steps"][index - 1]["step_id"])[1]
                if not prior_path.exists() or read_json(prior_path)["stop_case"]:
                    raise ValueError("V13_MICRO_PRIOR_TERMINAL_STEP_REQUIRED")
            caller = item.get("owner", case["owner"])
            output.update(
                backend=frozen["backend"],
                operation=item["operation"],
                owner=caller,
                primary_owner=case["owner"],
                generation_cap=item.get("generation_cap", 12),
            )
            emit(
                {
                    "event": "micro_public_step",
                    "input": item,
                    "primary_owner": case["owner"],
                    "process_id": os.getpid(),
                    "fixture_sha256": frozen["fixture_sha256"],
                }
            )
            phase = "setup"
            budget = entry_budget(RunLimits(**frozen["budget_limits"]), Path(config["budget_path"]))
            output["budget_before"] = json.loads(json.dumps(budget.state))
            cap = GenerationAdmission(output["generation_cap"])

            def admit() -> None:
                assert cap is not None
                try:
                    cap()
                except ValueError as error:
                    rejected.append(str(error))
                    emit(
                        {
                            "event": "micro_generation_cap_rejected",
                            "reason": str(error),
                            "request_sent": False,
                        }
                    )
                    raise

            with ExitStack() as stack:
                capacity = HostCapacity(config["capacity"])
                host = stack.enter_context(
                    VLLMClient(
                        VLLMConfig(**config["host"]),
                        emit=emit,
                        budget=budget,
                        capacity=capacity,
                    )
                )
                embed = stack.enter_context(
                    VLLMClient(
                        VLLMConfig(**config["embedding"]),
                        emit=emit,
                        budget=budget,
                    )
                )
                resource = case_root / "backend-resource"
                native = _native_runtime(
                    frozen["backend"],
                    config,
                    resource,
                    frozen["run_id"],
                    case["owner"],
                    host,
                    embed,
                    admit,
                )
                stack.callback(native.close)
                phase = "native_api"
                try:
                    if item["operation"] == "archive":
                        result = native.add_archive(caller, item["records"])
                    elif item["operation"] == "snapshot":
                        result = native.snapshot(caller)
                    else:
                        result = native.search_archive(caller, item["query"])
                    output["native_result"] = result
                    native_status = (
                        result.get("status", "COMPLETED")
                        if isinstance(result, dict)
                        else ("COMPLETED")
                    )
                    output.update(
                        native_status=native_status,
                        status=native_status
                        if native_status in {"INCOMPLETE", "MAINTENANCE_INCOMPLETE"}
                        else "MAINTENANCE_INCOMPLETE"
                        if rejected
                        else native_status,
                        stop_case=False,
                    )
                    provider_errors = [event for event in events if event["event"] == "vllm_error"]
                    provider_outcomes = [
                        event
                        for event in events
                        if event["event"] in {"vllm_error", "vllm_response"}
                    ]
                    pending_exhaustion, failed_native_stage = False, False
                    for event in events:
                        if event["event"] != "simplemem_observation":
                            continue
                        if event.get("kind") == "completion":
                            pending_exhaustion = event.get("outcome") == "exhausted"
                        elif event.get("kind") == "writer_window" or str(
                            event.get("kind")
                        ).startswith("_"):
                            failed_native_stage |= pending_exhaustion and bool(
                                event.get("native_fallback")
                            )
                            pending_exhaustion = False
                    if (
                        provider_errors
                        and (provider_outcomes[-1]["event"] == "vllm_error" or failed_native_stage)
                        and not rejected
                    ):
                        output.update(
                            status="INTERRUPTED",
                            stop_case=True,
                            error="native provider exhaustion; original errors in trace",
                        )
                    if "reader_question" in item:
                        output["reader_status"] = "NOT_RUN_NATIVE_INCOMPLETE"
                        if not output["stop_case"] and output["status"] not in {
                            "INCOMPLETE",
                            "MAINTENANCE_INCOMPLETE",
                        }:
                            phase = "reader"
                            admit()
                            reader_input = {
                                "question": item["reader_question"],
                                "memories": result["results"],
                            }
                            response = host.chat(
                                [
                                    {"role": "system", "content": config["reader_system_prompt"]},
                                    {
                                        "role": "user",
                                        "content": json.dumps(reader_input, ensure_ascii=False),
                                    },
                                ]
                            )
                            output["reader_receipt"] = response
                            choice = response["choices"][0]
                            if choice["finish_reason"] != "stop" or not isinstance(
                                choice["message"].get("content"), str
                            ):
                                raise ValueError("V13_MICRO_READER_RESPONSE_INCOMPLETE")
                            output.update(
                                reader_status="COMPLETED", answer=choice["message"]["content"]
                            )
                except Exception as error:
                    if _is_cap(error):
                        output.update(status="MAINTENANCE_INCOMPLETE", stop_case=False)
                        if phase == "reader":
                            output["reader_status"] = "NOT_RUN_CAP_REFUSAL"
                    elif (
                        phase == "native_api"
                        and isinstance(error, ValueError)
                        and any(code in str(error) for code in ("OWNER_SCOPE", "SCOPE_CHANGED"))
                    ):
                        output.update(status="REJECTED", stop_case=False)
                    else:
                        output.update(status="INTERRUPTED", stop_case=True)
                    output.update(
                        error_type=type(error).__name__, error=str(error), failure_stage=phase
                    )
                    if output["first_error"] is None:
                        output["first_error"] = {
                            "stage": phase,
                            "error_type": type(error).__name__,
                            "error": str(error),
                        }
                phase = "readback"
                read_wall, read_cpu = time.perf_counter_ns(), time.process_time_ns()
                output["records_after"] = native.snapshot(case["owner"])
                emit(
                    {
                        "event": "micro_primary_snapshot",
                        "owner": case["owner"],
                        "calls": 1,
                        "logical_bytes": len(
                            json.dumps(output["records_after"], ensure_ascii=False).encode()
                        ),
                        "wall_ns": time.perf_counter_ns() - read_wall,
                        "cpu_ns": time.process_time_ns() - read_cpu,
                    }
                )
                phase = "close"
        except Exception as error:
            output.update(
                status="INTERRUPTED",
                stop_case=True,
                error_type=type(error).__name__,
                error=str(error),
                failure_stage=phase,
            )
            if output["first_error"] is None:
                output["first_error"] = {
                    "stage": phase,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
        output.update(
            execution_wall_ns=time.perf_counter_ns() - wall,
            execution_cpu_ns=time.process_time_ns() - cpu,
            generation_admitted=cap.calls if cap is not None else 0,
            admission_rejections=rejected,
            usage=trace.usage,
            budget_after=budget.state if budget is not None else None,
            persistent_resource_bytes={
                str(path.relative_to(case_root)): path.stat().st_size
                for path in (case_root / "backend-resource").rglob("*")
                if path.is_file()
            },
            logical_snapshot_bytes=len(
                json.dumps(output.get("records_after"), ensure_ascii=False).encode()
            ),
            cost_scope="full provider reservations/usage; resource sizes and snapshot IO partial",
            cost_measurement_note=(
                "excludes interpreter/import and terminal artifact write; "
                "no complete Store IO trace"
            ),
            embedding_admission="configured context metadata only; no plain tokenizer enforcement",
        )
        emit(
            {
                "event": "micro_terminal",
                "status": output["status"],
                "stop_case": output["stop_case"],
            }
        )
        write_json(receipt_path, output)
        if output["first_error"] is not None and not (case_root / "first-error.json").exists():
            write_json(
                case_root / "first-error.json",
                {
                    "step_id": step_id,
                    "process_id": os.getpid(),
                    "first_error": output["first_error"],
                },
            )
        return output


def run(root: Path, case_ids: list[str] | None = None) -> list[dict[str, Any]]:
    frozen = _frozen(root)
    known = {case["case_id"] for case in frozen["fixture"]["cases"]}
    if case_ids is not None and not set(case_ids) <= known:
        raise ValueError("V13_MICRO_UNKNOWN_CASE")
    results: list[dict[str, Any]] = []
    for case in frozen["fixture"]["cases"]:
        if case_ids is not None and case["case_id"] not in case_ids:
            continue
        blocked = False
        for item in case["steps"]:
            case_root, path = _paths(root, case["case_id"], item["step_id"])
            row: dict[str, Any] = {"case_id": case["case_id"], "step_id": item["step_id"]}
            if blocked:
                results.append({**row, "status": "NOT_RUN", "reason": "prior_step_interrupted"})
                continue
            if path.exists():
                terminal = read_json(path)
                row.update(
                    status=terminal["status"], reused=True, process_id=terminal["process_id"]
                )
                blocked = terminal["stop_case"]
            else:
                wall = time.perf_counter_ns()
                process = subprocess.run(  # noqa: S603 - fixed own interpreter and frozen CLI
                    [
                        sys.executable,
                        str(CLI),
                        "step",
                        "--run-root",
                        str(root.resolve()),
                        "--case-id",
                        case["case_id"],
                        "--step-id",
                        item["step_id"],
                    ],
                    capture_output=True,
                    text=True,
                    cwd=LAB,
                    env={**os.environ, "PYTHONPATH": str(LAB / "src")},
                )
                row.update(
                    returncode=process.returncode,
                    stdout=process.stdout,
                    stderr=process.stderr,
                    process_wall_ns=time.perf_counter_ns() - wall,
                    reused=False,
                )
                if path.exists():
                    terminal = read_json(path)
                    row.update(status=terminal["status"], process_id=terminal["process_id"])
                    blocked = terminal["stop_case"] or process.returncode != 0
                else:
                    row.update(
                        status="INTERRUPTED", reason="process_exited_without_terminal_receipt"
                    )
                    blocked = True
                write_json(case_root / (path.stem + "-process.json"), row)
            results.append(row)
    write_json(root / "process-results.json", {"results": results})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "step", "run"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--backend", choices=BACKENDS)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--step-id")
    args = parser.parse_args()
    if args.command == "prepare":
        if args.fixture is None or args.config is None or args.backend is None:
            parser.error("prepare requires --fixture, --config and --backend")
        frozen = prepare(args.fixture, args.config, args.run_root, args.backend)
        print(
            json.dumps(
                {
                    "status": "PREPARED_ZERO_HTTP",
                    "backend": frozen["backend"],
                    "cases": len(frozen["fixture"]["cases"]),
                }
            )
        )
    elif args.command == "step":
        if not args.case_id or len(args.case_id) != 1 or args.step_id is None:
            parser.error("step requires one --case-id and --step-id")
        output = step(args.run_root, args.case_id[0], args.step_id)
        print(
            json.dumps({key: output[key] for key in ("case_id", "step_id", "status", "process_id")})
        )
        if output["stop_case"]:
            raise SystemExit(1)
    else:
        results = run(args.run_root, args.case_id)
        print(json.dumps({"steps": len(results), "results": results}))
        if any(row["status"] in {"INTERRUPTED", "NOT_RUN"} for row in results):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
