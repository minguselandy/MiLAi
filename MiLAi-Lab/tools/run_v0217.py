"""Shared A, public exact-note branch copy, then paired fresh-process continuations."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from replay_v0213_cost import read, save, sha
from run_v0212_horizon import product
from run_v0215 import prepare, state_write_arguments
from v02_local_provider import accounting, read_events
from v0210_v05_product import observer
from v0214_host_runtime import source_runtime
from v0216_support import mechanical_preflight
from v0217_support import public_work_history

LAB = Path(__file__).resolve().parents[1]


def scope_for(root: Path, key: str, arm: str) -> str:
    return "v0215-" + sha(f"{root.name}/{key}/{arm}".encode())[:24]


def check_manifest(root: Path) -> dict:
    manifest = read(root / "manifest.json")
    assert sha((root / "manifest.json").read_bytes()) == read(root / "manifest-sha256.json")[
        "sha256"]
    for path, digest in manifest["implementation"].items():
        assert sha((LAB / path).read_bytes()) == digest
    for path, digest in manifest["files"].items():
        assert sha((root / path).read_bytes()) == digest
    for path, digest in manifest["model_assets"].items():
        assert sha(Path(path).read_bytes()) == digest
    assert source_runtime(manifest["config"])[1] == manifest["host_acquisition"]
    assert len(set(manifest["baseline_system_sha256"].values())) == 1
    return manifest


def run_batch(root: Path, installed: Path) -> dict:
    manifest = check_manifest(root)
    cfg = manifest["config"]
    rows, trajectories = [], []
    started = time.monotonic()

    def cold(owned, key, arm, phase):
        used = sum(row["accounting"]["requests"] for row in rows)
        if used + cfg["max_generations_per_phase"] > cfg["max_batch_generations"]:
            raise ValueError("BATCH_REQUEST_ALLOCATION_EXHAUSTED")
        remaining = cfg["max_batch_seconds"] - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("BATCH_TIME_LIMIT")
        subprocess.run(  # noqa: S603 -- frozen local Host with bounded allocation
            [sys.executable, str(LAB / "tools/run_v0215.py"), "--root", str(root),
             "--cold", key, "--arm", arm, "--phase", str(phase), "--owned", str(owned)],
            check=True, timeout=min(remaining, cfg["seconds_per_phase"] + 20), cwd=LAB)
        row = read(root / "runs" / key / arm / f"phase-{phase}/result.json")
        rows.append(row)
        save(root / "progress.json", {"results": rows, "trajectories": trajectories})
        if row["accounting"]["pending"] or row["accounting"]["violations"] or row[
                "delivery_budget"]["pending"]:
            raise ValueError("UNKNOWN_USAGE_STOP")
        if row.get("reason", "").startswith("PUBLIC_STATE_OPERATION_FAILED"):
            raise ValueError("PUBLIC_COMMIT_FAILED_OR_UNKNOWN")
        return row

    with product(root / "product", installed) as owned:
        mechanical_preflight(owned, root, cfg)
        for index, key in enumerate(cfg["tasks"]):
            upstream = cold(owned, key, "A", 0)
            trajectory = {"key": key, "upstream": upstream["status"],
                "event_script_frozen_before_A": True, "note_selection": "ENTIRE_LATEST_TASK_SLOT"}
            trajectories.append(trajectory)
            source = root / "runs" / key / "A/phase-0"
            scope = scope_for(root, key, "A")
            handoff = root / "handoffs" / key
            handoff.mkdir(parents=True)
            with observer(owned, handoff / "get-A", task=scope,
                          principal=scope, project=scope) as public:
                state = public("milai_working_state_get", {"scope": "TASK"})
            save(handoff / "upstream-state.json", state)
            if state.get("mcp_error"):
                raise ValueError("COMMIT_OR_RESTORE_UNKNOWN")
            history = public_work_history(read_events(source / "actions.jsonl"),
                                          read_events(source / "tool-results.jsonl"))
            history_path = root / "cases" / key / "online/phase-1/source-90-work-history.txt"
            save(history_path, history)
            # A's genuine work product is public; its notebook, requests and receipts stay offline.
            snapshot = {str(p.relative_to(root)): sha(p.read_bytes()) for p in
                        history_path.parent.iterdir() if p.is_file()}
            save(handoff / "continuation-snapshot.json", snapshot)
            save(handoff / "interruption.json", {"old_host_pid": upstream["pid"],
                "old_host_terminated": True, "inherited_messages": 0,
                "event": read(history_path.parent / "task.json")["observation"],
                "event_kind": "PREDEFINED_ENVIRONMENT_CHANGE_AFTER_PROCESS_EXIT",
                "elapsed_time_claim": "NO_LONG_TERM_WAIT_CLAIM"})
            note = state.get("payload", {}).get("note")
            trajectory.update(note_status="COMMITTED" if note else "NO_WRITE",
                source_state_version=state.get("version"),
                note_sha256=sha(note.encode()) if note else None,
                note_bytes=len(note.encode()) if note else 0)
            if note:
                assert upstream["state_writes"] > 0
                branch = scope_for(root, key, "N1")
                with observer(owned, handoff / "branch-N1", task=branch,
                              principal=branch, project=branch) as public:
                    absent = public("milai_working_state_get", {"scope": "TASK"})
                    assert absent["status"] == "ABSENT"
                    copied = public("milai_working_state_update", state_write_arguments(
                        absent, note, branch + "-exact-upstream-copy"))
                    assert not copied.get("mcp_error"), copied
                    assert copied["payload"] == state["payload"]
                save(handoff / "branch-copy.json", {"kind": "EXACT_PUBLIC_NOTE_BRANCH_COPY",
                    "origin": state, "destination_absent": absent, "receipt": copied,
                    "content_rewritten": False, "copy_sha256": sha(note.encode())})
                arms = ["N0", "N1"] if index % 2 == 0 else ["N1", "N0"]
            else:
                assert upstream["state_writes"] == 0
                arms = ["N0"]
            trajectory["continuation_order"] = arms
            trajectory["pair_status"] = "PENDING_INPUT_AUDIT" if note else "NOTE_USE_NOT_EXERCISED"
            for arm in arms:
                for path, digest in snapshot.items():
                    assert sha((root / path).read_bytes()) == digest
                cold(owned, key, arm, 1)
                restored = read(root / "runs" / key / arm / "phase-1/cold-resume.json")["state"]
                if arm == "N0":
                    assert restored["status"] == "ABSENT"
                else:
                    assert restored == copied
            save(root / "progress.json", {"results": rows, "trajectories": trajectories})
    return {"status": "PAIRED_DISCOVERY_EXECUTION_SETTLED", "results": rows,
        "trajectories": trajectories, "requests": sum(x["accounting"]["requests"] for x in rows),
        "raw_tokens": sum(x["accounting"]["raw_tokens"] for x in rows),
        "seconds": time.monotonic() - started, "cleanup": read(root / "product/cleanup.json"),
        "shared_upstream_cost_counted_once": True, "raw_cap": None}


def run(root: Path, installed: Path):
    if (root / "result.json").exists():
        raise ValueError("ALREADY_TERMINAL_USE_NEW_RUN")
    try:
        result = run_batch(root, installed)
    except (Exception, KeyboardInterrupt) as exc:
        costs = [accounting(read_events(path)) for path in root.glob(
            "runs/*/*/phase-*/provider-ledger.jsonl")]
        progress = read(root / "progress.json") if (root / "progress.json").exists() else {}
        result = {"status": "STOPPED_PRESERVE_ALL_NO_RETRY", "reason": str(exc), **progress,
            "requests": sum(x["requests"] for x in costs),
            "raw_tokens": sum(x["raw_tokens"] for x in costs),
            "unknown_requests": sum(len(x["pending"]) for x in costs)}
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prepare-from", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--installed", type=Path)
    args = parser.parse_args()
    if args.prepare_from:
        value = prepare(args.root, args.prepare_from, args.config)
        shutil.copyfile(LAB / value["config"]["goal_document"], args.root / "goal-as-executed.md")
    else:
        value = run(args.root, args.installed)
    print(json.dumps({k: value[k] for k in ("status", "requests", "raw_tokens", "reason")
                      if k in value}))
