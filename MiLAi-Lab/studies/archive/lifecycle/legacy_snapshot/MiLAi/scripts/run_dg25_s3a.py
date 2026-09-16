#!/usr/bin/env python3
"""Run one independently authorized, label-free DG-25 S3A E1 replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__)
ROOT = _SCRIPT_PATH.resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (str(ROOT), str(RUNTIME_SRC)):
    if value not in sys.path:
        sys.path.insert(0, value)

from evals.dg25.routing_ablation import E1ArmConfigV01
from evals.dg25.s3a_generator import generate_e1_all_arm_bundle
from evals.dg25.stop_gate import evaluate_generation_gate

READINESS_ARTIFACT_FILENAMES = {
    "all_arm_seal_protocol": "all-arm-seal-protocol.json",
    "cost_ledger_schema": "cost-ledger-schema.json",
    "e1_action_role_manifest": "e1-action-role-manifest.json",
    "e2_common_input": "e2-common-input.json",
    "effect_scorer_contract": "effect-scorer-contract.json",
    "execution_delta_manifest": "execution-delta-manifest.json",
    "quality_evidence_binding": "quality-evidence-binding.json",
    "readiness_validation_report": "readiness-validation-report.json",
    "source_manifest": "source-manifest.json",
    "stop_evaluation_contract": "stop-evaluation-contract.json",
}
READINESS_SOURCE_PATHS = (
    "evals/dg25/routing_ablation.py",
    "evals/dg25/arm_sealing.py",
    "evals/dg25/s3a_generator.py",
    "evals/dg25/effect_scorer.py",
    "evals/dg25/stop_gate.py",
    "evals/dg25/s3_readiness.py",
    "evals/dg24/scorer.py",
    "scripts/run_dg25_readiness_quality.py",
    "scripts/run_dg25_s3_readiness.py",
    "scripts/run_dg25_s3a.py",
    "tests/test_dg25_s3_readiness.py",
    "runtime/src/milai/application/accuracy_acquisition.py",
    "runtime/src/milai/application/acquisition.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/evidence_semantics.py",
    "runtime/src/milai/application/requirement_acquisition.py",
    "runtime/src/milai/domain/requirement_acquisition.py",
    "runtime/src/milai/domain/temporal_proof.py",
)
PREDECESSOR_INPUT_PATHS = {
    "official_probe_collection": (
        "var/dg24/s3/dg24-s3-product-trace-20260829-002/"
        "sealed-official-probe-traces.json"
    ),
    "product_trace_collection": (
        "var/dg24/s3/dg24-s3-product-trace-20260829-002/"
        "sealed-product-traces.json"
    ),
}
SAFE_COMPONENT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
READINESS_ROOT = Path("var/dg25/readiness")
REVIEW_ROOT = Path("var/dg25/reviews")
S3A_OUTPUT_ROOT = Path("var/dg25/s3a")


@dataclass
class S3AFailureContext:
    """Mutable stage context captured by the single official failure wrapper."""

    first_failing_gate: str
    config_identity: dict[str, Any]
    source_identities: list[dict[str, Any]] = field(default_factory=list)
    input_identities: list[dict[str, Any]] = field(default_factory=list)
    snapshot_identities: list[dict[str, Any]] = field(default_factory=list)
    attempt_identity_envelope: dict[str, Any] = field(default_factory=dict)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--readiness-run-id", required=True)
    parser.add_argument("--authorization-review", type=Path, required=True)
    args = parser.parse_args()

    return _run_s3a_once(args, root=ROOT, argv=tuple(sys.argv))


def _run_s3a_once(
    args: argparse.Namespace,
    *,
    root: Path,
    argv: Sequence[str],
) -> int:
    """Run the official path once under its sole top-level failure boundary."""

    context = _build_s3a_failure_context(args, root=root)
    return _execute_with_failure_ledger(
        execute=lambda: _capture_and_execute(args, context, root=root),
        context=context,
        root=root,
        argv=argv,
    )


def _build_s3a_failure_context(
    args: argparse.Namespace,
    *,
    root: Path,
) -> S3AFailureContext:
    """Preallocate the complete fixed inventory without reading any input."""

    config_identity = {
        "run_id": str(args.run_id),
        "readiness_run_id": str(args.readiness_run_id),
        "authorization_review": str(args.authorization_review),
    }
    envelope = _preallocated_attempt_identity_envelope(
        root=root,
        config_identity=config_identity,
    )
    return S3AFailureContext(
        first_failing_gate="DG25_S3A_ATTEMPT_IDENTITY_ENVELOPE_PRECHECK",
        config_identity=config_identity,
        source_identities=[dict(item) for item in envelope["source_identities"]],
        input_identities=[dict(item) for item in envelope["input_identities"]],
        snapshot_identities=[dict(item) for item in envelope["snapshot_identities"]],
        attempt_identity_envelope=envelope,
    )


def _preallocated_attempt_identity_envelope(
    *,
    root: Path,
    config_identity: Mapping[str, Any],
) -> dict[str, Any]:
    requested_readiness_run_id = str(config_identity["readiness_run_id"])
    readiness_run_id = (
        requested_readiness_run_id
        if _is_safe_component(requested_readiness_run_id)
        else "__INVALID_READINESS_RUN_ID__"
    )
    readiness_dir = root / READINESS_ROOT / readiness_run_id
    readiness_receipt_path = readiness_dir / "receipt.json"
    requested_review_path = Path(str(config_identity["authorization_review"]))
    review_path = (
        requested_review_path
        if requested_review_path.is_absolute()
        else root / requested_review_path
    )
    snapshot_identities = [
        _unobserved_identity(
            root=root,
            path=readiness_receipt_path,
            expected={"path": _logical_path(root, readiness_receipt_path)},
            category="SNAPSHOT",
            key="readiness_receipt",
        ),
        _unobserved_identity(
            root=root,
            path=review_path,
            expected={"path": _logical_path(root, review_path)},
            category="SNAPSHOT",
            key="authorization_review",
        ),
    ]
    readiness_artifact_identities = []
    for key, filename in READINESS_ARTIFACT_FILENAMES.items():
        path = readiness_dir / filename
        readiness_artifact_identities.append(
            _unobserved_identity(
                root=root,
                path=path,
                expected={"path": _logical_path(root, path)},
                category="READINESS_ARTIFACT",
                key=key,
            )
        )
    source_identities = [
        _unobserved_identity(
            root=root,
            path=root / path,
            expected={"path": path},
            category="SOURCE",
            key=path,
        )
        for path in READINESS_SOURCE_PATHS
    ]
    predecessor_input_identities = []
    for key, fallback_path in PREDECESSOR_INPUT_PATHS.items():
        predecessor_input_identities.append(
            _unobserved_identity(
                root=root,
                path=root / fallback_path,
                expected={"path": fallback_path},
                category="PREDECESSOR_INPUT",
                key=key,
            )
        )

    input_identities = [
        *readiness_artifact_identities,
        *predecessor_input_identities,
    ]
    completeness_checks = {
        "snapshot_identity_count_two": len(snapshot_identities) == 2,
        "readiness_artifact_identity_count_ten": (
            len(readiness_artifact_identities) == 10
        ),
        "source_identity_count_eighteen": len(source_identities) == 18,
        "predecessor_input_identity_count_two": (
            len(predecessor_input_identities) == 2
        ),
        "all_entries_have_explicit_disposition": all(
            isinstance(item.get("disposition"), str)
            for item in (
                *snapshot_identities,
                *readiness_artifact_identities,
                *source_identities,
                *predecessor_input_identities,
            )
        ),
    }
    material: dict[str, Any] = {
        "schema": "milai.dg25.s3a-attempt-identity-envelope.v0.1",
        "frozen_before_covered_prechecks": True,
        "inventory_preallocated_before_reads": True,
        "capture_frozen_before_execute": False,
        "capture_complete": False,
        "config_identity": dict(config_identity),
        "snapshot_identities": snapshot_identities,
        "readiness_artifact_identities": readiness_artifact_identities,
        "source_identities": source_identities,
        "predecessor_input_identities": predecessor_input_identities,
        "input_identities": input_identities,
        "capture_diagnostics": {
            "top_level_capture": {"disposition": "NOT_ATTEMPTED"},
            "authorization_review": {"disposition": "NOT_ATTEMPTED"},
            "readiness_receipt": {"disposition": "NOT_ATTEMPTED"},
            "readiness_review_binding": {"disposition": "NOT_ATTEMPTED"},
            "readiness_artifact_contract": {"disposition": "NOT_ATTEMPTED"},
            "readiness_artifact_observation": {"disposition": "NOT_ATTEMPTED"},
            "source_manifest": {"disposition": "NOT_ATTEMPTED"},
            "source_manifest_contract": {"disposition": "NOT_ATTEMPTED"},
            "source_observation": {"disposition": "NOT_ATTEMPTED"},
            "e1_action_role_manifest": {"disposition": "NOT_ATTEMPTED"},
            "predecessor_contract": {"disposition": "NOT_ATTEMPTED"},
            "predecessor_observation": {"disposition": "NOT_ATTEMPTED"},
        },
        "completeness_checks": completeness_checks,
        "complete_inventory_frozen": all(completeness_checks.values()),
        "automatic_retries": 0,
    }
    material["envelope_digest"] = _canonical_sha256(material)
    return material


def _unobserved_identity(
    *,
    root: Path,
    path: Path,
    expected: Mapping[str, Any],
    category: str,
    key: str,
) -> dict[str, Any]:
    return {
        "category": category,
        "key": key,
        "path": _logical_path(root, path),
        "expected_identity": dict(expected),
        "observed_identity": None,
        "resolved_path": None,
        "disposition": "NOT_OBSERVED_CAPTURE_NOT_STARTED",
        "observation_error": None,
    }


def _capture_and_execute(
    args: argparse.Namespace,
    context: S3AFailureContext,
    *,
    root: Path,
) -> int:
    context.first_failing_gate = "DG25_S3A_TOP_LEVEL_PATH_PRECHECK"
    _validate_top_level_paths(args, root=root)
    context.first_failing_gate = "DG25_S3A_ATTEMPT_IDENTITY_CAPTURE"
    _capture_attempt_identity_envelope(args, context, root=root)
    context.first_failing_gate = "DG25_S3A_ATTEMPT_IDENTITY_ENVELOPE_PRECHECK"
    return _execute(args, context, root=root)


def _is_safe_component(value: str) -> bool:
    return (
        value not in {".", ".."}
        and SAFE_COMPONENT_PATTERN.fullmatch(value) is not None
    )


def _validate_top_level_paths(
    args: argparse.Namespace,
    *,
    root: Path,
) -> dict[str, Path]:
    run_id = str(args.run_id)
    readiness_run_id = str(args.readiness_run_id)
    if not _is_safe_component(run_id):
        raise ValueError("DG25_S3A_RUN_ID_NOT_SAFE_SINGLE_COMPONENT")
    if not _is_safe_component(readiness_run_id):
        raise ValueError("DG25_S3A_READINESS_RUN_ID_NOT_SAFE_SINGLE_COMPONENT")

    output_root = root / S3A_OUTPUT_ROOT
    readiness_root = root / READINESS_ROOT
    review_root = root / REVIEW_ROOT
    for path, code in (
        (output_root, "DG25_S3A_OUTPUT_ROOT_OUTSIDE_WORKSPACE"),
        (readiness_root, "DG25_S3A_READINESS_ROOT_OUTSIDE_WORKSPACE"),
        (review_root, "DG25_S3A_REVIEW_ROOT_OUTSIDE_WORKSPACE"),
    ):
        if (
            not _resolved_within(root, path)
            or path.resolve(strict=False) != path.absolute()
        ):
            raise ValueError(code)

    output = output_root / run_id
    readiness_dir = readiness_root / readiness_run_id
    _require_resolved_direct_child(
        output,
        parent=output_root,
        error_code="DG25_S3A_OUTPUT_NOT_RESOLVED_DIRECT_CHILD",
    )
    _require_resolved_direct_child(
        readiness_dir,
        parent=readiness_root,
        error_code="DG25_S3A_READINESS_NOT_RESOLVED_DIRECT_CHILD",
    )

    requested_review = Path(str(args.authorization_review))
    if requested_review.is_absolute():
        raise ValueError("DG25_S3A_AUTHORIZATION_ABSOLUTE_PATH_REJECTED")
    if not requested_review.parts or ".." in requested_review.parts:
        raise ValueError("DG25_S3A_AUTHORIZATION_TRAVERSAL_PATH_REJECTED")
    review_path = root / requested_review
    review_absolute = review_path.absolute()
    review_root_absolute = review_root.absolute()
    try:
        review_absolute.relative_to(review_root_absolute)
    except ValueError as exc:
        raise ValueError(
            "DG25_S3A_AUTHORIZATION_PATH_NOT_UNDER_REVIEW_ROOT"
        ) from exc
    if not _resolved_within(review_root, review_path):
        raise ValueError("DG25_S3A_AUTHORIZATION_RESOLVES_OUTSIDE_REVIEW_ROOT")

    return {
        "output": output,
        "readiness_dir": readiness_dir,
        "readiness_receipt": readiness_dir / "receipt.json",
        "review": review_path,
    }


def _require_resolved_direct_child(
    path: Path,
    *,
    parent: Path,
    error_code: str,
) -> None:
    if path.absolute().parent != parent.absolute():
        raise ValueError(error_code)
    resolved = path.resolve(strict=False)
    if resolved != path.absolute() or resolved.parent != parent.resolve(strict=False):
        raise ValueError(error_code)


def _resolved_within(root: Path, path: Path) -> bool:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError):
        return False
    return True


def _capture_attempt_identity_envelope(
    args: argparse.Namespace,
    context: S3AFailureContext,
    *,
    root: Path,
) -> None:
    """Capture fixed identities totally; all content failures become diagnostics."""

    envelope = json.loads(json.dumps(context.attempt_identity_envelope))
    diagnostics = dict(envelope["capture_diagnostics"])
    diagnostics["top_level_capture"] = None
    paths = _validate_top_level_paths(args, root=root)
    readiness_dir = paths["readiness_dir"]
    try:
        review_observation = _observe_identity(
            root=root,
            path=paths["review"],
            expected={"path": _logical_path(root, paths["review"])},
            category="SNAPSHOT",
            key="authorization_review",
            allowed_root=root / REVIEW_ROOT,
        )
        _replace_identity(
            envelope,
            "snapshot_identities",
            "authorization_review",
            review_observation,
        )
        review, review_error = _try_read_json_after_observation(
            paths["review"],
            review_observation,
        )
        diagnostics["authorization_review"] = review_error

        provisional_receipt_observation = _observe_identity(
            root=root,
            path=paths["readiness_receipt"],
            expected={
                "path": _logical_path(root, paths["readiness_receipt"]),
            },
            category="SNAPSHOT",
            key="readiness_receipt",
            allowed_root=readiness_dir,
            require_direct_parent=True,
        )
        _replace_identity(
            envelope,
            "snapshot_identities",
            "readiness_receipt",
            provisional_receipt_observation,
        )
        receipt, receipt_error = _try_read_json_after_observation(
            paths["readiness_receipt"],
            provisional_receipt_observation,
        )
        diagnostics["readiness_receipt"] = receipt_error
        if review is None or receipt is None:
            _skip_remaining_capture(
                envelope,
                diagnostics,
                disposition="NOT_OBSERVED_SNAPSHOT_CAPTURE_FAILED",
            )
            _freeze_captured_envelope(context, envelope, diagnostics)
            return

        expected_receipt = _reviewed_readiness_identity(
            root=root,
            readiness_receipt_path=paths["readiness_receipt"],
            review=review,
        )
        receipt_observation = _observe_identity(
            root=root,
            path=paths["readiness_receipt"],
            expected=expected_receipt,
            category="SNAPSHOT",
            key="readiness_receipt",
            allowed_root=readiness_dir,
            require_direct_parent=True,
        )
        _replace_identity(
            envelope,
            "snapshot_identities",
            "readiness_receipt",
            receipt_observation,
        )
        if not _review_binding_is_exact(
            review=review,
            expected_receipt=expected_receipt,
        ) or receipt_observation.get("disposition") != "MATCH":
            diagnostics["readiness_review_binding"] = _contract_diagnostic(
                "DG25_S3A_REVIEWED_READINESS_IDENTITY_NOT_EXACT"
            )
            _skip_remaining_capture(
                envelope,
                diagnostics,
                disposition="NOT_OBSERVED_UNAUTHENTICATED_READINESS_RECEIPT",
            )
            _freeze_captured_envelope(context, envelope, diagnostics)
            return
        diagnostics["readiness_review_binding"] = None

        artifact_expected, artifact_error = _exact_readiness_artifact_contract(
            receipt,
            root=root,
            readiness_dir=readiness_dir,
        )
        diagnostics["readiness_artifact_contract"] = artifact_error
        if artifact_expected is None:
            _mark_group_unobserved(
                envelope,
                "readiness_artifact_identities",
                disposition="NOT_OBSERVED_UNTRUSTED_ARTIFACT_CONTRACT",
            )
            _skip_remaining_capture(
                envelope,
                diagnostics,
                disposition="NOT_OBSERVED_UNTRUSTED_ARTIFACT_CONTRACT",
            )
            _freeze_captured_envelope(context, envelope, diagnostics)
            return

        artifact_observations = []
        for key, filename in READINESS_ARTIFACT_FILENAMES.items():
            artifact_observations.append(
                _observe_identity(
                    root=root,
                    path=readiness_dir / filename,
                    expected=artifact_expected[key],
                    category="READINESS_ARTIFACT",
                    key=key,
                    allowed_root=readiness_dir,
                    require_direct_parent=True,
                )
            )
        envelope["readiness_artifact_identities"] = artifact_observations
        artifact_capture_passed = all(
            item.get("disposition") == "MATCH"
            for item in artifact_observations
        )
        diagnostics["readiness_artifact_observation"] = (
            None
            if artifact_capture_passed
            else _contract_diagnostic(
                "DG25_S3A_READINESS_ARTIFACT_RESOLVED_IDENTITY_DRIFT"
            )
        )
        if not artifact_capture_passed:
            _skip_remaining_capture(
                envelope,
                diagnostics,
                disposition="NOT_OBSERVED_READINESS_ARTIFACT_IDENTITY_DRIFT",
            )
            _freeze_captured_envelope(context, envelope, diagnostics)
            return

        source_manifest_path = readiness_dir / READINESS_ARTIFACT_FILENAMES[
            "source_manifest"
        ]
        action_manifest_path = readiness_dir / READINESS_ARTIFACT_FILENAMES[
            "e1_action_role_manifest"
        ]
        source_manifest, source_error = _try_read_json(source_manifest_path)
        action_manifest, action_error = _try_read_json(action_manifest_path)
        diagnostics["source_manifest"] = source_error
        diagnostics["e1_action_role_manifest"] = action_error

        if source_manifest is None:
            _mark_group_unobserved(
                envelope,
                "source_identities",
                disposition="NOT_OBSERVED_SOURCE_MANIFEST_CAPTURE_FAILED",
            )
            diagnostics["source_manifest_contract"] = {
                "disposition": "SKIPPED_AFTER_SOURCE_MANIFEST_CAPTURE_FAILURE"
            }
            diagnostics["source_observation"] = {
                "disposition": "SKIPPED_AFTER_SOURCE_MANIFEST_CAPTURE_FAILURE"
            }
        else:
            source_expected, source_contract_error = _exact_source_contract(
                source_manifest
            )
            diagnostics["source_manifest_contract"] = source_contract_error
            if source_expected is None:
                _mark_group_unobserved(
                    envelope,
                    "source_identities",
                    disposition="NOT_OBSERVED_SOURCE_PATH_SET_DRIFT",
                )
                diagnostics["source_observation"] = {
                    "disposition": "SKIPPED_AFTER_SOURCE_PATH_SET_DRIFT"
                }
            else:
                source_observations = [
                    _observe_identity(
                        root=root,
                        path=root / path,
                        expected=source_expected[path],
                        category="SOURCE",
                        key=path,
                        allowed_root=root,
                    )
                    for path in READINESS_SOURCE_PATHS
                ]
                envelope["source_identities"] = source_observations
                source_capture_passed = all(
                    item.get("disposition") == "MATCH"
                    for item in source_observations
                )
                diagnostics["source_observation"] = (
                    None
                    if source_capture_passed
                    else _contract_diagnostic(
                        "DG25_S3A_SOURCE_RESOLVED_IDENTITY_DRIFT"
                    )
                )

        if action_manifest is None:
            _mark_group_unobserved(
                envelope,
                "predecessor_input_identities",
                disposition="NOT_OBSERVED_ACTION_MANIFEST_CAPTURE_FAILED",
            )
            diagnostics["predecessor_contract"] = {
                "disposition": "SKIPPED_AFTER_ACTION_MANIFEST_CAPTURE_FAILURE"
            }
            diagnostics["predecessor_observation"] = {
                "disposition": "SKIPPED_AFTER_ACTION_MANIFEST_CAPTURE_FAILURE"
            }
        else:
            predecessor_expected, predecessor_contract_error = (
                _exact_predecessor_contract(action_manifest)
            )
            diagnostics["predecessor_contract"] = predecessor_contract_error
            if predecessor_expected is None:
                _mark_group_unobserved(
                    envelope,
                    "predecessor_input_identities",
                    disposition="NOT_OBSERVED_PREDECESSOR_PATH_SET_DRIFT",
                )
                diagnostics["predecessor_observation"] = {
                    "disposition": "SKIPPED_AFTER_PREDECESSOR_PATH_SET_DRIFT"
                }
            else:
                predecessor_observations = [
                    _observe_identity(
                        root=root,
                        path=root / PREDECESSOR_INPUT_PATHS[key],
                        expected=predecessor_expected[key],
                        category="PREDECESSOR_INPUT",
                        key=key,
                        allowed_root=root,
                    )
                    for key in PREDECESSOR_INPUT_PATHS
                ]
                envelope["predecessor_input_identities"] = (
                    predecessor_observations
                )
                predecessor_capture_passed = all(
                    item.get("disposition") == "MATCH"
                    for item in predecessor_observations
                )
                diagnostics["predecessor_observation"] = (
                    None
                    if predecessor_capture_passed
                    else _contract_diagnostic(
                        "DG25_S3A_PREDECESSOR_RESOLVED_IDENTITY_DRIFT"
                    )
                )
        _freeze_captured_envelope(context, envelope, diagnostics)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        diagnostics["top_level_capture"] = _exception_diagnostic(exc)
        _skip_remaining_capture(
            envelope,
            diagnostics,
            disposition="NOT_OBSERVED_UNEXPECTED_CAPTURE_EXCEPTION",
        )
        _freeze_captured_envelope(context, envelope, diagnostics)


def _replace_identity(
    envelope: dict[str, Any],
    group: str,
    key: str,
    replacement: Mapping[str, Any],
) -> None:
    entries = envelope[group]
    for index, entry in enumerate(entries):
        if entry.get("key") == key:
            entries[index] = dict(replacement)
            return
    raise KeyError(f"missing preallocated identity slot: {group}/{key}")


def _mark_group_unobserved(
    envelope: dict[str, Any],
    group: str,
    *,
    disposition: str,
) -> None:
    for entry in envelope[group]:
        if entry.get("observed_identity") is None:
            entry["disposition"] = disposition


def _skip_remaining_capture(
    envelope: dict[str, Any],
    diagnostics: dict[str, Any],
    *,
    disposition: str,
) -> None:
    for group in (
        "snapshot_identities",
        "readiness_artifact_identities",
        "source_identities",
        "predecessor_input_identities",
    ):
        _mark_group_unobserved(envelope, group, disposition=disposition)
    for key, value in diagnostics.items():
        if isinstance(value, Mapping) and value.get("disposition") == "NOT_ATTEMPTED":
            diagnostics[key] = {"disposition": disposition}


def _freeze_captured_envelope(
    context: S3AFailureContext,
    envelope: dict[str, Any],
    diagnostics: Mapping[str, Any],
) -> None:
    envelope["capture_diagnostics"] = dict(diagnostics)
    envelope["input_identities"] = [
        *[dict(item) for item in envelope["readiness_artifact_identities"]],
        *[dict(item) for item in envelope["predecessor_input_identities"]],
    ]
    envelope["capture_frozen_before_execute"] = True
    envelope["capture_complete"] = _capture_is_complete(envelope)
    envelope.pop("envelope_digest", None)
    envelope["envelope_digest"] = _canonical_sha256(envelope)
    context.attempt_identity_envelope = envelope
    context.snapshot_identities = [
        dict(item) for item in envelope["snapshot_identities"]
    ]
    context.source_identities = [
        dict(item) for item in envelope["source_identities"]
    ]
    context.input_identities = [
        dict(item) for item in envelope["input_identities"]
    ]


def _capture_is_complete(envelope: Mapping[str, Any]) -> bool:
    diagnostics = envelope.get("capture_diagnostics")
    if not isinstance(diagnostics, Mapping) or any(
        value is not None for value in diagnostics.values()
    ):
        return False
    snapshots = envelope.get("snapshot_identities")
    if not isinstance(snapshots, Sequence) or isinstance(snapshots, (str, bytes)):
        return False
    snapshot_dispositions = {
        str(item.get("key")): item.get("disposition")
        for item in snapshots
        if isinstance(item, Mapping)
    }
    if snapshot_dispositions != {
        "readiness_receipt": "MATCH",
        "authorization_review": "OBSERVED_FIXED_PATH",
    }:
        return False
    for group in (
        "readiness_artifact_identities",
        "source_identities",
        "predecessor_input_identities",
    ):
        entries = envelope.get(group)
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            return False
        if any(
            not isinstance(item, Mapping) or item.get("disposition") != "MATCH"
            for item in entries
        ):
            return False
    return True


def _contract_diagnostic(code: str, **details: object) -> dict[str, Any]:
    return {"type": "ContractError", "code": code, **details}


def _exception_diagnostic(exc: Exception) -> dict[str, str]:
    message = str(exc)
    encoded_message = message.encode()
    message_digest = hashlib.sha256(encoded_message)
    return {
        "type": type(exc).__name__,
        "message_sha256": message_digest.hexdigest(),
    }


def _reviewed_readiness_identity(
    *,
    root: Path,
    readiness_receipt_path: Path,
    review: Mapping[str, Any] | None,
) -> dict[str, Any]:
    expected: dict[str, Any] = {
        "path": _logical_path(root, readiness_receipt_path),
    }
    if review is None:
        return expected
    sha256 = review.get("reviewed_readiness_receipt_sha256")
    if isinstance(sha256, str):
        expected["sha256"] = sha256
    reviewed_inputs = review.get("reviewed_inputs")
    if isinstance(reviewed_inputs, Sequence) and not isinstance(
        reviewed_inputs, (str, bytes)
    ):
        for raw in reviewed_inputs:
            if not isinstance(raw, Mapping) or raw.get("path") != expected["path"]:
                continue
            size = raw.get("size")
            if isinstance(size, int) and not isinstance(size, bool):
                expected["size"] = size
            break
    return expected


def _review_binding_is_exact(
    *,
    review: Mapping[str, Any],
    expected_receipt: Mapping[str, Any],
) -> bool:
    if not _identity_is_complete(expected_receipt):
        return False
    reviewed_inputs = review.get("reviewed_inputs")
    if not isinstance(reviewed_inputs, Sequence) or isinstance(
        reviewed_inputs, (str, bytes)
    ):
        return False
    matches = [
        raw
        for raw in reviewed_inputs
        if isinstance(raw, Mapping)
        and raw.get("path") == expected_receipt.get("path")
    ]
    if len(matches) != 1:
        return False
    reviewed_identity = matches[0]
    return all(
        reviewed_identity.get(field) == expected_receipt.get(field)
        for field in ("path", "sha256", "size")
    )


def _exact_readiness_artifact_contract(
    receipt: Mapping[str, Any],
    *,
    root: Path,
    readiness_dir: Path,
) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any] | None]:
    raw_artifacts = receipt.get("artifacts")
    if not isinstance(raw_artifacts, Mapping):
        return None, _contract_diagnostic(
            "DG25_S3A_READINESS_ARTIFACT_CONTRACT_NOT_MAPPING"
        )
    if set(raw_artifacts) != set(READINESS_ARTIFACT_FILENAMES):
        return None, _contract_diagnostic(
            "DG25_S3A_READINESS_ARTIFACT_KEY_SET_DRIFT"
        )
    result: dict[str, dict[str, Any]] = {}
    for key, filename in READINESS_ARTIFACT_FILENAMES.items():
        expected_path = _logical_path(root, readiness_dir / filename)
        identity = _exact_identity(raw_artifacts.get(key), expected_path=expected_path)
        if identity is None:
            return None, _contract_diagnostic(
                "DG25_S3A_READINESS_ARTIFACT_IDENTITY_NOT_EXACT",
                key=key,
            )
        result[key] = identity
    return result, None


def _exact_source_contract(
    source_manifest: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any] | None]:
    raw_files = source_manifest.get("files")
    if not isinstance(raw_files, Sequence) or isinstance(raw_files, (str, bytes)):
        return None, _contract_diagnostic(
            "DG25_S3A_SOURCE_IDENTITY_LIST_NOT_SEQUENCE"
        )
    observed_paths = [
        raw.get("path") if isinstance(raw, Mapping) else None
        for raw in raw_files
    ]
    if observed_paths != list(READINESS_SOURCE_PATHS):
        return None, _contract_diagnostic("DG25_S3A_SOURCE_PATH_SET_OR_ORDER_DRIFT")
    result: dict[str, dict[str, Any]] = {}
    for path, raw in zip(READINESS_SOURCE_PATHS, raw_files, strict=True):
        identity = _exact_identity(raw, expected_path=path)
        if identity is None:
            return None, _contract_diagnostic(
                "DG25_S3A_SOURCE_IDENTITY_NOT_EXACT",
                path=path,
            )
        result[path] = identity
    return result, None


def _exact_predecessor_contract(
    action_manifest: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any] | None]:
    result: dict[str, dict[str, Any]] = {}
    for key, expected_path in PREDECESSOR_INPUT_PATHS.items():
        identity = _exact_identity(
            action_manifest.get(key),
            expected_path=expected_path,
        )
        if identity is None:
            return None, _contract_diagnostic(
                "DG25_S3A_PREDECESSOR_IDENTITY_NOT_EXACT",
                key=key,
            )
        result[key] = identity
    return result, None


def _exact_identity(
    value: object,
    *,
    expected_path: str,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    identity = {
        "path": value.get("path"),
        "sha256": value.get("sha256"),
        "size": value.get("size"),
    }
    if identity["path"] != expected_path or not _identity_is_complete(identity):
        return None
    return identity


def _identity_is_complete(value: Mapping[str, Any]) -> bool:
    sha256 = value.get("sha256")
    size = value.get("size")
    return (
        isinstance(value.get("path"), str)
        and isinstance(sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", sha256) is not None
        and isinstance(size, int)
        and not isinstance(size, bool)
        and size >= 0
    )


def _observe_identity(
    *,
    root: Path,
    path: Path,
    expected: Mapping[str, Any],
    category: str,
    key: str,
    allowed_root: Path,
    require_direct_parent: bool = False,
) -> dict[str, Any]:
    expected_identity = dict(expected)
    observed_identity: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    resolved_path: Path | None = None
    try:
        if not _lexically_within(root, path):
            disposition = "OUTSIDE_WORKSPACE_REQUEST"
        else:
            try:
                resolved_path = path.resolve(strict=True)
            except FileNotFoundError:
                disposition = "MISSING"
            except OSError as exc:
                disposition = "UNREADABLE_PATH"
                error = _exception_diagnostic(exc)
            else:
                allowed_resolved = allowed_root.resolve(strict=False)
                if not _path_is_relative_to(resolved_path, allowed_resolved):
                    disposition = "OUTSIDE_PRESCRIBED_DIRECTORY"
                elif resolved_path != path.absolute():
                    disposition = "SYMLINK_PATH_SUBSTITUTION"
                elif (
                    require_direct_parent
                    and resolved_path.parent != allowed_resolved
                ):
                    disposition = "NOT_RESOLVED_DIRECT_CHILD"
                elif not resolved_path.is_file():
                    disposition = "NOT_A_FILE"
                else:
                    observed_identity = {
                        "path": _logical_path(root, path),
                        "sha256": _sha256(resolved_path),
                        "size": resolved_path.stat().st_size,
                    }
                    if not _identity_is_complete(expected_identity):
                        disposition = "OBSERVED_FIXED_PATH"
                    elif observed_identity == expected_identity:
                        disposition = "MATCH"
                    else:
                        disposition = "MISMATCH"
    except OSError as exc:
        disposition = "UNREADABLE"
        error = _exception_diagnostic(exc)
    return {
        "category": category,
        "key": key,
        "path": _logical_path(root, path),
        "expected_identity": expected_identity,
        "observed_identity": observed_identity,
        "resolved_path": (
            _logical_path(root, resolved_path)
            if resolved_path is not None and _resolved_within(root, resolved_path)
            else str(resolved_path) if resolved_path is not None else None
        ),
        "disposition": disposition,
        "observation_error": error,
    }


def _try_read_json_after_observation(
    path: Path,
    observation: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if observation.get("observed_identity") is None:
        disposition = str(observation.get("disposition"))
        encoded_disposition = disposition.encode()
        disposition_digest = hashlib.sha256(encoded_disposition)
        return None, {
            "type": "ObservationError",
            "message_sha256": disposition_digest.hexdigest(),
        }
    return _try_read_json(path)


def _try_read_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    try:
        return _read_json(path), None
    except (OSError, UnicodeError, TypeError, json.JSONDecodeError) as exc:
        return None, _exception_diagnostic(exc)


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _lexically_within(root: Path, path: Path) -> bool:
    absolute_path = path.absolute()
    absolute_root = root.absolute()
    try:
        absolute_path.relative_to(absolute_root)
    except ValueError:
        return False
    return True


def _logical_path(root: Path, path: Path) -> str:
    absolute_root = root.absolute()
    absolute_path = path.absolute()
    try:
        relative_path = absolute_path.relative_to(absolute_root)
        return relative_path.as_posix()
    except ValueError:
        return str(absolute_path)


def _validate_attempt_identity_envelope(context: S3AFailureContext) -> None:
    envelope = dict(context.attempt_identity_envelope)
    observed_digest = envelope.pop("envelope_digest", None)
    if observed_digest != _canonical_sha256(envelope):
        raise ValueError("DG25_S3A_ATTEMPT_IDENTITY_ENVELOPE_DIGEST_MISMATCH")
    if envelope.get("frozen_before_covered_prechecks") is not True:
        raise ValueError("DG25_S3A_ATTEMPT_IDENTITY_ENVELOPE_NOT_PREFROZEN")
    if envelope.get("inventory_preallocated_before_reads") is not True:
        raise ValueError("DG25_S3A_ATTEMPT_IDENTITY_INVENTORY_NOT_PREALLOCATED")
    if envelope.get("complete_inventory_frozen") is not True:
        raise ValueError("DG25_S3A_ATTEMPT_IDENTITY_ENVELOPE_INCOMPLETE")
    if envelope.get("capture_frozen_before_execute") is not True:
        raise ValueError("DG25_S3A_ATTEMPT_CAPTURE_NOT_FROZEN")
    if envelope.get("capture_complete") is not True:
        raise ValueError("DG25_S3A_ATTEMPT_CAPTURE_INCOMPLETE")
    if not _capture_is_complete(envelope):
        raise ValueError("DG25_S3A_ATTEMPT_CAPTURE_DISPOSITION_MISMATCH")
    expected_counts = {
        "snapshot_identities": 2,
        "readiness_artifact_identities": 10,
        "source_identities": 18,
        "predecessor_input_identities": 2,
        "input_identities": 12,
    }
    if any(len(envelope.get(key, [])) != count for key, count in expected_counts.items()):
        raise ValueError("DG25_S3A_ATTEMPT_IDENTITY_COUNT_MISMATCH")
    if (
        context.source_identities != envelope.get("source_identities")
        or context.input_identities != envelope.get("input_identities")
        or context.snapshot_identities != envelope.get("snapshot_identities")
    ):
        raise ValueError("DG25_S3A_ATTEMPT_IDENTITY_CONTEXT_DRIFT")


def _execute(
    args: argparse.Namespace,
    context: S3AFailureContext,
    *,
    root: Path,
) -> int:
    _validate_attempt_identity_envelope(context)
    paths = _validate_top_level_paths(args, root=root)
    context.first_failing_gate = "DG25_S3A_OUTPUT_DIRECTORY_PRECHECK"
    output = paths["output"]
    _ensure_output_absent(output)

    snapshot_index = {
        str(item["key"]): item
        for item in context.snapshot_identities
    }
    context.first_failing_gate = "DG25_S3A_INDEPENDENT_AUTHORIZATION_PRECHECK"
    review = _read_observation_bound_json(
        snapshot_index["authorization_review"],
        root=root,
        allowed_root=root / REVIEW_ROOT,
    )
    context.first_failing_gate = "DG25_S3A_READINESS_RECEIPT_PRECHECK"
    readiness_dir = paths["readiness_dir"]
    receipt = _read_observation_bound_json(
        snapshot_index["readiness_receipt"],
        root=root,
        allowed_root=readiness_dir,
        require_direct_parent=True,
    )
    receipt_identity = snapshot_index["readiness_receipt"]["observed_identity"]
    if (
        not isinstance(receipt_identity, Mapping)
        or review.get("reviewed_readiness_receipt_sha256")
        != receipt_identity.get("sha256")
    ):
        raise ValueError("DG25_S3A_REVIEW_RECEIPT_BINDING_MISMATCH")
    if review.get("verdict") != "AUTHORIZE_S3A_E1_LABEL_FREE_ALL_ARM_GENERATION":
        raise ValueError("DG25_S3A_REVIEW_VERDICT_NOT_AUTHORIZED")
    authorization = _mapping(
        review.get("s3a_execution_authorization"), "S3A execution authorization"
    )
    if receipt.get("status") != (
        "PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION"
    ):
        raise ValueError("DG25_S3A_READINESS_RECEIPT_NOT_PASS")
    if receipt.get("run_id") != str(args.readiness_run_id):
        raise ValueError("DG25_S3A_READINESS_RECEIPT_RUN_ID_MISMATCH")
    artifacts = _mapping(receipt.get("artifacts"), "readiness artifacts")
    if set(artifacts) != set(READINESS_ARTIFACT_FILENAMES):
        raise ValueError("DG25_S3A_READINESS_ARTIFACT_SET_MISMATCH")
    context.first_failing_gate = "DG25_S3A_READINESS_ARTIFACT_IDENTITY_PRECHECK"
    _validate_artifact_identities(
        artifacts,
        root=root,
        readiness_dir=readiness_dir,
    )

    delta = _read_bound_artifact(
        root, readiness_dir, artifacts, "execution_delta_manifest"
    )
    protocol = _read_bound_artifact(
        root, readiness_dir, artifacts, "all_arm_seal_protocol"
    )
    source_manifest = _read_bound_artifact(
        root, readiness_dir, artifacts, "source_manifest"
    )
    action_manifest = _read_bound_artifact(
        root, readiness_dir, artifacts, "e1_action_role_manifest"
    )
    ledger_schema = _read_bound_artifact(
        root, readiness_dir, artifacts, "cost_ledger_schema"
    )
    stop_contract = _read_bound_artifact(
        root, readiness_dir, artifacts, "stop_evaluation_contract"
    )
    context.first_failing_gate = "DG25_S3A_SOURCE_IDENTITY_PRECHECK"
    _validate_current_sources(source_manifest, root=root)

    expected = _mapping(
        stop_contract.get("s3a_generation_bindings"), "S3A expected bindings"
    )

    observed_bindings = _derive_s3a_bindings(
        delta=delta,
        protocol=protocol,
        source_manifest=source_manifest,
        action_manifest=action_manifest,
        ledger_schema=ledger_schema,
    )
    pre_observations: dict[str, Any] = {
        **observed_bindings,
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
        "output_directory_exists": False,
        "arm_output_count": 0,
        "all_arm_seal_present": False,
    }
    context.first_failing_gate = "DG25_S3A_PRE_GENERATION_STOP_GATE"
    pre_gate = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="PRE_GENERATION",
        observations=pre_observations,
        expected_bindings=expected,
    )
    _require_gate_pass(pre_gate, "DG25_S3A_PRE_GENERATION_STOP_GATE_FAILED")

    context.first_failing_gate = "DG25_S3A_PREDECESSOR_INPUT_IDENTITY_PRECHECK"
    probe_identity = _mapping(
        action_manifest.get("official_probe_collection"), "probe collection identity"
    )
    product_identity = _mapping(
        action_manifest.get("product_trace_collection"), "product collection identity"
    )
    probes = _read_identity_bound_json(
        probe_identity,
        root=root,
        expected_path=PREDECESSOR_INPUT_PATHS["official_probe_collection"],
    )
    product = _read_identity_bound_json(
        product_identity,
        root=root,
        expected_path=PREDECESSOR_INPUT_PATHS["product_trace_collection"],
    )
    e1 = _mapping(delta.get("E1"), "E1 delta")
    configs = [
        E1ArmConfigV01.model_validate(item)
        for item in _mapping_sequence(e1.get("arm_configs"), "E1 configs")
    ]
    common_bindings = {
        "execution_delta_manifest_digest": observed_bindings[
            "execution_delta_manifest_digest"
        ],
        "all_arm_seal_protocol_digest": observed_bindings[
            "all_arm_seal_protocol_digest"
        ],
        "readiness_source_manifest_digest": observed_bindings[
            "readiness_source_manifest_digest"
        ],
        "case_order_digest": observed_bindings["case_order_digest"],
        "config_set_digest": observed_bindings["e1_config_set_digest"],
        "input_binding_digest": observed_bindings[
            "e1_common_pool_binding_digest"
        ],
        "caps_digest": observed_bindings["e1_caps_digest"],
        "cost_ledger_schema_digest": observed_bindings[
            "cost_ledger_schema_digest"
        ],
        "final_k": observed_bindings["final_k"],
    }
    context.first_failing_gate = "DG25_S3A_GENERATION_AND_E1_ALL_ARM_SEAL"
    bundle = generate_e1_all_arm_bundle(
        configs=configs,
        action_manifest=action_manifest,
        official_probe_collection=probes,
        product_traces=product,
        common_execution_bindings=common_bindings,
        independent_authorization=authorization,
        expected_authorization_bindings=expected,
        frozen_case_order=_string_sequence(delta.get("case_order"), "frozen case order"),
        generator_source_sha256=observed_bindings["s3a_generator_source_sha256"],
        sealer_source_sha256=observed_bindings["s3a_sealer_source_sha256"],
        runner_source_sha256=observed_bindings["s3a_runner_source_sha256"],
    )
    outputs = _mapping(bundle.get("arm_outputs"), "E1 arm outputs")
    seal = _mapping(bundle.get("e1_all_arm_seal"), "E1 all-arm seal")
    post_observations = {
        **pre_observations,
        "arm_output_count": len(outputs),
        "all_arm_seal_present": True,
        "arm_order_exact": list(outputs) == list(e1["arm_order"]),
        "output_content_digests_recomputed": all(
            isinstance(value, Mapping)
            and _output_digest(value) == value.get("output_digest")
            for value in outputs.values()
        )
        and len(outputs) == 11,
        "execution_bindings_recomputed": all(
            isinstance(value, Mapping) and _binding_digest(value) is True
            for value in outputs.values()
        )
        and len(outputs) == 11,
        "all_arm_seal_recomputed": _seal_digest(seal) is True,
        "partial_duplicate_or_reordered_outputs": 0,
        "case_order_exact": _all_arm_case_orders_match(
            outputs,
            expected_case_order=_string_sequence(
                delta.get("case_order"), "frozen case order"
            ),
        ),
    }
    context.first_failing_gate = "DG25_S3A_POST_GENERATION_STOP_GATE"
    post_gate = evaluate_generation_gate(
        stage="S3A_E1_LABEL_FREE",
        phase="POST_GENERATION",
        observations=post_observations,
        expected_bindings=expected,
    )
    _require_gate_pass(post_gate, "DG25_S3A_POST_GENERATION_STOP_GATE_FAILED")

    context.first_failing_gate = "DG25_S3A_ATOMIC_OUTPUT_WRITE"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{args.run_id}.", dir=output.parent))
    output_artifact = {
        key: value for key, value in bundle.items() if key != "e1_all_arm_seal"
    }
    _write_json(temporary / "e1-label-free-arm-outputs.json", output_artifact)
    _write_json(temporary / "e1-all-arm-seal.json", seal)
    temporary.rename(output)
    print(
        json.dumps(
            {
                "status": "PASS_DG25_S3A_E1_LABEL_FREE_ALL_ARM_SEALED",
                "output": str(output.relative_to(root)),
                "e1_all_arm_seal_digest": seal["seal_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


def _execute_with_failure_ledger(
    *,
    execute: Callable[[], int],
    context: S3AFailureContext,
    root: Path,
    argv: Sequence[str],
) -> int:
    """Execute once and append exactly one immutable failure record on error."""

    try:
        return execute()
    except Exception as exc:
        _record_s3a_failure(
            root=root,
            argv=argv,
            context=context,
            error=exc,
        )
        raise


def _record_s3a_failure(
    *,
    root: Path,
    argv: Sequence[str],
    context: S3AFailureContext,
    error: Exception,
) -> dict[str, Any]:
    current_time = datetime.now(UTC)
    recorded = current_time.astimezone()
    run_id = _safe_failure_component(str(context.config_identity.get("run_id", "run")))
    failure_id = (
        f"{run_id}-failure-{recorded.strftime('%Y%m%dT%H%M%S%f%z')}"
    )
    failure_dir = root / "var/dg25/failures" / failure_id
    failure_dir.mkdir(parents=True, exist_ok=False)
    stdout_path = failure_dir / "stdout.txt"
    stderr_path = failure_dir / "stderr.txt"
    stdout_path.write_text("", encoding="utf-8")
    formatted_exception = traceback.format_exception(
        type(error), error, error.__traceback__
    )
    separator = ""
    stderr_path.write_text(
        separator.join(formatted_exception),
        encoding="utf-8",
    )
    receipt_path = failure_dir / "receipt.json"
    receipt = {
        "schema": "milai.dg25.failure-receipt.v0.1",
        "failure_id": failure_id,
        "recorded_at": recorded.isoformat(timespec="microseconds"),
        "command": {
            "argv": list(argv),
            "cwd": str(Path.cwd()),
            "exit_code": 1,
        },
        "config_identity": dict(context.config_identity),
        "source_identities": [dict(item) for item in context.source_identities],
        "input_identities": [dict(item) for item in context.input_identities],
        "snapshot_identities": [dict(item) for item in context.snapshot_identities],
        "attempt_identity_envelope": dict(context.attempt_identity_envelope),
        "attempt_identity_envelope_digest": context.attempt_identity_envelope.get(
            "envelope_digest"
        ),
        "stdout": _file_identity(root, stdout_path),
        "stderr": _file_identity(root, stderr_path),
        "first_failing_gate": context.first_failing_gate,
        "root_cause": f"{type(error).__name__}: {error}",
        "general_fix": (
            "Repair the first failing gate, reseal affected identities, and invoke "
            "the official path once with a new unique run ID; never auto-retry."
        ),
        "fresh_rerun_id": "REQUIRES_NEW_UNIQUE_RUN_ID_AFTER_ROOT_CAUSE_FIX",
        "automatic_retries": 0,
    }
    _write_json(receipt_path, receipt)
    receipt_identity = _file_identity(root, receipt_path)
    index_record = {
        "failure_id": failure_id,
        "first_failing_gate": context.first_failing_gate,
        "receipt": receipt_identity,
        "recorded_at": receipt["recorded_at"],
    }
    index_path = root / "var/dg25/failure-index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    encoded_record = (
        json.dumps(
            index_record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    encoded = encoded_record.encode("utf-8")
    descriptor = os.open(
        index_path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o644,
    )
    try:
        written = os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if written != len(encoded):
        raise OSError("DG25_S3A_FAILURE_INDEX_SHORT_APPEND")
    return receipt_identity


def _safe_failure_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "-", value)
    sanitized = sanitized.strip("-")
    return sanitized or "dg25-s3a"


def _ensure_output_absent(output: Path) -> None:
    if output.is_symlink() or output.exists():
        raise FileExistsError("DG25_S3A_EXISTING_OUTPUT_DIRECTORY_REJECTED")


def _require_gate_pass(gate: Mapping[str, Any], error_code: str) -> None:
    if gate.get("passed") is not True:
        raise ValueError(error_code)


def _derive_s3a_bindings(
    *,
    delta: Mapping[str, Any],
    protocol: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    action_manifest: Mapping[str, Any],
    ledger_schema: Mapping[str, Any],
) -> dict[str, Any]:
    e1 = _mapping(delta.get("E1"), "E1 delta")
    implementation = _mapping(
        delta.get("presealed_s3a_implementation"), "S3A implementation"
    )
    generator = _mapping(implementation.get("generator"), "S3A generator")
    sealer = _mapping(implementation.get("sealer"), "S3A sealer")
    runner = _mapping(implementation.get("runner"), "S3A runner")
    pool = _mapping(delta.get("e1_common_pool"), "E1 common pool")
    return {
        "execution_delta_manifest_digest": delta["manifest_digest"],
        "all_arm_seal_protocol_digest": protocol["protocol_digest"],
        "readiness_source_manifest_digest": source_manifest["source_manifest_digest"],
        "case_order_digest": delta["case_order_digest"],
        "e1_action_manifest_digest": action_manifest["manifest_digest"],
        "e1_config_set_digest": e1["config_set_digest"],
        "e1_common_pool_binding_digest": pool["pool_binding_digest"],
        "e1_channel_query_identities_digest": pool[
            "channel_query_identities_digest"
        ],
        "e1_caps_digest": e1["caps_digest"],
        "cost_ledger_schema_digest": ledger_schema["cost_ledger_schema_digest"],
        "s3a_generator_source_sha256": generator["sha256"],
        "s3a_sealer_source_sha256": sealer["sha256"],
        "s3a_runner_source_sha256": runner["sha256"],
        "final_k": pool["final_k"],
        "expected_arm_count": len(e1["arm_order"]),
    }


def _validate_artifact_identities(
    artifacts: Mapping[str, Any],
    *,
    root: Path,
    readiness_dir: Path,
) -> None:
    if set(artifacts) != set(READINESS_ARTIFACT_FILENAMES):
        raise ValueError("DG25_S3A_READINESS_ARTIFACT_SET_MISMATCH")
    for key, filename in READINESS_ARTIFACT_FILENAMES.items():
        path = readiness_dir / filename
        expected_path = _logical_path(root, path)
        identity = _exact_identity(artifacts.get(key), expected_path=expected_path)
        if identity is None:
            raise ValueError("DG25_S3A_READINESS_ARTIFACT_PATH_DRIFT")
        observation = _observe_identity(
            root=root,
            path=path,
            expected=identity,
            category="READINESS_ARTIFACT",
            key=key,
            allowed_root=readiness_dir,
            require_direct_parent=True,
        )
        if observation.get("disposition") != "MATCH":
            raise ValueError("DG25_S3A_READINESS_ARTIFACT_IDENTITY_DRIFT")


def _read_bound_artifact(
    root: Path,
    readiness_dir: Path,
    artifacts: Mapping[str, Any],
    key: str,
) -> dict[str, Any]:
    filename = READINESS_ARTIFACT_FILENAMES[key]
    expected_path = _logical_path(root, readiness_dir / filename)
    identity = _exact_identity(artifacts.get(key), expected_path=expected_path)
    if identity is None:
        raise ValueError("DG25_S3A_ARTIFACT_DIRECTORY_BINDING_MISMATCH")
    return _read_identity_bound_json(
        identity,
        root=root,
        expected_path=expected_path,
        allowed_root=readiness_dir,
        require_direct_parent=True,
    )


def _validate_current_sources(
    manifest: Mapping[str, Any],
    *,
    root: Path,
) -> None:
    if manifest.get("fresh") is not True:
        raise ValueError("DG25_S3A_SOURCE_MANIFEST_NOT_FRESH")
    expected, contract_error = _exact_source_contract(manifest)
    if expected is None or contract_error is not None:
        raise ValueError("DG25_S3A_SOURCE_PATH_SET_OR_ORDER_DRIFT")
    for source_path in READINESS_SOURCE_PATHS:
        observation = _observe_identity(
            root=root,
            path=root / source_path,
            expected=expected[source_path],
            category="SOURCE",
            key=source_path,
            allowed_root=root,
        )
        if observation.get("disposition") != "MATCH":
            raise ValueError("DG25_S3A_SOURCE_IDENTITY_DRIFT")


def _read_identity_bound_json(
    identity: Mapping[str, Any],
    *,
    root: Path,
    expected_path: str,
    allowed_root: Path | None = None,
    require_direct_parent: bool = False,
) -> dict[str, Any]:
    exact_identity = _exact_identity(identity, expected_path=expected_path)
    if exact_identity is None:
        raise ValueError("DG25_S3A_INPUT_PATH_IDENTITY_DRIFT")
    path = root / expected_path
    observation = _observe_identity(
        root=root,
        path=path,
        expected=exact_identity,
        category="BOUND_INPUT",
        key=expected_path,
        allowed_root=allowed_root or root,
        require_direct_parent=require_direct_parent,
    )
    if observation.get("disposition") != "MATCH":
        raise ValueError("DG25_S3A_INPUT_IDENTITY_DRIFT")
    return _read_json(path)


def _read_observation_bound_json(
    captured: Mapping[str, Any],
    *,
    root: Path,
    allowed_root: Path,
    require_direct_parent: bool = False,
) -> dict[str, Any]:
    observed = captured.get("observed_identity")
    expected_path = captured.get("path")
    if not isinstance(observed, Mapping) or not isinstance(expected_path, str):
        raise TypeError("DG25_S3A_CAPTURED_INPUT_IDENTITY_INCOMPLETE")
    return _read_identity_bound_json(
        observed,
        root=root,
        expected_path=expected_path,
        allowed_root=allowed_root,
        require_direct_parent=require_direct_parent,
    )


def _output_digest(value: Mapping[str, Any]) -> str:
    material = dict(value)
    material.pop("output_digest", None)
    return _canonical_sha256(material)


def _all_arm_case_orders_match(
    outputs: Mapping[str, Any],
    *,
    expected_case_order: Sequence[str],
) -> bool:
    expected = list(expected_case_order)
    if len(outputs) != 11:
        return False
    for value in outputs.values():
        if not isinstance(value, Mapping):
            return False
        observed = [
            str(item["query_id"])
            for item in _mapping_sequence(value.get("records"), "arm records")
        ]
        if observed != expected:
            return False
    return True


def _binding_digest(value: Mapping[str, Any]) -> bool:
    binding = value.get("execution_binding")
    if not isinstance(binding, Mapping):
        return False
    material = dict(binding)
    observed = material.pop("execution_binding_digest", None)
    return isinstance(observed, str) and observed == _canonical_sha256(material)


def _seal_digest(value: Mapping[str, Any]) -> bool:
    material = dict(value)
    observed = material.pop("seal_digest", None)
    return isinstance(observed, str) and observed == _canonical_sha256(material)


def _canonical_sha256(value: object) -> str:
    canonical_json = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded = canonical_json.encode("utf-8")
    digest = hashlib.sha256(encoded)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _file_identity(root: Path, path: Path) -> dict[str, Any]:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    relative_path = resolved_path.relative_to(resolved_root)
    return {
        "path": str(relative_path),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _sha256(path: Path) -> str:
    content = path.read_bytes()
    digest = hashlib.sha256(content)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _mapping_sequence(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{label} items must be mappings")
        result.append(item)
    return result


def _string_sequence(value: object, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    if not all(isinstance(item, str) for item in value):
        raise TypeError(f"{label} items must be strings")
    return list(value)


if __name__ == "__main__":
    raise SystemExit(main())
