"""Prepare, run and inspect the v16 model-hidden LangMem experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_agent import VLLMEmbeddings, open_persistent_state
from milai_lab.baselines.langmem_b1_identity import (
    ARMS,
    INSTRUMENTATION_VERSION,
    LAB,
    verify_b1_lock,
    verify_b1_prepared,
)
from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import (
    ObservedStore,
    RevisionSidecar,
    canonical_json,
)
from milai_lab.datasets.merit import load_exposed_arc
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
from milai_lab.runners.langmem_merit import run_exposed_merit_arc


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    verify_b1_lock(args.lock, args.config)
    receipt: dict[str, Any] = {
        "status": "PREPARED_ZERO_MODEL",
        "instrumentation_version": INSTRUMENTATION_VERSION,
        "arm_id": args.arm, "run_id": args.run,
        "lock_sha256": sha256_file(args.lock),
        "config_sha256": sha256_file(args.config),
        "recipe_id": read_json(args.config)["recipe_id"],
    }
    if args.mode == "merit":
        selection, arc, _, _, _ = load_exposed_arc(args.merit_selection)
        receipt.update({
            "merit_selection_sha256": sha256_file(args.merit_selection),
            "arc_id": arc.arc_id,
            "arc_sha256": selection["private_artifacts"]["arc_sha256"],
            "episodes": len(arc.episodes),
            "public_messages": sum(len(e.task.user_messages) for e in arc.episodes),
        })
    else:
        freeze = read_json(args.diagnostic_freeze)
        inputs = read_json(args.diagnostic_inputs)
        if sha256_file(args.diagnostic_inputs) != freeze["inputs_file_sha256"]:
            raise ValueError("B1_DIAGNOSTIC_INPUT_CHANGED")
        if len(inputs["cases"]) != freeze["cases"]:
            raise ValueError("B1_DIAGNOSTIC_COUNT_CHANGED")
        receipt.update({
            "diagnostic_inputs_sha256": sha256_file(args.diagnostic_inputs),
            "diagnostic_freeze_sha256": sha256_file(args.diagnostic_freeze),
            "diagnostic_cases": len(inputs["cases"]),
            "diagnostic_sessions": sum(len(c["sessions"]) for c in inputs["cases"]),
            "rubric_read_by_runner": False,
        })
    write_json(args.output, receipt)
    return receipt


def _trace_emit(
    trace: Trace, observer: ProvenanceObserver | None,
) -> Callable[[dict[str, Any]], None]:
    def emit(event: dict[str, Any]) -> None:
        offset = trace.path.stat().st_size if trace.path.exists() else 0
        trace(event)
        if observer is not None:
            record = json.dumps({"stage": trace.stage, **event}, ensure_ascii=False) + "\n"
            observer.capture_provider_event(event, {
                "path": str(trace.path.resolve()), "byte_offset": offset,
                "record_sha256": hashlib.sha256(record.encode("utf-8")).hexdigest(),
            })
    return emit


def _run(args: argparse.Namespace) -> dict[str, Any]:
    lock_sha = verify_b1_prepared(
        args.prepared, args.lock, args.config,
        arm_id=args.arm, run_id=args.run,
        merit_selection=args.merit_selection if args.mode == "merit" else None,
        diagnostic_inputs=args.diagnostic_inputs if args.mode == "diagnostic" else None,
        diagnostic_freeze=args.diagnostic_freeze if args.mode == "diagnostic" else None,
    )
    config = read_json(args.config)
    marker_path = (Path(config["checkpoint_path"]).parent / "b1-runtime-"
                   f"{hashlib.sha256(f'{args.run}:{args.arm}'.encode()).hexdigest()}.json")
    marker = {
        "run_id": args.run, "arm_id": args.arm,
        "lock_sha256": lock_sha,
        "config_sha256": sha256_file(args.config),
        "prepared_sha256": sha256_file(args.prepared),
    }
    if marker_path.exists():
        if read_json(marker_path) != marker:
            raise ValueError("B1_RUNTIME_IDENTITY_CHANGED")
    else:
        write_json(marker_path, marker)
    dsn = os.environ["MILAI_LANGMEM_POSTGRES_DSN"]
    budget = RunBudget(RunLimits(questions=12, arms=2, generation_requests=None,
                                 generation_tokens=None, embedding_tokens=None),
                       Path(config["budget_path"]))
    trace = Trace(Path(config["trace_path"]), args.stage)
    sidecar = (RevisionSidecar(Path(config["sidecar_path"]))
               if args.arm == "b1_instrumented" else None)
    observer = (ProvenanceObserver(sidecar, args.run, args.arm)
                if sidecar is not None else None)

    emit = _trace_emit(trace, observer)

    host_config = VLLMConfig(**config["host"])
    embed_config = VLLMConfig(
        base_url=config["embedding"]["base_url"],
        model=config["embedding"]["model"],
        timeout=config["embedding"].get("timeout", 180),
    )
    identity = {**config, "b1_lock_sha256": lock_sha, "arm_id": args.arm}
    try:
        if observer is not None:
            observer.assert_healthy()
        with VLLMClient(host_config, emit=emit, budget=budget,
                        capacity=HostCapacity(config["capacity"])) as host:
            with VLLMClient(embed_config, emit=trace, budget=budget) as embed:
                embeddings = VLLMEmbeddings(embed, embed_config.model)
                with open_persistent_state(
                    dsn, Path(config["checkpoint_path"]), embeddings,
                    embedding_dimensions=config["embedding_dimension"],
                ) as (base_store, saver):
                    store = (ObservedStore(base_store, observer)
                             if observer is not None else base_store)
                    model = VLLMChatModel(
                        client=host, capacity_path=Path(config["message_capacity_path"]),
                        observer=observer,
                    )
                    if args.mode == "merit":
                        return run_exposed_merit_arc(
                            args.merit_selection, args.output, args.run,
                            model, store, saver, identity, arm_id=args.arm,
                            observer=observer,
                        )
                    return run_frozen_diagnostics(
                        args.diagnostic_inputs, args.diagnostic_freeze,
                        args.output, args.run, model, store, saver, identity,
                        selected_cases=set(args.case) if args.case else None,
                        arm_id=args.arm, observer=observer,
                    )
    finally:
        if sidecar is not None:
            sidecar.close()


TABLES = {"bodies", "observations", "tool_calls", "operations", "revisions",
          "searches", "requests", "request_material"}


def _read_sidecar(
    path: Path, table: str, filters: list[str], *, latest: bool = False,
    resolve_body: bool = False, resolve_request: bool = False,
) -> list[dict[str, Any]]:
    if table not in TABLES:
        raise ValueError("B1_QUERY_TABLE_UNKNOWN")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        selected = [item.split("=", 1) for item in filters]
        if any(len(pair) != 2 or pair[0] not in columns for pair in selected):
            raise ValueError("B1_QUERY_FILTER_INVALID")
        where = " AND ".join(f'"{column}"=?' for column, _ in selected)
        query = f"SELECT * FROM {table}" + (" WHERE " + where if where else "")  # noqa: S608
        query += " ORDER BY rowid"
        rows = [dict(row) for row in conn.execute(
            query, [value for _, value in selected])]
        if latest:
            if table != "revisions":
                raise ValueError("B1_QUERY_LATEST_REQUIRES_REVISIONS")
            rows = rows[-1:]
        if resolve_body:
            for row in rows:
                ref = row.get("body_ref")
                if ref is None:
                    row["resolved_body"] = None
                    continue
                body = conn.execute("SELECT body_json FROM bodies WHERE body_ref=?",
                                    (ref,)).fetchone()
                if body is None:
                    raise ValueError("B1_QUERY_BODY_REF_MISSING")
                row["resolved_body"] = json.loads(body[0])
        if resolve_request:
            if table != "requests":
                raise ValueError("B1_QUERY_RESOLVE_REQUEST_REQUIRES_REQUESTS")
            for row in rows:
                if row["request_json"] is not None:
                    request = json.loads(row["request_json"])
                elif row["trace_path"] is not None:
                    with Path(row["trace_path"]).open("rb") as stream:
                        stream.seek(row["trace_byte_offset"])
                        raw = stream.readline()
                    if hashlib.sha256(raw).hexdigest() != row["trace_record_sha256"]:
                        raise ValueError("B1_QUERY_TRACE_REF_CHANGED")
                    request = json.loads(raw)["request"]
                else:
                    request = None
                if request is not None and hashlib.sha256(
                    canonical_json(request).encode("utf-8")
                ).hexdigest() != row["request_object_sha256"]:
                    raise ValueError("B1_QUERY_REQUEST_OBJECT_CHANGED")
                row["resolved_request"] = request
        return rows


def _summarize(path: Path) -> dict[str, Any]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        counts = {}
        for table in TABLES:
            counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
        by_status = {}
        for table, field in (("tool_calls", "status"), ("operations", "status"),
                             ("searches", "status"), ("requests", "status")):
            by_status[table] = {row[0]: row[1] for row in conn.execute(
                f"SELECT {field},count(*) FROM {table} GROUP BY {field}")}  # noqa: S608
        stats = dict(conn.execute("SELECT * FROM stats WHERE id=1").fetchone())
        observation_roles = {row[0]: row[1] for row in conn.execute(
            "SELECT role,count(*) FROM observations GROUP BY role")}
        revision_effects = {row[0]: row[1] for row in conn.execute(
            "SELECT actual_effect,count(*) FROM revisions GROUP BY actual_effect")}
        material_coverage = {row[0]: row[1] for row in conn.execute(
            "SELECT coverage,count(*) FROM request_material GROUP BY coverage")}
        search_returned = [json.loads(row[0]) for row in conn.execute(
            "SELECT returned_json FROM searches WHERE returned_json IS NOT NULL")]
    stats["sqlite_db_bytes"] = path.stat().st_size
    stats["net_sqlite_db_bytes"] = stats["sqlite_db_bytes"] - stats["initial_db_bytes"]
    stats["measured_scope"] = ("sidecar data transactions including commit; "
                                "stats bookkeeping excluded; additional Store reads separate")
    return {
        "counts": counts, "statuses": by_status,
        "observation_roles": observation_roles,
        "revision_effects": revision_effects,
        "material_coverage": material_coverage,
        "search_returned_items": sum(len(items) for items in search_returned),
        "search_exact_revision_bindings": sum(
            item["revision_status"] == "EXACT" for items in search_returned
            for item in items),
        "instrumentation_cost": stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", required=True, type=Path)
        item.add_argument("--lock", type=Path,
                          default=LAB / "data/locks/langmem-b1.lock.json")
        item.add_argument("--mode", choices=("diagnostic", "merit"), required=True)
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--output", required=True, type=Path)
        item.add_argument("--merit-selection", type=Path)
        item.add_argument("--diagnostic-inputs", type=Path)
        item.add_argument("--diagnostic-freeze", type=Path)
        if command == "run":
            item.add_argument("--prepared", required=True, type=Path)
            item.add_argument("--stage", required=True)
            item.add_argument("--case", action="append", default=[])
    query = commands.add_parser("query")
    query.add_argument("--sidecar", required=True, type=Path)
    query.add_argument("--table", choices=sorted(TABLES), required=True)
    query.add_argument("--filter", action="append", default=[],
                       help="Exact column=value filter; may repeat")
    query.add_argument("--latest", action="store_true")
    query.add_argument("--resolve-body", action="store_true")
    query.add_argument("--resolve-request", action="store_true")
    summary = commands.add_parser("summary")
    summary.add_argument("--sidecar", required=True, type=Path)
    args = parser.parse_args()
    if args.command in {"prepare", "run"}:
        if args.mode == "merit" and args.merit_selection is None:
            parser.error("MERIT requires --merit-selection")
        if args.mode == "diagnostic" and (args.diagnostic_inputs is None
                                          or args.diagnostic_freeze is None):
            parser.error("diagnostic requires --diagnostic-inputs and --diagnostic-freeze")
    if args.command == "prepare":
        result: Any = _prepare(args)
    elif args.command == "run":
        result = _run(args)
    elif args.command == "query":
        result = _read_sidecar(
            args.sidecar, args.table, args.filter, latest=args.latest,
            resolve_body=args.resolve_body, resolve_request=args.resolve_request,
        )
    else:
        result = _summarize(args.sidecar)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
