"""Offline identity check for the fixed LangMem recipe and exposed inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.baselines.langmem_agent import RECIPE_ID
from milai_lab.baselines.langmem_identity import sha256_file, verify_foundation_lock
from milai_lab.datasets.merit import load_exposed_arc
from milai_lab.harness.contextual_artifacts import read_json, write_json

LAB = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--lock", type=Path, default=LAB / "data/locks/langmem-foundation.lock.json",
    )
    parser.add_argument("--merit-selection", type=Path, required=True)
    parser.add_argument("--diagnostic-inputs", type=Path, required=True)
    parser.add_argument("--diagnostic-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    verify_foundation_lock(args.lock, args.config)
    selection, arc, _, _, _ = load_exposed_arc(args.merit_selection)
    freeze = read_json(args.diagnostic_freeze)
    if sha256_file(args.diagnostic_inputs) != freeze["inputs_file_sha256"]:
        raise ValueError("FOUNDATION_DIAGNOSTIC_INPUT_CHANGED")
    inputs = read_json(args.diagnostic_inputs)
    if len(inputs["cases"]) != freeze["cases"]:
        raise ValueError("FOUNDATION_DIAGNOSTIC_COUNT_CHANGED")
    receipt = {
        "status": "PREPARED_ZERO_MODEL",
        "recipe_id": RECIPE_ID,
        "lock_sha256": sha256_file(args.lock),
        "config_sha256": sha256_file(args.config),
        "merit_selection_sha256": sha256_file(args.merit_selection),
        "arc_id": arc.arc_id,
        "arc_sha256": selection["private_artifacts"]["arc_sha256"],
        "episodes": len(arc.episodes),
        "public_messages": sum(len(item.task.user_messages) for item in arc.episodes),
        "diagnostic_inputs_sha256": sha256_file(args.diagnostic_inputs),
        "diagnostic_cases": len(inputs["cases"]),
        "diagnostic_sessions": sum(len(case["sessions"]) for case in inputs["cases"]),
        "rubric_read_by_runner": False,
    }
    write_json(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
