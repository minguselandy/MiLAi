"""Freeze the declared task-dev denominator and actual final pre-HANDOFF states."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control_learning import decision_example


def prepare_panel(collection: Path, protocol: dict[str, Any]) -> dict[str, Any]:
    driver = read_json(collection / "driver.json")
    if driver["status"] in {"RUNNING", "LAUNCHING"}:
        raise ValueError("Wait for the declared common collection to close")
    histories = read_json(collection / "fixture.json")["histories"]
    if [h["source_group"] for h in histories] != protocol["selection"]["source_ids"]:
        raise ValueError("Task-dev source order or denominator changed")
    captures: dict[tuple[str, str], tuple[Path, dict[str, Any]]] = {}
    for path in (collection / "frozen-retrieval-calls").glob("*/call.json"):
        call = read_json(path)
        key = (call["bank"], call["public_message"]["message_id"])
        if key in captures:
            raise ValueError("A supplied task has multiple original retrieval attempts")
        captures[key] = path.parent, call
    completed = {(r["history"], r["request"]): r for r in driver["completed"]}
    positions: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for history in histories:
        if history["split"] != "dev" or len(history["requests"]) != 1:
            raise ValueError("E1 task panel uses one declared question per dev paper")
        request = history["requests"][0]
        bank = (history["id"] if history.get("continuous") and not request.get("independent")
                else history["id"] + "-" + request["id"])
        position: dict[str, Any] = {"family": history["source_group"], "history": history["id"],
            "request_id": request["id"], "bank": bank, "status": "MISSING_ORIGINAL_CAPTURE",
            "evaluation_index": None, "baseline_readout": completed.get(
                (history["id"], request["id"]), {}).get("conditional_readout")}
        positions.append(position)
        if (bank, request["id"]) not in captures:
            continue
        initial, call = captures[bank, request["id"]]
        position.update(initial_capture=str(initial.resolve()), original_status=call["status"])
        settings = read_json(Path(call["source_root"]) / "input-freeze.json")["config"]
        control = settings["memory_control"]
        if (control["policy"] != "fixed_context" or call["host_request_generated"]
                or call["public_message"]["content"] != request["content"]):
            raise ValueError("Common task collection changed its raw policy or supplied task")
        if call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
            position["status"] = "UNCLOSED_ORIGINAL_CAPTURE"
            continue
        selections = [e for e in call.get("control_events", []) if e["phase"] == "decision_output"]
        if not selections:
            position["status"] = "NO_ACTUAL_DECISION"
            continue
        last = selections[-1]
        action, = [a for a in last["actions"] if a["id"] == last["selected"]]
        if action["kind"] != "HANDOFF":
            position.update(status="NO_REACHED_FINAL_HANDOFF", last_actual_action=action)
            continue
        captured = initial / "steps" / f"step-{last['step']:04d}" if last["step"] else initial
        state = read_json(captured / "call.json")
        if (state["initial_observation"] != last["before"]
                or state["initial_actions"] != last["actions"]):
            raise ValueError("Final decision snapshot differs from the actual original decision")
        index = len(rows)
        row = decision_example({"before": state["initial_observation"],
            "actions": state["initial_actions"]}, {"row": index, "state_id": index,
            "event_id": f"{collection.resolve()}/{call['call_id']}/step-{last['step']}",
            "family": history["source_group"], "split": "dev", "task": "memory_operation",
            "capture": str(captured.resolve()), "path": str(captured.resolve()),
            "training_event": history["id"] + "/" + request["id"],
            "control_step": last["step"], "collection_policy": "fixed_context"})
        rows.append(row)
        position.update(status="ACTUAL_PRE_HANDOFF_EXPORTED", evaluation_index=index,
                        capture=str(captured.resolve()), baseline_action=action)
    return {"positions": positions, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    start = time.process_time()
    result = prepare_panel(args.collection, read_json(args.protocol))
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "states.jsonl").open("w") as stream:
        for row in result["rows"]:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "panel.json", {
        "status": "FIXED_TASK_DENOMINATOR_AND_REACHED_STATES_PREPARED;NO_MODEL_SELECTION",
        "collection": str(args.collection.resolve()), "protocol": str(args.protocol.resolve()),
        "planned_positions": len(result["positions"]), "actual_states": len(result["rows"]),
        "positions": result["positions"], "model_calls": 0, "no_sha_validation": True,
        "ledger_recorded": False, "cpu_seconds_pending": time.process_time()-start,
        "scope": "Every declared source remains in the task denominator. Missing final HANDOFF "
            "states are not replaced with earlier/ideal states. Full original menus, not a "
            "HANDOFF sub-menu, enter scoring. No gold/answer/annotation enters model inputs."})


if __name__ == "__main__":
    main()
