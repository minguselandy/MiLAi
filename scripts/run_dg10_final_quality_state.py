from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
CANDIDATE = "candidate.1"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-final-quality-state-{CANDIDATE}-{DATE}.json"
)
INPUTS = {
    "quality_contract": (
        ROOT / "docs/contracts/DG-10-quality-acceptance.yaml",
        "50599ac26f478370f85655df8acaa4b278d7ea3e94aba4938110474b1fcf9f51",
    ),
    "quality_calibration": (
        ROOT
        / "docs/reports/DG-10-quality-calibration-assessment-candidate.1-2026-08-22.json",
        "4df3da78254f356d77f687c2acfa66d6dd7a9a8fdeffc880903253057e6d31a9",
    ),
    "three_arm_longmemeval": (
        ROOT / "docs/reports/DG-10-benchmark-three-arm-dev-candidate.3-2026-08-22.json",
        "6c7b2261e82bbbbc417f371983fbdea921e1f7f123f394c705cfd7091f5ee10e",
    ),
    "longmemeval_v2": (
        ROOT
        / "docs/reports/DG-10-benchmark-lme-v2-dev-smoke-candidate.3-2026-08-21.json",
        "7caa9609a01883f89b696ad40b631940aaf2937cbd5377726da0d9e33ac3f0d9",
    ),
    "bfcl": (
        ROOT / "docs/reports/DG-10-bfcl-dev-aggregate-candidate.1-2026-08-21.json",
        "8bfce6d9bc957abe16404c419687050791375cbfb7951fd0e8f3119b8997cfc5",
    ),
    "tier2_package": (
        ROOT
        / "docs/reports/DG-10-tier2-blinded-audit-package-candidate.1-2026-08-22.json",
        "769a1bc87220ddf78de252aab61907e1d4f588b419e724c087700ed26860a014",
    ),
    "tier3_judge": (
        ROOT / "docs/reports/DG-10-tier3-same-vllm-judge-candidate.5-2026-08-22.json",
        "6e6992d321dd1c56a595ff80a72e68ad20c77c65a89922298e0c7bcf3f0924cc",
    ),
    "serving_characterization": (
        ROOT
        / "docs/reports/DG-10-serving-characterization-candidate.6-2026-08-22.json",
        "6ff6662188cbf96a5213a3a972631a69900293f6eb1e1d274531a94c021e38c6",
    ),
    "serving_assessment": (
        ROOT / "docs/reports/DG-10-serving-assessment-candidate.1-2026-08-22.json",
        "c5f47d17880e0ad4280b2439b71550432a0bc9545b005368fb0a61e8e13a1d61",
    ),
}


class FinalQualityStateError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_inputs() -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for name, (path, expected) in INPUTS.items():
        actual = _sha256(path)
        if actual != expected:
            raise FinalQualityStateError(
                f"bound input drift: {name}: expected={expected} actual={actual}"
            )
        if path.suffix == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise FinalQualityStateError(f"bound JSON is not an object: {name}")
            loaded[name] = value
    return loaded


def build_state(values: dict[str, Any]) -> dict[str, Any]:
    quality = values["quality_calibration"]
    three_arm = values["three_arm_longmemeval"]
    bfcl = values["bfcl"]
    tier2_package = values["tier2_package"]
    tier3 = values["tier3_judge"]
    serving = values["serving_assessment"]
    if (
        quality.get("quality_outcome") != "BELOW_TARGET"
        or quality.get("test_access_authorized") is not False
        or quality.get("test_labels_or_outputs_opened") is not False
        or three_arm.get("test_access_authorized") is not False
        or tier2_package.get("gate_results", {}).get("tier2_complete") != "NO"
        or tier3.get("release_input") is not False
        or tier3.get("status") != "TIER3_SAME_VLLM_DEV_CHARACTERIZATION_COMPLETE"
        or serving.get("bmg04_exit_criteria", {}).get("result")
        != "NO_GO_CHARACTERIZATION_ONLY"
    ):
        raise FinalQualityStateError("final quality state input semantics drift")

    lme_arms = quality["longmemeval"]["arms"]
    lme_delta = quality["longmemeval"]["milai_minus_strongest_baseline"]
    bfcl_aggregate = bfcl["aggregates"]
    tier3_arms = tier3["aggregates"]["by_arm"]
    created_at = datetime.now(UTC).isoformat()
    return {
        "schema": "milai.dg10.final-quality-state.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "created_at": created_at,
        "status": "EVALUATION_STOPPED_NO_GO_TEST_DENIED",
        "quality_outcome": "BELOW_TARGET",
        "aggregate_candidate_claim_allowed": False,
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "full_test_execution": "DENIED_NOT_RUN",
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "bound_inputs": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": expected,
            }
            for name, (path, expected) in INPUTS.items()
        },
        "scoring_tiers": {
            "tier_1_deterministic": {
                "status": "COMPLETE_BELOW_TARGET_ON_DEV",
                "release_input": True,
                "longmemeval": {
                    "case_count_per_arm": 50,
                    "NO_MEMORY": {
                        "exact_match": lme_arms["NO_MEMORY"]["exact_match_mean"],
                        "normalized_f1": lme_arms["NO_MEMORY"]["normalized_f1_mean"],
                    },
                    "NAIVE_RAG": {
                        "exact_match": lme_arms["NAIVE_RAG"]["exact_match_mean"],
                        "normalized_f1": lme_arms["NAIVE_RAG"]["normalized_f1_mean"],
                    },
                    "MILAI_MCP": {
                        "exact_match": lme_arms["MILAI_MCP"]["exact_match_mean"],
                        "normalized_f1": lme_arms["MILAI_MCP"]["normalized_f1_mean"],
                    },
                    "milai_minus_strongest_baseline": lme_delta,
                },
                "bfcl": {
                    "case_count": bfcl_aggregate["case_count"],
                    "overall_accuracy": bfcl_aggregate[
                        "adapted_official_checker_accuracy"
                    ],
                    "single_turn_supported_accuracy": bfcl_aggregate[
                        "single_turn_supported"
                    ]["accuracy"],
                    "multi_turn_accuracy": bfcl_aggregate["multi_turn"]["accuracy"],
                    "no_call_accuracy": bfcl_aggregate["category_metrics"][
                        "irrelevance"
                    ]["no_call_accuracy"],
                    "quarantined_cases_excluded": 4,
                },
                "decision": "BELOW_TARGET_TEST_DENIED",
            },
            "tier_2_blinded_human": {
                "status": tier2_package["status"],
                "release_input": True,
                "package_ready": True,
                "case_count": tier2_package["package"]["case_count"],
                "answer_count": tier2_package["package"]["answer_count"],
                "required_independent_humans": 2,
                "completed_independent_humans": 0,
                "third_adjudicator_required_on_conflict": True,
                "audit_complete": False,
                "blocker": "EXTERNAL_HUMAN_ANNOTATORS_NOT_PROVIDED",
                "may_override_tier_1": False,
            },
            "tier_3_same_vllm": {
                "status": tier3["status"],
                "release_input": False,
                "native_judge_calls": tier3["aggregates"]["native_model_calls"],
                "ordinal_correctness_mean": {
                    arm: tier3_arms[arm][
                        "ordinal_correctness_mean_excluding_ambiguous_reference"
                    ]
                    for arm in ("NO_MEMORY", "NAIVE_RAG", "MILAI_MCP")
                },
                "milai_minus_naive_rag": round(
                    tier3_arms["MILAI_MCP"][
                        "ordinal_correctness_mean_excluding_ambiguous_reference"
                    ]
                    - tier3_arms["NAIVE_RAG"][
                        "ordinal_correctness_mean_excluding_ambiguous_reference"
                    ],
                    6,
                ),
                "interpretation": "SAME_MODEL_JUDGE_SCORE_INFLATION_AND_BIAS_CHARACTERIZATION_ONLY",
                "may_override_tier_1": False,
            },
        },
        "serving": {
            "status": serving["status"],
            "BMG-04": serving["release_effect"]["BMG-04"],
            "result": serving["bmg04_exit_criteria"]["result"],
            "blocking_criteria": [
                name
                for name, state in serving["bmg04_exit_criteria"].items()
                if isinstance(state, str) and state.startswith("FAIL_")
            ],
        },
        "gate_state": {
            "BMG-00": "AUTHOR_EVIDENCE_COMPLETE_REVIEW_REQUIRED",
            "BMG-00A": "AUTHOR_EVIDENCE_COMPLETE_REVIEW_REQUIRED",
            "BMG-01": "PRIOR_AUTHOR_CANDIDATE_REVERIFY_UNCHANGED",
            "BMG-02": "NO_GO_DEV_MILAI_BELOW_STRONGEST_BASELINE",
            "BMG-03": "NO_GO_BFCL_DEV_BELOW_THRESHOLDS",
            "BMG-04": "NO_GO_CHARACTERIZATION_ONLY_INCOMPLETE_EXIT_CRITERIA",
            "BMG-05": "FROZEN_CONTRACT_COMPLETE_OUTCOME_BELOW_TARGET",
            "DG10-L4": "REVISE_BELOW_TARGET_AND_PERFORMANCE_INCOMPLETE",
            "CRG-00": "MAY_MATERIALIZE_NO_GO_REVIEW_BUNDLE",
            "CRG-01": "MAY_AUDIT_NO_GO_EVIDENCE_ONLY",
            "CRG-02": "CANNOT_PASS_WHILE_L4_NOT_ACCEPTED_AND_BELOW_TARGET",
        },
        "failed_release_conditions": [
            "LONGMEMEVAL_MILAI_BELOW_NAIVE_RAG",
            "BFCL_OVERALL_BELOW_0_8",
            "BFCL_MULTI_TURN_BELOW_0_5",
            "BFCL_NO_CALL_BELOW_0_8",
            "SERVING_NON_EXCLUSIVE_AND_INCOMPLETE_COMPONENT_METRICS",
            "TIER2_HUMAN_AUDIT_NOT_COMPLETED",
            "L4_NOT_ACCEPTED",
            "L5_NOT_STARTED",
        ],
        "preserved_claims": {
            "L1_L3_author_evidence": "UNCHANGED_REVIEW_REQUIRED",
            "MCP_wire_and_security": "NOT_RECLASSIFIED_AS_MODEL_QUALITY_FAILURE",
            "external_provider": "OE_F06_OPEN_PARKED",
        },
        "decision": {
            "run_full_test": False,
            "promote_local_vllm_mcp_agent_candidate": False,
            "perform_controlled_acceptance_pass": False,
            "next_allowed_action": "ADVERSARIAL_AUDIT_OF_NO_GO_EVIDENCE_AND_REMEDIATION_PLANNING_ONLY",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the DG-10 final quality state")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    state = build_state(_load_inputs())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FinalQualityStateError(f"refusing to overwrite final state: {output}")
    output.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(output, 0o600)
    print(
        json.dumps(
            {
                "status": state["status"],
                "quality_outcome": state["quality_outcome"],
                "output": str(output),
                "sha256": _sha256(output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
