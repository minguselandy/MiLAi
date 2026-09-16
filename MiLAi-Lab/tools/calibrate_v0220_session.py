"""Four exposed roots, two no-carry Host profiles, two cold scripted runs. V1 only."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from v0218_world import World
from v0220_evidence import LAB, read, save, seal, sha, validate


def calibrate(root: Path) -> dict:
    plan_path = LAB / "configs/v0220-execution-plan-v1.json"
    plan = read(plan_path)
    old = Path(plan["old_batch"])
    inputs = [plan_path]
    for key in plan["ordered_roots"]:
        inputs.extend(
            old / "cases" / key / name
            for name in ("public-initial.json", "independent-reference.json")
        )
    seal(
        root,
        entries=[
            Path(__file__),
            LAB / "tools/v0220_session_fixture_worker.py",
            LAB / "tests/unit/test_v0220_session.py",
            LAB / "tests/unit/test_v0220_action_adapter.py",
        ],
        inputs=inputs,
        contract={
            "stage": "V1_SCRIPTED_HOST_FIXTURE",
            "roots": plan["ordered_roots"],
            "profiles": ["INTENT_ORACLE", "NATURAL_NO_CARRY_R0"],
            "cold_repeats": 2,
            "model_requests": 0,
            "judge_requests": 0,
            "interpretation": "Scripted Host integration, not V2/V4 outcomes or allocations.",
        },
    )
    rows = []
    for key in plan["ordered_roots"]:
        public = read(old / "cases" / key / "public-initial.json")
        reference = read(old / "cases" / key / "independent-reference.json")
        records = reference.get("records", reference.get("initial_records"))
        targets = public["objects"][:2]
        for profile in ("INTENT_ORACLE", "NATURAL_NO_CARRY"):
            for cold in (1, 2):
                label = f"{key}-{profile}-{cold}"
                world = World.create(root / f"{label}.sqlite", label, public)
                actions = []
                for version, target in enumerate(targets):
                    actions.append(
                        {
                            "action": "put_record",
                            "arguments": {
                                "object_id": target,
                                "expected_version": version,
                                # Explicit evaluator fixture conversion, never runtime repair.
                                "data": {
                                    k: v for k, v in records[target].items() if k != "object_id"
                                },
                            },
                        }
                    )
                if profile == "NATURAL_NO_CARRY":
                    actions.insert(
                        0,
                        {
                            "action": "save_note",
                            "arguments": {"note": "Synthetic V1 local-session review; not memory."},
                        },
                    )
                actions.extend(
                    [
                        {"action": "read", "arguments": {"resource": "records"}},
                        {
                            "action": "finish",
                            "arguments": {
                                "message": "Scripted partial fixture, not task completion."
                            },
                        },
                    ]
                )
                directory = root / "cold" / label
                config = {
                    "stage": "V1_SCRIPTED_HOST_FIXTURE",
                    "batch": str(root),
                    "manifest_sha256": sha(root / "manifest.json"),
                    "world": str(world.path),
                    "scope": world.scope,
                    "output": str(directory),
                    "episode_id": label,
                    "profile": profile,
                    "arm": "ORACLE" if profile == "INTENT_ORACLE" else "R0-exec",
                    "intent": {"actions": actions[:2]} if profile == "INTENT_ORACLE" else None,
                    "outputs": [json.dumps(a, ensure_ascii=False) for a in actions],
                }
                config_path = root / "configs" / f"{label}.json"
                save(config_path, config)
                process = subprocess.run(  # noqa: S603 - fixed worker, owned sealed fixtures
                    [
                        sys.executable,
                        str(LAB / "tools/v0220_session_fixture_worker.py"),
                        "--config",
                        str(config_path),
                        "--config-sha256",
                        sha(config_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=45,
                    cwd=LAB,
                )
                save(
                    root / "exits" / f"{label}.json",
                    {
                        "returncode": process.returncode,
                        "stdout": process.stdout,
                        "stderr": process.stderr,
                    },
                )
                if process.returncode:
                    raise ValueError("SCRIPTED_CHILD_FAILED_SEE_OWNED_EXIT_RECEIPT")
                result = read(directory / "fixture-result.json")
                assert result["pid"] != os.getpid()
                assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
                assert result["actual_world_version"] == result["ledger_rows"] == 2
                assert world.snapshot()["records"] == {
                    target: records[target] for target in targets
                }
                assert result["experimental_model_requests"] == 0
                assert result["note_writes"] == int(profile == "NATURAL_NO_CARRY")
                presentation = read(directory / "initial-presentation.json")
                assert presentation["inherited_note"] is None
                assert ("authorized_intent" in presentation) == (profile == "INTENT_ORACLE")
                rows.append({"root": key, "profile": profile, "cold": cold, **result})
                print(label + " SCRIPTED_HOST_PASS", flush=True)
    validate(root)
    result = {
        "status": "V1_COLD_SCRIPTED_HOST_MATRIX_PASS",
        "rows": rows,
        "cold_processes": len(rows),
        "model_requests": 0,
        "judge_requests": 0,
        "manifest_sha256": sha(root / "manifest.json"),
        "interpretation": "Host contract/effects only; zero real-model evidence.",
        "remaining": ["V1 whole-gate audit", "Frozen V2 Intent Oracle and real Provider execution"],
    }
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    calibrate(parser.parse_args().root)
