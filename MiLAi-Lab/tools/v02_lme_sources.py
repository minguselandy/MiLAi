"""Source-only LME mapping and bounded capture through the public hook CLI."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import run_product09_codex_lifecycle as public
from run_product09_codex_lme import _observed_at


def history_events(source: dict[str, Any], binding: str, *,
                   preserve_session_time: bool = False) -> list[dict[str, Any]]:
    if set(source) != {"schema_version", "case_id", "question", "question_date", "sessions"}:
        raise ValueError("Source package has unapproved fields")
    if source["schema_version"] != "v02-lme-source-only-v1":
        raise ValueError("Unsupported source package")
    events = []
    for session in source["sessions"]:
        if set(session) != {"session_ordinal", "session_id", "observed_at", "turns"}:
            raise ValueError("Session has unapproved fields")
        instance = session["session_ordinal"]
        if session["session_id"] != f"session-{instance}":
            raise ValueError("Source session identity must be neutral, without corpus annotations")
        runtime_session = f"lme-{binding}-{instance}"
        turns = session["turns"]
        for turn in turns:
            if set(turn) != {"turn_ordinal", "role", "content"}:
                raise ValueError("Turn has unapproved fields")
        material = [t for t in turns if t["content"].strip()]
        for index, turn in enumerate(material):
            ordinal = turn["turn_ordinal"]
            source_id = f"lme://{binding}/session/{instance}/turn/{ordinal}"
            events.append({
                "schema_version": "host-agent-event-v1",
                "event_id": "lme-" + hashlib.sha256(source_id.encode()).hexdigest()[:40],
                "event_type": {"user": "USER_MESSAGE", "assistant": "ASSISTANT_MESSAGE",
                               "system": "SESSION_MARKER", "tool": "TOOL_RESULT"}[turn["role"]],
                "session_id": runtime_session, "source_id": source_id,
                "subject_id": "v02-lme-opened-user", "content": turn["content"],
                "observed_at": _observed_at(session["observed_at"],
                                            0 if preserve_session_time else ordinal),
                "turn_id": f"{runtime_session}:turn:{ordinal}", "turn_ordinal": ordinal,
                "round_id": f"{runtime_session}:round:{ordinal // 2}",
                "round_ordinal": ordinal // 2,
                **({"previous_turn_id": f"{runtime_session}:turn:"
                    f"{material[index - 1]['turn_ordinal']}"} if index else {}),
                **({"next_turn_id": f"{runtime_session}:turn:"
                    f"{material[index + 1]['turn_ordinal']}"}
                   if index + 1 < len(material) else {}),
            })
    return events


def capture_legacy(environment: dict[str, str], project: str,
                   events: list[dict[str, Any]], directory: Path,
                   timeout_seconds: float) -> dict[str, Any]:
    """Keep old one-process-per-Event semantics; split timing and bound every wait."""
    started = time.perf_counter()
    deadline = started + timeout_seconds
    values = dict(environment)
    values.update({"MILAI_AGENT_TOKEN": environment["MILAI_AGENT_SUBMITTER_TOKEN"],
                   "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [project]}),
                   "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
                   "MILAI_AGENT_MAX_RETRIES": "0", "MILAI_HOST_EVENT_CAPTURE": "ON",
                   "MILAI_HOST_EVENT_DATA_CLASSIFICATION": "DEIDENTIFIED"})
    outbox_ids = []
    with (directory / "source-receipts.jsonl").open("w") as output:
        for event in events:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError("Case capture/readiness budget exhausted")
            result = public._command(
                [str(public.HOOK_EXE), "AgentEvent"], cwd=public.HOOKS,
                env=public._clean_environment(values),
                input_text=json.dumps(event, ensure_ascii=False), timeout=min(45, remaining),
            )
            receipt = json.loads(result.stdout)
            if receipt.get("status") != "RAW_EVIDENCE_CAPTURED":
                raise RuntimeError("Capture did not return a valid public receipt")
            output.write(json.dumps({"source_id": event["source_id"], **receipt}) + "\n")
            output.flush()
            outbox_ids.append(receipt["receipt"]["outbox_id"])
    capture_done = time.perf_counter()
    readiness = []
    for start in range(0, len(outbox_ids), 512):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TimeoutError("Case capture/readiness budget exhausted before readiness")
        status, response = public._http_json(
            "POST", environment["MILAI_BASE_URL"] + "/v1/system/projection-readiness",
            token=environment["MILAI_AGENT_READER_TOKEN"],
            payload={"target_outbox_ids": outbox_ids[start:start + 512],
                     "required_projections": ["evidence"],
                     "expected_versions": {"evidence": "evidence-search-v1"},
                     "timeout_ms": max(1, int(min(30, remaining) * 1000)),
                     "poll_interval_ms": 50}, timeout=min(35, remaining),
        )
        if status != 200 or response.get("status") != "READY":
            raise RuntimeError("Projection did not reach READY")
        readiness.append(response)
    return {"capture_mode": "LEGACY_CLI_PER_EVENT", "capture_workers": 1,
            "events": len(events), "capture_seconds": capture_done - started,
            "projection_tail_seconds": time.perf_counter() - capture_done,
            "elapsed_seconds": time.perf_counter() - started, "readiness": readiness,
            "status": "READY"}
