"""Freeze a bounded E1 consumption-policy batch against the selected common baseline."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path

from run_v0218 import LAB, costs, episode_plan, run, save, sha
from v0218_policy_host import POLICIES, system_for


def read(path: Path):
    return json.loads(path.read_text())


def verify_source(batch: Path) -> dict:
    manifest = read(batch / "manifest.json")
    assert sha(batch / "manifest.json") == read(batch / "manifest-sha256.json")["sha256"]
    for name, expected in manifest["input_files"].items():
        assert sha(batch / name) == expected
    for name, expected in manifest["implementation"].items():
        assert sha(batch / "executed-source" / Path(name).name) == expected
    result = read(batch / "result.json")
    assert result["status"] == "E0_EXECUTED_REQUIRES_CHAIN_AND_BEHAVIOR_AUDIT"
    assert result["cost"] == costs(batch) == read(batch / "baseline-audit-v1.json")["cost"]
    assert not result["cost"]["pending"] and not result["cost"]["violations"]
    assert result["cleanup"]["api_stopped"] and result["cleanup"]["compose_stop_returncode"] == 0
    return manifest


def freeze(root: Path, plan_path: Path) -> dict:
    plan = read(plan_path)
    selection_path = LAB / plan["selection"]
    selection = read(selection_path)
    evidence_path = Path(selection["evidence"])
    assert sha(evidence_path) == selection["evidence_sha256"]
    evidence = read(evidence_path)
    assert evidence["standard_root_count"] == 6 and evidence["probes"]["B_attempts"] == 18
    assert selection["selected_arm"] == "N1"
    assert selection["host_sha256"] == sha(LAB / "tools/v0218_host.py")
    assert plan["stage"] == "E1_OPEN_DISCOVERY_V1"
    assert plan["arms"] == ["N1", "C1", "C2"]
    assert plan["variants"] == ["stable", "superseded"]
    assert len(plan["roots"]) == len({r["root"] for r in plan["roots"]}) == 2
    assert plan["generation_cap"] == 16 and plan["seconds_per_episode"] == 900
    assert plan["batch_seconds"] == 14400 and plan["episodes"] == 14
    assert plan["max_requests"] == 224 and plan["raw_token_cap"] is None
    assert plan["new_compatibility_requests"] == plan["new_Judge_requests"] == 0
    sources = [verify_source(Path(row["batch"])) for row in plan["roots"]]
    for source in sources:
        for name, digest in source["implementation"].items():
            if name != "tools/run_v0218.py":
                assert sha(LAB / name) == digest, name
        gate = source["G_TESTBED"]
        assert sha(Path(gate["path"]) / "testbed-manifest.json") == gate["manifest_sha256"]
        assert read(Path(gate["path"]) / "testbed-manifest.json")["status"] == (
            "TESTBED_READY_FOR_DISCOVERY"
        )
    episodes = episode_plan(plan["roots"], tuple(plan["arms"]), tuple(plan["variants"]))
    assert len(episodes) == plan["episodes"]
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    for item in plan["roots"]:
        shutil.copytree(Path(item["batch"]) / "cases" / item["root"], root / "cases" / item["root"])
    shutil.copyfile(plan_path, root / "discovery-plan.json")
    shutil.copyfile(selection_path, root / "s-star.json")
    shutil.copyfile(evidence_path, root / "e0-summary.json")
    manifest = copy.deepcopy(sources[0])
    for key in ("wave", "reminder", "reminder_policy", "E0_reuse", "protocol_revision"):
        manifest.pop(key, None)
    manifest.update(
        stage=plan["stage"],
        episodes=episodes,
        arms=plan["arms"],
        variants=plan["variants"],
        max_requests=plan["max_requests"],
        batch_seconds=plan["batch_seconds"],
        policies={arm: POLICIES[arm] for arm in plan["arms"]},
        policy_systems={arm: system_for(arm) for arm in plan["arms"]},
        shared_A="NEW_NORMAL_A_ONCE_PER_ROOT_NO_POLICY_IN_A",
        estimand=plan["estimand"],
        discovery_plan=plan,
        status="SEALED_BEFORE_MODEL_GENERATION",
        preceding_evidence=[
            {
                "path": item["batch"],
                "manifest_sha256": sha(Path(item["batch"]) / "manifest.json"),
                "result_sha256": sha(Path(item["batch"]) / "result.json"),
            }
            for item in plan["roots"]
        ],
        S_star="N1",
        whole_goal_complete=False,
    )
    code = [
        *sources[0]["implementation"],
        "tools/v0218_policy_host.py",
        "tools/run_v0218_discovery.py",
        "tools/audit_v0218_discovery.py",
    ]
    manifest["implementation"] = {name: sha(LAB / name) for name in code}
    for name in code:
        target = root / "executed-source" / Path(name).name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(LAB / name, target)
    manifest["input_files"] = {
        str(path.relative_to(root)): sha(path)
        for path in root.rglob("*")
        if path.is_file() and "executed-source" not in path.parts
    }
    save(root / "manifest.json", manifest)
    save(root / "manifest-sha256.json", {"sha256": sha(root / "manifest.json")})
    shutil.copyfile(
        LAB / "studies/active/MILA_V0218_行为真值测试床建设_GOAL_20260910.md",
        root / "goal-as-executed.md",
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--freeze-plan", type=Path)
    parser.add_argument("--installed", type=Path)
    args = parser.parse_args()
    result = (
        freeze(args.root, args.freeze_plan) if args.freeze_plan else run(args.root, args.installed)
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k in ("status", "stage", "cost", "max_requests", "reason")
            }
        )
    )
