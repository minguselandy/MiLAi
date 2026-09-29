"""Run the frozen Formation inputs with ordinary LangMem or native Mem0 memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from milai_lab.baselines.langmem_agent import VLLMEmbeddings, open_persistent_state
from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.memory.revision_store import ObservedStore, RevisionSidecar
from milai_lab.methods.freshness_projection.identity import LAB
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_diagnostic import run_frozen_diagnostics
from milai_lab.runners.mem0_identity import (
    INPUT_REFERENCE,
    MEM0_SOURCE_COMMIT,
    PROTOCOL_BY_ARM,
    verify_external_v26_lock,
    verify_external_v26_prepared,
)
from milai_lab.runners.mem0_native import Mem0NativeRuntime
from run_langmem_provenance import _trace_emit


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    verify_external_v26_lock(args.lock, args.config, arm_id=args.arm)
    reference = read_json(INPUT_REFERENCE)
    freeze = read_json(args.diagnostic_freeze)
    inputs = read_json(args.diagnostic_inputs)
    cases = inputs["cases"]
    sessions = sum(len(case["sessions"]) for case in cases)
    public_messages = sum(len(session["turns"]) for case in cases
                          for session in case["sessions"])
    if (sha256_file(args.diagnostic_inputs) != reference["inputs_sha256"]
            or sha256_file(args.diagnostic_freeze) != reference["diagnostic_freeze_sha256"]
            or freeze["inputs_file_sha256"] != reference["inputs_sha256"]
            or len(cases) != len(reference["cases"])
            or [case["id"] for case in cases] != reference["cases"]
            or sessions != reference["sessions_per_arm"]
            or public_messages != reference["public_messages_per_arm"]):
        raise ValueError("EXTERNAL_V26_INPUT_CHANGED")
    receipt = {
        "status": "PREPARED_ZERO_MODEL", "method": "external_memory_v26",
        "run_id": args.run, "arm_id": args.arm,
        "lock_sha256": sha256_file(args.lock),
        "config_sha256": sha256_file(args.config),
        "input_sha256": sha256_file(args.diagnostic_inputs),
        "diagnostic_freeze_sha256": sha256_file(args.diagnostic_freeze),
        "input_reference_sha256": sha256_file(INPUT_REFERENCE),
        "cases": len(cases), "sessions": sessions,
        "public_messages": public_messages, "rubric_read_by_runner": False,
    }
    write_json(args.output, receipt)
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    lock_sha = verify_external_v26_prepared(
        args.prepared, args.lock, args.config, run_id=args.run,
        arm_id=args.arm, inputs_path=args.diagnostic_inputs,
        diagnostic_freeze=args.diagnostic_freeze)
    config = read_json(args.config)
    if Path(sys.prefix).resolve() != (LAB / config["mem0_environment"]["venv_path"]).resolve():
        raise ValueError("EXTERNAL_V26_ENVIRONMENT_CHANGED")
    os.environ["FASTEMBED_CACHE_PATH"] = str(
        (LAB / config["mem0_environment"]["fastembed_cache_path"]).resolve())
    marker_path = Path(config["checkpoint_path"]).parent / (
        "external-v26-runtime-" + hashlib.sha256(
            f"{args.run}:{args.arm}".encode()).hexdigest() + ".json")
    marker = {"run_id": args.run, "arm_id": args.arm,
              "lock_sha256": lock_sha,
              "config_sha256": sha256_file(args.config),
              "prepared_sha256": sha256_file(args.prepared),
              "mem0_source_commit": MEM0_SOURCE_COMMIT}
    if marker_path.exists():
        if read_json(marker_path) != marker:
            raise ValueError("EXTERNAL_V26_RUNTIME_IDENTITY_CHANGED")
    else:
        write_json(marker_path, marker)
    budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
                                 generation_tokens=None, embedding_tokens=None),
                       Path(config["budget_path"]))
    trace = Trace(Path(config["trace_path"]), args.stage)
    host_config = VLLMConfig(**config["host"])
    embed_config = VLLMConfig(base_url=config["embedding"]["base_url"],
                              model=config["embedding"]["model"],
                              timeout=config["embedding"].get("timeout", 180))
    identity = {**config, "external_v26_lock_sha256": lock_sha,
                "arm_id": args.arm, "protocol_id": PROTOCOL_BY_ARM[args.arm]}
    selected = set(args.case) if args.case else None
    if args.arm == "b1_control":
        sidecar = RevisionSidecar(Path(config["sidecar_path"]))
        observer = ProvenanceObserver(sidecar, args.run, args.arm)
        emit = _trace_emit(trace, observer)
        try:
            with VLLMClient(host_config, emit=emit, budget=budget,
                            capacity=HostCapacity(config["capacity"])) as host:
                with VLLMClient(embed_config, emit=trace, budget=budget) as embed:
                    with open_persistent_state(
                        os.environ["MILAI_LANGMEM_POSTGRES_DSN"],
                        Path(config["checkpoint_path"]),
                        VLLMEmbeddings(embed, embed_config.model),
                        embedding_dimensions=config["embedding_dimension"],
                    ) as (base_store, saver):
                        model = VLLMChatModel(
                            client=host, capacity_path=Path(config["message_capacity_path"]),
                            observer=observer)
                        return run_frozen_diagnostics(
                            args.diagnostic_inputs, args.diagnostic_freeze,
                            args.output, args.run, model,
                            ObservedStore(base_store, observer), saver, identity,
                            selected_cases=selected, arm_id=args.arm,
                            observer=observer, protocol_id=PROTOCOL_BY_ARM[args.arm])
        finally:
            sidecar.close()
    with VLLMClient(host_config, emit=trace, budget=budget,
                    capacity=HostCapacity(config["capacity"])) as host:
        with VLLMClient(embed_config, emit=trace, budget=budget) as embed:
            checkpoint = Path(config["checkpoint_path"])
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
                runtime = Mem0NativeRuntime(
                    LAB / config["mem0_runtime_root"] / args.run,
                    args.run, args.arm, host, embed)
                try:
                    model = VLLMChatModel(
                        client=host, capacity_path=Path(config["message_capacity_path"]))
                    return run_frozen_diagnostics(
                        args.diagnostic_inputs, args.diagnostic_freeze,
                        args.output, args.run, model, None, saver, identity,
                        selected_cases=selected, arm_id=args.arm,
                        protocol_id=PROTOCOL_BY_ARM[args.arm],
                        external_memory=runtime)
                finally:
                    runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path,
                          default=LAB / "configs/milai-external-memory-v26.json")
        item.add_argument("--lock", type=Path,
                          default=LAB / "data/locks/milai-external-memory-v26.lock.json")
        item.add_argument("--diagnostic-inputs", type=Path,
                          default=LAB /
                          "data/diagnostics/milai-lifecycle-v24-formation-inputs.json")
        item.add_argument("--diagnostic-freeze", type=Path,
                          default=LAB /
                          "data/manifests/milai-lifecycle-v24-formation-diagnostic-freeze.json")
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=tuple(PROTOCOL_BY_ARM), required=True)
        item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--stage", required=True)
            item.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    result = prepare(args) if args.command == "prepare" else run(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
