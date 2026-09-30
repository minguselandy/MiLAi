"""Create a shared E1 stream using actual public tools, without memory/model calls.

This experiment driver extracts literal arguments from the supplied public request.
It is not a memory adapter and does not load an expected answer or scorer. Writers
must consume only the currently observed boundary, never a later boundary/query.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from milai_lab.application.world import ApplicationWorld


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def public_arguments(content: str) -> dict[str, Any]:
    match = re.search(
        # The public fixture uses literal fullwidth punctuation.
        r"物品完整引用是“([^”]+)”，数量(\d+)，目的地“([^”]+)”，包装要求“([^”]+)”",  # noqa: RUF001
        content,
    )
    if match is None:
        raise ValueError("Fixed-flow driver requires the existing literal public request format")
    key, quantity, destination, packing = match.groups()
    return {
        "item_key": key,
        "quantity": int(quantity),
        "destination": destination,
        "packing": packing,
    }


def worker(request_path: Path, world_path: Path, result_path: Path) -> None:
    if result_path.exists():
        raise ValueError("Do not rerun a completed fixed-flow business action")
    request = read(request_path)
    world = ApplicationWorld(world_path, request["initial_label_available"])
    try:
        name = request["tool"]
        if name not in {"reserve_and_label", "get_reservation"}:
            raise ValueError("Fixed-flow tool is not declared")
        receipt = getattr(world, name)(request["owner"], **request["arguments"])
        write(
            result_path,
            {
                "process_id": os.getpid(),
                "original_receipt": receipt,
                "world_snapshot_for_offline_audit_only": world.snapshot(),
            },
        )
    finally:
        world.close()


def build(fixture_path: Path, root: Path) -> dict[str, Any]:
    if root.exists():
        raise ValueError("Use a new fixed-flow root; existing actions must remain unchanged")
    fixture = read(fixture_path)
    root.mkdir(parents=True)
    world_source = Path(sys.modules[ApplicationWorld.__module__].__file__)
    before = sha(world_source)
    streams = []
    for ordinal, case in enumerate(fixture["cases"]):
        if len(case["messages"]) != 2:
            raise ValueError("E1 requires the two predeclared public messages")
        first, second = case["messages"]
        arguments = public_arguments(first["content"])
        if f"“{arguments['item_key']}”" not in second["content"]:
            raise ValueError("Second public request does not reference the actual first object")
        case_root = root / f"case-{ordinal}"
        boundaries = []
        for index, public in enumerate((first, second)):
            request_path = case_root / f"request-{index}.json"
            result_path = case_root / f"result-{index}.json"
            request = {
                "owner": case["owner"],
                "public_message": public,
                "tool": "reserve_and_label" if index == 0 else "get_reservation",
                "arguments": arguments if index == 0 else {"item_key": arguments["item_key"]},
                "initial_label_available": case["initial_world"]["label_available"],
            }
            write(request_path, request)
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(request_path),
                "--world",
                str(case_root / "world.sqlite"),
                "--result",
                str(result_path),
            ]
            # Fixed Python/script paths and JSON file arguments, with no shell.
            result = subprocess.run(  # noqa: S603
                command, text=True, capture_output=True, check=False
            )
            write(
                case_root / f"process-{index}.json",
                {
                    "command": command,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
            if result.returncode:
                raise RuntimeError(f"Fixed public tool process failed: {result.stderr}")
            actual = read(result_path)
            raw = actual["original_receipt"]
            boundaries.append(
                {
                    "index": index,
                    "request_path": str(request_path),
                    "request_sha256": sha(request_path),
                    "result_path": str(result_path),
                    "result_sha256": sha(result_path),
                    "process_id": actual["process_id"],
                    "events": [
                        {
                            "event_key": public["message_id"],
                            "session_id": public["session_id"],
                            "role": "user",
                            "origin": "public_user_message",
                            "content": public["content"],
                            "content_sha256": hashlib.sha256(
                                public["content"].encode()
                            ).hexdigest(),
                        },
                        {
                            "event_key": public["message_id"] + ":actual-public-tool",
                            "session_id": public["session_id"],
                            "role": "tool",
                            "origin": request["tool"],
                            "content": raw,
                            "content_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                        },
                    ],
                }
            )
        assert boundaries[0]["process_id"] != boundaries[1]["process_id"]
        streams.append(
            {
                "case_id": case["case_id"],
                "owner": case["owner"],
                "world_path_for_trusted_adapter_only": str(case_root / "world.sqlite"),
                "boundaries": boundaries,
            }
        )
    if before != sha(world_source):
        raise ValueError("ApplicationWorld source changed during fixed-flow construction")
    artifact = {
        "kind": "V13_2_E1_ACTUAL_PUBLIC_OBSERVED_FLOW",
        "fixture_path": str(fixture_path),
        "fixture_sha256": sha(fixture_path),
        "builder_sha256": sha(Path(__file__)),
        "world_source_sha256": before,
        "streams": streams,
        "runtime_carrier": "events of each currently observed boundary only",
        "excluded_from_model": "world snapshots, case/fault labels and future boundaries",
        "generation_calls": 0,
        "embedding_calls": 0,
        "not_a_free_host_sample": True,
    }
    write(root / "observed-flow.json", artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--world", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if args.worker:
        if not args.world or not args.result:
            parser.error("worker requires world and result")
        worker(args.worker, args.world, args.result)
    else:
        if not args.fixture or not args.output_dir:
            parser.error("build requires fixture and output-dir")
        flow = build(args.fixture.resolve(), args.output_dir.resolve())
        print(json.dumps({"streams": len(flow["streams"]), "generation": 0, "embedding": 0}))


if __name__ == "__main__":
    main()
