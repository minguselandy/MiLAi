"""Prepare and run the three v19 arms on the existing LangMem ReAct loop."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

from langchain_core.utils.function_calling import convert_to_openai_tool
from langmem import (  # type: ignore[import-untyped]
    create_manage_memory_tool,
    create_search_memory_tool,
)

from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    VLLMEmbeddings,
    open_persistent_state,
)
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
from milai_lab.methods.on_demand_reconstruction.controller import ARMS, ODRController
from milai_lab.methods.on_demand_reconstruction.identity import (
    LAB,
    verify_odr_lock,
    verify_odr_prepared,
)
from milai_lab.methods.on_demand_reconstruction.schema import ODR_PROTOCOL, odr_action_schema
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel, _action_prompt, _action_schema
from milai_lab.runners.langmem_diagnostic import run_frozen_diagnostics
from milai_lab.runners.langmem_merit import run_exposed_merit_arc
from milai_lab.runners.langmem_odr_mechanism import run_mechanism
from run_langmem_provenance import _trace_emit


def _input(args: argparse.Namespace) -> Path:
    return cast(Path, {"mechanism": args.fixture, "diagnostic": args.diagnostic_inputs,
                       "merit": args.merit_selection}[args.mode])


def _freeze(args: argparse.Namespace) -> Path | None:
    return cast(Path | None, {"mechanism": args.mechanism_freeze,
                              "diagnostic": args.diagnostic_freeze,
                              "merit": None}[args.mode])


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    verify_odr_lock(args.lock, args.config)
    input_path = _input(args)
    receipt = {"status": "PREPARED_ZERO_MODEL", "method": "odr",
               "arm_id": args.arm, "run_id": args.run, "mode": args.mode,
               "lock_sha256": sha256_file(args.lock),
               "config_sha256": sha256_file(args.config),
               "input_sha256": sha256_file(input_path)}
    freeze_path = _freeze(args)
    if freeze_path is not None:
        freeze = read_json(freeze_path)
        expected = (freeze["fixture_sha256"] if args.mode == "mechanism"
                    else freeze["inputs_file_sha256"])
        if sha256_file(input_path) != expected:
            raise ValueError("ODR_INPUT_FREEZE_CHANGED")
        if args.mode == "mechanism":
            fixture = read_json(input_path)
            if fixture["kind"] != "ODR_V19_REVISION_DIAGNOSTIC":
                raise ValueError("ODR_MECHANISM_KIND_INVALID")
            if len(fixture["public_messages"]) != freeze["public_messages"]:
                raise ValueError("ODR_MECHANISM_MESSAGE_COUNT_CHANGED")
        else:
            if len(read_json(input_path)["cases"]) != freeze["cases"]:
                raise ValueError("ODR_DIAGNOSTIC_CASE_COUNT_CHANGED")
        receipt["freeze_sha256"] = sha256_file(freeze_path)
    if args.mode in {"diagnostic", "merit"}:
        exposed = read_json(args.exposed_freeze)[args.mode]
        if args.mode == "diagnostic":
            if (exposed["inputs_sha256"] != sha256_file(input_path)
                    or exposed["freeze_sha256"] != sha256_file(args.diagnostic_freeze)):
                raise ValueError("ODR_EXPOSED_DIAGNOSTIC_CHANGED")
        else:
            selection, arc, _, _, _ = load_exposed_arc(input_path)
            if (exposed["selection_sha256"] != sha256_file(input_path)
                    or exposed["arc_sha256"] != selection["private_artifacts"]["arc_sha256"]
                    or exposed["episodes"] != len(arc.episodes)):
                raise ValueError("ODR_EXPOSED_MERIT_CHANGED")
        receipt["exposed_freeze_sha256"] = sha256_file(args.exposed_freeze)
    receipt["rubric_read_by_runner"] = False
    write_json(args.output, receipt)
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = _input(args)
    lock_sha = verify_odr_prepared(args.prepared, args.lock, args.config,
                                   arm_id=args.arm, run_id=args.run, input_path=input_path)
    receipt = read_json(args.prepared)
    freeze_path = _freeze(args)
    if freeze_path is not None and receipt.get("freeze_sha256") != sha256_file(freeze_path):
        raise ValueError("ODR_PREPARED_FREEZE_CHANGED")
    if (args.mode in {"diagnostic", "merit"}
            and receipt.get("exposed_freeze_sha256") != sha256_file(args.exposed_freeze)):
        raise ValueError("ODR_PREPARED_EXPOSED_CHANGED")
    config = read_json(args.config)
    marker_path = Path(config["checkpoint_path"]).parent / (
        "odr-runtime-" + hashlib.sha256(f"{args.run}:{args.arm}".encode()).hexdigest() + ".json")
    marker = {"run_id": args.run, "arm_id": args.arm, "lock_sha256": lock_sha,
              "config_sha256": sha256_file(args.config),
              "prepared_sha256": sha256_file(args.prepared)}
    if marker_path.exists():
        if read_json(marker_path) != marker:
            raise ValueError("ODR_RUNTIME_IDENTITY_CHANGED")
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
    identity = {**config, "odr_lock_sha256": lock_sha, "arm_id": args.arm}
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
                    controller = (ODRController(observer, args.arm,
                                                Path(config["reconstruction_trace_path"]))
                                  if args.arm != "b1_control" else None)
                    model = VLLMChatModel(
                        client=host, capacity_path=Path(config["message_capacity_path"]),
                        observer=observer, odr=controller,
                    )
                    if args.mode == "mechanism":
                        return run_mechanism(input_path, args.mechanism_freeze,
                                             args.output, args.run, args.arm, model,
                                             store, saver, observer)
                    if args.mode == "diagnostic":
                        return run_frozen_diagnostics(
                            input_path, args.diagnostic_freeze, args.output,
                            args.run, model, store, saver, identity,
                            selected_cases=set(args.case) if args.case else None,
                            arm_id=args.arm, observer=observer)
                    return run_exposed_merit_arc(input_path, args.output, args.run,
                                                 model, store, saver, identity,
                                                 arm_id=args.arm, observer=observer)
    finally:
        sidecar.close()


def schema(fixture_path: Path | None, arm: str) -> dict[str, Any]:
    tools = [convert_to_openai_tool(create_manage_memory_tool(namespace=MEMORY_NAMESPACE)),
             convert_to_openai_tool(create_search_memory_tool(namespace=MEMORY_NAMESPACE))]
    if fixture_path is not None:
        tools.append(read_json(fixture_path)["business_tool_schema"])
    action = _action_schema(tools, generation_only=True)
    protocol = _action_prompt(tools)
    if arm == "odr":
        action = odr_action_schema(action)
        protocol += "\n" + ODR_PROTOCOL
    return {"schema": action, "protocol": protocol,
            "tool_names": [tool["function"]["name"] for tool in tools],
            "arm_id": arm}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path, default=LAB / "configs/milai-odr-v19.json")
        item.add_argument("--lock", type=Path,
                          default=LAB / "data/locks/milai-odr-v19.lock.json")
        item.add_argument("--mode", choices=("mechanism", "diagnostic", "merit"), required=True)
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--output", type=Path, required=True)
        item.add_argument("--fixture", type=Path)
        item.add_argument("--mechanism-freeze", type=Path)
        item.add_argument("--diagnostic-inputs", type=Path)
        item.add_argument("--diagnostic-freeze", type=Path)
        item.add_argument("--merit-selection", type=Path)
        item.add_argument("--exposed-freeze", type=Path,
                          default=LAB / "data/manifests/milai-odr-v19-exposed-freeze.json")
        if command == "run":
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--stage", required=True)
            item.add_argument("--case", action="append", default=[])
    spec = commands.add_parser("schema")
    spec.add_argument("--fixture", type=Path)
    spec.add_argument("--arm", choices=ARMS, default="odr")
    args = parser.parse_args()
    if args.command == "schema":
        result = schema(args.fixture, args.arm)
    else:
        if any(value is None for value in ({"mechanism": (args.fixture, args.mechanism_freeze),
                                            "diagnostic": (args.diagnostic_inputs,
                                                           args.diagnostic_freeze),
                                            "merit": (args.merit_selection,)}[args.mode])):
            parser.error("selected mode requires its input and freeze")
        result = prepare(args) if args.command == "prepare" else run(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
