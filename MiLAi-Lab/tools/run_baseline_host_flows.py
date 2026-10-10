"""Prepare/explicitly run the existing Host stories; summarize stored results offline.

This entry delegates every message to run_functional.py. It changes no Host
permissions, tools or evaluator-control projection. Root schedules real calls;
there is no automatic dispatch, restart, unknown retry or semantic grading.
Summary outputs contain private text and belong under ignored artifacts/.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
STORIES = ("state-view-correction-history", "l4-h09")
FLOW_CHECKS = (
    "save-correct-actual-saved-history",
    "business-complete-save-only-fresh-query",
    "forget-reopen-read",
)
REPEATS = 3


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def cli(arguments: list[str], runtime: Path, output: Path) -> subprocess.CompletedProcess[str]:
    """Use the original CLI, with a separate temporary directory and no shell."""
    runtime.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(LAB / "src"), TMPDIR=str(runtime),
               SQLITE_TMPDIR=str(runtime))
    child = subprocess.run(  # noqa: S603 -- fixed local Python/CLI, argv only
        [sys.executable, str(LAB / "tools/run_functional.py"), "--runtime-dir", str(runtime),
         *arguments], cwd=LAB, env=env, capture_output=True, text=True, check=False,
    )
    output.with_suffix(".stdout.json").write_text(child.stdout)
    output.with_suffix(".stderr.log").write_text(child.stderr)
    return child


def prepare(root: Path, config: Path, fixture: Path, controls: Path,
            source_version: str) -> dict[str, Any]:
    root, config, fixture, controls = (
        path.resolve() for path in (root, config, fixture, controls))
    if root.exists():
        raise ValueError("Use a new root; earlier preparation and failures are retained")
    original = read(fixture)
    by_id = {case["case_id"]: case for case in original["cases"]}
    selected = {**original, "cases": [by_id[name] for name in STORIES]}
    if [len(case["messages"]) for case in selected["cases"]] != [8, 6]:
        raise ValueError("Original exposed 8+6-message stories are required")
    inputs = root / "inputs"
    write(inputs / "fixture.json", selected)
    # These remain evaluator-only in the original runner; no control enters Host input.
    inputs.joinpath("controls.json").write_bytes(controls.read_bytes())
    inputs.joinpath("config.json").write_bytes(config.read_bytes())
    manifest = {
        "schema": "baseline_host_flows_v1", "status": "PREPARING",
        "repeat_count_predeclared": REPEATS, "source_version": source_version,
        "stories": list(STORIES), "story_runs": len(STORIES) * REPEATS,
        "flow_checks": list(FLOW_CHECKS), "planned_messages": 14 * REPEATS,
        "original_fixture": str(fixture.resolve()),
        "independence": "Three flow checks share two stories; repetitions are not new tasks.",
        "ordinary_failure_policy": "Keep known protocol/capacity/format failures and continue.",
        "stop_policy": "Unknown effect, Store/snapshot, budget or undeclared failure stops.",
        "automatic_dispatch_or_retry": False, "semantic_correctness": "unchecked",
    }
    write(root / "protocol.json", manifest)
    for repeat in range(1, REPEATS + 1):
        prepared = root / f"rep-{repeat}"
        child = cli([
            "prepare", "--root", str(prepared), "--config", str(inputs / "config.json"),
            "--fixture", str(inputs / "fixture.json"), "--controls", str(inputs / "controls.json"),
            "--source-version", source_version,
        ], root / "runtime" / f"rep-{repeat}", root / f"prepare-{repeat}")
        if child.returncode:
            manifest["status"] = "PREPARATION_FAILED"
            write(root / "protocol.json", manifest)
            raise ValueError(f"Original prepare failed in repeat {repeat}; stderr retained")
    manifest["status"] = "PREPARED_NOT_DISPATCHED"
    write(root / "protocol.json", manifest)
    return manifest


def has_unknown(value: Any) -> bool:
    if isinstance(value, dict):
        return any((key == "status" and isinstance(item, str) and "unknown" in item.lower())
                   or has_unknown(item) for key, item in value.items())
    return isinstance(value, list) and any(has_unknown(item) for item in value)


def stop_reason(result: dict[str, Any], before: dict[str, Any],
                after: dict[str, Any]) -> str | None:
    if any(after[kind]["unknown_usage"] > before[kind]["unknown_usage"]
           for kind in ("generation", "embedding")):
        return "unconfirmed_model_outcome"
    if any(key in result for key in (
        "snapshot_error", "maintenance_snapshot_error", "application_snapshot_error",
        "checkpoint_snapshot_error", "capture_visibility_error", "failure_delivery_error",
    )):
        return "store_or_snapshot_failure"
    if result.get("status") in {"UNKNOWN", "PROVIDER_ERROR", "BUDGET_EXHAUSTED", "NOT_ADMITTED"}:
        return str(result["status"])
    if has_unknown(result.get("operation_status", {})):
        return "unconfirmed_operation"
    known = result.get("error_category") in {
        "provider_protocol", "request_capacity", "execution_limit", "final_delivery",
    } or result.get("error") in {
        "FUNCTIONAL_REQUIRED_MEMORY_OPERATION_MISSING",
        "FUNCTIONAL_COMPLETION_FEEDBACK_BUDGET_EXHAUSTED",
        "FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED",
    }
    if result.get("status") != "COMPLETED" and not known:
        return "undeclared_failure"
    return None


def serial_run(root: Path, schedule_note: str) -> dict[str, Any]:
    """Explicit Root dispatch after resources are free; not tied to old research gates."""
    root = root.resolve()
    if not schedule_note.strip():
        raise ValueError("Record Root's scheduling decision before dispatch")
    protocol = read(root / "protocol.json")
    if protocol["status"] != "PREPARED_NOT_DISPATCHED" or (root / "execution.json").exists():
        raise ValueError("Existing dispatch or incomplete preparation; no automatic restart")
    freezes = [read(root / f"rep-{repeat}" / "input-freeze.json")
               for repeat in range(1, REPEATS + 1)]
    for repeat, freeze in enumerate(freezes, 1):
        if ([case["case_id"] for case in freeze["fixture"]["cases"]] != list(STORIES)
                or [len(case["messages"]) for case in freeze["fixture"]["cases"]] != [8, 6]
                or any(freeze[key] != freezes[0][key]
                       for key in ("config", "fixture", "evaluator_controls", "source_version"))
                or (root / f"rep-{repeat}" / "banks").exists()):
            raise ValueError("Prepared inputs differ or a bank was already initialized")
    ledger = Path(freezes[0]["config"]["budget_path"])
    with ledger.with_suffix(ledger.suffix + ".http-owner.lock").open("a+b") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Original HTTP owner is live; no new calls dispatched") from error
        before = read(ledger)
        fcntl.flock(lease, fcntl.LOCK_UN)
    execution = {
        "status": "RUNNING", "pid": os.getpid(), "schedule_note": schedule_note,
        "started_at": datetime.now(UTC).isoformat(), "source_version": freezes[0]["source_version"],
        "planned_messages": 42, "repeats": REPEATS, "story_runs": len(STORIES) * REPEATS,
        "semantic_correctness": "unchecked", "automatic_restart_or_unknown_retry": False,
    }
    write(root / "accounting-before.json", before)
    write(root / "execution.json", execution)
    halted, all_results = None, []
    for repeat, freeze in enumerate(freezes, 1):
        run_root = root / f"rep-{repeat}"
        results = []
        for case in freeze["fixture"]["cases"]:
            for index, _ in enumerate(case["messages"]):
                identity = {"case_id": case["case_id"], "message_index": index}
                if halted is not None:
                    result = {**identity, "status": "NOT_RUN", "reason": halted}
                else:
                    child = cli([
                        "step", "--root", str(run_root), "--case-id", case["case_id"],
                        "--index", str(index),
                    ], root / "runtime" / f"rep-{repeat}",
                        run_root / f"cli-{case['case_id']}-{index}")
                    try:
                        decoded = read(run_root / f"cli-{case['case_id']}-{index}.stdout.json")
                        if (not isinstance(decoded, dict)
                                or not isinstance(decoded.get("status"), str)):
                            raise ValueError("Original CLI output has no execution status")
                        result = {**decoded, **identity, "returncode": child.returncode}
                    except (ValueError, OSError):
                        result = {**identity, "status": "UNKNOWN",
                                  "error": "CLI_OUTPUT_UNAVAILABLE", "returncode": child.returncode}
                    halted = ("unexpected_cli_exit" if child.returncode else
                              stop_reason(result, before, read(ledger)))
                results.append(result)
                all_results.append({"repeat": repeat, **result})
                write(run_root / "results.json", {"results": results})
                write(root / "results.json", {"results": all_results})
    after = read(ledger)
    write(root / "accounting-after.json", after)
    execution.update(
        status=("STOPPED" if halted else
                "CLOSED_ATTEMPTS_PENDING_RECONCILIATION_AND_SEMANTIC_REVIEW"),
        closed_at=datetime.now(UTC).isoformat(), stop_reason=halted,
        attempted_messages=sum(row["status"] != "NOT_RUN" for row in all_results),
        limits_unchanged=before["limits"] == after["limits"],
    )
    write(root / "execution.json", execution)
    return execution


def evaluator() -> Any:
    specification = importlib.util.spec_from_file_location(
        "existing_functional_evaluator", LAB / "tools/v13_5_evaluate.py")
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def summary(roots: list[Path]) -> dict[str, Any]:
    """Retain all attempts and their provenance; never infer correctness from status."""
    roots = [path.resolve() for path in roots]
    if len(roots) != len(set(roots)):
        raise ValueError("Duplicate run roots are not additional repetitions")
    existing = evaluator()
    messages, runs, first_failure = [], [], None
    for repeat, run_root in enumerate(roots, 1):
        evaluated = existing.evaluate(run_root, cohort="HOST_CONTINUOUS_FLOWS")
        freeze = read(run_root / "input-freeze.json")
        runs.append({"repeat": repeat, "root": str(run_root),
                     "source_version": freeze.get("source_version"),
                     "config_version": freeze.get("config_version"),
                     "scope": "Stored run versions; summary does not replay these inputs."})
        if not set(STORIES) <= {case["case_id"] for case in evaluated["case_packs"]}:
            raise ValueError("Both declared stories are required; preserve the planned scope")
        for case in evaluated["case_packs"]:
            if case["case_id"] not in STORIES:
                continue
            for message in case["messages"]:
                attempts = []
                for attempt in message["attempts"]:
                    raw = read(Path(attempt["artifact"]))
                    trace_path = Path(attempt["trace_path"])
                    events, _ = (existing.ArtifactReader(ordinary=True).lines(trace_path)
                                 if trace_path.exists() else ([], []))
                    candidate = raw.get("execution_candidate_answer")
                    finalization = raw.get("finalization", {})
                    # A separate response stage has its own model answer. Program
                    # receipt prose is always kept only in public_delivery.
                    separate_model_response = finalization.get("status") == "response_received"
                    model_answer = raw.get("final_answer") if separate_model_response else candidate
                    if model_answer is None and not (finalization.get("model_generation") is False
                                                     or raw.get("failure_delivery")):
                        model_answer = raw.get("final_answer")
                    attempts.append({
                        "artifact": attempt["artifact"], "attempt": attempt["attempt"],
                        "execution_status": attempt["execution_status"],
                        "raw_model_answer": model_answer,
                        "raw_model_http_linkage": existing.final_linkage(
                            model_answer, events, ordinary=True),
                        "execution_candidate_answer": candidate,
                        "public_delivery": raw.get("final_answer"),
                        "public_delivery_linkage": attempt["actual_http_linkage"],
                        "actual_effect": raw.get("operation_status"),
                        "error_category": raw.get("error_category"), "error": raw.get("error"),
                        "usage": attempt["usage_from_trace"],
                        "semantic_correctness": "unchecked",
                        "earliest_semantic_breakpoint": "unchecked",
                    })
                    if first_failure is None and attempt["execution_status"] != "COMPLETED":
                        first_failure = {"repeat": repeat, "case_id": case["case_id"],
                                         "message_index": message["message_index"],
                                         "error_category": raw.get("error_category"),
                                         "error": raw.get("error"), "artifact": attempt["artifact"]}
                messages.append({
                    "repeat": repeat, "case_id": case["case_id"],
                    "message_index": message["message_index"], "source_group": case["case_id"],
                    "public_message": message["public_message"],
                    "execution_status": message["execution_status"], "attempts": attempts,
                    "record_changes_since_previous_message": (
                        message["record_changes_since_previous_message"]),
                    "orphan_traces": message["orphan_traces"],
                    "semantic_correctness": "unchecked",
                })
    return {
        "schema": "baseline_host_flow_summary_v1", "new_model_calls": 0,
        "roots": [str(path.resolve()) for path in roots], "flow_checks": list(FLOW_CHECKS),
        "runs": runs,
        "planned_messages": len(messages),
        "retained_attempts": sum(len(m["attempts"]) for m in messages),
        "message_execution_counts": dict(Counter(m["execution_status"] for m in messages)),
        "source_groups": sorted({m["source_group"] for m in messages}),
        "independence": "Three flow checks share two stories; repetitions are not new tasks.",
        "first_recorded_runtime_failure": first_failure,
        "semantic_correctness": "unchecked; COMPLETED and linkage PASS are not task success",
        "messages": messages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "serial-run", "summary"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--controls", type=Path)
    parser.add_argument("--source-version")
    parser.add_argument("--schedule-note", help="Root's explicit resource/scheduling decision")
    parser.add_argument("--run-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, help="Private offline summary under artifacts/")
    args = parser.parse_args()
    if args.command == "prepare":
        if any(value is None for value in (
            args.root, args.config, args.fixture, args.controls, args.source_version,
        )):
            parser.error("prepare requires root/config/fixture/controls/source-version")
        result = prepare(args.root, args.config, args.fixture, args.controls, args.source_version)
    elif args.command == "serial-run":
        if args.root is None or args.schedule_note is None:
            parser.error("serial-run requires root and Root's schedule-note")
        result = serial_run(args.root, args.schedule_note)
    else:
        roots = args.run_root or ([args.root / f"rep-{repeat}" for repeat in range(1, REPEATS + 1)]
                                 if args.root is not None else [])
        if not roots or args.output is None:
            parser.error("summary requires root or run-root, plus a private output path")
        result = summary(roots)
        write(args.output, result)
        result = {key: value for key, value in result.items() if key != "messages"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
