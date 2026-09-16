"""Optional serial persistent capture; same public Evidence and readiness contracts."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import run_product09_codex_lifecycle as public


def capture_persistent(environment: dict[str, str], project: str,
                       events: list[dict[str, Any]], directory: Path,
                       timeout_seconds: float) -> dict[str, Any]:
    started = time.perf_counter()
    values = dict(environment)
    values.update({"MILAI_AGENT_TOKEN": environment["MILAI_AGENT_SUBMITTER_TOKEN"],
                   "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [project]}),
                   "MILAI_AGENT_MAX_RETRIES": "0", "MILAI_HOST_EVENT_CAPTURE": "ON",
                   "MILAI_HOST_EVENT_DATA_CLASSIFICATION": "DEIDENTIFIED"})
    worker = Path(__file__).with_name("v02_lme_capture_worker.py")
    with (directory / "source-receipts.jsonl").open("w") as receipts, (
        directory / "capture.stderr"
    ).open("w") as errors:
        result = subprocess.run(  # noqa: S603 -- pinned public hooks interpreter
            [str(public.HOOKS / ".venv/bin/python"), str(worker)],
            input="".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
            stdout=receipts, stderr=errors, text=True, check=False,
            env=public._clean_environment(values), timeout=timeout_seconds,
        )
    captured = time.perf_counter()
    rows = [json.loads(line) for line in
            (directory / "source-receipts.jsonl").read_text().splitlines()]
    if result.returncode or len(rows) != len(events) or any(
        row.get("status") != "RAW_EVIDENCE_CAPTURED" for row in rows
    ):
        raise RuntimeError("Persistent capture failed; inspect preserved per-event receipts")
    outbox_ids = [row["receipt"]["outbox_id"] for row in rows]
    readiness = []
    for start in range(0, len(outbox_ids), 512):
        remaining = timeout_seconds - (time.perf_counter() - started)
        if remaining <= 0:
            raise TimeoutError("Case capture/readiness budget exhausted")
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
    return {"capture_mode": "PUBLIC_HOOK_PERSISTENT_CLIENT", "capture_workers": 1,
            "events": len(events), "capture_seconds": captured - started,
            "projection_tail_seconds": time.perf_counter() - captured,
            "elapsed_seconds": time.perf_counter() - started,
            "readiness": readiness, "status": "READY"}
