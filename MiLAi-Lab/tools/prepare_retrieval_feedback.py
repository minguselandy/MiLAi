"""Attach explicit reviews to actual same-before branches without labelling other actions."""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from feedback_outcomes import paired_outcomes, reached_outcomes
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.memory_control_learning import decision_example
from quality_feedback import quality_counts
from retrieval_feedback import (
    RESOURCE_FIELDS,
    feedback_counts,
    resource_preference,
    validate_feedback,
)


def compile_collected_feedback(raw: list[dict[str, Any]], reviews: list[dict[str, Any]],
                               *, split: str = "train") -> list[dict[str, Any]]:
    """Reuse a real last policy decision and a same-before raw-delivery alternative."""
    by_capture = {str(Path(row["metadata"]["path"]).resolve()): row for row in raw}
    rows = []
    for review in reviews:
        capture = Path(review["capture"]).resolve()
        row = copy.deepcopy(by_capture[str(capture)])
        if row["metadata"]["split"] != split or row["gold"]:
            raise ValueError("Collected feedback needs masked states in the declared split")
        call = read_json(capture / "call.json")
        expected = decision_example({"before": call["initial_observation"],
                                     "actions": call["initial_actions"]}, {})
        if any(row[k] != expected[k] for k in ("state", "questions")):
            raise ValueError("Exported state differs from the actual captured decision")
        left, right = review["current_action"]["id"], review["baseline_action"]["id"]
        if left == right:
            raise ValueError("Identical bindings do not create a preference pair")
        origins = {left: review["current_origin"], right: review["baseline_origin"]}
        outcomes = paired_outcomes(capture, origins)
        if (outcomes[left]["action"] != review["current_action"]
                or outcomes[right]["action"] != review["baseline_action"]):
            raise ValueError("Reviewed parameters differ from executed bindings")
        quality = review["quality_before_resource_tiebreak"]
        if (any(o["readout_status"] != "COMPLETED" for o in outcomes.values())
                and quality["answer"] != "unknown"):
            raise ValueError("An incomplete final answer remains unknown for pair supervision")
        resources = {side: {k: review["resources"][name][k] for k in RESOURCE_FIELDS}
                     for side, name in (("left", "current"), ("right", "baseline"))}
        cost = resource_preference(resources["left"], resources["right"])
        labels = {target: cost if label == "tie" and cost in {"left", "right"} else label
                  for target, label in quality.items()}
        pair = {"left": left, "right": right, **labels, "basis": {
            "quality_before_resource_tiebreak": copy.deepcopy(quality),
            "resource_order": {**resources, "componentwise_preference": cost},
            "content_target": review["target"], "source_review": review["review"],
            "limitations": review["limitation"],
            "scope": "Source-author quality before cost; legacy cost tie-break stored separately "
                     "from the quality targets used by the new masked objectives."},
            "tool_statuses": [outcomes[k]["tool_status"] for k in (left, right)],
            "host_readout_statuses": [outcomes[k]["readout_status"] for k in (left, right)]}
        row["feedback"] = {"capture": str(capture), "comparisons": [pair], "outcomes": origins,
            "reviewer": review["reviewer"],
            "protocol": "collected_last_decision_vs_same_before_raw_delivery_v1"}
        row["metadata"].update(label_status="reviewed_branch_pairs_other_actions_unknown",
            feedback_stratum="pure_delivery" if review["pure_delivery"] else "acquisition_or_stop")
        validate_feedback(row)
        rows.append(row)
    if len({r["metadata"]["event_id"] for r in rows}) != len(rows):
        raise ValueError("A collected state was reviewed twice")
    return rows


def compared_branch(path: Path, state_protocol: bool) -> tuple[
        dict[str, Any], dict[str, Any], bool]:
    """Read the existing protocol's actual result, without manufacturing a legacy wrapper."""
    if state_protocol:
        branch = read_json(path / "retrieval/replay.json")
        run = read_json(path / "run.json")
        if branch["intervention"] != run["recipe"]["intervention"]:
            raise ValueError("STATE branch result differs from its declared intervention")
        return branch, run["recipe"]["policy"], (
            branch["status"] == "COMPLETED"
            and branch["frozen_request_and_allowance_equal"]
            and branch["frozen_initial_observation_and_actions_equal"])
    branch = read_json(path / "replay.json")
    return branch, branch["policy"], (branch["status"] == "COMPLETED"
        and branch["result"]["frozen_initial_observation_and_actions_equal"])


def compile_reached_feedback(
    raw: list[dict[str, Any]], reviews: list[dict[str, Any]], *, split: str = "train",
) -> list[dict[str, Any]]:
    """Compile actual origins; quality targets stay in their explicit pre-cost basis."""
    by_event = {row["metadata"]["event_id"]: row for row in raw}
    if len(by_event) != len(raw):
        raise ValueError("Raw reached-state identities are not unique")
    rows, seen = [], set()
    for review in reviews:
        event_id = review["event_id"]
        if event_id in seen:
            raise ValueError("A reached state was reviewed twice")
        seen.add(event_id)
        row = copy.deepcopy(by_event[event_id])
        capture = Path(review["capture"]).resolve()
        if (row["metadata"]["split"] != split or row["gold"]
                or Path(row["metadata"]["path"]).resolve() != capture):
            raise ValueError("Reached feedback requires the actual masked state and declared split")
        call = read_json(capture / "call.json")
        expected = decision_example({"before": call["initial_observation"],
                                     "actions": call["initial_actions"]}, {})
        if any(row[key] != expected[key] for key in ("state", "questions")):
            raise ValueError("Reached feedback changed the actual before or full menu")
        origins = review["outcomes"]
        outcomes = reached_outcomes(capture, origins)
        comparisons = []
        compared: set[str] = set()
        for comparison in review["comparisons"]:
            left, right = comparison["left"], comparison["right"]
            if left not in outcomes or right not in outcomes:
                raise ValueError("Every compared choice requires its own actual first outcome")
            compared.update((left, right))
            basis = copy.deepcopy(comparison["basis"])
            quality = basis["quality_before_resource_tiebreak"]
            if (any(outcomes[key]["readout_status"] != "COMPLETED" for key in (left, right))
                    and quality["answer"] != "unknown"):
                raise ValueError("An incomplete final answer remains unknown for pair supervision")
            order = basis["resource_order"]
            cost = resource_preference(order["left"], order["right"])
            order["componentwise_preference"] = cost
            labels = {target: cost if quality[target] == "tie" and cost in {"left", "right"}
                      else quality[target] for target in ("answer", "delivery")}
            comparisons.append({"left": left, "right": right,
                **labels, "basis": basis,
                "tool_statuses": [outcomes[key]["tool_status"] for key in (left, right)],
                "host_readout_statuses": [outcomes[key]["readout_status"]
                                         for key in (left, right)]})
        if compared != set(outcomes):
            raise ValueError("Keep only actual outcomes used by the declared state comparisons")
        row["feedback"] = {"capture": str(capture), "comparisons": comparisons,
            "outcomes": copy.deepcopy(origins), "reviewer": review["reviewer"],
            "protocol": "actual_reached_state_common_continuation_origins_v1"}
        row["metadata"].update(label_status="reviewed_branch_pairs_other_actions_unknown",
                               feedback_stratum="actual_reached_state_common_continuation")
        validate_feedback(row)
        rows.append(row)
    return rows


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
            loaded = [compared_branch(Path(comparison[side + "_case"]),
                call.get("schema") in {"state_dynamic_retrieval_call_v1",
                                       "state_dynamic_retrieval_decision_v1"})
                for side in ("left", "right")]
            branches = [value[0] for value in loaded]
            readout_statuses = (["NOT_EVALUATED", "NOT_EVALUATED"] if delivery_only else [
                read_json(Path(comparison[side + "_case"]) / "host-readout/readout.json")["status"]
                for side in ("left", "right")])
            if any(Path(branch["captured_call"]).resolve() != capture.resolve()
                   for branch in branches):
                raise ValueError("Compared branches came from different captures")
            actions = [branch["intervention"]["first_action"] for branch in branches]
            if any(action not in call["initial_actions"] for action in actions):
                raise ValueError("Compared action or its parameters differ from actual options")
            if (loaded[0][1] != loaded[1][1]
                    or branches[0]["intervention"]["continuation_steps"]
                    != branches[1]["intervention"]["continuation_steps"]):
                raise ValueError("First-action comparison requires a common continuation policy")
            tools_completed = all(value[2] for value in loaded)
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
                "matched_completed_tool_conditions": [value[2] for value in loaded],
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
    protocol = parser.add_mutually_exclusive_group()
    protocol.add_argument("--collected-last-decisions", action="store_true",
                          help="Compile collected-current and same-before raw-delivery origins")
    protocol.add_argument("--reached-decisions", action="store_true",
                          help="Compile actual common-continuation origins and terminal READ reuse")
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    raw = read_jsonl(args.raw)
    if (args.collected_last_decisions or args.reached_decisions) and args.delivery_only:
        parser.error("Origin-based protocols use their actual first readout records")
    if args.reached_decisions:
        rows = compile_reached_feedback(raw, read_json(args.reviews)["states"], split=args.split)
    elif args.collected_last_decisions:
        rows = compile_collected_feedback(raw, read_json(args.reviews)["records"], split=args.split)
    else:
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
        **({"quality_before_cost": {target: quality_counts(rows, target, "quality-tie")
            for target in ("answer", "delivery")},
            "feedback_label_scope": "feedback is the compatible legacy cost-augmented view; "
                "quality_before_cost and the retained quality-tie training objective use "
                "explicit pre-cost judgments, including quality ties."}
           if args.reached_decisions else {}),
        "model_input_unchanged": True, "full_option_ce_labels_added": False,
        "scope": "One shared pair pool; arm chooses feedback target, not a different state set.",
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu},
        "ledger_recorded": False,
    })


if __name__ == "__main__":
    main()
