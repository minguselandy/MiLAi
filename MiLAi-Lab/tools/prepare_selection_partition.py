"""Reserve the next MuSiQue panel from metadata, without loading candidate bodies.

The old fourteen evaluated families remain regressions. Training availability
is recomputed from registered row identities in the original family namespace,
including the second worktree whose family numbering differs.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def reserve(groups: list[dict[str, Any]], exposed: set[str], quota: dict[int, int],
            seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)  # noqa: S311 -- frozen metadata sampling
    result = []
    for steps, count in sorted(quota.items()):
        available = sorted((g for g in groups if g["family"] not in exposed
                            and g["max_steps"] == steps), key=lambda g: g["family"])
        if len(available) < count:
            raise ValueError(
                f"Only {len(available)} unused {steps}-step families for quota {count}")
        rng.shuffle(available)
        for group in available[:count]:
            question = rng.choice(sorted(q for q in group["question_ids"] if int(q[0]) == steps))
            result.append({"family": group["family"], "max_steps": steps,
                           "question_id": question, "protected_source_rows": group["rows"],
                           "protected_question_ids": group["question_ids"]})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    population = read_json(Path("data/manifests/milai-global-training-population-v1.json"))
    assignment = {r["row"]: r for r in read_json(
        Path(population["family_assignments"]["read_decisions"]))}
    seen = set()
    for entry in population["sampled_exposure_sources"]:
        path = Path(entry["root"]) / f"{entry['split']}.jsonl"
        for line in path.read_text().splitlines():
            seen.add(assignment[json.loads(line)["metadata"]["row"]]["family"])
    global_sources = Path(
        "artifacts/jev-reader/global-reader-reference-v1/data/selected-sources.jsonl")
    for line in global_sources.read_text().splitlines():
        seen.add(json.loads(line)["metadata"]["family"])
    audit = read_json(Path(
        "artifacts/jev-reader/global-training-design-v1/source-audit-selection.json"))
    for record in audit["selected"]:
        seen.update(assignment[i]["family"] for i in record["source_rows"])
    exposure = read_json(Path("artifacts/jev-reader/data/cross-worktree-exposure-20261017.json"))
    preview = set(exposure["shared_preview_exposure"]["question_ids"])
    seen.update(r["family"] for r in assignment.values() if r["question_id"] in preview)
    train = [json.loads(line) for line in
             Path(population["candidate_training_metadata_path"]).read_text().splitlines()]
    unseen = [r for r in train if r["family"] not in seen]
    (args.output / "unseen-train-metadata.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in unseen))
    steps: dict[str, int] = {}
    for row in unseen:
        steps[row["family"]] = max(steps.get(row["family"], 0), int(row["question_id"][0]))
    old = read_json(Path("data/manifests/milai-global-reserved-source-v1-protocol.json"))
    joint = read_json(Path("data/manifests/milai-global-joint-partition-v1-feasibility.json"))
    selected = reserve(joint["selection"]["groups"], {g["family"] for g in old["selected"]},
                       {2: 6, 3: 5, 4: 3}, 20261017)
    metadata = [json.loads(line) for line in Path(
        "artifacts/jev-reader/global-training-design-v1/heldout-candidate-intake/metadata.jsonl"
    ).read_text().splitlines()]
    for group in selected:
        group["source_rows"] = [r["row"] for r in metadata
                                if r["question_id"] == group["question_id"]]
    report = {
        "status": "METADATA_RESERVED_BEFORE_NEW_SOURCE_REVIEW_OR_TRAINING",
        "seed": 20261017, "selected": selected, "families": len(selected),
        "source_rows": sum(len(g["source_rows"]) for g in selected),
        "max_decomposition_steps": dict(Counter(g["max_steps"] for g in selected)),
        "unseen_training_rows": len(unseen), "unseen_training_families": len(steps),
        "unseen_training_max_steps": dict(Counter(steps.values())),
        "prior_evaluated_families": sorted(g["family"] for g in old["selected"]),
        "selection_rule": "Shuffle sorted unused families within fixed 2/3/4 strata, choose6/5/3; "
                          "one random maximum-step question with all variants; no reroll.",
        "isolation": "Entire selected families evaluation-only. Recheck literal target/pool "
                     "overlap against final new training sources before exposing reserved bodies.",
        "scope": "Public DEV mirror, not official test, pretraining novelty or complete-history "
                 "proof. Former14 keep their original frozen-evaluation validity "
                 "but are future regressions.",
        "archive_or_candidate_bodies_loaded": False, "model_calls": 0,
        "sha_checks": False, "content_fingerprints": False}
    write_json(args.output / "reservation.json", report)
    print(json.dumps({k: v for k, v in report.items()
                      if k not in {"selected", "prior_evaluated_families"}}))


if __name__ == "__main__":
    main()
