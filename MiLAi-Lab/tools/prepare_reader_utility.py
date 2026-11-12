"""Export executed packet references for offline scoring, separate from student inputs."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.laya_memory_policy import payload_actions


def qasper_references(control: dict[str, Any]) -> list[str]:
    """Use every native answer alternative verbatim; never compress a multi-part answer.

    Unanswerable/contradictory annotations remain on the semantic channel. The tokenizer's
    complete-input limit is the only length filter; no reference is silently truncated.
    """
    answers = [a["answer"] for a in control["annotations"]]
    if any(a["unanswerable"] for a in answers):
        return []
    refs = []
    for answer in answers:
        if answer["yes_no"] is not None:
            text = "Yes" if answer["yes_no"] else "No"
        elif answer["free_form_answer"]:
            text = answer["free_form_answer"].strip()
        else:
            text = ", ".join(answer["extractive_spans"]).strip()
        if not text:
            return []
        if text not in refs:
            refs.append(text)
    if "Yes" in refs and "No" in refs:
        return []
    return refs


def export_prepared(prepared: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use IDs, actual full bindings and existing packet records, without content hashes."""
    run = read_json(prepared / "run.json")
    if run["status"] != "COMPLETED":
        raise ValueError("Scoring input requires a completed branch preparation")
    collection_run = read_json(Path(run["collection"]) / "run.json")
    controls_path = Path(collection_run["controls"])
    controls = {(c["source_group"], c["request_id"]): c for c in read_jsonl(controls_path)}
    rows = read_jsonl(prepared / "states.jsonl")
    records, states = [], []
    for index, case in enumerate(read_json(prepared / "cases.json")):
        row = rows[case["state_index"]]
        meta = row["metadata"]
        if (meta["event_id"] != case["event_id"] or meta["family"] != case["family"]
                or meta["split"] != "train"):
            raise ValueError("Functional training input requires the actual TRAIN state")
        control = controls[(case["family"], case["request_id"])]
        if control["split"] != "train":
            raise ValueError("Reference research role differs from the training source")
        bindings = {a.id: asdict(a) for a in payload_actions(row)}
        refs = qasper_references(control)
        states.append(row)
        for branch_index, branch in enumerate(case["branches"]):
            action = branch["action"]
            if bindings.get(action["id"]) != action:
                raise ValueError("Executed full action differs from the student's menu")
            wire = json.loads(branch["readout_request"]["messages"][1]["content"])
            records.append({"event_id": case["event_id"], "family": case["family"],
                "research_split": meta["split"], "action": action,
                "packet_ref": {"path": str((prepared / "cases.json").resolve()),
                               "case_index": index, "branch_index": branch_index},
                "reference_set_id": {"path": str(controls_path.resolve()),
                                     "family": case["family"], "request_id": case["request_id"]},
                "continuation": {"policy": run["continuation_policy"],
                                 "steps": run["continuation_steps"],
                                 "terminal_handoff": run.get("terminal_handoff", "current")},
                "execution_status": "completed" if branch["execution_result"]["ok"] else "failed",
                "wire": wire, "references": refs})
    return records, states


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--prepared", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    all_records, all_states, seen = [], [], set()
    for path in args.prepared:
        records, states = export_prepared(path)
        for row in states:
            identity = row["metadata"]["event_id"]
            if identity in seen:
                raise ValueError("Duplicate event: declare separate continuation datasets")
            seen.add(identity)
        all_records.extend(records)
        all_states.extend(states)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, rows in (("packets.jsonl", all_records), ("states.jsonl", all_states)):
        with (args.output / name).open("x") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "run.json", {
        "status": "COMPLETED", "prepared": [str(p.resolve()) for p in args.prepared],
        "states": len(all_states), "families": len({r["family"] for r in all_records}),
        "packets": len(all_records),
        "packets_with_native_references": sum(bool(r["references"]) for r in all_records),
        "execution_status": dict(Counter(r["execution_status"] for r in all_records)),
        "no_sha_validation": True, "Host_calls": 0,
        "scope": "Reused actual TRAIN executions. No new branches; all original continuation "
                 "depths retained. Native references are offline only; student states unchanged.",
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu}})


if __name__ == "__main__":
    main()
