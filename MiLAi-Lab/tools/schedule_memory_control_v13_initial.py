"""Time-share our live S1/REF fits and the initial Reader queue without changing the service."""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import time
from pathlib import Path


def read(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def initial_readouts_closed(root):
    for family in ("rule", "gte-batch8"):
        selection = read(root / "baselines" / f"{family}-selection.json")
        if (
            not selection
            or not (root / "baselines/tune" / selection["selected"] / "summary.json").exists()
        ):
            return False
    return (root / "evidence-diagnostic/capture.json").is_file() and (
        root / "annotated-evidence-curve/summary.json"
    ).is_file()


def known_process(pid, entry, root):
    args = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    if entry.encode() not in args or not any(os.fsencode(root) in arg for arg in args):
        raise ValueError(f"Process {pid} is outside the declared experiment")
    return os.pidfd_open(pid)


def main(args):
    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    phase = args.root / "initial-schedule.json"
    handles = []
    stopped = []
    record = dict(
        scheduler_pid=os.getpid(),
        ref_pid=args.ref_pid,
        s1_pid=args.s1_pid,
        devices=dict(reader=[0, 1], reference=2, controller=3),
        accounting=(
            "Four physical resident devices. This interval separates independent "
            "fit computation from V13 Reader dispatch."
        ),
    )
    try:
        handles.append(known_process(args.ref_pid, "train_q_rag.py", args.root))
        handles.append(
            known_process(args.s1_pid, "milai_lab.runners.pretrained_control_train", args.root)
        )
        while not (args.root / "weights/s1/resume.pt").is_file():
            if select.select(handles, [], [], 2)[0]:
                raise RuntimeError("A fit exited before publishing the first S1 recovery state")
        # A pidfd cannot signal a later process that reuses the same numerical PID.
        for fd in handles:
            signal.pidfd_send_signal(fd, signal.SIGSTOP)
            stopped.append(fd)
        record.update(phase="initial_reader", started_ns=time.time_ns())
        save(phase, record)
        while True:
            if read(args.root / "resource-choice.json").get("mode") == "parallel_authorized":
                record["exit_reason"] = "updated_resource_choice"
                break
            warm = read(args.root / "warm-11/progress.json").get("feedback_calls", 0)
            # At an exact budget boundary the last partially bought pack can be omitted
            # from progress.json. Inspect the final exposure receipt in that case.
            if 1995 <= warm < 2000:
                from run_memory_control_v13_rounds import exposure

                warm = exposure(args.root / "warm-11")
            if warm >= 2000 and initial_readouts_closed(args.root):
                record["exit_reason"] = "initial_reader_queue_closed"
                break
            time.sleep(5)
    finally:
        for fd in stopped:
            try:
                signal.pidfd_send_signal(fd, signal.SIGCONT)
            except ProcessLookupError:
                pass
        for fd in handles:
            os.close(fd)
        if stopped:
            record.update(phase="independent_fit", ended_ns=time.time_ns())
            save(phase, record)


def advance(args):
    import fcntl

    from milai_lab.runners.v13_phase import UNITS, activate, state

    # Parked neural fits retain their own process state. Only this experiment's future
    # guarded work is admitted by the manifest. Existing Reader service is never leased here.
    root = args.root.resolve()
    with (root / ".phase-advance.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            phase = read(root / "initial-schedule.json").get("phase")
            explicit = read(root / "resource-choice.json").get("mode") == "parallel_authorized"
            complete = (
                read(root / "weights/s1/run.json").get("status") == "completed"
                and read(args.ref_result).get("optimizer_updates") == 10000
            )
            if explicit or complete:
                allow, reason = (
                    UNITS,
                    (
                        "user-selected parallel compute"
                        if explicit
                        else "reference curve and S1 complete; serialize core work units"
                    ),
                )
            elif phase == "initial_reader":
                allow, reason = {"reader", "evaluate"}, "initial TRAIN feedback and DEV readouts"
            elif phase == "independent_fit":
                allow, reason = {"fit"}, "complete the reference and evidence fits"
            else:
                raise RuntimeError("Initial phase owner is missing; inspect its live run")
            current = state(root / "phase")
            if (
                set(current.get("allow", [])) != set(allow)
                or current.get("parallel") != explicit
                or current.get("state") != "active"
            ):
                activate(root, allow, parallel=explicit, reason=reason)
            if explicit or complete:
                return
            time.sleep(20)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument(
        "--advance",
        action="store_true",
        help="Advance grants from the observed initial phase and completed fit receipts",
    )
    p.add_argument("--ref-result", type=Path)
    p.add_argument("--ref-pid", type=int)
    p.add_argument("--s1-pid", type=int)
    args = p.parse_args()
    if args.advance:
        if args.ref_result is None:
            p.error("--advance requires the retained reference result path")
        advance(args)
    elif args.ref_pid and args.s1_pid:
        main(args)
    else:
        p.error("Provide both live fit PIDs for an initial rotation")
