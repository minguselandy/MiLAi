"""Release completed paper prefixes from ongoing collection as fixed training shards."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def completed_rows(root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    run = read_json(root / "run.json")
    count = run["completed_families"] if limit is None else min(limit, run["completed_families"])
    histories = read_json(root / "sources.json")["histories"][:count]
    expected = sum(
        sum(r["states"] for r in read_json(root / "banks" / h["id"] / "report.json")["requests"])
        for h in histories
    )
    rows = []
    with (root / "states.jsonl").open() as stream:
        # Stop at the known closed-family boundary, never parse the active partial tail.
        for _ in range(expected):
            row = json.loads(next(stream))
            row["metadata"].update(
                source_collection=str(root.resolve()), source_state_id=row["metadata"]["state_id"]
            )
            rows.append(row)
    if {row["metadata"]["family"] for row in rows} != {h["source_group"] for h in histories}:
        raise ValueError("Collection prefix differs from its completed paper order")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-collections", type=Path, nargs="+", required=True)
    parser.add_argument("--dev-collection", type=Path, required=True)
    parser.add_argument("--train-families", type=int)
    parser.add_argument("--fast-dev-states", type=int, default=128)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = []
    families: set[str] = set()
    for root in args.train_collections:
        remaining = None if args.train_families is None else args.train_families - len(families)
        if remaining == 0:
            break
        rows = completed_rows(root, remaining)
        own = {row["metadata"]["family"] for row in rows}
        if own & families:
            raise ValueError("A training family was supplied in multiple collection slices")
        families.update(own)
        raw.extend(rows)
    dev = completed_rows(args.dev_collection)
    if (
        not raw
        or not dev
        or any(row["metadata"]["split"] != "train" for row in raw)
        or any(row["metadata"]["split"] != "dev" for row in dev)
        or families & {row["metadata"]["family"] for row in dev}
    ):
        raise ValueError("Training and development must retain disjoint existing research roles")
    if args.train_families is not None and len(families) != args.train_families:
        raise ValueError("The requested completed-family prefix is not yet available")
    train = [row for row in raw if row["gold"]]
    for index, row in enumerate([*train, *dev]):
        row["metadata"]["state_id"] = index
    # Round-robin evenly spaced within each family; cover initial and late prefixes.
    groups = {
        family: [row for row in dev if row["metadata"]["family"] == family]
        for family in dict.fromkeys(row["metadata"]["family"] for row in dev)
    }
    per_family = max(1, args.fast_dev_states // len(groups))
    panel = [
        rows[round(i * (len(rows) - 1) / max(1, min(per_family, len(rows)) - 1))]
        for rows in groups.values()
        for i in range(min(per_family, len(rows)))
    ]
    args.output.mkdir(parents=True, exist_ok=False)
    for name, rows in (("train", train), ("dev", panel), ("dev-full", dev)):
        with (args.output / f"{name}.jsonl").open("w") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(
        args.output / "manifest.json",
        {
            "status": "FIXED_OPERATION_SHARD_RELEASED",
            "no_sha_validation": True,
            "train_collections": [str(p.resolve()) for p in args.train_collections],
            "dev_collection": str(args.dev_collection.resolve()),
            "train_source_families": len(families),
            "train_labelled_families": len({row["metadata"]["family"] for row in train}),
            "train_raw_states": len(raw),
            "train_fit_states": len(train),
            "train_unknown_states_retained_in_collections": len(raw) - len(train),
            "dev_families": len(groups),
            "dev_fast_states": len(panel),
            "dev_full_states": len(dev),
            "train_labels": dict(Counter(row["metadata"]["label_status"] for row in train)),
            "train_stages": dict(Counter(row["metadata"]["stage"] for row in train)),
            "supervision_scope": "Reference-witness operation preferences, not exhaustive semantic "
            "proofs or measured Host success",
            "selection": "Completed family order, then known supervision; fast dev uses "
            "evenly spaced states in every family without outcome or predicted-score selection",
        },
    )


if __name__ == "__main__":
    main()
