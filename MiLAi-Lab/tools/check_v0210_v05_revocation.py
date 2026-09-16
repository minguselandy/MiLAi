"""Zero-model dependency revocation on a separate owned synthetic TASK."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from check_v0210_control import write
from v02_local_provider import append_event
from v0210_v05_product import observer


def run(root: Path) -> dict:
    binding = json.loads((root / "binding.json").read_text())
    binding["task"] += "-revocation"
    with observer(root, root / "revocation", **binding) as public:
        def call(tool, args):
            value = public(tool, args)
            append_event(root / "revocation-calls.jsonl", {
                "tool": tool, "arguments": args, "result": value})
            return value

        captured = call("milai_memory_save", {
            "operation_id": "v05-revocation-source", "content": "Synthetic dependency to revoke.",
            "options": {"action": "CAPTURE_EVIDENCE", "source_type": "DOCUMENT",
                        "source_ref": "synthetic:v0210-v05/revocation",
                        "subject_id": "v0210-v05-synthetic",
                        "observed_at": datetime.now(UTC).isoformat(), "confirmation": "CAPTURE"}})
        write(root / "revocation-capture.json", captured)
        evidence_id = captured["evidence_id"]
        saved = call("milai_working_state_update", {"scope": "TASK", "expected_version": 0,
                     "operation_id": "v05-dependent-state",
                     "payload": {"return_text": "Dependent synthetic note",
                                 "evidence_refs": [evidence_id]}})
        assert saved["status"] == "ACTIVE" and saved["payload"]
        revoked = call("milai_memory_delete", {"operation_id": "v05-revoke",
                       "target": {"kind": "EVIDENCE", "id": evidence_id,
                                  "reason_code": "USER_REQUEST", "confirmation": "REVOKE"}})
        after = call("milai_working_state_get", {"scope": "TASK"})
        assert after["payload"] == {} and after["payload_withheld"] and after["warnings"]
        result = {"status": "PASS", "model_generations": 0, "revocation": revoked,
                  "after": after, "scope": "OWNED_SYNTHETIC_ONLY",
                  "git_control": "NOT_SUPPORTED: application eligibility check required"}
        write(root / "revocation-result.json", result)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.root.resolve())["status"])
