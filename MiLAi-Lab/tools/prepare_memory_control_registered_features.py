"""Warm a frozen feature store for the registered TRAIN core roster."""

from __future__ import annotations

import argparse
import fcntl
import os
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.methods.frozen_feature_store import FrozenFeatureStore, batches
from milai_lab.methods.memory_control_dataset import MemoryControlDataset, StateIndex
from milai_lab.methods.small_control_model import SmallControlModel

BankRow = tuple[int, int, int, str, int]


def registered_index(dataset: MemoryControlDataset, roster: dict[str, Any]) -> list[StateIndex]:
    declared = [state for block in roster["batches"] for state in block["states"]]
    ids = [state["id"] for state in declared]
    if len(ids) != roster["distinct_states"] or len(set(ids)) != len(ids):
        raise ValueError("The registered feature roster must contain distinct states")
    requested = set(ids)
    found = {row.id: row for row in dataset.index("train") if row.id in requested}
    for state in declared:
        row = found.get(state["id"])
        if row is None or (row.dataset, row.group, row.task, row.budget, row.recipe) != (
            state["dataset"], state["group_id"], state["task_id"], state["budget"], state["recipe"],
        ):
            raise ValueError("Registered feature state did not match the TRAIN dataset")
    return [found[sid] for sid in ids]


def _bank_rows(path: Path) -> dict[int, BankRow]:
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        return {
            sid: (offset, length, objects, actions, width)
            for sid, offset, length, objects, actions, width in db.execute(
                "SELECT state_id,byte_offset,byte_length,object_count,action_ids,width FROM vectors"
            )
        }


def _vector_bytes(path: Path, rows: dict[int, BankRow], ids: set[int]) -> dict[int, bytes]:
    with path.open("rb") as vectors:
        records = {}
        for sid in sorted(ids):
            offset, length, *_ = rows[sid]
            vectors.seek(offset)
            value = vectors.read(length)
            if len(value) != length:
                raise ValueError("Frozen feature bytes fall outside the committed bank")
            records[sid] = value
        return records


def _probe_ids(index: list[StateIndex], new: set[int]) -> list[int]:
    representative: dict[tuple[str, int, bool], int] = {}
    for row in index:
        representative.setdefault((row.dataset, row.budget, row.id in new), row.id)
    return sorted(representative.values())


def _read_heads(
    checkpoints: list[Path], dataset: MemoryControlDataset, cache: Path,
    index: list[StateIndex], probes: list[int], device: str,
) -> list[dict[str, Any]]:
    import torch

    rows = dataset.training_rows(probes)
    readouts = []
    for checkpoint in checkpoints:
        model = SmallControlModel.load(checkpoint, device=device)
        model.train(False)
        store = FrozenFeatureStore(cache, dataset, model)
        counters = model.counters.copy()
        store.open(index)
        with torch.no_grad():
            states, actions, owners, lengths = store.batch(probes, rows, model.device)
            output = model.head(states, actions, owners)
        if output.numel() != sum(lengths) or not bool(torch.isfinite(output).all().item()):
            raise ValueError("Frozen feature probe did not produce finite action logits")
        if model.counters != counters:
            raise ValueError("The frozen feature read unexpectedly ran encoder work")
        readouts.append({
            "checkpoint": str(checkpoint), "architecture": model.config.object_architecture,
            "shared_states_opened": len(store.rows), "probe_states": len(probes),
            "probe_action_logits": output.numel(), "encoder_forwards": 0,
        })
        del store, model, states, actions, owners, output
    return readouts


def warm_registered_core(args: argparse.Namespace) -> dict[str, Any]:
    import torch

    clock, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(args.threads)
    dataset = MemoryControlDataset(args.data.resolve(strict=True),
                                   observation_protocol="semantic_nav_v1")
    index = registered_index(dataset, read_json(args.roster))
    ids = {row.id for row in index}
    if not index or len(args.checkpoint) != 2 or args.feature_batch_states < 1:
        raise ValueError("Provide a registered TRAIN roster and the two actual W checkpoints")
    checkpoints = [x.resolve(strict=True) for x in args.checkpoint]
    for checkpoint in checkpoints:
        w = read_json(checkpoint.parent / "run.json")
        contract = w["contract"]
        if (w["status"] != "COMPLETED" or contract["dataset_run_id"] != dataset.run_id
                or contract["supervision_mode"] != "weak"
                or contract["observation_protocol"] != dataset.observation_protocol
                or not contract["bucket_encoder_lengths"]
                or read_json(checkpoint / "config.json") != contract["config"]):
            raise ValueError("Checkpoint differs from the completed registered W input")
    bank = args.feature_store.resolve(strict=True)
    metadata_path = bank / "offsets.sqlite3"
    vectors_path = bank / "vectors.f32"
    old = _bank_rows(metadata_path)
    absent = ids - old.keys()
    old_end = max((offset + length for offset, length, *_ in old.values()), default=0)
    probes = _probe_ids(index, absent)
    existing_probes = (set(probes) - absent) | {next(reversed(old))} if old else set()
    previous_bytes = _vector_bytes(vectors_path, old, existing_probes)
    model = SmallControlModel.load(checkpoints[0], device=args.device)
    model.batch_tokens_by_length = True
    store = FrozenFeatureStore(bank, dataset, model)
    prep = store.prepare(
        dataset, model, index, cpu_workers=args.loader_workers,
        states_per_batch=args.feature_batch_states,
    )
    after = _bank_rows(metadata_path)
    if not ids <= after.keys() or any(after.get(sid) != entry for sid, entry in old.items()):
        raise ValueError("Prewarming changed a previously committed offset or left a roster gap")
    if prep["states_encoded"] > len(absent) or any(after[sid][0] < old_end for sid in absent):
        raise ValueError("Frozen vectors were not appended to the existing bank")
    if _vector_bytes(vectors_path, after, existing_probes) != previous_bytes:
        raise ValueError("A prior literal vector probe changed during append")
    for ordered in batches([row.id for row in index], 256):
        rows = dataset.training_rows(ordered)
        for sid, row in zip(ordered, rows, strict=True):
            if store.rows[sid][2] != [action["id"] for action in row["actions"]]:
                raise ValueError("The feature store differs from the trainer's legal action order")
    del store, model
    readouts = _read_heads(checkpoints, dataset, bank, index, probes, args.device)
    return {
        "status": "VERIFIED_REGISTERED_CORE_FEATURES_READY",
        "as_of": datetime.now().astimezone().isoformat(), "dataset_run_id": dataset.run_id,
        "roster": str(args.roster.resolve()), "bank": str(bank),
        "registered_states": len(index), "prior_bank_entries": len(old),
        "current_bank_entries": len(after), "previous_index_rows_unchanged": len(old),
        "new_registered_states": len(absent), "literal_old_vector_probes": len(existing_probes),
        "new_registered_by_source": dict(Counter(row.dataset for row in index if row.id in absent)),
        "append": prep, "registered_menu_matches": len(index), "both_w_head_readouts": readouts,
        "wall_seconds": time.perf_counter() - clock, "cpu_seconds": time.process_time() - cpu,
        "optimizer_updates": 0, "reader_requests": 0, "sha_validation": False,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for item in ("data", "roster", "feature-store", "output"):
        cli.add_argument(f"--{item}", required=True, type=Path)
    cli.add_argument("--checkpoint", required=True, type=Path, action="append")
    cli.add_argument("--device", default="cuda:0")
    cli.add_argument("--threads", type=int, default=2)
    cli.add_argument("--loader-workers", type=int, default=2)
    cli.add_argument("--feature-batch-states", type=int, default=32)
    args = cli.parse_args()
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".feature-preparation.lock").open("ab") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = root / "receipt.json"
        if receipt.exists():
            raise FileExistsError(
                "Use a new output directory for another feature preparation receipt"
            )
        write_json(root / "status.json", {
            "status": "WARMING_REGISTERED_CORE_FEATURES", "pid": os.getpid(),
        })
        try:
            result = warm_registered_core(args)
        except BaseException as exc:
            write_json(root / "status.json", {
                "status": "STOPPED", "pid": os.getpid(), "reason": f"{type(exc).__name__}: {exc}",
            })
            raise
        write_json(receipt, result)
        write_json(root / "status.json", {"status": result["status"], "pid": os.getpid(),
                                          "receipt": str(receipt)})
        print(result["status"], result["registered_states"], result["new_registered_states"])


if __name__ == "__main__":
    main()
