"""Shared variable-length float32 vectors for the frozen independent encoder."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import time
from collections import deque
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from milai_lab.datasets.memory_control_report import write_json

if TYPE_CHECKING:
    from milai_lab.methods.memory_control_dataset import MemoryControlDataset, StateIndex
    from milai_lab.methods.small_control_model import SmallControlModel


def batches(ids: Sequence[int], size: int) -> Iterator[list[int]]:
    for start in range(0, len(ids), size):
        yield list(ids[start : start + size])


def prefetch_rows(
    dataset: MemoryControlDataset,
    windows: Iterator[list[int]],
    workers: int,
    *,
    features_only: bool = False,
    supervision_only: bool = False,
) -> Iterator[tuple[list[int], list[dict[str, Any]], float]]:
    load = (
        dataset.training_rows
        if supervision_only
        else dataset.encoder_rows
        if features_only
        else dataset.rows
    )

    def timed(ids: list[int]) -> tuple[list[int], list[dict[str, Any]], float]:
        start = time.perf_counter()
        return ids, load(ids), time.perf_counter() - start

    if not workers:
        yield from map(timed, windows)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = deque(
            pool.submit(timed, ids)
            for _ in range(workers + 1)
            if (ids := next(windows, None)) is not None
        )
        while pending:
            result = pending.popleft().result()
            if (ids := next(windows, None)) is not None:
                pending.append(pool.submit(timed, ids))
            yield result


class FrozenFeatureStore:
    def __init__(self, root: Path, dataset: MemoryControlDataset, model: SmallControlModel) -> None:
        config = asdict(model.config)
        if (
            config["adaptation"] != "frozen"
            or config["readout"] != "objects"
            or config["family"] == "decoder"
            or any(p.requires_grad for p in model.encoder.parameters())
        ):
            raise ValueError("Shared feature caching requires independent frozen object encoding")
        self.root = root
        self.index_path = root / "offsets.sqlite3"
        self.values_path = root / "vectors.f32"
        self.manifest = {
            "storage_dtype": "float32",
            "layout": "ragged_state_major_v1",
            "dataset_run_id": dataset.run_id,
            "dataset_release": dataset.config["dataset_release"],
            "processing_version": dataset.config["processing_version"],
            "observation_protocol": dataset.observation_protocol,
            "delivery_protocol": dataset.revision["delivery_protocol"]
            if dataset.revision
            else None,
            "encoder_tokenizer": dataset.tokenizers["encoder"],
            "encoder_config": {
                k: config[k]
                for k in (
                    "family",
                    "backbone",
                    "chunk_tokens",
                    "projection_version",
                    "object_feature_layout",
                    "maximum_memory_objects",
                )
            },
        }
        self.rows: dict[int, tuple[int, int, list[str]]] = {}
        self.values: Any = None
        self.width = 0

    def prepare(
        self,
        dataset: MemoryControlDataset,
        model: SmallControlModel,
        index: list[StateIndex],
        *,
        cpu_workers: int,
        states_per_batch: int,
    ) -> dict[str, Any]:
        import torch  # type: ignore[import-not-found]

        self.root.mkdir(parents=True, exist_ok=True)
        wall, cpu = time.perf_counter(), time.process_time()
        build_time, io_time, loader_sum = 0.0, 0.0, 0.0
        before = dict(model.counters)
        with (self.root / ".cache.lock").open("a") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            manifest_path = self.root / "features.json"
            if manifest_path.exists():
                if json.loads(manifest_path.read_text()) != self.manifest:
                    raise ValueError("Frozen features describe a different encoder or online state")
            else:
                write_json(manifest_path, self.manifest)
            with closing(sqlite3.connect(self.index_path)) as db:
                db.execute("""CREATE TABLE IF NOT EXISTS vectors (
                    state_id INTEGER PRIMARY KEY, byte_offset INTEGER NOT NULL,
                    byte_length INTEGER NOT NULL, object_count INTEGER NOT NULL,
                    action_ids TEXT NOT NULL, width INTEGER NOT NULL
                )""")
                end = db.execute(
                    "SELECT coalesce(max(byte_offset+byte_length),0) FROM vectors"
                ).fetchone()[0]
                saved = {sid for (sid,) in db.execute("SELECT state_id FROM vectors")}
                pending = [
                    s.id
                    for s in sorted(index, key=lambda s: (s.root, s.task, s.id))
                    if s.id not in saved
                ]
                model.train(False)
                model.configure_base_encoding_cache(32 * 1024**2)
                try:
                    self.values_path.touch()
                    with self.values_path.open("r+b") as values, torch.no_grad():
                        if values.seek(0, os.SEEK_END) < end:
                            raise ValueError("Feature vectors are shorter than committed entries")
                        values.truncate(end)
                        values.seek(end)
                        for ids, rows, elapsed in prefetch_rows(
                            dataset,
                            batches(pending, states_per_batch),
                            cpu_workers,
                            features_only=True,
                        ):
                            loader_sum += elapsed
                            tick = time.perf_counter()
                            inputs = [
                                {key: row[key] for key in ("observation", "actions")}
                                for row in rows
                            ]
                            states, actions, _, lengths = model.features(inputs, pad_to_batch=True)
                            cpu_states = states.detach().float().cpu()
                            cpu_actions = actions.detach().float().cpu()
                            build_time += time.perf_counter() - tick
                            tick = time.perf_counter()
                            action_offset = 0
                            records = []
                            for sid, row, state, length in zip(
                                ids,
                                rows,
                                cpu_states,
                                lengths,
                                strict=True,
                            ):
                                width = state.shape[-1]
                                objects = row["object_count"] + 2
                                binding_ids = [action["id"] for action in row["actions"]]
                                if length != len(binding_ids) or objects > state.shape[0]:
                                    raise ValueError(
                                        "Feature vectors do not align with actual state"
                                    )
                                start = values.tell()
                                values.write(state[:objects].numpy().tobytes())
                                values.write(
                                    cpu_actions[action_offset : action_offset + length]
                                    .numpy()
                                    .tobytes()
                                )
                                records.append(
                                    (
                                        sid,
                                        start,
                                        values.tell() - start,
                                        objects,
                                        json.dumps(binding_ids),
                                        width,
                                    )
                                )
                                action_offset += length
                            values.flush()
                            os.fsync(values.fileno())
                            with db:
                                db.executemany("INSERT INTO vectors VALUES (?,?,?,?,?,?)", records)
                            io_time += time.perf_counter() - tick
                finally:
                    static_cache = model.base_encoding_cache_report()
                    model.configure_base_encoding_cache(0)
        self.open(index)
        return {
            "states_encoded": len(pending),
            "states_reused": len(index) - len(pending),
            "storage_bytes": self.values_path.stat().st_size,
            "encoding_and_transfer_wall_seconds": build_time,
            "mmap_write_wall_seconds": io_time,
            "loader_task_wall_seconds_sum": loader_sum,
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - wall,
            "static_encoder_cache": static_cache,
            "encoder_work": {key: value - before[key] for key, value in model.counters.items()},
        }

    def open(self, index: list[StateIndex]) -> None:
        import numpy as np

        if json.loads((self.root / "features.json").read_text()) != self.manifest:
            raise ValueError("Shared feature store contract changed")
        requested = {row.id for row in index}
        with closing(
            sqlite3.connect(f"{self.index_path.resolve().as_uri()}?mode=ro", uri=True)
        ) as db:
            widths = set()
            for sid, offset, length, objects, actions, width in db.execute("SELECT * FROM vectors"):
                if sid not in requested:
                    continue
                binding_ids = json.loads(actions)
                if length != (objects + len(binding_ids)) * width * 4 or offset % (width * 4):
                    raise ValueError("Invalid ragged feature row dimensions")
                self.rows[sid] = (offset // (width * 4), objects, binding_ids)
                widths.add(width)
            if not requested <= self.rows.keys() or len(widths) != 1:
                raise ValueError("Shared features do not cover the requested dataset IDs")
            (self.width,) = widths
        size = self.values_path.stat().st_size
        if size % (self.width * 4):
            raise ValueError("Frozen feature storage has incomplete values")
        self.values = np.memmap(
            self.values_path,
            dtype=np.float32,
            mode="r",
            shape=(size // (self.width * 4), self.width),
        )

    def batch(
        self,
        ids: list[int],
        online: list[dict[str, Any]],
        device: Any,
    ) -> tuple[Any, Any, Any, list[int]]:
        import torch

        entries = [self.rows[sid] for sid in ids]
        lengths = [len(entry[2]) for entry in entries]
        pinned = device.type == "cuda"
        states = torch.zeros(
            (len(ids), max(entry[1] for entry in entries), self.width),
            dtype=torch.float32,
            pin_memory=pinned,
        )
        actions = torch.empty((sum(lengths), self.width), dtype=torch.float32, pin_memory=pinned)
        offset = 0
        for i, ((first, n_objects, action_ids), row, length) in enumerate(
            zip(entries, online, lengths, strict=True),
        ):
            if action_ids != [action["id"] for action in row["actions"]]:
                raise ValueError("Cached action order differs from the actual menu")
            # Copy into the microbatch buffer, preserving read-only mapped storage.
            state_array, action_array = (
                states[i, :n_objects].numpy(),
                actions[offset : offset + length].numpy(),
            )
            state_array[:] = self.values[first : first + n_objects]
            action_array[:] = self.values[first + n_objects : first + n_objects + length]
            offset += length
        owners = torch.repeat_interleave(
            torch.arange(len(ids)), torch.tensor(lengths), output_size=sum(lengths)
        )
        return (
            states.to(device, non_blocking=pinned),
            actions.to(device, non_blocking=pinned),
            owners.to(device, non_blocking=pinned),
            lengths,
        )
