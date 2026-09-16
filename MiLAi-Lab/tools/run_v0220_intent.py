"""Seal and run V2 candidate 1 once, 24 cold chains, immediate bounded failure stop."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from v02_local_provider import accounting, read_events
from v0218_world import World, digest
from v0220_action_contract import ActionContract
from v0220_evidence import LAB, read, save, seal, sha, validate
from v0220_intent_audit import audit

ANNOTATION = (
    '\nEncoding calibration only (not a business fact): 中文 / English "quote"; literal \\path.\n'
)


def actions_for(selection: dict, records: dict, kind: str) -> list[dict]:
    targets = (
        selection["sequence"]
        if kind == "two_object_sequence"
        else [selection["complex"] if kind == "complex_complete_record" else selection["single"]]
    )
    result = []
    for version, target in enumerate(targets):
        data = {k: copy.deepcopy(v) for k, v in records[target].items() if k != "object_id"}
        if kind == "complex_complete_record":
            container = data
            for part in selection["text_path"][:-1]:
                container = container[part]
            field = selection["text_path"][-1]
            if not isinstance(container[field], str):
                raise ValueError("REVIEWED_FREE_TEXT_FIELD_REQUIRED")
            container[field] += ANNOTATION
        result.append(
            {
                "action": "put_record",
                "arguments": {
                    "object_id": target,
                    "expected_version": version,
                    "data": data,
                },
            }
        )
    return result


def prepare(root: Path, evidence: Path) -> dict:
    plan_path = LAB / "configs/v0220-execution-plan-v1.json"
    selection_path = LAB / "configs/v0220-v2-selection-v1.json"
    selection, plan = read(selection_path), read(plan_path)
    if selection["root_order"] != plan["ordered_roots"]:
        raise ValueError("ORIGINAL_ROOT_ORDER_REQUIRED")
    inputs = [
        plan_path,
        selection_path,
        LAB / "studies/active/MILA_V0220_动作执行有效性校准与记忆复验准入_GOAL_20260911.md",
    ]
    for name in (
        "v1-fault-matrix-v1",
        "v1-host-matrix-v1",
        "v1-nonbusiness-checker-audit-v1",
        "provider-compat-v1",
    ):
        validate(evidence / name)
        path = evidence / name / "result.json"
        inputs.append(path)
        result = read(path)
        if "PASS" not in result["status"]:
            raise ValueError("V1_AND_COMPATIBILITY_REQUIRED")
        if name == "provider-compat-v1" and (
            result["cost"]["requests"] != 2
            or result["cost"]["pending"]
            or result["cost"]["violations"]
        ):
            raise ValueError("SETTLED_COMPATIBILITY_REQUIRED")
    old = Path(plan["old_batch"])
    old_manifest = read(old / "manifest.json")
    inputs.append(old / "manifest.json")
    for name, expected in old_manifest["model_assets"].items():
        if sha(Path(name)) != expected:
            raise ValueError("MODEL_ASSET_DRIFT")
        inputs.append(Path(name))
    episodes, public_inputs, review = [], {}, {}
    for key in selection["root_order"]:
        public_path, reference_path = [
            old / "cases" / key / name
            for name in ("public-initial.json", "independent-reference.json")
        ]
        inputs.extend([public_path, reference_path])
        public, reference = read(public_path), read(reference_path)
        public_inputs[key] = public
        records = reference.get("records", reference.get("initial_records"))
        contract = ActionContract.from_public(public)
        review[key] = {
            "reference_sha256": sha(reference_path),
            "public_sha256": sha(public_path),
            "source_locations": reference["source_locations"],
            "prior_reviewer": reference["reviewer"],
            "selection": selection["roots"][key],
            "new_review": selection["review"],
        }
        for kind in selection["chain_order"]:
            actions = actions_for(selection["roots"][key], records, kind)
            for action in actions:
                contract.validate(action)
            for cold in selection["cold_repeats"]:
                identity = f"v2c1-{len(episodes) + 1:02d}"
                scope = identity + "-" + key
                initial = {
                    **copy.deepcopy(public),
                    "scope": scope,
                    "version": 0,
                    "records": {},
                    "pending": {},
                    "history": [],
                }
                episodes.append(
                    {
                        "id": identity,
                        "root": key,
                        "family": selection["roots"][key]["family"],
                        "kind": kind,
                        "cold": cold,
                        "scope": scope,
                        "initial_state_sha256": digest(initial),
                        "actions": actions,
                        "intent": {
                            "instruction": "Perform these complete writes in order. "
                            "Preserve the supplied values and full text exactly. Initial "
                            "WORLD version is available in the public observations. "
                            "After all writes, read records and verify actual content, "
                            "then finish. Do not perform other task deliverables. "
                            "At most four generations include readback and finish.",
                            "ordered_writes": [
                                {
                                    "object_id": a["arguments"]["object_id"],
                                    "data": a["arguments"]["data"],
                                }
                                for a in actions
                            ],
                        },
                    }
                )
    assert len(episodes) == 24
    contract = {
        "stage": "V2_INTENT_ORACLE",
        "candidate": 1,
        "maximum_protocol_candidates": 2,
        "generation_cap_per_chain": 4,
        "maximum_requests": 96,
        "raw_token_cap": None,
        "seconds_per_chain": 300,
        "batch_seconds": 7200,
        "model_concurrency": 1,
        "model": old_manifest["model"],
        "context": old_manifest["context"],
        "output_cap": 4096,
        "request_timeout_seconds": 60,
        "seed": 213,
        "temperature": 0,
        "enable_thinking": False,
        "new_compatibility_requests": 0,
        "judge_requests": 0,
        "smoke_positions_included": [1, 2],
        "episodes": episodes,
        "source_review": review,
        "stop": "First unexpected protocol failure, fidelity/effect failure, unknown usage/commit, "
        "safety or evidence failure stops this candidate. No replacement/retry. "
        "Unrun positions retained.",
        "interpretation": "Intent Oracle encoding/effect calibration; "
        "not natural task or Memory evidence.",
    }
    seal(
        root,
        entries=[
            Path(__file__),
            LAB / "tools/v0220_intent_worker.py",
            LAB / "tests/unit/test_v0220_intent.py",
            LAB / "tests/unit/test_v0220_action_adapter.py",
        ],
        inputs=inputs,
        contract=contract,
    )
    for spec in episodes:
        world = World.create(
            root / "worlds" / f"{spec['id']}.sqlite", spec["scope"], public_inputs[spec["root"]]
        )
        assert digest(world.snapshot()) == spec["initial_state_sha256"]
    save(
        root / "prepared.json",
        {
            "status": "SEALED_NOT_RUN",
            "manifest_sha256": sha(root / "manifest.json"),
            "episodes": 24,
            "allocated_request_bound": 96,
        },
    )
    return contract


def costs(root: Path) -> dict:
    states = [
        accounting(read_events(p))
        for p in sorted((root / "episodes").glob("*/provider-ledger.jsonl"))
    ]
    return {
        "requests": sum(s["requests"] for s in states),
        "raw_tokens": sum(s["raw_tokens"] for s in states),
        "pending": [v for s in states for v in s["pending"]],
        "violations": [v for s in states for v in s["violations"]],
    }


def execute(root: Path, manifest_sha: str) -> dict:
    manifest = validate(root, manifest_sha256=manifest_sha)
    contract = manifest["contract"]
    if contract["stage"] != "V2_INTENT_ORACLE" or contract["candidate"] != 1:
        raise ValueError("WRONG_STAGE")
    if (root / "episodes").exists() or (root / "result.json").exists():
        raise ValueError("CANNOT_RESTART_ATTEMPTED_MATRIX")
    save(
        root / "run-started.json",
        {"pid": os.getpid(), "unix": time.time(), "manifest_sha256": manifest_sha},
    )
    start, rows = time.monotonic(), []
    for spec in contract["episodes"]:
        validate(root, manifest_sha256=manifest_sha)
        if time.monotonic() - start >= contract["batch_seconds"]:
            break
        save(root / "launches" / f"{spec['id']}.json", {"episode": spec["id"], "unix": time.time()})
        timed_out = False
        try:
            child = subprocess.run(  # noqa: S603 - fixed actor, sealed owned evidence
                [
                    sys.executable,
                    str(LAB / "tools/v0220_intent_worker.py"),
                    "--root",
                    str(root),
                    "--manifest-sha256",
                    manifest_sha,
                    "--episode",
                    spec["id"],
                ],
                capture_output=True,
                text=True,
                timeout=310,
                cwd=LAB,
            )
            exit_receipt = {
                "returncode": child.returncode,
                "stdout": child.stdout,
                "stderr": child.stderr,
            }
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_receipt = {
                "returncode": None,
                "status": "OWNED_CHILD_TIMEOUT_KILLED_USAGE_NOT_ASSUMED_ZERO",
            }
        save(root / "exits" / f"{spec['id']}.json", exit_receipt)
        worker_path = root / "episodes" / spec["id"] / "worker-result.json"
        if timed_out or exit_receipt["returncode"] != 0 or not worker_path.is_file():
            outcome = {"status": "FAIL", "reason": "WORKER_INCOMPLETE"}
        else:
            worker = read(worker_path)
            if worker["status"] != "SESSION_FINISHED_NOT_TASK_VERDICT":
                outcome = {
                    "status": "FAIL",
                    "reason": worker["status"],
                    "rejection_counts": worker["rejection_counts"],
                    "cost": worker["cost"],
                }
            else:
                try:
                    outcome = audit(root, spec)
                except Exception as exc:
                    outcome = {
                        "status": "FAIL",
                        "reason": "EVIDENCE_AUDIT_FAILURE",
                        "exception_type": type(exc).__name__,
                    }
                if worker["pid"] == os.getpid():
                    outcome = {"status": "FAIL", "reason": "COLD_PROCESS_NOT_PROVEN"}
        row = {
            "episode": spec["id"],
            "root": spec["root"],
            "kind": spec["kind"],
            "cold": spec["cold"],
            **outcome,
        }
        rows.append(row)
        save(root / "audits" / f"{spec['id']}.json", row)
        current_cost = costs(root)
        print(
            json.dumps(
                {
                    "episode": spec["id"],
                    "status": outcome["status"],
                    "requests": current_cost["requests"],
                    "raw_tokens": current_cost["raw_tokens"],
                }
            ),
            flush=True,
        )
        if outcome["status"] != "PASS" or current_cost["pending"] or current_cost["violations"]:
            break
    cost = costs(root)
    passed = len(rows) == 24 and all(r["status"] == "PASS" for r in rows)
    result = {
        "status": "G_KNOWN_INTENT_PASS" if passed else "CANDIDATE_STOPPED_G_KNOWN_INTENT_NOT_MET",
        "candidate": 1,
        "rows": rows,
        "attempted_chains": len(rows),
        "passed_chains": sum(r["status"] == "PASS" for r in rows),
        "unrun": [s["id"] for s in contract["episodes"][len(rows) :]],
        "cost": cost,
        "seconds": time.monotonic() - start,
        "manifest_sha256": manifest_sha,
        "V3": "ELIGIBLE_NOT_RUN" if passed else "NOT_TRIGGERED",
        "V4": "NOT_TRIGGERED",
        "V5": "NOT_TRIGGERED",
    }
    validate(root, manifest_sha256=manifest_sha)
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "execute"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.root, args.evidence)
    else:
        execute(args.root, args.manifest_sha256)
