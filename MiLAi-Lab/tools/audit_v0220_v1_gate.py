"""Offline V1 gate evidence: independent full-task checker never enters the Host."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from v0218_world import World, digest
from v0219_record_check import evaluate
from v0220_evidence import LAB, read, save, seal, sha, validate
from v0220_session import Session
from v0220_session_fixture_worker import ScriptedProvider


def audit(root: Path, evidence: Path) -> dict:
    plan_path = LAB / "configs/v0220-execution-plan-v1.json"
    plan = read(plan_path)
    old = Path(plan["old_batch"])
    names = ["v1-fault-matrix-v1", "v1-host-matrix-v1", "v1-capacity-preflight-v1"]
    for name in names:
        validate(evidence / name)
    inputs = [plan_path]
    for name in names:
        inputs.extend(evidence / name / file for file in ("manifest.json", "result.json"))
    for key in plan["ordered_roots"]:
        inputs.extend(
            old / "cases" / key / file for file in ("public-initial.json", "oracle-initial.json")
        )
    seal(
        root,
        entries=[Path(__file__)],
        inputs=inputs,
        contract={
            "stage": "V1_OFFLINE_FULL_TASK_NONBUSINESS_NEGATIVE_AUDIT",
            "model_requests": 0,
            "judge_requests": 0,
            "private_checker": "Evaluator only: reject absent complete work; "
            "do not infer disputed values.",
        },
    )
    rows = []
    for key in plan["ordered_roots"]:
        public = read(old / "cases" / key / "public-initial.json")
        private = read(old / "cases" / key / "oracle-initial.json")
        world = World.create(root / f"{key}.sqlite", key + "-nonbusiness", public)
        before = digest(world.snapshot())
        directory = root / key
        session = Session(
            world,
            directory,
            episode_id=key,
            profile="NATURAL_NO_CARRY",
            arm="R0-exec",
            intent=None,
            validate_binding=lambda: validate(root),
        )
        provider = ScriptedProvider(
            directory,
            [
                '{"action":"save_note","arguments":{"note":"DONE: all work claimed complete."}}',
                '{"action":"finish","arguments":{"message":"DONE: all work claimed complete."}}',
            ],
        )
        execution = session.run(provider, deadline=time.monotonic() + 30)
        actual = World(world.path, world.scope).snapshot()
        verdict = evaluate(actual, private)
        assert execution["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
        assert execution["note_writes"] == 1
        assert before == digest(actual) and world.ledger() == []
        assert verdict["status"] == "FAIL"
        assert {"layer": "EXECUTED_RECORDS", "check": "COMPLETE_OBJECT_SET"} in verdict["errors"]
        save(directory / "independent-full-task-verdict.json", verdict)
        save(directory / "actual-world.json", actual)
        rows.append(
            {
                "root": key,
                "host_finished": True,
                "note_saved": True,
                "world_unchanged": True,
                "business_effects": 0,
                "independent_full_task": "FAIL",
                "verdict_sha256": sha(directory / "independent-full-task-verdict.json"),
            }
        )
    validate(root)
    result = {
        "status": "V1_NONBUSINESS_COMPLETION_NEGATIVE_AUDIT_PASS",
        "rows": rows,
        "model_requests": 0,
        "judge_requests": 0,
        "prior_evidence": {name: sha(evidence / name / "result.json") for name in names},
        "scope": "Public typed contract, real Lab effects, 88 cold fault processes, "
        "16 cold scripted Host processes, 4 independent Note/DONE negative full-task checks. "
        "No real-model gate inferred.",
        "V2": "NOT_RUN_REQUIRES_ORACLE_CORPUS_AND_BATCH_FREEZE",
        "V3": "NOT_RUN_REQUIRES_V2_AND_FROZEN_STIMULUS_RUNNER",
        "V4": "NOT_RUN_REQUIRES_V3_AND_SOURCE_GROUNDED_DISPUTE_CONTRACT",
        "V5": "CONDITIONAL_NOT_TRIGGERED",
    }
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    audit(args.root, args.evidence)
