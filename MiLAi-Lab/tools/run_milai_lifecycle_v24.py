"""Run frozen lifecycle diagnostics with B1, formation, or reconciliation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from milai_lab.methods.freshness_projection.identity import (
    LAB,
    verify_lifecycle_v24_lock,
    verify_lifecycle_v24_prepared,
)
from milai_lab.methods.memory_lifecycle import (
    FORMATION_CUE,
    FORMATION_PROTOCOL_ID,
    OBSERVATION_PROTOCOL_ID,
    RECONCILIATION_PROTOCOL_ID,
    BusinessObservationRequestView,
    BusinessReconciliationRequestView,
)
from run_milai_ser_v22 import prepare as prepare_diagnostic
from run_milai_ser_v22 import run as run_diagnostic

ARMS = ("b1_control", "f_prospective_retention", "f_observation_retention",
        "r_post_action")


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_diagnostic(
        args, lock_verifier=lambda lock, config: verify_lifecycle_v24_lock(
            lock, config, arm_id=args.arm), method_id="lifecycle_v24")


def run(args: argparse.Namespace) -> dict[str, Any]:
    return run_diagnostic(
        args, prepared_verifier=verify_lifecycle_v24_prepared,
        runtime_prefix=("lifecycle-v24-reconciliation" if args.arm == "r_post_action"
                        else "lifecycle-v24-formation"),
        lock_identity_key="lifecycle_v24_lock_sha256",
        environment_rules=(FORMATION_CUE if args.arm in {
            "f_prospective_retention", "f_observation_retention"} else ""),
        protocol_id=("langmem_default_v1" if args.arm == "b1_control" else
                     OBSERVATION_PROTOCOL_ID if args.arm == "f_observation_retention" else
                     RECONCILIATION_PROTOCOL_ID if args.arm == "r_post_action" else
                     FORMATION_PROTOCOL_ID),
        request_view_factory=(BusinessObservationRequestView
                              if args.arm == "f_observation_retention" else
                              BusinessReconciliationRequestView
                              if args.arm == "r_post_action" else None))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path, default=LAB /
                          "configs/milai-lifecycle-v24-reconciliation-r1.json")
        item.add_argument("--lock", type=Path, default=LAB /
                          "data/locks/milai-lifecycle-v24-reconciliation-r1.lock.json")
        item.add_argument("--diagnostic-inputs", type=Path, default=LAB /
                          "data/diagnostics/milai-lifecycle-v24-reconciliation-r1-inputs.json")
        item.add_argument("--diagnostic-freeze", type=Path, default=LAB /
                          "data/manifests/milai-lifecycle-v24-reconciliation-r1-diagnostic-freeze.json")
        item.add_argument("--input-freeze", "--exposed-freeze", dest="exposed_freeze",
                          type=Path, default=LAB /
                          "data/manifests/milai-lifecycle-v24-reconciliation-r1-input-freeze.json")
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--stage", required=True)
            item.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    args.mode = "diagnostic"
    result = prepare(args) if args.command == "prepare" else run(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
