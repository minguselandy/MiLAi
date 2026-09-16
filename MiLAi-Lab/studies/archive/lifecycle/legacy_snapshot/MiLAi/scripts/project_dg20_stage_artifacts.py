#!/usr/bin/env python3
"""Project immutable DG-20 S1/S4 runs into the standard S6 artifact layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_S1_SOURCE = ROOT / "var/dg20/s1/dg20-s1-official-channel-oracle-20260828-003"
DEFAULT_S4_SOURCE = ROOT / "var/dg20/s4/dg20-s4-product-faithful-20260828-002"

_S1_LOSS_DEPTH = {
    "CAPABILITY_UNAVAILABLE": 1,
    "NO_FEASIBLE_REQUIREMENT_ACTION": 2,
    "CHANNEL_RETRIEVAL_BOUND_MISS": 3,
    "FUSION_CUTOFF": 4,
    "BINDING_REJECTED_OR_POSSIBLE": 5,
    "SUFFICIENCY_OR_OPERATOR_NOT_READY": 6,
    "OPERATOR_READY": 7,
}
_S1_LEDGER_STAGE = {
    "CAPABILITY_UNAVAILABLE": "CAPABILITY",
    "NO_FEASIBLE_REQUIREMENT_ACTION": "APPLICABILITY_GATE",
    "CHANNEL_RETRIEVAL_BOUND_MISS": "CHANNEL",
    "FUSION_CUTOFF": "FUSION",
    "BINDING_REJECTED_OR_POSSIBLE": "BINDING",
    "SUFFICIENCY_OR_OPERATOR_NOT_READY": "SUFFICIENCY",
    "OPERATOR_READY": "SCORER",
}


class DG20ArtifactProjectionError(RuntimeError):
    """An immutable stage cannot be projected without changing its facts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG20ArtifactProjectionError(f"expected JSON object: {path}")
    return value


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DG20ArtifactProjectionError(f"{field} must be an object")
    return value


def _objects(value: object, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DG20ArtifactProjectionError(f"{field} must be an object list")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise DG20ArtifactProjectionError(f"refusing to overwrite artifact: {path}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _copy_immutable(source: Path, destination: Path) -> None:
    if destination.exists():
        raise DG20ArtifactProjectionError(f"refusing to overwrite artifact: {destination}")
    shutil.copyfile(source, destination)
    if _sha256(source) != _sha256(destination):
        raise DG20ArtifactProjectionError("byte-identical artifact projection failed")


def build_s1_loss_ledger(
    sealed: Mapping[str, Any], score: Mapping[str, Any], *, run_id: str
) -> dict[str, Any]:
    product = _object(sealed.get("product"), "S1 product")
    product_cases = {
        str(case.get("case_id")): case
        for case in _objects(product.get("cases"), "S1 product cases")
    }
    records: list[dict[str, Any]] = []
    for scored_case in _objects(score.get("cases"), "S1 scored cases"):
        case_id = str(scored_case.get("case_id"))
        product_case = product_cases.get(case_id)
        if product_case is None:
            raise DG20ArtifactProjectionError("S1 score/product case mismatch")
        baseline = _object(product_case.get("baseline"), "S1 baseline")
        state = _object(baseline.get("requirement_state"), "S1 RequirementState")
        product_requirements = {
            str(item.get("requirement_id")): item
            for item in _objects(product_case.get("requirements"), "S1 requirements")
        }
        for requirement in _objects(scored_case.get("requirements"), "S1 scored requirements"):
            requirement_id = str(requirement.get("requirement_id"))
            product_requirement = product_requirements.get(requirement_id)
            if product_requirement is None:
                raise DG20ArtifactProjectionError("S1 score/product requirement mismatch")
            scored_arms = _objects(requirement.get("arms"), "S1 scored arms")
            if not scored_arms:
                raise DG20ArtifactProjectionError("S1 unresolved requirement has no oracle arm")
            best = max(
                enumerate(scored_arms),
                key=lambda pair: (
                    _S1_LOSS_DEPTH.get(str(pair[1].get("first_loss_stage")), 0),
                    -pair[0],
                ),
            )[1]
            reason = str(best.get("first_loss_stage"))
            if reason not in _S1_LEDGER_STAGE:
                raise DG20ArtifactProjectionError("S1 arm has unknown first-loss stage")
            product_arms = {
                str(item.get("channel")): item
                for item in _objects(product_requirement.get("arms"), "S1 product arms")
            }
            product_arm = product_arms.get(str(best.get("channel")))
            if product_arm is None:
                raise DG20ArtifactProjectionError("S1 score/product arm mismatch")
            records.append(
                {
                    "case_id": case_id,
                    "requirement_id": requirement_id,
                    "requirement_state_digest": str(state.get("state_digest")),
                    "capability_digest": str(product_arm.get("capability_digest")),
                    "first_loss_stage": _S1_LEDGER_STAGE[reason],
                    "reason_code": (
                        "NO_LOSS_OPERATOR_READY" if reason == "OPERATOR_READY" else reason
                    ),
                    "channel": best.get("channel"),
                    "raw_rank": best.get("raw_rank"),
                    "fusion_rank": best.get("fusion_rank"),
                    "cutoff_rank": (
                        best.get("fusion_rank") if best.get("cutoff_survival") else None
                    ),
                    "answer_bearing_candidate_present": bool(best.get("answer_bearing_recovered")),
                    "binding_status": best.get("binding_statuses"),
                    "sufficiency_effect": reason == "OPERATOR_READY",
                    "scorer_truth_loaded_after_seal": True,
                }
            )
    expected = int(score.get("current_unresolved_requirement_count", -1))
    if len(records) != expected:
        raise DG20ArtifactProjectionError("S1 first-loss ledger denominator drifted")
    keys = [(item["case_id"], item["requirement_id"]) for item in records]
    if len(keys) != len(set(keys)):
        raise DG20ArtifactProjectionError("S1 requirement has multiple first-loss records")
    return {
        "schema": "milai.dg20.s1-acquisition-loss-ledger.v0.1",
        "run_id": run_id,
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "record_count": len(records),
        "records": records,
        "all_records_have_exactly_one_first_loss": True,
        "oracle_arm_classification_coverage": score.get("hard_gate", {}).get(
            "first_loss_classification_coverage"
        ),
    }


def build_s4_loss_ledger(sealed: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for case in _objects(sealed.get("cases"), "S4 cases"):
        case_id = str(case.get("case_id"))
        product = _object(case.get("product"), "S4 product arm")
        initial = _object(product.get("initial_requirement_state"), "S4 initial state")
        decision = _object(product.get("decision"), "S4 decision")
        final = _object(product.get("final"), "S4 final execution")
        final_state = _object(final.get("requirement_state"), "S4 final state")
        final_requirements = {
            str(item.get("requirement_id")): item
            for item in _objects(final_state.get("requirements"), "S4 final requirements")
        }
        binding_trace = _object(final.get("binding_trace"), "S4 binding trace")
        selected = decision.get("selected_action")
        selected_action = _object(selected, "S4 selected action") if selected is not None else None
        selected_target = (
            str(selected_action.get("target_requirement_id"))
            if selected_action is not None
            else None
        )
        selected_channel = selected_action.get("channel") if selected_action else None
        for requirement in _objects(initial.get("requirements"), "S4 initial requirements"):
            if requirement.get("status") == "SATISFIED":
                continue
            requirement_id = str(requirement.get("requirement_id"))
            final_requirement = final_requirements.get(requirement_id)
            if final_requirement is None:
                raise DG20ArtifactProjectionError("S4 final RequirementState lost a requirement")
            traces_raw = binding_trace.get(requirement_id, [])
            traces = _objects(traces_raw, "S4 requirement binding trace")
            statuses = sorted({str(item.get("status")) for item in traces})
            final_status = str(final_requirement.get("status"))
            if final_status == "SATISFIED":
                stage, reason = "SCORER", "NO_LOSS_REQUIREMENT_SATISFIED"
            elif final_status == "COMPLETENESS_PROOF_MISSING":
                stage, reason = "COMPLETENESS_PROOF", "COMPLETENESS_PROOF_MISSING"
            elif selected_target != requirement_id:
                stage, reason = "CAPABILITY", "NO_ACTION_SELECTED_FOR_REQUIREMENT"
            elif "MATCH" not in statuses:
                stage, reason = "BINDING", "NO_ACCEPTED_REQUIREMENT_BINDING"
            else:
                stage, reason = "SUFFICIENCY", "OPERATOR_NOT_READY_AFTER_FULL_RECOMPUTE"
            records.append(
                {
                    "case_id": case_id,
                    "requirement_id": requirement_id,
                    "requirement_state_digest": str(initial.get("state_digest")),
                    "capability_digest": str(decision.get("acquisition_capability_digest")),
                    "first_loss_stage": stage,
                    "reason_code": reason,
                    "channel": selected_channel if selected_target == requirement_id else None,
                    "raw_rank": None,
                    "fusion_rank": None,
                    "cutoff_rank": None,
                    "answer_bearing_candidate_present": None,
                    "binding_status": statuses,
                    "sufficiency_effect": final_status == "SATISFIED",
                    "scorer_truth_loaded_after_seal": True,
                    "answer_truth_evaluated": False,
                }
            )
    keys = [(item["case_id"], item["requirement_id"]) for item in records]
    if len(keys) != len(set(keys)):
        raise DG20ArtifactProjectionError("S4 requirement has multiple first-loss records")
    return {
        "schema": "milai.dg20.s4-acquisition-loss-ledger.v0.1",
        "run_id": run_id,
        "classification": "LABEL_FREE PRODUCT-FIDELITY / EVALUATION_PLANE",
        "record_count": len(records),
        "records": records,
        "all_records_have_exactly_one_first_loss": all(
            bool(item["first_loss_stage"]) for item in records
        ),
        "answer_truth_evaluated": False,
    }


def project_stage(*, stage: str, run_id: str, source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise DG20ArtifactProjectionError("output exists; choose a fresh projection run ID")
    source_receipt_path = source / "receipt.json"
    source_receipt = _read(source_receipt_path)
    expected_status = {
        "s1": "PASS_S1_OFFICIAL_CHANNEL_ORACLE",
        "s4": "PASS_S4_ONE_PASS_PRODUCT_FAITHFUL_INTEGRATION",
    }[stage]
    if source_receipt.get("status") != expected_status:
        raise DG20ArtifactProjectionError(f"source {stage.upper()} receipt did not pass")
    source_sealed_path = (
        source / "sealed-product-oracle.json"
        if stage == "s1"
        else source / "sealed-product-trace.json"
    )
    source_score_path = source / "score.json"
    source_plan_path = source / "plan.json"
    sealed = _read(source_sealed_path)
    score = _read(source_score_path)
    output.mkdir(parents=True)
    plan_path = output / "plan.json"
    sealed_path = output / "sealed-product-trace.json"
    score_path = output / "score.json"
    ledger_path = output / "acquisition-loss-ledger.json"
    receipt_path = output / "receipt.json"
    plan: dict[str, Any] = {
        "schema": f"milai.dg20.{stage}-artifact-projection-plan.v0.1",
        "run_id": run_id,
        "source_run_id": source_receipt.get("run_id"),
        "source_receipt": _identity(source_receipt_path),
        "mode": "BYTE_IDENTICAL_SEAL_AND_SCORE_PROJECTION",
        "product_replay_performed": False,
        "sealed_product_rewritten": False,
        "scorer_reexecuted": False,
        "formal_holdout_consumed": False,
    }
    if source_plan_path.is_file():
        plan["source_plan"] = _identity(source_plan_path)
    _write(plan_path, plan)
    _copy_immutable(source_sealed_path, sealed_path)
    _copy_immutable(source_score_path, score_path)
    ledger = (
        build_s1_loss_ledger(sealed, score, run_id=run_id)
        if stage == "s1"
        else build_s4_loss_ledger(sealed, run_id=run_id)
    )
    _write(ledger_path, ledger)
    receipt = {
        "schema": f"milai.dg20.{stage}-artifact-projection-receipt.v0.1",
        "run_id": run_id,
        "source_run_id": source_receipt.get("run_id"),
        "status": expected_status,
        "artifact_projection": True,
        "product_replay_performed": False,
        "sealed_product_rewritten": False,
        "scorer_reexecuted": False,
        "formal_holdout_consumed": False,
        "source_receipt": _identity(source_receipt_path),
        "source_sealed_product": _identity(source_sealed_path),
        "source_score": _identity(source_score_path),
        "plan": _identity(plan_path),
        "sealed_product_trace": _identity(sealed_path),
        "score": _identity(score_path),
        "acquisition_loss_ledger": _identity(ledger_path),
        "byte_identical_seal": _sha256(source_sealed_path) == _sha256(sealed_path),
        "byte_identical_score": _sha256(source_score_path) == _sha256(score_path),
        "runner": _identity(Path(__file__)),
    }
    _write(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("s1", "s4"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    source = args.source or (DEFAULT_S1_SOURCE if args.stage == "s1" else DEFAULT_S4_SOURCE)
    output = (args.output_root or ROOT / "var/dg20" / args.stage) / args.run_id
    receipt = project_stage(
        stage=args.stage,
        run_id=args.run_id,
        source=source,
        output=output,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
