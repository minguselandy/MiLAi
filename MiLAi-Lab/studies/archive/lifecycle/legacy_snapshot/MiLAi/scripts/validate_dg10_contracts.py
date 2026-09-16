from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
BASE_CONTRACT_DATE = "2026-08-21"
GOAL_VERSION = "0.3.1"
CLAIM_MATRIX = ROOT / "docs/contracts/DG-10-claim-matrix.yaml"
QUALITY_ACCEPTANCE = ROOT / "docs/contracts/DG-10-quality-acceptance.yaml"
GOALS = ROOT / "MiLAi_真实Provider验证与MCP_Agent接入_GOALS.md"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-contracts-current-state-candidate.3.3-{DATE}.json"
)
QUALITY_ASSESSMENT = (
    ROOT / f"docs/reports/DG-10-quality-calibration-assessment-candidate.1-{DATE}.json"
)
QUALITY_ASSESSMENT_SHA256 = (
    "4df3da78254f356d77f687c2acfa66d6dd7a9a8fdeffc880903253057e6d31a9"
)
SOL_DISPOSITION = (
    ROOT / f"docs/reviews/DG-10-sol-final-audit-disposition-candidate.1-{DATE}.json"
)
SOL_DISPOSITION_SHA256 = (
    "d73147e8df49ca27056a878a3ac9bcf0bdcb49668018146abb4ce2a065dc523f"
)

EXPECTED_GATES = {
    "package": {"MCG-00", "MCG-01", "MCG-02"},
    "host": {"OWG-00", "OWG-01", "OWG-02", "OWG-03"},
    "local_provider": {"PVL-00", "PVL-01", "PVL-02", "PVL-03", "PVL-04", "PVL-05"},
    "benchmark": {
        "BMG-00",
        "BMG-00A",
        "BMG-01",
        "BMG-02",
        "BMG-03",
        "BMG-04",
        "BMG-05",
    },
    "controlled_review": {"CRG-00", "CRG-01", "CRG-02"},
    "external_provider_parked": {"PVG-00", "PVG-01", "PVG-02", "PVG-03", "PVG-04"},
}
EXPECTED_STAGE_GATES = {
    "DG10-L1": {"MCG-00", "MCG-01", "MCG-02"},
    "DG10-L2": {"OWG-00", "OWG-01", "OWG-02", "OWG-03"},
    "DG10-L3": {"PVL-00", "PVL-01", "PVL-02", "PVL-03", "PVL-04", "BMG-01"},
    "DG10-L5": {"CRG-00", "CRG-01", "CRG-02"},
}
EXPECTED_L4_GATES = {"BMG-00", "BMG-00A", "BMG-02", "BMG-03", "BMG-04", "BMG-05"}
EXPECTED_ALLOWED_STATES = {
    "NOT_STARTED",
    "AUTHOR_CANDIDATE",
    "REVIEW_REQUIRED",
    "ACCEPTED",
    "REVISE",
    "NOT_APPLICABLE_WITH_RATIONALE",
}
EXPECTED_QUALITY_OUTCOMES = {
    "TARGET_MET",
    "BELOW_TARGET",
    "CHARACTERIZED_ONLY",
    "NOT_APPLICABLE",
}


class ContractError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"{path.relative_to(ROOT).as_posix()} is not a mapping")
    return value


def _as_set(value: object, label: str) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContractError(f"{label} must be a list[str]")
    return set(value)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ContractError(reason)


def _collect_gate_references(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"requires_all_gates", "requires_any_gates"}:
                result.update(_as_set(item, str(key)))
            elif key == "required_gate_states":
                if not isinstance(item, Mapping):
                    raise ContractError("required_gate_states must be a mapping")
                result.update(str(name) for name in item)
            else:
                result.update(_collect_gate_references(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_collect_gate_references(item))
    return result


def _null_required_thresholds(
    value: object, path: str = "$", inherited_required: bool = False
) -> list[str]:
    missing: list[str] = []
    if isinstance(value, Mapping):
        required = inherited_required or value.get("required_before_test") is True
        for key, item in value.items():
            child = f"{path}.{key}"
            if required and key in {"minimum_delta", "maximum", "k"} and item is None:
                missing.append(child)
            if required and key.endswith("_max") and item is None:
                missing.append(child)
            missing.extend(_null_required_thresholds(item, child, required))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            missing.extend(
                _null_required_thresholds(item, f"{path}[{index}]", inherited_required)
            )
    return missing


def _validate_goal_doc() -> dict[str, Any]:
    raw = GOALS.read_text(encoding="utf-8")
    required_fragments = {
        "goal_version": f"文档版本：`{GOAL_VERSION} CANDIDATE",
        "revision_date": f"修订日期：`{BASE_CONTRACT_DATE}`",
        "contract_cleanup_only": "CONTRACT CLEANUP ONLY",
        "l4_l5_not_accepted": "L4/L5 NOT ACCEPTED",
        "external_parked": "OE-F06 OPEN / PARKED",
        "next_chain": "下一执行链（`DG10-12..15`）",
    }
    missing = [
        name for name, fragment in required_fragments.items() if fragment not in raw
    ]
    _require(not missing, "GOALS required fragments missing: " + ",".join(missing))
    return {
        "path": GOALS.relative_to(ROOT).as_posix(),
        "sha256": _sha256(GOALS),
        "required_fragments": sorted(required_fragments),
    }


def _validate_claim_matrix(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(value.get("schema_version") == "1", "claim matrix schema_version drift")
    _require(value.get("goal_id") == "DG-10", "claim matrix goal_id drift")
    _require(
        value.get("goal_contract_version") == GOAL_VERSION,
        "claim matrix version drift",
    )
    _require(value.get("as_of") == DATE, "claim matrix as_of drift")
    boundaries = value.get("boundaries")
    _require(isinstance(boundaries, Mapping), "claim matrix boundaries missing")
    _require(
        boundaries.get("provider_under_test") == "self-hosted-vllm-only",
        "claim matrix provider boundary drift",
    )
    _require(
        boundaries.get("external_provider_gate") == "OE-F06_OPEN_PARKED",
        "claim matrix external provider gate drift",
    )
    _require(
        boundaries.get("codex_role") == "ADVERSARIAL_EVIDENCE_AUDITOR_ONLY",
        "claim matrix Codex role drift",
    )
    _require(
        _as_set(value.get("allowed_stage_states"), "allowed_stage_states")
        == EXPECTED_ALLOWED_STATES,
        "claim matrix stage state set drift",
    )
    _require(
        _as_set(value.get("quality_outcomes"), "quality_outcomes")
        == EXPECTED_QUALITY_OUTCOMES,
        "claim matrix quality outcome set drift",
    )
    catalog = value.get("gate_catalog")
    _require(isinstance(catalog, Mapping), "claim matrix gate_catalog missing")
    for group, expected in EXPECTED_GATES.items():
        _require(
            _as_set(catalog.get(group), f"gate_catalog.{group}") == expected,
            f"claim matrix gate catalog drift: {group}",
        )
    all_gates = set().union(*EXPECTED_GATES.values())
    referenced = _collect_gate_references(value)
    unknown = sorted(referenced - all_gates)
    _require(not unknown, "claim matrix references unknown gates: " + ",".join(unknown))
    stages = value.get("stages")
    _require(isinstance(stages, Mapping), "claim matrix stages missing")
    for stage, expected in EXPECTED_STAGE_GATES.items():
        stage_value = stages.get(stage)
        _require(isinstance(stage_value, Mapping), f"{stage} missing")
        _require(
            _as_set(
                stage_value.get("requires_all_gates"), f"{stage}.requires_all_gates"
            )
            == expected,
            f"{stage} gate mapping drift",
        )
    l4 = stages.get("DG10-L4")
    _require(isinstance(l4, Mapping), "DG10-L4 missing")
    required_gate_states = l4.get("required_gate_states")
    _require(
        isinstance(required_gate_states, Mapping), "DG10-L4 required gates missing"
    )
    _require(
        {str(item) for item in required_gate_states} == EXPECTED_L4_GATES,
        "DG10-L4 gate mapping drift",
    )
    _require(l4.get("requires_quality_outcome") is True, "DG10-L4 outcome gate drift")
    _require(l4.get("current_state") == "REVISE", "DG10-L4 state drift")
    _require(
        l4.get("current_quality_outcome") == "BELOW_TARGET",
        "DG10-L4 outcome drift",
    )
    l5 = stages.get("DG10-L5")
    _require(isinstance(l5, Mapping), "DG10-L5 missing")
    _require(l5.get("current_state") == "REVISE", "DG10-L5 state drift")
    _require(
        l5.get("current_review_outcome")
        == "OPEN_P1_NOT_INDEPENDENTLY_ACCEPTED",
        "DG10-L5 review outcome drift",
    )
    current_evidence = value.get("current_state_evidence")
    _require(isinstance(current_evidence, Mapping), "current state evidence missing")
    _require(
        current_evidence.get("sha256")
        == "a05cbc6f192968dea19003f01ff6dce690eb8a1988e76266d39103d2caa5d6af"
        and current_evidence.get("quality_outcome") == "BELOW_TARGET"
        and current_evidence.get("full_test_execution") == "DENIED_NOT_RUN"
        and current_evidence.get("test_labels_or_outputs_opened") is False,
        "current state evidence drift",
    )
    controlled_review = value.get("controlled_review_evidence")
    _require(
        isinstance(controlled_review, Mapping),
        "controlled review evidence missing",
    )
    _require(
        controlled_review.get("sha256") == SOL_DISPOSITION_SHA256
        and _sha256(SOL_DISPOSITION) == SOL_DISPOSITION_SHA256
        and controlled_review.get("review_candidate_decision")
        == "REVISE_NO_GO_EVIDENCE"
        and controlled_review.get("open_p0_count") == 0
        and controlled_review.get("open_p1_count") == 2
        and controlled_review.get("crg_02") == "NO_GO"
        and controlled_review.get("acceptance_authorized") is False,
        "controlled review evidence drift",
    )
    aggregate = value.get("aggregate_current_status")
    _require(isinstance(aggregate, Mapping), "aggregate status missing")
    _require(aggregate.get("allowed") is False, "aggregate claim must remain blocked")
    reasons = _as_set(aggregate.get("reasons"), "aggregate reasons")
    _require(
        {
            "DG10-L4_REVISE_BELOW_TARGET",
            "BMG-04_SERVING_NOT_ACCEPTED",
            "TIER2_HUMAN_AUDIT_NOT_COMPLETED",
            "FULL_TEST_DENIED_NOT_RUN",
            "DG10-L5_REVISE_OPEN_P1",
            "CRG-02_NO_GO",
            "SOL_REVIEW_TWO_OPEN_P1",
        }.issubset(reasons),
        "aggregate status no longer records current L4/L5 blockers",
    )
    claims = value.get("claims")
    _require(isinstance(claims, Mapping), "claims missing")
    local_candidate = claims.get("LOCAL_VLLM_MCP_AGENT_CANDIDATE")
    _require(
        isinstance(local_candidate, Mapping)
        and local_candidate.get("requires_quality_outcome") == "TARGET_MET"
        and local_candidate.get("requires_external_provider_gate") is False,
        "aggregate claim policy drift",
    )
    policy = value.get("claim_policy")
    _require(isinstance(policy, Mapping), "claim policy missing")
    _require(
        policy.get("frozen_quality_contract_preserve_claims_interpretation")
        == "PRESERVE_UNAFFECTED_AUTHOR_EVIDENCE_AND_STAGE_STATE_ONLY"
        and policy.get("preserved_unaccepted_stage_as_claim") == "DENY",
        "frozen preserve-claims interpretation drift",
    )
    return {
        "path": CLAIM_MATRIX.relative_to(ROOT).as_posix(),
        "sha256": _sha256(CLAIM_MATRIX),
        "gate_catalog_count": sum(len(values) for values in EXPECTED_GATES.values()),
        "referenced_gate_count": len(referenced),
        "aggregate_allowed": False,
        "open_p1_count": 2,
        "status": "PASS_CURRENT_STATE_NO_GO_OPEN_P1",
    }


def _validate_quality_acceptance(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(value.get("schema_version") == "1", "quality schema_version drift")
    _require(value.get("goal_id") == "DG-10", "quality goal_id drift")
    _require(
        value.get("goal_contract_version") == GOAL_VERSION,
        "quality version drift",
    )
    _require(value.get("as_of") == DATE, "quality as_of drift")
    _require(
        value.get("contract_status") == "FROZEN_PRETEST_NO_GO_DEV_BELOW_TARGET",
        "quality contract status drift",
    )
    freeze_policy = value.get("freeze_policy")
    _require(isinstance(freeze_policy, Mapping), "quality freeze_policy missing")
    _require(freeze_policy.get("frozen") is True, "quality thresholds must be frozen")
    _require(
        freeze_policy.get("test_access_authorized") is False,
        "quality test access must remain unauthorized",
    )
    for key in ("frozen_at", "frozen_by"):
        _require(
            isinstance(freeze_policy.get(key), str) and freeze_policy[key],
            f"quality freeze field drift: {key}",
        )
    _require(
        freeze_policy.get("calibration_report_sha256") == QUALITY_ASSESSMENT_SHA256
        and _sha256(QUALITY_ASSESSMENT) == QUALITY_ASSESSMENT_SHA256,
        "quality calibration assessment binding drift",
    )
    _require(
        freeze_policy.get("test_authorization_decision") == "DENY_DEV_BELOW_TARGET"
        and freeze_policy.get("test_labels_or_outputs_opened_at_freeze") is False,
        "quality pre-test NO-GO boundary drift",
    )
    arm_contract = value.get("arm_contract")
    _require(isinstance(arm_contract, Mapping), "quality arm_contract missing")
    _require(
        _as_set(arm_contract.get("arms"), "quality arms")
        == {"NO_MEMORY", "NAIVE_RAG", "MILAI_MCP"},
        "quality arm set drift",
    )
    for key in (
        "same_vllm_identity_required",
        "same_generation_contract_required",
        "same_budget_required",
    ):
        _require(arm_contract.get(key) is True, f"quality arm invariant drift: {key}")
    _require(
        arm_contract.get("hidden_or_extra_calls_max") == 0,
        "quality hidden call max drift",
    )
    safety = value.get("hard_safety_rules")
    _require(isinstance(safety, Mapping), "quality hard safety rules missing")
    nonzero = {key: item for key, item in safety.items() if item != 0}
    _require(not nonzero, "hard safety rules must be zero tolerance")
    feasibility = value.get("benchmark_feasibility")
    _require(isinstance(feasibility, Mapping), "benchmark feasibility missing")
    expected_decisions = {
        "longmemeval_v2": "ADAPTED_PROTOCOL",
        "longmemeval": "OFFICIAL_TEXT_INPUT_COMPATIBLE_FOR_CLEANED_500",
        "bfcl_v4_local_non_live": "ADAPTED_LOCAL_NON_LIVE_SUPPORTED_SUBSET",
    }
    for dataset, expected_decision in expected_decisions.items():
        dataset_value = feasibility.get(dataset)
        _require(isinstance(dataset_value, Mapping), f"{dataset} feasibility missing")
        _require(
            dataset_value.get("decision") == expected_decision,
            f"{dataset} feasibility decision drift",
        )
    quality = value.get("quality_acceptance")
    _require(isinstance(quality, Mapping), "quality_acceptance missing")
    missing_thresholds = _null_required_thresholds(quality)
    expected_missing = {
        "$.latency.t0_t1_t2_t3_thresholds.t0_raw_vllm_p95_ms_max",
        "$.latency.t0_t1_t2_t3_thresholds.t1_gateway_p95_ms_max",
        "$.latency.t0_t1_t2_t3_thresholds.t2_agent_integration_p95_ms_max",
        "$.latency.t0_t1_t2_t3_thresholds.t3_memory_e2e_p95_ms_max",
    }
    _require(
        set(missing_thresholds) == expected_missing,
        "quality threshold template null set drift",
    )
    longmemeval = quality.get("longmemeval_overall")
    _require(
        isinstance(longmemeval, Mapping)
        and longmemeval.get("primary_minimum_delta") == 0.0
        and float(longmemeval.get("observed_primary_delta")) < 0
        and longmemeval.get("secondary_minimum_delta") == 0.0
        and float(longmemeval.get("observed_secondary_delta")) < 0
        and longmemeval.get("result") == "BELOW_TARGET",
        "LongMemEval frozen NO-GO drift",
    )
    bfcl = quality.get("bfcl_agent_tool_calling")
    _require(isinstance(bfcl, Mapping), "BFCL frozen quality contract missing")
    for key in (
        "adapted_official_checker_accuracy",
        "multi_turn_accuracy",
        "irrelevance_no_call_accuracy",
    ):
        metric = bfcl.get(key)
        _require(
            isinstance(metric, Mapping)
            and float(metric.get("observed")) < float(metric.get("minimum"))
            and metric.get("result") == "BELOW_TARGET",
            f"BFCL frozen NO-GO drift: {key}",
        )
    _require(
        (quality.get("session_token_overhead") or {}).get("maximum") == 30000,
        "quality OG-05 token overhead contract drift",
    )
    decision = value.get("decision_policy")
    _require(isinstance(decision, Mapping), "quality decision_policy missing")
    target_rules = _as_set(decision.get("target_met_requires"), "target_met_requires")
    _require(
        {
            "ALL_HARD_SAFETY_RULES_PASS",
            "ALL_REQUIRED_THRESHOLDS_NON_NULL_AND_PASS",
            "NO_HIDDEN_OR_EXTRA_MODEL_CALL",
            "TIER_2_AUDIT_COMPLETE",
        }.issubset(target_rules),
        "quality TARGET_MET rules drift",
    )
    _require(
        decision.get("post_test_threshold_change") == "DENY_NEW_CANDIDATE_REQUIRED",
        "quality post-test threshold change policy drift",
    )
    calibration_decision = value.get("calibration_decision")
    _require(
        isinstance(calibration_decision, Mapping)
        and calibration_decision.get("quality_outcome") == "BELOW_TARGET"
        and calibration_decision.get("test_access_authorized") is False
        and calibration_decision.get("test_execution") == "DENIED_NOT_RUN",
        "quality calibration decision drift",
    )
    preserve_claims = _as_set(
        calibration_decision.get("preserve_claims"),
        "calibration_decision.preserve_claims",
    )
    _require(
        preserve_claims
        == {
            "MCP_PACKAGE_VERIFIED",
            "OPENWORKER_HOST_ISOLATED",
            "MCP_INTEGRATION_PASS",
            "LOCAL_PROVIDER_VERIFIED",
        },
        "frozen preserve-claims bytes drift",
    )
    tier_2 = (value.get("scoring_tiers") or {}).get("tier_2")
    _require(
        isinstance(tier_2, Mapping)
        and tier_2.get("status") == "PRE_FROZEN_AUDIT_NOT_STARTED"
        and tier_2.get("case_count") == 12
        and tier_2.get("case_ids_sha256")
        == "286fcfb4fad5bc3eb6a909cc31eb33eba00b4414a5a5db499789398fcaa3628b"
        and tier_2.get("human_annotations_present") is False,
        "Tier-2 pre-frozen manifest drift",
    )
    return {
        "path": QUALITY_ACCEPTANCE.relative_to(ROOT).as_posix(),
        "sha256": _sha256(QUALITY_ACCEPTANCE),
        "frozen": True,
        "test_access_authorized": False,
        "required_threshold_null_fields": sorted(missing_thresholds),
        "hard_safety_rules": dict(sorted(safety.items())),
        "quality_outcome": "BELOW_TARGET",
        "test_execution": "DENIED_NOT_RUN",
        "open_review_finding": "DG10-SOL-001",
        "preserve_claims_interpretation": (
            "QUALIFIED_BY_CURRENT_CLAIM_MATRIX_AS_AUTHOR_EVIDENCE_AND_STAGE_STATE_ONLY"
        ),
        "status": "PASS_IMMUTABLE_BYTES_WITH_OPEN_P1_NOT_ACCEPTANCE",
    }


def validate() -> dict[str, Any]:
    claim_matrix = _load_yaml(CLAIM_MATRIX)
    quality_acceptance = _load_yaml(QUALITY_ACCEPTANCE)
    report = {
        "schema": "milai.dg10.contract-validation.v1",
        "date": DATE,
        "goal_contract_version": GOAL_VERSION,
        "candidate": "candidate.3.3-contracts-0.3.1",
        "integration_candidate": "candidate.2.4",
        "status": "PASS_CURRENT_STATE_NO_GO_OPEN_P1",
        "data_boundary": "CONTRACTS_ONLY_SECRET_FREE",
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_gate": "OE-F06_OPEN_PARKED",
        "runtime_banner": "0.1.x CANDIDATE",
        "schema_banner": "0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE",
        "contract_cleanup_only": False,
        "runtime_architecture_vllm_candidate_bytes_changed": False,
        "goals": _validate_goal_doc(),
        "claim_matrix": _validate_claim_matrix(claim_matrix),
        "quality_acceptance": _validate_quality_acceptance(quality_acceptance),
        "allowed_current_claim": (
            "L1/L2/L3 remain author-candidate/review-required evidence only; "
            "L4 is REVISE/BELOW_TARGET and L5 is REVISE with two open P1; "
            "LOCAL_VLLM_MCP_AGENT_CANDIDATE is denied."
        ),
    }
    canonical = json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    report["report_body_sha256_without_self"] = hashlib.sha256(
        canonical.encode()
    ).hexdigest()
    return report


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate DG-10 0.3.1 contracts")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = validate()
    output = args.output.resolve()
    _write(output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
