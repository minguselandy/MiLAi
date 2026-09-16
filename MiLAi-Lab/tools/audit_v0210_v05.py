"""Read-only v0.5 ledger, cold-input and installed delivery audit; no model transport."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from check_v0210_control import LAB, write
from milai_lab.methods.state_control import digest
from v02_local_provider import accounting, read_events


def audit(root: Path) -> dict:
    batches = {}
    for name, count, cap in [("b3-20260909", 8, 64000), ("b4-r2-20260909", 4, 32000)]:
        directory = root / name
        events = read_events(directory / "provider-ledger.jsonl")
        state = accounting(events)
        assert state["requests"] == count and state["raw_tokens"] <= cap
        assert not state["pending"] and not state["violations"]
        for event in events:
            if event["event"] == "RESERVED":
                request = directory / f"{event['request_id']}-request.json"
                assert digest(request.read_bytes()) == event["payload_sha256"]
                body = json.loads(request.read_text())
                assert body["max_tokens"] == event["output_cap"] == 1024
                assert event["prompt_tokens"] <= 8192
            else:
                assert event["event"] == "SETTLED"
                assert event["usage"]["total_tokens"] == (
                    event["input_tokens"] + event["output_tokens"])
        pins = json.loads((directory / "implementation-pin.json").read_text())
        for relative, expected in pins.items():
            assert digest((LAB / relative).read_bytes()) == expected, relative
        result = json.loads((directory / "result.json").read_text())
        assert state == result["accounting"]
        assert result["seconds"] < (600 if count == 8 else 300)
        batches[name] = {"accounting": state, "seconds": result["seconds"],
                         "implementation_pin": "PASS"}
    cold = root / "b4-r2-20260909"
    for scenario in ("reopen", "retain"):
        a = json.loads((cold / f"{scenario}-N/messages.json").read_text())
        b = json.loads((cold / f"{scenario}-S/messages.json").read_text())
        assert a[:2] == b[:2] and a[2] != b[2]
    failed = accounting(read_events(root / "b4-20260909/provider-ledger.jsonl"))
    assert failed["requests"] == 0 and not failed["pending"]
    product = root / "e3a-20260909"
    bundle = product / "milai-mcp-delivery-0.1.15"
    installed = {}
    for venv, wheel_dir in [("mcp-venv", bundle / "packages"),
                            ("runtime-venv", bundle / "runtime/packages")]:
        for wheel in wheel_dir.glob("*.whl"):
            files = 0
            with zipfile.ZipFile(wheel) as archive:
                for name in archive.namelist():
                    if name.endswith(".py"):
                        path = product / venv / "lib/python3.11/site-packages" / name
                        assert path.read_bytes() == archive.read(name), name
                        files += 1
            installed[wheel.name] = {"sha256": digest(wheel.read_bytes()),
                                     "installed_python_files_matching": files}
    result = {"status": "PASS", "batches": batches,
              "actual_generations": sum(b["accounting"]["requests"] for b in batches.values()),
              "actual_raw_tokens": sum(b["accounting"]["raw_tokens"] for b in batches.values()),
              "failed_B4_assembly": {"actual": failed,
                  "reason": "LIMIT_KEY_MISMATCH_BEFORE_REQUEST",
                  "secondary_fix": "Cold provider performs own zero-generation model discovery"},
              "installed_artifacts": installed, "cold_common_inputs_equal": True,
              "e3a_generations": 0, "paid_generations": 0,
              "v04": "HISTORICAL_NOT_READ_RESCORED_OR_ADDED_TO_V05_BUDGET"}
    write(root / "execution-audit.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.root.resolve()), ensure_ascii=False))
