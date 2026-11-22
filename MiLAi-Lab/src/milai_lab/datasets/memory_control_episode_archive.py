"""Retain completed episode packets in a lossless, streamable tar archive."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tarfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_report import read_json, write_json

EPISODE_ARCHIVE = "episodes.tar.zst"


def _zstd() -> str:
    executable = shutil.which("zstd")
    if executable is None:
        raise FileNotFoundError("Completed episode compaction requires zstd")
    return executable


def _archive_members(path: Path) -> Iterator[tuple[str, bytes]]:
    args = [_zstd(), "-q", "-d", "-c", "--", str(path)]
    with subprocess.Popen(args, stdout=subprocess.PIPE) as child:  # noqa: S603
        assert child.stdout is not None
        with child.stdout as stream:
            with tarfile.open(fileobj=stream, mode="r|") as bundle:
                for member in bundle:
                    if not member.isfile():
                        raise ValueError(f"An episode archive must contain regular packets: {path}")
                    payload = bundle.extractfile(member)
                    if payload is None:
                        raise ValueError(f"Missing packet payload for {member.name}")
                    with payload:
                        yield member.name, payload.read()
            while stream.read(1024 * 1024):
                pass
        status = child.wait()
        if status:
            raise subprocess.CalledProcessError(status, args)


def _bound_record(
    name: str, payload: bytes, roster: dict[str, dict[str, Any]], seen: set[str],
) -> dict[str, Any]:
    if name not in roster or name in seen:
        raise ValueError(f"An archived packet is outside its registered roster: {name}")
    record: object = json.loads(payload)
    if not isinstance(record, dict) or any(
        record.get(key) != roster[name][key] for key in ("task_id", "dataset", "native_group")
    ):
        raise ValueError(f"Archived episode identity changed for {name}")
    seen.add(name)
    return record


def read_archived_episodes(
    root: Path, tasks: list[dict[str, Any]],
) -> dict[int, dict[str, Any]] | None:
    path = root / EPISODE_ARCHIVE
    if not path.is_file():
        return None
    roster = {f"{row['task_id']}.json": row for row in tasks}
    seen: set[str] = set()
    episodes = {}
    for name, payload in _archive_members(path):
        record = _bound_record(name, payload, roster, seen)
        episodes[record["task_id"]] = record
    if seen != roster.keys():
        raise ValueError(f"The archive lacks registered episode positions: {path}")
    return episodes


def archive_completed_readout(root: Path) -> dict[str, Any]:
    """Publish a byte-verified archive before releasing redundant per-task copies."""
    with (root / ".episode-writer.lock").open("ab") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        run = read_json(root / "run.json")
        tasks = read_json(root / "protocol.json")["population"]["tasks"]
        roster = {f"{row['task_id']}.json": row for row in tasks}
        if run["status"] != "COMPLETED" or len(roster) != len(tasks) or not roster:
            raise ValueError("Compaction requires a complete, uniquely registered episode readout")
        archive = root / EPISODE_ARCHIVE
        originals = root / "episodes"
        existing = {path.name: path for path in originals.glob("*.json")}
        creating = not archive.is_file()
        if not existing.keys() <= roster.keys() or (creating and existing.keys() != roster.keys()):
            raise ValueError("The source packets differ from the registered complete roster")
        partial = archive.with_suffix(".zst.part")
        try:
            if creating:
                args = [_zstd(), "-q", "-3", "-T1", "--no-check", "-c"]
                with partial.open("wb") as target, subprocess.Popen(  # noqa: S603
                    args, stdin=subprocess.PIPE, stdout=target,
                ) as child:
                    assert child.stdin is not None
                    with child.stdin as stream, tarfile.open(fileobj=stream, mode="w|") as bundle:
                        for name in roster:
                            bundle.add(existing[name], arcname=name, recursive=False)
                    status = child.wait()
                    if status:
                        raise subprocess.CalledProcessError(status, args)

            seen: set[str] = set()
            raw_bytes = 0
            statuses: Counter[str] = Counter()
            for name, payload in _archive_members(partial if creating else archive):
                record = _bound_record(name, payload, roster, seen)
                raw_bytes += len(payload)
                statuses[record["status"]] += 1
                if name in existing and existing[name].read_bytes() != payload:
                    raise ValueError(f"Archive copy changed the bytes for {name}")
            if seen != roster.keys() or dict(statuses) != run["by_episode_status"]:
                raise ValueError("Archive contents do not reproduce the completed readout receipt")
            if creating:
                with partial.open("rb") as stored:
                    os.fsync(stored.fileno())
                partial.replace(archive)
                directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            receipt = {
                "status": "ARCHIVED_COMPLETED_EPISODES", "archive": str(archive.resolve()),
                "episodes": len(seen), "by_episode_status": dict(statuses),
                "raw_packet_bytes": raw_bytes, "archive_bytes": archive.stat().st_size,
                "reader_requests": 0, "sha_validation": False,
            }
            write_json(root / "episode-archive.json", receipt)
            for path in existing.values():
                path.unlink()
            return receipt
        finally:
            partial.unlink(missing_ok=True)
