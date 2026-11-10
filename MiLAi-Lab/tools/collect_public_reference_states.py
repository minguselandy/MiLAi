"""Collect cold and real-known-reference operation states through the public retrieval tool.

Native context masks apply to both SEARCH and Source observations. Earlier
delivered tool references, never offline support annotations, supply Host knowledge.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langgraph.store.sqlite import SqliteStore

from collect_qasper_operation_states import (
    complete,
    covered_sources,
    reference_preferences,
    reference_proofs,
)
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.methods.source_ranges import SourceRangeBudget
from milai_lab.providers.contextual_capacity import HostCapacity


class LexicalCollectionPolicy:
    """One broad request search, ordinary reads, then current delivery; no gold access."""

    def __init__(self, reads: int = 6) -> None:
        self.reads = reads

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        if state.last_result is None:
            searches = [
                a
                for a in actions
                if a.kind == "SEARCH"
                and (
                    a.parameters.get("query_from") == "request"
                    or a.parameters.get("query") == state.task["request"]
                )
            ]
            if searches:
                return max(searches, key=lambda a: a.parameters["limit"]).id
        if len(state.observed_materials or []) < self.reads:
            read = next(
                (a for a in actions if a.kind == "READ" and set(a.parameters) == {"index"}), None
            )
            if read is not None:
                return read.id
        return next(a.id for a in actions if a.kind == "HANDOFF" and not a.parameters)


def bindings_for_supervision(event: dict[str, Any]) -> Any:
    """Use actual executor bindings recorded outside the model input."""
    scoped = {
        scope["item_index"]: {
            "kind": scope["evidence"]["kind"],
            "source_ranges": scope["source_ranges"],
        }
        for scope in event["before"].get("retrieved_scopes", [])
    }
    return SimpleNamespace(
        materials=event["candidate_materials"],
        observed={
            int(i): item
            for i, item in event.get("observed_materials", event["opened_materials"]).items()
        },
        opened={int(i): item for i, item in event["opened_materials"].items()},
        known_materials=event["known_materials"],
        retrieved_scopes=lambda: scoped,
    )


def observed_search_preferences(
    events: list[dict[str, Any]],
    proofs: list[list[set[str]]],
    mapping: dict[str, str],
    lengths: dict[str, int],
) -> dict[int, set[str]]:
    """Credit only executed full SEARCH bindings with actual useful candidate scope.

    Another query/limit remains unjudged. This is a reference-acquisition proxy,
    not a claim that the search immediately completed the Host task.
    """
    inputs = {e["step"]: e for e in events if e.get("phase") == "decision_input"}
    result: dict[int, set[str]] = {}
    for event in events:
        if event.get("phase") != "operation_result" or not event["result"].get("ok"):
            continue
        action = next(a for a in event["actions"] if a["id"] == event["selected"])
        if action["kind"] != "SEARCH" or event["step"] + 1 not in inputs:
            continue
        before, after = inputs[event["step"]], inputs[event["step"] + 1]
        already = covered_sources(
            [
                *before["known_materials"],
                *before.get("observed_materials", before["opened_materials"]).values(),
            ],
            mapping,
            lengths,
        )
        scope = [
            {
                **item,
                "source_ranges": item.get("context_source_ranges", item.get("source_ranges", [])),
            }
            for item in after["candidate_materials"]
        ]
        available = covered_sources(scope, mapping, lengths)
        if not complete(proofs, already) and any(
            not group & already and group & available for proof in proofs for group in proof
        ):
            result.setdefault(event["step"], set()).add(action["id"])
    return result


def collect_history(
    history: dict[str, Any],
    controls: dict[str, dict[str, Any]],
    root: Path,
    capacity: HostCapacity,
    *,
    max_steps: int,
    material_tokens: int,
    known_condition: bool,
    append: Any,
    source_cluster: str | None = None,
    request_limit: int | None = None,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    report = {
        "family": history["source_group"],
        "source_cluster": source_cluster,
        "source_units": len(history["sources"]),
        "requests": [],
    }
    ranges = SourceRangeBudget(
        256,
        capacity.text_tokens,
        lambda text: capacity.tokenizer(
            text, add_special_tokens=False, return_offsets_mapping=True
        )["offset_mapping"],
    )
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("public-operation-collection", history["id"], "collector"),
            "collector",
            root / "lock",
            functional_contract="functional_v1",
        )
        mapping, lengths = {}, {}
        for source in history["sources"]:
            receipt = service.capture_tool(
                source["session_id"],
                source["event_key"],
                source["origin"],
                source["content"],
                None,
                occurred_at=source["occurred_at"],
            )
            mapping[receipt["source_ref"]] = source["original_event_id"]
            lengths[receipt["source_ref"]] = len(source["content"])
        write_json(root / "source-map.json", {"mapping": mapping, "source_lengths": lengths})
        for request in history["requests"][:request_limit]:
            allowed = set(request.get("source_event_ids", mapping.values()))
            if not allowed <= set(mapping.values()):
                raise ValueError("Native request contains a source outside its actual family bank")
            excluded = tuple(ref for ref, native in mapping.items() if native not in allowed)
            proofs = reference_proofs(controls[request["id"]])
            known_refs: list[dict[str, Any]] = []
            parent_receipt = None
            conditions = ("cold", "known-first") if known_condition else ("cold",)
            for condition in conditions:
                if condition == "known-first" and not known_refs:
                    report["requests"].append(
                        {
                            "request": request["id"],
                            "condition": condition,
                            "status": "NO_EARLIER_DELIVERED_REFERENCE",
                        }
                    )
                    continue
                incoming = copy.deepcopy(request["retrieval_request"])
                incoming.setdefault("task_context", {})["known_evidence_refs"] = copy.deepcopy(
                    known_refs if condition == "known-first" else []
                )
                session = request["id"]
                source = service.capture_user(
                    session,
                    condition,
                    request["content"],
                    capture_context="given_retrieval_request",
                )
                version = "public-reference-conditions-v1"
                service.bind_public_turn(
                    session, condition, source["source_ref"], config_version=version, phase="start"
                )
                cfg = {
                    "configurable": {
                        "user_id": "collector",
                        "v13_session": session,
                        "v13_turn_id": condition,
                        "v13_config_version": version,
                    }
                }
                trace = root / f"{request['id']}-{condition}-operations.jsonl"
                labels: Counter[str] = Counter()
                events: list[dict[str, Any]] = []

                def compile_record(
                    event: dict[str, Any],
                    search_preferences: set[str],
                    trace: Path = trace,
                    proofs: list[list[set[str]]] = proofs,
                    request: dict[str, Any] = request,
                    condition: str = condition,
                    parent_receipt: Path | None = parent_receipt,
                    allowed: set[str] = allowed,
                    labels: Counter[str] = labels,
                ) -> None:
                    if event.get("phase") != "decision_input":
                        return
                    actions = [MemoryAction(**a) for a in event["actions"]]
                    accepted, status = reference_preferences(
                        actions,
                        bindings_for_supervision(event),
                        proofs,
                        mapping,
                        lengths,
                        search_preferences=search_preferences,
                    )
                    row = decision_example(
                        event,
                        {
                            "family": history["source_group"],
                            "split": history["split"],
                            "row": request.get("native_source_row", request["id"]),
                            "source_cluster": source_cluster or history["source_group"],
                            "event_id": (
                                f"{history['source_group']}/{request['id']}/{condition}"
                                f"/step-{event['step']}"
                            ),
                            "training_event": request["id"],
                            "task": "memory_operation",
                            "source_version": history["source_version"],
                            "condition": condition,
                            "trace": str(trace.resolve()),
                            "collector": "public_lexical_prefix",
                            "stage": "initial" if event["step"] == 0 else "post_operation",
                            "known_reference_parent_receipt": str(parent_receipt)
                            if condition != "cold"
                            else None,
                            "native_context_source_ids": sorted(allowed),
                            "supervision_version": "reference_witness_v4_bound_search_known_refs",
                            "reference_proofs": [[sorted(g) for g in proof] for proof in proofs],
                            "supervision_scope": "Native witness plus actual known materials; "
                            "not exhaustive proofs or Host success. Missing support stays unknown.",
                        },
                    )
                    row["metadata"]["label_status"] = status
                    if accepted:
                        row["gold"] = {
                            "next": {"probabilities": {key: 1 / len(accepted) for key in accepted}}
                        }
                    labels[status] += 1
                    append(row)

                def record(
                    event: dict[str, Any],
                    trace: Path = trace,
                    events: list[dict[str, Any]] = events,
                ) -> None:
                    with trace.open("a") as stream:
                        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                    if event.get("phase") in {"decision_input", "operation_result"}:
                        events.append(copy.deepcopy(event))

                memory = IntentRetrievalMemory(
                    service,
                    capacity.text_tokens,
                    interface_version="I2",
                    material_limit=material_tokens,
                    read_limit=max_steps + 1,
                    source_access="independent_v1",
                    source_tokenization="unicode_v1",
                    source_top_k=16,
                    evidence_policy="question_pack_v1",
                    control_policy=LexicalCollectionPolicy(),
                    control_steps=max_steps,
                    control_record=record,
                    control_internal_views=False,
                    control_delivery_selection=True,
                    control_source_observation_tokens=2048,
                    control_source_ranges=ranges,
                    control_excluded_source_refs=excluded,
                    control_exclude_given_requests=True,
                )
                try:
                    packet = memory.retrieve(
                        cfg, "actual-retrieval", RetrievalRequest.model_validate(incoming)
                    )
                finally:
                    searches = observed_search_preferences(events, proofs, mapping, lengths)
                    for event in events:
                        compile_record(event, searches.get(event["step"], set()))
                receipt = root / f"{request['id']}-{condition}-receipt.json"
                write_json(
                    receipt,
                    {
                        "request": incoming,
                        "packet": packet,
                        "native_context_source_ids": sorted(allowed),
                        "Host_executed": False,
                    },
                )
                if condition == "cold":
                    known_refs = [packet["evidence"][0]["ref"]] if packet["evidence"] else []
                    parent_receipt = receipt
                report["requests"].append(
                    {
                        "request": request["id"],
                        "condition": condition,
                        "status": "COMPLETED",
                        "states": sum(labels.values()),
                        "labels": dict(labels),
                        "receipt": str(receipt.resolve()),
                        "known_reference_reads": packet["usage"].get("known_reference_reads", 0),
                        "delivered_items": len(packet["evidence"]),
                    }
                )
                write_json(root / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("population", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--families", type=int)
    parser.add_argument("--requests-per-family", type=int)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--cold-only", action="store_true")
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    source = read_json(args.population / "histories.json")["histories"]
    histories = source[args.offset : None if args.families is None else args.offset + args.families]
    controls = {
        (r["source_group"], r["request_id"]): r
        for r in read_jsonl(args.population / "controls.jsonl")
    }
    clusters = {
        family: f"musique-target-component-{i:05d}"
        for i, group in enumerate(
            read_json(args.population / "population.json")["target_title_clusters"]
        )
        for family in group
    }
    settings = read_json(args.config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "sources.json", {"histories": histories})
    run = {
        "status": "RUNNING",
        "pid": os.getpid(),
        "population": str(args.population.resolve()),
        "planned_families": len(histories),
        "completed_families": 0,
        "raw_states": 0,
        "labelled_states": 0,
        "labels": {},
        "conditions": {},
        "no_sha_validation": True,
        "model_calls": 0,
        "Host_calls": 0,
        "automatic_retry": False,
        "requests_per_family": args.requests_per_family,
    }

    def append(row: dict[str, Any]) -> None:
        row["metadata"]["state_id"] = run["raw_states"]
        run["raw_states"] += 1
        run["labelled_states"] += bool(row["gold"])
        for field, value in (
            ("labels", row["metadata"]["label_status"]),
            ("conditions", row["metadata"]["condition"]),
        ):
            run[field][value] = run[field].get(value, 0) + 1
        with (args.output / "states.jsonl").open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    try:
        for history in histories:
            run["active_family"] = history["source_group"]
            write_json(args.output / "run.json", run)
            collect_history(
                history,
                {q["id"]: controls[history["source_group"], q["id"]] for q in history["requests"]},
                args.output / "banks" / history["id"],
                capacity,
                max_steps=args.max_steps,
                material_tokens=settings["ordinary_material_tokens"],
                known_condition=not args.cold_only,
                append=append,
                source_cluster=clusters[history["source_group"]],
                request_limit=args.requests_per_family,
            )
            run["completed_families"] += 1
            write_json(args.output / "run.json", run)
            print(
                json.dumps(
                    {k: run[k] for k in ("completed_families", "raw_states", "labelled_states")}
                ),
                flush=True,
            )
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run["compute"] = {
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - started,
        }
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
