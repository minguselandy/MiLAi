#!/usr/bin/env python3
"""Consume one fresh authorization and score sealed DG-25 E1/E2 arms once."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import traceback
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__)
ROOT = _SCRIPT_PATH.resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (str(ROOT), str(RUNTIME_SRC)):
    if value not in sys.path:
        sys.path.insert(0, value)

from evals.dg25.arm_sealing import (
    E1_ARM_ORDER,
    E2_ARM_ORDER,
    validate_combined_all_arm_seal,
)
from evals.dg25.effect_scorer import score_all_arms
from evals.dg25.s4b_readiness import (
    CURRENT_SCORER_SHA256,
    FIXED_INPUT_PATHS,
    S4B_OUTPUT_ROOT,
    S4B_READINESS_ROOT,
    S4B_REVIEW_ROOT,
    build_s4b_source_manifest,
    file_identity,
    read_json,
    validate_label_free_bundle,
    validate_readiness_receipt,
)
from evals.dg25.s4b_scoring import (
    S4B_OFFICIAL_RUN_ID,
    SCORED_ARTIFACT_FILENAMES,
    build_scored_reports,
    validate_scoring_review,
)
from evals.dg25.stop_gate import evaluate_score_gate

SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
FAILURE_INDEX = Path("var/dg25/failure-index.jsonl")
FAILURE_ROOT = Path("var/dg25/failures")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--readiness-run-id", required=True)
    parser.add_argument("--authorization-review", type=Path, required=True)
    args = parser.parse_args()
    argv = list(sys.argv)
    try:
        return run_once(
            run_id=str(args.run_id),
            readiness_run_id=str(args.readiness_run_id),
            authorization_review=args.authorization_review,
            root=ROOT,
        )
    except Exception as exc:
        _record_failure(root=ROOT, argv=argv, error=exc)
        raise


def run_once(
    *,
    run_id: str,
    readiness_run_id: str,
    authorization_review: Path,
    root: Path,
) -> int:
    """Validate all pre-score material before opening either registry."""

    root = root.resolve()
    if run_id != S4B_OFFICIAL_RUN_ID:
        raise ValueError("DG25_S4B_OFFICIAL_RUN_ID_MISMATCH")
    output = _validated_output(root, run_id)
    if output.is_symlink() or output.exists():
        raise FileExistsError("DG25_S4B_EXISTING_OUTPUT_REJECTED")
    readiness_dir = _validated_readiness_dir(root, readiness_run_id)
    review_path = _validated_review_path(root, authorization_review)

    receipt_path = readiness_dir / "receipt.json"
    receipt = read_json(receipt_path)
    validate_readiness_receipt(
        root=root, readiness_dir=readiness_dir, receipt=receipt
    )
    reviewed_receipt_identity = file_identity(root, receipt_path)
    request = _mapping(receipt.get("authorization_request"), "authorization request")
    _validate_request(request)
    expected_bindings = _mapping(
        request.get("authorization_bindings"), "authorization bindings"
    )

    execution = read_json(readiness_dir / "execution-manifest.json")
    amendment = read_json(
        readiness_dir / "scorer-source-compatibility-amendment.json"
    )
    source_manifest = read_json(readiness_dir / "source-manifest.json")
    _validate_live_readiness(
        root=root,
        receipt=receipt,
        execution=execution,
        amendment=amendment,
        source_manifest=source_manifest,
        request=request,
        expected_bindings=expected_bindings,
    )

    review = read_json(review_path)
    authorization = validate_scoring_review(
        review,
        expected_request_digest=str(request["request_digest"]),
        expected_authorization_bindings=expected_bindings,
        reviewed_readiness_receipt=reviewed_receipt_identity,
    )
    review_identity = file_identity(root, review_path)

    e1_bundle = read_json(root / FIXED_INPUT_PATHS["e1_bundle"])
    e1_seal = read_json(root / FIXED_INPUT_PATHS["e1_seal"])
    e2_bundle = read_json(root / FIXED_INPUT_PATHS["e2_bundle"])
    e2_seal = read_json(root / FIXED_INPUT_PATHS["e2_seal"])
    combined_seal = read_json(root / FIXED_INPUT_PATHS["combined_seal"])
    e1_outputs = validate_label_free_bundle(
        bundle=e1_bundle,
        seal=e1_seal,
        block="E1",
        arm_order=E1_ARM_ORDER,
    )
    e2_outputs = validate_label_free_bundle(
        bundle=e2_bundle,
        seal=e2_seal,
        block="E2",
        arm_order=E2_ARM_ORDER,
    )
    arm_outputs = {**e1_outputs, **e2_outputs}
    base_readiness_bindings = _mapping(
        combined_seal.get("readiness_bindings"), "combined readiness bindings"
    )
    validate_combined_all_arm_seal(
        seal=combined_seal,
        e1_seal=e1_seal,
        e2_seal=e2_seal,
        arm_outputs=arm_outputs,
        readiness_bindings=base_readiness_bindings,
    )

    score_gate_bindings = {
        **dict(base_readiness_bindings),
        "e1_all_arm_seal_digest": e1_seal["seal_digest"],
        "e2_all_arm_seal_digest": e2_seal["seal_digest"],
        "combined_all_arm_seal_digest": combined_seal["seal_digest"],
        "independent_scoring_authorization_digest": authorization[
            "authorization_digest"
        ],
    }
    pre_score_gate = evaluate_score_gate(
        phase="PRE_SCORE",
        observations=_score_gate_observations(
            score_gate_bindings,
            phase="PRE_SCORE",
            all_arm_count=len(arm_outputs),
        ),
        expected_bindings=score_gate_bindings,
    )
    amendment_checks = {
        "amendment_digest_matches_authorization": amendment.get("amendment_digest")
        == authorization.get("scorer_source_amendment_digest"),
        "effective_source_matches_authorization": CURRENT_SCORER_SHA256
        == authorization.get("effect_scorer_source_sha256"),
        "base_sealed_source_preserved": base_readiness_bindings.get(
            "effect_scorer_source_sha256"
        )
        == amendment.get("base_scorer_source", {}).get("sha256"),
        "registry_content_unopened": True,
    }
    pre_score_gate["scorer_source_amendment_checks"] = amendment_checks
    pre_score_gate["passed"] = bool(pre_score_gate["passed"]) and all(
        amendment_checks.values()
    )
    pre_score_gate["disposition"] = (
        "PROCEED_TO_AUTHORIZED_REGISTRY_OPEN"
        if pre_score_gate["passed"]
        else "STOP"
    )
    if pre_score_gate["passed"] is not True:
        raise ValueError("DG25_S4B_PRE_SCORE_GATE_STOP")

    # This is the first content access to scorer-only registries in DG-25 S4B.
    gold_identity, gold_registry = _open_authorized_registry(
        root=root,
        path=Path(str(expected_bindings["gold_registry_path"])),
        expected_sha256=str(expected_bindings["gold_registry_sha256"]),
        expected_size=int(expected_bindings["gold_registry_size"]),
    )
    proof_identity, proof_registry = _open_authorized_registry(
        root=root,
        path=Path(str(expected_bindings["proof_registry_path"])),
        expected_sha256=str(expected_bindings["proof_registry_sha256"]),
        expected_size=int(expected_bindings["proof_registry_size"]),
    )

    score = score_all_arms(
        combined_seal=combined_seal,
        arm_outputs=arm_outputs,
        gold_registry=gold_registry,
        proof_registry=proof_registry,
        authorization=authorization,
        expected_contract_digest=str(
            expected_bindings["effect_scorer_contract_digest"]
        ),
        expected_readiness_bindings=base_readiness_bindings,
    )
    reports = build_scored_reports(score)
    arm_scores = _mapping(score.get("arm_scores"), "arm scores")
    post_observations = _score_gate_observations(
        score_gate_bindings,
        phase="POST_SCORE",
        all_arm_count=len(arm_outputs),
    )
    post_observations["accepted_binding_precision"] = min(
        float(_mapping(value, "arm score")["accepted_binding_precision"])
        for value in arm_scores.values()
    )
    post_observations["wrong_complete"] = sum(
        int(_mapping(value, "arm score")["wrong_complete"])
        for value in arm_scores.values()
    )
    post_score_gate = evaluate_score_gate(
        phase="POST_SCORE",
        observations=post_observations,
        expected_bindings=score_gate_bindings,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=output.parent))
    artifact_materials = {
        **reports,
        "pre_score_gate": pre_score_gate,
        "post_score_gate": post_score_gate,
    }
    artifact_identities: dict[str, dict[str, Any]] = {}
    try:
        for key, filename in SCORED_ARTIFACT_FILENAMES.items():
            material = artifact_materials[key]
            path = temporary / filename
            _write_json(path, material)
            identity = file_identity(root, path)
            identity["path"] = (output / filename).relative_to(root).as_posix()
            artifact_identities[key] = identity
        passed = post_score_gate["passed"] is True
        receipt_material: dict[str, Any] = {
            "schema": "milai.dg25.s4b-score-receipt.v0.1",
            "run_id": run_id,
            "status": (
                "PASS_DG25_S4B_JOINT_E1_E2_POST_SEAL_SCORE"
                if passed
                else "STOP_DG25_S4B_POST_SCORE_GATE"
            ),
            "readiness_receipt": reviewed_receipt_identity,
            "independent_review": review_identity,
            "authorization_digest": authorization["authorization_digest"],
            "authorization_consumed": True,
            "combined_all_arm_seal": file_identity(
                root, root / FIXED_INPUT_PATHS["combined_seal"]
            ),
            "combined_all_arm_seal_digest": combined_seal["seal_digest"],
            "scorer_source_amendment_digest": amendment["amendment_digest"],
            "effective_scorer_source_sha256": CURRENT_SCORER_SHA256,
            "registry_identities": {
                "gold_equivalence_registry": gold_identity,
                "proof_obligation_registry": proof_identity,
            },
            "artifacts": artifact_identities,
            "score_digest": score["score_digest"],
            "score_execution_count": 1,
            "registry_content_open_count": 2,
            "labels_loaded_after_pre_score_gate": True,
            "post_score_gate_passed": passed,
            "post_score_adaptation": False,
            "reader_model_provider_controller_calls": 0,
            "formal_holdout_consumed": False,
            "candidate_default": False,
            "canonical_mutations": 0,
            "automatic_retries": 0,
        }
        receipt_material["receipt_digest"] = canonical_sha256(receipt_material)
        _write_json(temporary / "receipt.json", receipt_material)
        temporary.rename(output)
    except Exception:
        _remove_partial_directory(temporary)
        raise

    print(
        json.dumps(
            {
                "status": receipt_material["status"],
                "output": output.relative_to(root).as_posix(),
                "score_digest": score["score_digest"],
                "post_score_gate_passed": receipt_material[
                    "post_score_gate_passed"
                ],
            },
            sort_keys=True,
        )
    )
    if receipt_material["post_score_gate_passed"] is not True:
        raise RuntimeError("DG25_S4B_POST_SCORE_GATE_STOP_AFTER_OUTPUT_SEALED")
    return 0


def _validate_request(request: Mapping[str, Any]) -> None:
    material = dict(request)
    observed = material.pop("request_digest", None)
    if (
        request.get("schema")
        != "milai.dg25.s4b-scoring-authorization-request.v0.1"
        or request.get("scope") != "S4B_JOINT_E1_E2_POST_SEAL_SCORE"
        or request.get("official_s4b_run_id") != S4B_OFFICIAL_RUN_ID
        or observed != canonical_sha256(material)
    ):
        raise ValueError("DG25_S4B_AUTHORIZATION_REQUEST_INVALID")
    bindings = _mapping(request.get("authorization_bindings"), "request bindings")
    if request.get("authorization_bindings_digest") != canonical_sha256(dict(bindings)):
        raise ValueError("DG25_S4B_AUTHORIZATION_REQUEST_BINDING_DIGEST_MISMATCH")


def _validate_live_readiness(
    *,
    root: Path,
    receipt: Mapping[str, Any],
    execution: Mapping[str, Any],
    amendment: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    request: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> None:
    current_source = build_s4b_source_manifest(root)
    failure_identity = file_identity(root, root / FAILURE_INDEX)
    if (
        source_manifest != current_source
        or execution.get("authorization_bindings") != dict(expected_bindings)
        or execution.get("authorization_request_digest") != request.get("request_digest")
        or execution.get("scorer_source_amendment_digest")
        != amendment.get("amendment_digest")
        or receipt.get("failure_index_snapshot", {}).get("sha256")
        != failure_identity["sha256"]
        or receipt.get("failure_index_snapshot", {}).get("line_count")
        != _nonempty_line_count(root / FAILURE_INDEX)
    ):
        raise ValueError("DG25_S4B_READINESS_STALE_OR_DRIFTED")
    amendment_material = dict(amendment)
    observed = amendment_material.pop("amendment_digest", None)
    effective = _mapping(amendment.get("effective_scorer_source"), "effective scorer")
    if (
        observed != canonical_sha256(amendment_material)
        or effective.get("sha256") != CURRENT_SCORER_SHA256
        or expected_bindings.get("scorer_source_amendment_digest") != observed
    ):
        raise ValueError("DG25_S4B_SCORER_SOURCE_AMENDMENT_INVALID")


def _score_gate_observations(
    bindings: Mapping[str, Any],
    *,
    phase: str,
    all_arm_count: int,
) -> dict[str, Any]:
    observations: dict[str, Any] = {
        **dict(bindings),
        "identity_drift": 0,
        "label_before_seal": 0,
        "pool_k_mismatch": 0,
        "invalid_plan_count": 0,
        "budget_overflow": 0,
        "boundary_drift": 0,
        "forbidden_calls": 0,
        "post_score_adaptation": 0,
        "e1_all_arm_seal_present": True,
        "e2_all_arm_seal_present": True,
        "combined_all_arm_seal_present": True,
        "all_arm_output_count": all_arm_count,
        "independent_scoring_authorized": True,
        "automatic_retries": 0,
    }
    if phase == "PRE_SCORE":
        observations.update(
            {
                "stage": "S4B_PRE_SCORE",
                "labels_loaded": False,
                "scoring_executed": False,
            }
        )
    else:
        observations.update(
            {
                "stage": "S4B_POST_SCORE",
                "labels_loaded": True,
                "scoring_executed": True,
                "score_execution_count": 1,
            }
        )
    return observations


def _open_authorized_registry(
    *, root: Path, path: Path, expected_sha256: str, expected_size: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = file_identity(root, root / path)
    if identity["sha256"] != expected_sha256 or identity["size"] != expected_size:
        raise ValueError("DG25_S4B_AUTHORIZED_REGISTRY_IDENTITY_MISMATCH")
    return identity, read_json(root / path)


def _validated_output(root: Path, run_id: str) -> Path:
    if SAFE_COMPONENT.fullmatch(run_id) is None:
        raise ValueError("DG25_S4B_RUN_ID_NOT_SAFE")
    parent = root / S4B_OUTPUT_ROOT
    if parent.resolve(strict=False) != parent.absolute():
        raise ValueError("DG25_S4B_OUTPUT_ROOT_SYMLINK_OR_DRIFT")
    output = parent / run_id
    if output.absolute().parent != parent.absolute():
        raise ValueError("DG25_S4B_OUTPUT_NOT_DIRECT_CHILD")
    return output


def _validated_readiness_dir(root: Path, run_id: str) -> Path:
    if SAFE_COMPONENT.fullmatch(run_id) is None:
        raise ValueError("DG25_S4B_READINESS_RUN_ID_NOT_SAFE")
    path = root / S4B_READINESS_ROOT / run_id
    if path.is_symlink() or not path.is_dir():
        raise ValueError("DG25_S4B_READINESS_DIR_INVALID")
    return path


def _validated_review_path(root: Path, requested: Path) -> Path:
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("DG25_S4B_REVIEW_PATH_INVALID")
    path = root / requested
    if path.is_symlink() or not path.is_file():
        raise ValueError("DG25_S4B_REVIEW_NOT_REGULAR_FILE")
    review_root = (root / S4B_REVIEW_ROOT).resolve(strict=False)
    try:
        path.resolve(strict=True).relative_to(review_root)
    except ValueError as exc:
        raise ValueError("DG25_S4B_REVIEW_OUTSIDE_REVIEW_ROOT") from exc
    return path


def _record_failure(*, root: Path, argv: Sequence[str], error: Exception) -> None:
    recorded = datetime.now().astimezone()
    failure_id = f"dg25-s4b-official-run-{recorded.strftime('%Y%m%d-%H%M%S')}"
    directory = root / FAILURE_ROOT / failure_id
    directory.mkdir(parents=True, exist_ok=False)
    stderr = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    stdout_path = directory / "stdout.txt"
    stderr_path = directory / "stderr.txt"
    stdout_path.write_text("\n", encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    receipt: dict[str, Any] = {
        "schema": "milai.dg25.failure-receipt.v0.1",
        "failure_id": failure_id,
        "first_failing_gate": "DG25_S4B_OFFICIAL_ONE_SHOT_SCORE",
        "recorded_at": recorded.isoformat(timespec="seconds"),
        "command": {"argv": list(argv), "cwd": str(root), "exit_code": 1},
        "root_cause": f"{type(error).__name__}: {error}",
        "general_fix": (
            "Do not automatically retry. Preserve any published one-shot output and "
            "require a new failure-bound readiness and independent authorization only "
            "if the terminal contract permits another attempt."
        ),
        "automatic_retries": 0,
        "source_identities": [],
        "snapshot_identities": [],
        "stdout": file_identity(root, stdout_path),
        "stderr": file_identity(root, stderr_path),
    }
    receipt_path = directory / "receipt.json"
    _write_json(receipt_path, receipt)
    receipt_identity = file_identity(root, receipt_path)
    index_record = {
        "failure_id": failure_id,
        "first_failing_gate": receipt["first_failing_gate"],
        "receipt": receipt_identity,
        "recorded_at": receipt["recorded_at"],
    }
    index_path = root / FAILURE_INDEX
    payload = (json.dumps(index_record, separators=(",", ":"), sort_keys=True) + "\n").encode()
    descriptor = os.open(index_path, os.O_WRONLY | os.O_APPEND)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_partial_directory(path: Path) -> None:
    if not path.exists() or path.is_symlink():
        return
    for child in path.iterdir():
        if child.is_file() and not child.is_symlink():
            child.unlink()
    path.rmdir()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _nonempty_line_count(path: Path) -> int:
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
