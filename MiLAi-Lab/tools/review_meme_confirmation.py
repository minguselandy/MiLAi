"""Build label-hidden review packs and aggregate completed MEME confirmations.

Judgments remain source-grounded author review, not an independent human or an
official Judge. Model condition and seed are joined only after review is complete.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json


def prepare(root: Path) -> dict:
    driver = read_json(root / "driver.json")
    if driver["status"] != "COMPLETED":
        raise ValueError("Complete all scheduled first predictions before reviewing")
    output = root / "review-pack"
    output.mkdir(parents=True, exist_ok=False)
    references = {(r["episode"], r["id"]): r
                  for r in read_json(root / "prepared/references.json")}
    groups = defaultdict(list)
    for path in sorted((root / "runs").glob("*/*/answers.json")):
        for row in read_json(path):
            groups[row["episode"], row["id"]].append({**row, "seed": int(path.parents[1].name),
                                                     "source_result": str(path.resolve())})
    rng = random.Random(20261019)  # noqa: S311 -- reproducible review order, not cryptography
    mapping, contexts, packets = {}, {}, defaultdict(list)
    for key, reference in sorted(references.items()):
        rows = groups[key]
        rng.shuffle(rows)
        visible_inputs = []
        for row in rows:
            request = read_json(Path(row["source_result"]).parent / "http/questions"
                                / row["variant"] / row["episode"] / row["id"] / "request.json")
            visible_inputs.append(json.loads(request["messages"][-1]["content"]))
        visible = visible_inputs[0]
        if any(item != visible for item in visible_inputs) or visible["question"] != reference[
                "question"]:
            raise ValueError("Paired actual inputs or question/reference identity differ")
        context = {k: v for k, v in visible.items() if k != "question"}
        context_key = (reference["episode"], reference["phase"])
        if context_key in contexts and contexts[context_key] != context:
            raise ValueError("The questions do not share their declared source prefix")
        contexts[context_key] = context
        responses = []
        for row in rows:
            identity = f"r{len(mapping):04d}"
            mapping[identity] = {k: row[k] for k in (
                "seed", "variant", "episode", "id", "source_result")}
            mapping[identity]["missing_prediction"] = row.get("hypothesis") is None
            responses.append({"review_id": identity, "hypothesis": row.get("hypothesis"),
                              "known_failure": row.get("hypothesis") is None})
        packets[reference["episode"]].append({"reference": reference, "responses": responses})
    for (episode, phase), context in contexts.items():
        write_json(output / episode / f"{phase}-sources.json", context)
    for episode, packet in packets.items():
        write_json(output / episode / "questions.json", packet)
    if len(mapping) != driver["planned_calls"]:
        raise ValueError("Review pack does not cover every planned first response")
    write_json(output / "join-after-review.json", mapping)
    result = {"status": "LABEL_HIDDEN_REVIEW_PACK_READY", "responses": len(mapping),
              "episodes": list(packets), "source_contexts": len(contexts),
              "scope": "Hide condition/seed labels, not a claim of independent adjudication "
                       "or perfect blinding from response style."}
    write_json(output / "preparation.json", result)
    return result


def score(root: Path, judgment_path: Path) -> dict:
    mapping = read_json(root / "review-pack/join-after-review.json")
    judgments = read_json(judgment_path)["judgments"]
    if set(judgments) != set(mapping):
        raise ValueError("Every response needs an explicit author judgment")
    refs = {(r["episode"], r["id"]): r
            for r in read_json(root / "prepared/references.json")}
    keyed = {(m["seed"], m["episode"], m["variant"], m["id"]): judgments[key]
             for key, m in mapping.items()}
    cells = defaultdict(lambda: defaultdict(int))
    records = []
    for identity, entry in mapping.items():
        reference = refs[entry["episode"], entry["id"]]
        judgment = judgments[identity]
        if judgment["judgment"] not in {"pass", "fail", "ambiguous", "missing"}:
            raise ValueError("Unknown judgment")
        if entry["missing_prediction"] and judgment["judgment"] != "missing":
            raise ValueError("A failed original prediction must remain explicitly missing")
        before = reference["before_id"]
        gate = before is None or keyed[
            entry["seed"], entry["episode"], entry["variant"], before]["judgment"] == "pass"
        phase = reference["phase"]
        cell = cells[entry["seed"], entry["episode"], entry["variant"]]
        cell[phase + "_total"] += 1
        cell[phase + "_raw_pass"] += judgment["judgment"] == "pass"
        cell[phase + "_gated_pass"] += judgment["judgment"] == "pass" and gate
        cell[phase + "_ambiguous"] += judgment["judgment"] == "ambiguous"
        cell[phase + "_missing"] += judgment["judgment"] == "missing"
        records.append({"review_id": identity, **entry, **judgment,
                        "task_type": reference["task_type"], "before_gate": gate})
    episode_rates = defaultdict(lambda: defaultdict(list))
    for (_, episode, variant), cell in cells.items():
        episode_rates[episode][variant].append(cell["after_gated_pass"] / cell["after_total"])
    paired = [{"episode": episode,
               "baseline": sum(r["baseline"]) / len(r["baseline"]),
               "compact": sum(r["compact"]) / len(r["compact"]),
               "difference": sum(r["compact"]) / len(r["compact"])
                             - sum(r["baseline"]) / len(r["baseline"])}
              for episode, r in sorted(episode_rates.items())]
    result = {"status": "AUTHOR_REVIEW_JOINED", "records": records,
              "cells": [{"seed": k[0], "episode": k[1], "variant": k[2], **v}
                        for k, v in sorted(cells.items())], "paired_episode_rates": paired,
              "episode_macro_difference": sum(p["difference"] for p in paired) / len(paired),
              "scope": "Four episodes, two draws each; do not treat200positions as independent. "
                       "Shared domain DAGs, author judgment and source-only view limit claims."}
    write_json(root / "reviewed-scores.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--phase", choices=("prepare", "score"), required=True)
    parser.add_argument("--judgments", type=Path)
    args = parser.parse_args()
    if args.phase == "prepare":
        print(json.dumps(prepare(args.root)))
    else:
        if args.judgments is None:
            parser.error("score requires --judgments")
        result = score(args.root, args.judgments)
        print(json.dumps({k: v for k, v in result.items() if k not in {"records", "cells"}}))


if __name__ == "__main__":
    main()
