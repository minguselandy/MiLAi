"""Prospective full B/C live execution; no service request on import.

Original full acceptance, 16/24 cold workers and parent finish/gates. Every
execution requires a new externally pinned contract and actual functional A.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

LAB = Path("/cra/memory/mx_memory/MiLAi-Lab")
CASES = Path("/cra/memory/mx_memory/evidence/v0219/f2-wave1-v1/cases")


@dataclass(frozen=True)
class LiveAuthority:
    static: object
    gate_a_path: Path
    gate_a_sha256: str


def _batch(root, binding, authority):
    from v0224_live_completion_batch import Batch

    return Batch(
        root,
        binding,
        static_authority=authority.static,
        gate_a_path=authority.gate_a_path,
        gate_a_sha256=authority.gate_a_sha256,
    )


def FullProvider(root, *, batch, episode, world=None):
    from v0222_presentation_provider_v2 import FullProvider as OriginalProvider
    from v0224_live_http import BoundedLiveHTTP

    count = 1 if batch.spec(episode)["stage"] == "P3" else 4
    transport = BoundedLiveHTTP(identity_get=2, tokenize_post=count, generation_post=count)
    try:
        return OriginalProvider(
            root, batch=batch, episode=episode, world=world, transport=transport
        )
    except BaseException as primary:
        try:
            transport.close()
        except BaseException as secondary:
            primary.add_note("SECONDARY_TRANSPORT_CLOSE_FAILURE: " + type(secondary).__name__)
        raise


def stop_batch(root, binding, batch, exc):
    from v0220_evidence import sha
    from v0220_provider_hardened import ProviderStop
    from v0224_live_completion_batch import ROOT as CPU_ROOT
    from v0224_live_completion_batch import Batch as OfflineBatch

    try:
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

    batch = None
    try:
        batch = _batch(root, binding, authority)
        return materialize_references(batch)
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        raise


def run_worker(root: Path, binding: str, episode: str, authority) -> dict:
    from v0218_world import World
    from v0220_evidence import read, save
    from v0220_provider_hardened import ProviderStop
    from v0220_session import PROFILES, Session

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
    from v0224_live_completion_batch import LIVE_MODE

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
                "LIVE_P3_PASS"
                if stage == "P3" and len(rows) == 16 and error is None and not snapshot["stop"]
                else "LIVE_P4_PASS"
                if stage == "P4" and len(rows) == 24 and error is None and not snapshot["stop"]
                else "LIVE_STAGE_NOT_MET"
            ),
            "execution_mode": LIVE_MODE,
            "http_accounting": "ACTUAL_RAW_RECEIPTS_AND_MIRRORED_LEDGERS",
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


def preflight(root: Path, binding: str, stage: str, *, authority) -> dict:

    import httpx

    from preflight_v0222_presentation import PREFLIGHT_SECONDS, RECEIPT_COUNTS, REFERENCE_COUNTS
    from preflight_v0222_presentation_v2 import admit_preflight
    from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
    from v0220_evidence import save, sha
    from v0220_provider_hardened import ProviderStop
    from v0220_wire_contract import encoded
    from v0222_http import bounded_request, strict_http_json
    from v0222_presentation_audit import validate_reference
    from v0222_presentation_http_v2 import identity, owned_timeout
    from v0224_live_http import BoundedLiveHTTP

    preflight_started = time.monotonic()
    batch = None

    def fail(exc):
        stop_batch(root, binding, batch, exc)
        return str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__

    def persist(path, value):
        try:
            save(path, value)
        except BaseException as exc:
            fail(exc)
            raise

    try:
        if stage not in PREFLIGHT_SECONDS:
            raise ProviderStop("PRESENTATION_PREFLIGHT_STAGE_REQUIRED")
        batch = _batch(root, binding, authority)
        transport = BoundedLiveHTTP(
            identity_get=4, tokenize_post=2 * REFERENCE_COUNTS[stage], generation_post=0
        )
        directory = batch.root / (stage + "-preflight")
        deadline = time.monotonic() + (batch.auth["expires_unix"] - time.time())

        def admit_http():
            return admit_preflight(batch, stage, deadline)

        admit_http()
        references = batch.references(stage)
        positions = [
            (spec["id"], turn)
            for spec in batch.plan[stage]
            for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3)
        ]
        if (
            len(references) != REFERENCE_COUNTS[stage]
            or [(ref["episode"], ref["turn"]) for ref in references] != positions
        ):
            raise ProviderStop("COMPLETE_ORDERED_STAGE_REFERENCES_REQUIRED")
        directory.mkdir(exist_ok=False)
    except BaseException as exc:
        fail(exc)
        raise

    rows, calls, reason = [], [], None
    try:
        with httpx.Client(
            base_url=ENDPOINT,
            transport=transport,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            initial_identity = identity(
                client, directory / "identity-start", admit=admit_http, on_failure=fail
            )
            if initial_identity != batch.plan["http_identity"]:
                raise ProviderStop("HTTP_IDENTITY_DRIFT")
            for ref in references:
                _, _, wire, raw = validate_reference(batch, ref, batch.spec(ref["episode"]))
                counts = {}
                for kind, body in (
                    ("input", {key: wire[key] for key in TOKENIZE_KEYS}),
                    ("output", {"model": MODEL, "prompt": raw, "add_special_tokens": False}),
                ):
                    stem = directory / f"{ref['episode']}-{ref['turn']:02d}-{kind}"
                    attempt = {
                        "episode": ref["episode"],
                        "turn": ref["turn"],
                        "kind": kind,
                        "method": "POST",
                        "route": "/tokenize",
                    }
                    content = encoded(body).encode()
                    persist(stem.with_suffix(".request.json"), body)
                    persist(stem.with_suffix(".attempt.json"), attempt)
                    claim = admit_http()
                    timeout = owned_timeout(claim, 5)
                    calls.append(attempt)
                    http_started = time.monotonic()
                    try:
                        response = bounded_request(
                            client,
                            "POST",
                            "/tokenize",
                            content=content,
                            headers={"Content-Type": "application/json"},
                            timeout=timeout,
                        )
                    except BaseException as exc:
                        fail(exc)
                        try:
                            persist(
                                stem.with_suffix(".error.json"),
                                {
                                    "exception_type": type(exc).__name__,
                                    "seconds": time.monotonic() - http_started,
                                },
                            )
                        except BaseException as secondary:
                            exc.add_note(
                                "SECONDARY_HTTP_REPORT_FAILURE: " + type(secondary).__name__
                            )
                        raise
                    persist(
                        stem.with_suffix(".http.json"),
                        {
                            "status_code": response.status_code,
                            "body": response.text,
                            "seconds": time.monotonic() - http_started,
                        },
                    )
                    if response.status_code != 200:
                        raise ProviderStop("TOKENIZE_REQUIRES_HTTP_200")
                    count = strict_http_json(response.text)["count"]
                    if type(count) is not int or count < 0:
                        raise ProviderStop("INVALID_TOKENIZE_COUNT")
                    counts[kind] = count
                if counts["input"] + 4096 > 65536 or counts["output"] + 1 > 4096:
                    raise ProviderStop("COMPLETE_INPUT_OR_OUTPUT_CAPACITY_NOT_MET")
                rows.append(
                    {
                        "episode": ref["episode"],
                        "turn": ref["turn"],
                        "counts": counts,
                        "reference_hashes": ref["hashes"],
                    }
                )
                print(f"capacity {stage} {len(rows)}/{len(references)} {counts}", flush=True)
            if (
                identity(client, directory / "identity-final", admit=admit_http, on_failure=fail)
                != initial_identity
            ):
                raise ProviderStop("HTTP_IDENTITY_DRIFT")
            admit_http()
    except Exception as exc:
        reason = fail(exc)
    except BaseException as exc:
        fail(exc)
        raise

    try:
        files = {str(path): sha(path) for path in sorted(directory.rglob("*.json"))}
        if reason is None and len(files) != RECEIPT_COUNTS[stage]:
            raise ProviderStop("EXACT_COMPLETE_PREFLIGHT_RECEIPTS_REQUIRED")
        result = {
            "status": "G_PREFLIGHT_PASS" if reason is None else "NOT_MET",
            "stage": stage,
            "selected_condition": "B1",
            "selected_decoder": "D11",
            "rows": rows,
            "tokenize_calls": calls,
            "reason": reason,
            "model_requests": 0,
            "direct_device_calls": 0,
            "historical_preflight_window_seconds": PREFLIGHT_SECONDS[stage],
            "cpu_efficiency_window_enforced": False,
            "authorization_expires_unix": batch.auth["expires_unix"],
            "elapsed_before_report_seconds": time.monotonic() - preflight_started,
            "files": files,
        }
        persist(directory / "result.json", result)
        if reason is None:
            admit_http()
            batch.freeze_artifact(
                stage + "_preflight", directory / "result.json", "G_PREFLIGHT_PASS"
            )
            admit_http()
        return result
    except BaseException as exc:
        fail(exc)
        raise


LIMITS = {
    "http_requests": 504,
    "model_requests": 112,
    "device_calls": 0,
    "identity_get": 88,
    "tokenize_post": 304,
    "concurrency": 1,
    "p3_episodes": 16,
    "p4_episodes": 24,
    "p3_reference_rows": 16,
    "p4_reference_rows": 80,
}


def validate_contract(value):
    from v0220_provider_hardened import ProviderStop
    from v0224_live_completion_batch import ROOT as CPU_ROOT

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
            "gate_a",
            "limits",
        },
        "EXACT_K3_FUNCTIONAL_CONTRACT_REQUIRED",
    )
    require(
        value["status"] == "V0224_BC_LIVE_FROZEN"
        and value["execution_revision"] == "V0224_BC_LIVE_COMPLETION_01",
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
    gate_a = value["gate_a"]
    require(
        type(gate_a) is dict
        and set(gate_a) == {"path", "sha256"}
        and path(gate_a["path"])
        and digest(gate_a["sha256"])
        and files.get(gate_a["path"]) == gate_a["sha256"],
        "EXTERNAL_FUNCTIONAL_GATE_A_REQUIRED",
    )
    return value


def load_contract(contract_path, contract_sha256):
    """Full physical first/close external pins, no expected value discovery."""
    from v0220_evidence import dependencies
    from v0220_provider_hardened import ProviderStop
    from v0222_admission_read_scope import AdmissionReadScope
    from v0224_static_bundle import BundleLimits
    from v0224_verified_digest_batch import StaticAuthority

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
    return value, LiveAuthority(authority, Path(value["gate_a"]["path"]), value["gate_a"]["sha256"])


def main():
    import threading

    from v0220_provider_hardened import ProviderStop
    from v0223_transaction_primary_fix import installed_transaction_fix

    if sys.getprofile() is not None or sys.gettrace() is not None or threading.active_count() != 1:
        raise ProviderStop("UNPROFILED_SINGLE_THREAD_CPU_REQUIRED")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("references", "preflight", "stage", "worker"))
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--stage", choices=("P3", "P4"))
    parser.add_argument("--episode")
    args = parser.parse_args()
    if (args.mode in {"stage", "preflight"}) != (args.stage is not None) or (
        args.mode == "worker"
    ) != (args.episode is not None):
        parser.error("stage requires only --stage; worker requires only --episode")
    if args.mode == "references":
        from v0222_scoped_cpu_guard import enable_cpu_network_guard

        enable_cpu_network_guard()
    contract, authority = load_contract(args.contract_path, args.contract_sha256)
    root, binding = Path(contract["root"]), contract["binding_sha256"]
    with installed_transaction_fix():
        if args.mode == "references":
            result = prepare_references(root, binding, authority)
            passed = result["status"] == "REFERENCE_PREPARATION_PASS"
        elif args.mode == "preflight":
            result = preflight(root, binding, args.stage, authority=authority)
            passed = result["status"] == "G_PREFLIGHT_PASS"
        elif args.mode == "stage":
            result = run_stage(
                root,
                binding,
                args.stage,
                authority,
                contract_path=args.contract_path,
                contract_sha256=args.contract_sha256,
            )
            passed = result["status"] == "LIVE_" + args.stage + "_PASS"
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
                "live_scope": "B_C_ONLY",
            }
        ),
        flush=True,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
