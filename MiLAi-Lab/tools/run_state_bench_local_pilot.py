"""One explicitly selected STATE research run with the existing local Host and MiLAi.

Uses the public orchestrator directly, not the official CLI/protocol or its hash
validation. Domain tools/prompts remain upstream; local Host/simulator, JSON-action,
public observation capture and optional Views are explicit dynamic-research choices.
"""
from __future__ import annotations

import argparse
import copy
import os
import resource
import sys
import time
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.sqlite import SqliteStore

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
from milai_lab.memory.service import MemoryService
from milai_lab.methods.readonly_retrieval import (
    ReadOnlyMemoryService,
    ReadOnlyRetrieval,
    open_readonly_store,
)
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import MeteredEmbeddings
from milai_lab.runners.functional import seed_sources
from milai_lab.runners.state_bench_adapter import (
    StateMemoryHook,
    StateReadOnlyMemoryHook,
    make_state_agent,
    run_with_domain_snapshots,
)
from milai_lab.runners.state_memory import build_retrieval, dependency_generator, policy_and_pool
from milai_lab.runners.state_retrieval_capture import capture_state_retrieval


class LocalSimulator:
    """Keep upstream simulator prompts and use the accounted JSON-action bridge."""

    def __init__(self, model: VLLMChatModel, *, enable_thinking: bool | None = None) -> None:
        self.model = model
        self.enable_thinking = enable_thinking
        self.calls = 0

    def complete_chat(self, *, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        self.model.begin_public_message(f"simulator-{self.calls}")
        result = self.model.invoke([
            SystemMessage(content=messages[0]["content"]),
            HumanMessage(content=messages[1]["content"])],
            enable_thinking=self.enable_thinking)
        return str(result.content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("preparation", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--policy", choices=("fixed_context", "fixed", "mempursuit", "rules",
                                            "view_cache", "laya"),
                        default="fixed_context", help="Existing local evidence policy")
    parser.add_argument("--split", choices=("train", "test"), default="train",
                        help="Declared selection split; task membership is checked before loading")
    parser.add_argument("--memory-protocol", choices=("dynamic", "readonly"), default="dynamic")
    parser.add_argument("--memory-artifact", type=Path,
                        help="Readonly descriptor: database, namespace, owner, source_split=train")
    parser.add_argument("--compute-phase",
                        default="host_intent_view_v4_state_local_travel_pilot_v1",
                        help="Distinct phase in the original ledger for each declared experiment")
    parser.add_argument("--initial-retrieval", type=Path,
                        help="Actual prior Host request for a conditional interface probe only")
    parser.add_argument("--retrieval-snapshots", action="store_true",
                        help="Save actual dynamic pre-call and control-step Store/domain states")
    args = parser.parse_args()
    if (args.memory_protocol == "readonly") != (args.memory_artifact is not None):
        parser.error("--memory-protocol readonly requires --memory-artifact; "
                     "dynamic does not use it")
    if args.retrieval_snapshots and args.memory_protocol != "dynamic":
        parser.error("--retrieval-snapshots captures the dynamic protocol only")
    selection = read_json(args.preparation / "selection.json")
    sys.path.insert(0, selection["source"])
    from state_bench.agents.base import AgentRuntimeContext
    from state_bench.domain import get_domain_config
    from state_bench.env_loader import load_task_environment
    from state_bench.orchestrator import run_task
    from state_bench.schemas import TaskDefinition
    from state_bench.scoring import evaluate_state_requirements

    source = Path(selection["source"])
    domain = get_domain_config(selection["domain"])
    split = read_json(source / "state_bench/domains" / domain.name / "splits/train_test.json")
    if (selection["split"] != args.split
            or selection["task_id"] not in split["splits"][args.split]):
        raise ValueError("STATE task does not belong to the explicitly selected split")
    task = TaskDefinition.load(source / "state_bench/domains" / domain.name / "tasks"
                               / (selection["task_id"] + ".json"))
    initial = read_json(args.initial_retrieval) if args.initial_retrieval else None
    if initial is not None and (initial["task_id"] != task.task_id
                                or initial["public_opening"] != task.opening_message):
        raise ValueError("Frozen initial retrieval belongs to a different public task")
    env_data, env_path = load_task_environment(domain, task)
    settings = read_json(args.config)["entrypoints"]["functional"]
    host_config = VLLMConfig(**settings["host"])
    simulator_thinking = settings.get("stage_enable_thinking", {}).get("state_simulator")
    embedding_config = (VLLMConfig(**settings["embedding"])
                        if args.policy == "mempursuit" else None)
    clients = [asdict(host_config)]
    if embedding_config is not None:
        clients.append(asdict(embedding_config))
    args.output.mkdir(parents=True, exist_ok=False)
    trace = Trace(args.output / "trace.jsonl", "state_local_research_v1")
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": args.source_version, "task_id": task.task_id,
        "split": args.split, "domain": domain.name, "runs": 1, "official_protocol": False,
        "automatic_retry": False, "sha_validation_executed": False,
        "environment_file": str(env_path), "source_selection": selection,
        "host_and_simulator": asdict(host_config), "judge": "NOT_RUN",
        "simulator_enable_thinking_override": simulator_thinking,
        "memory_policy": args.policy, "return_envelope": "at most3strings; one full receipt",
        "memory_protocol": args.memory_protocol,
        "retrieval_snapshots": args.retrieval_snapshots,
        "memory_artifact": str(args.memory_artifact) if args.memory_artifact else None,
        "memory_control_configuration": settings.get("memory_control", {}),
        "compute_phase": args.compute_phase,
        "initial_request_transport": "frozen_actual_request" if initial else "autonomous",
        "initial_request_provenance": initial,
        "max_return_tokens": settings["ordinary_material_tokens"],
        "monetary_cost": "Not priced; upstream default USD fields are not observed zero cost.",
        "scope": "One research trajectory with the declared split and public training corpus. "
                 "Local Qwen Host/simulator and JSON-action transport; deterministic state "
                 "evaluation, without the official simulator/judge or LLM task/UX score."}
    write_json(args.output / "run.json", run)
    started, cpu = time.perf_counter(), time.process_time()
    with ExitStack() as stack:
        budget = stack.enter_context(http_budget_scope(
            settings, client_configs=clients))
        assert budget is not None
        before = copy.deepcopy(budget.state)
        try:
            capacity = HostCapacity(settings["capacity"])
            client = stack.enter_context(VLLMClient(host_config, emit=trace, budget=budget,
                                                   capacity=capacity))
            host = VLLMChatModel(client=client,
                                max_calls_per_message=settings["max_calls_per_message"])
            simulator = LocalSimulator(VLLMChatModel(client=client, max_calls_per_message=1),
                                       enable_thinking=simulator_thinking)
            embeddings = None
            if embedding_config is not None:
                embedding_client = stack.enter_context(VLLMClient(
                    embedding_config, emit=trace, budget=budget))
                embeddings = MeteredEmbeddings(embedding_client, embedding_config.model,
                    settings["embedding_capacity"], dimension=settings["embedding_dimension"],
                    batch_size=settings["embedding_batch_size"])
            service: MemoryService
            store: SqliteStore
            if args.memory_protocol == "dynamic":
                store = stack.enter_context(TransactionalSqliteStore.from_conn_string(
                    str(args.output / "memory.sqlite")))
                owner = "state-public-training-corpus"
                service = MemoryService(store, ("state-research", "pilot", owner), owner,
                    args.output / "memory.lock", functional_contract="functional_v1",
                    memory_profile="unified_v1", memory_ranking="activation")
                run["source_import_receipts"] = seed_sources(service,
                    read_json(args.preparation / "sources.json"),
                    args.output / "source-imports.json",
                    preserve_occurrence=True)
            else:
                artifact = read_json(args.memory_artifact)
                if artifact["source_split"] != "train":
                    raise ValueError("STATE_READONLY_ARTIFACT_REQUIRES_DECLARED_TRAIN_SOURCES")
                store = stack.enter_context(open_readonly_store(Path(artifact["database"])))
                readonly = ReadOnlyMemoryService(store, tuple(artifact["namespace"]),
                    artifact["owner"], args.output / "memory.lock",
                    functional_contract="functional_v1", memory_profile="unified_v1",
                    memory_ranking="activation")
                service = readonly
                run["memory_artifact_provenance"] = artifact

            generate = dependency_generator(host, settings, trace)

            hook: StateMemoryHook | StateReadOnlyMemoryHook
            if args.memory_protocol == "dynamic":
                memory = build_retrieval(service, capacity.text_tokens, settings, args.policy,
                    budget, trace, embeddings=embeddings, call=generate,
                    admit=lambda: host.reserve_external_request("memory_control"),
                    available=lambda: host.calls_in_message < settings["max_calls_per_message"] - 2)
                hook = StateMemoryHook(memory, session="state-task", now=task.now,
                    domain=domain.name,
                    user_id=task.user_id, config_version=args.source_version, record=trace)
            else:
                control = settings.get("memory_control", {})
                policy, rank_pool = policy_and_pool(control, args.policy, budget, trace, embeddings,
                    generate, lambda: host.reserve_external_request("memory_control"))
                readonly_memory = ReadOnlyRetrieval(readonly, capacity.text_tokens, policy,
                    material_limit=settings["ordinary_material_tokens"],
                    read_limit=settings["additional_reads"],
                    control_steps=control.get("max_control_steps", 8),
                    source_top_k=settings["source_top_k"],
                    semantic_top_k=settings["semantic_top_k"],
                    view_capacity=control.get("view_capacity", 1),
                    source_observation_tokens=control.get("source_observation_tokens"),
                    record=trace, rank_pool=rank_pool,
                    available=lambda: host.calls_in_message < settings["max_calls_per_message"] - 2)
                hook = StateReadOnlyMemoryHook(readonly_memory, session="state-task", now=task.now,
                    domain=domain.name, user_id=task.user_id, record=trace)
            # The evaluator-only summary/requirements never enter this public context.
            runtime = AgentRuntimeContext(task_id="state-task", user_id=task.user_id,
                                          domain=domain.name, now=task.now)
            environment = domain.environment_class(env_data.deep_copy(), now=task.now)
            host_frame: dict[str, Any] = {}
            frame_number = 0

            def observe_host(frame: dict[str, Any]) -> None:
                nonlocal frame_number
                frame_number += 1
                host_frame.clear()
                host_frame.update(frame, frame_number=frame_number, memory_calls_before=hook.calls)
                if args.retrieval_snapshots:
                    write_json(args.output / "host-frames" / f"frame-{frame_number:04d}.json",
                               host_frame)

            if args.retrieval_snapshots:
                assert isinstance(hook, StateMemoryHook)
                capture_state_retrieval(hook, args.output,
                    domain_snapshot=environment.get_full_snapshot,
                    context=lambda: {"host_frame": host_frame,
                        "generation_calls_before": host.calls_in_message,
                        "source_version": args.source_version, "settings": settings,
                        "source_selection": selection, "trace_path": str(trace.path.resolve())})
            agent = make_state_agent(host, hook, runtime,
                initial_retrieval=initial["arguments"] if initial else None,
                observe_host=observe_host)
            run["state_snapshot_files"] = [
                "state-before.json", "state-after.json", "state-diff.json"]
            trajectory = run_with_domain_snapshots(environment, args.output, lambda: run_task(
                task=task, env_data=env_data, user_id=task.user_id, env=environment,
                # Upstream annotates concrete clients; this local adapter implements complete_chat.
                client=None, simulator_client=cast(Any, simulator), domain=domain, agent=agent,
                trajectory_metadata={"research_variant": True, "official_protocol": False}))
            write_json(args.output / "trajectory.json", trajectory.to_dict())
            hook.bind_conversation(trajectory.conversation)
            write_json(args.output / "memory-sources.json", service.sources())
            state_score = evaluate_state_requirements(task, trajectory.state_diff)
            write_json(args.output / "deterministic-state-score.json",
                       state_score.to_dict() if state_score is not None else None)
            run.update(status="COMPLETED_RESEARCH_TRAJECTORY", memory_calls=hook.calls,
                       simulator_calls=simulator.calls,
                       state_changed=not trajectory.state_diff.is_empty(),
                       deterministic_state_score=(state_score.score if state_score else None))
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
                       compute=measures,
                       whole_driver_cpu_seconds=whole_cpu,
                       nested_cpu_seconds_already_billed=direct_cpu,
                       peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
