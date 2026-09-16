"""Conditional real State generation and independent U/V tasks, with all files retained."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any

import run_v02_memory_flow as base
from run_product09_codex_lme import _observed_at
from run_v02_lme_incremental import CONFIG, DATA, STUDY, code_identity
from v02_lme_capture import capture_persistent
from v02_lme_host import run_host
from v02_lme_sources import history_events
from v02_task_artifacts import carry_task_artifacts

PLAN = base.LAB / "studies/active/MILA_V02_LME_INCREMENTAL_R.json"


def remap(payload: Any, mapping: dict[str, str]) -> Any:
    if isinstance(payload, dict):
        return {k: remap(v, mapping) for k, v in payload.items()}
    if isinstance(payload, list):
        return [remap(v, mapping) for v in payload]
    if isinstance(payload, str):
        for old, new in mapping.items():
            payload = payload.replace(old, new)
    return payload


def reserve(root: Path, session: str, batch: str, kind: str,
            config: dict[str, Any]) -> tuple[Path, float]:
    paths = list(root.parent.glob("*/sessions/*/allocation.json"))
    if any(not (p.parent / "result.json").exists() for p in paths):
        raise RuntimeError("Resolve previous allocations before another model session")
    rows = [base.read_json(p) for p in paths]
    phase = [row for row in rows if row["phase"] == "L4"]
    if len(rows) >= config["model_phase_limits"]["total"] or len(phase) >= 12:
        raise RuntimeError("Goal or L4 allocation budget exhausted")
    if kind == "UPDATE" and sum(r["kind"] == "UPDATE" for r in phase) >= 2:
        raise RuntimeError("Real update generator budget exhausted")
    if kind == "FOLLOWUP" and sum(r["kind"] == "FOLLOWUP" for r in phase) >= 8:
        raise RuntimeError("Independent followup allocation budget exhausted")
    same = [p for p, r in zip(paths, rows, strict=True) if r["batch_id"] == batch]
    remaining = config["batch_wall_seconds"] - sum(
        base.read_json(p.parent / "result.json")["elapsed_seconds"] for p in same)
    if len(same) >= 4 or remaining <= 0:
        raise RuntimeError("L4 batch budget exhausted")
    observation = root / "sessions" / session
    observation.mkdir(parents=True, mode=0o700, exist_ok=False)
    return observation, min(config["session_timeout_seconds"], remaining)


def run(case_id: str, followup: str | None, arm: str) -> int:
    root = STUDY / "l0l1-20260905a"
    base.assert_services(root)
    verification = base.pin(CONFIG)
    config = base.read_json(CONFIG)
    plan = base.read_json(PLAN)
    cluster = next(c for c in plan["clusters"] if c["case_id"] == case_id)
    if (followup is None) != (arm == "G"):
        raise ValueError("G generates; U/V require a distinct planned followup")
    if followup is not None and followup not in {f["id"] for f in cluster["followups"]}:
        raise ValueError("Followup is not prespecified")
    generator = root / "sessions" / f"l4-{case_id}-generate"
    if arm != "G":
        decision = base.read_json(generator / "update-review.json")
        if decision["status"] != "GROUNDED_UPDATE_ELIGIBLE":
            raise RuntimeError("No reviewed real update; this chain is not evaluable")
        prior_after = base.read_json(generator / "after.json")
        prior_before = base.read_json(generator / "before.json")
        if prior_after["status"] != "ACTIVE" or prior_after["version"] <= prior_before["version"]:
            raise RuntimeError("Future branch requires an actual persisted changed State")
    raw = (DATA / "sources" / f"{case_id}.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != base.read_json(DATA / "manifest.json")["cases"][case_id]["source_sha256"]:
        raise ValueError("Full source identity mismatch")
    source = json.loads(raw)
    boundary = _observed_at(source["question_date"], 0)
    if any(_observed_at(s["observed_at"], 0) > boundary for s in source["sessions"]):
        raise ValueError("Source history exceeds the prespecified current-task boundary")
    task = secrets.token_hex(12)
    project = "v02l-" + task
    events = history_events(source, task)
    session = f"l4-{case_id}-" + ("generate" if arm == "G" else f"{followup}-{arm}")
    batch = "l4-generators" if arm == "G" else f"l4-followups-{case_id}"
    identity = {"product_pin": verification, "config_sha256": hashlib.sha256(
        CONFIG.read_bytes()).hexdigest(),
        "plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        "code": {**code_identity(), **{p: hashlib.sha256((base.LAB / "tools" / p).read_bytes())
                                       .hexdigest() for p in ["run_v02_lme_reuse.py",
                                                             "v02_lme_capture.py",
                                                             "v02_lme_capture_worker.py"]}}}
    frozen = root / "batches" / batch / "identity.json"
    if frozen.exists():
        if base.read_json(frozen) != identity:
            raise RuntimeError("L4 frozen batch changed")
    else:
        frozen.parent.mkdir(parents=True)
        base.write_json(frozen, identity)
    kind = "UPDATE" if arm == "G" else "FOLLOWUP"
    observation, timeout = reserve(root, session, batch, kind, config)
    base.write_json(observation / "allocation.json", {
        "phase": "L4", "kind": kind, "arm": arm, "case_id": case_id, "batch_id": batch,
        "task_ref": task, "project": project, "started_at": time.time(),
        "source_sha256": digest, "session_timeout_seconds": timeout, **identity})
    (observation / "events.jsonl").touch()
    values = base._load_environment(root / "runtime.env")
    token, port = secrets.token_urlsafe(32), base._free_port()
    values.update({"MILAI_CODEX_PRINCIPAL_ID": "v02-lme-host", "MILAI_CODEX_TASK_REF": task,
                   "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [project]}),
                   "MILAI_CODEX_TOKEN": token,
                   "MILAI_MCP_HTTP_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}"})
    group = base.ProcessGroup(observation)
    started = time.perf_counter()
    try:
        server = group.start("observer-mcp", [str(base.MCP / ".venv/bin/milai-codex-full-mcp"),
                                              "--port", str(port)], cwd=base.MCP,
                             env=base._clean_environment(values))
        base._wait_http(f"http://127.0.0.1:{port}/readyz", server)

        def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return base.structured(asyncio.run(base.mcp_call(
                f"http://127.0.0.1:{port}/mcp", token, tool, arguments)))

        base.write_json(observation / "tool-catalog.json", asyncio.run(base.mcp_call(
            f"http://127.0.0.1:{port}/mcp", token, None, {})))
        before = call("milai_working_state_get", {"scope": "TASK"})
        if before["status"] != "ABSENT" or before["version"] != 0:
            raise RuntimeError("New branch unexpectedly has State")
        prepared = capture_persistent(values, project, events, observation, 300)
        base.write_json(observation / "source-preparation.json", prepared)
        workspace = root / "host-sessions" / secrets.token_hex(12) / "workspace"
        (workspace / "sources").mkdir(parents=True)
        (workspace / "sources/history.json").write_bytes(raw)
        artifacts = []
        if arm != "G":
            prior_workspace = Path(base.read_json(generator / "host-paths.json")["workspace"])
            artifacts = carry_task_artifacts(prior_workspace, workspace)
            old_rows = [json.loads(line) for line in
                        (generator / "source-receipts.jsonl").read_text().splitlines()]
            new_rows = [json.loads(line) for line in
                        (observation / "source-receipts.jsonl").read_text().splitlines()]
            mapping = {str(prior_workspace): str(workspace)}
            for old, new in zip(old_rows, new_rows, strict=True):
                if old["source_id"].split("/session/")[1] != \
                        new["source_id"].split("/session/")[1]:
                    raise ValueError("Branch source alignment differs")
                mapping[old["receipt"]["evidence_id"]] = new["receipt"]["evidence_id"]
                mapping[old["source_id"]] = new["source_id"]
            base.write_json(observation / "branch-evidence-map.json", mapping)
            for artifact in artifacts:
                path = workspace / artifact["path"]
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                replaced = remap(content, mapping)
                if replaced != content:
                    path.write_text(replaced, encoding="utf-8")
                artifact["branch_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            if arm == "V":
                seeded = call("milai_working_state_update", {"operation_id": "initialize-" + task,
                    "expected_version": 0, "payload": remap(prior_after["payload"], mapping)})
                base.write_json(observation / "initialization-receipt.json", seeded)
                before = call("milai_working_state_get", {"scope": "TASK"})
                if before["status"] != "ACTIVE" or before["version"] != 1:
                    raise RuntimeError("V State initialization failed")
        base.write_json(observation / "before.json", before)
        base.write_json(observation / "task-artifacts.json", artifacts)
        base.write_json(observation / "source-access.json", {
            "history_sha256": digest, "labels_mounted": False, "future_questions_mounted": False,
            "same_generator_files_for_U_V": True, "task_files": artifacts})
        base.write_json(observation / "preparation-timing.json", {
            "pre_host_setup_seconds": time.perf_counter() - started,
            "source_capture_seconds": prepared["capture_seconds"],
            "projection_tail_seconds": prepared["projection_tail_seconds"]})
        prompt = cluster["current_task"] if arm == "G" else next(
            f["question"] for f in cluster["followups"] if f["id"] == followup)
        prompt += ("\nHistory boundary: " + cluster["cut_point"] +
                   ". Conversation history is available in sources/history.json "
                   "and project memory.")
        result = run_host(root, observation, workspace, values, config, prompt, task, project,
                          before, call, timeout)
        print(json.dumps({"session": session, "returncode": result["returncode"],
                          "save_status": result["save_status"], "usage": result["usage"],
                          "elapsed_seconds": result["elapsed_seconds"]}), flush=True)
        return int(result["returncode"] != 0)
    except Exception as exc:
        parsed = [e for e in base.parse_events(observation / "events.jsonl")
                  if e.get("item", {}).get("type") != "reasoning"]
        (observation / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in parsed))
        process = observation / "process.json"
        base.write_json(observation / "result.json", {
            "returncode": 1, "stop_reason": "L4_EXECUTION_FAILURE",
            "elapsed_seconds": time.time() - base.read_json(process)["launched_at"]
            if process.exists() else 0, "usage": None, "save_status": "OUTCOME_UNKNOWN",
            "failure": {"type": type(exc).__name__, "message": str(exc)}})
        raise
    finally:
        group.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True, choices=("27016adc", "852ce960"))
    parser.add_argument("--arm", required=True, choices=("G", "U", "V"))
    parser.add_argument("--followup")
    args = parser.parse_args()
    raise SystemExit(run(args.case_id, args.followup, args.arm))
