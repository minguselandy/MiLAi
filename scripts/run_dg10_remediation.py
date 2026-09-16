from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation

DEFAULT_OUTPUT = ROOT / "docs/reports/DG-10-model-run-authorization-candidate.4-2026-08-22.json"
DEFAULT_POST_R3_OUTPUT = ROOT / (
    "docs/reports/DG-10-model-run-authorization-post-r3-candidate.4-2026-08-22.json"
)


def smoke_preflight(
    *,
    candidate: str,
    r0_r2_aggregate_path: Path | None = None,
    identity_receipt_path: Path | None = None,
) -> dict[str, Any]:
    if candidate != remediation.CANDIDATE:
        raise remediation.RemediationError("candidate identity mismatch")
    result = authorization.evaluate_first_model_authorization(
        phase=authorization.BOOTSTRAP_PHASE,
        planned_model_calls=authorization.BOOTSTRAP_MODEL_CALLS,
        r0_r2_aggregate_path=r0_r2_aggregate_path,
        identity_receipt_path=identity_receipt_path,
        test_access_requested=False,
    )
    return {
        "schema": "milai.dg10.remediation-smoke-preflight.v1",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "phase": "smoke",
        "status": (
            "AUTHORIZED_READY_FOR_T2_EXECUTION"
            if result["authorized"]
            else "BLOCKED_BEFORE_MODEL_CALL"
        ),
        "provider_requests": 0,
        "model_outputs_opened": False,
        "test_access_authorized": False,
        "authorization": result,
        "next_required_action": (
            "EXECUTE_T2_24_ATTEMPTS"
            if result["authorized"]
            else "OBTAIN_ARTIFACT_BOUND_AI_ACCEPTANCE_RECEIPTS_FOR_R0_R2_ON_CANDIDATE_4"
        ),
    }


def post_r3_preflight(
    *,
    candidate: str,
    planned_model_calls: int,
    r0_r2_aggregate_path: Path | None = None,
    r3_stage_receipt_path: Path | None = None,
    identity_receipt_path: Path | None = None,
) -> dict[str, Any]:
    if candidate != remediation.CANDIDATE:
        raise remediation.RemediationError("candidate identity mismatch")
    result = authorization.evaluate_first_model_authorization(
        phase=authorization.POST_R3_PHASE,
        planned_model_calls=planned_model_calls,
        r0_r2_aggregate_path=r0_r2_aggregate_path,
        post_r3_stage_receipt_path=r3_stage_receipt_path,
        identity_receipt_path=identity_receipt_path,
        test_access_requested=False,
    )
    return {
        "schema": "milai.dg10.post-r3-model-preflight.v1",
        "candidate_id": remediation.CANDIDATE,
        "phase": authorization.POST_R3_PHASE,
        "status": (
            "AUTHORIZED_READY_FOR_POST_R3_EXECUTION"
            if result["authorized"]
            else "BLOCKED_BEFORE_MODEL_CALL"
        ),
        "provider_requests": 0,
        "model_outputs_opened": False,
        "test_access_authorized": False,
        "authorization": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="DG-10 remediation phase runner")
    parser.add_argument("--phase", choices=("smoke", "post-r3"), required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--r0-r2-aggregate", type=Path)
    parser.add_argument("--identity-receipt", type=Path)
    parser.add_argument("--r3-stage-receipt", type=Path)
    parser.add_argument("--planned-model-calls", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    aggregate = (
        args.r0_r2_aggregate.resolve()
        if args.r0_r2_aggregate is not None
        else None
    )
    identities = (
        args.identity_receipt.resolve()
        if args.identity_receipt is not None
        else None
    )
    if args.phase == "smoke":
        if args.planned_model_calls is not None or args.r3_stage_receipt is not None:
            parser.error("smoke phase does not accept post-R3 arguments")
        report = smoke_preflight(
            candidate=args.candidate,
            r0_r2_aggregate_path=aggregate,
            identity_receipt_path=identities,
        )
        output = (args.output or DEFAULT_OUTPUT).resolve()
    else:
        if args.planned_model_calls is None or args.r3_stage_receipt is None:
            parser.error(
                "post-r3 phase requires --planned-model-calls and --r3-stage-receipt"
            )
        report = post_r3_preflight(
            candidate=args.candidate,
            planned_model_calls=args.planned_model_calls,
            r0_r2_aggregate_path=aggregate,
            r3_stage_receipt_path=args.r3_stage_receipt.resolve(),
            identity_receipt_path=identities,
        )
        output = (args.output or DEFAULT_POST_R3_OUTPUT).resolve()
    remediation.atomic_write_new(output, remediation.encoded_json(report))
    print(json.dumps({"status": report["status"], "provider_requests": 0}, sort_keys=True))
    expected_status = (
        "AUTHORIZED_READY_FOR_T2_EXECUTION"
        if args.phase == "smoke"
        else "AUTHORIZED_READY_FOR_POST_R3_EXECUTION"
    )
    if report["status"] != expected_status:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
