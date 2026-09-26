"""Run the exposed LangMem controls with B1 or the frozen SER projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

from milai_lab.baselines.langmem_agent import VLLMEmbeddings, open_persistent_state
from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import ObservedStore, RevisionSidecar
from milai_lab.datasets.merit import load_exposed_arc
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.methods.freshness_projection.controller import ProjectionController
from milai_lab.methods.freshness_projection.identity import (
    LAB,
    verify_ser_v22_lock,
    verify_ser_v22_prepared,
)
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_diagnostic import run_frozen_diagnostics
from milai_lab.runners.langmem_merit import run_exposed_merit_arc
from run_langmem_provenance import _trace_emit

ARMS = ("b1_control", "a5_rank_bounded_rebase")


def _input(args: argparse.Namespace) -> Path:
    return cast(Path, args.diagnostic_inputs if args.mode == "diagnostic"
                else args.merit_selection)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    verify_ser_v22_lock(args.lock, args.config)
    input_path = _input(args)
    exposed = read_json(args.exposed_freeze)[args.mode]
    receipt = {"status": "PREPARED_ZERO_MODEL", "method": "ser_v22",
               "run_id": args.run, "arm_id": args.arm, "mode": args.mode,
               "lock_sha256": sha256_file(args.lock),
               "config_sha256": sha256_file(args.config),
               "input_sha256": sha256_file(input_path),
               "exposed_freeze_sha256": sha256_file(args.exposed_freeze),
               "rubric_read_by_runner": False}
    if args.mode == "diagnostic":
        freeze, inputs = read_json(args.diagnostic_freeze), read_json(input_path)
        cases = inputs["cases"]
        sessions = sum(len(case["sessions"]) for case in cases)
        public_messages = sum(len(session["turns"]) for case in cases
                              for session in case["sessions"])
        if (freeze["inputs_file_sha256"] != receipt["input_sha256"]
                or len(cases) != freeze["cases"]
                or receipt["input_sha256"] != exposed["inputs_sha256"]
                or sha256_file(args.diagnostic_freeze) != exposed["freeze_sha256"]
                or len(cases) != exposed["cases"] or sessions != exposed["sessions"]
                or public_messages != exposed["public_messages"]):
            raise ValueError("SER_V22_DIAGNOSTIC_INPUT_CHANGED")
        receipt["diagnostic_freeze_sha256"] = sha256_file(args.diagnostic_freeze)
        receipt["cases"] = len(cases)
        receipt["sessions"] = sessions
        receipt["public_messages"] = public_messages
    else:
        selection, arc, _, _, _ = load_exposed_arc(input_path)
        public_messages = sum(len(episode.task.user_messages) for episode in arc.episodes)
        dependent_episodes = sum(episode.task.dependent for episode in arc.episodes)
        if (receipt["input_sha256"] != exposed["selection_sha256"]
                or selection["private_artifacts"]["arc_sha256"] != exposed["arc_sha256"]
                or selection["private_artifacts"]["initial_world_sha256"]
                != exposed["world_sha256"]
                or arc.arc_id != exposed["arc_id"]
                or len(arc.episodes) != exposed["episodes"]
                or dependent_episodes != exposed["dependent_episodes"]
                or public_messages != exposed["public_messages"]):
            raise ValueError("SER_V22_MERIT_SELECTION_CHANGED")
        receipt["arc_sha256"] = exposed["arc_sha256"]
        receipt["episodes"] = len(arc.episodes)
        receipt["public_messages"] = public_messages
    write_json(args.output, receipt)
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = _input(args)
    lock_sha = verify_ser_v22_prepared(
        args.prepared, args.lock, args.config, run_id=args.run, arm_id=args.arm,
        mode=args.mode, input_path=input_path, exposed_freeze=args.exposed_freeze,
        diagnostic_freeze=args.diagnostic_freeze if args.mode == "diagnostic" else None)
    config = read_json(args.config)
    marker_path = Path(config["checkpoint_path"]).parent / (
        "ser-v22-runtime-" + hashlib.sha256(
            f"{args.run}:{args.arm}".encode()).hexdigest() + ".json")
    marker = {"run_id": args.run, "arm_id": args.arm,
              "lock_sha256": lock_sha, "config_sha256": sha256_file(args.config),
              "prepared_sha256": sha256_file(args.prepared)}
    if marker_path.exists():
        if read_json(marker_path) != marker:
            raise ValueError("SER_V22_RUNTIME_IDENTITY_CHANGED")
    else:
        write_json(marker_path, marker)
    budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
                                 generation_tokens=None, embedding_tokens=None),
                       Path(config["budget_path"]))
    trace = Trace(Path(config["trace_path"]), args.stage)
    sidecar = RevisionSidecar(Path(config["sidecar_path"]))
    observer = ProvenanceObserver(sidecar, args.run, args.arm)
    emit = _trace_emit(trace, observer)
    host_config = VLLMConfig(**config["host"])
    embed_config = VLLMConfig(base_url=config["embedding"]["base_url"],
                              model=config["embedding"]["model"],
                              timeout=config["embedding"].get("timeout", 180))
    identity = {**config, "ser_v22_lock_sha256": lock_sha, "arm_id": args.arm}
    try:
        observer.assert_healthy()
        with VLLMClient(host_config, emit=emit, budget=budget,
                        capacity=HostCapacity(config["capacity"])) as host:
            with VLLMClient(embed_config, emit=trace, budget=budget) as embed:
                embeddings = VLLMEmbeddings(embed, embed_config.model)
                with open_persistent_state(
                    os.environ["MILAI_LANGMEM_POSTGRES_DSN"],
                    Path(config["checkpoint_path"]), embeddings,
                    embedding_dimensions=config["embedding_dimension"],
                ) as (base_store, saver):
                    store = ObservedStore(base_store, observer)
                    policy = config["refresh_policy"]
                    projection = (ProjectionController(
                        observer, emit, arm=args.arm, store=store, stage="v21",
                        refresh_until_current_candidate=policy[
                            "refresh_until_current_candidate"],
                        max_exact_refresh_per_search=policy["max_exact_refresh_per_search"])
                        if args.arm == "a5_rank_bounded_rebase" else None)
                    model = VLLMChatModel(
                        client=host, capacity_path=Path(config["message_capacity_path"]),
                        observer=observer, projection=projection)
                    if args.mode == "diagnostic":
                        return run_frozen_diagnostics(
                            input_path, args.diagnostic_freeze, args.output,
                            args.run, model, store, saver, identity,
                            selected_cases=set(args.case) if args.case else None,
                            arm_id=args.arm, observer=observer)
                    return run_exposed_merit_arc(
                        input_path, args.output, args.run, model, store, saver,
                        identity, arm_id=args.arm, observer=observer,
                        continue_on_local_capacity=config.get(
                            "continue_on_local_capacity", False))
    finally:
        sidecar.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path,
                          default=LAB / "configs/milai-ser-v22-r2.json")
        item.add_argument("--lock", type=Path,
                          default=LAB / "data/locks/milai-ser-v22-p7r3.lock.json")
        item.add_argument("--mode", choices=("diagnostic", "merit"), required=True)
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--diagnostic-inputs", type=Path)
        item.add_argument("--diagnostic-freeze", type=Path)
        item.add_argument("--merit-selection", type=Path)
        item.add_argument("--exposed-freeze", type=Path, required=True)
        item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--stage", required=True)
            item.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    if args.mode == "diagnostic" and (args.diagnostic_inputs is None
                                      or args.diagnostic_freeze is None):
        parser.error("diagnostic requires --diagnostic-inputs and --diagnostic-freeze")
    if args.mode == "merit" and args.merit_selection is None:
        parser.error("merit requires --merit-selection")
    result = prepare(args) if args.command == "prepare" else run(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
