"""Export closed Host decision observations, without automatically labelling policy choices."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control_learning import decision_example


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run = read_json(args.run / "driver.json")
    args.output.mkdir(parents=True, exist_ok=False)
    examples: list[dict[str, Any]] = []
    redacted = 0
    for row in run["completed"]:
        root = Path(run.get("runtime_root", str(args.run))) / row["policy"]
        bank_name = "bank-" + str(run["histories"].index(row["history"]))
        bank = next(b["id"] for b in read_json(root / "bank-index.json")
                    if b["identity"]["bank"] == bank_name)
        folder = root / "banks" / bank
        message_id = next(m["id"] for m in read_json(folder / "message-index.json")
                          if m["identity"]["message_id"] == row["step"])
        path = folder / f"{message_id}-trace-0.jsonl"
        for event in (json.loads(line) for line in path.read_text().splitlines()):
            if event.get("event") != "memory_control_step":
                continue
            if "phase" not in event:
                redacted += 1
                continue
            if event["phase"] != "decision_input":
                continue
            examples.append(decision_example(event, {
                "family": row["history"], "row": row["step"], "state_id": len(examples),
                "event_id": f"{row['policy']}:{row['history']}:{row['step']}:{event['step']}",
                "training_event": row["step"], "policy": row["policy"],
                "source_version": run["source_version"], "trace": str(path),
                "decision_step": event["step"], "split": "functional_development"}))
    with (args.output / "unlabelled.jsonl").open("w") as stream:
        for example in examples:
            stream.write(json.dumps(example, ensure_ascii=False) + "\n")
    write_json(args.output / "summary.json", {"states": len(examples),
        "closed_messages": len(run["completed"]), "redacted_events_skipped": redacted,
        "gold_created": False, "source_run": str(args.run),
        "scope": "Functional development observations; no new training-family claim"})


if __name__ == "__main__":
    main()
