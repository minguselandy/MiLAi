"""Project reviewed source cuts into ordinary Host histories, with offline proofs separate."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def project_case(
    sample: dict[str, Any], case: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    turns = [((segment["segment_index"], i), turn)
             for segment in sorted(sample["conversations"], key=lambda s: s["segment_index"])
             for i, turn in enumerate(segment["dialogue"], 1)]
    steps, originals, contexts = [], [], {}
    previous = (0, 0)
    for index, cut in enumerate(case["cuts"]):
        position = tuple(cut["through"])
        if position <= previous or not any(p == position and t["role"] == "user"
                                           for p, t in turns):
            raise ValueError("Each cut must advance to an actual user turn")
        incoming = []
        for (segment, ordinal), turn in turns:
            if not previous < (segment, ordinal) <= position:
                continue
            source_id = f"s{segment}t{ordinal}"
            incoming.append({"session_id": f"source-session-{segment}",
                "event_key": source_id, "role": turn["role"], "content": turn["content"],
                "occurred_at": None})
            originals.append({"id": source_id, "role": turn["role"],
                              "content": turn["content"]})
        for repeat in (False, True):
            step_id = f"stage-{index}" + ("-repeat" if repeat else "")
            steps.append({"id": step_id, "kind": "task",
                "session": "query" if index == 0 else "query-reopened",
                "content": case["query"], "occurred_at": None, "query_time": None,
                "incoming_sources": [] if repeat else incoming,
                "expected": cut["answer"]})
            contexts[step_id] = {"context": f"stage-{index}", "answer": cut["answer"],
                "support_sets": cut["support_sets"], "through": list(position)}
        previous = position
    identity = "memops_" + case["family"]
    history = {"id": identity, "source_family": identity, "split": "train",
               "task_count": len(steps), "steps": steps}
    labels = {"family": identity, "split": "train", "sources": originals,
              "offline_review": {"steps": contexts,
                  "status": "author-reviewed source-task sufficiency, not operation gold",
                  "source_file": case["file"]}}
    return history, labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    review = read_json(args.review)
    histories, labels = [], []
    for case in review["cases"]:
        for assignment in review["family_assignments"]:
            if assignment[case["family"]] != "train":
                raise ValueError("Only jointly assigned training families enter this preparation")
        history, label = project_case(read_json(Path(review["source_root"]) / case["file"]), case)
        histories.append(history)
        labels.append(label)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "histories.json", {"version": review["version"],
        "scope": review["scope"], "histories": histories})
    write_json(args.output / "source-review.json", {"version": review["version"],
        "scope": "Offline proofs and expected meanings; never passed to Host input",
        "families": labels})


if __name__ == "__main__":
    main()
