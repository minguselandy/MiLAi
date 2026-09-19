"""Complete K3 CPU replay: original references, cold workers and coordinator finish.

No efficiency acceptance gate, retained authority cache, model or real HTTP.
The guarded CLI runs only a fixed externally bound K3 workpoint. Original
business validation and finite deadlines remain; this is not live admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
CASES = Path("/cra/memory/mx_memory/evidence/v0219/f2-wave1-v1/cases")


def _batch(root, binding, authority):
    from v0224_k3_cpu_batch import OfflineBatch

    return OfflineBatch(root, binding, static_authority=authority)


def stop_batch(root, binding, batch, exc):
    from v0220_evidence import sha
    from v0220_provider_hardened import ProviderStop
    from v0222_scoped_cpu_guard import require_cpu_network_guard
    from v0224_k3_cpu_batch import CPU_ROOT, OfflineBatch

    try:
        require_cpu_network_guard()
        if batch is None:
            if (
                root != CPU_ROOT
                or root.resolve() != root
                or sha(root / "execution-binding.json") != binding
            ):
                return
            batch = OfflineBatch.__new__(OfflineBatch)
            batch.root, batch.path, batch.binding_sha = root, root / "batch.sqlite", binding
        batch.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
    except BaseException as secondary:
        exc.add_note("SECONDARY_STOP_FAILURE: " + type(secondary).__name__)


def prepare_references(root, binding, authority):
    from prepare_v0222_presentation_v2 import materialize_references
    from v0222_scoped_cpu_guard import require_cpu_network_guard

    require_cpu_network_guard()
    batch = None
    try:
        batch = _batch(root, binding, authority)
        return materialize_references(batch)
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        raise


def make_mock_transport(batch, episode: str | None = None):
    from v0220_provider_hardened import ProviderStop
    from v0222_http import strict_http_json
    from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard
    from v0222_scoped_cpu_mock import _scripted_transport
    from v0224_k3_cpu_batch import OfflineBatch

    require_cpu_network_guard()
    if (
        type(batch) is not OfflineBatch
        or batch.auth.get("execution_mode") != CPU_MODE
        or batch.auth.get("real_http_allowed") is not False
        or batch.auth.get("mock_cost_is_not_real_cost") is not True
    ):
        raise ProviderStop("EXACT_CPU_BATCH_REQUIRED_FOR_SCRIPTED_TRANSPORT")
    outputs = []
    if episode is not None:
        spec = batch.spec(episode)
        references = [row for row in batch.references(spec["stage"]) if row["episode"] == episode]
        total = 1 if spec["stage"] == "P3" else len(spec["actions"]) + 2
        if [row["turn"] for row in references] != list(range(1, total + 1)):
            raise ProviderStop("CPU_REPLAY_COMPLETE_ORDERED_REFERENCE_OUTPUTS_REQUIRED")
        for row in references:
            path = Path(row["output"])
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != row["hashes"]["output"]:
                raise ProviderStop("CPU_REPLAY_REFERENCE_OUTPUT_DRIFT")
            raw = strict_http_json(data.decode("utf-8"))["raw"]
            if type(raw) is not str:
                raise ProviderStop("CPU_REPLAY_EXACT_RAW_STRING_REQUIRED")
            outputs.append(raw)
    return _scripted_transport(batch.plan["http_identity"], tuple(outputs))


def FullProvider(root, *, batch, episode, world=None):
    from v0222_presentation_provider_v2 import FullProvider as OriginalProvider

    return OriginalProvider(
        root,
        batch=batch,
        episode=episode,
        world=world,
        transport=make_mock_transport(batch, episode),
    )


def run_worker(root: Path, binding: str, episode: str, authority) -> dict:
    from v0218_world import World
    from v0220_evidence import read, save
    from v0220_provider_hardened import ProviderStop
    from v0220_session import PROFILES, Session
    from v0222_scoped_cpu_guard import require_cpu_network_guard

    require_cpu_network_guard()
    batch, provider, failure = None, None, None
    try:
        batch = _batch(root, binding, authority)
        batch.claim(episode)
        spec = batch.spec(episode)
        directory = root / "episodes" / episode
        if spec["stage"] == "P3":
            row = next(r for r in batch.references("P3") if r["episode"] == episode)
            provider = FullProvider(directory / "provider", batch=batch, episode=episode)
            provider.verify()
            raw = provider.generate(episode, read(Path(row["canonical"])))
            result = {
                "status": "VALIDATE_ONLY_PASS",
                "raw": raw,
                "business_dispatches": 0,
                "notebook_writes": 0,
            }
        elif spec["stage"] == "P4":
            if PROFILES["INTENT_ORACLE"]["ORACLE"] != 4:
                raise ProviderStop("FOUR_ROUND_SESSION_CONTRACT_CHANGED")
            public = read(CASES / spec["root"] / "public-initial.json")
            world = World.create(root / "worlds" / (episode + ".sqlite"), spec["scope"], public)
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
            provider = FullProvider(
                directory / "provider", batch=batch, episode=episode, world=world
            )
            result = host.run(provider, deadline=provider.provider.deadline)
            if (
                result.get("status") != "SESSION_FINISHED_NOT_TASK_VERDICT"
                or result.get("close_exception_type")
                or host.adapter.journal.unresolved()
            ):
                raise ProviderStop("PRESENTATION_SESSION_NOT_CLEANLY_FINISHED")
            save(directory / "final-world.json", world.snapshot())
            save(directory / "final-ledger.json", world.ledger())
            result["unresolved_operations"] = []
        else:
            raise ProviderStop("WRONG_PRESENTATION_FULL_STAGE")
        # Close before success persistence; a close failure is never a PASS.
        provider.close()
        batch.admit(episode)
        result["pid"] = os.getpid()
        save(directory / "worker-result.json", result)
        return result
    except BaseException as exc:
        failure = exc
        stop_batch(root, binding, batch, exc)
        raise
    finally:
        if provider is not None:
            try:
                provider.close()
            except BaseException as exc:
                stop_batch(root, binding, batch, exc)
                if failure is None:
                    raise
                failure.add_note("SECONDARY_PROVIDER_CLOSE_FAILURE: " + type(exc).__name__)


def run_child(command, *, timeout, on_failure):
    """Own a fresh process group; preserve primary on all cleanup failures."""
    import signal

    from v0220_provider_hardened import ProviderStop

    started = time.monotonic()
    child = subprocess.Popen(  # noqa: S603 - fixed CLI worker, synthetic tests use local Python
        command,
        cwd=LAB,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except BaseException as primary:
        try:
            on_failure(primary)
        except BaseException as secondary:
            primary.add_note("SECONDARY_STOP_FAILURE: " + repr(secondary))
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except BaseException as secondary:
            primary.add_note("SECONDARY_CHILD_KILL_FAILURE: " + repr(secondary))
        try:
            stdout, stderr = child.communicate(timeout=5)
        except BaseException as secondary:
            primary.add_note("SECONDARY_CHILD_WAIT_FAILURE: " + repr(secondary))
            raise primary from None
        if not isinstance(primary, subprocess.TimeoutExpired):
            raise
        timed_out = True
    if child.returncode != 0:
        on_failure(ProviderStop("PRESENTATION_WORKER_STOPPED"))
    return {
        "pid": child.pid,
        "parent_pid": os.getpid(),
        "returncode": child.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "seconds": time.monotonic() - started,
        "timed_out": timed_out,
    }


def run_stage(
    root: Path, binding: str, stage: str, authority, *, contract_path, contract_sha256
) -> dict:
    from v0220_evidence import save
    from v0220_provider_hardened import ProviderStop
    from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard

    require_cpu_network_guard()
    batch, rows, error = None, [], None
    try:
        if stage not in {"P3", "P4"}:
            raise ProviderStop("ONLY_FULL_VALIDATION_OR_CONDITIONAL_EXECUTION")
        batch = _batch(root, binding, authority)
        batch.launch_once(stage)
        for spec in batch.plan[stage]:
            # One explicit admission; no historical/global reader patching.
            with batch._operation(stage) as (db, _scope, _state):
                deadline = float(
                    db.execute(
                        "SELECT value FROM meta WHERE key=?", (stage + "_deadline",)
                    ).fetchone()[0]
                )
            remaining = min(300.0, deadline - time.time())
            if remaining <= 0:
                raise ProviderStop("BATCH_PHASE_DEADLINE")
            exit_record = run_child(
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
                on_failure=lambda exc: stop_batch(root, binding, batch, exc),
            )
            save(root / "exits" / (spec["id"] + ".json"), exit_record)
            if exit_record["returncode"] != 0 or exit_record["timed_out"]:
                raise ProviderStop("PRESENTATION_WORKER_STOPPED")
            audit = batch.finish(spec["id"])
            if audit["pid"] != exit_record["pid"] or audit["pid"] == os.getpid():
                raise ProviderStop("ACTUAL_COLD_CHILD_PID_NOT_PROVEN")
            rows.append(audit)
        if stage == "P3":
            # This API derives, re-audits and freezes in one scoped operation.
            batch.freeze_p3_gate(root / "P3-gate.json")
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        if batch is None or stage not in {"P3", "P4"} or not isinstance(exc, Exception):
            raise
        error = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
    try:
        snapshot = batch.snapshot()
        result = {
            "status": (
                "CPU_REPLAY_P3_PASS"
                if stage == "P3" and len(rows) == 16 and error is None and not snapshot["stop"]
                else "CPU_REPLAY_P4_PASS"
                if stage == "P4" and len(rows) == 24 and error is None and not snapshot["stop"]
                else "CPU_REPLAY_STAGE_NOT_MET"
            ),
            "execution_mode": CPU_MODE,
            "real_http_requests": 0,
            "real_model_requests": 0,
            "mock_cost_is_not_real_cost": True,
            "model_capability_or_live_admission": False,
            "stage": stage,
            "passed": len(rows),
            "rows": rows,
            "error": error,
            "batch": snapshot,
            "unrun": [s["id"] for s in snapshot["episodes"] if s["status"] == "PENDING"],
            "Memory": "NOT_ADMITTED",
            "Judge": 0,
            "direct_device_calls": 0,
        }
        save(root / (stage + "-result.json"), result)
        return result
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        raise


LIMITS = {
    "http_requests": 0,
    "model_requests": 0,
    "device_calls": 0,
    "concurrency": 1,
    "p3_episodes": 16,
    "p4_episodes": 24,
    "p3_reference_rows": 16,
    "p4_reference_rows": 80,
}


def validate_contract(value):
    from v0220_provider_hardened import ProviderStop
    from v0224_k3_cpu_batch import CPU_ROOT

    def require(ok, reason):
        if not ok:
            raise ProviderStop(reason)

    def digest(value):
        return (
            type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
        )

    def path(value):
        return (
            type(value) is str
            and Path(value).is_absolute()
            and ".." not in Path(value).parts
            and str(Path(value)) == value
            and Path(value).resolve() == Path(value)
        )

    require(
        type(value) is dict
        and set(value)
        == {
            "status",
            "execution_revision",
            "root",
            "binding_sha256",
            "static_authority",
            "files",
            "priority_policy",
            "limits",
        },
        "EXACT_K3_FUNCTIONAL_CONTRACT_REQUIRED",
    )
    require(
        value["status"] == "V0224_K3_FUNCTIONAL_FROZEN"
        and value["execution_revision"] == "V0224_K3_COMPLETION_PRIORITY_01",
        "FROZEN_K3_REVISION_REQUIRED",
    )
    require(value["root"] == str(CPU_ROOT) and path(value["root"]), "FIXED_K3_ROOT_REQUIRED")
    require(
        type(value["limits"]) is dict
        and set(value["limits"]) == set(LIMITS)
        and all(
            type(value["limits"][k]) is int and value["limits"][k] == v for k, v in LIMITS.items()
        ),
        "EXACT_FULL_CPU_MATRIX_LIMITS_REQUIRED",
    )
    files = value["files"]
    require(
        type(files) is dict
        and bool(files)
        and all(path(p) and digest(d) for p, d in files.items()),
        "EXACT_EXTERNAL_FILE_PINS_REQUIRED",
    )
    require(
        digest(value["binding_sha256"])
        and files.get(str(CPU_ROOT / "execution-binding.json")) == value["binding_sha256"],
        "EXTERNAL_K3_BINDING_REQUIRED",
    )
    require(
        not {str(CPU_ROOT / ("batch.sqlite" + suffix)) for suffix in ("", "-wal", "-shm")}
        & set(files),
        "MUTABLE_COORDINATOR_MUST_NOT_BE_FILE_PINNED",
    )
    policy = value["priority_policy"]
    require(
        type(policy) is dict
        and set(policy) == {"path", "sha256"}
        and path(policy["path"])
        and digest(policy["sha256"])
        and files.get(policy["path"]) == policy["sha256"],
        "EXTERNAL_PRIORITY_POLICY_REQUIRED",
    )
    authority = value["static_authority"]
    require(
        type(authority) is dict
        and set(authority)
        == {"bundle_path", "bundle_sha256", "receipt_path", "receipt_sha256", "limits"},
        "EXACT_STATIC_AUTHORITY_REQUIRED",
    )
    for kind in ("bundle", "receipt"):
        require(
            path(authority[kind + "_path"])
            and digest(authority[kind + "_sha256"])
            and files.get(authority[kind + "_path"]) == authority[kind + "_sha256"],
            "EXTERNAL_STATIC_AUTHORITY_PINS_REQUIRED",
        )
    require(
        authority["bundle_path"] != authority["receipt_path"], "DISTINCT_AUTHORITY_FILES_REQUIRED"
    )
    limits = authority["limits"]
    require(
        type(limits) is dict
        and set(limits) == {"max_header_bytes", "max_payload_bytes", "max_paths", "max_blobs"}
        and all(type(v) is int and v > 0 for v in limits.values()),
        "EXACT_BUNDLE_LIMITS_REQUIRED",
    )
    return value


def load_contract(contract_path, contract_sha256):
    """Full physical first/close external pins, no expected value discovery."""
    from v0220_evidence import dependencies
    from v0220_provider_hardened import ProviderStop
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_scoped_cpu_guard import require_cpu_network_guard
    from v0224_k3_cpu_batch import StaticAuthority
    from v0224_static_bundle import BundleLimits

    require_cpu_network_guard()
    contract_path = Path(contract_path)
    if (
        not contract_path.is_absolute()
        or contract_path.resolve() != contract_path
        or ".." in contract_path.parts
    ):
        raise ProviderStop("CANONICAL_EXTERNAL_CONTRACT_REQUIRED")
    with AdmissionReadScope() as scope:
        value = validate_contract(scope.read_json(contract_path, contract_sha256))
        for source in dependencies([Path(__file__).resolve()]):
            if str(source) not in value["files"]:
                raise ProviderStop("COMPLETE_EXECUTING_SOURCE_PINS_REQUIRED")
        for name, digest in value["files"].items():
            scope.read_bytes(Path(name), digest)
    spec = value["static_authority"]
    authority = StaticAuthority(
        bundle_path=Path(spec["bundle_path"]),
        bundle_sha256=spec["bundle_sha256"],
        receipt_path=Path(spec["receipt_path"]),
        receipt_sha256=spec["receipt_sha256"],
        limits=BundleLimits(**spec["limits"]),
    )
    return value, authority


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    import threading

    from v0220_provider_hardened import ProviderStop
    from v0223_transaction_primary_fix import installed_transaction_fix

    if sys.getprofile() is not None or sys.gettrace() is not None or threading.active_count() != 1:
        raise ProviderStop("UNPROFILED_SINGLE_THREAD_CPU_REQUIRED")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("references", "stage", "worker"))
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"))
    parser.add_argument("--episode")
    args = parser.parse_args()
    if (args.mode == "stage") != (args.stage is not None) or (args.mode == "worker") != (
        args.episode is not None
    ):
        parser.error("stage requires only --stage; worker requires only --episode")
    contract, authority = load_contract(args.contract_path, args.contract_sha256)
    root, binding = Path(contract["root"]), contract["binding_sha256"]
    with installed_transaction_fix():
        if args.mode == "references":
            result = prepare_references(root, binding, authority)
            passed = result["status"] == "REFERENCE_PREPARATION_PASS"
        elif args.mode == "stage":
            result = run_stage(
                root,
                binding,
                args.stage,
                authority,
                contract_path=args.contract_path,
                contract_sha256=args.contract_sha256,
            )
            passed = result["status"] == "CPU_REPLAY_" + args.stage + "_PASS"
        else:
            result = run_worker(root, binding, args.episode, authority)
            passed = True
        try:
            final_contract, _ = load_contract(args.contract_path, args.contract_sha256)
            if final_contract != contract:
                raise ProviderStop("EXTERNAL_CONTRACT_DRIFT")
        except BaseException as exc:
            stop_batch(root, binding, None, exc)
            raise
    print(
        json.dumps(
            {
                "mode": args.mode,
                "status": result["status"],
                "pid": os.getpid(),
                "functional_pass": passed,
                "efficiency_gate": "NOT_APPLIED_BY_USER_PRIORITY",
                "live_admitted": False,
            }
        ),
        flush=True,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
