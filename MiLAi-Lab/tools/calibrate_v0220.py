"""Zero-model typed-contract smoke over complete, already exposed reference records.

These evaluator fixtures test expression/effects, not natural task competence.
They must never be mounted in natural Host inputs or counted as Intent Oracle trials.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from audit_v0220_contract import LAB, read, save, sha
from v0218_world import World, digest
from v0220_action_adapter import ActionAdapter
from v0220_action_contract import ActionContract


def calibrate(destination: Path) -> dict:
    if destination.exists():
        raise ValueError("FRESH_CALIBRATION_REQUIRED")
    plan = read(LAB / "configs/v0220-execution-plan-v1.json")
    old = Path(plan["old_batch"])
    files = [
        "tools/calibrate_v0220.py",
        "tools/v0220_action_contract.py",
        "tools/v0220_action_adapter.py",
        "tools/v0220_dispatch_journal.py",
        "tools/v0218_world.py",
        "tools/audit_v0220_contract.py",
        "tests/unit/test_v0220_action_adapter.py",
        "configs/v0220-execution-plan-v1.json",
    ]
    destination.mkdir(parents=True)
    hashes = {name: sha(LAB / name) for name in files}
    save(
        destination / "manifest.json",
        {
            "profile": "ZERO_MODEL_EXPOSED_REFERENCE_CALIBRATION",
            "implementation": hashes,
            "roots": plan["ordered_roots"],
            "model_requests": 0,
            "old_manifest_sha256": sha(old / "manifest.json"),
            "raw_token_cap": None,
        },
    )
    for name in files:
        path = destination / "executed-source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write((LAB / name).read_bytes())
    rows = []
    for key in plan["ordered_roots"]:
        case = old / "cases" / key
        public, reference = (
            read(case / "public-initial.json"),
            read(case / "independent-reference.json"),
        )
        records = reference.get("records", reference.get("initial_records"))
        assert set(records) == set(public["objects"])
        contract = ActionContract.from_public(public)
        scope = "v0220-calibration-" + key
        adapter = ActionAdapter(
            World.create(destination / (key + ".sqlite"), scope, public), contract
        )
        save(destination / (key + "-contract.json"), contract.documents())
        receipts = []
        for index, target in enumerate(public["objects"]):
            # Explicit evaluator fixture conversion, never a runtime payload repair.
            data = {k: copy.deepcopy(v) for k, v in records[target].items() if k != "object_id"}
            action = {
                "action": "put_record",
                "arguments": {"object_id": target, "expected_version": index, "data": data},
            }
            decoded = contract.decode(json.dumps(action, ensure_ascii=False))
            before = adapter.world.snapshot()
            receipt = adapter.execute(decoded, operation_id=f"create-{index}")
            assert receipt["committed"] is True, (key, target, receipt)
            assert receipt["version"] == index + 1
            assert adapter.read("records")["content"][target] == records[target]
            assert adapter.execute(decoded, operation_id=f"create-{index}") == receipt
            # Stored output is deliberately invalid as write data: no automatic stripping.
            illegal = copy.deepcopy(action)
            illegal["arguments"]["expected_version"] = index + 1
            illegal["arguments"]["data"] = copy.deepcopy(records[target])
            settled = adapter.world.snapshot()
            rejected = adapter.execute(illegal, operation_id=f"illegal-{index}")
            assert rejected["code"] == "READ_ONLY_FIELD" and rejected["committed"] is False
            assert adapter.world.snapshot() == settled
            receipts.append(
                {
                    "action": action,
                    "before_sha256": digest(before),
                    "receipt": receipt,
                    "public_read": adapter.read("records"),
                    "storage_payload_rejection": rejected,
                }
            )
        assert adapter.world.snapshot()["records"] == records
        assert len(adapter.world.ledger()) == len(records)
        assert adapter.journal.unresolved() == []
        save(destination / (key + "-receipts.json"), receipts)
        save(destination / (key + "-final-world.json"), adapter.world.snapshot())
        rows.append(
            {
                "root": key,
                "complete_record_count": len(records),
                "first_attempt_accepted": len(records),
                "exact_replays": len(records),
                "stored_payload_rejected_no_effect": len(records),
                "ledger_effects": len(adapter.world.ledger()),
                "contract_sha256": contract.fingerprint,
                "public_source_sha256": sha(case / "public-initial.json"),
                "reference_source_sha256": sha(case / "independent-reference.json"),
                "final_world_sha256": sha(destination / (key + "-final-world.json")),
            }
        )
    assert all(sha(LAB / name) == value for name, value in hashes.items())
    result = {
        "status": "V1_COMPLETE_RECORD_SMOKE_PASS_NOT_FULL_GATE",
        "rows": rows,
        "model_requests": 0,
        "judge_requests": 0,
        "goal_complete": False,
        "remaining": [
            "Machine-readable receipt schema and comprehensive four-root fault matrix",
            "Frozen real Provider compatibility and V2 Intent Oracle matrix",
            "Conditional V3/V4/V5 and final gate-by-gate report",
        ],
        "scope": "Scripted public-structure/effect check only. Does not adjudicate old disputed "
        "semantic fields, change prior scores, or demonstrate model task execution.",
    }
    save(destination / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = calibrate(args.root)
    print(
        json.dumps(
            {
                "status": result["status"],
                "roots": len(result["rows"]),
                "records": sum(r["complete_record_count"] for r in result["rows"]),
                "result_sha256": sha(args.root / "result.json"),
            }
        )
    )
