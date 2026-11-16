"""Score one explicitly selected event split through the actual metered HTTP adapter."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import http_budget_scope
from milai_lab.methods.laya_impact import CRITERIA, impact_payload
from milai_lab.runners.laya_impact import impact_model_call


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--budget", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:7870")
    args = parser.parse_args()
    config = {"base_url": args.base_url, "model": args.model,
              "max_len": 2048, "head_max_len": 256, "timeout_seconds": 180.0}
    settings = {"budget_path": str(args.budget), "laya_impact": config,
        "http_ownership_profile": "serialized_ledger_owner_v1",
        "http_ownership_domain": {"deployment_id": "milai-laya-impact-local-cpu-v1",
                                  "clients": [config]}}
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "config.json", {"settings": settings, "data": str(args.data),
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_config": read_json(args.checkpoint / "rl_agent_config.json")})
    confusion: Counter[tuple[str, str]] = Counter()
    complete_events = exact_events = 0
    with http_budget_scope(settings) as budget:
        assert budget is not None
        write_json(args.output / "accounting-start.json", budget.state)
        for row in rows:
            aliases = list(row["metadata"]["labels"])
            schema = {"properties": {"roots": {"items": {"enum": aliases}}}}
            messages = [{"role": "user", "content": json.dumps(row["state"], ensure_ascii=False)}]
            if impact_payload(messages, schema) != {k: row[k] for k in ("state", "questions")}:
                raise ValueError("Runtime and training payload differ")
            event = row["metadata"]["event_id"]
            call = impact_model_call(lambda *_: {}, settings, budget=budget,
                                     root=args.output / "typed-http" / event)
            selected = call("impact", messages, schema)
            predicted = {f"unit_{i}": "direct_root" if alias in selected["roots"] else
                "preserve_successor" if alias in selected["preserve"] else "other"
                for i, alias in enumerate(aliases)}
            for qid, gold in row["expected"].items():
                confusion[gold, predicted[qid]] += 1
            fully_labelled = len(row["expected"]) == len(row["questions"])
            complete_events += fully_labelled
            exact_events += fully_labelled and predicted == row["expected"]
            write_json(args.output / "predictions" / f"{event}.json", {
                "event_id": event, "predicted": predicted, "expected": row["expected"],
                "selection": selected, "fully_labelled": fully_labelled})
        write_json(args.output / "accounting-end.json", budget.state)
    counts = {label: {
        "true_positive": confusion[label, label],
        "gold": sum(v for (g, _), v in confusion.items() if g == label),
        "false_positive": sum(v for (g, p), v in confusion.items() if p == label and g != label),
        "false_negative": sum(v for (g, p), v in confusion.items() if g == label and p != label),
    } for label in CRITERIA}
    write_json(args.output / "result.json", {"status": "COMPLETED", "events": len(rows),
        "fully_labelled_events": complete_events, "exact_events": exact_events,
        "labelled_questions": sum(confusion.values()),
        "correct_questions": sum(v for (g, p), v in confusion.items() if g == p),
        "roles": counts, "calibrated": False,
        "scope": "Controller diagnostic only; no Writer/Reader/state-quality result"})


if __name__ == "__main__":
    main()
