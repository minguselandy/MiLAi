"""Mirror atomically published upstream actors and preserve live resource observations."""

import argparse
import fcntl
import json
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

import yaml


def read(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def durable(path, value):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def progress(log):
    with log.open("rb") as f:
        f.seek(max(0, log.stat().st_size - 32000))
        results = re.findall(rb"(\d+)/80000\s*\[", f.read())
    return int(results[-1]) if results else None


def watch(args):
    run, root = args.run.resolve(), args.root.resolve()
    archive = run / "retained-actors"
    archive.mkdir(exist_ok=True)
    lock = (archive / ".writer.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    owner = Path(f"/proc/{args.pid}")
    cmd = (owner / "cmdline").read_bytes().split(b"\0")
    if b"train_q_rag.py" not in cmd or os.fsencode("logger.log_dir=" + str(run.parent)) not in cmd:
        raise ValueError("Unexpected REF process or run")
    ticks = os.sysconf("SC_CLK_TCK")
    start = int((owner / "stat").read_text().split()[21])
    poll = select.poll()
    fd = os.pidfd_open(args.pid)
    poll.register(fd, select.POLLIN)
    config = yaml.safe_load((run / "config.yaml").read_text())
    model_dir = Path(config["checkpoint_dir"])
    curve = run / "tb_logs/reference-curve.jsonl"
    base = args.base.resolve()
    index = read(archive / "index.json")
    if index:
        if (index["pid"], index["start_ticks"]) != (args.pid, start):
            resumed = read(run / "fit-resumed.json")
            if (resumed.get("pid"), resumed.get("start_ticks"), resumed.get("run")) != (
                args.pid,
                start,
                str(run),
            ):
                raise ValueError("A previous REF incarnation owns this mirror")
            durable(archive / f"index-before-{args.pid}.json", index)
            index.update(pid=args.pid, start_ticks=start)
            durable(archive / "index.json", index)
    else:
        index = {
            "pid": args.pid,
            "start_ticks": start,
            "upstream_run": str(run),
            "base": str(base),
            "actors": {},
        }
    log = run.parent / "training.log"
    last_ticks = {}
    elapsed = read(archive / "live-resource.json").get(
        "process_elapsed_to_observation_seconds", 0.0
    )

    def heartbeat(compressing=None):
        nonlocal last_ticks, elapsed
        now = time.time_ns()
        live = not bool(poll.poll(0))
        if live:
            if not model_dir.is_dir():
                model_dir.mkdir(parents=True, exist_ok=True)
                print(f"Restored absent checkpoint parent {model_dir}", flush=True)
            elapsed = time.clock_gettime(time.CLOCK_BOOTTIME) - start / ticks
            try:
                stat = (owner / "stat").read_text().split()
            except FileNotFoundError:
                stat = []
            if stat and int(stat[21]) == start:
                last_ticks = {
                    "state": stat[2],
                    "user_cpu_seconds": int(stat[13]) / ticks,
                    "system_cpu_seconds": int(stat[14]) / ticks,
                }
        else:
            settled = read(run.parent / "fit-resource.json")
            if settled.get("pid") == args.pid:
                elapsed = settled["elapsed_seconds"]
        phase = read(root / "initial-schedule.json")
        parked = 0
        if phase.get("ref_pid") == args.pid and "started_ns" in phase:
            parked = max(0, (phase.get("ended_ns", now) - phase["started_ns"]) / 1e9)
        rows = (
            [json.loads(line) for line in curve.read_text().splitlines()] if curve.exists() else []
        )
        position = progress(log)
        durable(
            archive / "live-resource.json",
            {
                "observed_ns": now,
                "pid": args.pid,
                "start_ticks": start,
                "live_at_observation": live,
                **last_ticks,
                "process_elapsed_to_observation_seconds": elapsed,
                "retained_parked_seconds": parked,
                "process_wall_minus_recorded_park_seconds": max(0, elapsed - parked),
                "observed_completed_rollouts": position,
                "last_validation": rows[-1] if rows else None,
                "latest_durable_actor_updates": {
                    k: v["optimizer_updates"] for k, v in index["actors"].items()
                },
                "compressing": compressing,
                "full_optimizer_recovery": False,
                "scope": "Live observation; last observation before host loss is a lower bound",
            },
        )
        return rows

    while True:
        rows = heartbeat()
        live = not bool(poll.poll(0))
        for kind in ("best", "last") if rows else ():
            current = model_dir / f"model_{kind}.pt"
            if not current.exists():
                continue
            best = max(rows, key=lambda x: x["gt_dev_return"])
            row = best if kind == "best" else rows[-1]
            step = row["optimizer_updates"]
            if kind == "last" and step != config["steps_count"]:
                continue
            info = current.stat()
            ident = [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size]
            prev = index["actors"].get(kind, {})
            if prev.get("source_stat") == ident:
                continue
            if kind == "best" and row == rows[-1] and info.st_mtime_ns < curve.stat().st_mtime_ns:
                continue
            pinned = model_dir / f".watch-{os.getpid()}-{kind}.pt"
            dest = archive / f"{kind}-u{step:06d}.zip"
            receipt = archive / f"{kind}-u{step:06d}.json"
            try:
                os.link(current, pinned)
            except FileNotFoundError:
                continue
            try:
                # An atomic best publication may race stat/link. Retry on its next observed inode.
                if pinned.stat().st_ino != info.st_ino:
                    continue
                adopt = kind == "best" and args.adopt and step == args.adopt_update
                cmd = [
                    sys.executable,
                    str(Path(__file__).with_name("qrag_ref_actor_delta.py")),
                    "verify" if adopt else "compact",
                    "--actor",
                    str(pinned),
                    "--base",
                    str(base),
                    "--delta",
                    str(args.adopt if adopt else dest),
                ]
                with (
                    (archive / "codec-output.tmp").open("w") as output,
                    subprocess.Popen(  # noqa: S603 -- local verified codec command
                        cmd,
                        stdout=output,
                        env={**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"},
                    ) as child,
                ):
                    while child.poll() is None:
                        heartbeat(f"{kind}/update-{step}")
                        try:
                            child.wait(20)
                        except subprocess.TimeoutExpired:
                            pass
                    if child.returncode:
                        raise ValueError(f"Actor archive did not verify (exit {child.returncode})")
                if adopt and not dest.exists():
                    os.link(args.adopt, dest)
                detail = read(archive / "codec-output.tmp")
                detail.update(
                    kind=kind,
                    optimizer_updates=step,
                    archive=str(dest),
                    base=str(base),
                    bytes=dest.stat().st_size,
                    source_stat=ident,
                    receipt=str(receipt),
                )
                durable(receipt, detail)
                index["actors"][kind] = detail
                durable(archive / "index.json", index)
                if prev:
                    old = Path(prev["archive"])
                    if old != dest and old.parent == archive:
                        old.unlink(missing_ok=True)
            finally:
                pinned.unlink(missing_ok=True)
        if not live:
            heartbeat()
            break
        poll.poll(20000)
    os.close(fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--adopt", type=Path)
    parser.add_argument("--adopt-update", type=int, default=-1)
    watch(parser.parse_args())
