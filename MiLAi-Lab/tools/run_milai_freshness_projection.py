"""Prepare, inspect and run the staged freshness-projection mechanism controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

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
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.methods.freshness_projection.controller import ARMS, ProjectionController
from milai_lab.methods.freshness_projection.identity import (
    LAB,
    verify_lock,
    verify_prepared,
)
from milai_lab.methods.freshness_projection.projection import SOURCE_AUTHORITY
from milai_lab.methods.on_demand_reconstruction.controller import ODRController
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel, _action_prompt, _action_schema
from milai_lab.runners.langmem_projection_mechanism import run_mechanism
from run_langmem_provenance import _trace_emit


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    verify_lock(args.lock, args.config, args.arm)
    fixture, freeze = read_json(args.fixture), read_json(args.mechanism_freeze)
    if (fixture["kind"] != "ODR_V19_REVISION_DIAGNOSTIC"
            or sha256_file(args.fixture) != freeze["fixture_sha256"]
            or fixture["case_id"] != freeze["case_id"]
            or len(fixture["public_messages"]) != freeze["public_messages"]):
        raise ValueError("PROJECTION_MECHANISM_FIXTURE_CHANGED")
    receipt = {"status": "PREPARED_ZERO_MODEL", "method": "freshness_projection",
               "run_id": args.run, "arm_id": args.arm, "mode": "mechanism",
               "lock_sha256": sha256_file(args.lock),
               "config_sha256": sha256_file(args.config),
               "fixture_sha256": sha256_file(args.fixture),
               "freeze_sha256": sha256_file(args.mechanism_freeze),
               "rubric_read_by_runner": False}
    write_json(args.output, receipt)
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    lock_sha = verify_prepared(args.prepared, args.lock, args.config,
                               run_id=args.run, arm_id=args.arm,
                               fixture_path=args.fixture)
    if read_json(args.prepared)["freeze_sha256"] != sha256_file(args.mechanism_freeze):
        raise ValueError("PROJECTION_PREPARED_FREEZE_CHANGED")
    config = read_json(args.config)
    marker_path = Path(config["checkpoint_path"]).parent / (
        "projection-runtime-" + hashlib.sha256(
            f"{args.run}:{args.arm}".encode()).hexdigest() + ".json")
    marker = {"run_id": args.run, "arm_id": args.arm,
              "lock_sha256": lock_sha, "config_sha256": sha256_file(args.config),
              "prepared_sha256": sha256_file(args.prepared)}
    if marker_path.exists():
        if read_json(marker_path) != marker:
            raise ValueError("PROJECTION_RUNTIME_IDENTITY_CHANGED")
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
                    notice = (ODRController(observer, "freshness_only",
                                            Path(config["trace_path"]))
                              if args.arm == "a1_notice" else None)
                    projection = (ProjectionController(observer, emit,
                                                      arm=args.arm, store=store)
                                  if args.arm in {"a2_quarantine", "a3_exact_refresh"}
                                  else None)
                    model = VLLMChatModel(
                        client=host, capacity_path=Path(config["message_capacity_path"]),
                        observer=observer, odr=notice, projection=projection,
                    )
                    return run_mechanism(args.fixture, args.mechanism_freeze,
                                         args.output, args.run, args.arm, model,
                                         store, saver, observer)
    finally:
        sidecar.close()


def schema(fixture_path: Path | None, arm: str) -> dict[str, Any]:
    tools = [convert_to_openai_tool(create_manage_memory_tool(namespace=MEMORY_NAMESPACE)),
             convert_to_openai_tool(create_search_memory_tool(namespace=MEMORY_NAMESPACE))]
    if fixture_path is not None:
        tools.append(read_json(fixture_path)["business_tool_schema"])
    protocol = _action_prompt(tools)
    if arm in {"a2_quarantine", "a3_exact_refresh"}:
        protocol += "\n" + SOURCE_AUTHORITY
    return {"schema": _action_schema(tools, generation_only=True),
            "protocol": protocol, "arm_id": arm,
            "tool_names": [tool["function"]["name"] for tool in tools]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path,
                          default=LAB / "configs/milai-freshness-projection-v19.json")
        item.add_argument("--lock", type=Path)
        item.add_argument("--mode", choices=("mechanism",), default="mechanism")
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--fixture", type=Path, required=True)
        item.add_argument("--mechanism-freeze", type=Path, required=True)
        item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--stage", required=True)
    spec = commands.add_parser("schema")
    spec.add_argument("--fixture", type=Path)
    spec.add_argument("--arm", choices=ARMS, default="a2_quarantine")
    args = parser.parse_args()
    if args.command in {"prepare", "run"} and args.lock is None:
        stage = "a3" if args.arm == "a3_exact_refresh" else "a2"
        args.lock = LAB / f"data/locks/milai-freshness-projection-v19-{stage}.lock.json"
    result = (schema(args.fixture, args.arm) if args.command == "schema" else
              prepare(args) if args.command == "prepare" else run(args))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
