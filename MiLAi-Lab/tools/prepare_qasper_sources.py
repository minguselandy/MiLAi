"""Prepare a native paper-partitioned QASPER cohort for existing Source/Host runners."""
from __future__ import annotations

import argparse
import json
import tarfile
import time
from collections import Counter
from pathlib import Path
from typing import BinaryIO, cast

from milai_lab.datasets.qasper import allocate_papers, export_paper
from milai_lab.harness.artifact_io import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--train-papers", type=int, default=384)
    parser.add_argument("--dev-papers", type=int, default=32)
    parser.add_argument("--questions-per-paper", type=int, default=2)
    parser.add_argument("--given-requests", action="store_true",
                        help="Supply literal native questions as queries; omit for autonomous Host")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if min(args.train_papers, args.dev_papers) < 0 or not 1 <= args.questions_per_paper <= 2:
        parser.error("Paper quotas must be nonnegative; this first tier uses one or two questions")
    started, cpu = time.perf_counter(), time.process_time()
    with tarfile.open(args.archive) as archive:
        # Read only the named native train/dev files; no test or general archive extraction.
        train = json.load(cast(BinaryIO, archive.extractfile("qasper-train-v0.3.json")))
        dev = json.load(cast(BinaryIO, archive.extractfile("qasper-dev-v0.3.json")))
    groups = allocate_papers(train, dev, train_count=args.train_papers,
                             dev_count=args.dev_papers, seed=args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "allocation.json", {"seed": args.seed, "groups": groups,
        "source_version": "qasper-v0.3", "selection": "Paper IDs sorted then seeded shuffle; "
        "native train/dev retained. Questions use the first native entries. No outcome selection.",
        "scope": "Allocated before exporting annotations; unused papers have metadata only. "
        "Public-source separation, not pretraining isolation or blind confirmation."})
    splits = {}
    for split, papers in (("train", train), ("dev", dev)):
        histories, controls = [], []
        for group in groups:
            if group["split"] == split:
                history, review = export_paper(group["paper_id"], papers[group["paper_id"]], split,
                                               max_questions=args.questions_per_paper,
                                               given_requests=args.given_requests)
                histories.append(history)
                controls.extend(review)
        write_json(args.output / f"{split}.json", {"histories": histories})
        with (args.output / f"{split}-controls.jsonl").open("w") as stream:
            for row in controls:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        statuses = Counter(e["status"] for row in controls for a in row["annotations"]
                           for e in a["evidence"])
        splits[split] = {"papers": len(histories), "questions": len(controls),
            "sources": sum(len(h["sources"]) for h in histories),
            "annotations": sum(len(c["annotations"]) for c in controls),
            "evidence_status": dict(statuses),
            "unanswerable_annotations": sum(a["answer"]["unanswerable"]
                                           for c in controls for a in c["annotations"])}
    write_json(args.output / "preparation.json", {
        "status": "NATIVE_QASPER_SOURCE_REQUESTS_PREPARED;NO_ACTUAL_READ_OR_HANDOFF",
        "source_archive": str(args.archive.resolve()), "source_version": "qasper-v0.3",
        "source_url": "https://qasper-dataset.s3.us-west-2.amazonaws.com/"
                      "qasper-train-dev-v0.3.tgz",
        "data_card": "https://huggingface.co/datasets/allenai/qasper/blob/main/README.md",
        "evidence_mapping": "Literal first, then official reader newline-to-space and strip. "
            "Section headings are separate textual source units; no fuzzy or semantic matching.",
        "reader_reference": "https://github.com/allenai/qasper-led-baseline/blob/main/"
                            "qasper_baselines/dataset_reader.py",
        "license": "CC-BY-4.0", "citation": "Dasigi et al. 2021, A Dataset of Information-Seeking "
            "Questions and Answers Anchored in Research Papers (NAACL)",
        "native_papers": {"train": len(train), "dev": len(dev)}, "splits": splits,
        "requested_papers": {"train": args.train_papers, "dev": args.dev_papers},
        "unused_papers": sum(g["split"] == "unused" for g in groups),
        "questions_per_paper": args.questions_per_paper, "seed": args.seed,
        "given_requests": args.given_requests,
        "retrieval_query_scope": "When explicitly supplied, query is the literal native question; "
            "public task instructions remain in request.content. Omitted for autonomous Host.",
        "runtime_bank_ids": "Percent-escape literal percent and period for the existing Store "
            "namespace; native paper IDs, source groups and source sessions remain unchanged.",
        "scope": "All paragraphs and caption text are public sources independent of annotations. "
            "No image/table content invented. Native answers/evidence are separate controls. "
            "No operation labels, ideal post-states, generated Views, or Host-quality claim.",
        "model_calls": 0, "operation_labels": 0, "ledger_recorded": False,
        "no_sha_validation": True, "compute": {"cpu_seconds": time.process_time() - cpu,
                                               "wall_seconds": time.perf_counter() - started}})


if __name__ == "__main__":
    main()
