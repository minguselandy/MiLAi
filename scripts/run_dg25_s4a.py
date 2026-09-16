#!/usr/bin/env python3
"""Run one independently authorized, label-free DG-25 S4A E2 generation."""

from __future__ import annotations

import argparse
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

from milai.domain.requirement_state import canonical_sha256

from evals.dg25.arm_sealing import (
    COMBINED_SEAL_READINESS_BINDING_FIELDS,
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    build_combined_all_arm_seal,
    validate_combined_all_arm_seal,
)
from evals.dg25.routing_ablation import E2ArmConfigV01
from evals.dg25.s4a_generator import (
    generate_e2_all_arm_bundle,
    validate_s4a_authorization,
)
from evals.dg25.s4a_readiness import (
    FIXED_INPUT_PATHS,
    READINESS_ARTIFACT_FILENAMES,
    REVIEW_ROOT,
    S4A_OFFICIAL_RUN_ID,
    S4A_OUTPUT_ROOT,
    S4A_READINESS_ROOT,
    build_s4a_source_manifest,
    file_identity,
    read_json,
    validate_and_order_e1_bundle,
    validate_readiness_receipt,
)

SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
REVIEW_SCHEMA = "milai.dg25.s4a-independent-review.v0.1"
REVIEW_VERDICT = "AUTHORIZE_S4A_E2_LABEL_FREE_ALL_ARM_AND_COMBINED_SEAL"


@dataclass
class FailureContext:
    first_failing_gate: str
    config_identity: dict[str, Any]
    source_identities: list[dict[str, Any]] = field(default_factory=list)
    input_identities: list[dict[str, Any]] = field(default_factory=list)
    snapshot_identities: list[dict[str, Any]] = field(default_factory=list)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--readiness-run-id", required=True)
    parser.add_argument("--authorization-review", type=Path, required=True)
    args = parser.parse_args()
    return run_s4a_once(args=args, root=ROOT, argv=tuple(sys.argv))


def run_s4a_once(
    *,
    args: argparse.Namespace,
    root: Path,
    argv: Sequence[str],
) -> int:
    context = FailureContext(
        first_failing_gate="DG25_S4A_TOP_LEVEL_PATH_PRECHECK",
        config_identity={
            "run_id": str(args.run_id),
            "readiness_run_id": str(args.readiness_run_id),
            "authorization_review": str(args.authorization_review),
        },
    )
    return _execute_with_failure_ledger(
        execute=lambda: _execute(args=args, context=context, root=root.resolve()),
        context=context,
        root=root.resolve(),
        argv=argv,
    )


def _execute(
    *,
    args: argparse.Namespace,
    context: FailureContext,
    root: Path,
) -> int:
    paths = validate_top_level_paths(args=args, root=root)
    output = paths["output"]
    if output.is_symlink() or output.exists():
        raise FileExistsError("DG25_S4A_EXISTING_OUTPUT_DIRECTORY_REJECTED")

    context.first_failing_gate = "DG25_S4A_READINESS_RECEIPT_IDENTITY_PRECHECK"
    readiness_receipt_identity = file_identity(root, paths["readiness_receipt"])
    readiness_receipt = read_json(paths["readiness_receipt"])
    artifact_identities = validate_readiness_receipt(
        root=root,
        readiness_dir=paths["readiness_dir"],
        receipt=readiness_receipt,
    )
    context.snapshot_identities.append(readiness_receipt_identity)
    context.input_identities.extend(artifact_identities.values())

    context.first_failing_gate = "DG25_S4A_AUTHORIZATION_REVIEW_PRECHECK"
    review_identity = file_identity(root, paths["review"])
    review = read_json(paths["review"])
    context.snapshot_identities.append(review_identity)

    artifacts = {
        key: read_json(paths["readiness_dir"] / filename)
        for key, filename in READINESS_ARTIFACT_FILENAMES.items()
    }
    execution_manifest = artifacts["execution_manifest"]
    source_manifest = artifacts["source_manifest"]
    stop_contract = artifacts["stop_contract"]
    validation_report = artifacts["validation_report"]
    _validate_readiness_materials(
        execution_manifest=execution_manifest,
        source_manifest=source_manifest,
        stop_contract=stop_contract,
        validation_report=validation_report,
    )
    expected_bindings = _mapping(
        execution_manifest.get("authorization_bindings"),
        "authorization bindings",
    )
    context.first_failing_gate = "DG25_S4A_OFFICIAL_RUN_ID_BINDING_PRECHECK"
    validate_official_run_id_binding(
        run_id=str(args.run_id),
        expected_bindings=expected_bindings,
        execution_manifest=execution_manifest,
        stop_contract=stop_contract,
    )
    combined_readiness_bindings = resolve_combined_seal_readiness_bindings(
        execution_manifest=execution_manifest,
        stop_contract=stop_contract,
        expected_authorization_bindings=expected_bindings,
    )
    authorization = validate_independent_review(
        review=review,
        readiness_receipt_identity=readiness_receipt_identity,
        expected_bindings=expected_bindings,
    )
    validate_s4a_authorization(
        authorization=authorization,
        expected_bindings=expected_bindings,
    )

    context.first_failing_gate = "DG25_S4A_CURRENT_SOURCE_IDENTITY_PRECHECK"
    current_source_manifest = build_s4a_source_manifest(root)
    if current_source_manifest != source_manifest:
        raise ValueError("DG25_S4A_CURRENT_SOURCE_MANIFEST_DRIFT")
    context.source_identities.extend(
        dict(item)
        for item in _mapping_sequence(source_manifest.get("files"), "source files")
    )

    context.first_failing_gate = "DG25_S4A_FIXED_INPUT_IDENTITY_PRECHECK"
    fixed_expected = _mapping(
        execution_manifest.get("fixed_input_identities"), "fixed inputs"
    )
    fixed_observed: dict[str, dict[str, Any]] = {}
    for key, relative in FIXED_INPUT_PATHS.items():
        observed = file_identity(root, root / relative)
        if observed != dict(_mapping(fixed_expected.get(key), key)):
            raise ValueError(f"DG25_S4A_FIXED_INPUT_IDENTITY_DRIFT:{key}")
        fixed_observed[key] = observed
    context.input_identities.extend(fixed_observed.values())
    if dict(_mapping(execution_manifest.get("failure_index_snapshot"), "failure")) != {
        **fixed_observed["failure_index"],
        "line_count": _nonempty_line_count(root / FIXED_INPUT_PATHS["failure_index"]),
    }:
        raise ValueError("DG25_S4A_FAILURE_INDEX_SNAPSHOT_DRIFT")

    context.first_failing_gate = "DG25_S4A_PRE_GENERATION_STOP_GATE"
    if (
        stop_contract.get("pre_generation")
        != {
            **_execution_boundaries(),
            "output_directory_exists": False,
            "e1_all_arm_seal_valid": True,
            "e2_arm_output_count": 0,
            "e2_all_arm_seal_present": False,
            "combined_all_arm_seal_present": False,
        }
        or output.exists()
    ):
        raise ValueError("DG25_S4A_PRE_GENERATION_STOP_GATE_FAILED")

    context.first_failing_gate = "DG25_S4A_LABEL_FREE_INPUT_LOAD"
    delta = read_json(root / FIXED_INPUT_PATHS["execution_delta_manifest"])
    common_input = read_json(root / FIXED_INPUT_PATHS["e2_common_input"])
    product_traces = read_json(root / FIXED_INPUT_PATHS["product_traces"])
    label_free_inputs = read_json(root / FIXED_INPUT_PATHS["label_free_inputs"])
    input_manifest = read_json(root / FIXED_INPUT_PATHS["input_only_manifest"])
    e1_bundle = read_json(root / FIXED_INPUT_PATHS["e1_label_free_bundle"])
    e1_seal = read_json(root / FIXED_INPUT_PATHS["e1_all_arm_seal"])
    e1_outputs = validate_and_order_e1_bundle(e1_bundle, e1_seal)

    e2_delta = _mapping(delta.get("E2"), "E2 delta")
    configs = [
        E2ArmConfigV01.model_validate(item)
        for item in _mapping_sequence(e2_delta.get("arm_configs"), "E2 configs")
    ]
    common_execution_bindings = _mapping(
        execution_manifest.get("common_execution_bindings"),
        "common execution bindings",
    )

    context.first_failing_gate = "DG25_S4A_E2_GENERATION_AND_SEAL"
    bundle = generate_e2_all_arm_bundle(
        configs=configs,
        common_input=common_input,
        product_traces=product_traces,
        label_free_inputs=label_free_inputs,
        input_manifest=input_manifest,
        common_execution_bindings=common_execution_bindings,
        independent_authorization=authorization,
        expected_authorization_bindings=expected_bindings,
        generator_source_sha256=str(expected_bindings["s4a_generator_source_sha256"]),
        sealer_source_sha256=str(expected_bindings["s4a_sealer_source_sha256"]),
        runner_source_sha256=str(expected_bindings["s4a_runner_source_sha256"]),
    )
    e2_outputs_raw = _mapping(bundle.get("arm_outputs"), "E2 outputs")
    if set(e2_outputs_raw) != set(E2_ARM_ORDER):
        raise ValueError("DG25_S4A_E2_OUTPUT_SET_DRIFT")
    e2_outputs = {
        arm_id: _mapping(e2_outputs_raw[arm_id], arm_id) for arm_id in E2_ARM_ORDER
    }
    e2_seal = _mapping(bundle.get("e2_all_arm_seal"), "E2 seal")

    combined_outputs = {
        **{arm_id: e1_outputs[arm_id] for arm_id in E1_ARM_ORDER},
        **{arm_id: e2_outputs[arm_id] for arm_id in E2_ARM_ORDER},
    }
    combined_seal = build_combined_all_arm_seal(
        e1_seal=e1_seal,
        e2_seal=e2_seal,
        arm_outputs=combined_outputs,
        readiness_bindings=combined_readiness_bindings,
    )
    validate_combined_all_arm_seal(
        seal=combined_seal,
        e1_seal=e1_seal,
        e2_seal=e2_seal,
        arm_outputs=combined_outputs,
        readiness_bindings=combined_readiness_bindings,
    )

    context.first_failing_gate = "DG25_S4A_POST_GENERATION_STOP_GATE"
    post_observations = {
        **_execution_boundaries(),
        "e1_all_arm_seal_valid": True,
        "e2_arm_output_count": len(e2_outputs),
        "e2_arm_order_exact": list(bundle.get("arm_order", [])) == list(E2_ARM_ORDER),
        "e2_output_digests_recomputed": all(
            _self_digest(item, "output_digest") for item in e2_outputs.values()
        ),
        "e2_execution_bindings_recomputed": all(
            _self_digest(
                _mapping(item.get("execution_binding"), "execution binding"),
                "execution_binding_digest",
            )
            for item in e2_outputs.values()
        ),
        "e2_all_arm_seal_recomputed": _self_digest(e2_seal, "seal_digest"),
        "combined_all_arm_seal_recomputed": _self_digest(combined_seal, "seal_digest"),
        "partial_duplicate_or_reordered_outputs": 0,
    }
    if post_observations != stop_contract.get("post_generation"):
        raise ValueError("DG25_S4A_POST_GENERATION_STOP_GATE_FAILED")

    context.first_failing_gate = "DG25_S4A_ATOMIC_OUTPUT_WRITE"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{args.run_id}.", dir=output.parent))
    output_bundle = {
        key: value for key, value in bundle.items() if key != "e2_all_arm_seal"
    }
    _write_json(temporary / "e2-label-free-arm-outputs.json", output_bundle)
    _write_json(temporary / "e2-all-arm-seal.json", e2_seal)
    _write_json(temporary / "e1-e2-all-arm-seal.json", combined_seal)
    output_artifacts = {}
    for filename in (
        "e2-label-free-arm-outputs.json",
        "e2-all-arm-seal.json",
        "e1-e2-all-arm-seal.json",
    ):
        identity = file_identity(root, temporary / filename)
        identity["path"] = (output / filename).relative_to(root).as_posix()
        output_artifacts[filename] = identity
    generation_receipt = {
        "schema": "milai.dg25.s4a-generation-receipt.v0.1",
        "run_id": str(args.run_id),
        "status": "PASS_DG25_S4A_E2_LABEL_FREE_ALL_ARM_AND_COMBINED_SEALED",
        "readiness_receipt": readiness_receipt_identity,
        "authorization_review": review_identity,
        "authorization_digest": authorization["authorization_digest"],
        "artifacts": output_artifacts,
        "e1_all_arm_seal_digest": e1_seal["seal_digest"],
        "e2_all_arm_seal_digest": e2_seal["seal_digest"],
        "combined_all_arm_seal_digest": combined_seal["seal_digest"],
        **_execution_boundaries(),
    }
    _write_json(temporary / "generation-receipt.json", generation_receipt)
    temporary.rename(output)

    print(
        json.dumps(
            {
                "status": generation_receipt["status"],
                "output": output.relative_to(root).as_posix(),
                "e2_all_arm_seal_digest": e2_seal["seal_digest"],
                "combined_all_arm_seal_digest": combined_seal["seal_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


def validate_top_level_paths(
    *,
    args: argparse.Namespace,
    root: Path,
) -> dict[str, Path]:
    run_id = str(args.run_id)
    readiness_run_id = str(args.readiness_run_id)
    if not _safe_component(run_id):
        raise ValueError("DG25_S4A_RUN_ID_NOT_SAFE_SINGLE_COMPONENT")
    if not _safe_component(readiness_run_id):
        raise ValueError("DG25_S4A_READINESS_RUN_ID_NOT_SAFE_SINGLE_COMPONENT")
    output_root = root / S4A_OUTPUT_ROOT
    readiness_root = root / S4A_READINESS_ROOT
    review_root = root / REVIEW_ROOT
    for path, code in (
        (output_root, "DG25_S4A_OUTPUT_ROOT_DRIFT"),
        (readiness_root, "DG25_S4A_READINESS_ROOT_DRIFT"),
        (review_root, "DG25_S4A_REVIEW_ROOT_DRIFT"),
    ):
        if path.resolve(strict=False) != path.absolute():
            raise ValueError(code)
    output = output_root / run_id
    readiness_dir = readiness_root / readiness_run_id
    if output.absolute().parent != output_root.absolute():
        raise ValueError("DG25_S4A_OUTPUT_NOT_DIRECT_CHILD")
    if readiness_dir.absolute().parent != readiness_root.absolute():
        raise ValueError("DG25_S4A_READINESS_NOT_DIRECT_CHILD")
    review_arg = Path(str(args.authorization_review))
    if review_arg.is_absolute() or not review_arg.parts or ".." in review_arg.parts:
        raise ValueError("DG25_S4A_AUTHORIZATION_REVIEW_PATH_INVALID")
    review = root / review_arg
    try:
        review.resolve(strict=False).relative_to(review_root.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("DG25_S4A_AUTHORIZATION_REVIEW_OUTSIDE_REVIEW_ROOT") from exc
    if review.is_symlink() or not review.is_file():
        raise ValueError("DG25_S4A_AUTHORIZATION_REVIEW_NOT_REGULAR_FILE")
    if readiness_dir.is_symlink() or not readiness_dir.is_dir():
        raise ValueError("DG25_S4A_READINESS_DIRECTORY_INVALID")
    return {
        "output": output,
        "readiness_dir": readiness_dir,
        "readiness_receipt": readiness_dir / "receipt.json",
        "review": review,
    }


def validate_independent_review(
    *,
    review: Mapping[str, Any],
    readiness_receipt_identity: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> Mapping[str, Any]:
    if (
        review.get("schema") != REVIEW_SCHEMA
        or review.get("verdict") != REVIEW_VERDICT
        or review.get("reviewed_readiness_receipt") != dict(readiness_receipt_identity)
        or review.get("readiness_bindings") != dict(expected_bindings)
        or review.get("readiness_bindings_digest")
        != canonical_sha256(dict(expected_bindings))
    ):
        raise ValueError("DG25_S4A_INDEPENDENT_REVIEW_BINDING_INVALID")
    review_material = dict(review)
    review_digest = review_material.pop("review_digest", None)
    if review_digest != canonical_sha256(review_material):
        raise ValueError("DG25_S4A_INDEPENDENT_REVIEW_DIGEST_MISMATCH")
    authorization = _mapping(review.get("authorization"), "authorization")
    if authorization.get("readiness_bindings") != dict(expected_bindings):
        raise ValueError("DG25_S4A_AUTHORIZATION_READINESS_BINDING_DRIFT")
    return authorization


def resolve_combined_seal_readiness_bindings(
    *,
    execution_manifest: Mapping[str, Any],
    stop_contract: Mapping[str, Any],
    expected_authorization_bindings: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return only the frozen scorer-facing bindings for the combined seal."""

    fields = execution_manifest.get("combined_seal_readiness_binding_fields")
    bindings = _mapping(
        execution_manifest.get("combined_seal_readiness_bindings"),
        "combined seal readiness bindings",
    )
    digest = canonical_sha256(dict(bindings))
    if (
        fields != list(COMBINED_SEAL_READINESS_BINDING_FIELDS)
        or set(bindings) != set(COMBINED_SEAL_READINESS_BINDING_FIELDS)
        or execution_manifest.get("combined_seal_readiness_bindings_digest") != digest
        or expected_authorization_bindings.get(
            "combined_seal_readiness_bindings_digest"
        )
        != digest
        or stop_contract.get("combined_seal_readiness_binding_fields") != fields
        or stop_contract.get("expected_combined_seal_readiness_bindings")
        != dict(bindings)
        or stop_contract.get("expected_combined_seal_readiness_bindings_digest")
        != digest
    ):
        raise ValueError("DG25_S4A_COMBINED_SEAL_SCORER_BINDING_MISMATCH")
    return bindings


def validate_official_run_id_binding(
    *,
    run_id: str,
    expected_bindings: Mapping[str, Any],
    execution_manifest: Mapping[str, Any],
    stop_contract: Mapping[str, Any],
) -> None:
    """Prevent one positive review from being replayed under another output ID."""

    if (
        run_id != S4A_OFFICIAL_RUN_ID
        or expected_bindings.get("official_s4a_run_id") != S4A_OFFICIAL_RUN_ID
        or execution_manifest.get("official_s4a_run_id") != S4A_OFFICIAL_RUN_ID
        or stop_contract.get("official_s4a_run_id") != S4A_OFFICIAL_RUN_ID
    ):
        raise ValueError("DG25_S4A_OFFICIAL_RUN_ID_BINDING_MISMATCH")


def _validate_readiness_materials(
    *,
    execution_manifest: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    stop_contract: Mapping[str, Any],
    validation_report: Mapping[str, Any],
) -> None:
    for value, digest_key, schema, code in (
        (
            execution_manifest,
            "execution_manifest_digest",
            "milai.dg25.s4a-execution-manifest.v0.1",
            "EXECUTION_MANIFEST",
        ),
        (
            source_manifest,
            "source_manifest_digest",
            "milai.dg25.s4a-source-manifest.v0.1",
            "SOURCE_MANIFEST",
        ),
        (
            stop_contract,
            "stop_contract_digest",
            "milai.dg25.s4a-stop-contract.v0.1",
            "STOP_CONTRACT",
        ),
        (
            validation_report,
            "validation_digest",
            "milai.dg25.s4a-readiness-validation.v0.1",
            "VALIDATION_REPORT",
        ),
    ):
        if value.get("schema") != schema:
            raise ValueError(f"DG25_S4A_{code}_SCHEMA_INVALID")
        material = dict(value)
        observed = material.pop(digest_key, None)
        if observed != canonical_sha256(material):
            raise ValueError(f"DG25_S4A_{code}_DIGEST_MISMATCH")
    if (
        validation_report.get("status")
        != "PASS_DG25_S4A_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION"
        or execution_manifest.get("status")
        != "READY_PENDING_FRESH_INDEPENDENT_S4A_AUTHORIZATION"
        or stop_contract.get("expected_authorization_bindings")
        != execution_manifest.get("authorization_bindings")
    ):
        raise ValueError("DG25_S4A_READINESS_STATUS_OR_BINDING_INVALID")


def _execute_with_failure_ledger(
    *,
    execute: Callable[[], int],
    context: FailureContext,
    root: Path,
    argv: Sequence[str],
) -> int:
    try:
        return execute()
    except Exception as error:
        _record_failure(root=root, argv=argv, context=context, error=error)
        raise


def _record_failure(
    *,
    root: Path,
    argv: Sequence[str],
    context: FailureContext,
    error: Exception,
) -> None:
    recorded = datetime.now(UTC).astimezone()
    run_id = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        str(context.config_identity.get("run_id", "dg25-s4a")),
    ).strip("-")
    failure_id = (
        f"{run_id or 'dg25-s4a'}-failure-{recorded.strftime('%Y%m%dT%H%M%S%f%z')}"
    )
    failure_dir = root / "var/dg25/failures" / failure_id
    failure_dir.mkdir(parents=True, exist_ok=False)
    stdout_path = failure_dir / "stdout.txt"
    stderr_path = failure_dir / "stderr.txt"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text(
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        encoding="utf-8",
    )
    receipt = {
        "schema": "milai.dg25.failure-receipt.v0.1",
        "failure_id": failure_id,
        "recorded_at": recorded.isoformat(timespec="microseconds"),
        "command": {"argv": list(argv), "cwd": str(Path.cwd()), "exit_code": 1},
        "config_identity": context.config_identity,
        "source_identities": context.source_identities,
        "input_identities": context.input_identities,
        "snapshot_identities": context.snapshot_identities,
        "stdout": file_identity(root, stdout_path),
        "stderr": file_identity(root, stderr_path),
        "first_failing_gate": context.first_failing_gate,
        "root_cause": f"{type(error).__name__}: {error}",
        "general_fix": (
            "Repair the first failing gate, rebuild quality/readiness/review bindings, "
            "and use a new unique run ID; never retry automatically."
        ),
        "fresh_rerun_id": "REQUIRES_NEW_UNIQUE_RUN_ID_AFTER_ROOT_CAUSE_FIX",
        "automatic_retries": 0,
    }
    receipt_path = failure_dir / "receipt.json"
    _write_json(receipt_path, receipt)
    index_record = {
        "failure_id": failure_id,
        "first_failing_gate": context.first_failing_gate,
        "receipt": file_identity(root, receipt_path),
        "recorded_at": receipt["recorded_at"],
    }
    encoded = (
        json.dumps(
            index_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode()
    index_path = root / "var/dg25/failure-index.jsonl"
    descriptor = os.open(index_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        written = os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if written != len(encoded):
        raise OSError("DG25_S4A_FAILURE_INDEX_SHORT_APPEND")


def _execution_boundaries() -> dict[str, Any]:
    return {
        "labels_loaded": False,
        "registry_content_loaded": False,
        "scoring_executed": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
    }


def _self_digest(value: Mapping[str, Any], digest_key: str) -> bool:
    material = dict(value)
    observed = material.pop(digest_key, None)
    return isinstance(observed, str) and observed == canonical_sha256(material)


def _safe_component(value: str) -> bool:
    return value not in {".", ".."} and SAFE_COMPONENT.fullmatch(value) is not None


def _nonempty_line_count(path: Path) -> int:
    return sum(
        bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _mapping_sequence(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{label} items must be mappings")
        result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
