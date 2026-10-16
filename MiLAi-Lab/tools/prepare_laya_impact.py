"""Export source-reviewed events with family splits before expanding unit questions."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.methods.laya_impact import CRITERIA, impact_payload


def prepare(rows: list[dict[str, Any]], source_root: Path) -> dict[str, list[dict[str, Any]]]:
    families: dict[str, str] = {}
    result: dict[str, list[dict[str, Any]]] = {s: [] for s in (
        "train", "dev", "calibration", "test")}
    for row in rows:
        family, split = row["family_id"], row["split"]
        if family in families and families[family] != split:
            raise ValueError(f"Source family crosses splits: {family}")
        families[family] = split
        request = json.loads((source_root / row["request_path"]).read_text())
        messages = request["messages"]
        supplied = json.loads(messages[-1]["content"])
        schema = supplied["response_schema"]
        aliases = schema["properties"]["roots"]["items"]["enum"]
        payload = impact_payload(messages, schema)
        if set(row["labels"]) != set(aliases):
            raise ValueError(f"Review must cover each actual unit: {row['event_id']}")
        expected = {}
        for i, alias in enumerate(aliases):
            label = row["labels"][alias]["label"]
            if label is not None:
                if label not in CRITERIA:
                    raise ValueError(f"Unknown role: {label}")
                expected[f"unit_{i}"] = label
        # Metadata is deliberately outside both state and questions.
        result[split].append({**payload, "expected": expected, "metadata": row})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.reviews.read_text().splitlines() if line.strip()]
    grouped = prepare(rows, args.source_root)
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {}
    for split, events in grouped.items():
        (args.output / f"{split}.jsonl").write_text("".join(
            json.dumps(event, ensure_ascii=False) + "\n" for event in events))
        summary[split] = {
            "events": len(events),
            "families": sorted({e["metadata"]["family_id"] for e in events}),
            "labels": dict(Counter(v for e in events for v in e["expected"].values())),
            "masked": sum(len(e["questions"]) - len(e["expected"]) for e in events),
        }
    (args.output / "preparation.json").write_text(json.dumps({
        "reviews": str(args.reviews), "source_root": str(args.source_root),
        "splits": summary, "augmentation": "none", "calibrated": False,
        "scope": "exposed author development; family-separated learning diagnostic",
        "model_calls": 0,
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
