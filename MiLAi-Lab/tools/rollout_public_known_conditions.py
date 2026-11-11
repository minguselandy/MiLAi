"""Run a frozen learned policy in original public Source banks with fixed actual known refs."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.laya_memory_policy import LayaMemoryPolicy
from milai_lab.methods.source_ranges import SourceRangeBudget
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.laya_local import NativeDecision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--families", type=int, default=8)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    original = read_json(args.collection / "run.json")
    if original["status"] != "COMPLETED":
        raise ValueError("Use closed source collection and actual earlier knowledge receipts")
    histories = read_json(args.collection / "sources.json")["histories"]
    histories = histories[args.offset:args.offset + args.families]
    if len(histories) != args.families:
        raise ValueError("Requested source-family prefix is unavailable")
    settings = read_json(args.config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    ranges = SourceRangeBudget(256, capacity.text_tokens, lambda text: capacity.tokenizer(
        text, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"])
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "sources.json", {"histories": histories})
    run = {
        "status": "RUNNING", "pid": os.getpid(), "collection": str(args.collection.resolve()),
        "config": str(args.config.resolve()), "checkpoint": str(args.checkpoint.resolve()),
        "device": args.device, "precision": "float32", "projection": "shared_actions",
        "planned_families": len(histories), "completed_families": 0, "closed_requests": 0,
        "model_calls": 0, "Host_calls": 0, "no_sha_validation": True, "automatic_retry": False,
        "source_bank_reuse": True, "new_Source_copies": 0,
        "scope": "Frozen model public rollouts. Both models use the original lexical collector's "
                 "first returned item as K, never their own potentially different cold output. "
                 "Supplied requests, not autonomous Host. No offline labels enter execution.",
    }
    write_json(args.output / "run.json", run)
    decision = None
    try:
        import torch

        torch.set_num_threads(4)
        torch.backends.mha.set_fastpath_enabled(False)
        decision = NativeDecision(args.checkpoint, 16384, 2048, args.device)
        decision.model.encoder.config.reference_compile = False
        for history in histories:
            request = history["requests"][0]
            bank = args.collection / "banks" / history["id"]
            output = args.output / "banks" / history["id"]
            output.mkdir(parents=True, exist_ok=False)
            mapping = read_json(bank / "source-map.json")["mapping"]
            allowed = set(request.get("source_event_ids", mapping.values()))
            excluded = tuple(ref for ref, native in mapping.items() if native not in allowed)
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                service = MemoryService(store, ("public-operation-collection", history["id"],
                    "collector"), "collector", bank / "lock", functional_contract="functional_v1")
                for condition in ("cold", "known-first"):
                    original_receipt = bank / f"{request['id']}-{condition}-receipt.json"
                    incoming = read_json(original_receipt)["request"]
                    turn = f"{args.output.name}/{condition}"
                    source = service.capture_user(request["id"], turn, request["content"],
                                                  capture_context="given_retrieval_request")
                    service.bind_public_turn(request["id"], turn, source["source_ref"],
                                             config_version=args.output.name, phase="start")
                    cfg = {"configurable": {"user_id": "collector", "v13_session": request["id"],
                        "v13_turn_id": turn, "v13_config_version": args.output.name}}
                    trace = output / f"{request['id']}-{condition}-operations.jsonl"
                    scores = output / f"{request['id']}-{condition}-predictions.jsonl"

                    def record(event: dict, trace: Path = trace) -> None:
                        with trace.open("a") as stream:
                            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

                    def predict(payload: dict, scores: Path = scores) -> dict:
                        result = decision.predict(payload)
                        run["model_calls"] += 1
                        with scores.open("a") as stream:
                            stream.write(json.dumps({"input": payload, "prediction": result},
                                                    ensure_ascii=False) + "\n")
                        return result

                    memory = IntentRetrievalMemory(service, capacity.text_tokens,
                        interface_version="I2", material_limit=settings["ordinary_material_tokens"],
                        read_limit=args.max_steps + 1, source_access="independent_v1",
                        source_tokenization="unicode_v1", source_top_k=16,
                        evidence_policy="question_pack_v1",
                        control_policy=LayaMemoryPolicy(predict, "shared_actions"),
                        control_steps=args.max_steps, control_record=record,
                        control_internal_views=False, control_delivery_selection=True,
                        control_source_observation_tokens=2048, control_source_ranges=ranges,
                        control_excluded_source_refs=excluded, control_exclude_given_requests=True)
                    packet = memory.retrieve(cfg, "actual-retrieval",
                                             RetrievalRequest.model_validate(incoming))
                    write_json(output / f"{request['id']}-{condition}-receipt.json", {
                        "request": incoming, "packet": packet, "Host_executed": False,
                        "native_context_source_ids": sorted(allowed),
                        "original_Source_bank": str(bank.resolve()),
                        "known_reference_parent_receipt": str((bank /
                            f"{request['id']}-cold-receipt.json").resolve()),
                    })
                    run["closed_requests"] += 1
                    run["active_family"] = history["source_group"]
                    write_json(args.output / "run.json", run)
                    print(json.dumps({k: run[k] for k in (
                        "active_family", "closed_requests", "model_calls")}), flush=True)
            run["completed_families"] += 1
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run["compute"] = {"cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - started,
            **(decision.counters if decision is not None else {})}
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
