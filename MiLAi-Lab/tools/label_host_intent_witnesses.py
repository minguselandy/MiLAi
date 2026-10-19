"""Compile request-approved original-source witnesses on actual recorded states."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional_state import reference_key
from milai_lab.methods.retrieval_supervision import (
    annotate_decisions,
    original_witness_preferences,
)
from milai_lab.providers.contextual_capacity import HostCapacity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("states", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.states.read_text().splitlines()]
    contracts = {c["event_prefix"]: c for c in read_json(args.reviews)["requests"]}
    indexed = {r["metadata"]["event_id"]: r for r in rows}
    capacity = HostCapacity(read_json(args.config)["entrypoints"]["functional"]["capacity"])
    results: dict[str, Any] = {}
    annotations = []
    for row in rows:
        event_id = row["metadata"]["event_id"]
        prefix, step_text = event_id.rsplit("/", 1)
        review = contracts.get(prefix)
        if review is None:
            continue
        if review["request"] != row["state"]["task"]["retrieval_request"]:
            raise ValueError("Review is for a different actual Host request")
        result_path = row["metadata"]["result_path"]
        if result_path not in results:
            results[result_path] = read_json(Path(result_path))
        result = results[result_path]
        sources = {s["event_id"]: s for s in result["sources"]}
        proofs = []
        for witnesses in review["support_sets"]:
            selected = set()
            for witness in witnesses:
                matches = [s["event_id"] for s in sources.values()
                    if s["session"] == witness["session"]
                    and s["capture_key"] == witness["event_key"]
                    and s["role"] == witness["role"]]
                if len(matches) != 1:
                    raise ValueError("Witness does not identify one actual source/role")
                selected.add(matches[0])
            proofs.append(selected)
        successor = indexed.get(prefix + "/" + str(int(step_text) + 1))
        observed_search = None
        if successor is not None:
            last = successor["state"]["last_result"]
            if last and last.get("status") == "searched" and last["action"]["kind"] == "SEARCH":
                observed_search = (last["action"]["id"],
                    successor["metadata"]["actual_bindings"]["candidate_materials"])
        call_id = prefix.rsplit("/", 1)[1]
        key = "retrieval:" + reference_key([result["session"], result["message_id"], call_id])
        preferred, status = original_witness_preferences(row, proofs=proofs, sources=sources,
            return_key=key, token_count=capacity.text_tokens, observed_search=observed_search)
        annotations.append({"event_id": event_id, "preferred_actions": preferred,
            "basis": review["basis"], "preference_reason": status,
            "support_sets": review["support_sets"],
            "request_review": review["request_review"],
            "reviewer": "assistant author; not independent judgment",
            "scope": "Whole-source, request-approved preferences; exact return budget checked. "
                     "No automatic USE_VIEW/REFRESH positives or native-answer gold."})
    labelled = annotate_decisions(rows, annotations)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "compiled-reviews.json", {"reviews": annotations})
    for split in ("train", "dev"):
        with (args.output / f"{split}.jsonl").open("w") as stream:
            for row in labelled:
                if row["metadata"]["split"] == split:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"states": len(rows), "reviewed_requests": len(contracts),
        "reviewed_states": len(annotations), "labelled": sum(bool(r["gold"]) for r in labelled),
        "reasons": dict(Counter(r["preference_reason"] for r in annotations)),
        "families_labelled": len({r["metadata"]["family"] for r in labelled if r["gold"]}),
        "model_calls": 0, "inputs_changed": False, "states_source": str(args.states),
        "reviews_source": str(args.reviews)}
    write_json(args.output / "labels.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
