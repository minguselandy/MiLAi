"""Expand native TRAIN papers/questions while preserving all inherited research roles."""

from __future__ import annotations

import argparse
import json
import random
import tarfile
import time
from pathlib import Path
from typing import BinaryIO, cast

from milai_lab.datasets.qasper import export_paper
from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("parent_allocation", type=Path)
    parser.add_argument("research_allocation", type=Path)
    parser.add_argument("prior_sources", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reserve-new-families", type=int, default=96)
    parser.add_argument("--seed", type=int, default=20261111)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    original = read_json(args.parent_allocation)["groups"]
    research = read_json(args.research_allocation)
    protected = {
        row["source_group"]
        for role in ("DEVELOPMENT64", "CONFIRMATION256")
        for row in research[role]
    }
    prior = [
        *read_json(args.prior_sources / "new-histories.json")["histories"],
        *read_json(args.prior_sources / "replay-histories.json")["histories"],
    ]
    existing = {h["source_group"]: {r["id"] for r in h["requests"]} for h in prior}
    unused = [
        row
        for row in original
        if row["native_split"] == "train"
        and row["split"] == "unused"
        and row["source_group"] not in protected
    ]
    random.Random(args.seed).shuffle(unused)  # noqa: S311 -- fixed metadata allocation
    if not 0 <= args.reserve_new_families <= len(unused):
        raise ValueError("New reservation must fit the unused native-TRAIN population")
    reservation, new_train = (
        unused[: args.reserve_new_families],
        unused[args.reserve_new_families :],
    )
    selected = {row["source_group"] for row in new_train} | set(existing)
    if selected & (protected | {r["source_group"] for r in reservation}):
        raise ValueError("Training would change an inherited/reserved study role")
    args.output.mkdir(parents=True, exist_ok=False)
    # This metadata allocation precedes all new source export. Reserved bodies are not exported.
    write_json(
        args.output / "population.json",
        {
            "seed": args.seed,
            "parent_allocation": str(args.parent_allocation.resolve()),
            "research_allocation": str(args.research_allocation.resolve()),
            "existing_train": sorted(existing),
            "new_train": new_train,
            "new_confirmation_metadata_only": reservation,
            "inherited_protected": sorted(protected),
            "no_sha_validation": True,
            "scope": "New confirmation means unexposed to this project's fitting/selection, "
            "not public pretraining isolation; N96 is not a guaranteed 5pp power claim",
        },
    )
    with tarfile.open(args.archive) as archive:
        train = json.load(cast(BinaryIO, archive.extractfile("qasper-train-v0.3.json")))
    groups = {row["source_group"]: row for row in original}
    outputs = {"new-family": [], "additional-question": []}
    controls = {name: [] for name in outputs}
    for family in [*[r["source_group"] for r in new_train], *existing]:
        paper_id = groups[family]["paper_id"]
        paper = train[paper_id]
        history, review = export_paper(paper_id, paper, "train", max_questions=len(paper["qas"]))
        known = existing.get(family, set())
        history["requests"] = [r for r in history["requests"] if r["id"] not in known]
        review = [r for r in review if r["request_id"] not in known]
        if not history["requests"]:
            continue
        name = "additional-question" if family in existing else "new-family"
        outputs[name].append(history)
        controls[name].extend(review)
    for name, histories in outputs.items():
        write_json(args.output / f"{name}-histories.json", {"histories": histories})
        with (args.output / f"{name}-controls.jsonl").open("w") as stream:
            for row in controls[name]:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(
        args.output / "manifest.json",
        {
            "status": "EXPANDED_TRAIN_SOURCES_FROZEN_OPERATION_COLLECTION_PENDING",
            "native_train_papers": len(train),
            "existing_train_families": len(existing),
            "new_train_families": len(new_train),
            "combined_train_families": len(selected),
            "new_confirmation_families": len(reservation),
            "reserved_content_exported": False,
            "sources": {
                name: {
                    "families": len(histories),
                    "native_requests": sum(len(h["requests"]) for h in histories),
                }
                for name, histories in outputs.items()
            },
            "no_sha_validation": True,
            "new_operation_states": 0,
            "inherited_roles_changed": False,
            "raw_archive": str(args.archive.resolve()),
            "scope": "Extra natural questions share their paper family, not independent sources. "
            "Existing op3k inputs unchanged. Larger curves expand both family and query coverage; "
            "native annotation mapping remains offline and does not certify Host success.",
            "compute": {
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
            },
        },
    )


if __name__ == "__main__":
    main()
