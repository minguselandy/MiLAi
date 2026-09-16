"""V1 public contract and actual cold-process fault matrix, with zero generations."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

from v0218_world import World, WorldError, digest
from v0220_action_adapter import ActionAdapter
from v0220_action_contract import ActionContract
from v0220_evidence import LAB, read, save, seal, sha, validate


def action(target: str, record: dict, version: int) -> dict:
    return {
        "action": "put_record",
        "arguments": {
            "object_id": target,
            "expected_version": version,
            "data": {k: copy.deepcopy(v) for k, v in record.items() if k != "object_id"},
        },
    }


class Matrix:
    def __init__(self, root: Path):
        self.root, self.number, self.calls = root, 0, []

    def worker(
        self,
        world: World,
        public_path: Path,
        mode: str,
        *,
        expected_exit=0,
        error=None,
        tamper=False,
        **kwargs,
    ) -> dict | None:
        self.number += 1
        name = f"{self.number:03d}-{mode}"
        config = {
            "batch": str(self.root),
            "manifest_sha256": sha(self.root / "manifest.json"),
            "world": str(world.path),
            "scope": world.scope,
            "public": str(public_path),
            "mode": mode,
            "output": str(self.root / "cold" / (name + "-result.json")),
            **kwargs,
        }
        path = self.root / "cold" / (name + "-config.json")
        save(path, config)
        expected_hash = sha(path)
        if tamper:
            path = self.root / "cold" / (name + "-tampered-config.json")
            save(path, {**config, "scope": "tampered"})
        tick = time.monotonic()
        result = subprocess.run(  # noqa: S603 - sealed worker, fixed argv, test-owned config
            [
                sys.executable,
                str(LAB / "tools/v0220_calibration_worker.py"),
                "--config",
                str(path),
                "--config-sha256",
                expected_hash,
            ],
            cwd=LAB,
            capture_output=True,
            text=True,
            timeout=30,
        )
        receipt = {
            "id": name,
            "pid_parent": __import__("os").getpid(),
            "config_sha256": expected_hash,
            "actual_config_sha256": sha(path),
            "returncode": result.returncode,
            "seconds": time.monotonic() - tick,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        save(self.root / "cold" / (name + "-exit.json"), receipt)
        self.calls.append(receipt)
        assert result.returncode == expected_exit, (name, result.returncode, result.stderr)
        output = Path(config["output"])
        if expected_exit:
            assert not output.exists()
            if error:
                assert error in result.stderr
            return None
        response = read(output)
        assert response["pid"] != receipt["pid_parent"] and response["model_requests"] == 0
        return response


def calibrate(root: Path) -> dict:
    plan_path = LAB / "configs/v0220-execution-plan-v1.json"
    plan = read(plan_path)
    old = Path(plan["old_batch"])
    inputs = [plan_path, old / "manifest.json", old / "final-decision-audit-v1.json"]
    for key in plan["ordered_roots"]:
        inputs.extend(
            old / "cases" / key / name
            for name in ["public-initial.json", "public-changed.json", "independent-reference.json"]
        )
    seal(
        root,
        entries=[
            Path(__file__),
            LAB / "tools/v0220_calibration_worker.py",
            LAB / "tests/unit/test_v0220_action_adapter.py",
        ],
        inputs=inputs,
        contract={
            "stage": "V1_ZERO_MODEL_CONTRACT_AND_FAULT_CALIBRATION",
            "roots": plan["ordered_roots"],
            "model_requests": 0,
            "judge_requests": 0,
            "raw_token_cap": None,
            "faults": [
                "stale_unchanged_premise",
                "changed_premise",
                "crash_before_effect",
                "crash_after_effect",
                "scope",
                "payload",
                "drift",
            ],
            "scope": "Exposed reference fixtures only; no semantic or model efficacy score.",
        },
    )
    matrix, rows = Matrix(root), []
    for key in plan["ordered_roots"]:
        public_path = old / "cases" / key / "public-initial.json"
        public = read(public_path)
        reference = read(old / "cases" / key / "independent-reference.json")
        records = reference.get("records", reference.get("initial_records"))
        contract = ActionContract.from_public(public)
        save(root / (key + "-contract.json"), contract.documents())
        full = ActionAdapter(
            World.create(root / (key + "-full.sqlite"), key + "-full", public), contract
        )
        effects = []
        for index, target in enumerate(public["objects"]):
            request = action(target, records[target], index)
            result = full.execute(
                contract.decode(json.dumps(request, ensure_ascii=False)),
                operation_id=f"full-{index}",
            )
            assert result["committed"] and result["version"] == index + 1
            assert full.execute(request, operation_id=f"full-{index}") == result
            assert full.operation_status(f"full-{index}") == result
            effects.append({"action": request, "receipt": result})
        observed = matrix.worker(full.world, public_path, "read", resource="records")
        assert observed["response"]["content"] == records
        assert len(full.world.ledger()) == len(records)
        clone = full.clone(root / (key + "-clone.sqlite"), key + "-clone")
        assert clone.read("records")["content"] == records
        assert clone.operation_status("full-0")["committed"] is None
        target, other = public["objects"][:2]
        assert clone.execute(action(target, records[target], len(records)), operation_id="full-0")[
            "committed"
        ]
        assert full.world.snapshot()["version"] == len(records)
        try:
            World.create(full.world.path, "reset-overwrite", public)
        except WorldError as exc:
            assert str(exc) == "FRESH_WORLD_AND_SCOPE_REQUIRED"
        else:
            raise AssertionError("RESET_OVERWROTE_EXISTING_WORLD")
        fresh = ActionAdapter(
            World.create(root / (key + "-negative.sqlite"), key + "-negative", public), contract
        )
        negative = []
        for kind in [
            "stored_payload",
            "scope_field",
            "foreign_target",
            "missing_field",
            "unknown_argument",
            "unknown_field",
            "wrong_type",
            "null_version",
            "note_version",
        ]:
            request = action(target, records[target], 0)
            args = request["arguments"]
            if kind == "stored_payload":
                args["data"] = copy.deepcopy(records[target])
            elif kind == "scope_field":
                args["data"]["scope"] = "PRIVATE_VALUE_CANARY"
            elif kind == "foreign_target":
                args["object_id"] = "foreign-object"
            elif kind == "missing_field":
                del args["data"][next(iter(args["data"]))]
            elif kind == "unknown_argument":
                args["scope"] = "PRIVATE_VALUE_CANARY"
            elif kind == "unknown_field":
                args["data"]["UNDECLARED"] = "PRIVATE_VALUE_CANARY"
            elif kind == "wrong_type":
                args["data"] = None
            elif kind == "null_version":
                args["expected_version"] = None
            else:
                args["expected_version"] = (
                    1  # Distinct Note-domain value, while observed World is0.
                )
            before = digest(fresh.world.snapshot())
            response = fresh.execute(request, operation_id=kind)
            assert response["committed"] is False and digest(fresh.world.snapshot()) == before
            assert "PRIVATE_VALUE_CANARY" not in json.dumps(response)
            negative.append({"kind": kind, "response": response, "state_sha256": before})
        for raw in [
            '{"action":"read","action":"finish","arguments":{}}',
            '{"action":"put_record","arguments_json":"{}"}',
            json.dumps(
                {
                    "action": "put_record",
                    "arguments": {
                        "object_id": target,
                        "expected_version": 0,
                        "data": {"gold_answer": "PRIVATE_VALUE_CANARY"},
                    },
                }
            ),
        ]:
            response = matrix.worker(
                fresh.world,
                public_path,
                "decode_execute",
                raw=raw,
                operation_id="decode-" + str(len(negative)),
            )
            assert response["response"]["committed"] is False
            assert response["before_sha256"] == response["after_sha256"]
            assert "PRIVATE_VALUE_CANARY" not in json.dumps(response)
            negative.append(response)
        assert fresh.world.ledger() == []
        matrix.worker(
            World(fresh.world.path, "foreign-scope"),
            public_path,
            "read",
            resource="records",
            expected_exit=1,
            error="SCOPE_DENIED",
        )
        matrix.worker(
            fresh.world,
            public_path,
            "read",
            resource="records",
            tamper=True,
            expected_exit=1,
            error="CONFIG_DRIFT",
        )
        recovery = []
        for changed in [False, True]:
            label = "changed" if changed else "unrelated"
            world = World.create(root / f"{key}-{label}.sqlite", key + "-" + label, public)
            # Synthetic applicability condition, not a replacement native business answer.
            world.publish(
                event_id=label, current={**public["current"], "fixture_authorized": not changed}
            )
            request = action(target, records[target], 0)
            rejected = matrix.worker(
                world, public_path, "execute", action=request, operation_id="old"
            )
            assert rejected["response"]["code"] == "VERSION_CONFLICT"
            assert rejected["before_sha256"] == rejected["after_sha256"]
            observation = matrix.worker(world, public_path, "read", resource="current")
            assert observation["response"]["content"]["fixture_authorized"] == (not changed)
            version = observation["response"]["version"]
            revised = (
                {
                    "action": "request_clarification",
                    "arguments": {
                        "object_id": target,
                        "expected_version": version,
                        "data": {"question": "Fixture authorization changed; reauthorize?"},
                    },
                }
                if changed
                else action(target, records[target], version)
            )
            repaired = matrix.worker(
                world, public_path, "execute", action=revised, operation_id="revalidated"
            )
            assert repaired["response"]["committed"]
            current = world.snapshot()
            assert (target in current["pending"]) == changed
            assert (target in current["records"]) == (not changed)
            recovery.append(
                {
                    "kind": label,
                    "rejection": rejected,
                    "observation": observation,
                    "revalidated_action": revised,
                    "repaired": repaired,
                }
            )
        losses = []
        for mode in ["crash_before_effect", "crash_after_effect"]:
            world = World.create(root / f"{key}-{mode}.sqlite", key + "-" + mode, public)
            request = action(target, records[target], 0)
            matrix.worker(
                world, public_path, mode, action=request, operation_id="uncertain", expected_exit=71
            )
            query = matrix.worker(world, public_path, "query", operation_id="uncertain")
            committed = mode == "crash_after_effect"
            assert query["response"]["committed"] == (True if committed else None)
            before = digest(world.snapshot())
            blocked = matrix.worker(
                world,
                public_path,
                "execute",
                operation_id="new",
                action=action(other, records[other], world.snapshot()["version"]),
            )
            assert blocked["response"]["code"] == "UNRESOLVED_PRIOR_OPERATION"
            assert blocked["before_sha256"] == blocked["after_sha256"] == before
            if committed:
                resolved = matrix.worker(
                    world, public_path, "acknowledge", operation_id="uncertain"
                )
            else:
                resolved = matrix.worker(
                    world, public_path, "execute", action=request, operation_id="uncertain"
                )
            assert resolved["response"]["committed"] and resolved["unresolved"] == []
            replay = matrix.worker(
                world, public_path, "execute", action=request, operation_id="uncertain"
            )
            assert replay["response"] == resolved["response"] and len(world.ledger()) == 1
            losses.append(
                {
                    "mode": mode,
                    "query": query,
                    "fence": blocked,
                    "resolved": resolved,
                    "replay": replay,
                }
            )
        save(
            root / (key + "-details.json"),
            {
                "effects": effects,
                "negative": negative,
                "recoveries": recovery,
                "process_losses": losses,
                "full_final": full.world.snapshot(),
            },
        )
        rows.append(
            {
                "root": key,
                "full_record_effects": len(effects),
                "negative_cases": len(negative),
                "stale_premise_scenarios": 2,
                "process_loss_scenarios": 2,
                "scope_denied": True,
                "config_drift_denied": True,
                "clone_isolated": True,
            }
        )
        print(
            json.dumps(
                {"root": key, "status": "ROOT_FAULT_MATRIX_PASS", "cold_processes": matrix.number}
            ),
            flush=True,
        )
    validate(root)
    result = {
        "status": "V1_TYPED_CONTRACT_FAULT_MATRIX_PASS_HOST_AND_PROVIDER_NOT_YET_ADMITTED",
        "rows": rows,
        "cold_processes": matrix.number,
        "calls": matrix.calls,
        "manifest_sha256": sha(root / "manifest.json"),
        "model_requests": 0,
        "judge_requests": 0,
        "goal_complete": False,
        "remaining": [
            "Host integration and code/config/canary negative contract tests",
            "Pre-model source-reviewed Intent Oracle freeze and actual V2",
        ],
        "interpretation": "Scripted effects/encoding/recovery only, not model competence.",
    }
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = calibrate(args.root)
    print(json.dumps({"status": result["status"], "result_sha256": sha(args.root / "result.json")}))
