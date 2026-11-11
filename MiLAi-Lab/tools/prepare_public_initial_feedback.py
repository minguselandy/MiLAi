"""Replay actual public initial states through existing EvidenceOperations, with fixed receipt K."""

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
)
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.methods.source_ranges import SourceRangeBudget
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import receipt_conditioned_packet_request
from prepare_collected_operation_feedback import execute_branch, nominate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--families", type=int, required=True)
    parser.add_argument("--offset", type=int, default=0)
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
    assert len(histories) == args.families and all(h["split"] == "train" for h in histories)
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
        "source_split": "train",
        "families": len(histories),
        "comparison_states": 0,
        "packets": 0,
        "source_bank_reuse": True,
        "new_Source_copies": 0,
        "new_model_calls": 0,
        "Host_calls": 0,
        "new_supplied_query_events": 0,
        "continuation_policy": args.continuation_policy,
        "continuation_steps": 4,
        "terminal_handoff": "policy",
        "no_sha_validation": True,
        "automatic_retry": False,
        "known_query_only": args.known_query_only,
        "readout_scope": (
            "Actual public initial cold/fixed-receipt-K observation/menu and saved model input. "
            "Same EvidenceOperations, declared four-step continuation and policy HANDOFF. "
            "Replay work counters restored separately from actual measured cost, as existing "
            "collected_handoff; no Source data or original labels changed. Core operation packet, "
            "not a rerun of full public-message/admission history. Explicit referenced prior K "
            "plus current real acquired packet, not autonomous Host."
        ),
    }
    write_json(args.output / "run.json", run)
    try:
        for history in histories:
            public = history["requests"][0]
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
                    event = copy.deepcopy(
                        next(
                            e
                            for e in events
                            if e.get("phase") == "decision_output" and e["step"] == 0
                        )
                    )
                    pred = read_jsonl(collected / f"{public['id']}-{condition}-predictions.jsonl")[
                        0
                    ]
                    event["prediction"] = pred["prediction"]
                    assert event["selected"] == pred["prediction"]["choice"]
                    event_id = f"{history['source_group']}/{public['id']}/{condition}/step-0"
                    row = decision_example(
                        event,
                        {
                            "family": history["source_group"],
                            "split": "train",
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
                    if args.known_query_only:
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
                        choices = nominate(event, coverage, len(rows) - 1, "fixed_context")
                    request = RetrievalRequest.model_validate(receipt["request"])
                    resolver = IntentRetrievalMemory(
                        service,
                        capacity.text_tokens,
                        interface_version="I2",
                        control_policy=FixedContextMemoryPolicy(reads=4),
                    )
                    known = resolver._known_materials(request)
                    state = MemoryControlState(**copy.deepcopy(event["before"]))
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
                            steps=event["before"]["budget"]["remaining_control_steps"],
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
                    original_budget = event["before"]["budget"]
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
                    assert state.project() == event["before"], (
                        "Source or actual initial state changed"
                    )
                    assert [asdict(a) for a in actions] == event["actions"], (
                        "Actual full menu changed"
                    )
                    saved = operations.checkpoint()
                    observation = (
                        operations.source_pages.budget if operations.source_pages else None
                    )
                    parent = read_json(Path(receipt["known_reference_parent_receipt"]))
                    case = {
                        "family": history["source_group"],
                        "source_split": "train",
                        "event_id": event_id,
                        "case_key": event_id,
                        "request_id": public["id"],
                        "condition": condition,
                        "native_source_row": public["native_source_row"],
                        "state_index": len(rows) - 1,
                        "before": event["before"],
                        "actions": event["actions"],
                        "choices": choices,
                        "branches": [],
                        "restored_replay_budget": {
                            "actual_reconstruction": actual_budget,
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
                            0,
                            4,
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
                    run.update(
                        comparison_states=len(cases), packets=sum(len(x["branches"]) for x in cases)
                    )
                    write_json(args.output / "cases.json", cases)
                    (args.output / "states.jsonl").write_text(
                        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
                    )
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
        run["compute"] = {
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - start,
        }
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
