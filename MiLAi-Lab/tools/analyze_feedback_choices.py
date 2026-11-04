"""Report saved full-menu choices against already executed, source-reviewed branches."""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from feedback_choices import (
    baseline_choice,
    relative_quality,
    saved_decisions,
    summarize_choices,
)
from feedback_outcomes import paired_outcomes
from milai_lab.harness.artifact_io import read_json, write_json
from quality_feedback import validate_quality_pool

TYPE_ORDER = ("SEARCH", "READ", "USE_VIEW", "REFRESH_VIEW", "HANDOFF")


def executed_outcomes(row: dict[str, Any], call: dict[str, Any]) -> dict[str, Any]:
    """Read first attempts, including failures; require the same local continuation."""
    if "outcomes" in row["feedback"]:
        capture = Path(row["feedback"]["capture"])
        if read_json(capture / "call.json") != call:
            raise ValueError("Outcome provenance and evaluated capture differ")
        return paired_outcomes(capture, row["feedback"]["outcomes"])
    actions = {a["id"]: a for a in call["initial_actions"]}
    cases: dict[str, str] = {}
    for pair in row["feedback"]["comparisons"]:
        for side in ("left", "right"):
            key, case = pair[side], pair[side + "_case"]
            if key in cases and cases[key] != case:
                raise ValueError("One binding has multiple outcomes in this declared comparison")
            cases[key] = case
    outcomes = {}
    conditions = []
    for key, case in cases.items():
        path = Path(case)
        replay = read_json(path / "replay.json")
        readout = read_json(path / "host-readout" / "readout.json")
        frame = read_json(path / "host-readout" / "frame.json")
        if frame["call_id"] != call["call_id"]:
            raise ValueError("Branch readout belongs to a different captured Host call")
        if replay["intervention"]["first_action"] != actions[key]:
            raise ValueError("Executed binding differs from the offered full action")
        if replay["status"] not in {"COMPLETED", "FAILED"} or readout["status"] not in {
                "COMPLETED", "FAILED"}:
            raise ValueError("Choice analysis needs terminal original attempts")
        if replay["status"] == "COMPLETED" and not (
                replay["result"]["frozen_request_and_allowance_equal"]
                and replay["result"]["frozen_initial_observation_and_actions_equal"]):
            raise ValueError("Executed branch changed its captured before state or allowance")
        conditions.append((replay["policy"], replay["intervention"]["continuation_steps"]))
        outcomes[key] = {"case": case, "tool_status": replay["status"],
                         "readout_status": readout["status"]}
    if any(condition != conditions[0] for condition in conditions):
        raise ValueError("Compared outcomes have different continuation policies or budgets")
    return outcomes


def analyze(evaluation: Path, baseline: str, reads: int) -> dict[str, Any]:
    started, cpu = time.perf_counter(), time.process_time()
    run, decisions = saved_decisions(evaluation)
    records = []
    for capture, decision in decisions.items():
        row, call, prediction = (decision[k] for k in ("row", "call", "prediction"))
        if "feedback" not in row:
            continue
        validate_quality_pool([row])
        outcomes = executed_outcomes(row, call)
        executed = set(outcomes)
        actions = call["initial_actions"]
        keys = [a["id"] for a in actions]
        choice = prediction["choice"]
        reference = baseline_choice(call, baseline, reads)
        submenu = max((k for k in keys if k in executed),
                      key=lambda k: prediction["logits"][k], default=None)
        fixed = min(actions, key=lambda a: TYPE_ORDER.index(a["kind"]))["id"]
        choices = {"full_menu": choice, "executed_submenu": submenu, "fixed_type_order": fixed}
        quality, space = {}, {}
        for target in ("answer", "delivery"):
            quality[target] = {name: relative_quality(row, key, reference, target, executed)
                               for name, key in choices.items()}
            alternatives = [relative_quality(row, k, reference, target, executed)
                            for k in keys if k in executed and k != reference]
            space[target] = ("observed_better" if "win" in alternatives else "unknown"
                if reference not in executed or "unknown" in alternatives else "none_observed")
        records.append({"capture": capture, "event_id": row["metadata"]["event_id"],
            "family": row["metadata"]["family"], "split": row["metadata"]["split"],
            "evaluation_index": decision["evaluation_index"], "menu": actions,
            "choices": choices, "baseline": reference, "outcomes": outcomes,
            "full_menu_executed": choice in executed, "baseline_executed": reference in executed,
            "full_menu_readout_completed": (choice in executed
                and outcomes[choice]["readout_status"] == "COMPLETED"),
            "quality_vs_baseline": quality, "observed_improvement_space": space})
    return {"status": "CLOSED_SAVED_FULL_MENU_OBSERVATIONAL_DIAGNOSTIC",
        "evaluation": str(evaluation.resolve()), "checkpoint": run["checkpoint"],
        "operation_state": run["operation_state"], "baseline": baseline, "baseline_reads": reads,
        "fixed_type_order": list(TYPE_ORDER), "summary": summarize_choices(records),
        "records": records, "model_calls": 0, "model_weights_loaded": 0,
        "no_sha_validation": True, "ledger_recorded": False,
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started},
        "scope": "Same captured inputs, first branch attempts and declared fixed continuation. "
            "Full-menu argmax and executed-submenu argmax are separate. Unknown outcomes remain "
            "in coverage denominators. Pre-cost quality only; signed win/tie/loss is not a numeric "
            "task-success gain. Identical bindings are separate, not judged quality ties. "
            "Observed improvement space is finite-pool hindsight, not a policy. "
            "This local raw-context choice is not the end-to-end fixed-context Host baseline. "
            "Conditional change/stable and absolute answer-success gains need separate labels."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", choices=("raw_context", "raw_delivery", "rules"),
                        default="raw_context")
    parser.add_argument("--reads", type=int, default=4)
    args = parser.parse_args()
    write_json(args.output, analyze(args.evaluation, args.baseline, args.reads))


if __name__ == "__main__":
    main()
