"""One training-side STATE research run with the existing local Host and MiLAi.

Uses the public orchestrator directly, not the official CLI/protocol or its hash
validation. Domain tools/prompts remain upstream; local Host/simulator, JSON-action
transport and raw historical evidence are explicit research-variant choices.
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
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
from milai_lab.memory.service import MemoryService
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.memory_control import FixedContextMemoryPolicy
from milai_lab.providers.chat_bridge import VLLMChatModel
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.functional import seed_sources
from milai_lab.runners.state_bench_adapter import StateMemoryHook, make_state_agent


class LocalSimulator:
    """Keep upstream simulator prompts and use the accounted JSON-action bridge."""

    def __init__(self, model: VLLMChatModel) -> None:
        self.model = model
        self.calls = 0

    def complete_chat(self, *, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        self.model.begin_public_message(f"simulator-{self.calls}")
        result = self.model.invoke([
            SystemMessage(content=messages[0]["content"]),
            HumanMessage(content=messages[1]["content"])])
        return str(result.content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("preparation", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
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
    if selection["task_id"] not in split["splits"]["train"]:
        raise ValueError("This functional pilot admits only an explicitly selected training task")
    task = TaskDefinition.load(source / "state_bench/domains" / domain.name / "tasks"
                               / (selection["task_id"] + ".json"))
    env_data, env_path = load_task_environment(domain, task)
    settings = read_json(args.config)["entrypoints"]["functional"]
    host_config = VLLMConfig(**settings["host"])
    args.output.mkdir(parents=True, exist_ok=False)
    trace = Trace(args.output / "trace.jsonl", "state_local_research_v1")
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": args.source_version, "task_id": task.task_id,
        "split": "train", "domain": domain.name, "runs": 1, "official_protocol": False,
        "automatic_retry": False, "sha_validation_executed": False,
        "environment_file": str(env_path), "source_selection": selection,
        "host_and_simulator": asdict(host_config), "judge": "NOT_RUN",
        "memory_policy": "fixed_context", "return_envelope": "at most3strings; one full receipt",
        "max_return_tokens": settings["ordinary_material_tokens"],
        "monetary_cost": "Not priced; upstream default USD fields are not observed zero cost.",
        "scope": "Functional integration only. Local Qwen Host/simulator, JSON-action transport, "
                 "historical evidence from two other public training trajectories; no official "
                 "five-run score, learned-policy comparison or LLM task/UX judge."}
    write_json(args.output / "run.json", run)
    started, cpu = time.perf_counter(), time.process_time()
    with ExitStack() as stack:
        budget = stack.enter_context(http_budget_scope(
            settings, client_configs=[asdict(host_config)]))
        assert budget is not None
        before = copy.deepcopy(budget.state)
        try:
            capacity = HostCapacity(settings["capacity"])
            client = stack.enter_context(VLLMClient(host_config, emit=trace, budget=budget,
                                                   capacity=capacity))
            host = VLLMChatModel(client=client,
                                max_calls_per_message=settings["max_calls_per_message"])
            simulator = LocalSimulator(VLLMChatModel(client=client, max_calls_per_message=1))
            store = stack.enter_context(TransactionalSqliteStore.from_conn_string(
                str(args.output / "memory.sqlite")))
            owner = "state-public-training-corpus"
            service = MemoryService(store, ("state-research", "pilot", owner), owner,
                args.output / "memory.lock", functional_contract="functional_v1",
                memory_profile="unified_v1", memory_ranking="activation")
            run["source_import_receipts"] = seed_sources(service,
                read_json(args.preparation / "sources.json"), args.output / "source-imports.json",
                preserve_occurrence=True)
            memory = IntentRetrievalMemory(service, capacity.text_tokens,
                material_limit=settings["ordinary_material_tokens"],
                read_limit=settings["additional_reads"], source_access="independent_v1",
                source_tokenization="unicode_v1", evidence_policy="question_pack_v1",
                source_top_k=settings["source_top_k"], semantic_top_k=settings["semantic_top_k"],
                control_policy=FixedContextMemoryPolicy(reads=4), control_steps=8,
                control_delivery_selection=True, control_record=trace)
            hook = StateMemoryHook(memory, session="state-task", now=task.now, domain=domain.name,
                user_id=task.user_id, config_version=args.source_version, record=trace)
            # The evaluator-only summary/requirements never enter this public context.
            runtime = AgentRuntimeContext(task_id="state-task", user_id=task.user_id,
                                          domain=domain.name, now=task.now)
            agent = make_state_agent(host, hook, runtime)
            trajectory = run_task(task=task, env_data=env_data, user_id=task.user_id,
                client=None, simulator_client=simulator, domain=domain, agent=agent,
                trajectory_metadata={"research_variant": True, "official_protocol": False})
            write_json(args.output / "trajectory.json", trajectory.to_dict())
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
            measures = {"wall_seconds": time.perf_counter() - started,
                        "cpu_seconds": time.process_time() - cpu, "runs": 1}
            budget.record_compute("host_intent_view_v4_state_local_travel_pilot_v1", measures)
            run.update(budget_before=before, budget_after=copy.deepcopy(budget.state),
                       compute=measures,
                       peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
