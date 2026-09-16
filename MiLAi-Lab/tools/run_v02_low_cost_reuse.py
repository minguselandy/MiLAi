"""Ordinary G and independent full-A0 F/S tasks for the v02-03 study."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import time
from pathlib import Path

import run_v02_memory_flow as base
from run_v02_lme_reuse import remap
from run_v02_low_cost_diagnostics import CONFIG, DATA, ROOT
from v02_lme_capture import capture_persistent
from v02_lme_host import run_host
from v02_low_cost_protocol import (
    allocation_gate,
    allocation_rows,
    derived_events,
    derived_history,
    digest,
    operational_cost,
)
from v02_low_cost_public import observer
from v02_task_artifacts import carry_task_artifacts

PLAN = base.LAB / "studies/active/MILA_V02_LOW_COST_REUSE_R.json"


def run(case: str, arm: str, future: str | None, attempt: int = 1) -> None:
    config = base.read_json(CONFIG)
    phase = config.get("execution_phase", "N3_N4")
    pin = base.pin(CONFIG)
    base.assert_services(ROOT)
    cluster = next(c for c in base.read_json(PLAN)["clusters"] if c["case_id"] == case)
    if (arm == "G") != (future is None):
        raise ValueError("Only future arms have a future task")
    followup = next((f for f in cluster["followups"] if f["id"] == future), None)
    if arm != "G" and followup is None:
        raise ValueError("Future not prespecified")
    generator = ROOT / "sessions" / f"r-{case}-G"
    completed_pointer = ROOT / f"generator-{case}.json"
    if completed_pointer.exists():
        generator = Path(base.read_json(completed_pointer)["observation"])
        if arm == "G":
            raise RuntimeError("This history already has its one completed G")
    checkpoint = None
    if arm != "G":
        review = base.read_json(generator / "qualification.json")
        checkpoint = base.read_json(generator / "checkpoint.json")
        if review["status"] != "ELIGIBLE" or checkpoint["status"] != "SAVED_CONFIRMED":
            raise RuntimeError("No eligible actual extra checkpoint")
    source_path = DATA / "sources" / f"{case}.json"
    expected_hash = base.read_json(DATA / "manifest.json")["cases"][case]["source_sha256"]
    if digest(source_path) != expected_hash:
        raise ValueError("Source hash mismatch")
    history = derived_history(base.read_json(source_path), cluster["cutoff"])
    raw = json.dumps(history, ensure_ascii=False, indent=2).encode()
    session = f"r-{case}-" + ("G" if arm == "G" else f"{future}-{arm}")
    if attempt != 1:
        session += f"-r{attempt}"
    batch = "r-generators" if arm == "G" else f"r-future-{case}"
    batch += f"-v{config['execution_batch_version']}"
    roots = [p for p in ROOT.parent.iterdir() if p.is_dir()]
    roots.extend(base.LAB / p for p in config.get("historical_allocation_roots", []))
    rows = allocation_rows(roots)
    timeout = allocation_gate(rows, config, phase, batch)
    identity = {"pin": pin, "config_sha256": digest(CONFIG), "plan_sha256": digest(PLAN),
                "code": {p: digest(base.LAB / "tools" / p) for p in (
                    "run_v02_low_cost_reuse.py", "v02_low_cost_protocol.py", "v02_exact_note.py",
                    "v02_low_cost_public.py", "v02_lme_host.py", "v02_codex_container.py",
                    "v02_low_cost_container.py",
                    "v02_lme_capture.py", "v02_lme_capture_worker.py", "v02_task_artifacts.py")}}
    frozen = ROOT / "batches" / batch / "identity.json"
    if frozen.exists():
        if base.read_json(frozen) != identity:
            raise RuntimeError("BATCH_IDENTITY_CHANGED")
    else:
        frozen.parent.mkdir(parents=True)
        base.write_json(frozen, identity)
    observation = ROOT / "sessions" / session
    observation.mkdir(parents=True, exist_ok=False)
    task = secrets.token_hex(12)
    project = "v0203-" + task
    base.write_json(observation / "allocation.json", {
        "phase": phase, "batch_id": batch, "arm": arm, "case_id": case,
        "kind": "COMMON_TASK" if arm == "G" else "FOLLOWUP", "allocation_id": session,
        "task_ref": task, "project": project, "cutoff": cluster["cutoff"],
        "source_sha256": digest(source_path), "session_timeout_seconds": timeout,
        "started_at": time.time(), **identity})
    (observation / "events.jsonl").touch()
    started = time.perf_counter()
    try:
        with observer(ROOT, observation, project, task) as (call, values):
            base.write_json(observation / "tool-catalog.json", call(None, {}))
            before = call("milai_working_state_get", {"scope": "TASK"})
            if before["status"] != "ABSENT":
                raise RuntimeError("New branch has State")
            prepared = capture_persistent(values, project, derived_events(history, task),
                                           observation, 300)
            base.write_json(observation / "source-preparation.json", prepared)
            workspace = ROOT / "host-sessions" / secrets.token_hex(12) / "workspace"
            (workspace / "sources").mkdir(parents=True)
            (workspace / "sources/history.json").write_bytes(raw)
            artifacts = []
            if arm != "G":
                prior = Path(base.read_json(generator / "host-paths.json")["workspace"])
                artifacts = carry_task_artifacts(prior, workspace)
                if (prior / "answer.txt").exists():
                    shutil.copy2(prior / "answer.txt", workspace / "prior-task-answer.txt")
                    artifacts.append({"path": "prior-task-answer.txt",
                                      "sha256": digest(prior / "answer.txt")})
                old = [json.loads(s) for s in
                       (generator / "source-receipts.jsonl").read_text().splitlines()]
                new = [json.loads(s) for s in
                       (observation / "source-receipts.jsonl").read_text().splitlines()]
                mapping = {str(prior): str(workspace)}
                for a, b in zip(old, new, strict=True):
                    if a["source_id"].split("/session/")[1] != b["source_id"].split("/session/")[1]:
                        raise ValueError("Source mapping mismatch")
                    mapping[a["source_id"]] = b["source_id"]
                    mapping[a["receipt"]["evidence_id"]] = b["receipt"]["evidence_id"]
                base.write_json(observation / "branch-evidence-map.json", mapping)
                for artifact in artifacts:
                    path = workspace / artifact["path"]
                    try:
                        text = path.read_bytes().decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    path.write_bytes(remap(text, mapping).encode())
                    artifact["branch_sha256"] = digest(path)
                parent_head = (base.read_json(generator / "after.json") if arm == "F"
                               else checkpoint["after"])
                if parent_head["status"] == "ACTIVE":
                    payload = remap(parent_head["payload"], mapping)
                    receipt = call("milai_working_state_update", {
                        "operation_id": "seed-" + task, "expected_version": 0, "payload": payload})
                    base.write_json(observation / "initialization-receipt.json", receipt)
                    before = call("milai_working_state_get", {"scope": "TASK"})
                    if before["status"] != "ACTIVE" or before["payload"] != payload:
                        raise RuntimeError("Branch did not recover exact parent State")
            base.write_json(observation / "before.json", before)
            base.write_json(observation / "task-artifacts.json", artifacts)
            base.write_json(observation / "source-access.json", {
                "history_sha256": digest(workspace / "sources/history.json"),
                "native_question_removed": True, "future_questions_mounted": False,
                "labels_mounted": False, "cutoff": cluster["cutoff"]})
            base.write_json(observation / "preparation-timing.json", {
                "research_preparation_seconds": time.perf_counter() - started})
            prompt = cluster["current_task"] if arm == "G" else followup["question"]
            prompt += ("\nConversation history is available in sources/history.json and project "
                       "memory. History boundary: " + cluster["cutoff"] + ".")
            result = run_host(ROOT, observation, workspace, values, config, prompt, task, project,
                              before, call, timeout)
            result.update(operational_cost(result, observation))
            base.write_json(observation / "result.json", result)
            files = [{"path": str(p.relative_to(workspace)), "sha256": digest(p),
                      "bytes": p.stat().st_size} for p in workspace.rglob("*")
                     if p.is_file() and not p.is_symlink()]
            base.write_json(observation / "completed-files.json", files)
            if arm == "G" and result["returncode"] == 0 and result["stop_reason"] is None:
                base.write_json(completed_pointer, {"observation": str(observation)})
            print(json.dumps({"session": session, "returncode": result["returncode"],
                              "tokens": result["known_tokens"],
                              "operational_seconds": result["operational_online_seconds"]}))
    except Exception as exc:
        process_exists = (observation / "process.json").exists()
        existing = base.read_json(observation / "result.json") if (
            observation / "result.json").exists() else {}
        base.write_json(observation / "result.json", {**existing, "status": "EXECUTION_FAILURE",
            "model_started": process_exists, "failure_type": type(exc).__name__,
            "failure": str(exc), "raw_elapsed_seconds": time.perf_counter() - started})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("27016adc", "852ce960"), required=True)
    parser.add_argument("--arm", choices=("G", "F", "S"), required=True)
    parser.add_argument("--future")
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()
    run(args.case, args.arm, args.future, args.attempt)
