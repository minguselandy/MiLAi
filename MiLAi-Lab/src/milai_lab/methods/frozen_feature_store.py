"""Shared variable-length float32 vectors for the frozen independent encoder."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import time
from array import array
from collections import Counter, deque
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from milai_lab.datasets.memory_control_report import write_json
from milai_lab.methods.control_numeric import ACTION_WIDTH, STATE_WIDTH, numeric_rows

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
    def __init__(
        self, root: Path, dataset: MemoryControlDataset, model: SmallControlModel,
        *, raw_store: Path | None = None, _raw_only: bool = False,
    ) -> None:
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
        self.numeric: dict[int, bytes] = {}
        self.projection_lane: str | None = None
        self.raw_store: FrozenFeatureStore | None = None
        if _raw_only:
            self.manifest["encoder_config"]["object_feature_layout"] = "literal_v1"
            self.projection_lane = "raw"
        if raw_store is not None:
            layout = model.config.object_feature_layout
            if (layout not in {"dual_raw_v2", "dual_semantic_v2"}
                    or raw_store.resolve() == root.resolve()):
                raise ValueError("A distinct shared raw store requires the V1.2 dual layout")
            self.raw_store = FrozenFeatureStore(raw_store, dataset, model, _raw_only=True)
            self.projection_lane = (
                "semantic_availability" if layout == "dual_raw_v2" else "semantic"
            )
            self.manifest.update(
                layout="ragged_with_shared_raw_v2", raw_store=str(raw_store.resolve()),
                supplemental_lane=self.projection_lane,
            )
        self.numeric_schema: str | None = None
        if getattr(dataset, "numeric_observation", False) and not _raw_only:
            self.numeric_schema = dataset.control_release["declaration"]["numeric_schema"]
        self.values: Any = None
        self.width = 0

    def _validate_manifest(self) -> str | None:
        recorded = json.loads((self.root / "features.json").read_text())
        legacy_numeric = recorded.pop("numeric_schema", None)
        if recorded != self.manifest:
            raise ValueError("Frozen features describe a different encoder or online state")
        if legacy_numeric is not None and not isinstance(legacy_numeric, str):
            raise ValueError("Frozen numeric schema must have a versioned identifier")
        numeric_path = self.root / "numeric-features.json"
        if not numeric_path.exists():
            return legacy_numeric
        declared = json.loads(numeric_path.read_text())["numeric_schema"]
        if not isinstance(declared, str):
            raise ValueError("Frozen numeric schema must have a versioned identifier")
        if legacy_numeric is not None and declared != legacy_numeric:
            raise ValueError("Frozen numeric schema disagrees with the original feature manifest")
        return declared

    @staticmethod
    def _numeric_record(sid: int, row: dict[str, Any]) -> tuple[int, bytes]:
        global_values, action_values = numeric_rows(row)
        flattened = array("f", global_values)
        for action_values_row in action_values:
            flattened.extend(action_values_row)
        return sid, flattened.tobytes()

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
        navigation: Counter[str] = Counter()
        objects_encoded = 0
        numeric_created = 0
        before = dict(model.counters)
        raw_receipt = None
        if self.raw_store is not None:
            raw_receipt = self.raw_store.prepare(
                dataset, model, index, cpu_workers=cpu_workers,
                states_per_batch=states_per_batch,
            )
        with (self.root / ".cache.lock").open("a") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            manifest_path = self.root / "features.json"
            declared_numeric = None
            if manifest_path.exists():
                declared_numeric = self._validate_manifest()
            else:
                write_json(manifest_path, self.manifest)
            if self.numeric_schema is not None:
                if declared_numeric is not None and declared_numeric != self.numeric_schema:
                    raise ValueError("Frozen numeric features describe a different input schema")
                if declared_numeric is None:
                    write_json(self.root / "numeric-features.json", {
                        "numeric_schema": self.numeric_schema,
                    })
            with closing(sqlite3.connect(self.index_path)) as db:
                db.execute("""CREATE TABLE IF NOT EXISTS vectors (
                    state_id INTEGER PRIMARY KEY, byte_offset INTEGER NOT NULL,
                    byte_length INTEGER NOT NULL, object_count INTEGER NOT NULL,
                    action_ids TEXT NOT NULL, width INTEGER NOT NULL
                )""")
                if self.numeric_schema is not None:
                    db.execute("""CREATE TABLE IF NOT EXISTS numeric_vectors (
                        state_id INTEGER PRIMARY KEY REFERENCES vectors(state_id),
                        payload BLOB NOT NULL
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
                            if self.projection_lane is None:
                                states, actions, _, lengths = model.features(
                                    inputs, pad_to_batch=True,
                                )
                            else:
                                states, actions, _, lengths = model.object_features(
                                    inputs, pad_to_batch=True, projection_lane=self.projection_lane,
                                )
                            cpu_states = states.detach().float().cpu()
                            cpu_actions = actions.detach().float().cpu()
                            build_time += time.perf_counter() - tick
                            tick = time.perf_counter()
                            action_offset = 0
                            records = []
                            numeric_records = []
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
                                if self.numeric_schema is not None:
                                    numeric_records.append(self._numeric_record(sid, row))
                                navigation.update(row.get("navigation_costs", {}))
                                objects_encoded += objects + length
                                action_offset += length
                            values.flush()
                            os.fsync(values.fileno())
                            with db:
                                db.executemany("INSERT INTO vectors VALUES (?,?,?,?,?,?)", records)
                                if numeric_records:
                                    db.executemany(
                                        "INSERT INTO numeric_vectors VALUES (?,?)", numeric_records,
                                    )
                            numeric_created += len(numeric_records)
                            io_time += time.perf_counter() - tick
                finally:
                    static_cache = model.base_encoding_cache_report()
                    model.configure_base_encoding_cache(0)
                if self.numeric_schema is not None:
                    saved_numeric = {sid for (sid,) in db.execute(
                        "SELECT state_id FROM numeric_vectors"
                    )}
                    order = sorted(index, key=lambda row: (row.root, row.task, row.id))
                    missing_numeric = [row.id for row in order if row.id not in saved_numeric]
                    for ids, rows, elapsed in prefetch_rows(
                        dataset, batches(missing_numeric, states_per_batch), cpu_workers,
                        features_only=True,
                    ):
                        loader_sum += elapsed
                        numeric_updates = []
                        for sid, row in zip(ids, rows, strict=True):
                            base = db.execute(
                                "SELECT object_count,action_ids FROM vectors WHERE state_id=?",
                                (sid,),
                            ).fetchone()
                            ids_in_menu = [action["id"] for action in row["actions"]]
                            if (base is None or base[0] != row["object_count"] + 2
                                    or json.loads(base[1]) != ids_in_menu):
                                raise ValueError("Numeric features changed the cached action menu")
                            numeric_updates.append(self._numeric_record(sid, row))
                            navigation.update(row.get("navigation_costs", {}))
                        tick = time.perf_counter()
                        with db:
                            db.executemany(
                                "INSERT INTO numeric_vectors VALUES (?,?)", numeric_updates,
                            )
                        numeric_created += len(numeric_updates)
                        io_time += time.perf_counter() - tick
        self.open(index)
        return {
            "states_encoded": len(pending),
            "states_reused": len(index) - len(pending),
            "object_and_action_vectors_encoded": objects_encoded,
            "numeric_states_written": numeric_created,
            "navigation_work": dict(navigation),
            "storage_bytes": self.values_path.stat().st_size,
            "encoding_and_transfer_wall_seconds": build_time,
            "mmap_write_wall_seconds": io_time,
            "loader_task_wall_seconds_sum": loader_sum,
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - wall,
            "static_encoder_cache": static_cache,
            "encoder_work": {key: value - before[key] for key, value in model.counters.items()},
            **({"shared_raw_preparation": raw_receipt} if raw_receipt is not None else {}),
        }

    def open(self, index: list[StateIndex]) -> None:
        import numpy as np

        declared_numeric = self._validate_manifest()
        if self.numeric_schema is not None and declared_numeric != self.numeric_schema:
            raise ValueError("Frozen numeric store does not match the actual input schema")
        if self.raw_store is not None:
            self.raw_store.open(index)
        self.rows.clear()
        self.numeric.clear()
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
            if self.numeric_schema is not None:
                for sid, values in db.execute("SELECT state_id,payload FROM numeric_vectors"):
                    if sid not in requested:
                        continue
                    if len(values) != 4 * (STATE_WIDTH + len(self.rows[sid][2]) * ACTION_WIDTH):
                        raise ValueError("Numeric cache row does not match its original menu")
                    self.numeric[sid] = values
                if self.numeric.keys() != requested:
                    raise ValueError("Numeric cache does not cover the requested states")
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

    def numeric_batch(self, ids: list[int], device: Any) -> tuple[Any, Any]:
        import numpy as np
        import torch

        states, actions = [], []
        for sid in ids:
            vector = np.frombuffer(self.numeric[sid], dtype=np.float32)
            states.append(vector[:STATE_WIDTH])
            actions.append(vector[STATE_WIDTH:].reshape(-1, ACTION_WIDTH))
        return (torch.from_numpy(np.stack(states)).to(device),
                torch.from_numpy(np.concatenate(actions)).to(device))

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
        states = states.to(device, non_blocking=pinned)
        actions = actions.to(device, non_blocking=pinned)
        if self.raw_store is not None:
            raw_states, raw_actions, _, raw_lengths = self.raw_store.batch(ids, online, device)
            if raw_lengths != lengths or raw_states.shape[:2] != states.shape[:2]:
                raise ValueError("Shared raw features differ from the supplemental lane binding")
            if self.projection_lane == "semantic_availability":
                states, actions = raw_states * states, raw_actions * actions
            elif raw_states.shape[-1] != states.shape[-1]:
                raise ValueError("Raw and semantic embedding dimensions differ")
            states = torch.cat((raw_states, states), dim=-1)
            actions = torch.cat((raw_actions, actions), dim=-1)
        return (
            states,
            actions,
            owners.to(device, non_blocking=pinned),
            lengths,
        )
