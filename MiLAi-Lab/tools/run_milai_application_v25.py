"""Run one frozen, durable LangMem application phase per process."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.freshness_projection.identity import (
    APPLICATION_V25_PROTOCOL,
    LAB,
    verify_application_v25_lock,
    verify_application_v25_prepared,
)
from milai_lab.runners.langmem_application import run_phase
from milai_lab.runners.langmem_application_runtime import open_application_runtime

ARMS = ("b1_control", "a3_exact_refresh", "a4_selective_rebase",
        "a5_rank_bounded_rebase")


def _script(args: argparse.Namespace) -> dict[str, Any]:
    script: dict[str, Any] = read_json(args.script)
    freeze = read_json(args.input_freeze)
    protocol = read_json(APPLICATION_V25_PROTOCOL)
    messages = [item for phase in script["phases"] for item in phase["messages"]]
    order = [{key: item[key] for key in (
        "message_id", "user_id", "session_id", "public_index")}
        for item in messages]
    sessions = {(item["user_id"], item["session_id"]) for item in messages}
    if (script["kind"] != "MILAI_APPLICATION_V25_SCRIPT"
            or freeze["kind"] != "MILAI_APPLICATION_V25_INPUT_FREEZE"
            or (LAB / freeze["script_path"]).resolve() != args.script.resolve()
            or freeze["script_sha256"] != sha256_file(args.script)
            or freeze["script_id"] != script["script_id"]
            or freeze["phases"] != len(script["phases"])
            or freeze["public_messages"] != len(messages)
            or freeze["users"] != len(script["users"])
            or freeze["sessions_per_user"] * len(script["users"]) != len(sessions)
            or freeze["rubric_read_by_runner"] is not False
            or [phase["id"] for phase in script["phases"]] != protocol["phase_order"]
            or order != protocol["public_message_order"]
            or args.arm not in protocol["run_order"]):
        raise ValueError("APPLICATION_V25_SCRIPT_OR_FREEZE_CHANGED")
    return script


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    verify_application_v25_lock(args.lock, args.config, arm_id=args.arm)
    script = _script(args)
    receipt = {"status": "PREPARED_ZERO_MODEL", "method": "application_v25",
               "run_id": args.run, "arm_id": args.arm,
               "lock_sha256": sha256_file(args.lock),
               "config_sha256": sha256_file(args.config),
               "script_sha256": sha256_file(args.script),
               "input_freeze_sha256": sha256_file(args.input_freeze),
               "runtime_root": str(args.runtime_root.resolve()),
               "script_id": script["script_id"],
               "phases": len(script["phases"]),
               "public_messages": sum(len(phase["messages"])
                                      for phase in script["phases"]),
               "rubric_read_by_runner": False}
    write_json(args.output, receipt)
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    lock_sha = verify_application_v25_prepared(
        args.prepared, args.lock, args.config, run_id=args.run, arm_id=args.arm,
        script_path=args.script, input_freeze=args.input_freeze,
        runtime_root=args.runtime_root)
    script = _script(args)
    root = args.runtime_root
    marker_path = root / "runtime-identity.json"
    identity = {"run_id": args.run, "arm_id": args.arm,
                "lock_sha256": lock_sha,
                "config_sha256": sha256_file(args.config),
                "prepared_sha256": sha256_file(args.prepared),
                "script_sha256": sha256_file(args.script),
                "input_freeze_sha256": sha256_file(args.input_freeze)}
    if marker_path.exists():
        if read_json(marker_path) != identity:
            raise ValueError("APPLICATION_V25_RUNTIME_IDENTITY_CHANGED")
    else:
        write_json(marker_path, identity)
    config = read_json(args.config)
    with open_application_runtime(config, args.run, args.arm, root, args.stage) as runtime:
        return run_phase(script, root, args.run, args.arm, args.phase, runtime)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run-phase"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path, default=LAB /
                          "configs/milai-application-v25.json")
        item.add_argument("--lock", type=Path, default=LAB /
                          "data/locks/milai-application-v25.lock.json")
        item.add_argument("--script", type=Path, required=True)
        item.add_argument("--input-freeze", type=Path, required=True)
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--runtime-root", type=Path, required=True)
        if command == "prepare":
            item.add_argument("--output", type=Path, required=True)
        else:
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--phase", type=int, required=True)
            item.add_argument("--stage", required=True)
    args = parser.parse_args()
    result = prepare(args) if args.command == "prepare" else run(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
