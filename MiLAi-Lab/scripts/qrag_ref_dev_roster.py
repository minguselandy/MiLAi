"""Restrict every REF validation pass to the same project-TUNE MuSiQue-Ans questions."""

import argparse
import csv
import gzip
import json
import random
from pathlib import Path


def prepare(roles: Path, source: Path, output: Path, count: int, frozen: Path) -> None:
    registered = json.loads(frozen.read_text()) if frozen.is_file() else None
    if registered is not None:
        tune = set(registered["groups"])
        if registered["role"] != "TUNE" or registered["n"] != count or len(tune) != count:
            raise ValueError("Invalid frozen REF validation roster")
    else:
        with gzip.open(roles, "rt", newline="") as stream:
            tune = {
                r["native_group"]
                for r in csv.DictReader(stream, delimiter="\t")
                if r["source"] == "musique_full" and r["v13_role"] == "TUNE"
            }
    dev_name = "musique_ans_v1.0_dev.jsonl"
    with (source / dev_name).open() as stream:
        rows = {}
        for line in stream:
            group = json.loads(line)["id"]
            if group in tune:
                if group in rows:
                    raise ValueError("Duplicate native Ans group")
                rows[group] = line
    groups = sorted(rows) if registered else sorted(random.Random(42).sample(sorted(rows), count))  # noqa: S311 -- reproducible native group roster
    if registered and groups != registered["groups"]:
        raise ValueError("Original dev split does not resolve every frozen REF identity")
    output.mkdir(parents=True, exist_ok=True)
    roster = output / "roster.json"
    if roster.exists() and json.loads(roster.read_text())["groups"] != groups:
        raise ValueError("Existing REF cohort differs from the proposed cohort")
    (output / dev_name).write_text("".join(rows[group] for group in groups))
    train_name = "musique_ans_v1.0_train.jsonl"
    train_link = output / train_name
    if not train_link.exists():
        train_link.symlink_to((source / train_name).resolve())
    if train_link.resolve() != (source / train_name).resolve():
        raise ValueError("Unexpected REF train source")
    roster.write_text(
        json.dumps(
            {
                "role": "TUNE",
                "official_split": "Ans dev",
                "n": count,
                "sample_seed": 42,
                "groups": groups,
            },
            indent=2,
        )
    )
    if registered is None:
        frozen.write_text(roster.read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roles", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frozen", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.roles, args.source, args.output, 300, args.frozen)
