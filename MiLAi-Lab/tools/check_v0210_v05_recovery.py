"""Zero-model, real public MCP and Git-notes mechanical recovery comparison."""

# ruff: noqa: S603 -- fixed interpreter and host-authored code, no shell

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from check_v0210_control import LAB, write
from v02_local_provider import append_event
from v0210_v05_file import GitNotes
from v0210_v05_product import observer


def check(root: Path) -> dict:
    config = json.loads((LAB / "configs/v0210-v05-resume.json").read_text())
    write(root / "resume-config.json", config)
    binding = {"task": config["task_binding"], "project": config["project"],
               "principal": config["principal"]}
    payload = {"return_text": config["return_text"]}
    output = {"model_generations": 0, "seed_origin": config["origin"], "git": {}, "state": {}}
    write(root / "binding.json", binding)

    def recorded(call, tool, arguments):
        start = time.monotonic()
        result = call(tool, arguments)
        append_event(root / "mechanical-calls.jsonl", {"tool": tool, "arguments": arguments,
                     "result": result, "seconds": time.monotonic() - start})
        return result

    note = GitNotes(root / "git-notes-verified" / config["task_binding"])
    start = time.monotonic()
    first = note.update("seed", 0, payload)
    assert first["version"] == 1
    # Fresh interpreter, no old Python object or cache survives this restoration.
    code = ("import json,sys; from pathlib import Path; from v0210_v05_file import GitNotes; "
            "print(json.dumps(GitNotes(Path(sys.argv[1])).get()))")
    cold = json.loads(subprocess.run([sys.executable, "-c", code, str(note.root)],
                                    cwd=LAB / "tools", check=True, capture_output=True,
                                    text=True).stdout)
    assert cold["payload"] == payload and cold["version"] == 1
    note.update("lost-ack", 1, payload)  # controlled receipt loss AFTER commit
    replay = note.update("lost-ack", 1, payload)
    assert replay["version"] == 2 and replay["replayed"]
    with ThreadPoolExecutor(2) as pool:
        conflicts = list(pool.map(lambda op: note.update(op, 2, payload), ["race-a", "race-b"]))
    assert sorted(v["status"] for v in conflicts) == ["ACTIVE", "STALE_VERSION"]
    output["git"] = {"cold_roundtrip": "PASS", "version": note.get()["version"],
                     "same_operation_reconciliation": replay, "concurrent_results": conflicts,
                     "elapsed_seconds": time.monotonic() - start,
                     "task_binding": "HOST_SELECTED_DIRECTORY",
                     "isolation": "POSIX_0700_SAME_UID_NOT_A_PRINCIPAL_BOUNDARY",
                     "evidence_revocation": "NOT_SUPPORTED; application eligibility check required",
                     "unknown_fault": "CONTROLLED_HOST_RECEIPT_LOSS_AFTER_COMMIT_NOT_NETWORK_FAULT"}
    with observer(root, root / "mechanical-mcp-1", **binding) as call:
        catalog = recorded(call, None, {})
        write(root / "catalog.json", catalog)
        assert len(catalog["tools"]["tools"]) == 8
        absent = recorded(call, "milai_working_state_get", {"scope": "TASK"})
        if absent["status"] == "ABSENT":
            first = recorded(call, "milai_working_state_update", {
                "scope": "TASK", "operation_id": "seed", "expected_version": 0,
                "payload": payload})
        else:
            # Continue only the known seed committed before the rejected input diagnostic.
            first = absent
        assert first["version"] == 1 and first["payload"] == payload
    # The previous MCP process ended. The next one uses only stable trusted binding.
    with observer(root, root / "mechanical-mcp-2", **binding) as call:
        cold = recorded(call, "milai_working_state_get", {"scope": "TASK"})
        assert cold["payload"] == payload and cold["version"] == 1
        args = {"scope": "TASK", "state_id": cold["state_id"],
                "operation_id": "lost-ack", "expected_version": 1,
                "payload": payload}
        recorded(call, "milai_working_state_update", args)  # discard at controlled Host boundary
        replay = recorded(call, "milai_working_state_update", args)
        assert replay["version"] == 2 and replay["replayed"]
        with ThreadPoolExecutor(2) as pool:
            conflicts = list(pool.map(lambda op: recorded(call, "milai_working_state_update", {
                "scope": "TASK", "state_id": cold["state_id"], "operation_id": op,
                "expected_version": 2, "payload": payload}),
                ["race-a", "race-b"]))
        assert sum(v.get("version") == 3 for v in conflicts) == 1
        assert sum(v.get("mcp_error", False) for v in conflicts) == 1
        head = recorded(call, "milai_working_state_get", {"scope": "TASK"})
        assert head["version"] == 3 and head["payload"] == payload
        write(root / "confirmed-resume-head.json", head)
        output["state"] = {"cold_roundtrip": "PASS", "version": 3,
                           "same_operation_reconciliation": replay, "concurrent_results": conflicts,
                           "unknown_fault": "CONTROLLED_HOST_RECEIPT_LOSS_AFTER_COMMIT"}
    isolated = []
    for field in ("task", "principal", "project"):
        other = {**binding, field: binding[field] + "-other"}
        with observer(root, root / f"isolation-{field}", **other) as call:
            result = recorded(call, "milai_working_state_get", {"scope": "TASK"})
            assert result["status"] == "ABSENT"
            isolated.append({"changed": field, "status": result["status"]})
    output["state"]["isolation"] = isolated
    # A separate synthetic TASK exercises missing/unreadable dependency handling.
    other = {**binding, "task": binding["task"] + "-unreadable"}
    with observer(root, root / "unreadable", **other) as call:
        result = recorded(call, "milai_working_state_update", {
            "scope": "TASK", "operation_id": "unreadable", "expected_version": 0,
            "payload": {**payload, "evidence_refs": [str(uuid4())]}})
        output["state"]["unreadable_dependency"] = result
        output["state"]["revoked_dependency"] = "NOT_EXERCISED; not inferred from absent dependency"
    output["cost_limits"] = {"human_seconds": "NOT_OBSERVED", "gpu_cost": "NOT_APPLICABLE_NO_MODEL",
                              "infrastructure_resource_cost": "NOT_METERED",
                              "latencies": "mechanical-calls.jsonl; single observations"}
    output["status"] = "E3A_CORE_MECHANICAL_PASS_WITH_DECLARED_LIMITS"
    write(root / "mechanical-result.json", output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(check(args.root.resolve())["status"])
