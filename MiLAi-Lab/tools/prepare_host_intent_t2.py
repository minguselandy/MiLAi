"""Select registered training histories and aggregate reviewed on-policy states.

Selection uses source-group metadata only. Aggregation preserves old rows and
requires reviews of the actual new inputs; it never generates operation labels.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.retrieval_supervision import annotate_decisions


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def source_registry(data: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, str]]:
    registry: dict[str, dict[str, str]] = {}
    for split, rows in data.items():
        for row in rows:
            metadata = row["metadata"]
            if metadata["split"] != split:
                raise ValueError("Data row is in a different split")
            if metadata["task"] != "memory_operation":
                continue
            family = metadata["family"]
            entry = {"split": split, "component": metadata["component"]}
            if family in registry and registry[family] != entry:
                raise ValueError("A source group crosses splits or memory components")
            registry[family] = entry
    return registry


def select_histories(
    fixture: dict[str, Any], registry: dict[str, dict[str, str]], *, count: int, seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_group: dict[str, list[dict[str, Any]]] = {}
    identities = set()
    for history in fixture["histories"]:
        family = history["source_group"]
        if history["id"] in identities:
            raise ValueError("Duplicate public history identity")
        identities.add(history["id"])
        if history["split"] != registry[family]["split"]:
            raise ValueError("Public history changed its inherited source split")
        by_group.setdefault(family, []).append(history)
    if set(by_group) != set(registry):
        raise ValueError("Public histories do not cover the original primary source registry")
    eligible = sorted(family for family, entry in registry.items() if entry["split"] == "train")
    rng = random.Random(seed)  # noqa: S311 -- registered outcome-blind source selection
    chosen = sorted(rng.sample(eligible, count))
    histories = [copy.deepcopy(history) for family in chosen
                 for history in sorted(by_group[family], key=lambda item: item["id"])]
    selection = {
        "schema": "host_intent_t2_selection_v1", "status": "SELECTED_NOT_COLLECTED",
        "selection_seed": seed, "eligible_groups": eligible, "selected_groups": chosen,
        "components": {family: registry[family]["component"] for family in chosen},
        "source_groups": len(chosen), "histories": len(histories),
        "request_positions_per_interface": sum(len(h["requests"]) for h in histories),
        "component_groups": dict(Counter(registry[family]["component"] for family in chosen)),
        "selection": "Uniform sample without replacement from sorted registered train groups. "
                     "No labels, task outcomes or model predictions used; keep every request "
                     "and the original source/arrival order within each selected history.",
    }
    return ({**fixture, "schema": "host_intent_t2_histories_v1",
             "scope": "Existing training sources; new current-policy trajectories required.",
             "histories": histories}, selection)


def aggregate(
    data: dict[str, list[dict[str, Any]]], raw: list[dict[str, Any]],
    reviewed: list[dict[str, Any]], selection: dict[str, Any], *, collector_policy: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Append all actual own states, including masks; old train/dev rows stay exact."""
    registry = source_registry(data)
    selected = set(selection["selected_groups"])
    if any(registry[family]["split"] != "train" for family in selected):
        raise ValueError("Own-trajectory selection contains a non-training source")
    if any(row["gold"] for row in raw):
        raise ValueError("Actual raw exports must be masked before source review")
    reviews = [row["metadata"]["source_review"] for row in reviewed
               if "source_review" in row["metadata"]]
    if annotate_decisions(raw, reviews) != reviewed:
        raise ValueError("Reviewed rows changed actual inputs, metadata, order or compiled targets")
    old_rows = [row for rows in data.values() for row in rows]
    state_ids = [row["metadata"]["state_id"] for row in old_rows]
    if len(state_ids) != len(set(state_ids)):
        raise ValueError("Old state identities are not unique")
    seen = {(row["metadata"]["task"], row["metadata"]["event_id"]) for row in old_rows}
    next_identity = max(state_ids) + 1
    own = []
    for row in reviewed:
        metadata = row["metadata"]
        family = metadata["family"]
        if metadata["split"] != "train" or family not in selected:
            raise ValueError("Own trajectory is outside the declared training source cohort")
        if metadata["collection_policy"] != collector_policy:
            raise ValueError("Own trajectory came from a different collector policy")
        identity = ("memory_operation", metadata["event_id"])
        if identity in seen:
            raise ValueError("Duplicate decision or overlapping export prefix")
        seen.add(identity)
        item = copy.deepcopy(row)
        item["metadata"].update(task="memory_operation", component=registry[family]["component"],
                                state_id=next_identity)
        next_identity += 1
        own.append(item)
    labelled = sum(bool(row["gold"]) for row in own)
    if not labelled:
        raise ValueError("T2 aggregation requires actual reviewed own-trajectory labels")
    effective = sum(bool(row["gold"]) for row in data["train"]) + labelled
    updates = math.ceil(2 * effective / 16)
    report = {
        "status": "AGGREGATED_NOT_FITTED", "old_train_rows": len(data["train"]),
        "old_train_labelled": effective - labelled, "old_dev_rows": len(data["dev"]),
        "own_rows": len(own), "own_labelled": labelled, "own_masked": len(own) - labelled,
        "own_groups_with_states": len({row["metadata"]["family"] for row in own}),
        "own_component_rows": dict(Counter(row["metadata"]["component"] for row in own)),
        "effective_train_rows": effective, "optimizer_updates_each_arm": updates,
        "row_draws_each_arm": 16 * updates, "effective_batch": 16,
        "old_rows_and_ids_unchanged": True, "own_public_inputs_and_reviewed_gold_unchanged": True,
        "budget_rule": "ceil(2 * labelled augmented training rows / 16), matched continued-CE "
                       "uses the same additional updates on old T1 data only.",
        "control": "Same corresponding final T1 checkpoint, optimizer reset, mixture masses and "
                   "training recipe. Different tokens and exposure/passes must be reported.",
    }
    return {"train": [*copy.deepcopy(data["train"]), *own],
            "dev": copy.deepcopy(data["dev"])}, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select")
    select.add_argument("data", type=Path)
    select.add_argument("histories", type=Path)
    select.add_argument("output", type=Path)
    select.add_argument("--groups", type=int, default=32)
    select.add_argument("--selection-seed", type=int, default=0)
    combine = sub.add_parser("aggregate")
    combine.add_argument("data", type=Path)
    combine.add_argument("selection", type=Path)
    combine.add_argument("raw", type=Path)
    combine.add_argument("reviewed", type=Path)
    combine.add_argument("output", type=Path)
    combine.add_argument("--collector-policy", default="laya")
    for command in (select, combine):
        command.add_argument("--source-version", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {
        "phase": "host_intent_t2_" + args.command + "_v1", "status": "RUNNING",
        "source_version": args.source_version, "data": str(args.data),
        "model_calls": 0, "ledger_recorded": False,
    }
    try:
        data = {split: read_rows(args.data / f"{split}.jsonl") for split in ("train", "dev")}
        if args.command == "select":
            public, selection = select_histories(read_json(args.histories), source_registry(data),
                                                  count=args.groups, seed=args.selection_seed)
            selection.update(data=str(args.data), public_histories=str(args.histories))
            write_json(args.output / "histories.json", public)
            write_json(args.output / "selection.json", selection)
            report.update({key: selection[key] for key in (
                "status", "selection_seed", "source_groups", "histories",
                "request_positions_per_interface", "component_groups")})
        else:
            augmented, details = aggregate(
                data, read_rows(args.raw), read_rows(args.reviewed), read_json(args.selection),
                collector_policy=args.collector_policy)
            report.update(details, selection=str(args.selection), raw=str(args.raw),
                          reviewed=str(args.reviewed), collector_policy=args.collector_policy)
            # Copy the common frozen files directly; append only new JSONL rows.
            for arm in ("aggregate", "continued-ce"):
                directory = args.output / arm
                directory.mkdir()
                for name in ("train.jsonl", "dev.jsonl", "mixture.json"):
                    shutil.copy2(args.data / name, directory / name)
            train_path = args.output / "aggregate/train.jsonl"
            with train_path.open("rb+") as stream:
                stream.seek(-1, 2)
                if stream.read(1) != b"\n":
                    stream.write(b"\n")
                for row in augmented["train"][len(data["train"]):]:
                    stream.write((json.dumps(row, ensure_ascii=False) + "\n").encode())
        print(json.dumps(report), flush=True)
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started,
                      cpu_seconds=time.process_time() - cpu)
        write_json(args.output / "preparation.json", report)


if __name__ == "__main__":
    main()
