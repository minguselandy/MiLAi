"""Thin full-Host adapter for the staged, opened-development LME study."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

import run_v02_memory_flow as base
from v02_lme_capture import capture_persistent
from v02_lme_host import run_host
from v02_lme_sources import capture_legacy, history_events

CONFIG = base.LAB / "configs/v02-lme-incremental.json"
SELECTION = base.LAB / "studies/active/MILA_V02_LME_INCREMENTAL_SELECTION.json"
DATA = base.LAB / "artifacts/v02-lme-incremental/data-20260905b"
STUDY = base.LAB / "artifacts/v02-lme-incremental"


def reserve(root: Path, session: str, batch: str, kind: str,
            config: dict[str, Any]) -> tuple[Path, float]:
    """Count all allocated failures and bound the sum of batch online time."""
    previous = [p for p in root.parent.glob("*/sessions/*/allocation.json")]
    rows = [(p, base.read_json(p)) for p in previous]
    if any(not (p.parent / "result.json").exists() for p, _ in rows):
        raise RuntimeError("Unresolved allocated session; inspect it before starting another")
    if len(rows) >= config["model_phase_limits"]["total"]:
        raise RuntimeError("Goal model-allocation budget exhausted")
    phase = [r for _, r in rows if r["phase"] == "L0_L2"]
    if len(phase) >= config["model_phase_limits"]["L0_L2"]:
        raise RuntimeError("L0-L2 allocation budget exhausted")
    if kind == "SMOKE" and sum(r["kind"] == kind for r in phase) >= 2:
        raise RuntimeError("Smoke allocation limit reached")
    if kind == "DIAGNOSTIC" and sum(r["kind"] == kind for r in phase) >= 2:
        raise RuntimeError("Diagnostic allocation limit reached")
    same_batch = [p for p, r in rows if r["batch_id"] == batch]
    if len(same_batch) >= config["batch_session_limit"]:
        raise RuntimeError("Batch allocation limit reached")
    elapsed = sum(base.read_json(p.parent / "result.json")["elapsed_seconds"] for p in same_batch)
    remaining = config["batch_wall_seconds"] - elapsed
    if remaining <= 0:
        raise RuntimeError("Batch online budget exhausted")
    observation = root / "sessions" / session
    observation.mkdir(mode=0o700, parents=True, exist_ok=False)
    return observation, min(config["session_timeout_seconds"], remaining)


def code_identity() -> dict[str, str]:
    names = ["run_v02_lme_incremental.py", "v02_lme_host.py", "v02_lme_sources.py",
             "run_v02_memory_flow.py", "v02_codex_container.py", "v02_task_artifacts.py",
             "v02_lme_capture.py", "v02_lme_capture_worker.py"]
    return {name: hashlib.sha256((base.LAB / "tools" / name).read_bytes()).hexdigest()
            for name in names}


def run_case(root: Path, case_id: str, session: str, batch: str, kind: str) -> int:
    verification = base.pin(CONFIG)
    base.assert_services(root)
    config = base.read_json(CONFIG)
    if config != base.read_json(root / "config.json"):
        raise RuntimeError("Record a new config identity before changing an active batch")
    selection = base.read_json(SELECTION)
    if case_id not in selection["D"]:
        raise ValueError("This first increment only permits the selected D cases")
    if kind == "SMOKE" and case_id not in selection["smoke"]:
        raise ValueError("Case is not a prespecified smoke")
    source_path = DATA / "sources" / f"{case_id}.json"
    raw_source = source_path.read_bytes()
    digest = hashlib.sha256(raw_source).hexdigest()
    if digest != base.read_json(DATA / "manifest.json")["cases"][case_id]["source_sha256"]:
        raise ValueError("Source-only bundle identity mismatch")
    source = json.loads(raw_source)
    task = secrets.token_hex(12)
    project = "v02l-" + task
    events = history_events(source, task)
    batch_identity = {"config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
                      "code_sha256": code_identity(), "product_pin": verification}
    batch_path = root / "batches" / batch / "identity.json"
    if batch_path.exists():
        if base.read_json(batch_path) != batch_identity:
            raise RuntimeError("Batch identity changed; use a new registered batch")
    else:
        batch_path.parent.mkdir(parents=True)
        base.write_json(batch_path, batch_identity)
    observation, timeout = reserve(root, session, batch, kind, config)
    allocation = {"started_at": time.time(), "phase": "L0_L2", "kind": kind,
                  "arm": "A0", "case_id": case_id, "batch_id": batch,
                  "task_ref": task, "project": project, "source_sha256": digest,
                  "fixture_sha256": digest, "product_pin": verification,
                  "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
                  "code_sha256": code_identity(), "session_timeout_seconds": timeout,
                  "source_sessions": len(source["sessions"]), "source_events": len(events),
                  "model_started": "See process.json; allocation always consumes slot"}
    base.write_json(observation / "allocation.json", allocation)
    (observation / "events.jsonl").touch()
    values = base._load_environment(root / "runtime.env")
    if values["MILAI_DATA_MODE"] != config["data_mode"]:
        raise RuntimeError("Instance data mode does not match config")
    values.update({"MILAI_CODEX_PRINCIPAL_ID": "v02-lme-host", "MILAI_CODEX_TASK_REF": task,
                   "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [project]})})
    token = secrets.token_urlsafe(32)
    port = base._free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    values.update({"MILAI_CODEX_TOKEN": token,
                   "MILAI_MCP_HTTP_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}"})
    group = base.ProcessGroup(observation)
    setup_started = time.perf_counter()
    try:
        server = group.start("observer-mcp", [str(base.MCP / ".venv/bin/milai-codex-full-mcp"),
                                              "--port", str(port)], cwd=base.MCP,
                             env=base._clean_environment(values))
        base._wait_http(f"http://127.0.0.1:{port}/readyz", server)

        def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return base.structured(asyncio.run(base.mcp_call(url, token, tool, arguments)))

        base.write_json(observation / "tool-catalog.json", asyncio.run(
            base.mcp_call(url, token, None, {})
        ))
        before = call("milai_working_state_get", {"scope": "TASK"})
        base.write_json(observation / "before.json", before)
        if before["status"] != "ABSENT" or before["version"] != 0:
            raise RuntimeError("Native task requires an absent isolated State")
        observer_ready = time.perf_counter()
        modes = {"LEGACY_CLI_PER_EVENT": capture_legacy,
                 "PUBLIC_HOOK_PERSISTENT_CLIENT": capture_persistent}
        capture = modes[config.get("capture_mode", "LEGACY_CLI_PER_EVENT")]
        prepared = capture(values, project, events, observation,
                           config["capture_readiness_timeout_seconds"])
        base.write_json(observation / "source-preparation.json", prepared)
        workspace = root / "host-sessions" / secrets.token_hex(12) / "workspace"
        (workspace / "sources").mkdir(parents=True)
        (workspace / "sources/history.json").write_bytes(raw_source)
        base.write_json(observation / "source-access.json", {
            "files": [{"path": "sources/history.json", "sha256": digest}],
            "corpus_mounted": False, "labels_mounted": False,
            "isolation": "same readonly container source mount as full v0.2 Host",
            "source_session_count": len(source["sessions"]),
        })
        base.write_json(observation / "preparation-timing.json", {
            "observer_catalog_state_seconds": observer_ready - setup_started,
            "pre_host_setup_seconds": time.perf_counter() - setup_started,
            "source_capture_seconds": prepared["capture_seconds"],
            "projection_tail_seconds": prepared["projection_tail_seconds"],
        })
        prompt = (source["question"] + "\n\nQuestion date: " + source["question_date"] +
                  ". Conversation history is available in sources/history.json and project memory.")
        result = run_host(root, observation, workspace, values, config, prompt, task, project,
                          before, call, timeout)
        print(json.dumps({"session": session, "returncode": result["returncode"],
                          "stop_reason": result["stop_reason"], "usage": result["usage"],
                          "elapsed_seconds": result["elapsed_seconds"],
                          "save_status": result["save_status"]}), flush=True)
        return int(result["returncode"] != 0)
    except Exception as exc:
        observed = base.parse_events(observation / "events.jsonl")
        observed = [e for e in observed if e.get("item", {}).get("type") != "reasoning"]
        (observation / "events.jsonl").write_text("".join(
            json.dumps(e, ensure_ascii=False) + "\n" for e in observed
        ))
        process_path = observation / "process.json"
        launched = base.read_json(process_path)["launched_at"] if process_path.exists() else None
        base.write_json(observation / "result.json", {
            "returncode": 1, "stop_reason": "HOST_OR_OBSERVER_FAILURE" if launched else
            "PRE_HOST_FAILURE", "elapsed_seconds": time.time() - launched if launched else 0,
            "pre_host_or_total_failure_seconds": time.perf_counter() - setup_started,
            "usage": [e["usage"] for e in observed if e.get("type") == "turn.completed"] or None,
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "save_status": "OUTCOME_UNKNOWN" if launched else "NOT_ATTEMPTED",
        })
        print(json.dumps({"session": session, "status": "FAILED", "type": type(exc).__name__}),
              flush=True)
        return 1
    finally:
        group.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "status"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--session-id")
    parser.add_argument("--batch-id", default="l0-smoke")
    parser.add_argument("--kind", choices=("SMOKE", "DIAGNOSTIC", "PAIR"), default="SMOKE")
    args = parser.parse_args()
    for value in (args.run_id, args.case_id, args.session_id, args.batch_id):
        if value is not None and not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            raise ValueError("Unsafe identifier")
    root = STUDY / args.run_id
    if args.action == "prepare":
        config = base.read_json(CONFIG)
        base.prepare(root, config_path=CONFIG, runtime_overrides={
            "MILAI_DATA_MODE": config["data_mode"],
            "MILAI_RETRIEVAL_CONTINUATION_V0_1_ENABLED": "true",
            "MILAI_INTRA_SOURCE_ACQUISITION_V0_1_MODE": "SHADOW",
        })
    elif args.action == "status":
        base.assert_services(root)
        print(json.dumps({"status": "LIVE_PROCESSES", "pin": base.pin(CONFIG)}))
    else:
        if not args.case_id or not args.session_id:
            raise ValueError("run requires case-id and session-id")
        return run_case(root, args.case_id, args.session_id, args.batch_id, args.kind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
