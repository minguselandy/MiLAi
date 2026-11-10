"""Run first conditional Host readouts of actual same-pool packets, without retries."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import jsonschema

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.given_host_readout import ANSWER_SCHEMA


def parse_readout(response: dict[str, Any]) -> dict[str, Any]:
    choice = response["choices"][0]
    if choice["finish_reason"] != "stop":
        return {"status": "FAILED", "answer": None, "reason": choice["finish_reason"]}
    try:
        parsed = json.loads(choice["message"]["content"])
        jsonschema.validate(parsed, ANSWER_SCHEMA)
    except (ValueError, TypeError, jsonschema.ValidationError) as error:
        return {"status": "FAILED", "answer": None, "reason": type(error).__name__}
    return {"status": "COMPLETED", "answer": parsed["answer"]}


def reusable_readout(
    case: dict[str, Any],
    branch: dict[str, Any],
    prior: list[tuple[Path, dict[str, Any], dict[str, Any]]],
) -> tuple[Path, dict[str, Any]] | None:
    """Reuse a closed first outcome only for the identical actual conditional Host wire."""
    for path, record, wire in prior:
        if (
            record["status"] in {"COMPLETED", "FAILED"}
            and record["family"] == case["family"]
            and record["event_id"] == case["event_id"]
            and record["action"] == branch["action"]
            and wire == branch["readout_request"]
        ):
            return path, record
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--compute-phase", required=True)
    parser.add_argument(
        "--reuse-readouts",
        type=Path,
        help="Reuse earlier first outcomes only where complete Host wires match",
    )
    args = parser.parse_args()
    prepared = read_json(args.prepared / "run.json")
    if prepared["status"] != "COMPLETED":
        raise ValueError("Finish the actual finite decisions and packet execution first")
    settings = read_json(Path(prepared["config"]))["entrypoints"]["functional"]
    cases = read_json(args.prepared / "cases.json")
    prior = []
    if args.reuse_readouts:
        if read_json(args.reuse_readouts / "run.json")["status"] not in {
            "COMPLETED",
            "COMPLETED_WITH_FAILURES",
        }:
            raise ValueError("Reuse requires a closed first-readout matrix")
        previous = read_json(args.reuse_readouts / "readout-paths.json")
        for path in sorted({p for entries in previous.values() for p in entries.values()}):
            record = read_json(Path(path))
            prior.append((Path(path), record, read_json(Path(record["request"]))))
    args.output.mkdir(parents=True, exist_ok=False)
    run = {
        "status": "RUNNING",
        "pid": os.getpid(),
        "prepared": str(args.prepared.resolve()),
        "planned_families": len({case["family"] for case in cases}),
        "planned_states": len(cases),
        "planned_unique_packets": sum(len(case["branches"]) for case in cases),
        "planned_policy_positions": sum(len(case["choices"]) for case in cases),
        "closed_readouts": 0,
        "failed_readouts": 0,
        "chat_invocations": 0,
        "reused_readouts": 0,
        "reuse_source": str(args.reuse_readouts.resolve()) if args.reuse_readouts else None,
        "response_callbacks": 0,
        "error_callbacks": 0,
        "automatic_retry": False,
        "no_sha_validation": True,
        "answer_persisted_as_source": False,
        "scope": "Conditional public task plus actual packet with empty known refs; "
        "not autonomous Host conversation or business execution",
    }
    write_json(args.output / "run.json", run)
    started, cpu = time.perf_counter(), time.process_time()
    trace = Trace(args.output / "trace.jsonl", "collected_handoff_readout")
    paths: dict[str, dict[str, str]] = {}

    def emit(event: dict[str, Any]) -> None:
        trace(event)
        if event["event"] == "vllm_response":
            run["response_callbacks"] += 1
        elif event["event"] == "vllm_error":
            run["error_callbacks"] += 1

    with http_budget_scope(settings) as budget:
        assert budget is not None
        generation_before = dict(budget.state["generation"])
        try:
            capacity = HostCapacity(settings["capacity"])
            with VLLMClient(
                VLLMConfig(**settings["host"]), budget=budget, capacity=capacity, emit=emit
            ) as client:
                for index, case in enumerate(cases):
                    # Rotate the predetermined unique branches; no selection by outcome.
                    branches = case["branches"]
                    offset = index % len(branches)
                    for ordinal in [*range(offset, len(branches)), *range(offset)]:
                        branch = branches[ordinal]
                        destination = args.output / f"case-{index:03d}" / f"packet-{ordinal}"
                        destination.mkdir(parents=True, exist_ok=False)
                        request = branch["readout_request"]
                        write_json(destination / "request.json", request)
                        record = {
                            "status": "RUNNING",
                            "family": case["family"],
                            "event_id": case["event_id"],
                            "request_id": case["request_id"],
                            "policies": branch["policies"],
                            "action": branch["action"],
                            "packet_tokens": branch["body_tokens"],
                            "answer": None,
                            "request": str((destination / "request.json").resolve()),
                        }
                        path = destination / "readout.json"
                        run["active"] = str(path.resolve())
                        write_json(path, record)
                        write_json(args.output / "run.json", run)
                        wall, process = time.perf_counter(), time.process_time()
                        try:
                            if not branch["execution_result"]["ok"]:
                                record.update(status="NOT_EXECUTED", reason="HANDOFF_FAILED")
                            elif (reused := reusable_readout(case, branch, prior)) is not None:
                                previous_path, previous_record = reused
                                record.update(
                                    {
                                        key: previous_record[key]
                                        for key in ("status", "answer", "reason", "error", "usage")
                                        if key in previous_record
                                    }
                                )
                                record.update(
                                    reused_from=str(previous_path.resolve()), new_generation=False
                                )
                                response_path = previous_path.parent / "response.json"
                                if response_path.exists():
                                    shutil.copyfile(response_path, destination / "response.json")
                                run["reused_readouts"] += 1
                                trace(
                                    {
                                        "event": "readout_reused",
                                        "original": str(previous_path),
                                        "request": str(destination / "request.json"),
                                    }
                                )
                            else:
                                record["new_generation"] = True
                                run["chat_invocations"] += 1
                                response = client.chat(
                                    request["messages"],
                                    response_format=request["response_format"],
                                    enable_thinking=request["chat_template_kwargs"][
                                        "enable_thinking"
                                    ],
                                )
                                write_json(destination / "response.json", response)
                                record.update(parse_readout(response), usage=response.get("usage"))
                        except BaseException as error:
                            record.update(
                                status="FAILED", reason=type(error).__name__, error=str(error)
                            )
                            raise
                        finally:
                            record.update(
                                wall_seconds=time.perf_counter() - wall,
                                cpu_seconds=time.process_time() - process,
                            )
                            write_json(path, record)
                        for policy in branch["policies"]:
                            paths.setdefault(policy, {})[case.get("case_key", case["family"])] = (
                                str(path.resolve())
                            )
                        run["closed_readouts"] += 1
                        run["failed_readouts"] += record["status"] != "COMPLETED"
                        write_json(args.output / "readout-paths.json", paths)
                        write_json(args.output / "run.json", run)
                        print(
                            json.dumps(
                                {
                                    k: run[k]
                                    for k in (
                                        "closed_readouts",
                                        "planned_unique_packets",
                                        "failed_readouts",
                                    )
                                }
                            ),
                            flush=True,
                        )
                        if (
                            budget.state["generation"]["unknown_usage"]
                            > generation_before["unknown_usage"]
                        ):
                            raise RuntimeError(
                                "Unconfirmed usage retained; no additional requests dispatched"
                            )
            run["status"] = "COMPLETED_WITH_FAILURES" if run["failed_readouts"] else "COMPLETED"
        except BaseException as error:
            run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            measures = {
                "cpu_seconds": time.process_time() - cpu,
                "wall_seconds": time.perf_counter() - started,
                "runs": 1,
            }
            budget.record_compute(args.compute_phase, measures)
            run.update(
                compute=measures,
                generation_delta={
                    key: value - generation_before[key]
                    for key, value in budget.state["generation"].items()
                },
            )
            write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
