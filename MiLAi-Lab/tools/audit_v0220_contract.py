"""V0 zero-generation audit of the four already exposed V0219 action contracts."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from v0218_host import SCHEMA, TOOLS
from v0218_world import World, WorldError

LAB = Path(__file__).resolve().parents[1]


def read(path: Path):
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def audit(destination: Path) -> dict:
    if destination.exists():
        raise ValueError("FRESH_AUDIT_REQUIRED")
    plan_path = LAB / "configs/v0220-execution-plan-v1.json"
    plan = read(plan_path)
    old = Path(plan["old_batch"])
    manifest = read(old / "manifest.json")
    assert sha(old / "manifest.json") == (
        "e70a4a2030e8ffff7c0b51d4a62a3761ce6a4a1f28f6eca6082d1b5597ab0159"
    )
    assert [r["root"] for r in manifest["roots"]] == plan["ordered_roots"]
    destination.mkdir(parents=True)
    goal_path = LAB / "studies/active/MILA_V0220_动作执行有效性校准与记忆复验准入_GOAL_20260911.md"
    # Preserve exact input bytes, not a rewritten summary of the governing contract.
    with (destination / "goal-frozen.md").open("xb") as stream:
        stream.write(goal_path.read_bytes())
    rows, total, b_total = [], collections.Counter(), collections.Counter()
    for root in manifest["roots"]:
        key = root["root"]
        public_path = old / "cases" / key / "public-initial.json"
        public = read(public_path)
        schema = public["task"]["record_schemas"]
        assert set(schema) == set(public["objects"])
        decision = read(Path(manifest["screening"]) / f"{root['order']:03d}-decision.json")
        rejections = collections.Counter()
        for path in sorted((old / "episodes").glob(key + "-*/result.json")):
            result = read(path)
            for action in result["actions"]:
                receipt = action.get("tool_result") or {}
                if receipt.get("status") == "ACTION_REJECTED":
                    reason = receipt["reason"]
                    rejections[reason] += 1
                    total[reason] += 1
                    if path.parent.name != key + "-A":
                        b_total[reason] += 1
        world = World.create(destination / (key + ".sqlite"), "v0220-audit-" + key, public)
        before = world.snapshot()
        try:
            world.act(
                operation_id="reproduce-identity",
                expected_version=0,
                action="put_record",
                object_id=public["objects"][0],
                data={"object_id": public["objects"][0]},
            )
        except WorldError as exc:
            assert str(exc) == "IMMUTABLE_IDENTITY_FIELD"
        else:
            raise AssertionError("OLD_REJECTION_NOT_REPRODUCED")
        assert world.snapshot() == before and world.ledger() == []
        save(destination / (key + "-public-read-schemas.json"), schema)
        rows.append(
            {
                **root,
                "native_id": decision["native_id"],
                "public_initial_sha256": sha(public_path),
                "object_count": len(public["objects"]),
                "stored_identity_required": all(
                    "object_id" in s["required"] for s in schema.values()
                ),
                "identity_rejection_reproduced_without_effect": True,
                "observed_rejections": dict(rejections),
            }
        )
    assert sum(total.values()) == 296 and sum(b_total.values()) == 274
    assert b_total["IMMUTABLE_IDENTITY_FIELD"] == 156
    files = [
        "tools/v0218_host.py",
        "tools/v0219_host.py",
        "tools/v0218_world.py",
        "tools/v0213_provider.py",
        "tools/v0219_record_check.py",
        "pyproject.toml",
        "uv.lock",
    ]
    result = {
        "status": "V0_CONTRACT_AUDITED_V1_REQUIRED",
        "goal_sha256": sha(goal_path),
        "plan_sha256": sha(plan_path),
        "script_sha256": sha(Path(__file__)),
        "old_dependencies": {name: sha(LAB / name) for name in files},
        "old_manifest_sha256": sha(old / "manifest.json"),
        "old_final_audit_sha256": sha(old / "final-decision-audit-v1.json"),
        "old_schema": SCHEMA,
        "old_tools": TOOLS,
        "roots": rows,
        "old_all_rejections": dict(total),
        "old_B_rejections": dict(b_total),
        "contract_findings": [
            "Outer JSON action is constrained but arguments_json remains a second free encoding.",
            "Stored record requires object_id; write data prohibits object_id/scope/version.",
            "World CAS is global per isolated scope, not record or Note version.",
            "World operations atomically persist request hash and receipt; add authorized query. "
            "Do not infer absence means no commit.",
            "Old World checks identity/scope/CAS but not all public field types before commit; "
            "the new adapter must revalidate without private postconditions.",
            "Clarification leaves existing records active; Note/finish are not business effects.",
        ],
        "root_name_discrepancy": plan["root_naming_note"],
        "generation_requests": 0,
        "judge_requests": 0,
        "new_allocation": 0,
        "reserve_semantics_opened": 0,
        "goal_complete": False,
        "next": "New typed contract/adapter and zero-model calibration before V2 allocation.",
    }
    save(destination / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    outcome = audit(args.root)
    print(
        json.dumps(
            {
                "status": outcome["status"],
                "sha256": sha(args.root / "result.json"),
                "roots": len(outcome["roots"]),
                "new_generation_requests": 0,
            }
        )
    )
