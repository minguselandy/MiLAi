"""Controlled record research through the existing SQLite and evidence executor."""
from __future__ import annotations

import copy
import json
import os
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore  # type: ignore[import-not-found]

from milai_lab.datasets.record_control import (
    make_root,
    matching_records,
    packet_coverage,
    query_text,
    score_first,
)
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.control_observation import control_input
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    MemoryControlState,
    RulesMemoryPolicy,
    run_memory_control,
)
from milai_lab.methods.small_control_model import SmallControlModel
from milai_lab.methods.small_memory_policy import SmallMemoryPolicy
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request, separate_answer_fields


def no_refresh(*_: Any) -> Any:
    raise ValueError("This controlled read task does not generate Views")


@contextmanager
def source_service(root: dict[str, Any], bank: Path, *, initialize: bool = False) -> Any:
    bank.mkdir(parents=True, exist_ok=True)
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store, ("small-control-records", root["group_id"], "author"),
            "author", bank / "lock", functional_contract="functional_v1",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC))
        if initialize:
            mapping = {}
            for record in root["records"]:
                receipt = service.capture_tool("registry", record["record_id"],
                    "controlled_registry", json.dumps(record, sort_keys=True), None)
                mapping[record["record_id"]] = receipt["source_ref"]
            write_json(bank / "record-source-map.json", mapping)
        yield service


def environment(service: MemoryService, query: dict[str, Any], capacity: HostCapacity,
                material_tokens: int, *, state: MemoryControlState | None = None,
                checkpoint: dict[str, Any] | None = None) -> tuple[MemoryControlState, Any]:
    text = query_text(query)
    if state is None:
        state = MemoryControlState(task={"request": text, "query_time": query["as_of"],
            "retrieval_request": {"query": text, "read_goal": {
                "purpose": "Controlled registry lookup", "evidence": ["original_source"]}},
            "mode": "read"}, budget={"remaining_control_steps": 8,
                                     "reader_capacity_reserved": True})

    def pool() -> list[dict[str, Any]]:
        found = service.search_sources(text, limit=16, tokenization="unicode_v1",
                                       include_scope=True)
        return build_evidence_packs(service, text, query["as_of"],
            found["source_materials"], [], source_scope=found["source_scope"])

    def fits(items: list[dict[str, Any]]) -> bool:
        return capacity.text_tokens(json.dumps(controlled_reader_packet(items, "registry"),
            ensure_ascii=False)) <= material_tokens

    operations = EvidenceOperations(service, state, load_pool=pool, refresh_call=no_refresh,
        fits=fits, internal_views=False, view_updates=False, delivery_selection=True,
        source_observation=SourceObservationBudget(2048, capacity.text_tokens),
        checkpoint=checkpoint)
    return state, operations


def execute_prefix(state: MemoryControlState, operations: Any, refs: list[str]) -> None:
    for ref in refs:
        action = next(a for a in operations.actions(state) if a.kind == "READ"
                      and a.parameters.get("observed_source", {}).get("source_ref") == ref
                      and not a.parameters.get("observe_only"))
        result = operations.execute(action, state)
        if not result["ok"]:
            raise ValueError(f"Actual registry prefix failed: {result}")
        state.last_result = {"action": asdict(action), **result}
        state.budget["remaining_control_steps"] -= 1


def structural_row(service: MemoryService, root: dict[str, Any], query_index: int,
                   prefix_index: int, refs: list[str], capacity: HostCapacity,
                   material_tokens: int) -> dict[str, Any]:
    query = root["queries"][query_index]
    state, operations = environment(service, query, capacity, material_tokens)
    execute_prefix(state, operations, refs)
    actions = operations.actions(state)
    before, checkpoint = state.project(), operations.checkpoint()
    branches = []
    for action in actions:
        branch_state = MemoryControlState(**copy.deepcopy(before))
        branch_state, branch = environment(service, query, capacity, material_tokens,
            state=branch_state, checkpoint=checkpoint)
        result = ({"ok": True, "status": "plain_handoff"} if action.kind == "HANDOFF"
                  and not action.parameters else branch.execute(action, branch_state))
        if not result["ok"]:
            raise ValueError(f"Actual registry branch failed: {result}")
        packet = controlled_reader_packet(branch.reader_evidence(), "structural_bridge")
        coverage = packet_coverage(query, packet)
        acquisition = int(action.kind == "READ")
        nonterminal_operation = int(action.kind != "HANDOFF")
        tokens = capacity.text_tokens(json.dumps(packet, ensure_ascii=False))
        branches.append({"action_id": action.id, "actual_result": result,
            "field_coverage": coverage, "new_read_operations": acquisition,
            "new_nonterminal_operations": nonterminal_operation,
            "body_tokens": tokens, "packet": packet,
            "objective": [coverage, -nonterminal_operation, -tokens]})
    best = max(tuple(b["objective"]) for b in branches)
    good = [b["action_id"] for b in branches if tuple(b["objective"]) == best]
    preferences = []
    for left, right in combinations(branches, 2):
        if left["action_id"] not in good and right["action_id"] not in good:
            continue
        lval, rval = tuple(left["objective"]), tuple(right["objective"])
        preferences.append({"left": left["action_id"], "right": right["action_id"],
            "outcome": "tie" if lval == rval else "left" if lval > rval else "right",
            "preference_source": ("program_defined_field_coverage"
                if left["field_coverage"] != right["field_coverage"]
                else "declared_structural_cost_tie_break_not_quality_difference")})
    return {"sample_id": f"{root['group_id']}/q{query_index}/prefix{prefix_index}",
        "group_id": root["group_id"], "split": root["split"],
        **control_input(state, actions), "offline_supervision": {
            "label_grade": "A_program_field_coverage_not_Reader_task_success",
            "objective": "Immediate requested-field coverage; then nonterminal operations; "
                         "then packet tokens",
            "observed_action_ids": [a.id for a in actions], "preferences": preferences},
        "offline_branches": branches,
        "provenance": {"query_index": query_index, "prefix_source_refs": refs,
            "scope": "All legal read-only branches actually executed from same checkpoint; "
                     "controlled structural bridge, not outcome-trained controller"}}


def prepare_records(args: Any) -> None:
    args.output.mkdir(parents=True, exist_ok=False)
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    started, cpu = time.perf_counter(), time.process_time()
    roots: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    run = {"status": "RUNNING", "pid": os.getpid(), "config": str(args.reader_config),
        "sha_validation": False, "Reader_calls": 0, "seed": args.seed,
        "closed_roots": 0, "compute_ledger_status": "pending_idle_settlement"}
    write_json(args.output / "run.json", run)
    try:
        for split, count in (("train", args.train_roots), ("dev_fit", args.dev_roots),
                             ("dev_select", args.dev_roots)):
            with (args.output / f"{split}.jsonl").open("x") as stream:
                for _ in range(count):
                    root = make_root(len(roots), split, args.seed)
                    bank = args.output / "banks" / root["group_id"]
                    with source_service(root, bank, initialize=True) as service:
                        mapping = read_json(bank / "record-source-map.json")
                        needed = matching_records(root["records"], root["queries"][2])
                        first, second = [mapping[v["record_id"]] for v in needed.values()]
                        for query_index in range(3):
                            for prefix_index, refs in enumerate(([], [first], [second],
                                                                  [first, second])):
                                row = structural_row(service, root, query_index, prefix_index,
                                                     refs, capacity, args.material_tokens)
                                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                                counts[split] += 1
                    roots.append(root)
                    run["closed_roots"] = len(roots)
                    write_json(args.output / "roots.json", roots)
                    write_json(args.output / "run.json", run)
                    print(json.dumps({"roots": len(roots), "states": dict(counts)}), flush=True)
        run.update(status="COMPLETED", states=dict(counts))
    except Exception as error:
        run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(wall_seconds=time.perf_counter() - started,
                   cpu_seconds=time.process_time() - cpu)
        write_json(args.output / "run.json", run)


def score_record_readouts(args: Any) -> None:
    """Bind all planned positions to actual saved firsts, with one native field score."""
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    native_run = read_json(args.readouts / "run.json")
    if native_run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
        raise ValueError("Score a closed first-response matrix; do not silently omit a tail")
    prepared = Path(native_run["prepared"])
    cases = read_json(prepared / "cases.json")
    rows = []
    for case_index, case in enumerate(cases):
        for branch_index, branch in enumerate(case["branches"]):
            folder = args.readouts / f"case-{case_index:03}" / f"packet-{branch_index}"
            record = read_json(folder / "readout.json")
            if (record["family"] != case["family"] or record["event_id"] != case["event_id"]
                    or record["action"] != branch["action"]
                    or read_json(folder / "request.json") != branch["readout_request"]):
                raise ValueError("First-response identity or complete wire does not match")
            response_path = folder / "response.json"
            result = score_first(case["offline_root"], case["offline_query"], branch["packet"],
                read_json(response_path) if response_path.exists() else None,
                observed_status=record["status"])
            for policy in branch["policies"]:
                rows.append({"event_id": case["event_id"], "group_id": case["family"],
                    "policy": policy, "first_path": str(folder / "readout.json"),
                    "reused_from": record.get("reused_from"),
                    "body_tokens": branch["body_tokens"], "outcome": result})
    summaries = {}
    for policy in sorted({row["policy"] for row in rows}):
        selected = [row for row in rows if row["policy"] == policy]
        outcomes = [row["outcome"] for row in selected]
        primary = Counter(str(o["primary_outcome"]) for o in outcomes)
        summaries[policy] = {"planned_tasks": len(outcomes),
            "roots": len({row["group_id"] for row in selected}),
            "primary_counts": dict(primary),
            "success_fraction": primary["True"] / len(outcomes),
            "unknown_bounds": [primary["True"] / len(outcomes),
                (primary["True"] + primary["None"]) / len(outcomes)],
            "execution": dict(Counter(o["execution_status"] for o in outcomes)),
            "format": dict(Counter(o["output_format_status"] for o in outcomes)),
            "material_sufficient": sum(o["material_sufficient"] for o in outcomes),
            "answer_exact": sum(o["answer_exact"] for o in outcomes),
            "body_tokens": sum(row["body_tokens"] for row in selected)}
    write_json(args.output / "results.json", rows)
    write_json(args.output / "summary.json", summaries)
    write_json(args.output / "run.json", {"status": "COMPLETED", "pid": os.getpid(),
        "readouts": str(args.readouts), "prepared": str(prepared),
        "planned_positions": len(rows), "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "compute_ledger_status": "pending_idle_settlement", "Reader_calls": 0,
        "sha_validation": False, "metric": "Exact requested registry fields AND actual "
            "delivered matching records AND completed first response",
        "scope": "Executable closed-protocol controlled task only; explanation prose and "
                 "natural-language entailment are not scored"})
    print(json.dumps(summaries, indent=2))


def prepare_record_rollouts(args: Any) -> None:
    """Save complete real trajectories/packets; the existing first Reader driver executes them."""
    import torch  # type: ignore[import-not-found]

    torch.set_num_threads(4)
    started, cpu = time.perf_counter(), time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    roots = [r for r in read_json(args.dataset / "roots.json") if r["split"] == args.split]
    if args.roots is not None:
        roots = roots[:args.roots]
    policies: dict[str, Any] = {"fixed_context": FixedContextMemoryPolicy(reads=4),
                                "rules": RulesMemoryPolicy(reads=4)}
    models = {}
    for name, checkpoint in args.checkpoint:
        models[name] = SmallControlModel.load(Path(checkpoint), device=args.device)
        policies[name] = SmallMemoryPolicy(models[name])
    cases, trajectories = [], []
    run = {"status": "RUNNING", "pid": os.getpid(), "config": str(args.reader_config),
        "dataset": str(args.dataset), "split": args.split,
        "sha_validation": False, "Reader_calls": 0, "closed_tasks": 0,
        "compute_ledger_status": "pending_idle_settlement",
        "scope": "Complete bounded controlled registry rollouts; no natural quality claim"}
    write_json(args.output / "run.json", run)
    try:
        for root in roots:
            with source_service(root, args.dataset / "banks" / root["group_id"]) as service:
                for qi, query in enumerate(root["queries"]):
                    key = f"{root['group_id']}/q{qi}"
                    case = {"family": root["group_id"], "event_id": key, "case_key": key,
                        "request_id": f"q{qi}",
                        "choices": {}, "branches": [], "offline_root": root,
                        "offline_query": query}
                    for name, policy in policies.items():
                        state, operations = environment(service, query, capacity,
                                                        args.material_tokens)
                        trace = run_memory_control(state, policy, operations,
                                                   max_steps=args.control_steps)
                        packet = controlled_reader_packet(operations.reader_evidence(), "policy")
                        request = state.task["retrieval_request"]
                        wire = separate_answer_fields(given_packet_request({
                            "content": state.task["request"], "query_time": query["as_of"],
                            "calendar_context": "UTC"}, request, packet, settings))
                        capacity.check(wire["messages"])
                        action = {"id": name, "kind": "HANDOFF", "target": "actual_policy_packet",
                                  "parameters": {}}
                        case["choices"][name] = name
                        case["branches"].append({"action": action, "policies": [name],
                            "packet": packet, "readout_request": wire,
                            "body_tokens": capacity.text_tokens(json.dumps(packet)),
                            "execution_result": {"ok": True, "status": trace["reason"]}})
                        trajectories.append({"event_id": key, "policy": name, "trace": trace,
                            "field_coverage": packet_coverage(query, packet)})
                    cases.append(case)
                    run["closed_tasks"] = len(cases)
                    write_json(args.output / "cases.json", cases)
                    write_json(args.output / "trajectories.json", trajectories)
                    write_json(args.output / "run.json", run)
                    print(json.dumps({"closed_tasks": len(cases)}), flush=True)
        run["status"] = "COMPLETED"
    except Exception as error:
        run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu,
            model_counters={name: model.counters for name, model in models.items()})
        write_json(args.output / "run.json", run)
