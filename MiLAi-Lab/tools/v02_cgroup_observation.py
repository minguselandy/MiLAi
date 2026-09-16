"""Read only the run-owned container's cgroup; no SQL or Product internals."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


def host_scheduler_sample(pids: dict[str, int], *, proc_root=Path("/proc")) -> dict:
    """Host-wide counters and owned main-thread scheduler clocks, not causal attribution."""
    started = time.monotonic()
    raw, unavailable, processes = {}, [], {}
    for name in ("stat", "pressure/cpu", "pressure/io"):
        try:
            raw[name] = (proc_root / name).read_text()
        except OSError:
            unavailable.append(name)
    for name, pid in pids.items():
        proc = proc_root / str(pid)
        try:
            before = start_ticks(proc)
            scheduler = (proc / "schedstat").read_text()
            after = start_ticks(proc)
            if before != after:
                processes[name] = {"pid": pid, "status": "IDENTITY_CHANGED"}
            else:
                processes[name] = {"pid": pid, "start_ticks": before,
                                   "status": "OBSERVED", "main_thread_schedstat": scheduler}
        except OSError:
            processes[name] = {"pid": pid, "status": "UNAVAILABLE"}
    return {"started_s": started, "ended_s": time.monotonic(), "host_raw": raw,
            "unavailable": unavailable, "processes": processes,
            "scope": "HOST_SHARED_COUNTERS_AND_OWNED_MAIN_THREADS_NOT_REQUEST_EXCLUSIVE"}


def start_ticks(proc: Path) -> str:
    return (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]


@dataclass(frozen=True)
class ContainerObservation:
    proc: Path
    cgroup: Path
    membership: str
    start: str

    @classmethod
    def bind(
        cls, pid: int, container_id: str, *, proc_root=Path("/proc"),
        cgroup_root=Path("/sys/fs/cgroup"),
    ):
        proc = proc_root / str(pid)
        membership = (proc / "cgroup").read_text()
        entries = [line[3:] for line in membership.splitlines() if line.startswith("0::")]
        if len(entries) != 1 or not container_id or container_id not in entries[0]:
            raise RuntimeError("RUN_CONTAINER_CGROUP_IDENTITY_UNCONFIRMED")
        cgroup = (cgroup_root / entries[0].lstrip("/")).resolve()
        if not cgroup.is_relative_to(cgroup_root.resolve()):
            raise RuntimeError("CGROUP_PATH_OUTSIDE_MOUNT")
        observer = cls(proc, cgroup, membership, start_ticks(proc))
        observer.sample()
        return observer

    def sample(self) -> dict:
        started = time.monotonic()
        if (
            (self.proc / "cgroup").read_text() != self.membership
            or start_ticks(self.proc) != self.start
        ):
            raise RuntimeError("RUN_CONTAINER_PROCESS_IDENTITY_CHANGED")
        raw = {name: (self.cgroup / name).read_text() for name in ("cpu.stat", "cpu.max")}
        unavailable = []
        for name in (
            "cpu.stat.local", "cpu.pressure", "io.stat", "io.pressure",
            "memory.current", "memory.events",
        ):
            try:
                raw[name] = (self.cgroup / name).read_text()
            except FileNotFoundError:
                unavailable.append(name)
        return {
            "started_s": started, "ended_s": time.monotonic(),
            "raw": raw, "unavailable": unavailable,
        }


def counters(raw: dict) -> dict[str, int]:
    result = {
        "cpu." + k: int(v) for k, v in (line.split() for line in raw["cpu.stat"].splitlines())
    }
    for name in ("cpu.pressure", "io.pressure"):
        for line in raw.get(name, "").splitlines():
            kind, *fields = line.split()
            values = dict(x.split("=") for x in fields)
            result[name + "." + kind + ".total_usec"] = int(values["total"])
    return result


def enclosing_window(samples: list[dict], start: float, end: float) -> dict:
    before = [s for s in samples if s["ended_s"] <= start]
    after = [s for s in samples if s["started_s"] >= end]
    if not before or not after:
        return {"status": "NOT_BRACKETED_NOT_ZERO"}
    left, right = before[-1], after[0]
    a, b = counters(left["raw"]), counters(right["raw"])
    keys = a.keys() & b.keys()
    if any(b[k] < a[k] for k in keys):
        return {"status": "COUNTER_RESET_NOT_ZERO"}
    return {
        "status": "ENCLOSING_CONTAINER_WINDOW_NOT_REQUEST_EXCLUSIVE",
        "started_s": left["started_s"], "ended_s": right["ended_s"],
        "before_margin_ms": 1000 * (start - left["started_s"]),
        "after_margin_ms": 1000 * (right["ended_s"] - end),
        "delta": {k: b[k] - a[k] for k in sorted(keys)},
        "unavailable": sorted(set(left["unavailable"]) | set(right["unavailable"])),
    }
