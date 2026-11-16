"""Review actual Host prefixes using their persisted pools, never reconstructed teacher states."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional_state import body_text, namespace, reference_key
from milai_lab.memory.reader_projection import merge_source_ranges
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.memory_control_learning import decision_example, reviewed_prefix_preferences


def source_task_review(
    family: dict[str, Any], step: str, arrived: set[str],
) -> tuple[str, list[set[str]], str]:
    review = family["offline_review"]
    if "steps" in review:
        current = review["steps"][step]
        return (current["context"], [set(p) for p in current["support_sets"]], current["answer"])
    context = "after" if "u" in arrived else "before"
    return (context, [set(p) for p in review[context + "_support_sets"]],
            review[context + "_answer"])


def original_source_mapping(
    originals: list[dict[str, Any]], sources: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Bind authored source IDs to actual captures, never to a future matching sentence."""
    by_id = {s["id"]: s for s in originals}
    return {ref: original["id"] for ref, source in sources.items()
            if (original := by_id.get(source["capture_key"])) is not None
            and source["role"] == original["role"] and body_text(source) == body_text(original)}


def delivered_original_sources(
    event: dict[str, Any], mapping: dict[str, str], sources: dict[str, dict[str, Any]],
) -> tuple[set[str], bool]:
    """Use actual opened spans; old traces require unambiguous literal/time matching."""
    if "opened_original_source_ranges" in event:
        return ({mapping[span["source_ref"]] for span in merge_source_ranges(
                    event["opened_original_source_ranges"])
                 if span["source_ref"] in mapping and span["start"] == 0
                 and span["end"] == len(body_text(sources[span["source_ref"]]))
                 and span["source_revision"] == sources[span["source_ref"]]["source_revision"]},
                False)
    covered: set[str] = set()
    ambiguous = False
    for item in event["before"]["visible_evidence"]:
        if item["kind"] != "original_source":
            continue
        for body in item.get("evidence", []):
            matches = {ref for ref, source in sources.items()
                if source["role"] == body["role"] and body_text(source) == body["content"]
                and ("captured_at" not in body or body["captured_at"] == source["observed_at"])}
            if len(matches) == 1:
                covered.update(mapping[ref] for ref in matches if ref in mapping)
            ambiguous |= len(matches) > 1 and any(ref in mapping for ref in matches)
    return covered, ambiguous


def prepare(run_path: Path, families_path: Path, output: Path, review_path: Path | None) -> None:
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    driver = read_json(run_path / "driver.json")
    runtime = Path(driver.get("runtime_root", str(run_path)))
    families = {f["family"]: f for f in read_json(families_path)["families"]}
    reviewed = (
        {
            (r["policy"], r["family"], r["label"], r["revision"], r["context"]): r[
                "task_sufficient"
            ]
            for r in read_json(review_path)["reviews"]
        }
        if review_path
        else {}
    )
    view_packets: dict[tuple[str, str, str, int, str], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    checked = 0
    for policy in driver["policies"]:
        root = runtime / policy
        freeze = read_json(root / "input-freeze.json")
        banks = read_json(root / "bank-index.json")
        for number, family_id in enumerate(driver["histories"]):
            if not any(
                r["policy"] == policy and r["history"] == family_id for r in driver["completed"]
            ):
                continue
            family = families[family_id]
            originals = [*family["sources"], *(family[key] for key in
                         ("related_update", "unrelated_update") if key in family)]
            bank_name = f"bank-{number}"
            bank = next(b for b in banks if b["identity"]["bank"] == bank_name)
            owner = bank["identity"]["owner"]
            folder = root / "banks" / bank["id"]
            work = output / "store-copy" / policy / family_id
            work.mkdir(parents=True)
            with sqlite3.connect(f"file:{folder / 'memory.sqlite'}?mode=ro", uri=True) as source:
                with sqlite3.connect(work / "memory.sqlite") as destination:
                    source.backup(destination)
            with SqliteStore.from_conn_string(str(work / "memory.sqlite")) as store:
                service = MemoryService(
                    store,
                    ("functional", freeze["run_id"], bank_name, owner),
                    owner,
                    work / "lock",
                    functional_contract="functional_v1",
                )
                messages = read_json(folder / "message-index.json")
                for closed in driver["completed"]:
                    if closed["policy"] != policy or closed["history"] != family_id:
                        continue
                    mid = next(
                        m["id"] for m in messages if m["identity"]["message_id"] == closed["step"]
                    )
                    result_path = folder / f"{mid}-result.json"
                    result = read_json(result_path)
                    sources = {s["event_id"]: s for s in result.get("sources", [])}
                    mapping = original_source_mapping(originals, sources)
                    context, proofs, expected = source_task_review(
                        family, closed["step"], set(mapping.values()))
                    key = "evidence-pool:" + reference_key(
                        [result["session"], result["message_id"], service.forget_epoch]
                    )
                    saved = store.get(namespace(service), key)
                    pool = saved.value["materials"] if saved else []
                    trace_path = folder / f"{mid}-trace-0.jsonl"
                    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
                    for event in events:
                        if (
                            event.get("event") != "memory_control_step"
                            or event.get("phase") != "decision_input"
                        ):
                            continue
                        state, actions = event["before"], event["actions"]
                        for candidate in state["pending_candidates"]:
                            if candidate != EvidenceOperations.candidate(
                                pool[candidate["item_index"]], candidate["item_index"]
                            ):
                                raise ValueError("Persisted pool does not match actual prefix")
                            checked += 1
                        covered, ambiguous_source = delivered_original_sources(
                            event, mapping, sources)
                        opened_views = []
                        for item in state["visible_evidence"]:
                            if item["kind"] != "query_structure":
                                continue
                            view_key = (policy, family_id, item["label"], item["revision"], context)
                            opened_views.append(reviewed.get(view_key))
                            view_packets.setdefault(
                                view_key,
                                {
                                    "policy": policy,
                                    "family": family_id,
                                    "label": item["label"],
                                    "revision": item["revision"],
                                    "context": context,
                                    "first_seen_step": closed["step"],
                                    "trace": str(trace_path),
                                    "view": item,
                                    "view_bindings": [
                                        v["source_bindings"]
                                        for v in state["views"]
                                        if v["revision"] == item["revision"]
                                    ],
                                    "sources": list(sources.values()),
                                    "expected": expected,
                                    "task_sufficient": reviewed.get(view_key),
                                    "note": "",
                                },
                            )
                        reads, refreshes = {}, {}
                        for action in actions:
                            parameters = action["parameters"]
                            if action["kind"] == "REFRESH_VIEW":
                                refreshes[action["id"]] = {
                                    mapping[r] for r in parameters["source_refs"] if r in mapping
                                }
                            if action["kind"] != "READ" or parameters.get("history_directory"):
                                continue
                            item = pool[parameters["index"]]
                            spans = item.get(
                                "context_source_ranges"
                                if parameters.get("expand_context")
                                else "source_ranges",
                                [],
                            )
                            reads[action["id"]] = {
                                mapping[s["source_ref"]]
                                for s in spans
                                if s["source_ref"] in mapping
                                and s["start"] == 0
                                and s["end"] == len(sources[s["source_ref"]]["content"])
                            }
                        selected, status, basis = reviewed_prefix_preferences(
                            actions,
                            proofs=proofs,
                            covered=covered,
                            read_sources=reads,
                            refresh_sources=refreshes,
                            opened_views=opened_views,
                        )
                        if ambiguous_source and status != "forced_single_action_masked" \
                                and not any(p <= covered for p in proofs) \
                                and not any(v is True for v in opened_views):
                            selected, status = [], "ambiguous_original_identity_masked"
                            basis = [*basis, "ambiguous_original_identity"]
                        row = decision_example(
                            event,
                            {
                                "family": family_id,
                                "split": family["split"],
                                "row": closed["step"],
                                "training_event": closed["step"],
                                "state_id": len(rows),
                                "event_id": (f"{policy}:{family_id}:"
                                             f"{closed['step']}:{event['step']}"),
                                "source_version": driver["source_version"],
                                "trace": str(trace_path),
                                "result": str(result_path),
                                "decision_step": event["step"],
                                "source_context": context,
                                "original_sources_delivered": sorted(covered),
                                "source_proofs": [sorted(p) for p in proofs],
                                "label_basis": basis,
                                "label_kind": "reviewed task preference, not exhaustive legality",
                            },
                        )
                        row["metadata"]["label_status"] = status
                        row["gold"] = (
                            {
                                "next": {
                                    "probabilities": {key: 1 / len(selected) for key in selected}
                                }
                            }
                            if selected
                            else {}
                        )
                        rows.append(row)
    for split in ("train", "dev"):
        with (output / f"{split}.jsonl").open("w") as stream:
            for row in rows:
                if row["metadata"]["split"] == split:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(output / "view-review-required.json", {"reviews": list(view_packets.values())})
    write_json(
        output / "summary.json",
        {
            "source_run": str(run_path),
            "source_status": driver["status"],
            "states": len(rows),
            "labelled_by_split": dict(Counter(r["metadata"]["split"] for r in rows if r["gold"])),
            "statuses": dict(Counter(r["metadata"]["label_status"] for r in rows)),
            "unreviewed_view_contexts": sum(
                r["task_sufficient"] is None for r in view_packets.values()
            ),
            "persisted_candidate_matches": checked,
            "policy_choices_copied": False,
            "scope": "Single-slot source-only own rollouts; inputs unchanged, actual pools only. "
            "View adequacy reviewed separately in the declared source contexts. "
            "No silent stale-view credit or future-source reconstruction.",
        },
    )
    write_json(
        output / "compute.json",
        {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "ledger_recorded": False,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("families", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--view-review", type=Path)
    args = parser.parse_args()
    prepare(args.run, args.families, args.output, args.view_review)


if __name__ == "__main__":
    main()
