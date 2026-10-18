"""Compile reviewed source-task preferences on real observations, without teacher-choice copying."""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import build_evidence_packs


def original_coverage(state: dict[str, Any], texts: dict[tuple[str, str], str]) -> set[str]:
    return {
        texts[(turn["role"], turn["content"])]
        for item in state["visible_evidence"]
        if item["kind"] == "original_source"
        for turn in item.get("evidence", [])
        if (turn["role"], turn["content"]) in texts
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    fixture = read_json(args.collection / "source-families.json")
    reviews = {(r["family"], r["phase"]): r for r in read_json(args.review)["reviews"]}
    rows = [
        json.loads(line) for line in (args.collection / "unlabelled.jsonl").read_text().splitlines()
    ]
    outputs: list[dict[str, Any]] = []
    coverage_checks = 0
    for family in fixture["families"]:
        name = family["family"]
        originals = [*family["sources"], family["unrelated_update"], family["related_update"]]
        texts = {(s["role"], s["content"]): s["id"] for s in originals}
        report = read_json(args.collection / name / "report.json")
        work = args.output / "reconstruction" / name
        work.mkdir(parents=True)
        # A diagnostic copy preserves original Source IDs/clocks and immutable artifacts.
        with sqlite3.connect(
            f"file:{args.collection / name / 'memory.sqlite'}?mode=ro", uri=True
        ) as src:
            with sqlite3.connect(work / "memory.sqlite") as dst:
                src.backup(dst)
        with SqliteStore.from_conn_string(str(work / "memory.sqlite")) as store:
            service = MemoryService(
                store,
                ("operation-collection", "author"),
                "author",
                work / "lock",
                functional_contract="functional_v1",
            )
            for phase in family["phase_order"]:
                selected = [
                    r
                    for r in rows
                    if r["metadata"]["family"] == name and r["metadata"]["row"] == phase
                ]
                mapping = selected[0]["metadata"]["source_id_mapping"]
                allowed = [ref for ref, label in mapping.items() if label != "query:" + phase]
                found = service.search_sources(
                    family["query"],
                    source_refs=allowed,
                    tokenization="unicode_v1",
                    limit=20,
                    include_scope=True,
                )
                pool = build_evidence_packs(
                    service,
                    family["query"],
                    family["query_time"],
                    found["source_materials"],
                    [],
                    source_scope=found["source_scope"],
                )
                events = [
                    json.loads(line)
                    for line in (args.collection / name / f"{phase}-operations.jsonl")
                    .read_text()
                    .splitlines()
                ]
                decisions = {e["step"]: e for e in events if e.get("phase") == "decision_input"}
                changed = "u" in mapping.values()
                proofs = [
                    set(p)
                    for p in family["offline_review"][
                        "after_support_sets" if changed else "before_support_sets"
                    ]
                ]
                for row in selected:
                    labelled = copy.deepcopy(row)
                    state = row["state"]
                    step = int(row["metadata"]["event_id"].rsplit(":", 1)[1])
                    actions = decisions[step]["actions"]
                    for candidate in state["pending_candidates"]:
                        expected = EvidenceOperations.candidate(
                            pool[candidate["item_index"]], candidate["item_index"]
                        )
                        if candidate != expected:
                            raise ValueError(
                                "Recorded candidate differs from actual-prefix copy: "
                                f"{name}/{phase}/{step}"
                            )
                        coverage_checks += 1
                    covered = original_coverage(state, texts)
                    raw_ready = any(p <= covered for p in proofs)
                    view_ready = False
                    for item in state["visible_evidence"]:
                        if item["kind"] != "query_structure" or "interpretation" not in item:
                            continue
                        view_phase = next(
                            p
                            for p in ("changed", "cold")
                            if report["phases"][p]["view"] is not None
                            and report["phases"][p]["view"]["revision"] == item["revision"]
                        )
                        # Current updates cannot be answered with a pre-update interpretation.
                        if changed and view_phase == "cold":
                            continue
                        if not changed and view_phase == "changed":
                            raise ValueError("Future view entered an earlier observation")
                        view_ready |= reviews[name, view_phase]["task_text_sufficient"]
                    positives, basis = [], []
                    if len(actions) == 1:
                        status = "forced_single_action_masked"
                    elif raw_ready or view_ready:
                        positives = [a["id"] for a in actions if a["kind"] == "HANDOFF"]
                        status = "ready_handoff_preference"
                        basis = [
                            "adequate_originals" if raw_ready else "reviewed_task_adequate_view"
                        ]
                    else:
                        status = "acquire_evidence_preference"
                        for action in actions:
                            kind = action["kind"]
                            if kind == "SEARCH":
                                positives.append(action["id"])
                                basis.append("source_pool_acquisition")
                            elif kind == "USE_VIEW":
                                # Inspect a view without assuming its hidden contents are valid.
                                positives.append(action["id"])
                                basis.append("inspect_existing_same_task_interpretation")
                            elif kind == "REFRESH_VIEW":
                                supplied = {
                                    mapping.get(ref) for ref in action["parameters"]["source_refs"]
                                }
                                if any(p <= supplied for p in proofs):
                                    positives.append(action["id"])
                                    basis.append(
                                        "adequate_source_scope_for_interpretation; "
                                        "executor_success_separate"
                                    )
                            elif kind == "READ" and not action["parameters"].get(
                                "history_directory"
                            ):
                                item = pool[action["parameters"]["index"]]
                                ranges = (
                                    item["context_source_ranges"]
                                    if action["parameters"].get("expand_context")
                                    else item["source_ranges"]
                                )
                                additions = {
                                    mapping.get(span["source_ref"]) for span in ranges
                                } - covered
                                if any(additions & (proof - covered) for proof in proofs):
                                    positives.append(action["id"])
                                    basis.append("adds_a_missing_reviewed_source_premise")
                        if not positives:
                            status = "ambiguous_no_proven_progress_masked"
                    labelled["gold"] = (
                        {"next": {"probabilities": {key: 1 / len(positives) for key in positives}}}
                        if positives
                        else {}
                    )
                    labelled["metadata"].update(
                        label_status=status,
                        label_kind=("source-grounded current-task preference, "
                                    "not exhaustive legality"),
                        label_basis=sorted(set(basis)),
                        original_sources_delivered=sorted(covered),
                        source_proofs=[sorted(p) for p in proofs],
                        view_graph_validity_not_credited=True,
                    )
                    outputs.append(labelled)
    outputs.sort(key=lambda r: r["metadata"]["state_id"])
    for split in ("train", "dev"):
        with (args.output / f"{split}.jsonl").open("w") as stream:
            for row in outputs:
                if row["metadata"]["split"] == split:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(
        args.output / "summary.json",
        {
            "rows": len(outputs),
            "labelled_by_split": dict(
                Counter(r["metadata"]["split"] for r in outputs if r["gold"])
            ),
            "statuses": dict(Counter(r["metadata"]["label_status"] for r in outputs)),
            "positive_action_kinds": dict(
                Counter(
                    r["metadata"]["action_kinds"][a]
                    for r in outputs
                    for a in r["gold"].get("next", {}).get("probabilities", {})
                )
            ),
            "candidate_reconstruction_checks": coverage_checks,
            "teacher_choices_copied": False,
            "scope": "T0 source-task preferences; partial observed states, "
                     "not optimal lifelong policy or QA proof",
        },
    )
    write_json(
        args.output / "compute.json",
        {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "ledger_recorded": False,
        },
    )


if __name__ == "__main__":
    main()
