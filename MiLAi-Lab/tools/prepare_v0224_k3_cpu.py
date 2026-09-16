"""One fixed K3 fixture; original R04 authority and functional completion priority."""

from __future__ import annotations

import argparse
import copy
import hashlib
import os
import sys
import threading
import time
from pathlib import Path

from prepare_v0224_cpu_workflow import (
    R04_EVIDENCE_PINS as OLD_R04_EVIDENCE_PINS,
)
from prepare_v0224_cpu_workflow import (
    REQUIRED_TESTS as OLD_REQUIRED_TESTS,
)
from prepare_v0224_cpu_workflow import (
    REQUIRED_TOOLS as OLD_REQUIRED_TOOLS,
)
from prepare_v0224_verified_digest_fixture import (
    FAILED_PREPARATION_REVIEW,
    FAILED_PREPARATION_REVIEW_SHA256,
    FAILED_REFERENCE_REVIEW,
    FAILED_REFERENCE_REVIEW_SHA256,
    _check_initialized_state,
    _check_sealed_pins,
    _collect_input_pins,
    _public_inputs,
    _public_source_pins,
    _require_fresh_root,
)
from run_v0224_verified_digest_preparation import (
    FINALIZER_CODE,
    _approval_input,
    _pinned_json,
    _remaining,
    _run_child,
)

LIMIT_SECONDS = 3600  # Preparation watchdog; CPU efficiency is not an acceptance gate.

REQUIRED_TOOLS = (
    *OLD_REQUIRED_TOOLS,
    "v0224_k3_cpu_batch.py",
    "prepare_v0224_k3_cpu.py",
    "run_v0224_k3_cpu.py",
    "preflight_v0224_k3_cpu.py",
)
REQUIRED_TESTS = (
    *OLD_REQUIRED_TESTS,
    "test_v0224_k3_cpu_batch.py",
    "test_prepare_v0224_k3_cpu.py",
    "test_run_v0224_k3_cpu.py",
    "test_preflight_v0224_k3_cpu.py",
)
R04_EVIDENCE_PINS = {
    **OLD_R04_EVIDENCE_PINS,
    (
        "/cra/memory/mx_memory/evidence/v0224/20260913-a-workflow-v1/"
        "independent-a1-calibration-result-review.json"
    ): "44dc8703222bd52dcbc000708a35c6a2329b59e9caa7bd7585ae56aa42b1395d",
    (
        "/cra/memory/mx_memory/MiLAi-Lab/studies/active/"
        "MILA_V0224_COMPLETION_PRIORITY_DELTA_20260913.md"
    ): "9e1579276f60cc8b43db1151951b6eb45a1712abf37530c37179cb75f7a527f6",
}


def _required_entries(lab: Path) -> list[Path]:
    entries = [lab / "tools" / name for name in REQUIRED_TOOLS]
    entries.extend(lab / "tests/unit" / name for name in REQUIRED_TESTS)
    for path in entries:
        if not path.is_file() or path.resolve() != path:
            raise ValueError("REQUIRED_R03_SOURCE_MISSING_OR_ALIASED: " + str(path))
    return entries


def _prepare(static_authority):
    # Install the irreversible guard before importing any replay/provider code.
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_full import resolve_p4_spec
    from v0220_evidence import LAB, dependencies, save, seal, sha
    from v0222_scoped_cpu_batch import CPU_ROOT as OLD_ROOT
    from v0222_scoped_cpu_batch import PRESENTATION_BINDING, PRESENTATION_ROOT
    from v0222_scoped_evidence import verify_manifest
    from v0224_k3_cpu_batch import (
        CPU_REVISION,
        INSTANCE_NAMES,
        OfflineBatch,
        StaticAuthority,
        cpu_authorization_source,
        make_cpu_authorization,
        selected_root,
        workpoint_purpose,
    )
    from v0224_verified_digest_lineage import verify_lineage_r03
    from v0224_verified_digest_scope import BundleReadScope

    root = selected_root()
    if root.name not in INSTANCE_NAMES:
        raise ValueError("ONLY_FIXED_R03_BUNDLE_FIXTURE_REQUIRED")
    if type(static_authority) is not StaticAuthority:
        raise TypeError("EXPLICIT_EXTERNAL_STATIC_AUTHORITY_REQUIRED")
    _required_entries(LAB)
    _require_fresh_root(root)
    with BundleReadScope(**static_authority.scope_arguments()) as scope:
        history = verify_lineage_r03(scope)
        binding = scope.read_json(
            OLD_ROOT / "execution-binding.json", sha(OLD_ROOT / "execution-binding.json")
        )
        original = verify_manifest(scope, OLD_ROOT, binding["manifest.json"])
        public_inputs = _public_inputs(scope, PRESENTATION_ROOT, PRESENTATION_BINDING)
        plan = copy.deepcopy(original["contract"])
        plan["coordinator_revision"] = CPU_REVISION
        plan["purpose"] = workpoint_purpose(root)
        plan["cpu_efficiency_gate_enforced"] = False
        plan["static_authority"] = static_authority.contract_value()
        public_pins = _public_source_pins(plan, public_inputs, CASES)
        scope.read_bytes(FAILED_PREPARATION_REVIEW, FAILED_PREPARATION_REVIEW_SHA256)
        scope.read_bytes(FAILED_REFERENCE_REVIEW, FAILED_REFERENCE_REVIEW_SHA256)
        for evidence_path, evidence_sha in R04_EVIDENCE_PINS.items():
            scope.read_bytes(Path(evidence_path), evidence_sha)
        mappings = []
        for stage in ("P3", "P4"):
            for index, spec in enumerate(plan[stage]):
                before = copy.deepcopy(spec)
                spec["id"] = f"{root.name}-{stage.lower()}-{index + 1:02d}"
                spec["scope"] = f"v0224-{root.name}-{stage.lower()}-{index + 1:02d}"
                if stage == "P4":
                    path = CASES / spec["root"] / "public-initial.json"
                    public = scope.read_json(path, public_inputs[str(path)])
                    spec, _ = resolve_p4_spec(spec, public)
                    plan[stage][index] = spec
                allowed = (
                    {"id", "scope", "initial_state_sha256"} if stage == "P4" else {"id", "scope"}
                )
                assert {k: v for k, v in before.items() if k not in allowed} == {
                    k: v for k, v in spec.items() if k not in allowed
                }
                mappings.append(
                    {
                        "before": {k: before[k] for k in allowed},
                        "after": {k: spec[k] for k in allowed},
                    }
                )
        # Retain every original input and source/copy as benchmark burden.
        inputs = {Path(name) for name in original["inputs"]}
        inputs.update(Path(name) for name in public_pins)
        inputs.add(FAILED_PREPARATION_REVIEW)
        inputs.add(FAILED_REFERENCE_REVIEW)
        inputs.update(Path(name) for name in R04_EVIDENCE_PINS)
        inputs.update(Path(name) for name in original["dependencies"])
        inputs.update(
            OLD_ROOT / "executed-source" / Path(name).relative_to(LAB)
            for name in original["dependencies"]
        )
        inputs.add(OLD_ROOT / "manifest.json")
        engineering_path = OLD_ROOT / "engineering-checks.json"
        engineering = scope.read_json(engineering_path, sha(engineering_path))
        inputs.add(engineering_path)
        # Retain every frozen current source/input/copy, never its mutable stopped SQLite.
        prior_root = Path(
            "/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-diagnostic-v1/diagv1-d1-u1"
        )
        prior_binding = scope.read_json(
            prior_root / "execution-binding.json",
            "a72effffc756a8ee237304e3672cc35bd43e4c3a4dcb4afca1b5a284ff3577a6",
        )
        prior_manifest = verify_manifest(scope, prior_root, prior_binding["manifest.json"])
        inputs.update(Path(name) for name in prior_manifest["inputs"])
        inputs.update(Path(name) for name in prior_manifest["dependencies"])
        inputs.update(
            prior_root / "executed-source" / Path(name).relative_to(LAB)
            for name in prior_manifest["dependencies"]
        )
        inputs.add(prior_root / "manifest.json")
        inputs.add(prior_root / "execution-binding.json")
        inputs.update({static_authority.bundle_path, static_authority.receipt_path})
        entries = _required_entries(LAB)
        entries.extend(Path(name) for name in prior_manifest["dependencies"])
        entries.extend(Path(name) for name in original["dependencies"])
        # Freeze observed bytes before scope.close; seal must not bless drift.
        trusted_pins = {
            **public_pins,
            **R04_EVIDENCE_PINS,
            str(FAILED_PREPARATION_REVIEW): FAILED_PREPARATION_REVIEW_SHA256,
            str(FAILED_REFERENCE_REVIEW): FAILED_REFERENCE_REVIEW_SHA256,
            str(static_authority.bundle_path): static_authority.bundle_sha256,
            str(static_authority.receipt_path): static_authority.receipt_sha256,
        }
        input_pins = _collect_input_pins(inputs, trusted_pins, sha)
        source_pins = {str(path): sha(path) for path in dependencies(entries)}
        for pins in (input_pins, source_pins):
            for name, digest in pins.items():
                with scope.physical_reads():
                    scope.read_bytes(Path(name), digest)
    _require_fresh_root(root)
    manifest = seal(root, entries=entries, inputs=sorted(inputs), contract=plan)
    _check_sealed_pins(manifest, input_pins, source_pins)
    # Fixed-width timestamps avoid accidental U/S file-size differences.
    issued = int(time.time())
    save(
        root / "authorization.json",
        make_cpu_authorization(root, issued=issued, expires=issued + 36 * 3600, history=history),
    )
    save(root / "authorization-source.json", cpu_authorization_source())
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("authorization.json", "authorization-source.json", "manifest.json")
        },
    )
    digest = sha(root / "execution-binding.json")
    batch = OfflineBatch(root, digest, static_authority=static_authority)
    batch.initialize()
    save(root / "engineering-checks.json", engineering)
    batch.freeze_artifact(
        "engineering_checks", root / "engineering-checks.json", "ENGINEERING_CHECKS_PASS"
    )
    snapshot = batch.snapshot()
    with batch.transaction() as db:
        initial_events = batch.events(db)
    _check_initialized_state(snapshot, initial_events)
    result = {
        "status": "K3_FIXTURE_ONLY_NOT_CURRENT_ENGINEERING_OR_GATE_A_PASS",
        "root": str(root),
        "binding_sha256": digest,
        "mappings": mappings,
        "historical_engineering_only": True,
        "http_requests": 0,
        "model_requests": 0,
        "new_source_count": len(manifest["dependencies"]),
        "snapshot": snapshot,
        "initial_events": initial_events,
        "static_authority": static_authority.contract_value(),
    }
    save(root / "fixture-prepared.json", result)
    return result


def prepare(static_authority):
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise ValueError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0223_transaction_primary_fix import installed_transaction_fix

    with installed_transaction_fix():
        return _prepare(static_authority)


def fixture_main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--bundle-path", type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--receipt-path", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    for field in ("max-header-bytes", "max-payload-bytes", "max-paths", "max-blobs"):
        parser.add_argument("--" + field, type=int, required=True)
    args = parser.parse_args(argv)
    # Guard precedes imports of the binding and complete replay stack.
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0224_k3_cpu_batch import StaticAuthority
    from v0224_static_bundle import BundleLimits

    os.environ["MILA_V0224_INSTANCE"] = args.instance
    authority = StaticAuthority(
        args.bundle_path,
        args.bundle_sha256,
        args.receipt_path,
        args.receipt_sha256,
        BundleLimits(args.max_header_bytes, args.max_payload_bytes, args.max_paths, args.max_blobs),
    )
    result = prepare(authority)
    print({key: result[key] for key in ("status", "root", "binding_sha256")})


def run_preparation(contract_path, contract_sha256, *, approval_fd=0):
    start = time.monotonic()
    deadline = start + LIMIT_SECONDS
    if sys.getprofile() is not None or sys.gettrace() is not None or threading.active_count() != 1:
        raise ValueError("UNPROFILED_UNTRACED_SINGLE_THREAD_PARENT_REQUIRED")
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0224_bundle_authority import _validate_contract
    from v0220_evidence import dependencies
    from v0222_admission_read_scope import AdmissionReadScope
    from v0224_k3_cpu_batch import INSTANCE_ORDER
    from v0224_static_bundle import canonical_json

    contract_path = Path(contract_path)
    if (
        not contract_path.is_absolute()
        or contract_path.resolve() != contract_path
        or ".." in contract_path.parts
    ):
        raise ValueError("CANONICAL_FROZEN_PREPARATION_CONTRACT_REQUIRED")
    out = contract_path.parent / "preparation-controller-v1"
    out.mkdir(exist_ok=False)
    children = []
    phase = "verify_frozen_contract"
    record = {
        "status": "PREPARATION_INCOMPLETE",
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "contract_sha256": contract_sha256,
        "children": children,
    }
    try:
        with AdmissionReadScope() as scope:
            contract = scope.read_json(contract_path, contract_sha256)
            _validate_contract(contract, {str(p) for p in dependencies([Path(__file__).resolve()])})
            for name, digest in contract["files"].items():
                scope.read_bytes(Path(name), digest)
        _remaining(deadline)
        tools = Path(__file__).resolve().parent
        phase = "authority_builder"
        authority_child = _run_child(
            [
                sys.executable,
                str(tools / "prepare_v0224_bundle_authority.py"),
                "--contract-path",
                str(contract_path),
                "--contract-sha256",
                contract_sha256,
            ],
            phase,
            out,
            deadline,
            children,
        )
        directory = contract_path.parent / "authority-v1"
        report_path = directory / "authority-prepared.json"
        report = _pinned_json(report_path, hashlib.sha256(report_path.read_bytes()).hexdigest())
        if (
            report["status"] != "READY_FOR_INDEPENDENT_AUTHORITY_REVIEW"
            or report["runtime_authorized"] is not False
            or report["pid"] != authority_child["pid"]
            or report["contract_sha256"] != contract_sha256
        ):
            raise ValueError("ACTUAL_AUTHORITY_CHILD_REPORT_REQUIRED")
        generated = report["generated_files"]
        candidate_path = directory / "sealed/candidate-receipt.json"
        mechanical_path = directory / "revalidated/mechanical-revalidation.json"
        bundle_path = directory / "sealed/static.bundle"
        observation_path = directory / "sealed/seal-observation.json"
        if set(generated) != {
            str(p) for p in (candidate_path, mechanical_path, bundle_path, observation_path)
        }:
            raise ValueError("EXACT_CURRENT_AUTHORITY_OUTPUTS_REQUIRED")
        candidate = _pinned_json(candidate_path, generated[str(candidate_path)])
        if candidate["bundle_sha256"] != generated[str(bundle_path)]:
            raise ValueError("ACTUAL_BUNDLE_OUTPUT_BINDING_REQUIRED")
        phase = "waiting_for_independent_approval"
        wait_start = time.monotonic()
        print("WAITING_FOR_INDEPENDENT_APPROVAL", flush=True)
        approval = _approval_input(
            contract_path.parent / "independent-authority-approval.json", deadline, approval_fd
        )
        record["approval_wait_seconds"] = time.monotonic() - wait_start
        record["approval"] = approval
        phase = "finalizer"
        _run_child(
            [
                sys.executable,
                "-c",
                FINALIZER_CODE,
                str(candidate_path),
                generated[str(candidate_path)],
                str(mechanical_path),
                generated[str(mechanical_path)],
                approval["approval_path"],
                approval["approval_sha256"],
            ],
            phase,
            out,
            deadline,
            children,
        )
        # The finalizer import path is provided by the controller's fixed tools cwd.
        from v0222_scoped_evidence import _strict_json

        finalizer = _strict_json((out / "finalizer.stdout").read_text())
        receipt_path = directory / "approved-receipt.json"
        if finalizer["status"] != "APPROVED_RECEIPT_MATERIALIZED_NOT_GATE_A" or finalizer[
            "path"
        ] != str(receipt_path):
            raise ValueError("ACTUAL_FINALIZER_RESULT_REQUIRED")
        receipt = _pinned_json(receipt_path, finalizer["sha256"])
        if receipt != {**candidate, "status": "INDEPENDENT_STATIC_BUNDLE_APPROVED"}:
            raise ValueError("FINALIZED_RECEIPT_NOT_EXACT_APPROVED_CANDIDATE")
        for instance in INSTANCE_ORDER:
            phase = "fixture_preparer-" + instance
            argv = [
                sys.executable,
                str(tools / "prepare_v0224_k3_cpu.py"),
                "fixture",
                "--instance",
                instance,
                "--bundle-path",
                str(bundle_path),
                "--bundle-sha256",
                candidate["bundle_sha256"],
                "--receipt-path",
                str(receipt_path),
                "--receipt-sha256",
                finalizer["sha256"],
            ]
            for name, value in contract["limits"].items():
                argv.extend(["--" + name.replace("_", "-"), str(value)])
            _run_child(argv, phase, out, deadline, children)
        phase = "parent_input_recheck"
        with AdmissionReadScope() as scope:
            current_contract = scope.read_json(contract_path, contract_sha256)
            if current_contract != contract:
                raise ValueError("FINAL_PARENT_CONTRACT_DRIFT")
            for name, digest in contract["files"].items():
                scope.read_bytes(Path(name), digest)
        _remaining(deadline)
        record["final_parent_input_scope_stats"] = scope.stats
        phase = "parent_report"
        _remaining(deadline)
        record.update(
            status="PREPARATION_STEPS_COMPLETE_EXTERNAL_EXIT_REQUIRED",
            elapsed_before_report_seconds=time.monotonic() - start,
        )
        with (out / "preparation-result.json").open("xb") as stream:
            stream.write(canonical_json(record))
        _remaining(deadline)
        return record
    except BaseException as primary:
        record.update(
            status="PREPARATION_FAILED_NO_RETRY",
            phase=phase,
            exception_type=type(primary).__name__,
            reason=str(primary),
            elapsed_seconds=time.monotonic() - start,
        )
        try:
            with (out / "preparation-failure.json").open("xb") as stream:
                stream.write(canonical_json(record))
        except BaseException as secondary:
            primary.add_note("SECONDARY_PREPARATION_FAILURE_RECORD: " + repr(secondary))
        raise


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"fixture", "controller"}:
        raise ValueError("EXPLICIT_FIXTURE_OR_CONTROLLER_COMMAND_REQUIRED")
    if args[0] == "fixture":
        return fixture_main(args[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    options = parser.parse_args(args[1:])
    return run_preparation(options.contract_path, options.contract_sha256)


if __name__ == "__main__":
    main()
