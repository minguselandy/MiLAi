"""Run frozen single-arc MERIT comparisons with the existing LangMem runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_agent import VLLMEmbeddings, open_persistent_state
from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import ObservedStore, RevisionSidecar
from milai_lab.datasets.merit import load_frozen_arc
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
    SER_V23_PRE_REGISTRATION,
    verify_ser_v23_lock,
    verify_ser_v23_prepared,
)
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_merit import run_frozen_merit_arc
from run_langmem_provenance import _trace_emit

ARMS = ("b1_control", "a3_exact_refresh", "a4_selective_rebase")


def projection_for_arm(observer: ProvenanceObserver, emit: Any, store: ObservedStore,
                       arm: str) -> ProjectionController | None:
    if arm == "b1_control":
        return None
    return ProjectionController(
        observer, emit, arm=arm, store=store, stage="v21",
        refresh_until_current_candidate=False, max_exact_refresh_per_search=None)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    verify_ser_v23_lock(args.lock, args.config)
    freeze = read_json(args.freeze)
    pre_registration = read_json(SER_V23_PRE_REGISTRATION)
    selection, arc, _, _, _ = load_frozen_arc(args.selection)
    selection_sha = sha256_file(args.selection)
    pre_registration_sha = sha256_file(SER_V23_PRE_REGISTRATION)
    if (freeze["kind"] != "MILAI_SER_V23_ARC_FREEZE"
            or (LAB / freeze["selection_path"]).resolve() != args.selection.resolve()
            or freeze["selection_sha256"] != selection_sha
            or freeze["arc_sha256"] != selection["private_artifacts"]["arc_sha256"]
            or freeze["world_sha256"] != selection["private_artifacts"][
                "initial_world_sha256"]
            or freeze["arc_id"] != arc.arc_id
            or freeze["episode_count"] != len(arc.episodes)
            or freeze["dependent_episode_count"] != sum(
                episode.task.dependent for episode in arc.episodes)
            or freeze["public_messages"] != sum(
                len(episode.task.user_messages) for episode in arc.episodes)
            or (LAB / freeze["pre_registration_path"]).resolve()
            != SER_V23_PRE_REGISTRATION
            or freeze["pre_registration_sha256"] != pre_registration_sha
            or selection["generator_arguments"] not in pre_registration[
                "generator_arguments"]
            or selection["source_sha256"] != pre_registration["source_sha256"]
            or selection["source_commit"] != pre_registration["source_commit"]
            or freeze["unseen_at_selection"] is not True):
        raise ValueError("SER_V23_FROZEN_ARC_CHANGED")
    receipt = {"status": "PREPARED_ZERO_MODEL", "method": "ser_v23",
               "run_id": args.run, "arm_id": args.arm,
               "lock_sha256": sha256_file(args.lock),
               "config_sha256": sha256_file(args.config),
               "selection_sha256": selection_sha,
               "freeze_sha256": sha256_file(args.freeze),
               "pre_registration_sha256": pre_registration_sha,
               "arc_id": arc.arc_id,
               "arc_sha256": freeze["arc_sha256"],
               "world_sha256": freeze["world_sha256"],
               "episodes": len(arc.episodes),
               "dependent_episodes": freeze["dependent_episode_count"],
               "public_messages": freeze["public_messages"],
               "rubric_read_by_runner": False}
    write_json(args.output, receipt)
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    lock_sha = verify_ser_v23_prepared(
        args.prepared, args.lock, args.config, run_id=args.run, arm_id=args.arm,
        selection_path=args.selection, freeze_path=args.freeze)
    config = read_json(args.config)
    marker_path = Path(config["checkpoint_path"]).parent / (
        "ser-v23-runtime-" + hashlib.sha256(
            f"{args.run}:{args.arm}".encode()).hexdigest() + ".json")
    marker = {"run_id": args.run, "arm_id": args.arm,
              "lock_sha256": lock_sha, "config_sha256": sha256_file(args.config),
              "prepared_sha256": sha256_file(args.prepared)}
    if marker_path.exists():
        if read_json(marker_path) != marker:
            raise ValueError("SER_V23_RUNTIME_IDENTITY_CHANGED")
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
    identity = {**config, "ser_v23_lock_sha256": lock_sha, "arm_id": args.arm}
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
                    projection = projection_for_arm(observer, emit, store, args.arm)
                    model = VLLMChatModel(
                        client=host, capacity_path=Path(config["message_capacity_path"]),
                        observer=observer, projection=projection)
                    return run_frozen_merit_arc(
                        args.selection, args.output, args.run, model, store, saver,
                        identity, {"method": "ser_v23", "lock_sha256": lock_sha,
                                   "freeze_sha256": sha256_file(args.freeze),
                                   "pre_registration_sha256": sha256_file(
                                       SER_V23_PRE_REGISTRATION)},
                        arm_id=args.arm, observer=observer,
                        continue_on_local_capacity=config["continue_on_local_capacity"])
    finally:
        sidecar.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path,
                          default=LAB / "configs/milai-ser-v23.json")
        item.add_argument("--lock", type=Path,
                          default=LAB / "data/locks/milai-ser-v23.lock.json")
        item.add_argument("--selection", type=Path, required=True)
        item.add_argument("--freeze", type=Path, required=True)
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--stage", required=True)
    args = parser.parse_args()
    result = prepare(args) if args.command == "prepare" else run(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
