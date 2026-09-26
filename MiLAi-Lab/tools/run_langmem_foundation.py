"""Persistent LangMem foundation CLI for spike, MERIT and diagnostic runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from milai_lab.baselines.langmem_agent import (
    FoundationScope,
    VLLMEmbeddings,
    build_agent,
    invoke_public_message,
    open_persistent_state,
    resume_public_message,
)
from milai_lab.baselines.langmem_identity import sha256_file, verify_prepared_run
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_diagnostic import run_frozen_diagnostics
from milai_lab.runners.langmem_foundation import BusinessActionJournal
from milai_lab.runners.langmem_merit import run_exposed_merit_arc

LAB = Path(__file__).resolve().parents[1]


def _verify_development_spike(config_path: Path, config: dict[str, Any], run: str) -> None:
    identity_path = (Path(config["checkpoint_path"]).parent
                     / f"spike-identity-{hashlib.sha256(run.encode()).hexdigest()}.json")
    identity = {
        "status": "DEVELOPMENT_SPIKE",
        "run_id": run,
        "config_sha256": sha256_file(config_path),
        "source_sha256": {
            relative: sha256_file(LAB / relative) for relative in (
                "src/milai_lab/baselines/langmem_agent.py",
                "src/milai_lab/providers/langmem_chat.py",
                "src/milai_lab/runners/langmem_foundation.py",
                "tools/run_langmem_foundation.py",
            )
        },
    }
    if identity_path.exists():
        if read_json(identity_path) != identity:
            raise ValueError("DEVELOPMENT_SPIKE_IDENTITY_CHANGED")
    else:
        write_json(identity_path, identity)


def _spike_tool(path: Path) -> Any:
    @tool
    def record_spike_action(value: str) -> str:
        """Record a requested test action in the isolated spike world and return its receipt."""
        state = json.loads(path.read_text()) if path.exists() else {"actions": []}
        action = {"value": value, "sequence": len(state["actions"]) + 1}
        state["actions"].append(action)
        write_json(path, state)
        return json.dumps(action, ensure_ascii=False)

    return record_spike_action


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--lock", type=Path,
                        default=LAB / "data/locks/langmem-foundation.lock.json")
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--arm", default="b0")
    parser.add_argument("--user")
    parser.add_argument("--episode")
    parser.add_argument("--message")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--merit-selection", type=Path)
    parser.add_argument("--diagnostic-inputs", type=Path)
    parser.add_argument("--diagnostic-freeze", type=Path)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    if args.merit_selection is not None and args.diagnostic_inputs is not None:
        parser.error("choose one formal run: MERIT or diagnostic")
    formal = args.merit_selection is not None or args.diagnostic_inputs is not None
    if formal:
        if args.prepared is None or args.output is None:
            parser.error("formal runs require --prepared and --output")
        if args.diagnostic_inputs is not None and args.diagnostic_freeze is None:
            parser.error("diagnostic requires --diagnostic-freeze")
        lock_sha256 = verify_prepared_run(
            args.prepared, args.lock, args.config,
            merit_selection=args.merit_selection,
            diagnostic_inputs=args.diagnostic_inputs,
        )
        runtime_identity = {**config, "foundation_lock_sha256": lock_sha256}
    else:
        _verify_development_spike(args.config, config, args.run)
        runtime_identity = config
    dsn = os.environ["MILAI_LANGMEM_POSTGRES_DSN"]
    budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
                                 generation_tokens=None, embedding_tokens=None),
                       Path(config["budget_path"]))
    trace = Trace(Path(config["trace_path"]), args.stage)
    host_config = VLLMConfig(**config["host"])
    embed_config = VLLMConfig(
        base_url=config["embedding"]["base_url"],
        model=config["embedding"]["model"],
        timeout=config["embedding"].get("timeout", 180),
    )
    capacity = HostCapacity(config["capacity"])
    with VLLMClient(host_config, emit=trace, budget=budget, capacity=capacity) as host_client:
        with VLLMClient(embed_config, emit=trace, budget=budget) as embed_client:
            embeddings = VLLMEmbeddings(embed_client, embed_config.model)
            with open_persistent_state(
                dsn,
                Path(config["checkpoint_path"]),
                embeddings,
                embedding_dimensions=config["embedding_dimension"],
            ) as (store, saver):
                model = VLLMChatModel(
                    client=host_client,
                    capacity_path=Path(config["message_capacity_path"]),
                )
                if args.merit_selection is not None:
                    if args.output is None:
                        parser.error("--output is required with --merit-selection")
                    result = run_exposed_merit_arc(
                        args.merit_selection, args.output, args.run,
                        model, store, saver, runtime_identity,
                    )
                    print(json.dumps(result, ensure_ascii=False))
                elif args.diagnostic_inputs is not None:
                    if args.output is None or args.diagnostic_freeze is None:
                        parser.error("diagnostic requires --output and --diagnostic-freeze")
                    result = run_frozen_diagnostics(
                        args.diagnostic_inputs, args.diagnostic_freeze,
                        args.output, args.run, model, store, saver, runtime_identity,
                        selected_cases=set(args.case) if args.case else None,
                    )
                    print(json.dumps(result, ensure_ascii=False))
                else:
                    if (not args.user or not args.episode or args.result is None
                            or (not args.resume and args.message is None)):
                        parser.error(
                            "spike requires --user, --episode, --result, "
                            "and --message unless --resume"
                        )
                    tools = [_spike_tool(Path(config["spike_world_path"]))]
                    journal = BusinessActionJournal(
                        Path(config["business_journal_path"]), [tool.name for tool in tools],
                    )
                    agent = build_agent(model, store, saver, tools,
                                        business_call_wrapper=journal)
                    scope = FoundationScope(args.run, args.arm, args.user, args.episode)
                    messages = (resume_public_message(agent, model, scope) if args.resume
                                else invoke_public_message(agent, model, scope, args.message))
                    write_json(args.result, {
                        "scope": {"run": args.run, "arm": args.arm, "user": args.user,
                                  "episode": args.episode},
                        "stage": args.stage,
                        "messages": [message.model_dump(mode="json") for message in messages],
                        "budget": budget.state,
                    })
                    print(messages[-1].content)


if __name__ == "__main__":
    main()
