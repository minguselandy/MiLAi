"""Execute a complete bounded policy from initial paper observations, without Host calls."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from collected_handoff import replay_collected_prefix
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.laya_memory_policy import LayaMemoryPolicy
from milai_lab.methods.memory_control import FixedContextMemoryPolicy, run_memory_control
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path, help="Existing immutable paper Source banks")
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--method", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixed-context", action="store_true")
    mode.add_argument("--checkpoint", type=Path)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--query-time", required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--families", type=int)
    parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    source_run = read_json(args.collection / "run.json")
    if source_run["status"] != "COMPLETED":
        raise ValueError("Use closed Source-bank initialization or collection")
    histories = read_json(args.collection / "sources.json")["histories"]
    histories = histories[args.offset:None if args.families is None
                          else args.offset + args.families]
    if any(len(h["requests"]) != 1 for h in histories):
        raise ValueError("This first-question protocol declares one request per source")
    settings = read_json(args.config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    args.output.mkdir(parents=True, exist_ok=False)
    cases: list[dict[str, Any]] = []
    run: dict[str, Any] = {
        "status": "RUNNING", "pid": os.getpid(), "config": str(args.config.resolve()),
        "collection": str(args.collection.resolve()), "method": args.method,
        "checkpoint": str(args.checkpoint.resolve()) if args.checkpoint else None,
        "device": args.device if args.checkpoint else None,
        "planned_families": len(histories), "completed_families": 0,
        "max_steps": args.max_steps, "query_time": args.query_time,
        "model_calls": 0, "truncated_model_inputs": 0, "Host_calls": 0,
        "source_bank_copies": 0, "automatic_retry": False, "no_sha_validation": True,
        "scope": "Complete policy at the initial observation, using existing core execution. "
                 "No forced last-step HANDOFF beyond native termination. Source banks reused; "
                 "no gold or annotation files read. Last action is provenance, not a "
                 "same-before intervention or a trainable policy-comparison label.",
        "readout_scope": "Complete cold given-question policy followed by the fixed packet "
                         "Reader; empty prior known refs, not autonomous Host/business execution.",
    }
    write_json(args.output / "run.json", run)
    decision = None
    try:
        if args.checkpoint:
            import torch

            from milai_lab.providers.laya_local import NativeDecision

            torch.set_num_threads(4)
            torch.backends.mha.set_fastpath_enabled(False)
            decision = NativeDecision(args.checkpoint, 16384, 2048, args.device)
            decision.model.encoder.config.reference_compile = False
        for index, history in enumerate(histories):
            request = history["requests"][0]
            folder = args.output / f"case-{index:03d}"
            folder.mkdir()
            run["active_family"] = history["source_group"]
            write_json(args.output / "run.json", run)
            trace_path = (args.collection / "banks" / history["id"]
                          / f"{request['id']}-operations.jsonl")
            initial = read_jsonl(trace_path)[0]
            initial_event = f"{history['source_group']}/{request['id']}/step-0"
            prefix = {"event_id": initial_event, "before": initial["before"],
                      "actions": initial["actions"]}

            def predict(payload: dict[str, Any], destination: Path = folder) -> dict[str, Any]:
                assert decision is not None
                result = decision.predict(payload)
                run["model_calls"] += 1
                run["truncated_model_inputs"] += int(result["truncated"])
                with (destination / "model-calls.jsonl").open("a") as stream:
                    stream.write(json.dumps({"input": payload, "output": result},
                                            ensure_ascii=False) + "\n")
                return result

            policy = (FixedContextMemoryPolicy(reads=4) if args.fixed_context
                      else LayaMemoryPolicy(predict, "shared_actions"))
            with replay_collected_prefix(args.collection, history, prefix, settings,
                                         capacity, target_step=0) as (operations, state):
                state.task["query_time"] = args.query_time
                rollout = run_memory_control(state, policy, operations, max_steps=args.max_steps)
                if not rollout["trace"]:
                    raise ValueError("The declared policy produced no control decision")
                last = rollout["trace"][-1]
                action = next(a for a in last["actions"] if a["id"] == last["selected"])
                packet = controlled_reader_packet(operations.reader_evidence(), "collection")
                public = {"content": request["content"], "query_time": args.query_time,
                          "calendar_context": state.task["calendar_context"]}
                wire = given_packet_request(public, state.task["retrieval_request"],
                                            packet, settings)
                write_json(folder / "rollout.json", rollout)
                event_id = f"{history['source_group']}/{request['id']}/policy-{args.method}"
                case = {"case_key": str(index), "family": history["source_group"],
                        "event_id": event_id,
                        "request_id": request["id"], "split": history["split"],
                        "choices": {args.method: action["id"]},
                        "original_Source_bank": str(args.collection / "banks" / history["id"]),
                        "initial_event_id": initial_event,
                        "branches": [{"policies": [args.method], "action": action,
                            "trajectory": str((folder / "rollout.json").resolve()),
                            "execution_result": {
                                "ok": rollout["reason"] != "operation_outcome_unknown",
                                "status": "whole_policy_packet_prepared",
                                "termination_reason": rollout["reason"]},
                            "packet": packet, "readout_request": wire,
                            "body_tokens": capacity.text_tokens(
                                json.dumps(packet, ensure_ascii=False)),
                            "condition_provenance": {"method": args.method,
                                "scope": "Whole trajectory; last action is provenance only",
                                "actual_control_steps": len(rollout["trace"]),
                                "termination_reason": rollout["reason"]}}]}
            cases.append(case)
            run["completed_families"] += 1
            write_json(args.output / "cases.json", cases)
            write_json(args.output / "run.json", run)
            print(json.dumps({"completed_families": run["completed_families"],
                              "model_calls": run["model_calls"]}), flush=True)
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED_FIRST_RETAINED", error_type=type(error).__name__,
                   error=str(error))
        raise
    finally:
        run["compute"] = {"cpu_seconds": time.process_time()-cpu,
                          "wall_seconds": time.perf_counter()-started}
        run["compute_scope"] = ("Tool-stage CPU, not self-billed; "
                                "whole-child accounting is not additive")
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
