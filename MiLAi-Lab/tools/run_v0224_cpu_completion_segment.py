"""Finish the missing frozen P4 positions in a separately bound CPU-only segment."""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def require(ok, why):
    if not ok:
        from v0220_provider_hardened import ProviderStop

        raise ProviderStop(why)


def stop(batch, primary):
    from v0220_provider_hardened import ProviderStop

    try:
        batch.stop(str(primary) if isinstance(primary, ProviderStop) else type(primary).__name__)
    except BaseException as secondary:
        primary.add_note("SECONDARY_SEGMENT_STOP_FAILURE: " + type(secondary).__name__)


def make_mock_transport(batch, episode):
    from v0222_http import strict_http_json
    from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard
    from v0222_scoped_cpu_mock import _scripted_transport
    from v0224_cpu_completion_segment import Batch

    require_cpu_network_guard()
    require(
        type(batch) is Batch
        and batch.auth["execution_mode"] == CPU_MODE
        and batch.auth["real_http_allowed"] is False
        and batch.auth["mock_cost_is_not_real_cost"] is True,
        "EXACT_CPU_SEGMENT_REQUIRED_FOR_SCRIPTED_TRANSPORT",
    )
    spec = batch.spec(episode)
    references = [row for row in batch.references("P4") if row["episode"] == episode]
    require(
        [row["turn"] for row in references] == list(range(1, len(spec["actions"]) + 3)),
        "COMPLETE_UNCHANGED_REFERENCE_OUTPUTS_REQUIRED",
    )
    outputs = []
    for row in references:
        raw = Path(row["output"]).read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == row["hashes"]["output"], "REFERENCE_OUTPUT_DRIFT"
        )
        value = strict_http_json(raw.decode())["raw"]
        require(type(value) is str, "EXACT_REFERENCE_RAW_STRING_REQUIRED")
        outputs.append(value)
    return _scripted_transport(batch.plan["http_identity"], tuple(outputs))


def run_worker(batch, episode):
    from prepare_v0221_http_v2 import CASES
    from v0218_world import World
    from v0220_evidence import read, save
    from v0220_session import PROFILES, Session
    from v0222_presentation_provider_v2 import FullProvider
    from v0222_scoped_cpu_guard import require_cpu_network_guard

    require_cpu_network_guard()
    provider, failure = None, None
    try:
        batch.claim(episode)
        spec = batch.spec(episode)
        require(spec["stage"] == "P4", "ONLY_MISSING_P4_POSITION_ALLOWED")
        require(PROFILES["INTENT_ORACLE"]["ORACLE"] == 4, "FOUR_ROUND_CONTRACT_CHANGED")
        directory = batch.root / "episodes" / episode
        public = read(CASES / spec["root"] / "public-initial.json")
        world = World.create(batch.root / "worlds" / (episode + ".sqlite"), spec["scope"], public)
        host = Session(
            world,
            directory,
            episode_id=episode,
            profile="INTENT_ORACLE",
            arm="ORACLE",
            intent=spec["intent"],
            validate_binding=lambda: batch.admit(episode),
        )
        save(directory / "initial-world.json", world.snapshot())
        transport = make_mock_transport(batch, episode)
        try:
            provider = FullProvider(
                directory / "provider",
                batch=batch,
                episode=episode,
                world=world,
                transport=transport,
            )
        except BaseException as primary:
            try:
                transport.close()
            except BaseException as secondary:
                primary.add_note("SECONDARY_MOCK_CLOSE_FAILURE: " + type(secondary).__name__)
            raise
        result = host.run(provider, deadline=provider.provider.deadline)
        require(
            result.get("status") == "SESSION_FINISHED_NOT_TASK_VERDICT"
            and not result.get("close_exception_type")
            and not host.adapter.journal.unresolved(),
            "ORIGINAL_SESSION_MUST_FINISH_CLEANLY",
        )
        save(directory / "final-world.json", world.snapshot())
        save(directory / "final-ledger.json", world.ledger())
        provider.close()
        batch.admit(episode)
        result.update(pid=os.getpid(), unresolved_operations=[])
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
                failure.add_note("SECONDARY_PROVIDER_CLOSE_FAILURE: " + type(secondary).__name__)


def run_stage(batch, contract_path, contract_sha256):
    from run_v0224_live_completion import run_child
    from v0220_evidence import save

    rows = []
    try:
        batch.launch_once("P4")
        specs = batch.plan["P4"]
        require(len(specs) == 16, "EXACT_MISSING_SIXTEEN_POSITIONS")
        for spec in specs:
            batch.authorize("P4")
            remaining = min(3600, batch.auth["expires_unix"] - time.time())
            require(remaining > 0, "SEGMENT_AUTHORIZATION_EXPIRED")
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
            save(batch.root / "exits" / (spec["id"] + ".json"), terminal)
            require(
                terminal["returncode"] == 0 and not terminal["timed_out"],
                "ACTUAL_CLEAN_COLD_SEGMENT_EXIT_REQUIRED",
            )
            audit = batch.finish(spec["id"])
            require(audit["pid"] == terminal["pid"], "ACTUAL_COLD_PID_BINDING_REQUIRED")
            rows.append(audit)
        snapshot = batch.snapshot()
        require(
            len(snapshot["episodes"]) == 16
            and all(row["status"] == "PASS" for row in snapshot["episodes"])
            and not snapshot["stop"],
            "FULL_SEGMENT_PARENT_FINISH_REQUIRED",
        )
        result = {
            "status": "CPU_COMPLETION_SEGMENT_P4_PASS",
            "pid": os.getpid(),
            "rows": rows,
            "batch": snapshot,
            "real_model_requests": 0,
            "real_http_requests": 0,
            "direct_device_calls": 0,
            "mock_cost_is_not_real_cost": True,
            "gate_a": "SEPARATE_COMPOSED_AUDIT_REQUIRED",
        }
        save(batch.root / "stage-result.json", result)
        return result
    except BaseException as primary:
        stop(batch, primary)
        try:
            save(
                batch.root / "stage-failure.json",
                {
                    "status": "CPU_SEGMENT_STOPPED",
                    "completed": rows,
                    "exception_type": type(primary).__name__,
                },
            )
        except BaseException as secondary:
            primary.add_note("SECONDARY_STAGE_REPORT_FAILURE: " + type(secondary).__name__)
        raise


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0220_evidence import dependencies
    from v0222_admission_read_scope import AdmissionReadScope
    from v0223_transaction_primary_fix import installed_transaction_fix
    from v0224_cpu_completion_segment import load_batch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "worker"))
    parser.add_argument("--contract-path", required=True, type=Path)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--episode")
    args = parser.parse_args()
    if (args.mode == "worker") != (args.episode is not None):
        parser.error("episode required exactly for worker")
    with installed_transaction_fix():
        contract, batch = load_batch(args.contract_path, args.contract_sha256)
        require(
            set(map(str, dependencies([Path(__file__).resolve()]))).issubset(contract["files"]),
            "COMPLETE_EXECUTING_RUNNER_SOURCE_PINS_REQUIRED",
        )
        result = (
            run_worker(batch, args.episode)
            if args.mode == "worker"
            else run_stage(batch, args.contract_path, args.contract_sha256)
        )
        try:
            batch.authorize("PREP")
            with AdmissionReadScope() as scope:
                require(
                    scope.read_json(args.contract_path, args.contract_sha256) == contract,
                    "EXTERNAL_SEGMENT_CONTRACT_DRIFT",
                )
                for name, expected in contract["files"].items():
                    scope.read_bytes(Path(name), expected)
        except BaseException as primary:
            stop(batch, primary)
            raise
    print(json.dumps({"status": result["status"], "pid": os.getpid()}), flush=True)


if __name__ == "__main__":
    main()
