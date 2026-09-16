"""Seal one offline-only CPU instance after current engineering and review.

No reference preparation, stage launch, HTTP or model call is performed here.
The initialized 40-PENDING instance still needs complete preparation and its
independent scope review. This is not a live authorization or a stopped retry.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from prepare_v0222_scoped_cpu import episode_specs
from seal_v0222_presentation import ENGINEERING_COMMANDS
from v0220_evidence import LAB, dependencies, save, seal, sha
from v0220_provider_hardened import ProviderStop
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_lineage_v2 import (
    EVIDENCE_INDEX_PATH,
    EVIDENCE_INDEX_SHA256,
    LAUNCH_REVIEW_PATH,
    LAUNCH_REVIEW_SHA256,
    read_inventory,
    verify_lineage,
)
from v0222_scoped_cpu_batch import (
    BOUNDARY_BINDING,
    BOUNDARY_ROOT,
    CPU_REVISION,
    CPU_ROOT,
    IDENTITY,
    PARENT_BINDING,
    PARENT_ROOT,
    PRESENTATION_BINDING,
    PRESENTATION_ROOT,
    REVISION,
    OfflineBatch,
    cpu_authorization_source,
    make_cpu_authorization,
)
from v0222_scoped_cpu_guard import CPU_MODE, require_cpu_network_guard
from v0222_scoped_cpu_worker import stop_batch
from v0222_scoped_history import INVENTORY_PATH, INVENTORY_SHA256

ENTRY_NAMES = (
    "run_v0222_scoped_cpu_seal.py",
    "run_v0222_scoped_cpu_prepare.py",
    "run_v0222_scoped_cpu_preflight.py",
    "run_v0222_scoped_cpu_worker.py",
    "run_v0222_scoped_cpu.py",
)
TEST_NAMES = (
    "test_v0222_scoped_cpu_observation.py",
    "test_v0222_scoped_cpu_contract.py",
    "test_v0222_scoped_cpu_controls.py",
    "test_v0222_scoped_cpu_worker.py",
    "test_v0222_scoped_cpu_preparation.py",
    "test_v0222_scoped_cpu_preflight.py",
    "test_v0222_scoped_cpu_runner.py",
    "test_v0222_scoped_cpu_seal.py",
    "test_v0222_presentation_integration_v2.py",
    "test_v0222_presentation_batch_v2_controls.py",
    "test_v0222_presentation_runner_v2.py",
    "test_v0220_action_adapter.py",
)


def _entries() -> list[Path]:
    """Explicit package/test closure beyond the frozen tools-only walker.

    Keep the old dependency algorithm unchanged. Local package code and both
    imported test helpers must be copied and bound as sources, not just trusted
    because a review record happened to include their input hashes.
    """
    entries = [LAB / "tools" / name for name in ENTRY_NAMES]
    entries += [LAB / "tests/unit" / name for name in TEST_NAMES]
    package = LAB / "src/milai_lab"
    package_sources = sorted(package.rglob("*.py"))
    if not package_sources or not (package / "__init__.py").is_file():
        raise ProviderStop("COMPLETE_LOCAL_CPU_PACKAGE_SOURCES_REQUIRED")
    entries += package_sources
    if any(not path.is_file() for path in entries):
        raise ProviderStop("ALL_CPU_ENTRYPOINTS_AND_TESTS_REQUIRED")
    return entries


def _merge(target: dict, source: dict) -> None:
    for name, expected in source.items():
        if name in target and target[name] != expected:
            raise ProviderStop("CPU_SEAL_CONFLICTING_INPUT_PIN")
        target[name] = expected


def _checked_record(scope, path, status):
    expected = sha(path)
    value = scope.read_json(path, expected)
    if value.get("status") != status or type(value.get("files")) is not dict or not value["files"]:
        raise ProviderStop("CPU_SEAL_CURRENT_COMPLETE_RECORD_REQUIRED")
    pins = {str(path): expected}
    _merge(pins, value["files"])
    for name, digest in pins.items():
        scope.read_bytes(Path(name), digest)
    return value, pins


def prepare(root: Path, engineering_path: Path, review_path: Path) -> dict:
    require_cpu_network_guard()
    if root != CPU_ROOT or root.resolve() != root or root.exists():
        raise ProviderStop("ONE_FRESH_CANONICAL_CPU_INSTANCE_REQUIRED")
    entries = _entries()
    with AdmissionReadScope() as scope:
        engineering, inputs = _checked_record(scope, engineering_path, "ENGINEERING_CHECKS_PASS")
        checks = engineering.get("checks", [])
        if (
            len(checks) != len(ENGINEERING_COMMANDS)
            or {row.get("command") for row in checks} != ENGINEERING_COMMANDS
            or any(type(row.get("exit_code")) is not int or row["exit_code"] != 0 for row in checks)
        ):
            raise ProviderStop("ALL_SIX_TERMINAL_ENGINEERING_CHECKS_REQUIRED")
        review, review_pins = _checked_record(
            scope, review_path, "CPU_REPLAY_IMPLEMENTATION_REVIEW_PASS"
        )
        if (
            review.get("root") != str(CPU_ROOT)
            or review.get("execution_mode") != CPU_MODE
            or review.get("review_is_not_user_consent") is not True
            or review.get("real_http_allowed") is not False
            or review.get("blocking_findings") != []
        ):
            raise ProviderStop("EXPLICIT_CPU_ONLY_IMPLEMENTATION_REVIEW_REQUIRED")
        source_pins = {}
        for path in dependencies(entries):
            digest = sha(path)
            if (
                engineering["files"].get(str(path)) != digest
                or review["files"].get(str(path)) != digest
            ):
                raise ProviderStop("CURRENT_COMPLETE_CPU_SOURCE_CLOSURE_REQUIRED")
            source_pins[str(path)] = digest
        _merge(inputs, review_pins)
        history = verify_lineage(scope)
        inventory = read_inventory(scope)
        _merge(inputs, inventory["files"])
        _merge(
            inputs,
            {
                str(INVENTORY_PATH): INVENTORY_SHA256,
                str(LAUNCH_REVIEW_PATH): LAUNCH_REVIEW_SHA256,
                str(EVIDENCE_INDEX_PATH): EVIDENCE_INDEX_SHA256,
            },
        )
        matrix = episode_specs(scope)
        for name, expected in inputs.items():
            scope.read_bytes(Path(name), expected)
    plan = {
        **matrix,
        "revision": REVISION,
        "coordinator_revision": CPU_REVISION,
        "execution_mode": CPU_MODE,
        "real_http_allowed": False,
        "device_calls_allowed": False,
        "mock_cost_is_not_real_cost": True,
        "selected_decoder": "D11",
        "selected_presentation": "B1",
        "parent_root": str(PARENT_ROOT),
        "parent_binding": PARENT_BINDING,
        "boundary_root": str(BOUNDARY_ROOT),
        "boundary_binding": BOUNDARY_BINDING,
        "presentation_root": str(PRESENTATION_ROOT),
        "presentation_binding": PRESENTATION_BINDING,
        "historical_paths": [row["path"] for row in history["sources"]],
        "http_identity": IDENTITY,
        "raw_cap": None,
        "model_capability_or_live_admission": False,
        "future_recovery_task_memory": "NOT_ADMITTED_BY_THIS_INSTANCE",
    }
    issued = time.time()
    authorization = make_cpu_authorization(
        root, issued=issued, expires=issued + 36 * 3600, history=history
    )
    manifest = seal(root, entries=entries, inputs=[Path(name) for name in inputs], contract=plan)
    if manifest["dependencies"] != source_pins:
        raise ProviderStop("CPU_SEAL_SOURCE_CLOSURE_CHANGED_AFTER_REVIEW")
    if manifest["inputs"] != inputs:
        raise ProviderStop("CPU_SEAL_INPUT_CHANGED_AFTER_SCOPE_CLOSE")
    save(root / "authorization-source.json", cpu_authorization_source())
    save(root / "authorization.json", authorization)
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("authorization.json", "authorization-source.json", "manifest.json")
        },
    )
    binding = sha(root / "execution-binding.json")
    batch = None
    try:
        batch = OfflineBatch(root, binding)
        batch.initialize()
        save(root / "engineering-checks.json", engineering)
        batch.freeze_artifact(
            "engineering_checks", root / "engineering-checks.json", "ENGINEERING_CHECKS_PASS"
        )
        result = {
            "status": "CPU_INSTANCE_INITIALIZED_PREPARATION_AND_SCOPE_REVIEW_REQUIRED",
            "execution_mode": CPU_MODE,
            "binding_sha256": binding,
            "root": str(root),
            "model_requests": 0,
            "http_requests": 0,
            "P3": "NOT_STARTED",
            "P4": "NOT_TRIGGERED",
            "Memory": "NOT_ADMITTED",
            "model_capability_or_live_admission": False,
        }
        save(root / "cpu-instance-initialized.json", result)
        return result
    except BaseException as exc:
        stop_batch(root, binding, batch, exc)
        raise


def main():
    require_cpu_network_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--engineering-checks", type=Path, required=True)
    parser.add_argument("--implementation-review", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.root, args.engineering_checks, args.implementation_review))
    return 0
