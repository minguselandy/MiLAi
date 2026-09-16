"""Freeze metadata-selected positions before source qualification or answer review."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from check_v0210_control import LAB, write


def freeze(root: Path) -> dict:
    review = json.loads((LAB / "data/manifests/v0211-exposure-review.json").read_text())
    config = json.loads((LAB / "configs/v0211-external-diagnostic.json").read_text())
    metadata = json.loads((root / "v2-metadata.json").read_text())
    allowed = set(review["v2"]["outside_old_partition_ids"])
    candidates = [r for r in metadata if r["id"] in allowed]
    queues = {domain: sorted([r for r in candidates if r["domain"] == domain], key=lambda r:
              hashlib.sha256((config["seed"] + r["id"]).encode()).hexdigest())
              for domain in ("web", "enterprise")}
    # All remaining items are gotchas. Do not transfer their surplus to other abilities.
    gotchas = [queues[domain][i] for i in range(5) for domain in ("web", "enterprise")]
    slots = []
    for stratum in config["V1"]["strata"]:
        for ordinal in range(6):
            slots.append({"dataset": "V1", "stratum": stratum, "ordinal": ordinal,
                          "question_id": None, "status": "NO_ELIGIBLE_NEW_PARTITION"})
    for stratum, quota in zip(config["V2"]["strata"], config["V2"]["quotas"], strict=True):
        for ordinal in range(quota):
            row = gotchas[ordinal] if stratum == "gotcha" else None
            slots.append({"dataset": "V2", "stratum": stratum, "ordinal": ordinal,
                          "question_id": row["id"] if row else None,
                          "run_id": uuid4().hex if row else None,
                          "metadata": row,
                          "status": "SOURCE_CLUSTER_QUALIFICATION_PENDING" if row
                          else "NO_ELIGIBLE_NEW_PARTITION"})
    result = {"status": "POSITIONS_FROZEN_NO_MODEL_AUTHORIZED_BEFORE_QUALIFICATION",
              "selection": "Metadata-only SHA256 order, web/enterprise alternating within gotcha",
              "seed": config["seed"], "target_positions": 69, "named_candidates": 10,
              "unfilled_positions": 59, "first_wave_positions": 9,
              "first_wave_named_candidates": [gotchas[0]["id"]],
              "slots": slots, "branch_rule": config["branch_rule"],
              "newness": "UNKNOWN until source/task overlap review; no outcome-based replacement"}
    write(root / "candidate-manifest.json", result)
    offline = root / "evaluation"
    offline.mkdir(mode=0o700)
    wanted = {r["id"] for r in gotchas}
    prior = set(review["v2"]["previously_opened_ids"])
    source = LAB.parent / "benchmarks/LongMemEval-V2/data/longmemeval-v2/questions.jsonl"
    selected, old = [], []
    # These records are outside the protected partition or explicitly already opened.
    # All nonselected/protected lines remain undecoded and are not copied.
    from prepare_v0211_inventory import metadata as meta
    for raw in source.open("rb"):
        identity = meta(raw)["id"]
        if identity in wanted:
            selected.append(json.loads(raw))
        elif identity in prior:
            old.append(json.loads(raw))
    write(offline / "candidate-official-records.json", selected)
    write(offline / "previously-opened-official-records.json", old)
    write(offline / "responsibility.json", {"mode": "USER_AUTHORIZED_SUBAGENT_SEMANTIC_REVIEW",
          "order": ["source/task overlap qualification", "per-question evaluation contract",
                    "freeze hash before any generation", "first-answer correctness",
                    "support presented", "failure layer"],
          "paid_or_local_benchmark_judge_calls": 0,
          "review_budget": ("One qualification/contract review and one result review per wave; "
                            "disagreement remains DISPUTED without hidden judge calls"),
          "review_cost": "Orchestrator model-assisted labor; separately reported, not human/free",
          "protected_records_decoded": 0})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = freeze(args.root.resolve())
    print(json.dumps({k: v for k, v in result.items() if k != "slots"}))
