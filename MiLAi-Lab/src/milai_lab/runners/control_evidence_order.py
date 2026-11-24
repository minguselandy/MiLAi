"""Recover a frozen S1 sampling order from native task identities and legal action prefixes."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sqlite3
import zlib
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import NamedTuple

from milai_lab.datasets.memory_control_store import connect, get_meta

FIELDS = ("dataset", "split", "native_group", "native_id", "setting", "source_row")
FORMAT = "s1_native_task_prefix_order_v1"
ADDRESS_FORMAT = "s1_rebuilt_root_addresses_v1"


class Address(NamedTuple):
    frozen_row: int
    local_row: int
    frozen_task: int
    local_task: int
    source: str
    group: str


def _database(path: Path) -> Path:
    return path / "memory_control.sqlite3" if path.is_dir() else path


def _tasks(master: Path) -> tuple[str, dict[int, tuple]]:
    with closing(connect(_database(master))) as db:
        by_id = {
            row[0]: tuple(row[1:])
            for row in db.execute("""
            SELECT id,dataset,split,native_group,native_id,setting,source_row
            FROM experiment_tasks WHERE experiment_role='train' AND clean_role='train'
        """)
        }
        run = get_meta(db, "run_id")
    if not by_id or len(set(by_id.values())) != len(by_id):
        raise ValueError("TRAIN task source/split/group/native ID/setting/source row is ambiguous")
    if any(None in key for key in by_id.values()):
        raise ValueError("Missing native task identity")
    return run, by_id


def _protocol(db):
    manifest = dict(db.execute("SELECT field,value FROM manifest"))
    if not (manifest.get("complete") and manifest.get("replay_complete")):
        raise ValueError("Both evidence preparation passes must be complete")
    # Paths may change on restoration. Remaining fields encode seed, operations,
    # material budget, retrieval pool and scored pool.
    stored = json.loads(manifest["protocol"])
    return Path(stored[0]), stored[1:]


def _roots(db, by_id):
    result = {}
    seen = set()
    for local, tid, source, group, blob in db.execute(
        "SELECT id,task_id,source,native_group,data FROM roots"
    ):
        row = json.loads(zlib.decompress(blob))
        native = by_id.get(tid)
        root_id = row["root_state_id"]
        if (
            not native
            or (native[0], native[2]) != (source, group)
            or (row["task_id"], row["source"], row["native_group_id"], row["split_role"])
            != (tid, source, group, "train")
            or not root_id
            or root_id[0] != tid
        ):
            raise ValueError(f"Root {local} is outside its native TRAIN task")
        prefix = tuple(root_id[1:])
        if not prefix or prefix[0] != "search" or not all(isinstance(x, str) and x for x in prefix):
            raise ValueError(f"Root {local} has an invalid bound prefix")
        key = (native, prefix)
        if key in seen:
            raise ValueError(f"Duplicate native task and executed prefix at local row {local}")
        seen.add(key)
        result[local] = (tid, prefix)
    return result


def _write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as tmp:
        pending = Path(tmp.name)
    try:
        with gzip.open(pending, "wt", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        try:
            os.link(pending, path)
        except FileExistsError:
            with gzip.open(path, "rb") as old, gzip.open(pending, "rb") as new:
                while True:
                    a, b = old.read(1024 * 1024), new.read(1024 * 1024)
                    if a != b:
                        raise ValueError(f"Existing registration differs: {path}") from None
                    if not a:
                        break
    finally:
        pending.unlink(missing_ok=True)


def freeze(db, master, output):
    source_root, protocol = _protocol(db)
    run, tasks = _tasks(master or source_root)
    by_row = _roots(db, tasks)
    # Use the normal training index entry point's iteration order, not the order
    # of the scan that included the compressed supervision payload.
    ids = [r[0] for r in db.execute("SELECT id,source,native_group FROM roots")]
    if len(ids) != len(by_row) or set(ids) != set(by_row):
        raise ValueError("Training index and physical root population differ")
    header = dict(
        format=FORMAT,
        fields=FIELDS,
        master_run=run,
        protocol=protocol,
        tasks=len(tasks),
        roots=len(ids),
    )

    def rows():
        yield header
        for tid, task in sorted(tasks.items()):
            yield ["task", tid, *task]
        for local in ids:
            tid, prefix = by_row[local]
            yield ["root", local, tid, *prefix]

    _write_lines(output, rows())
    return header


def _read_frozen(path):
    with gzip.open(path, "rt", encoding="utf-8") as source:
        header = json.loads(next(source))
        if header.get("format") != FORMAT or tuple(header.get("fields", ())) != FIELDS:
            raise ValueError("Unsupported S1 order mapping")
        tasks = {}
        for _ in range(header["tasks"]):
            tag, tid, *native = json.loads(next(source))
            if tag != "task" or tid in tasks or len(native) != len(FIELDS) or None in native:
                raise ValueError("Invalid native task in frozen mapping")
            tasks[tid] = tuple(native)
        if len(set(tasks.values())) != len(tasks):
            raise ValueError("Nonunique frozen native task")
        roots = []
        seen = set()
        for line in source:
            tag, ordinal, tid, *prefix = json.loads(line)
            key = tid, tuple(prefix)
            if (
                tag != "root"
                or tid not in tasks
                or not prefix
                or prefix[0] != "search"
                or key in seen
            ):
                raise ValueError("Invalid or duplicated frozen root")
            seen.add(key)
            roots.append((ordinal, tid, tuple(prefix)))
    if len(roots) != header["roots"] or len({r[0] for r in roots}) != len(roots):
        raise ValueError("Incomplete frozen root address sequence")
    return header, tasks, roots


def align(db: sqlite3.Connection, path: Path, master: Path | None = None):
    header, frozen_tasks, order = _read_frozen(path)
    source_root, protocol = _protocol(db)
    if header["protocol"] != protocol:
        raise ValueError("Rebuilt collection protocol differs from frozen native order")
    run, tasks = _tasks(master or source_root)
    translated = {key: tid for tid, key in tasks.items()}
    if set(translated) != set(frozen_tasks.values()):
        raise ValueError("Rebuilt and frozen native TRAIN task populations differ")
    rebuilt = _roots(db, tasks)
    addresses = {key: local for local, key in rebuilt.items()}
    if len(addresses) != len(order):
        raise ValueError("Rebuilt and frozen root counts differ")
    result = []
    for frozen_row, tid, prefix in order:
        native = frozen_tasks[tid]
        local_tid = translated[native]
        local_row = addresses.pop((local_tid, prefix), None)
        if local_row is None:
            raise ValueError(f"Missing rebuilt native root for frozen row {frozen_row}")
        result.append(Address(frozen_row, local_row, tid, local_tid, native[0], native[2]))
    if addresses:
        raise ValueError("Unexpected rebuilt native roots")
    return header, run, result


def read_canonical_row(db, address: Address) -> dict:
    result = db.execute("SELECT data FROM roots WHERE id=?", (address.local_row,)).fetchone()
    if result is None:
        raise ValueError(f"Missing aligned row {address.local_row}")
    row = json.loads(zlib.decompress(result[0]))
    if row["task_id"] != address.local_task or row["root_state_id"][0] != address.local_task:
        raise ValueError("Rebuilt root refers to a different task")
    row["task_id"] = address.frozen_task
    row["root_state_id"][0] = address.frozen_task
    prefix = row["root_state_id"][1:]
    if row["online"]["observation"].setdefault("action_history", prefix) != prefix:
        raise ValueError("Recorded history differs from reconstructed prefix")
    return row


def align_file(db, manifest, master, destination, reference_evidence=None):
    header, run, addresses = align(db, manifest, master)
    stats = dict(
        format=ADDRESS_FORMAT,
        reference=str(manifest.resolve()),
        reference_master_run=header["master_run"],
        rebuilt_master_run=run,
        native_tasks=header["tasks"],
        native_roots=len(addresses),
        changed_root_addresses=sum(a.frozen_row != a.local_row for a in addresses),
        changed_task_addresses=sum(a.frozen_task != a.local_task for a in addresses),
        roots_by_source=Counter(a.source for a in addresses),
    )

    stats["equivalent_payloads"] = None
    if reference_evidence is not None:
        with closing(connect(reference_evidence)) as original:
            for address in addresses:
                frozen = Address(
                    address.frozen_row,
                    address.frozen_row,
                    address.frozen_task,
                    address.frozen_task,
                    address.source,
                    address.group,
                )
                if read_canonical_row(original, frozen) != read_canonical_row(db, address):
                    raise ValueError(f"Legal input or supervision differs at {address.frozen_row}")
        stats["equivalent_payloads"] = len(addresses)

    def rows() -> Iterator:
        yield stats
        for addr in addresses:
            yield [addr.frozen_row, addr.local_row, addr.frozen_task, addr.local_task]

    _write_lines(destination, rows())
    with gzip.open(destination, "rt", encoding="utf-8") as stream:
        for expected, line in zip(rows(), stream, strict=True):
            if json.loads(line) != expected:
                raise ValueError("Aligned address file differs on independent readback")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("freeze")
    resolve = sub.add_parser("align")
    for cmd in (create, resolve):
        cmd.add_argument("--evidence", type=Path, required=True)
        cmd.add_argument("--master", type=Path, help="Native dataset root or original SQLite index")
        cmd.add_argument("--output", type=Path, required=True)
    resolve.add_argument(
        "--reference", type=Path, required=True, help="Frozen native order .jsonl.gz"
    )
    resolve.add_argument(
        "--reference-evidence",
        type=Path,
        help="Optionally compare every normalized training payload to the frozen evidence DB",
    )
    args = parser.parse_args()
    with closing(connect(args.evidence)) as connection:
        connection.execute("BEGIN")
        report = (
            freeze(connection, args.master, args.output)
            if args.command == "freeze"
            else align_file(
                connection, args.reference, args.master, args.output, args.reference_evidence
            )
        )
    print(json.dumps(report, ensure_ascii=False))
