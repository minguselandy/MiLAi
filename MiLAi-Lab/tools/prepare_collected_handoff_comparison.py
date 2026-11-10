"""Select and execute three same-pool HANDOFF policies on a fixed development prefix."""

from __future__ import annotations

import argparse
import copy
import fcntl
import gc
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from collected_handoff import replay_collected_prefix
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.laya_memory_policy import project_operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, RulesMemoryPolicy
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.laya_local import NativeDecision
from milai_lab.runners.given_host_readout import given_packet_request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("trained", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--families", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-phase", required=True)
    args = parser.parse_args()
    import torch

    torch.set_num_threads(4)
    torch.backends.mha.set_fastpath_enabled(False)
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    settings = read_json(args.config)["entrypoints"]["functional"]
    histories = {
        h["source_group"]: h for h in read_json(args.collection / "sources.json")["histories"]
    }
    selected = {}
    for branch in read_jsonl(args.collection / "branches.jsonl"):
        if branch["family"] not in selected and len(selected) < args.families:
            if branch["split"] != "dev":
                raise ValueError(
                    "This task comparison uses existing source-disjoint development only"
                )
            selected[branch["family"]] = branch
    branches = list(selected.values())
    rows = [
        decision_example(
            {"before": b["before"], "actions": b["actions"]},
            {
                "family": b["family"],
                "split": b["split"],
                "event_id": b["event_id"],
                "state_id": i,
                "row": i,
            },
        )
        for i, b in enumerate(branches)
    ]
    rows = [project_operation_payload(row, "shared_actions") for row in rows]
    write_json(
        args.output / "selection.json",
        {
            "selection": "First collected HANDOFF per family, first N families in existing order; "
            "no labels, outcomes or model scores used for selection",
            "events": [b["event_id"] for b in branches],
            "requested_families": args.families,
        },
    )
    with (args.output / "model-inputs.jsonl").open("w") as stream:
        for row in rows:
            stream.write(
                json.dumps({k: row[k] for k in ("state", "questions")}, ensure_ascii=False) + "\n"
            )
    run = {
        "status": "RUNNING",
        "pid": os.getpid(),
        "device": args.device,
        "families": len(branches),
        "new_Host_calls": 0,
        "no_sha_validation": True,
        "scorers": {},
        "packets": 0,
        "collection": str(args.collection.resolve()),
        "config": str(args.config.resolve()),
        "automatic_retry": False,
    }
    write_json(args.output / "run.json", run)
    predictions = {}
    try:
        for name, checkpoint in (("base", args.base), ("i2", args.trained)):
            phase_start, phase_cpu = time.perf_counter(), time.process_time()
            decision = NativeDecision(checkpoint, 16384, 2048, args.device)
            decision.model.encoder.config.reference_compile = False
            predictions[name] = []
            for index in range(0, len(rows), 2):
                predictions[name].extend(decision.predict_batch(rows[index : index + 2], 2))
                run.update(active_scorer=name, scorer_rows=len(predictions[name]))
                write_json(args.output / "run.json", run)
                print(json.dumps({"scorer": name, "rows": len(predictions[name])}), flush=True)
            run["scorers"][name] = {
                "checkpoint": str(checkpoint.resolve()),
                **decision.counters,
                "wall_seconds": time.perf_counter() - phase_start,
                "cpu_seconds": time.process_time() - phase_cpu,
            }
            write_json(args.output / f"{name}-predictions.json", predictions[name])
            del decision
            gc.collect()
        capacity = HostCapacity(settings["capacity"])
        observation = SourceObservationBudget(2048, capacity.text_tokens)
        cases = []
        for index, branch in enumerate(branches):
            phase_start, phase_cpu = time.perf_counter(), time.process_time()
            history = histories[branch["family"]]
            request_id = branch["event_id"].rsplit("/", 2)[1]
            original_request = next(r for r in history["requests"] if r["id"] == request_id)
            choices = {name: predictions[name][index]["choice"] for name in predictions}
            actions = [MemoryAction(**a) for a in branch["actions"]]
            choices["rules"] = RulesMemoryPolicy(reads=4).choose(
                MemoryControlState(**copy.deepcopy(branch["before"])), actions
            )
            case = {
                "family": branch["family"],
                "event_id": branch["event_id"],
                "request_id": request_id,
                "choices": choices,
                "branches": [],
                "original_Source_bank": str(args.collection / "banks" / history["id"]),
                "known_evidence_refs": [],
                "prefix_reexecuted_for_reconstruction": True,
            }
            with replay_collected_prefix(args.collection, history, branch, settings, capacity) as (
                operations,
                state,
            ):
                saved = operations.checkpoint()
                for key in dict.fromkeys(choices.values()):
                    operations.restore_checkpoint(saved, observation)
                    state = MemoryControlState(**copy.deepcopy(branch["before"]))
                    action = next(a for a in actions if a.id == key)
                    result = (
                        operations.execute(action, state)
                        if action.parameters
                        else {"ok": True, "status": "current_delivery"}
                    )
                    packet = controlled_reader_packet(operations.reader_evidence(), "collection")
                    public = {
                        "content": original_request["content"],
                        "query_time": state.task["query_time"],
                        "calendar_context": state.task["calendar_context"],
                    }
                    request = RetrievalRequest.model_validate(
                        state.task["retrieval_request"]
                    ).model_dump(mode="json")
                    wire = given_packet_request(public, request, packet, settings)
                    case["branches"].append(
                        {
                            "policies": [
                                name for name, selected_id in choices.items() if selected_id == key
                            ],
                            "action": asdict(action),
                            "execution_result": result,
                            "packet": packet,
                            "readout_request": wire,
                            "body_tokens": capacity.text_tokens(
                                json.dumps(packet, ensure_ascii=False)
                            ),
                            "Host_result": None,
                        }
                    )
                    run["packets"] += 1
            case.update(
                reconstruction_and_delivery_wall_seconds=time.perf_counter() - phase_start,
                reconstruction_and_delivery_cpu_seconds=time.process_time() - phase_cpu,
            )
            cases.append(case)
            write_json(args.output / "cases.json", cases)
            print(json.dumps({"actual_cases": len(cases), "packets": run["packets"]}), flush=True)
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measures = {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "runs": 1,
        }
        write_json(args.output / "compute.json", measures)
        ledger = Path(settings["budget_path"])
        with ledger.with_name("budget.json.http-owner.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(ledger)["limits"]), ledger)
            budget.record_compute(args.compute_phase, measures)
        run["scope"] = (
            "Conditional same-acquired-pool comparison; not autonomous Host results. "
            "Original first packets retained; reconstruction work included in new cost."
        )
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
