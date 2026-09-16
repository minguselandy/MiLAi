"""Cold D1/D2 execution and accounting; business qualification is offline."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from run_v0224_live_completion import run_child
from v0218_world import World, digest
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0224_natural_session import NaturalSession
from v0224_recovery_session import RecoverySession
from v0224_static_bundle import BundleLimits
from v0224_task_batch import ROOTS, Batch, require
from v0224_task_provider import TaskProvider
from v0224_verified_digest_batch import StaticAuthority

# An ordinary wrong action or exhausted generation budget remains a scored outcome.
CLEAN_TERMINALS = frozenset(
    {"SESSION_FINISHED_NOT_TASK_VERDICT", "PROTOCOL_REJECTION_STOP", "GENERATION_LIMIT"}
)


def load_batch(contract_path, contract_sha256):
    path = Path(contract_path)
    require(path in {root / "contract.json" for root in ROOTS.values()}, "FIXED_TASK_CONTRACT_PATH")
    require(path.resolve() == path and sha(path) == contract_sha256, "EXTERNAL_TASK_CONTRACT_DRIFT")
    contract = read(path)
    value = contract["static_authority"]
    authority = StaticAuthority(
        Path(value["bundle_path"]),
        value["bundle_sha256"],
        Path(value["receipt_path"]),
        value["receipt_sha256"],
        BundleLimits(**value["limits"]),
    )
    # Batch independently reads the exact external digest, all authority and fresh inputs.
    return Batch(path.parent, contract_sha256, static_authority=authority)


def stop(batch, primary):
    try:
        batch.stop(str(primary) if isinstance(primary, ProviderStop) else type(primary).__name__)
    except BaseException as secondary:
        primary.add_note("SECONDARY_TASK_STOP_FAILURE: " + type(secondary).__name__)


def run_worker(batch, episode):
    provider, failure = None, None
    try:
        batch.claim(episode)
        spec = batch.spec(episode)
        directory = batch.root / "episodes" / episode
        source = Path(spec["public_source"]["path"])
        require(sha(source) == spec["public_source"]["sha256"], "PUBLIC_TASK_SOURCE_DRIFT")
        world_path = batch.root / "worlds" / (episode + ".sqlite")
        require(not world_path.exists(), "FRESH_TASK_WORLD_REQUIRED")
        world = World.create(world_path, spec["scope"], read(source))
        require(
            digest(world.snapshot()) == spec["initial_state_sha256"], "INITIAL_TASK_WORLD_DRIFT"
        )
        initial_world = world.snapshot()
        args = {
            "episode_id": episode,
            "profile": spec["profile"],
            "arm": spec["arm"],
            "validate_binding": lambda: batch.admit(episode),
        }
        if spec["stage"] == "D1":
            host = RecoverySession(
                world, directory, **args, intent=spec["intent"], event=spec["event"]
            )
        else:
            host = NaturalSession(world, directory, **args)
        save(directory / "initial-world.json", initial_world)
        provider = TaskProvider(directory / "provider", batch=batch, episode=episode)
        result = host.run(provider, deadline=provider.provider.deadline)
        require(
            result.get("status") in CLEAN_TERMINALS
            and not result.get("close_exception_type")
            and not host.adapter.journal.unresolved(),
            "TASK_EXECUTION_OR_ACCOUNTING_NOT_CLEAN",
        )
        provider.close()
        batch.admit(episode)
        save(directory / "final-world.json", world.snapshot())
        save(directory / "final-ledger.json", world.ledger())
        result.update(
            pid=os.getpid(),
            execution_status="EXECUTION_COMPLETE",
            unresolved_operations=[],
            task_correctness="NOT_EVALUATED",
            files={str(path): sha(path) for path in sorted(directory.rglob("*")) if path.is_file()},
        )
        save(directory / "worker-result.json", result)
        return result
    except BaseException as primary:
        failure = primary
        stop(batch, primary)
        raise
    finally:
        if provider is not None:
            try:
                provider.close()
            except BaseException as secondary:
                stop(batch, secondary)
                if failure is None:
                    raise
                failure.add_note(
                    "SECONDARY_TASK_PROVIDER_CLOSE_FAILURE: " + type(secondary).__name__
                )


def run_stage(batch, contract_path, contract_sha256):
    rows = []
    try:
        batch.launch_once(batch.stage)
        for spec in batch.plan[batch.stage]:
            batch.authorize(batch.stage)
            remaining = min(
                batch.auth["episode_wall_seconds"], batch.auth["expires_unix"] - time.time()
            )
            require(remaining > 0, "TASK_AUTHORIZATION_EXPIRED")
            terminal = run_child(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "worker",
                    "--contract-path",
                    str(contract_path),
                    "--contract-sha256",
                    contract_sha256,
                    "--episode",
                    spec["id"],
                ],
                timeout=remaining,
                on_failure=lambda exc: stop(batch, exc),
            )
            path = batch.root / "exits" / (spec["id"] + ".json")
            save(path, terminal)
            require(
                terminal["returncode"] == 0 and not terminal["timed_out"], "TASK_COLD_EXIT_FAILED"
            )
            rows.append(batch.finish(spec["id"], path, sha(path)))
        snapshot = batch.snapshot()
        require(
            len(rows) == len(batch.plan[batch.stage])
            and all(row["status"] == "EXECUTION_COMPLETE" for row in snapshot["episodes"]),
            "COMPLETE_FROZEN_TASK_MATRIX_REQUIRED",
        )
        result = {
            "status": "TASK_MATRIX_EXECUTION_COMPLETE_OFFLINE_QUALIFICATION_REQUIRED",
            "stage": batch.stage,
            "pid": os.getpid(),
            "rows": rows,
            "batch": snapshot,
            "task_correctness": "NOT_EVALUATED",
            "direct_device_calls": 0,
        }
        save(batch.root / "stage-result.json", result)
        return result
    except BaseException as primary:
        stop(batch, primary)
        try:
            save(
                batch.root / "stage-failure.json",
                {
                    "status": "TASK_STAGE_STOPPED",
                    "completed": rows,
                    "exception_type": type(primary).__name__,
                },
            )
        except BaseException as secondary:
            primary.add_note("SECONDARY_TASK_REPORT_FAILURE: " + type(secondary).__name__)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "worker"))
    parser.add_argument("--contract-path", required=True, type=Path)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--episode")
    args = parser.parse_args()
    if (args.mode == "worker") != (args.episode is not None):
        parser.error("episode required exactly for worker")
    batch = load_batch(args.contract_path, args.contract_sha256)
    result = (
        run_worker(batch, args.episode)
        if args.mode == "worker"
        else run_stage(batch, args.contract_path, args.contract_sha256)
    )
    print(json.dumps({"status": result["status"], "pid": os.getpid()}))


if __name__ == "__main__":
    main()
