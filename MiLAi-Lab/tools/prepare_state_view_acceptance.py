"""Prepare conditional STATE material probes for the existing captured retrieval runner."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.datasets.state_training import view_acceptance_history
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("materials", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    selection = read_json(args.materials / "pilot-selection.json")
    streams = {row["id"]: row for row in read_jsonl(args.materials / "streams.jsonl")}
    histories = [view_acceptance_history(streams[key]) for key in selection["stream_ids"]]
    config = read_json(args.config)
    settings = config["entrypoints"]["functional"]
    settings["config_version"] = "generalization-state-view-acceptance-v2"
    settings["edit_interface_version"] = "I2"
    settings["retrieval_tool"] = "rich"
    settings["host_source_arrivals"] = True
    settings["edit_features"] = {**settings.get("edit_features", {}), "source_metadata": True}
    settings["memory_control"]["policy"] = "view_cache"
    settings["business_tools"] = []
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "histories.json", {
        "schema": "state_view_acceptance_histories_v1", "histories": histories,
        "scope": "Conditional retrieval-only acceptance on public historical training material; "
                 "not native STATE task execution or an official score."})
    write_json(args.output / "config.json", config)
    report = {"status": "PREPARED_NOT_EXECUTED", "source_materials": str(args.materials),
        "selection": selection, "histories": len(histories),
        "planned_retrieval_calls": sum(len(h["requests"]) for h in histories),
        "frontiers": [{"id": h["id"], **h["frontiers"]} for h in histories],
        "runtime": "Existing run_host_intent_retrieval.py --given-requests "
                   "--capture-control-steps --policies view_cache --interfaces rich --split train",
        "known_refs": "Only actual earlier returned evidence references, bound at execution",
        "view_creation": "Actual model query-structure path; no fixture stored_revisions",
        "branches": "Existing prepare_view_feedback_branches --include-control-steps; "
                    "run_frozen_retrieval_calls without Host readout for these given requests",
        "host_answer_requested": False, "business_actions_executed": 0,
        "views_generated": 0, "new_operation_labels": 0, "model_calls": 0,
        "no_sha_validation": True, "ledger_recorded": False,
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu}}
    write_json(args.output / "preparation.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
