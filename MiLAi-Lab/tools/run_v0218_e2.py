"""Freeze the complete E2 matched-information control matrix before model allocation."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path

from run_v0218 import LAB, costs, episode_plan, run, save, sha
from v0218_e2_host import POLICIES, system_for
from v0218_host import PUBLIC_PREFETCH


def read(path: Path):
    return json.loads(path.read_text())


def verify_prior(item: dict) -> dict:
    root = Path(item["path"])
    manifest = read(root / "manifest.json")
    assert sha(root / "manifest.json") == read(root / "manifest-sha256.json")["sha256"]
    assert sha(root / "result.json") == item["result_sha256"]
    assert sha(root / "discovery-audit-v1.json") == item["audit_sha256"]
    for name, expected in manifest["input_files"].items():
        assert sha(root / name) == expected
    for name, expected in manifest["implementation"].items():
        assert sha(root / "executed-source" / Path(name).name) == expected
    result, audit = read(root / "result.json"), read(root / "discovery-audit-v1.json")
    assert manifest["stage"] == "E1_OPEN_DISCOVERY_V1"
    assert result["status"] == "DISCOVERY_EXECUTED_REQUIRES_AUDIT"
    assert len(result["rows"]) == len(manifest["episodes"]) == 14
    assert audit["manifest_sha256"] == sha(root / "manifest.json")
    assert audit["result_sha256"] == item["result_sha256"]
    assert result["cost"] == audit["cost"] == costs(root)
    assert not result["cost"]["pending"] and not result["cost"]["violations"]
    assert result["cleanup"]["api_stopped"] and result["cleanup"]["compose_stop_returncode"] == 0
    return manifest


def validate_plan(plan: dict) -> list[dict]:
    assert plan["stage"] == "E2_MATCHED_PUBLIC_INFORMATION_V1"
    assert plan["arms"] == list(POLICIES)
    assert plan["variants"] == ["stable", "superseded", "unresolved"]
    assert plan["public_prefetch"] == PUBLIC_PREFETCH
    assert len(plan["roots"]) == len({r["root"] for r in plan["roots"]}) == 2
    assert len(plan["preceding_runs"]) == 2
    assert plan["generation_cap"] == 16 and plan["seconds_per_episode"] == 900
    assert plan["batch_seconds"] == 30600 and plan["episodes"] == 32
    assert plan["max_requests"] == 512 and plan["raw_token_cap"] is None
    assert plan["new_compatibility_requests"] == plan["new_Judge_requests"] == 0
    episodes = episode_plan(plan["roots"], tuple(plan["arms"]), tuple(plan["variants"]))
    assert len(episodes) == 32 and len(episodes) * plan["generation_cap"] == 512
    return episodes


def freeze(root: Path, plan_path: Path) -> dict:
    plan = read(plan_path)
    episodes = validate_plan(plan)
    sources = [verify_prior(item) for item in plan["preceding_runs"]]
    selection_path = LAB / plan["selection"]
    selection = read(selection_path)
    assert selection["selected_arm"] == "N1"
    assert sha(Path(selection["evidence"])) == selection["evidence_sha256"]
    for source in sources:
        assert source["implementation"]["tools/v0218_host.py"] == selection["host_sha256"]
        assert {r["root"] for r in source["episodes"]} == {r["root"] for r in plan["roots"]}
        for name, expected in source["implementation"].items():
            if name not in {"tools/run_v0218.py", "tools/v0218_host.py"}:
                assert sha(LAB / name) == expected, name
        for arm in ("N1", "C1", "C2"):
            assert source["policy_systems"][arm] == system_for(arm)
        gate = source["G_TESTBED"]
        assert sha(Path(gate["path"]) / "testbed-manifest.json") == gate["manifest_sha256"]
        assert read(Path(gate["path"]) / "testbed-manifest.json")["status"] == (
            "TESTBED_READY_FOR_DISCOVERY"
        )
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    prior_root = Path(plan["preceding_runs"][0]["path"])
    for item in plan["roots"]:
        shutil.copytree(prior_root / "cases" / item["root"], root / "cases" / item["root"])
        spec = read(root / "cases" / item["root"] / "evaluation-contract.json")
        assert set(plan["variants"]).issubset(spec["variants"])
    shutil.copyfile(plan_path, root / "control-plan.json")
    shutil.copyfile(selection_path, root / "s-star.json")
    shutil.copyfile(Path(selection["evidence"]), root / "e0-summary.json")
    shutil.copyfile(
        LAB / "studies/active/MILA_V0218_E2_CONTROL_PLAN_20260911.md", root / "control-plan.md"
    )
    manifest = copy.deepcopy(sources[0])
    manifest.pop("discovery_plan", None)
    manifest.update(
        stage=plan["stage"],
        episodes=episodes,
        arms=plan["arms"],
        variants=plan["variants"],
        max_requests=512,
        batch_seconds=30600,
        compatibility_requests=0,
        policies=POLICIES,
        policy_systems={arm: system_for(arm) for arm in plan["arms"]},
        public_prefetch=PUBLIC_PREFETCH,
        prefetch_origin="HARNESS_PUBLIC_PREFETCH",
        common_plumbing_revision={
            "old_host_sha256": selection["host_sha256"],
            "new_host_sha256": sha(LAB / "tools/v0218_host.py"),
            "change": "Optional B-only full public prefetch; default path unchanged",
        },
        shared_A="NEW_NORMAL_A_ONCE_PER_ROOT_NO_POLICY_OR_PREFETCH_IN_A",
        estimand=plan["estimand"],
        control_plan=plan,
        preceding_evidence=plan["preceding_runs"],
        status="SEALED_BEFORE_MODEL_GENERATION",
        whole_goal_complete=False,
    )
    code = [
        *sources[0]["implementation"],
        "tools/v0218_e2_host.py",
        "tools/run_v0218_e2.py",
        "tools/audit_v0218_e2.py",
    ]
    manifest["implementation"] = {name: sha(LAB / name) for name in code}
    for name in code:
        target = root / "executed-source" / Path(name).name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(LAB / name, target)
    shutil.copyfile(
        LAB / "studies/active/MILA_V0218_行为真值测试床建设_GOAL_20260910.md",
        root / "goal-as-executed.md",
    )
    manifest["input_files"] = {
        str(path.relative_to(root)): sha(path)
        for path in root.rglob("*")
        if path.is_file() and "executed-source" not in path.parts
    }
    save(root / "manifest.json", manifest)
    save(root / "manifest-sha256.json", {"sha256": sha(root / "manifest.json")})
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
