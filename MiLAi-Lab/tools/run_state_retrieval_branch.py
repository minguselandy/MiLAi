"""Run one declared STATE retrieval branch from an actual saved before.

Recipe: {"policy": {"policy": "fixed_context", ...}, "intervention":
{"first_action": <complete captured action>, "continuation_steps": 0}}.
Omit intervention to compare the declared policy's normal continuation. Uses the
original continuous budget and original capacity; never regenerates a Host task,
retries a failure, executes business tools or assigns task-feedback labels.
"""
from __future__ import annotations

import argparse
import copy
import time
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import MeteredEmbeddings
from milai_lab.runners.state_memory import build_retrieval, dependency_generator
from milai_lab.runners.state_retrieval_replay import replay_state_retrieval


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--compute-phase", required=True,
                        help="Distinct original-ledger phase for this branch's direct CPU")
    args = parser.parse_args()
    call, recipe = read_json(args.capture / "call.json"), read_json(args.recipe)
    settings = copy.deepcopy(call["settings"])
    settings["memory_control"] = {**settings.get("memory_control", {}), **recipe["policy"]}
    policy = settings["memory_control"]["policy"]
    host_config = VLLMConfig(**settings["host"])
    embedding_config = VLLMConfig(**settings["embedding"]) if policy == "mempursuit" else None
    clients = [asdict(host_config)]
    if embedding_config is not None:
        clients.append(asdict(embedding_config))
    args.output.mkdir(parents=True, exist_ok=False)
    trace = Trace(args.output / "provider-trace.jsonl", "state_retrieval_branch")
    run: dict[str, Any] = {"status": "RUNNING", "capture": str(args.capture.resolve()),
        "source_version": args.source_version, "recipe": recipe, "settings": settings,
        "compute_phase": args.compute_phase, "automatic_retry": False,
        "original_generation_calls": call["generation_calls_before"],
        "budget_path": settings["budget_path"], "new_budget_created": False,
        "scope": "Frozen actual retrieval branch, not autonomous Host/task feedback."}
    write_json(args.output / "run.json", run)
    started, cpu = time.perf_counter(), time.process_time()
    with ExitStack() as stack:
        budget = stack.enter_context(http_budget_scope(settings, client_configs=clients))
        assert budget is not None
        before = copy.deepcopy(budget.state)
        try:
            capacity = HostCapacity(settings["capacity"])
            client = stack.enter_context(VLLMClient(host_config, emit=trace, budget=budget,
                                                   capacity=capacity))
            host = VLLMChatModel(client=client,
                                max_calls_per_message=settings["max_calls_per_message"])
            host.begin_public_message(call["public_turn"],
                                      checkpoint_calls=call["generation_calls_before"])
            embeddings = None
            if embedding_config is not None:
                embedding_client = stack.enter_context(VLLMClient(
                    embedding_config, emit=trace, budget=budget))
                embeddings = MeteredEmbeddings(embedding_client, embedding_config.model,
                    settings["embedding_capacity"], dimension=settings["embedding_dimension"],
                    batch_size=settings["embedding_batch_size"])

            generate = dependency_generator(host, settings, trace)

            result = replay_state_retrieval(args.capture, args.output / "retrieval",
                source_version=args.source_version, intervention=recipe.get("intervention"),
                build_memory=lambda service, record: build_retrieval(service, capacity.text_tokens,
                    settings, policy, budget, record, embeddings=embeddings, call=generate,
                    admit=lambda: host.reserve_external_request("memory_control"),
                    available=lambda: host.calls_in_message
                    < settings["max_calls_per_message"] - 2))
            run.update(status=result["status"],
                       generation_calls_after=host.calls_in_message)
        except BaseException as error:
            run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            whole_cpu = time.process_time() - cpu
            direct_cpu = sum(metrics.get("cpu_seconds", 0)
                - before.get("compute", {}).get(name, {}).get("cpu_seconds", 0)
                for name, metrics in budget.state.get("compute", {}).items())
            measures = {"wall_seconds": time.perf_counter() - started,
                        "cpu_seconds": whole_cpu - direct_cpu, "runs": 1}
            budget.record_compute(args.compute_phase, measures)
            run.update(budget_before=before, budget_after=copy.deepcopy(budget.state),
                compute=measures, whole_driver_cpu_seconds=whole_cpu,
                nested_cpu_seconds_already_billed=direct_cpu)
            write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
