"""Serial JSONL worker using the pinned public hook and one public SDK client.

Run with the hooks package's installed Python. This optional Lab capture path only
supports capture ON, journal OFF; reject other modes before the first write.
"""

from __future__ import annotations

import json
import os
import sys

from milai_client import MilaiClient, MilaiClientError
from milai_hooks.agent_event import capture_host_agent_event


def main() -> int:
    if os.environ.get("MILAI_HOST_EVENT_CAPTURE") != "ON":
        raise PermissionError("Host AgentEvent capture is not enabled")
    if os.environ.get("MILAI_HOST_EVENT_JOURNAL", "OFF") != "OFF":
        raise ValueError("Persistent Lab worker only supports journal OFF")
    scope = json.loads(os.environ["MILAI_AGENT_SCOPE_JSON"])
    if not isinstance(scope, dict):
        raise ValueError("Host scope must be an object")
    scope["readable"] = True
    classification = os.environ.get("MILAI_HOST_EVENT_DATA_CLASSIFICATION", "PERSONAL")
    if classification not in {"SYNTHETIC", "DEIDENTIFIED", "PERSONAL"}:
        raise ValueError("Invalid data classification")
    retries = int(os.environ.get("MILAI_AGENT_MAX_RETRIES", "0"))
    if retries != 0:
        raise ValueError("Measured serial worker requires zero retries")
    client = MilaiClient(max_retries=0)
    try:
        for line in sys.stdin:
            event = json.loads(line)
            try:
                receipt = capture_host_agent_event(
                    client, event, permission_snapshot=scope,
                    data_classification=classification,
                )
            except MilaiClientError as exc:
                print(json.dumps({"status": "REJECTED", "source_id": event.get("source_id"),
                                  "error": {"code": exc.code, "status_code": exc.status_code,
                                            "retryable": exc.retryable}}), flush=True)
                return 1
            print(json.dumps({"source_id": event["source_id"], **receipt}), flush=True)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
