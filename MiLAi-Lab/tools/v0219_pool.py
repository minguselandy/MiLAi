"""Prospective neutral Seal A; no task text, evaluator labels or model outcomes used."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

from v0219_inventory import LAB, digest, read, save, sha


def rank(contract: dict, revision: str, key: str, salt: str) -> str:
    return digest(
        [contract["goal_id"], contract["pool_version"], revision, key, salt, contract["seed"]]
    )


def allocate(rows: list[dict], exposure: dict, contract: dict) -> dict:
    assert contract["A_D_wave_prefixes"] == [4, 8, 12] and contract["A_D_target"] == 12
    assert contract["new_model_allocation"] == contract["new_Judge_allocation"] == 0
    assert contract["raw_token_cap"] is None
    action = [r for r in rows if r["lane"] == "A"]
    old_families = {r["family"] for r in action if r["old_D"]}
    groups = defaultdict(list)
    excluded, reserve = [], []
    for row in action:
        if row["old_D"] or exposure[row["root_id"]]["prior_reference_count"]:
            excluded.append({"root_id": row["root_id"], "reason": "KNOWN_OLD_OR_PRIOR_REFERENCED"})
        elif row["family"] in old_families:
            groups[row["family"]].append(row)
        else:
            reserve.append(
                {
                    "root_id": row["root_id"],
                    "family": row["family"],
                    "reserve_group": row["reserve_group"],
                    "status": "RESERVED_UNVERIFIED_NOT_STATIC_ACCEPTED_C",
                }
            )
    revision = action[0]["revision"]
    families = sorted(
        groups, key=lambda family: rank(contract, revision, family, contract["order_salt"])
    )
    for family in families:
        groups[family].sort(
            key=lambda r: rank(contract, revision, r["root_id"], contract["order_salt"])
        )
    ordered = []
    for offset in range(max((len(group) for group in groups.values()), default=0)):
        for family in families:
            if offset < len(groups[family]):
                row = groups[family][offset]
                ordered.append(
                    {
                        "root_id": row["root_id"],
                        "family": family,
                        "reserve_group": row["reserve_group"],
                        "order": len(ordered) + 1,
                        "exposure": row["known_exposure"],
                        "status": "D_CANDIDATE_NOT_YET_STATIC_ACCEPTED",
                    }
                )
    return {
        "D_order": ordered,
        "reserve": reserve,
        "excluded": excluded,
        "D_family_order": families,
        "C_static_accepted": 0,
        "group_assignment_uses": "NEUTRAL_FAMILY_AND_PRIOR_EXPOSURE_ONLY",
        "cross_family_semantic_dependence": "UNKNOWN_NOT_INDEPENDENCE_PROOF",
    }


def seal(inventory: Path, exposure: Path, contract_path: Path, output: Path) -> dict:
    assert not output.exists()
    inv_result, exp_result = read(inventory / "result.json"), read(exposure / "result.json")
    assert sha(inventory / "neutral-manifest.json") == inv_result["neutral_manifest_sha256"]
    assert sha(inventory / "neutral-manifest.json") == exp_result["inventory_sha256"]
    assert sha(exposure / "exposure-manifest.json") == exp_result["exposure_manifest_sha256"]
    contract = read(contract_path)
    rows = read(inventory / "neutral-manifest.json")["rows"]
    exp = {r["root_id"]: r for r in read(exposure / "exposure-manifest.json")["rows"]}
    assignment = allocate(rows, exp, contract)
    output.mkdir(parents=True, mode=0o700)
    for path, destination in [
        (contract_path, "pool-contract.json"),
        (inventory / "neutral-manifest.json", "neutral-manifest.json"),
        (exposure / "exposure-manifest.json", "exposure-manifest.json"),
    ]:
        shutil.copyfile(path, output / destination)
    shutil.copyfile(inventory / "private/source-map.json", output / "private-source-map.json")
    save(output / "assignment.json", assignment)
    code = ["tools/v0219_inventory.py", "tools/v0219_exposure.py", "tools/v0219_pool.py"]
    for name in code:
        target = output / "executed-source" / Path(name).name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(LAB / name, target)
    result = {
        "status": "SEAL_A_FROZEN_RESERVE_PROTECTED_CONFIRMATION_ELIGIBILITY_UNPROVEN",
        "inventory_path": str(inventory),
        "inventory_result_sha256": sha(inventory / "result.json"),
        "exposure_path": str(exposure),
        "exposure_result_sha256": sha(exposure / "result.json"),
        "D_candidates": len(assignment["D_order"]),
        "D_families": len(assignment["D_family_order"]),
        "excluded_old_or_referenced": len(assignment["excluded"]),
        "reserve_candidates": len(assignment["reserve"]),
        "reserve_families": len({r["family"] for r in assignment["reserve"]}),
        "C_static_accepted": 0,
        "new_model_allocation": 0,
        "goal_complete": False,
        "F2": "REQUIRES_NEW_D_ADAPTER_CALIBRATION_AND_BATCH_SEAL",
        "files": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()},
    }
    save(output / "seal-A.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--exposure", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = seal(args.inventory, args.exposure, args.contract, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}))
