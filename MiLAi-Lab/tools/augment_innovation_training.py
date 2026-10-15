"""Consistent entity/alias augmentation of reviewed references; never a new real bank.

Original provenance remains attached. Variants are dependent training examples,
not independently observed histories, teacher successes or evaluation cases.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import re
from pathlib import Path

from milai_lab.methods.semantic_delta import compile_delta


def augment(row, entities, seed, name):
    rng = random.Random(seed)  # noqa: S311 - reproducible presentation augmentation
    aliases = list(row["mapping"]["units"])
    shuffled = rng.sample(aliases, len(aliases))
    alias_map = dict(zip(aliases, shuffled, strict=True))
    pattern = re.compile("|".join(
        rf"\b{re.escape(key)}\b" if key.isascii() else re.escape(key)
        for key in sorted(entities, key=len, reverse=True)))

    def rewrite(value):
        if isinstance(value, str):
            return alias_map.get(value, pattern.sub(lambda match: entities[match.group()], value))
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            return {alias_map.get(key, key): rewrite(item) for key, item in value.items()}
        return value

    result = copy.deepcopy(row)
    for key in ("input", "mapping", "delta_target", "consequence_targets", "quality_feedback"):
        result[key] = rewrite(row[key])
    for record in result["input"]["delivery"]["records"]:
        rng.shuffle(record["clauses"])
    result["example_id"] = row["example_id"] + ":" + name
    result["provenance"] = {
        "owner": row["provenance"]["owner"], "derived_from": row["example_id"],
        "original": copy.deepcopy(row["provenance"]), "entity_bijection": entities,
        "public_unit_alias_bijection": alias_map, "seed": seed,
        "scope": "Synthetic renaming of the original source/state projection. Original Source "
                 "identities are donor provenance, not a claim that renamed sources were observed. "
                 "No source bank is written; old-clause presentation order is shuffled.",
    }
    result["review"] = {"type": "mechanical_variant_of_reviewed_reference",
                        "original_review": copy.deepcopy(row["review"]),
                        "independent_semantic_review": False}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.references.read_text().splitlines() if line.strip()]
    config = json.loads(args.config.read_text())
    augmented = copy.deepcopy(rows)
    for ordinal, variant in enumerate(config["variants"]):
        for index, row in enumerate(rows):
            augmented.append(augment(row, variant["entities"],
                                     config["seed"] + ordinal * len(rows) + index, variant["name"]))
    for row in augmented:
        compile_delta(row["delta_target"], row["mapping"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in augmented))
    args.output.with_suffix(".preparation.json").write_text(json.dumps({
        "reference_examples": len(rows), "augmented_examples": len(augmented),
        "source_chains": len({row["provenance"]["owner"] for row in rows}),
        "config": str(args.config), "references": str(args.references),
        "scope": "Dependent training augmentation only; no independent sample count increase.",
        "model_calls": 0, "parameter_updates": 0, "semantic_bank_writes": 0,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
