"""Cooperative V13 phase boundaries, outside the native Reader transport lease."""

from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path

from milai_lab.datasets.memory_control_report import write_json

UNITS = {"fit", "reader", "evaluate", "pq", "qr"}
PROTOCOL = "memory_control_v13_phases_v1"


def phase_directory(path: Path, *, supervised_qr: bool = False):
    folder = path.absolute()
    for ancestor in (folder, *folder.parents):
        candidate = ancestor / "phase"
        if (candidate / "managed.json").is_file():
            return candidate
    if supervised_qr and (folder / "launch.json").exists():
        return folder.parent / "phase"
    return None


def state(directory):
    path = directory / "phase.json"
    if not path.exists():
        return {}
    with path.open() as f:
        data = json.load(f)
    if data.get("protocol") != PROTOCOL or data.get("root") != str(directory.parent.absolute()):
        raise ValueError("Phase declaration belongs to a different experiment")
    return data


def activate(root: Path, allow, *, parallel=False, reason=""):
    directory = root.absolute() / "phase"
    directory.mkdir(parents=True, exist_ok=True)
    allow = sorted(set(allow))
    if not set(allow) <= UNITS:
        raise ValueError("Unknown V13 unit")
    with (directory / "scheduler.lock").open("a") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX)
        declaration = dict(
            protocol=PROTOCOL,
            root=str(directory.parent),
            issued_ns=time.time_ns(),
            allow=allow,
            parallel=parallel,
            reason=reason,
        )
        write_json(
            directory / "managed.json", {"protocol": PROTOCOL, "root": str(directory.parent)}
        )
        # New workers wait; the single exclusive lease waits for already admitted bounded work.
        write_json(directory / "phase.json", dict(declaration, state="draining"))
        with (directory / "units.lock").open("a") as units:
            fcntl.flock(units, fcntl.LOCK_EX)
            result = dict(declaration, state="active", active_ns=time.time_ns())
            write_json(directory / "phase.json", result)
    return result


@contextmanager
def phase_unit(directory, unit, *, waiting=None):
    if unit not in UNITS:
        raise ValueError(f"Unknown V13 work unit {unit}")
    if directory is None:
        yield
        return
    directory.mkdir(parents=True, exist_ok=True)
    last = object()
    with (directory / "units.lock").open("a") as lease:
        while True:
            current = state(directory)
            permitted = current.get("state") == "active" and unit in current["allow"]
            if permitted:
                # CPU-only readers rely on their common native transport owner. Independent fits
                # can share dedicated controller cards during a fit-only phase. Mixed units execute
                # serially under a strict resource envelope.
                allowed = set(current["allow"])
                shared = (
                    current["parallel"]
                    or (unit == "fit" and allowed == {"fit"})
                    or (unit == "reader" and allowed <= {"reader", "evaluate"})
                )
                fcntl.flock(lease, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                if state(directory) == current:
                    break
                fcntl.flock(lease, fcntl.LOCK_UN)
            if waiting is not None and current != last:
                waiting(current)
                last = current
            time.sleep(0.5)
        try:
            yield
        finally:
            fcntl.flock(lease, fcntl.LOCK_UN)
