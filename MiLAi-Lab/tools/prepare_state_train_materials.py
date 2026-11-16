"""Prepare all public STATE train observation streams; no model or domain execution."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from milai_lab.datasets.state_training import load_training_streams
from milai_lab.harness.artifact_io import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    domains = ["travel", "customer_support", "shopping_assistant"]
    streams, provenance = load_training_streams(args.source, domains)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "LICENSE").write_text(
        (args.source / "LICENSE").read_text(encoding="utf-8"), encoding="utf-8")
    with (args.output / "streams.jsonl").open("w", encoding="utf-8") as stream:
        for row in streams:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "provenance.json", {"trajectories": provenance})
    write_json(args.output / "pilot-selection.json", {
        "status": "PREPARED_NOT_EXECUTED", "selection": "first2native-train-IDs/domain",
        "stream_ids": [row["id"] for domain in domains
                       for row in [s for s in streams if s["domain"] == domain][:2]],
        "scope": "Future sequential source ingestion and real View build/refresh acceptance; "
                 "not an official STATE score or a sample selected by teacher success."})
    report = {"status": "PUBLIC_TRAIN_MATERIALS_PREPARED_NO_VIEWS_OR_LABELS",
        "source": str(args.source), "trajectories": len(streams),
        "domains": dict(Counter(row["domain"] for row in streams)),
        "sources": sum(len(row["sources"]) for row in streams),
        "tool_observations": sum(len(row["observations"]) for row in streams),
        "public_user_checkpoints": sum(len(row["checkpoints"]) for row in streams),
        "nonterminal_user_checkpoints": sum(not c["terminal"]
            for row in streams for c in row["checkpoints"]),
        "nonterminal_checkpoints_with_prior_tools": sum(not c["terminal"] and any(
            o["source_index"] < c["source_count"] for o in row["observations"])
            for row in streams for c in row["checkpoints"]),
        "tools": dict(Counter(o["tool_name"] for row in streams for o in row["observations"])),
        "native_test_bodies_or_environments_loaded": False,
        "assistant_prose_ingested": False, "live_object_authority_minted": False,
        "source_timestamps_invented": False, "teacher_actions_as_operation_gold": False,
        "independent_source_groups_claimed": False, "new_operation_labels": 0,
        "model_calls": 0, "domain_tool_calls_executed": 0, "views_generated": 0,
        "no_sha_validation": True, "ledger_recorded": False,
        "compute": {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu}}
    write_json(args.output / "preparation.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
