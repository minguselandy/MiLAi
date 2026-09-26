"""Prepare, run and inspect the opt-in v18 M1 pivot over the v16 foundation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
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
from milai_lab.methods.milai_m1.controller import (
    M1_PROTOCOL,
    M1Controller,
    m1_action_schema,
)
from milai_lab.methods.milai_m1.identity import (
    ARMS,
    LAB,
    verify_m1_lock,
    verify_m1_prepared,
)
from milai_lab.methods.milai_m1.state_store import DecisionBasisStore
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel, _action_prompt, _action_schema
from milai_lab.runners.langmem_diagnostic import run_frozen_diagnostics
from milai_lab.runners.langmem_merit import run_exposed_merit_arc
from run_langmem_provenance import _trace_emit


def _input_path(args: argparse.Namespace) -> Path:
    if args.mode == "diagnostic":
        return cast(Path, args.diagnostic_inputs)
    if args.mode == "merit":
        return cast(Path, args.merit_selection)
    return cast(Path, args.fixture)


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    verify_m1_lock(args.lock, args.config)
    input_path = _input_path(args)
    receipt = {
        "status": "PREPARED_ZERO_MODEL", "method": "m1",
        "arm_id": args.arm, "run_id": args.run, "mode": args.mode,
        "lock_sha256": sha256_file(args.lock),
        "config_sha256": sha256_file(args.config),
        "input_sha256": sha256_file(input_path),
    }
    if args.mode == "diagnostic":
        freeze, inputs = read_json(args.diagnostic_freeze), read_json(input_path)
        exposed = read_json(args.exposed_freeze)["diagnostic"]
        if sha256_file(input_path) != freeze["inputs_file_sha256"]:
            raise ValueError("M1_DIAGNOSTIC_INPUT_CHANGED")
        if len(inputs["cases"]) != freeze["cases"]:
            raise ValueError("M1_DIAGNOSTIC_COUNT_CHANGED")
        if (sha256_file(input_path) != exposed["inputs_sha256"]
                or sha256_file(args.diagnostic_freeze) != exposed["freeze_sha256"]
                or len(inputs["cases"]) != exposed["cases"]):
            raise ValueError("M1_EXPOSED_DIAGNOSTIC_CHANGED")
        receipt["freeze_sha256"] = sha256_file(args.diagnostic_freeze)
        receipt["exposed_freeze_sha256"] = sha256_file(args.exposed_freeze)
        receipt["rubric_read_by_runner"] = False
    elif args.mode == "merit":
        selection, arc, _, _, _ = load_exposed_arc(input_path)
        exposed = read_json(args.exposed_freeze)["merit"]
        if (sha256_file(input_path) != exposed["selection_sha256"]
                or selection["private_artifacts"]["arc_sha256"] != exposed["arc_sha256"]
                or len(arc.episodes) != exposed["episodes"]):
            raise ValueError("M1_EXPOSED_MERIT_CHANGED")
        receipt.update({"arc_id": arc.arc_id,
                        "arc_sha256": selection["private_artifacts"]["arc_sha256"],
                        "episodes": len(arc.episodes),
                        "exposed_freeze_sha256": sha256_file(args.exposed_freeze)})
    else:
        fixture, freeze = read_json(input_path), read_json(args.mechanism_freeze)
        if fixture.get("kind") != "M1_V18_RECHECK_DIAGNOSTIC":
            raise ValueError("M1_MECHANISM_KIND_INVALID")
        if sha256_file(input_path) != freeze["fixture_sha256"]:
            raise ValueError("M1_MECHANISM_FIXTURE_CHANGED")
        receipt.update({"freeze_sha256": sha256_file(args.mechanism_freeze),
                        "public_messages": len(fixture["public_messages"]),
                        "rubric_read_by_runner": False})
    write_json(args.output, receipt)
    return receipt


def _run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = _input_path(args)
    lock_sha = verify_m1_prepared(
        args.prepared, args.lock, args.config,
        arm_id=args.arm, run_id=args.run, input_path=input_path,
    )
    config = read_json(args.config)
    receipt = read_json(args.prepared)
    if args.mode in {"diagnostic", "mechanism"}:
        freeze_path = (args.diagnostic_freeze if args.mode == "diagnostic"
                       else args.mechanism_freeze)
        if receipt.get("freeze_sha256") != sha256_file(freeze_path):
            raise ValueError("M1_PREPARED_FREEZE_CHANGED")
    if (args.mode in {"diagnostic", "merit"}
            and receipt.get("exposed_freeze_sha256") != sha256_file(args.exposed_freeze)):
        raise ValueError("M1_PREPARED_EXPOSED_FREEZE_CHANGED")
    marker_path = Path(config["checkpoint_path"]).parent / (
        "m1-runtime-" + hashlib.sha256(f"{args.run}:{args.arm}".encode()).hexdigest() + ".json"
    )
    marker = {"run_id": args.run, "arm_id": args.arm,
              "lock_sha256": lock_sha, "config_sha256": sha256_file(args.config),
              "prepared_sha256": sha256_file(args.prepared)}
    if marker_path.exists():
        if read_json(marker_path) != marker:
            raise ValueError("M1_RUNTIME_IDENTITY_CHANGED")
    else:
        write_json(marker_path, marker)
    budget = RunBudget(RunLimits(questions=12, arms=2, generation_requests=None,
                                 generation_tokens=None, embedding_tokens=None),
                       Path(config["budget_path"]))
    trace = Trace(Path(config["trace_path"]), args.stage)
    sidecar = RevisionSidecar(Path(config["sidecar_path"]))
    observer = ProvenanceObserver(sidecar, args.run, args.arm)
    basis_store = DecisionBasisStore(Path(config["m1_state_path"]))
    emit = _trace_emit(trace, observer)
    host_config = VLLMConfig(**config["host"])
    embed_config = VLLMConfig(
        base_url=config["embedding"]["base_url"],
        model=config["embedding"]["model"],
        timeout=config["embedding"].get("timeout", 180),
    )
    identity = {**config, "m1_lock_sha256": lock_sha, "arm_id": args.arm}
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
                    controller = (M1Controller(basis_store, observer)
                                  if args.arm == "m1" else None)
                    model = VLLMChatModel(
                        client=host, capacity_path=Path(config["message_capacity_path"]),
                        observer=observer, m1=controller,
                    )
                    if args.mode == "merit":
                        return run_exposed_merit_arc(
                            input_path, args.output, args.run, model, store, saver,
                            identity, arm_id=args.arm, observer=observer,
                        )
                    if args.mode == "diagnostic":
                        return run_frozen_diagnostics(
                            input_path, args.diagnostic_freeze, args.output, args.run,
                            model, store, saver, identity,
                            selected_cases=set(args.case) if args.case else None,
                            arm_id=args.arm, observer=observer,
                        )
                    from milai_lab.runners.langmem_m1_mechanism import run_mechanism
                    return run_mechanism(
                        input_path, args.mechanism_freeze, args.output, args.run,
                        args.arm, model, store, saver, observer,
                    )
    finally:
        basis_store.close()
        sidecar.close()


STATE_TABLES = ("m1_format", "active_tasks", "bases", "delta_receipts",
                "events", "write_transactions")


def _query(path: Path, table: str) -> list[dict[str, Any]]:
    if table not in STATE_TABLES:
        raise ValueError("M1_QUERY_TABLE_UNKNOWN")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]  # noqa: S608


def _summary(path: Path) -> dict[str, Any]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
                  for table in STATE_TABLES}
        delta = dict(conn.execute(
            "SELECT status,count(*) FROM delta_receipts GROUP BY status"))
        events = dict(conn.execute("SELECT event,count(*) FROM events GROUP BY event"))
        active = conn.execute(
            "SELECT count(*) FROM bases WHERE basis_json IS NOT NULL"
        ).fetchone()[0]
        writes = dict(conn.execute(
            "SELECT operation,count(*) FROM write_transactions GROUP BY operation"
        ))
        state_format = conn.execute("SELECT version FROM m1_format").fetchone()[0]
    return {"counts": counts, "delta_statuses": delta, "events": events,
            "active_bases": active, "format": state_format,
            "write_transactions": {"total": counts["write_transactions"],
                                   "by_operation": writes},
            "sqlite_bytes": path.stat().st_size,
            "sqlite_wal_bytes": Path(str(path) + "-wal").stat().st_size
            if Path(str(path) + "-wal").exists() else 0}


def _schema(fixture_path: Path | None) -> dict[str, Any]:
    tools = [
        convert_to_openai_tool(create_manage_memory_tool(namespace=MEMORY_NAMESPACE)),
        convert_to_openai_tool(create_search_memory_tool(namespace=MEMORY_NAMESPACE)),
    ]
    if fixture_path is not None:
        tools.append(read_json(fixture_path)["business_tool_schema"])
    return {
        "schema": m1_action_schema(_action_schema(tools, generation_only=True)),
        "protocol": _action_prompt(tools) + "\n" + M1_PROTOCOL,
        "tool_names": [tool["function"]["name"] for tool in tools],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", required=True, type=Path)
        item.add_argument("--lock", type=Path, default=LAB / "data/locks/milai-m1-v18.lock.json")
        item.add_argument("--mode", choices=("diagnostic", "merit", "mechanism"), required=True)
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--output", required=True, type=Path)
        item.add_argument("--diagnostic-inputs", type=Path)
        item.add_argument("--diagnostic-freeze", type=Path)
        item.add_argument("--merit-selection", type=Path)
        item.add_argument("--fixture", type=Path)
        item.add_argument("--mechanism-freeze", type=Path)
        item.add_argument("--exposed-freeze", type=Path,
                          default=LAB / "data/manifests/milai-m1-v18-exposed-freeze.json")
        if command == "run":
            item.add_argument("--prepared", required=True, type=Path)
            item.add_argument("--stage", required=True)
            item.add_argument("--case", action="append", default=[])
    query = commands.add_parser("query")
    query.add_argument("--state", type=Path, required=True)
    query.add_argument("--table", choices=STATE_TABLES,
                       required=True)
    summary = commands.add_parser("summary")
    summary.add_argument("--state", type=Path, required=True)
    schema = commands.add_parser("schema")
    schema.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    if args.command in {"prepare", "run"}:
        required = {"diagnostic": (args.diagnostic_inputs, args.diagnostic_freeze),
                    "merit": (args.merit_selection,),
                    "mechanism": (args.fixture, args.mechanism_freeze)}[args.mode]
        if any(value is None for value in required):
            parser.error(f"{args.mode} input/freeze is required")
    if args.command == "prepare":
        result: Any = _prepare(args)
    elif args.command == "run":
        result = _run(args)
    elif args.command == "query":
        result = _query(args.state, args.table)
    elif args.command == "summary":
        result = _summary(args.state)
    else:
        result = _schema(args.fixture)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
