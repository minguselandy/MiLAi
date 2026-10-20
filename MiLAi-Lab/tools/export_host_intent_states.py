"""Export actual closed Host decision inputs, masked until source-grounded annotation."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control_learning import decision_example


def export_states(
    root: Path, *, driver: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Export one caller-selected closed-position snapshot, including live runs."""
    if driver is None:
        driver = read_json(root / "driver.json")
    histories = {h["id"]: h for h in read_json(root / "fixture.json")["histories"]}
    rows: list[dict[str, Any]] = []
    results_by_profile: dict[str, dict[tuple[str, str], tuple[Path, dict[str, Any]]]] = {}
    for position in driver["completed"]:
        history = histories[position["history"]]
        request = next(r for r in history["requests"] if r["id"] == position["request"])
        profile = position.get("profile", position["policy"])
        bank = (history["id"] if history.get("continuous") and not request.get("independent") else
                history["id"] + "-" + position["request"])
        if profile not in results_by_profile:
            indexed = {}
            for path in (root / profile / "banks").glob("*/*-result.json"):
                result = read_json(path)
                indexed[result["bank"], result["message_id"]] = (path, result)
            results_by_profile[profile] = indexed
        indexed = results_by_profile[profile]
        result_key = (bank, position["request"])
        path, result = indexed[result_key if result_key in indexed else (bank, "request")]
        trace = next(path.parent.glob(path.name.replace("-result.json", "-trace-*.jsonl")))
        for line in trace.read_text().splitlines():
            event = json.loads(line)
            if (event.get("event") != "memory_control_step"
                    or event.get("phase") != "decision_input"):
                continue
            key = [profile, history["id"], position["request"],
                   event["retrieval_call_id"], str(event["step"])]
            metadata = {"family": history["source_group"], "split": history["split"],
                "row": len(rows), "event_id": "/".join(key),
                "training_event": "/".join(key[:3]), "interface": position.get("interface", "rich"),
                "collection_policy": position["policy"], "source_version": driver["source_version"],
                "result_path": str(path), "trace_path": str(trace),
                "task_status": result["status"], "actual_bindings": {key: event[key] for key in (
                    "candidate_materials", "opened_materials", "known_materials",
                    "observed_materials") if key in event}}
            rows.append(decision_example(event, metadata))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    snapshots = [(run, read_json(run / "driver.json")) for run in args.runs]
    rows = [row for run, driver in snapshots for row in export_states(run, driver=driver)]
    write_json(args.output / "closed-positions.json", {"runs": [
        {"run": str(run), "driver": driver} for run, driver in snapshots]})
    keys = [row["metadata"]["event_id"] for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate source decisions; name collection policies/profiles explicitly")
    for split in ("train", "dev"):
        with (args.output / f"{split}.jsonl").open("w") as stream:
            for row in rows:
                if row["metadata"]["split"] == split:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"status": "ACTUAL_STATES_EXPORTED_ALL_LABELS_MASKED",
        "runs": list(map(str, args.runs)),
        "states": len(rows), "labelled": 0,
        "closed_host_positions": sum(len(driver["completed"]) for _, driver in snapshots),
        "positions_with_states": len({row["metadata"]["training_event"] for row in rows}),
        "splits": dict(Counter(row["metadata"]["split"] for row in rows)),
        "interfaces": dict(Counter(row["metadata"]["interface"] for row in rows)),
        "families": len({row["metadata"]["family"] for row in rows}),
        "projection": "live operation_payload via decision_example; actual bindings outside state",
        "annotation": "No teacher action, operation availability or final answer becomes gold."}
    write_json(args.output / "export.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
