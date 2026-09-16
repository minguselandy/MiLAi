"""Full, unchanged public-schema CPU preflight. Not an end-to-end model admission."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from v0213_provider import payload
from v0220_action_contract import ActionContract
from v0220_evidence import LAB, read, save, seal, sha, validate


def keyword_paths(value: object, keyword: str, path: str = "") -> list[str]:
    """Inventory schema keywords, not identically named properties or literal data."""
    if not isinstance(value, dict):
        return []
    found = [path + "/" + keyword] if keyword in value else []
    for key in ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas"):
        for name, child in value.get(key, {}).items():
            escaped = name.replace("~", "~0").replace("/", "~1")
            found.extend(keyword_paths(child, keyword, path + "/" + key + "/" + escaped))
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for i, child in enumerate(value.get(key, [])):
            found.extend(keyword_paths(child, keyword, path + f"/{key}/{i}"))
    for key in ("items", "additionalProperties", "contains", "not", "if", "then", "else"):
        found.extend(keyword_paths(value.get(key), keyword, path + "/" + key))
    return found


def run(source: Path, root: Path) -> dict:
    validate(source)
    original = read(source / "manifest.json")
    roots = list(dict.fromkeys(row["root"] for row in original["contract"]["episodes"]))
    if len(roots) != 4:
        raise ValueError("ORIGINAL_FOUR_ROOTS_REQUIRED")
    old = Path("/cra/memory/mx_memory/evidence/v0219/f2-wave1-v1")
    inputs = [old / "cases" / key / "public-initial.json" for key in roots]
    script = LAB / "tools/v0220_provider_cpu_probe_v3.py"
    seal(
        root,
        entries=[Path(__file__), script],
        inputs=[source / "manifest.json", *inputs],
        contract={
            "stage": "FULL_UNCHANGED_SCHEMA_CPU_PREFLIGHT",
            "roots": roots,
            "model_requests": 0,
            "no_schema_lowering_or_target_filtering": True,
            "no_V2_resumption": True,
            "scope": "Actual installed parameter validation; not GPU decoding/usage evidence",
        },
    )
    requests, inventory = [], []
    for key, path in zip(roots, inputs, strict=True):
        contract = ActionContract.from_public(read(path))
        for finish_only in (False, True):
            schema = contract.action_schema(finish_only=finish_only)
            identity = key + ("-finish" if finish_only else "-full")
            body = payload(
                [{"role": "user", "content": "CPU validation only; do not generate."}], schema
            )
            save(root / "requests" / f"{identity}.json", body)
            requests.append({"id": identity, "body": body})
            inventory.append(
                {
                    "id": identity,
                    "root": key,
                    "finish_only": finish_only,
                    "targets": sorted(contract.read_schemas),
                    "branches": len(schema["anyOf"]),
                    "uniqueItems_paths": keyword_paths(schema, "uniqueItems"),
                    "request_sha256": sha(root / "requests" / f"{identity}.json"),
                }
            )
    save(root / "inventory.json", inventory)
    batch = (
        "import sys,json,asyncio\n"
        "data=json.load(sys.stdin); namespace={'__name__':'cpu_probe_module'}\n"
        "exec(compile(data['script'],'cpu_probe_v3.py','exec'),namespace)\n"
        "rows=[]\n"
        "for item in data['requests']:\n"
        " value=asyncio.run(namespace['probe'](item['body']))\n"
        " value.pop('sources'); rows.append({'id':item['id'],**value})\n"
        "print(json.dumps(rows))\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed installed CPU diagnostic, no engine
        ["/usr/bin/docker", "exec", "-i", "bcec1ef46198", "python3", "-c", batch],
        input=json.dumps({"script": script.read_text(), "requests": requests}),
        capture_output=True,
        text=True,
        timeout=45,
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
        raise ValueError("FULL_SCHEMA_CPU_PROCESS_FAILED")
    rows = json.loads(completed.stdout.splitlines()[-1])
    save(root / "probes.json", rows)
    for row in rows:
        counts, observed = row["counts"], row["observed"]
        if counts["input_validation_entered"] != 1 or counts["engine_submissions"] != 0:
            raise ValueError("CPU_PROBE_BOUNDARY_FAILURE")
        passed = counts["post_validation_reached"] == 1 and (
            observed["cause_message"] == "CPU_PROBE_STOP_AFTER_PARAMETER_VALIDATION_NO_ENGINE"
        )
        row["validation_status"] = "PASS_CPU_ONLY" if passed else "REJECTED"
    result = {
        "status": "COMPATIBILITY_CHECK_COMPLETED_NOT_V2_ADMITTED",
        "rows": [
            {
                "id": r["id"],
                "status": r["validation_status"],
                "cause_type": r["observed"]["cause_type"],
                "cause_message": r["observed"]["cause_message"],
            }
            for r in rows
        ],
        "model_requests": 0,
        "unchanged_public_contract": True,
        "V2_decision": "DO_NOT_RESUME: all full schemas must pass before any live admission",
        "live_generation_compatibility": "NOT_TESTED",
    }
    validate(root)
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.root)
