"""Collect real source-backed operation prefixes; native evidence is offline supervision.

One immutable Source bank per paper, ordinary request-local executor state, and
at most three actual same-pool HANDOFF packets. No model calls or Store-per-state copies.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from feedback_choices import coverage_alternative, parameter_stratum
from milai_lab.datasets.qasper import QUESTION_PROMPT_PREFIX, given_question_request
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.memory.reader_projection import merge_source_ranges
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, RulesMemoryPolicy
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.methods.source_ranges import SourceRangeBudget
from milai_lab.providers.contextual_capacity import HostCapacity


def reference_proofs(control: dict[str, Any]) -> list[list[set[str]]]:
    """An annotation is a conjunction of evidence groups, each allowing literal duplicates.

    Keep alternative annotations separate. Unanswerable, figures and unmatched
    annotations cannot establish complete textual proofs or force a stop label.
    """
    if control.get("schema") == "source_reference_witness_v1":
        return [[set(group) for group in proof] for proof in control["reference_proofs"]]
    proofs = []
    for annotation in control["annotations"]:
        evidence = annotation["evidence"]
        if (
            not annotation["answer"]["unanswerable"]
            and evidence
            and all(e["status"] == "matched_text" and e["source_event_ids"] for e in evidence)
        ):
            proofs.append([set(e["source_event_ids"]) for e in evidence])
    return proofs


def complete(proofs: list[list[set[str]]], covered: set[str]) -> bool:
    return any(all(group & covered for group in proof) for proof in proofs)


def covered_sources(
    items: list[dict[str, Any]], mapping: dict[str, str], source_lengths: dict[str, int]
) -> set[str]:
    spans = merge_source_ranges(
        [
            span
            for item in items
            if item["kind"] == "original_source"
            for span in item.get("source_ranges", [])
        ]
    )
    return {
        mapping[span["source_ref"]]
        for span in spans
        if span["source_ref"] in mapping
        and span["start"] == 0
        and span["end"] == source_lengths[span["source_ref"]]
    }


def handoff_items(action: MemoryAction, operations: EvidenceOperations) -> list[dict[str, Any]]:
    if not action.parameters:
        return list(operations.opened.values())
    narrowed = action.parameters.get("retrieved_scope_indices", [])
    retrieved = operations.retrieved_scopes() if narrowed else {}
    return [
        retrieved[i] if i in narrowed else operations.observed[i]
        for i in action.parameters["delivery_indices"]
    ]


def reference_preferences(
    actions: list[MemoryAction],
    operations: EvidenceOperations,
    proofs: list[list[set[str]]],
    mapping: dict[str, str],
    lengths: dict[str, int],
    search_preferences: set[str] | None = None,
) -> tuple[list[str], str]:
    """Annotated-proof acquisition/delivery preferences, not exhaustive semantic negatives."""
    if not proofs:
        return [], "unknown_textual_reference"
    known = covered_sources(operations.known_materials, mapping, lengths)
    accepted = [
        a.id
        for a in actions
        if a.kind == "HANDOFF"
        and complete(
            proofs, known | covered_sources(handoff_items(a, operations), mapping, lengths)
        )
    ]
    if accepted:
        return accepted, "reference_preserving_handoff"
    # Acquisition and current delivery differ when a READ exceeds the packet budget.
    covered = known | covered_sources(list(operations.observed.values()), mapping, lengths)
    accepted = []
    for action in actions:
        if action.kind == "SEARCH" and (
            search_preferences is None or action.id in search_preferences
        ):
            # Source discovery is a structural prerequisite, not a sufficiency judgment.
            accepted.append(action.id)
        if action.kind != "READ" or action.parameters.get("observe_only"):
            continue
        parameters = action.parameters
        if "observed_source" in parameters:
            spans = [parameters["observed_source"]]
        elif "index" in parameters and not parameters.get("history_directory"):
            item = operations.materials[parameters["index"]]
            spans = item.get(
                "context_source_ranges" if parameters.get("expand_context") else "source_ranges", []
            )
        else:
            continue
        acquired = covered_sources(
            [{"kind": "original_source", "source_ranges": spans}], mapping, lengths
        )
        if any(not group & covered and group & acquired for proof in proofs for group in proof):
            accepted.append(action.id)
    return accepted, "reference_acquisition" if accepted else "unknown_reference_progress"


def no_refresh(*_: Any) -> Any:
    raise RuntimeError("This source-only collection has no generated View operation")


def collect_paper(
    history: dict[str, Any],
    controls: dict[str, dict[str, Any]],
    root: Path,
    capacity: HostCapacity,
    settings: dict[str, Any],
    *,
    max_steps: int,
    branches: bool,
    seed: int,
    append: Any,
    source_bank: Path | None = None,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    bank = source_bank or root
    observation = SourceObservationBudget(2048, capacity.text_tokens)
    ranges = SourceRangeBudget(
        256,
        capacity.text_tokens,
        lambda text: capacity.tokenizer(
            text, add_special_tokens=False, return_offsets_mapping=True
        )["offset_mapping"],
    )
    report: dict[str, Any] = {
        "family": history["source_group"],
        "split": history["split"],
        "requests": [],
        "source_units": len(history["sources"]),
        "source_bank_root": str(bank.resolve()),
        "existing_Source_bank_reused": source_bank is not None,
    }
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("scalable-evidence", history["id"], "collector"),
            "collector",
            bank / "lock",
            functional_contract="functional_v1",
        )
        if source_bank is not None:
            saved = read_json(bank / "source-map.json")
            mapping, lengths = saved["mapping"], saved["source_lengths"]
            if set(mapping.values()) != {s["original_event_id"] for s in history["sources"]}:
                raise ValueError("Existing Source bank belongs to different native source units")
        else:
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
                ref = receipt["source_ref"]
                mapping[ref] = source["original_event_id"]
                lengths[ref] = len(source["content"])
        write_json(root / "source-map.json", {"mapping": mapping, "source_lengths": lengths})
        for request_index, request in enumerate(history["requests"]):
            query = request["content"].removeprefix(QUESTION_PROMPT_PREFIX)
            retrieval_request = given_question_request(query)
            proofs = reference_proofs(controls[request["id"]])
            state = MemoryControlState(
                task={
                    "request": query,
                    "query_time": "2026-11-11",
                    "calendar_context": "Asia/Shanghai",
                    "read_goal": retrieval_request["read_goal"],
                    "retrieval_request": retrieval_request,
                    "mode": "read",
                    "fresh_observations": [],
                }
            )

            def pool(query: str = query) -> list[dict[str, Any]]:
                found = service.search_sources(
                    query,
                    source_refs=list(mapping),
                    limit=16,
                    tokenization="unicode_v1",
                    include_scope=True,
                )
                return build_evidence_packs(
                    service,
                    query,
                    "2026-11-11",
                    found["source_materials"],
                    [],
                    source_scope=found["source_scope"],
                    source_range_budget=ranges,
                    source_range_limit=16,
                )

            operations = EvidenceOperations(
                service,
                state,
                load_pool=pool,
                refresh_call=no_refresh,
                fits=lambda evidence: (
                    capacity.text_tokens(
                        json.dumps(
                            controlled_reader_packet(evidence, "collection"), ensure_ascii=False
                        )
                    )
                    <= settings["ordinary_material_tokens"]
                ),
                internal_views=False,
                view_updates=False,
                delivery_selection=True,
                source_observation=observation,
            )
            trace = root / f"{request['id']}-operations.jsonl"
            labels, chosen = Counter(), []
            for step in range(max_steps):
                state.budget.update(
                    remaining_control_steps=max_steps - step, reader_capacity_reserved=True
                )
                actions = operations.actions(state)
                event = {
                    "step": step,
                    "before": state.project(),
                    "actions": [asdict(action) for action in actions],
                }
                accepted, label_status = reference_preferences(
                    actions, operations, proofs, mapping, lengths
                )
                row = decision_example(
                    event,
                    {
                        "family": history["source_group"],
                        "split": history["split"],
                        "row": request_index,
                        "event_id": f"{history['source_group']}/{request['id']}/step-{step}",
                        "training_event": request["id"],
                        "task": "memory_operation",
                        "source_version": "qasper-v0.3",
                        "trace": str(trace.resolve()),
                        "source_bank_root": str(bank.resolve()),
                        "collector": "fixed_lexical_read_prefix",
                        "stage": (
                            "initial" if step == 0 else "post_search" if step == 1 else "post_read"
                        ),
                        "supervision_scope": "Native complete-text annotation witness preference; "
                        "not exhaustive alternative proofs, runtime sufficiency or Host success",
                        "supervision_version": "reference_witness_v2_observed_delivery",
                        "reference_proofs": [
                            [sorted(group) for group in proof] for proof in proofs
                        ],
                    },
                )
                row["metadata"]["label_status"] = label_status
                if accepted:
                    row["gold"] = {
                        "next": {"probabilities": {key: 1 / len(accepted) for key in accepted}}
                    }
                labels[label_status] += 1
                append("states", row)
                if step == max_steps - 1:
                    action = next(a for a in actions if a.kind == "HANDOFF" and not a.parameters)
                else:
                    action = next((a for a in actions if a.kind == "SEARCH"), None)
                    if action is None:
                        action = next(
                            (
                                a
                                for a in actions
                                if a.kind == "READ" and set(a.parameters) == {"index"}
                            ),
                            None,
                        )
                    if action is None:
                        action = next(
                            a for a in actions if a.kind == "HANDOFF" and not a.parameters
                        )
                if action.kind == "HANDOFF" and branches:
                    saved, before = operations.checkpoint(), state.project()
                    handoffs = [a for a in actions if a.kind == "HANDOFF"]
                    rule_id = RulesMemoryPolicy(reads=4).choose(state, handoffs)
                    selected = list(dict.fromkeys([action.id, rule_id]))
                    coverage: Counter[str] = Counter()
                    for key in selected:
                        coverage[
                            parameter_stratum(next(asdict(a) for a in handoffs if a.id == key))
                        ] += 1
                    alternative = coverage_alternative(
                        {
                            "initial_observation": before,
                            "initial_actions": [asdict(a) for a in handoffs],
                        },
                        [asdict(a) for a in handoffs if a.id in selected],
                        coverage,
                        seed + request_index,
                    )
                    if alternative is not None:
                        selected.append(alternative["id"])
                    branch_rows = []
                    for key in selected:
                        branch_state = MemoryControlState(**copy.deepcopy(before))
                        operations.restore_checkpoint(saved, observation)
                        bound = next(a for a in handoffs if a.id == key)
                        result = (
                            operations.execute(bound, branch_state)
                            if bound.parameters
                            else {"ok": True, "status": "current_delivery"}
                        )
                        packet = controlled_reader_packet(
                            operations.reader_evidence(), "collection"
                        )
                        delivered = covered_sources(
                            list(operations.opened.values()), mapping, lengths
                        )
                        branch_rows.append(
                            {
                                "action": asdict(bound),
                                "result": result,
                                "packet": packet,
                                "delivered_native_sources": sorted(delivered),
                                "reference_proof_complete": complete(proofs, delivered)
                                if proofs
                                else None,
                                "Host_result": None,
                            }
                        )
                    operations.restore_checkpoint(saved, observation)
                    append(
                        "branches",
                        {
                            "event_id": row["metadata"]["event_id"],
                            "family": history["source_group"],
                            "split": history["split"],
                            "before": before,
                            "actions": [asdict(a) for a in handoffs],
                            "results": branch_rows,
                            "prefix_reexecuted": False,
                        },
                    )
                started = time.perf_counter()
                result = (
                    operations.execute(action, state)
                    if action.kind != "HANDOFF" or action.parameters
                    else {"ok": True, "status": "current_delivery"}
                )
                state.last_result = {"action": asdict(action), **result}
                event.update(
                    selected=action.id,
                    result=result,
                    operation_wall_seconds=time.perf_counter() - started,
                )
                with trace.open("a") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                chosen.append(action.id)
                if action.kind == "HANDOFF":
                    break
            report["requests"].append(
                {
                    "request_id": request["id"],
                    "states": sum(labels.values()),
                    "label_status": dict(labels),
                    "actions": chosen,
                    "Host_executed": False,
                }
            )
            write_json(root / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("histories", type=Path)
    parser.add_argument("controls", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--families", type=int)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--branch-families", type=int, default=64)
    parser.add_argument(
        "--reuse-source-collections",
        type=Path,
        nargs="+",
        default=[],
        help="Use existing immutable paper banks for additional native questions",
    )
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    histories = read_json(args.histories)["histories"]
    histories = histories[
        args.offset : None if args.families is None else args.offset + args.families
    ]
    controls = {(c["source_group"], c["request_id"]): c for c in read_jsonl(args.controls)}
    source_banks = {
        h["source_group"]: collection / "banks" / h["id"]
        for collection in args.reuse_source_collections
        for h in read_json(collection / "sources.json")["histories"]
    }
    if not histories or any(h["split"] not in {"train", "dev"} for h in histories):
        raise ValueError("Collection requires an existing TRAIN/development source allocation")
    settings = read_json(args.config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "sources.json", {"histories": histories})
    run = {
        "status": "RUNNING",
        "pid": os.getpid(),
        "histories": str(args.histories.resolve()),
        "controls": str(args.controls.resolve()),
        "config": str(args.config.resolve()),
        "offset": args.offset,
        "planned_families": len(histories),
        "completed_families": 0,
        "raw_states": 0,
        "labelled_states": 0,
        "branch_states": 0,
        "branch_packets": 0,
        "labels": {},
        "stages": {},
        "no_sha_validation": True,
        "model_calls": 0,
        "Host_calls": 0,
        "automatic_retry": False,
        "reused_source_families": sum(h["source_group"] in source_banks for h in histories),
    }

    def append(kind: str, row: dict[str, Any]) -> None:
        if kind == "states":
            row["metadata"]["state_id"] = run["raw_states"]
            run["raw_states"] += 1
            run["labelled_states"] += bool(row["gold"])
            for field, value in (
                ("labels", row["metadata"]["label_status"]),
                ("stages", row["metadata"]["stage"]),
            ):
                run[field][value] = run[field].get(value, 0) + 1
        else:
            run["branch_states"] += 1
            run["branch_packets"] += len(row["results"])
        with (args.output / f"{kind}.jsonl").open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    try:
        for index, history in enumerate(histories):
            run["active_family"] = history["source_group"]
            write_json(args.output / "run.json", run)
            collect_paper(
                history,
                {r["id"]: controls[history["source_group"], r["id"]] for r in history["requests"]},
                args.output / "banks" / history["id"],
                capacity,
                settings,
                max_steps=args.max_steps,
                branches=args.offset + index < args.branch_families,
                seed=args.offset + index,
                append=append,
                source_bank=source_banks.get(history["source_group"]),
            )
            run["completed_families"] += 1
            write_json(args.output / "run.json", run)
            print(
                json.dumps(
                    {
                        k: run[k]
                        for k in (
                            "completed_families",
                            "raw_states",
                            "labelled_states",
                            "branch_packets",
                        )
                    }
                ),
                flush=True,
            )
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run["compute"] = {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
        }
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
