"""Replay actual local-world writes/reset/paired events/repair, explicitly without Agent claims."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from v0218_checker import evaluate
from v0218_world import World, digest


def schedule(day, hour, online=False):
    return {
        "start": f"2026-03-{day}T{hour}:00:00+08:00",
        "end": f"2026-03-{day}T{hour}:30:00+08:00",
        "interviewer": "A",
        "room": "online" if online else "301",
        "mode": "online" if online else "in_person",
        "confirmed": True,
    }


def execute(root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for item in json.loads((root / "manifest.json").read_text())["roots"]:
        key = item["root"]
        spec = json.loads((root / key / "evaluation-contract.json").read_text())
        assert (
            hashlib.sha256((root / key / "evaluation-contract.json").read_bytes()).hexdigest()
            == item["contract_sha256"]
        )
        world = World(root / key / "initial.sqlite", key).clone(
            output / f"{key}-A.sqlite", key + "-A"
        )
        if item["family"] == "scheduling":
            initial = {"C03": schedule("25", "09"), "C04": schedule("26", "13")}
            repaired = {"C03": schedule("25", "09", True), "C04": schedule("26", "10")}
        else:
            initial = {
                "FLT-DLY-0315": {
                    "decision": "approved",
                    "amount_cny": 400,
                    "delay_minutes": 167,
                    "reason": "weather",
                    "basis_revision": "official-v1",
                }
            }
            repaired = {
                "FLT-DLY-0315": {
                    "decision": "rejected",
                    "amount_cny": 0,
                    "delay_minutes": 167,
                    "reason": "operational_rotation",
                    "basis_revision": "official-v2",
                }
            }

        def apply(target, records, tag):
            for object_id, record in records.items():
                target.act(
                    operation_id=f"{tag}-{object_id}",
                    expected_version=target.snapshot()["version"],
                    action="put_record",
                    object_id=object_id,
                    data=record,
                )

        apply(world, initial, "A")
        assert evaluate(world.snapshot())["status"] == "PASS"
        for variant in ("stable", "superseded", "unresolved"):
            branch = world.clone(output / f"{key}-{variant}.sqlite", key + "-" + variant)
            prefix_hash = digest({k: v for k, v in branch.snapshot().items() if k != "scope"})
            branch.publish(
                event_id="predefined-B", current=spec["variants"][variant], task=spec["task_B"]
            )
            before = evaluate(branch.snapshot())
            expected_before = "PASS" if variant == "stable" else "FAIL"
            assert before["status"] == expected_before
            if variant == "superseded":
                apply(branch, repaired, "repair")
            elif variant == "unresolved":
                unresolved = [
                    obj
                    for obj, value in spec["variants"][variant][
                        "candidates" if item["family"] == "scheduling" else "claims"
                    ].items()
                    if value["status"] == "unresolved"
                ]
                valid = {obj: value for obj, value in repaired.items() if obj not in unresolved}
                apply(branch, valid, "still-resolved")
                for obj in unresolved:
                    apply(
                        branch,
                        {
                            obj: {"confirmed": False}
                            if item["family"] == "scheduling"
                            else {"decision": "pending"}
                        },
                        "withdraw-unsupported",
                    )
                    branch.act(
                        operation_id="clarify-" + obj,
                        expected_version=branch.snapshot()["version"],
                        action="request_clarification",
                        object_id=obj,
                        data={
                            "question": "Please resolve the pending official facts for this object."
                        },
                    )
            after = evaluate(branch.snapshot())
            assert after["status"] == "PASS"
            row = {
                "root": key,
                "variant": variant,
                "common_A_prefix_sha256": prefix_hash,
                "before": before,
                "after": after,
                "snapshot_sha256": digest(branch.snapshot()),
                "ledger_entries": len(branch.ledger()),
                "execution_kind": "SCRIPTED_LOCAL_WORLD_MUTATION",
                "agent_recovery": "NOT_MEASURED",
                "model_requests": 0,
            }
            rows.append(row)
            (output / f"{key}-{variant}-ledger.json").write_text(
                json.dumps(branch.ledger(), indent=2)
            )
    result = {
        "status": "T1_TWO_VERTICALS_REPLAYED_NOT_G_TESTBED",
        "rows": rows,
        "roots": 2,
        "variants": 6,
        "model_requests": 0,
        "persistent_chains": 0,
        "construction_target": 12,
        "scope_complete": False,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.root, args.output)))
