"""Source-disjoint native-reference QA preparation, reusing ordinary Source histories."""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from milai_lab.datasets.hotpot_memory import allocate_metadata, article_id, export_question
from milai_lab.harness.artifact_io import read_json, write_json


def read_metadata(path: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq  # type: ignore[import-not-found]

    file = pq.ParquetFile(path)
    rows: list[dict[str, Any]] = []
    for batch in file.iter_batches(columns=["id", "context.title"], batch_size=512):
        for row in batch.to_pylist():
            titles = row["context"]["title"] if "context" in row else row["title"]
            ids = [article_id(title) for title in titles]
            rows.append({"native_id": row["id"], "file": str(path.resolve()),
                "physical_row": len(rows), "article_title_ids": sorted(set(ids)),
                "valid_titles": bool(ids) and all(ids) and len(ids) == len(set(ids))})
    return rows


def partition(args: argparse.Namespace) -> None:
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    train = [row for path in args.train_files for row in read_metadata(path)]
    validation = {row["native_id"]: row for row in read_metadata(args.validation_file)}
    order = [validation[row["native_id"]] for row in read_json(args.validation_order)]
    result = allocate_metadata(train, order, set(read_json(args.excluded_titles)), {
        "train": args.train_roots, "dev_fit": args.dev_roots,
        "dev_select": args.dev_roots, "confirm": args.confirm_roots}, seed=args.seed)
    result["inputs"] = {"train_files": [str(path.resolve()) for path in args.train_files],
        "validation_file": str(args.validation_file.resolve()),
        "validation_order": str(args.validation_order.resolve()),
        "excluded_titles": str(args.excluded_titles.resolve())}
    write_json(args.output / "partition.json", result)
    write_json(args.output / "run.json", {"status": result["status"], "pid": os.getpid(),
        "wall_seconds": time.perf_counter() - tick, "cpu_seconds": time.process_time() - cpu,
        "compute_ledger_status": "pending_idle_settlement", "model_calls": 0,
        "only_columns_read": ["id", "context.title"], "sha_validation": False})
    print(json.dumps({key: result[key] for key in (
        "status", "target_counts", "selected_counts", "rejected_before_feedback")}), flush=True)
    if result["status"] != "COMPLETE_METADATA_PARTITION":
        raise ValueError("Source-disjoint allocation incomplete; do not relax the boundary")


def export(args: argparse.Namespace) -> None:
    if args.split not in {"train", "dev_fit", "dev_select"}:
        raise ValueError("Pilot exporter cannot unseal confirmation labels")
    import pyarrow.parquet as pq

    manifest = read_json(args.partition)
    if manifest["status"] != "COMPLETE_METADATA_PARTITION":
        raise ValueError("Complete metadata roles before inspecting native labels")
    selected = manifest["roles"][args.split][:args.roots]
    if not selected:
        raise ValueError("No admitted roots for this role")
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    groups: dict[str, list[str]] = defaultdict(list)
    for row in selected:
        groups[row["file"]].append(row["native_id"])
    native = {}
    for path, identifiers in groups.items():
        # Parquet filtering returns only the admitted role's selected rows. No
        # CONFIRM file/labels are passed to this pilot exporter.
        table = pq.read_table(path, filters=[("id", "in", identifiers)])
        for row in table.to_pylist():
            if row["id"] in native:
                raise ValueError("Native identity occurs more than once")
            native[row["id"]] = row
    histories, controls, invalid = [], [], []
    for index, metadata in enumerate(selected):
        row = native[metadata["native_id"]]
        actual = sorted({article_id(title) for title in row["context"]["title"]})
        if actual != metadata["article_title_ids"]:
            raise ValueError("Native source identities differ from frozen metadata")
        try:
            history, control = export_question(row, args.split, ordinal=index, seed=args.seed)
        except ValueError as error:
            invalid.append({"native_id": row["id"], "reason": str(error)})
            continue  # Dataset defect, recorded before any model outcome; no replacement.
        histories.append(history)
        controls.append(control)
    write_json(args.output / "sources.json", {"histories": histories})
    with (args.output / "controls.jsonl").open("x") as stream:
        for row in controls:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "invalid-native-annotations.json", invalid)
    write_json(args.output / "run.json", {"status": "COMPLETED", "pid": os.getpid(),
        "partition": str(args.partition.resolve()), "split": args.split,
        "selected_metadata_roots": len(selected), "exported_roots": len(histories),
        "native_defects_not_replaced": len(invalid), "model_calls": 0,
        "wall_seconds": time.perf_counter() - tick, "cpu_seconds": time.process_time() - cpu,
        "compute_ledger_status": "pending_idle_settlement", "sha_validation": False,
        "scope": "Only admitted non-confirm role rows exported; native answers/supports "
                 "offline. Original paragraph text and sentence spans retained."})
    print(json.dumps({"split": args.split, "selected": len(selected),
                      "exported": len(histories), "native_defects": len(invalid)}), flush=True)


def add_commands(sub: Any) -> None:
    command = sub.add_parser("native-partition")
    command.add_argument("--train-files", type=Path, nargs="+", required=True)
    command.add_argument("--validation-file", type=Path, required=True)
    command.add_argument("--validation-order", type=Path, required=True)
    command.add_argument("--excluded-titles", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--train-roots", type=int, default=2000)
    command.add_argument("--dev-roots", type=int, default=128)
    command.add_argument("--confirm-roots", type=int, default=1000)
    command.add_argument("--seed", type=int, default=20261117)
    command = sub.add_parser("native-export")
    command.add_argument("--partition", type=Path, required=True)
    command.add_argument("--split", choices=["train", "dev_fit", "dev_select"], required=True)
    command.add_argument("--roots", type=int, default=64)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--seed", type=int, default=20261117)
