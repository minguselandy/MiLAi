"""Zero-generation compatibility repair proof on all four already exposed roots.

Original vs wire schemas use the installed CPU validation/error wrapper. Reference
actions are offline fixtures only; they never enter a real model or a natural run.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator

from v0218_world import World
from v0220_action_adapter import ActionAdapter
from v0220_action_contract import ActionContract
from v0220_evidence import LAB, read, save, seal, validate
from v0220_wire_admission import backend_identity
from v0220_wire_contract import REVISION, WireContractError, compile_contract, fingerprint


def duplicate_candidates(schema: dict, value: object, path: list | None = None) -> list[list]:
    path = path or []
    found = []
    if schema.get("uniqueItems") is True and isinstance(value, list) and value:
        found.append(path)
    if isinstance(value, dict):
        for name, child in schema.get("properties", {}).items():
            if name in value:
                found.extend(duplicate_candidates(child, value[name], [*path, name]))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, child in enumerate(value):
            found.extend(duplicate_candidates(schema["items"], child, [*path, i]))
    return found


def semantic_checks(root: Path, cases: list[tuple[str, Path, Path]]) -> dict:
    rows = []
    for key, public_path, reference_path in cases:
        public, reference = read(public_path), read(reference_path)
        records = reference.get("records", reference.get("initial_records"))
        contract = ActionContract.from_public(public)
        adapter = ActionAdapter(
            World.create(root / f"{key}.sqlite", "wire-" + key, public), contract
        )
        plan = compile_contract(contract.action_schema())
        assert set(records) == set(public["objects"])
        for i, target in enumerate(public["objects"]):
            data = {k: copy.deepcopy(v) for k, v in records[target].items() if k != "object_id"}
            # Explicit conversion of already exposed evaluator fixtures, not model-output repair.
            action = {
                "action": "put_record",
                "arguments": {
                    "object_id": target,
                    "expected_version": i,
                    "data": data,
                },
            }
            decoded = plan.validate_output(json.dumps(action, ensure_ascii=False))
            assert decoded == action and Draft202012Validator(plan.wire).is_valid(action)
            before = adapter.world.snapshot()
            mutations = []
            for path in duplicate_candidates(contract.write_schemas()[target], data):
                invalid = copy.deepcopy(action)
                obj = invalid["arguments"]["data"]
                for part in path:
                    obj = obj[part]
                obj.append(copy.deepcopy(obj[0]))
                wire_accepts = Draft202012Validator(plan.wire).is_valid(invalid)
                try:
                    plan.validate_output(json.dumps(invalid, ensure_ascii=False))
                except WireContractError:
                    rejected = True
                else:
                    rejected = False
                assert rejected and adapter.world.snapshot() == before
                response = adapter.execute(invalid, operation_id=f"duplicate-{i}-{len(mutations)}")
                assert response["committed"] is False and adapter.world.snapshot() == before
                mutations.append(
                    {
                        "path": path,
                        "wire_accepts": wire_accepts,
                        "full_validator_rejects": rejected,
                        "executor_rejects": True,
                        "business_effect": False,
                    }
                )
            identity = copy.deepcopy(action)
            identity["arguments"]["data"]["scope"] = "not-authorized"
            try:
                plan.validate_output(json.dumps(identity))
            except WireContractError:
                identity_rejected = True
            else:
                identity_rejected = False
            assert identity_rejected and adapter.world.snapshot() == before
            receipt = adapter.execute(decoded, operation_id=f"write-{i}")
            assert receipt["committed"] is True
            assert adapter.read("records")["content"][target] == records[target]
            assert adapter.execute(decoded, operation_id=f"write-{i}") == receipt
            current = adapter.world.snapshot()
            stale = adapter.execute(decoded, operation_id=f"stale-{i}")
            assert stale["code"] == "VERSION_CONFLICT" and adapter.world.snapshot() == current
            rows.append(
                {
                    "root": key,
                    "target": target,
                    "exact_full_record_roundtrip": True,
                    "wire_accepts_original_valid_action": True,
                    "duplicate_mutants": mutations,
                    "identity_rejected": identity_rejected,
                    "exact_replay": True,
                    "stale_version_rejected_no_effect": True,
                }
            )
        assert adapter.world.snapshot()["records"] == records
        assert len(adapter.world.ledger()) == len(records)
    return {
        "rows": rows,
        "all_pass": True,
        "model_requests": 0,
        "profile": "EXPOSED_SCRIPTED_REFERENCE_NOT_MODEL_OR_BUSINESS_SCORE",
    }


def run(source: Path, root: Path, container: str) -> dict:
    validate(source)
    original = read(source / "manifest.json")
    roots = original["contract"]["roots"]
    execution = read(LAB / "configs/v0220-execution-plan-v1.json")
    if roots != execution["ordered_roots"] or len(set(roots)) != 4:
        raise ValueError("ORIGINAL_COMPLETE_FOUR_ROOT_ORDER_REQUIRED")
    cases = [
        (
            k,
            Path(execution["old_batch"]) / "cases" / k / "public-initial.json",
            Path(execution["old_batch"]) / "cases" / k / "independent-reference.json",
        )
        for k in roots
    ]
    before_backend = backend_identity(container)
    probe = LAB / "tools/v0220_provider_cpu_probe_v3.py"
    inventory = read(source / "inventory.json")
    assert len(inventory) == 8
    requests = [source / "requests" / (r["id"] + ".json") for r in inventory]
    seal(
        root,
        entries=[Path(__file__), probe, LAB / "tools/v0220_wire_provider.py"],
        inputs=[
            source / "manifest.json",
            source / "result.json",
            source / "inventory.json",
            source / "probes.json",
            LAB / "configs/v0220-execution-plan-v1.json",
            *requests,
            *(p for _, *paths in cases for p in paths),
        ],
        contract={
            "revision": REVISION,
            "roots": roots,
            "model_requests": 0,
            "public_contract_unchanged": True,
            "wire_uniqueItems_deferred": True,
            "backend_identity": before_backend,
            "shared_service_changes": 0,
            "historical_usage_waived": False,
            "V2_resumed": False,
        },
    )
    prepared, pairs = [], []
    for item, request_path in zip(inventory, requests, strict=True):
        body = read(request_path)
        plan = compile_contract(body["response_format"]["json_schema"]["schema"])
        wire = plan.prepare(body)
        key = item["id"]
        save(root / "requests" / (key + "-canonical.json"), body)
        save(root / "requests" / (key + "-wire.json"), wire)
        save(
            root / "contracts" / (key + ".json"),
            {
                **plan.manifest(),
                "canonical": plan.canonical,
                "wire": plan.wire,
            },
        )
        pairs.append(
            {
                **item,
                "canonical_request_sha256": fingerprint(body),
                "wire_request_sha256": fingerprint(wire),
                "contract": plan.manifest(),
            }
        )
        prepared.extend(
            [{"id": key + "-canonical", "body": body}, {"id": key + "-wire", "body": wire}]
        )
    save(root / "inventory.json", pairs)
    program = (
        "import sys,json,asyncio\n"
        "data=json.load(sys.stdin); ns={'__name__':'cpu_probe_module'}\n"
        "exec(compile(data['script'],'cpu_probe_v3.py','exec'),ns)\n"
        "rows=[]\n"
        "for item in data['requests']:\n"
        " value=asyncio.run(ns['probe'](item['body']))\n"
        " value.pop('sources'); rows.append({'id':item['id'],**value})\n"
        "print(json.dumps(rows))\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed CPU-only probe, validated container identity
        ["/usr/bin/docker", "exec", "-i", container, "python3", "-c", program],
        input=json.dumps({"script": probe.read_text(), "requests": prepared}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    save(
        root / "process.json",
        {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        },
    )
    if completed.returncode:
        raise ValueError("CPU_WIRE_PROBE_PROCESS_FAILED")
    rows = json.loads(completed.stdout.splitlines()[-1])
    for row in rows:
        counts = row["counts"]
        assert counts["input_validation_entered"] == 1 and counts["engine_submissions"] == 0
        passed = counts["post_validation_reached"] == 1 and row["observed"]["cause_message"] == (
            "CPU_PROBE_STOP_AFTER_PARAMETER_VALIDATION_NO_ENGINE"
        )
        row["status"] = "PASS_CPU_ONLY" if passed else "REJECTED"
    save(root / "probes.json", rows)
    semantic = semantic_checks(root / "semantic", cases)
    save(root / "semantic.json", semantic)
    assert backend_identity(container) == before_backend
    expected = {r["id"] + suffix for r in inventory for suffix in ("-canonical", "-wire")}
    assert len(rows) == 16 and {r["id"] for r in rows} == expected
    all_wire_pass = all(r["status"] == "PASS_CPU_ONLY" for r in rows if r["id"].endswith("-wire"))
    result = {
        "status": "WIRE_REPAIR_CPU_VALIDATED_NOT_LIVE_OR_V2_PASS"
        if all_wire_pass
        else "WIRE_BLOCKED",
        "all_wire_cpu_pass": all_wire_pass,
        "all_local_semantic_checks_pass": semantic["all_pass"],
        "canonical_rejections": sum(
            r["status"] == "REJECTED" for r in rows if r["id"].endswith("-canonical")
        ),
        "wire_cpu_passes": sum(
            r["status"] == "PASS_CPU_ONLY" for r in rows if r["id"].endswith("-wire")
        ),
        "exact_reference_records": len(semantic["rows"]),
        "duplicate_mutants": sum(len(r["duplicate_mutants"]) for r in semantic["rows"]),
        "deferred_constraint_witnesses": sum(
            m["wire_accepts"] for r in semantic["rows"] for m in r["duplicate_mutants"]
        ),
        "model_requests": 0,
        "historical_usage": "UNKNOWN_UNCHANGED",
        "V2_resumed": False,
        "backend_identity_sha256": fingerprint(before_backend),
        "continuation": (
            "Requires separately authorized live diagnostic and historical usage handling"
        ),
    }
    validate(root)
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.root, args.container), ensure_ascii=False))
