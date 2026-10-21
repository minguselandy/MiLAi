"""Attach explicit reviews to actual same-before branches without labelling other actions."""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.memory_control_learning import decision_example
from retrieval_feedback import feedback_counts, validate_feedback


def compile_feedback(
    raw: list[dict[str, Any]], reviews: list[dict[str, Any]],
    *, split: str = "train", delivery_only: bool = False,
) -> list[dict[str, Any]]:
    by_event = {row["metadata"]["event_id"]: row for row in raw}
    if len(by_event) != len(raw):
        raise ValueError("Raw state identities are not unique")
    rows = []
    seen = set()
    for review in reviews:
        event_id = review["event_id"]
        if event_id in seen:
            raise ValueError("Duplicate state review")
        seen.add(event_id)
        row = copy.deepcopy(by_event[event_id])
        if row["metadata"]["split"] != split or row["gold"]:
            raise ValueError("Feedback collection requires masked states from the declared split")
        capture = Path(review["capture"])
        call = read_json(capture / "call.json")
        expected = decision_example(
            {"before": call["initial_observation"], "actions": call["initial_actions"]}, {})
        if any(row[key] != expected[key] for key in ("state", "questions")):
            raise ValueError("Review capture differs from the exported actual initial state")
        comparisons = []
        for comparison in review["comparisons"]:
            branches = [read_json(Path(comparison[side + "_case"]) / "replay.json")
                        for side in ("left", "right")]
            readout_statuses = (["NOT_EVALUATED", "NOT_EVALUATED"] if delivery_only else [
                read_json(Path(comparison[side + "_case"]) / "host-readout/readout.json")["status"]
                for side in ("left", "right")])
            if any(Path(branch["captured_call"]).resolve() != capture.resolve()
                   for branch in branches):
                raise ValueError("Compared branches came from different captures")
            actions = [branch["intervention"]["first_action"] for branch in branches]
            if any(action not in call["initial_actions"] for action in actions):
                raise ValueError("Compared action or its parameters differ from actual options")
            if (branches[0]["policy"] != branches[1]["policy"]
                    or branches[0]["intervention"]["continuation_steps"]
                    != branches[1]["intervention"]["continuation_steps"]):
                raise ValueError("First-action comparison requires a common continuation policy")
            tools_completed = all(
                branch["status"] == "COMPLETED"
                and branch["result"]["frozen_initial_observation_and_actions_equal"]
                for branch in branches)
            if not tools_completed and any(comparison[target] != "unknown"
                                           for target in ("answer", "delivery")):
                raise ValueError("Unclosed tool comparisons remain unknown")
            if (any(status != "COMPLETED" for status in readout_statuses)
                    and comparison["answer"] != "unknown"):
                raise ValueError(
                    "Unclosed or unevaluated Host readouts leave answer feedback unknown")
            comparisons.append({
                "left": actions[0]["id"], "right": actions[1]["id"],
                **{key: copy.deepcopy(comparison[key]) for key in (
                    "answer", "delivery", "basis", "left_case", "right_case")},
                "tool_statuses": [branch["status"] for branch in branches],
                "host_readout_statuses": readout_statuses,
            })
        row["feedback"] = {"capture": str(capture), "comparisons": comparisons,
                           "reviewer": review["reviewer"]}
        row["metadata"]["label_status"] = "reviewed_branch_pairs_other_actions_unknown"
        validate_feedback(row)
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--split", choices=("train", "dev"), default="train")
    parser.add_argument("--delivery-only", action="store_true",
                        help="Do not read Host readouts; every answer comparison must stay unknown")
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    raw = read_jsonl(args.raw)
    rows = compile_feedback(raw, read_json(args.reviews)["states"], split=args.split,
                            delivery_only=args.delivery_only)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "feedback.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    write_json(args.output / "preparation.json", {
        "status": "REVIEWED_COMMON_PAIR_POOL_NOT_FITTED",
        "raw": str(args.raw), "reviews": str(args.reviews), "raw_states": len(raw),
        "reviewed_states": len(rows), "unreviewed_states": len(raw) - len(rows),
        "split": args.split,
        "host_readout_evaluation": "not_used" if args.delivery_only else "required",
        "families": len({row["metadata"]["family"] for row in rows}),
        "feedback": {target: feedback_counts(rows, target) for target in ("answer", "delivery")},
        "model_input_unchanged": True, "full_option_ce_labels_added": False,
        "scope": "One shared pair pool; arm chooses feedback target, not a different state set.",
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu},
        "ledger_recorded": False,
    })


if __name__ == "__main__":
    main()
