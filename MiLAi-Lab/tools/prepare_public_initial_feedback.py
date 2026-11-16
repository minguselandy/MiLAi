"""Replay actual public reached states through EvidenceOperations, with fixed receipt K."""

import argparse
import copy
import json
import os
import time
from collections import Counter
from dataclasses import asdict
from functools import partial
from pathlib import Path

from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.memory.functional_state import canonical
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory, delivery_packet_fits
from milai_lab.methods.laya_memory_policy import project_operation_payload
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
    RulesMemoryPolicy,
)
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.methods.source_ranges import SourceRangeBudget
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import receipt_conditioned_packet_request
from prepare_collected_handoff_comparison import complementary_deliveries
from prepare_collected_operation_feedback import append_completed_case, execute_branch, nominate


def replay_public_to_step(operations, state, events, target_step):
    """Reexecute the actual prefix rather than initialize an executor from an ideal post-state."""
    decisions = [e for e in events if e.get("phase") == "decision_output"]
    outcomes = {e["step"]: e for e in events if e.get("phase") == "operation_result"}
    for event in decisions:
        state.budget = copy.deepcopy(event["before"]["budget"])
        actions = operations.actions(state)
        if state.project() != event["before"] or [asdict(a) for a in actions] != event["actions"]:
            raise ValueError("Actual public prefix no longer matches recorded state/menu")
        if event["step"] == target_step:
            return state
        action = next(a for a in actions if a.id == event["selected"])
        if action.kind == "HANDOFF":
            raise ValueError("Requested post-state lies beyond an actual terminal HANDOFF")
        result = operations.execute(action, state)
        if result != outcomes[event["step"]]["result"]:
            raise ValueError("Actual public prefix outcome changed")
        state.last_result = {"action": asdict(action), **result}
    raise ValueError("Requested public post-state was not reached")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--families", type=int, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--requests-per-family", type=int, default=1,
                        help="Original request prefix; zero means all")
    parser.add_argument("--target-step", type=int, default=0)
    parser.add_argument("--split", choices=("train", "dev"), default="train")
    parser.add_argument("--terminal-deliveries", action="store_true",
                        help="Compare only legal deliveries at an actual learner HANDOFF; "
                             "forced or unreached terminal states remain missing")
    parser.add_argument("--continuation-steps", type=int, default=4)
    parser.add_argument("--include-legal-handoff", action="store_true")
    parser.add_argument("--snapshot-every", type=int, default=128)
    parser.add_argument(
        "--nomination-source",
        type=Path,
        help="Reuse complete declared choices from an existing same-before preparation",
    )
    parser.add_argument(
        "--continuation-policy",
        choices=("fixed_context", "query_once_context"),
        default="fixed_context",
    )
    parser.add_argument(
        "--known-query-only",
        action="store_true",
        help="Execute only the largest offered search from the actual first known item; "
        "extend existing same-state comparisons without rerunning their other actions",
    )
    args = parser.parse_args()
    if min(args.requests_per_family, args.target_step, args.continuation_steps) < 0:
        parser.error("Request/step limits must be nonnegative")
    if args.snapshot_every < 1:
        parser.error("Snapshot interval must be positive")
    if args.nomination_source and args.known_query_only:
        parser.error("Choose frozen nominations or the known-query extension, not both")
    if args.terminal_deliveries and (args.known_query_only or args.target_step
                                    or args.continuation_steps):
        parser.error("Terminal deliveries require --continuation-steps 0 "
                     "and terminal state selection")
    nominations = (
        {c["event_id"]: c for c in read_json(args.nomination_source / "cases.json")}
        if args.nomination_source
        else {}
    )
    start, cpu = time.perf_counter(), time.process_time()
    original = read_json(args.collection / "run.json")
    assert args.offset + args.families <= original["completed_families"]
    settings = read_json(Path(original["config"]))["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    ranges = SourceRangeBudget(
        256,
        capacity.text_tokens,
        lambda s: capacity.tokenizer(s, add_special_tokens=False, return_offsets_mapping=True)[
            "offset_mapping"
        ],
    )
    histories = read_json(args.collection / "sources.json")["histories"][
        args.offset : args.offset + args.families
    ]
    assert len(histories) == args.families and all(h["split"] == args.split for h in histories)
    args.output.mkdir(exist_ok=False)
    cases = []
    rows = []
    coverage = Counter()
    run = {
        "status": "RUNNING",
        "pid": os.getpid(),
        "collection": str(args.collection.resolve()),
        "config": original["config"],
        "collector_checkpoint": original["checkpoint"],
        "source_split": args.split,
        "families": len(histories),
        "comparison_states": 0,
        "packets": 0,
        "source_bank_reuse": True,
        "new_Source_copies": 0,
        "new_model_calls": 0,
        "Host_calls": 0,
        "new_supplied_query_events": 0,
        "continuation_policy": args.continuation_policy,
        "continuation_steps": args.continuation_steps,
        "nomination_baseline": args.continuation_policy,
        "requests_per_family": args.requests_per_family,
        "target_step": args.target_step,
        "terminal_deliveries": args.terminal_deliveries,
        "snapshot_every": args.snapshot_every,
        "incremental_cases": "completed-cases.jsonl",
        "include_legal_handoff": args.include_legal_handoff,
        "terminal_handoff": "policy",
        "no_sha_validation": True,
        "automatic_retry": False,
        "known_query_only": args.known_query_only,
        "nomination_source": str(args.nomination_source) if args.nomination_source else None,
        "readout_scope": (
            "Actual public reached cold/fixed-receipt-K observation/menu and saved model input. "
            "Same EvidenceOperations, declared bounded continuation and policy HANDOFF. "
            "Replay work counters restored separately from actual measured cost, as existing "
            "collected_handoff; no Source data or original labels changed. Core operation packet, "
            "not a rerun of full public-message/admission history. Explicit referenced prior K "
            "plus current real acquired packet, not autonomous Host."
        ),
    }
    write_json(args.output / "run.json", run)
    try:
        collected_limit = original.get("requests_per_family", 1)
        units = []
        for history in histories:
            available = (history["requests"][:collected_limit] if collected_limit
                         else history["requests"])
            requested = (available[:args.requests_per_family]
                         if args.requests_per_family else available)
            units.extend((history, request) for request in requested)
        run["planned_native_requests"] = len(units)
        for history, public in units:
            source = Path(original["collection"]) / "banks" / history["id"]
            collected = args.collection / "banks" / history["id"]
            mapping = read_json(source / "source-map.json")["mapping"]
            allowed = set(public.get("source_event_ids", mapping.values()))
            with SqliteStore.from_conn_string(str(source / "memory.sqlite")) as store:
                service = MemoryService(
                    store,
                    ("public-operation-collection", history["id"], "collector"),
                    "collector",
                    source / "lock",
                    functional_contract="functional_v1",
                )
                supplied = set()
                offset = 0
                while True:
                    page = store.search(
                        service.sources_namespace,
                        filter={
                            "owner": service.owner,
                            "capture_context": "given_retrieval_request",
                        },
                        limit=1000,
                        offset=offset,
                    )
                    supplied.update(
                        item.key for item in page if item.namespace == service.sources_namespace
                    )
                    if len(page) < 1000:
                        break
                    offset += len(page)
                excluded = tuple(
                    sorted(
                        supplied | {ref for ref, native in mapping.items() if native not in allowed}
                    )
                )
                conditions = ["known-first"] if args.known_query_only else ["cold", "known-first"]
                for condition in conditions:
                    receipt = read_json(collected / f"{public['id']}-{condition}-receipt.json")
                    events = read_jsonl(collected / f"{public['id']}-{condition}-operations.jsonl")
                    initial = next(e for e in events
                                   if e.get("phase") == "decision_output" and e["step"] == 0)
                    model_events = [e for e in events if e.get("phase") == "decision_output"
                                    and e.get("selection_mode") == "policy"]
                    predictions = read_jsonl(
                        collected / f"{public['id']}-{condition}-predictions.jsonl")
                    if len(model_events) != len(predictions):
                        raise ValueError("Public model receipts do not align with policy decisions")
                    target_step = args.target_step
                    if args.terminal_deliveries:
                        terminal = next((e for e in model_events if any(
                            a["id"] == e["selected"] and a["kind"] == "HANDOFF"
                            for a in e["actions"])), None)
                        target_step = terminal["step"] if terminal else None
                    found = next(((e, p) for e, p in zip(model_events, predictions, strict=True)
                                  if e["step"] == target_step), None)
                    if found is None:
                        run.setdefault("unreached_or_forced_states", []).append({
                            "family": history["source_group"], "request_id": public["id"],
                            "condition": condition, "target_step": target_step})
                        continue
                    event, pred = copy.deepcopy(found)
                    event["prediction"] = pred["prediction"]
                    assert event["selected"] == pred["prediction"]["choice"]
                    event_id = (f"{history['source_group']}/{public['id']}/{condition}/"
                                f"step-{target_step}")
                    row = decision_example(
                        event,
                        {
                            "family": history["source_group"],
                            "split": args.split,
                            "row": len(rows),
                            "state_id": len(rows),
                            "event_id": event_id,
                            "training_event": public["id"],
                            "task": "memory_operation",
                            "collector": "frozen_public_learner",
                            "condition": condition,
                        },
                    )
                    projected = project_operation_payload(row, "shared_actions")
                    assert pred["input"] == {k: projected[k] for k in ["state", "questions"]}
                    rows.append(row)
                    if args.nomination_source:
                        frozen = nominations[event_id]
                        if (
                            frozen["before"] != event["before"]
                            or frozen["actions"] != event["actions"]
                        ):
                            raise ValueError("Frozen nomination belongs to a different before/menu")
                        choices = copy.deepcopy(frozen["choices"])
                        if not set(choices.values()) <= {a["id"] for a in event["actions"]}:
                            raise ValueError("Frozen nomination has an unavailable action")
                        if args.terminal_deliveries and any(
                            a["kind"] != "HANDOFF" for a in event["actions"]
                            if a["id"] in choices.values()
                        ):
                            raise ValueError("Conditional delivery cannot nominate acquisition")
                    elif args.terminal_deliveries:
                        delivery_actions = [MemoryAction(**a) for a in event["actions"]
                                            if a["kind"] == "HANDOFF"]
                        choices = {"collector_delivery": event["selected"],
                            "rules": RulesMemoryPolicy(reads=4).choose(
                                MemoryControlState(**copy.deepcopy(event["before"])),
                                delivery_actions)}
                        full = next((a for a in delivery_actions if not a.parameters), None)
                        if full is not None:
                            choices["full_delivery"] = full.id
                        choices.update(complementary_deliveries(delivery_actions, tuple(
                            item["item_index"] for item in event["before"]["observed_materials"]
                            if item["selected"])))
                    elif args.known_query_only:
                        searches = [
                            a
                            for a in event["actions"]
                            if a["kind"] == "SEARCH"
                            and a["parameters"].get("query_from") == "known_material"
                            and a["parameters"].get("index") == 0
                        ]
                        if not searches:
                            raise ValueError("Actual state offers no first-known-item query")
                        choices = {
                            "known_query": max(searches, key=lambda a: a["parameters"]["limit"])[
                                "id"
                            ]
                        }
                    else:
                        choices = nominate(event, coverage, len(rows) - 1,
                                           args.continuation_policy, args.include_legal_handoff)
                    if not choices:
                        rows.pop()
                        run.setdefault("unselected_nomination_states", []).append(event_id)
                        continue
                    request = RetrievalRequest.model_validate(receipt["request"])
                    resolver = IntentRetrievalMemory(
                        service,
                        capacity.text_tokens,
                        interface_version="I2",
                        control_policy=FixedContextMemoryPolicy(reads=4),
                    )
                    known = resolver._known_materials(request)
                    state = MemoryControlState(**copy.deepcopy(initial["before"]))
                    limit = state.budget["max_return_tokens"]
                    key = "retrieval:" + json.dumps(
                        [public["id"], args.collection.name + "/" + condition, "actual-retrieval"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )

                    def search_pool(
                        query, count, *, service=service, excluded=excluded, request=request
                    ):
                        found = service.search_sources(
                            query,
                            limit=min(count, 16),
                            excluded_source_refs=excluded,
                            tokenization="unicode_v1",
                        )
                        return build_evidence_packs(
                            service,
                            request.query,
                            request.task_context.as_of or "",
                            found["source_materials"],
                            [],
                            tokenization="unicode_v1",
                            source_range_budget=ranges,
                            source_range_limit=min(count, 16),
                        )

                    def no_refresh(*a, **k):
                        raise AssertionError(
                            "No View refresh exists in this actual source-only menu"
                        )

                    operations = EvidenceOperations(
                        service,
                        state,
                        load_pool=lambda search_pool=search_pool, query=request.query: search_pool(
                            query, 16
                        ),
                        search_pool=search_pool,
                        search_batch_sizes=(8, 16),
                        refresh_call=no_refresh,
                        fits=lambda items, limit=limit: (
                            capacity.text_tokens(
                                json.dumps(
                                    items, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                                )
                            )
                            <= limit
                        ),
                        fits_materials=partial(
                            delivery_packet_fits,
                            key,
                            steps=initial["before"]["budget"]["remaining_control_steps"],
                            known_count=len(known),
                            return_limit=limit,
                            return_tokens=lambda value: capacity.text_tokens(canonical(value)),
                            intervention=False,
                        ),
                        excluded_source_refs=excluded,
                        exclude_given_requests=True,
                        known_materials=known,
                        internal_views=False,
                        source_observation=SourceObservationBudget(2048, capacity.text_tokens),
                        delivery_selection=True,
                    )
                    actual_budget = copy.deepcopy(state.budget)
                    original_budget = initial["before"]["budget"]
                    changed = {
                        k
                        for k in set(actual_budget) | set(original_budget)
                        if actual_budget.get(k) != original_budget.get(k)
                    }
                    assert changed <= {"source_feed_rows", "source_inventory_wall_seconds"}, (
                        "Non-work budget changed"
                    )
                    state.budget = copy.deepcopy(original_budget)
                    actions = operations.actions(state)
                    assert state.project() == initial["before"], (
                        "Source or actual initial state changed"
                    )
                    assert [asdict(a) for a in actions] == initial["actions"], (
                        "Actual full menu changed"
                    )
                    state = replay_public_to_step(operations, state, events, target_step)
                    saved = operations.checkpoint()
                    observation = (
                        operations.source_pages.budget if operations.source_pages else None
                    )
                    parent = read_json(Path(receipt["known_reference_parent_receipt"]))
                    case = {
                        "family": history["source_group"],
                        "source_split": args.split,
                        "event_id": event_id,
                        "case_key": event_id,
                        "request_id": public["id"],
                        "step": target_step,
                        "condition": condition,
                        "native_source_row": public["native_source_row"],
                        "state_index": len(rows) - 1,
                        "before": event["before"],
                        "actions": event["actions"],
                        "choices": choices,
                        "branches": [],
                        "restored_replay_budget": {
                            "actual_reconstruction": actual_budget,
                            "original_initial_observation": initial["before"]["budget"],
                            "target_step": target_step,
                            "original_model_observation": event["before"]["budget"],
                            "scope": (
                                "Same recorded work-counter restoration as collected_handoff. "
                                "Query-source feed-row scan and timing changed after excluded "
                                "supplied-query events; Source bodies, roles and state "
                                "and menu must match. Resource allowances remain unchanged."
                            ),
                        },
                    }
                    for action_id in dict.fromkeys(choices.values()):
                        operations.restore_checkpoint(saved, observation)
                        action = next(
                            MemoryAction(**a) for a in event["actions"] if a["id"] == action_id
                        )
                        result = execute_branch(
                            operations,
                            event["before"],
                            action,
                            target_step,
                            args.continuation_steps,
                            "policy",
                            args.continuation_policy,
                        )
                        packet = controlled_reader_packet(
                            operations.reader_evidence(), "collection"
                        )
                        wire = receipt_conditioned_packet_request(
                            public, receipt["request"], packet, settings, [parent]
                        )
                        case["branches"].append(
                            {
                                "policies": [p for p, c in choices.items() if c == action_id],
                                "action": asdict(action),
                                "continuation": result,
                                "execution_result": {
                                    "ok": result["reason"] != "operation_outcome_unknown"
                                    and result["trace"][-1]
                                    .get("result", {"ok": True})
                                    .get("ok", True),
                                    "status": result["reason"],
                                },
                                "packet": packet,
                                "body_tokens": capacity.text_tokens(
                                    json.dumps(packet, ensure_ascii=False)
                                ),
                                "readout_request": wire,
                                "reference_proof_complete": None,
                                "actual_before_and_full_menu_equal": True,
                                "condition_provenance": {
                                    "known_reference_parent_receipt": receipt[
                                        "known_reference_parent_receipt"
                                    ],
                                    "known_evidence_refs": request.task_context.model_dump()[
                                        "known_evidence_refs"
                                    ],
                                    "native_context_source_ids": sorted(allowed),
                                    "original_Source_bank": str(source),
                                    "full_public_admission_replayed": False,
                                },
                            }
                        )
                    cases.append(case)
                    append_completed_case(args.output, case)
                    run.update(
                        comparison_states=len(cases), packets=sum(len(x["branches"]) for x in cases)
                    )
                    if len(cases) % args.snapshot_every == 0:
                        write_json(args.output / "cases.json", cases)
                    with (args.output / "states.jsonl").open("a") as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    write_json(args.output / "run.json", run)
                    print(
                        json.dumps(
                            {
                                "family": history["source_group"],
                                "condition": condition,
                                "states": len(cases),
                                "packets": run["packets"],
                            }
                        ),
                        flush=True,
                    )
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(
            status="FAILED_FIRST_RETAINED", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        write_json(args.output / "cases.json", cases)
        (args.output / "states.jsonl").write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
        run["compute"] = {
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - start,
        }
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
