#!/usr/bin/env python3
"""Seal the honest DG-25 terminal after the one-shot S4B stop."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (str(ROOT), str(RUNTIME_SRC)):
    if value not in sys.path:
        sys.path.insert(0, value)

from evals.dg25.artifacts import (
    append_failure,
    canonical_sha256,
    file_identity,
    write_json_new,
)

OFFICIAL_RUN_ID = "dg25-s10-terminal-20260830-001"
OUTPUT_ROOT = Path("var/dg25/terminal")
S4B_OUTPUT = Path("var/dg25/s4b/dg25-s4b-joint-score-20260830-001")
FAILURE_INDEX = Path("var/dg25/failure-index.jsonl")
GOAL = Path("MiLAi_DG-25_Requirement定向检索与时间答案正确性闭环_GOALS.md")
RUNBOOK = Path("docs/runbooks/dg25-requirement-complete-acquisition.md")
ARCHITECTURE_MANIFEST = Path("architecture/v1.0/architecture_manifest.json")
ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)
SCORE_DIGEST = "480a59a44fe0690f64e2c36ce068836e039d1b6785bde7a1de79b102e74484b7"
COMBINED_SEAL_DIGEST = (
    "c2a75955c7ba1a1bff93f341ccf81c1c46f0ddb3492595012ed435533d907b7f"
)
PROTECTED_DIFF_SHA256 = {
    "scripts/dg13u_u1_review.py": (
        "5469b6ac14898ca55d92489f47ec4868893b40060912f06ed24d6ae5360ee476"
    ),
    "tests/test_dg13u_u1_review.py": (
        "588b98756db645a5ee93090245e6e510945145bfd86ec235074b44717929e4cd"
    ),
}

S4B_ARTIFACTS = {
    "joint_score": "joint-score.json",
    "routing_selection_report": "routing-selection-ablation-report.json",
    "component_unique_report": "component-unique-contribution-report.json",
    "rule_leave_one_out_report": "rule-leave-one-out-report.json",
    "temporal_ablation_report": "temporal-ablation-report.json",
    "final_minimal_policy": "final-minimal-policy.json",
    "pre_score_gate": "pre-score-stop-gate.json",
    "post_score_gate": "post-score-stop-gate.json",
}
EXPECTED_ARMS = (
    "R0",
    "R0P",
    "R1",
    "R2",
    "R3",
    "R4",
    "R5_NO_SYNONYM_NORMALIZATION",
    "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
    "R_FINAL_DROP_ROLE_RESERVATION",
    "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
    "R_FINAL_DROP_UNIFIED_PROOF_FIRST",
    "T0",
    "T1",
    "T2",
    "T3",
    "T4",
)
TEMPORAL_ARMS = ("T0", "T1", "T2", "T3", "T4")

AUTHORITATIVE_JSON = {
    "s0": (
        Path("var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/receipt.json"),
        "status",
        "PENDING_INDEPENDENT_ABLATION_REVIEW_OR_OWNER_WAIVER",
        "7cf91c97c0fb752873d350c46753985868fd9589f5946d9f7a22218e6a485982",
        3187,
    ),
    "s1": (
        Path("var/dg25/s1/dg25-s1-contracts-20260829-002/receipt.json"),
        "status",
        "PASS_DG25_S1_TYPED_CONTRACTS_SYNTHETIC_MATRIX",
        "e6cc9cee3751c88cf969e1db25cb9c4323adbd274dcb28ec7476b909866c9023",
        2613,
    ),
    "s2": (
        Path("var/dg25/s2/dg25-s2-plan-execution-20260829-003/receipt.json"),
        "status",
        "PASS_DG25_S2_UNIFIED_PLAN_OFFICIAL_BATCH_EXECUTION",
        "b79fea0f2efd858fc651df2f0fcfbcc3fd0bfdf27e63d9c731f070c433ca7d77",
        4484,
    ),
    "s3_readiness": (
        Path("var/dg25/readiness/dg25-s3-readiness-20260830-011/receipt.json"),
        "status",
        "PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION",
        "d5628ffb571e82794344a059a50734467c6069b6614a84864ed8e77ef74e8ac8",
        4430,
    ),
    "s3_review": (
        Path(
            "var/dg25/reviews/"
            "dg25-s3-readiness-independent-review-20260830-008/review.json"
        ),
        "verdict",
        "AUTHORIZE_S3A_E1_LABEL_FREE_ALL_ARM_GENERATION",
        "ce3b330fe78a045b6c6b430cb17f6df22c2cbf24c65d0e433247e7bcb3f4776e",
        33541,
    ),
    "s4a_quality": (
        Path("var/dg25/quality/dg25-s4a-quality-20260830-005/receipt.json"),
        "status",
        "PASS_DG25_S4A_QUALITY",
        "5e4c17ef5ad390ad4f6c1a7b35219c2f5da2699a8d7d711aea148f21d69ad669",
        13010,
    ),
    "s4a_readiness": (
        Path("var/dg25/s4a-readiness/dg25-s4a-readiness-20260830-006/receipt.json"),
        "status",
        "PASS_DG25_S4A_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION",
        "f948a6167aa25d2420b2335d538600e2f769e47c90b9222a6990c11d81a7afe0",
        6160,
    ),
    "s4a_review": (
        Path("var/dg25/reviews/dg25-s4a-independent-review-20260830-004/review.json"),
        "verdict",
        "AUTHORIZE_S4A_E2_LABEL_FREE_ALL_ARM_AND_COMBINED_SEAL",
        "ba95c9adb2bf7e9188e3b104fa7579edbfd17f7d3a16988ec6e10498935c0858",
        6077,
    ),
    "s4a_generation": (
        Path(
            "var/dg25/s4a/dg25-s4a-e2-label-free-20260830-001/generation-receipt.json"
        ),
        "status",
        "PASS_DG25_S4A_E2_LABEL_FREE_ALL_ARM_AND_COMBINED_SEALED",
        "c72d945140fde2bd5736d7cbe1b651fad62d2928356bada4959d397f2802b779",
        1984,
    ),
    "s4b_quality": (
        Path("var/dg25/quality/dg25-s4b-quality-20260830-002/receipt.json"),
        "status",
        "PASS_DG25_S4B_QUALITY",
        "fd7941c81e956b526005e9131589ba8276d5df2597adedd7c32ff44f3180248f",
        8414,
    ),
    "s4b_readiness": (
        Path("var/dg25/s4b-readiness/dg25-s4b-readiness-20260830-003/receipt.json"),
        "status",
        "PASS_DG25_S4B_READINESS_PENDING_FRESH_INDEPENDENT_SCORING_AUTHORIZATION",
        "56154aba328cf030d0924c6a100ed3a3088fb4a59185c551734797c2aef07fb1",
        6492,
    ),
    "s4b_review": (
        Path("var/dg25/reviews/dg25-s4b-independent-review-20260830-001/review.json"),
        "verdict",
        "AUTHORIZE_S4B_JOINT_E1_E2_POST_SEAL_SCORE",
        "3c53eb15e4384b003fe6e75f130ac0739374775e8fd6492aa98b5dee858a4311",
        6508,
    ),
    "s4b_score": (
        S4B_OUTPUT / "receipt.json",
        "status",
        "STOP_DG25_S4B_POST_SCORE_GATE",
        "7af5760d0da3fd578f54037383a86e1abed9c49c8368ea4834a370b93d65d4c4",
        4173,
    ),
}

REGISTRY_IDENTITIES = {
    "gold_equivalence_registry": {
        "path": (
            "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
            "gold-equivalence-registry-v0.1.json"
        ),
        "sha256": "c13789936296695027191f3c625c99e49e5725db189fd53791d207879226493a",
        "size": 39189,
    },
    "proof_obligation_registry": {
        "path": (
            "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
            "proof-obligation-registry-v0.1.json"
        ),
        "sha256": "a2e40b175c33ebc453253e1596f680285c33e13e6b8141cd6a0d5be6158ba26a",
        "size": 18208,
    },
}

DELIVERABLE_NAMES = (
    "baseline-freeze.json",
    "denominator-freeze.json",
    "source-config-index-snapshot-manifest.json",
    "preexisting-worktree-receipt.json",
    "ablation-independent-review.json",
    "s0-receipt.json",
    "contract-schema-bundle.json",
    "synthetic-matrix.json",
    "negative-contract-report.json",
    "s1-receipt.json",
    "requirement-acquisition-plan-traces.json",
    "plan-validation-report.json",
    "official-execution-equivalence-report.json",
    "s2-receipt.json",
    "routing-selection-ablation-report.json",
    "component-unique-contribution-report.json",
    "rule-leave-one-out-report.json",
    "final-minimal-policy.json",
    "s4b-receipt.json",
    "event-time-interval-traces.json",
    "event-identity-dedup-traces.json",
    "bounded-range-scan-proof-v02-collection.json",
    "temporal-ablation-report.json",
    "s4-receipt.json",
    "sealed-product-treatment.json",
    "sealed-product-treatment-sha256.txt",
    "mediator-score.json",
    "first-loss-post-treatment.json",
    "proof-obligation-post-treatment.json",
    "cost-trace.json",
    "s5-receipt.json",
    "typed-answer-decision-collection.json",
    "answer-conformance-negative-report.json",
    "sealed-reader-treatment.json",
    "answer-score.json",
    "reader-call-ledger.json",
    "s7-receipt.json",
    "latency-repeat-report.json",
    "quality-gate-receipt.json",
    "postgresql-integration-security-receipt.json",
    "temporary-database-cleanup.json",
    "privacy-secret-scan.json",
    "architecture-lock-verification.json",
    "terminal/receipt.json",
    "terminal/deliverable-index.json",
    "terminal/source-artifact-manifest.json",
    "terminal/failure-index.json",
    "docs/runbooks/dg25-requirement-complete-acquisition.md",
    "terminal/rollback-report.json",
)


class DG25TerminalError(RuntimeError):
    """The sealed DG-25 evidence cannot support an honest terminal."""


def _read_json(root: Path, path: Path) -> dict[str, Any]:
    value = json.loads((root / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG25TerminalError(f"JSON object required: {path}")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG25TerminalError(f"mapping required: {label}")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DG25TerminalError(f"sequence required: {label}")
    return value


def _identity(root: Path, path: Path) -> dict[str, Any]:
    return file_identity(root, root / path)


def _verify_identity(root: Path, reference: Mapping[str, Any]) -> None:
    relative = reference.get("path")
    if not isinstance(relative, str):
        raise DG25TerminalError("artifact identity path is missing")
    if _identity(root, Path(relative)) != dict(reference):
        raise DG25TerminalError(f"artifact identity drifted: {relative}")


def _all_checks_pass(value: object, label: str) -> bool:
    checks = _mapping(value, label)
    return bool(checks) and all(
        _mapping(item, f"{label}.{key}").get("passed") is True
        for key, item in checks.items()
    )


def derive_terminal_dispositions(post_gate: Mapping[str, Any]) -> dict[str, str]:
    """Apply the preregistered S4B safety-first terminal precedence."""

    if post_gate.get("passed") is not False or post_gate.get("disposition") != "STOP":
        raise DG25TerminalError("S4B post-score STOP is not authoritative")
    rules = _sequence(post_gate.get("rules"), "post-score rules")
    failed = {
        str(rule.get("id")): rule
        for item in rules
        for rule in [_mapping(item, "post-score rule")]
        if rule.get("passed") is False
    }
    if set(failed) != {"STOP_PRECISION", "STOP_WRONG_COMPLETE"}:
        raise DG25TerminalError("unexpected S4B post-score failure set")
    precision = failed["STOP_PRECISION"]
    wrong_complete = failed["STOP_WRONG_COMPLETE"]
    if (
        precision.get("expected") != 1.0
        or precision.get("observed") != 2 / 3
        or wrong_complete.get("expected") != 0
        or wrong_complete.get("observed") != 16
    ):
        raise DG25TerminalError("S4B terminal metrics drifted")
    return {
        "overall": "FAIL_SAFETY_OR_REGRESSION",
        "retrieval": "FAIL_BINDING_PRECISION_OR_GOVERNANCE",
        "temporal": "PARKED_EVENT_TIME_OR_DEDUP_UNRESOLVED",
        "answer": "NOT_ENTERED_C1_FAILED",
        "efficiency": "NOT_ENTERED_CORRECTNESS_UNSEALED",
        "safety": "FAIL_SAFETY_OR_REGRESSION",
        "quality": "NOT_ENTERED_S9_DUE_S4B_STOP",
    }


def validate_s4b_stop(root: Path = ROOT) -> dict[str, Any]:
    """Validate the sealed score without reopening either scorer registry."""

    root = root.resolve()
    output = root / S4B_OUTPUT
    observed_names = {path.name for path in output.iterdir() if path.is_file()}
    expected_names = {*S4B_ARTIFACTS.values(), "receipt.json"}
    if observed_names != expected_names:
        raise DG25TerminalError("S4B output file set drifted")

    receipt = _read_json(root, S4B_OUTPUT / "receipt.json")
    receipt_material = dict(receipt)
    receipt_digest = receipt_material.pop("receipt_digest", None)
    if receipt_digest != canonical_sha256(receipt_material):
        raise DG25TerminalError("S4B receipt digest drifted")
    expected_receipt_values = {
        "schema": "milai.dg25.s4b-score-receipt.v0.1",
        "run_id": "dg25-s4b-joint-score-20260830-001",
        "status": "STOP_DG25_S4B_POST_SCORE_GATE",
        "score_digest": SCORE_DIGEST,
        "combined_all_arm_seal_digest": COMBINED_SEAL_DIGEST,
        "authorization_consumed": True,
        "score_execution_count": 1,
        "registry_content_open_count": 2,
        "labels_loaded_after_pre_score_gate": True,
        "post_score_gate_passed": False,
        "post_score_adaptation": False,
        "reader_model_provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "canonical_mutations": 0,
        "automatic_retries": 0,
    }
    if any(receipt.get(key) != value for key, value in expected_receipt_values.items()):
        raise DG25TerminalError("S4B receipt contract drifted")

    artifacts = _mapping(receipt.get("artifacts"), "S4B artifacts")
    if set(artifacts) != set(S4B_ARTIFACTS):
        raise DG25TerminalError("S4B artifact denominator drifted")
    for key, filename in S4B_ARTIFACTS.items():
        reference = _mapping(artifacts[key], key)
        if reference.get("path") != (S4B_OUTPUT / filename).as_posix():
            raise DG25TerminalError(f"S4B artifact path drifted: {key}")
        _verify_identity(root, reference)
    for key in ("combined_all_arm_seal", "independent_review", "readiness_receipt"):
        _verify_identity(root, _mapping(receipt.get(key), key))
    if receipt.get("registry_identities") != REGISTRY_IDENTITIES:
        raise DG25TerminalError("receipt-bound scorer registry identities drifted")

    joint = _read_json(root, S4B_OUTPUT / S4B_ARTIFACTS["joint_score"])
    joint_material = dict(joint)
    score_digest = joint_material.pop("score_digest", None)
    if score_digest != SCORE_DIGEST or score_digest != canonical_sha256(joint_material):
        raise DG25TerminalError("joint score digest drifted")
    arm_scores = _mapping(joint.get("arm_scores"), "arm scores")
    if tuple(arm_scores) != EXPECTED_ARMS:
        raise DG25TerminalError("joint score arm order drifted")
    precisions: list[float] = []
    wrong_complete = 0
    wrong_complete_arms: list[str] = []
    for arm, raw_score in arm_scores.items():
        score = _mapping(raw_score, f"arm score {arm}")
        precision = score.get("accepted_binding_precision")
        wrong = score.get("wrong_complete")
        if not isinstance(precision, (int, float)) or isinstance(precision, bool):
            raise DG25TerminalError(f"arm precision invalid: {arm}")
        if not isinstance(wrong, int) or isinstance(wrong, bool):
            raise DG25TerminalError(f"arm WrongComplete invalid: {arm}")
        precisions.append(float(precision))
        wrong_complete += wrong
        if wrong:
            wrong_complete_arms.append(str(arm))
    if any(
        _mapping(arm_scores[arm], arm).get("wrong_complete") != 0
        for arm in TEMPORAL_ARMS
    ):
        raise DG25TerminalError("temporal WrongComplete disposition drifted")

    pre_gate = _read_json(root, S4B_OUTPUT / S4B_ARTIFACTS["pre_score_gate"])
    post_gate = _read_json(root, S4B_OUTPUT / S4B_ARTIFACTS["post_score_gate"])
    if (
        pre_gate.get("passed") is not True
        or pre_gate.get("disposition") != "PROCEED_TO_AUTHORIZED_REGISTRY_OPEN"
        or not _all_checks_pass(pre_gate.get("binding_checks"), "pre binding checks")
        or not all(_mapping(pre_gate.get("schedule_checks"), "pre schedule").values())
        or not all(
            _mapping(
                pre_gate.get("scorer_source_amendment_checks"), "amendment checks"
            ).values()
        )
        or not _all_checks_pass(post_gate.get("binding_checks"), "post binding checks")
        or not all(_mapping(post_gate.get("schedule_checks"), "post schedule").values())
    ):
        raise DG25TerminalError("S4B schedule or binding gate drifted")
    dispositions = derive_terminal_dispositions(post_gate)
    if min(precisions) != 2 / 3 or wrong_complete != 16:
        raise DG25TerminalError("joint score does not reproduce post-score STOP")

    final_policy = _read_json(root, S4B_OUTPUT / S4B_ARTIFACTS["final_minimal_policy"])
    policy_material = dict(final_policy)
    policy_digest = policy_material.pop("policy_digest", None)
    if (
        policy_digest != canonical_sha256(policy_material)
        or final_policy.get("score_digest") != SCORE_DIGEST
        or final_policy.get("candidate_default") is not False
        or final_policy.get("formal_holdout_consumed") is not False
        or final_policy.get("post_score_adaptation") is not False
    ):
        raise DG25TerminalError("diagnostic final-minimal-policy drifted")

    return {
        "receipt": receipt,
        "receipt_identity": _identity(root, S4B_OUTPUT / "receipt.json"),
        "post_gate": post_gate,
        "post_gate_identity": _identity(
            root, S4B_OUTPUT / S4B_ARTIFACTS["post_score_gate"]
        ),
        "score_identity": _identity(root, S4B_OUTPUT / S4B_ARTIFACTS["joint_score"]),
        "final_policy_identity": _identity(
            root, S4B_OUTPUT / S4B_ARTIFACTS["final_minimal_policy"]
        ),
        "dispositions": dispositions,
        "metrics": {
            "arm_count": len(arm_scores),
            "minimum_accepted_binding_precision": min(precisions),
            "wrong_complete_sum_across_diagnostic_arms": wrong_complete,
            "wrong_complete_arm_count": len(wrong_complete_arms),
            "wrong_complete_arms": wrong_complete_arms,
            "temporal_wrong_complete_sum": 0,
        },
        "registry_content_reopened": False,
        "policy_adopted": False,
    }


def _validate_authoritative_json(root: Path) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for stage, (path, field, expected, sha256, size) in AUTHORITATIVE_JSON.items():
        value = _read_json(root, path)
        identity = _identity(root, path)
        if (
            value.get(field) != expected
            or identity["sha256"] != sha256
            or identity["size"] != size
        ):
            raise DG25TerminalError(f"authoritative stage evidence drifted: {stage}")
        identities[stage] = identity
    return identities


def _validate_failure_index(root: Path) -> dict[str, Any]:
    path = root / FAILURE_INDEX
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise DG25TerminalError("failure index record invalid")
    failure_ids = [str(row.get("failure_id", "")) for row in rows]
    if any(not value for value in failure_ids) or len(failure_ids) != len(
        set(failure_ids)
    ):
        raise DG25TerminalError("failure index identity is not append-only unique")
    for row in rows:
        _verify_identity(root, _mapping(row.get("receipt"), "failure receipt"))
    official = [
        row
        for row in rows
        if row.get("first_failing_gate") == "DG25_S4B_OFFICIAL_ONE_SHOT_SCORE"
    ]
    if len(official) != 1:
        raise DG25TerminalError("S4B one-shot failure denominator is not one")
    official_receipt_ref = _mapping(official[0].get("receipt"), "official failure")
    official_receipt = _read_json(root, Path(str(official_receipt_ref["path"])))
    command = _mapping(official_receipt.get("command"), "official failure command")
    if (
        official_receipt.get("automatic_retries") != 0
        or official_receipt.get("first_failing_gate")
        != "DG25_S4B_OFFICIAL_ONE_SHOT_SCORE"
        or official_receipt.get("root_cause")
        != "RuntimeError: DG25_S4B_POST_SCORE_GATE_STOP_AFTER_OUTPUT_SEALED"
        or command.get("exit_code") != 1
    ):
        raise DG25TerminalError("official S4B STOP failure receipt drifted")
    return {
        "identity": _identity(root, FAILURE_INDEX),
        "line_count": len(rows),
        "unique_failure_count": len(set(failure_ids)),
        "official_s4b_failure": dict(official_receipt_ref),
    }


def _protected_diff_hashes(root: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in PROTECTED_DIFF_SHA256.items():
        result = subprocess.run(
            ["git", "diff", "--binary", "--", relative],
            cwd=root,
            check=True,
            capture_output=True,
        )
        digest = hashlib.sha256(result.stdout).hexdigest()
        if digest != expected:
            raise DG25TerminalError(f"protected user diff drifted: {relative}")
        observed[relative] = digest
    return observed


def _present_item(
    root: Path,
    index: int,
    path: Path,
    *,
    status: str = "PRESENT",
    representation: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": index,
        "name": DELIVERABLE_NAMES[index - 1],
        "status": status,
        "evidence": [_identity(root, path)],
    }
    if representation is not None:
        item["representation"] = representation
    return item


def _deliverable_index(
    root: Path,
    output: Path,
    *,
    failure_pointer: Path,
    rollback_report: Path,
) -> dict[str, Any]:
    s0 = Path("var/dg25/s0/dg25-s0-baseline-freeze-20260829-001")
    s1 = Path("var/dg25/s1/dg25-s1-contracts-20260829-002")
    s2 = Path("var/dg25/s2/dg25-s2-plan-execution-20260829-003")
    e2 = Path("var/dg25/s4a/dg25-s4a-e2-label-free-20260830-001")
    items = [
        _present_item(root, 1, s0 / "baseline-freeze.json"),
        _present_item(root, 2, s0 / "denominator-freeze.json"),
        _present_item(root, 3, s0 / "source-config-index-snapshot-manifest.json"),
        _present_item(root, 4, s0 / "preexisting-worktree-receipt.json"),
        _present_item(
            root,
            5,
            Path(
                "var/dg25/reviews/dg25-ablation-independent-review-20260829-001/review.json"
            ),
            representation="independent review stored in the review namespace",
        ),
        _present_item(root, 6, s0 / "receipt.json"),
        _present_item(root, 7, s1 / "contract-schema-bundle.json"),
        _present_item(root, 8, s1 / "synthetic-matrix.json"),
        _present_item(root, 9, s1 / "negative-contract-report.json"),
        _present_item(root, 10, s1 / "receipt.json"),
        _present_item(root, 11, s2 / "requirement-acquisition-plan-traces.json"),
        _present_item(root, 12, s2 / "plan-validation-report.json"),
        _present_item(root, 13, s2 / "official-execution-equivalence-report.json"),
        _present_item(root, 14, s2 / "receipt.json"),
        _present_item(
            root,
            15,
            S4B_OUTPUT / S4B_ARTIFACTS["routing_selection_report"],
            status="SEALED_DIAGNOSTIC_NOT_PUBLISHED_S4B_STOP",
        ),
        _present_item(
            root,
            16,
            S4B_OUTPUT / S4B_ARTIFACTS["component_unique_report"],
            status="SEALED_DIAGNOSTIC_NOT_PUBLISHED_S4B_STOP",
        ),
        _present_item(
            root,
            17,
            S4B_OUTPUT / S4B_ARTIFACTS["rule_leave_one_out_report"],
            status="SEALED_DIAGNOSTIC_NOT_PUBLISHED_S4B_STOP",
        ),
        _present_item(
            root,
            18,
            S4B_OUTPUT / S4B_ARTIFACTS["final_minimal_policy"],
            status="SEALED_DIAGNOSTIC_NOT_PUBLISHED_S4B_STOP",
        ),
        _present_item(
            root,
            19,
            S4B_OUTPUT / "receipt.json",
            status="SEALED_DIAGNOSTIC_NOT_PUBLISHED_S4B_STOP",
        ),
        _present_item(
            root,
            20,
            e2 / "e2-label-free-arm-outputs.json",
            status="PRESENT_IN_SEALED_E2_BUNDLE",
            representation="T1 interval traces inside the immutable E2 bundle",
        ),
        _present_item(
            root,
            21,
            e2 / "e2-label-free-arm-outputs.json",
            status="PRESENT_IN_SEALED_E2_BUNDLE",
            representation="T3 identity and dedup traces inside the immutable E2 bundle",
        ),
        _present_item(
            root,
            22,
            e2 / "e2-label-free-arm-outputs.json",
            status="PRESENT_IN_SEALED_E2_BUNDLE",
            representation="T4 BoundedRangeScanProofV02 collection inside the E2 bundle",
        ),
        _present_item(
            root,
            23,
            S4B_OUTPUT / S4B_ARTIFACTS["temporal_ablation_report"],
            status="SEALED_DIAGNOSTIC_NOT_PUBLISHED_S4B_STOP",
        ),
        _present_item(root, 24, e2 / "generation-receipt.json"),
    ]
    items.extend(
        {
            "id": index,
            "name": DELIVERABLE_NAMES[index - 1],
            "status": "NOT_ENTERED_S4B_STOP",
            "evidence": [],
        }
        for index in range(25, 44)
    )
    for index, filename in (
        (44, "receipt.json"),
        (45, "deliverable-index.json"),
        (46, "source-artifact-manifest.json"),
    ):
        items.append(
            {
                "id": index,
                "name": DELIVERABLE_NAMES[index - 1],
                "status": "SEALED_BY_TERMINAL_RECEIPT",
                "path": (output / filename).relative_to(root).as_posix(),
            }
        )
    items.extend(
        [
            _present_item(root, 47, failure_pointer.relative_to(root)),
            _present_item(root, 48, RUNBOOK),
            _present_item(root, 49, rollback_report.relative_to(root)),
        ]
    )
    if len(items) != 49 or [item["id"] for item in items] != list(range(1, 50)):
        raise DG25TerminalError("deliverable denominator is not exactly 49")
    material: dict[str, Any] = {
        "schema": "milai.dg25.s10-deliverable-index.v0.1",
        "deliverable_count": len(items),
        "present_or_sealed_diagnostic_count": 30,
        "not_entered_count": 19,
        "items": items,
    }
    material["index_digest"] = canonical_sha256(material)
    return material


def _source_artifact_paths(
    root: Path,
    *,
    output: Path,
    official_failure: Mapping[str, Any],
) -> list[Path]:
    paths = {
        GOAL,
        RUNBOOK,
        FAILURE_INDEX,
        ARCHITECTURE_MANIFEST,
        Path("scripts/build_dg25_s10_terminal.py"),
        Path("tests/test_dg25_s10_terminal.py"),
        Path("scripts/run_dg25_s4b.py"),
        Path("scripts/run_dg25_s4b_quality.py"),
        Path("scripts/run_dg25_s4b_readiness.py"),
        Path("evals/dg25/effect_scorer.py"),
        Path("evals/dg25/s4b_scoring.py"),
        Path("evals/dg25/s4b_readiness.py"),
        Path(str(official_failure["path"])),
        (output / "deliverable-index.json").relative_to(root),
        (output / "failure-index.json").relative_to(root),
        (output / "rollback-report.json").relative_to(root),
    }
    fixed_roots = (
        Path("var/dg25/s0/dg25-s0-baseline-freeze-20260829-001"),
        Path("var/dg25/s1/dg25-s1-contracts-20260829-002"),
        Path("var/dg25/s2/dg25-s2-plan-execution-20260829-003"),
        Path("var/dg25/readiness/dg25-s3-readiness-20260830-011"),
        Path("var/dg25/s3a/dg25-s3a-e1-label-free-20260830-001"),
        Path("var/dg25/s4a-readiness/dg25-s4a-readiness-20260830-006"),
        Path("var/dg25/s4a/dg25-s4a-e2-label-free-20260830-001"),
        Path("var/dg25/s4b-readiness/dg25-s4b-readiness-20260830-003"),
        S4B_OUTPUT,
    )
    for relative_root in fixed_roots:
        paths.update(
            child.relative_to(root)
            for child in (root / relative_root).iterdir()
            if child.is_file()
        )
    paths.update(path for path, _, _, _, _ in AUTHORITATIVE_JSON.values())
    return sorted(paths, key=Path.as_posix)


def _write_digest_artifact(path: Path, material: dict[str, Any], key: str) -> None:
    material[key] = canonical_sha256(material)
    write_json_new(path, material)


def run(*, root: Path, run_id: str) -> dict[str, Any]:
    root = root.resolve()
    if run_id != OFFICIAL_RUN_ID:
        raise DG25TerminalError("DG-25 terminal run id is fixed")
    output = root / OUTPUT_ROOT / run_id
    if output.exists():
        raise DG25TerminalError("terminal output exists; do not overwrite or replay")

    stage_identities = _validate_authoritative_json(root)
    s4b = validate_s4b_stop(root)
    failures = _validate_failure_index(root)
    protected_diffs = _protected_diff_hashes(root)
    architecture_identity = _identity(root, ARCHITECTURE_MANIFEST)
    if architecture_identity["sha256"] != ARCHITECTURE_MANIFEST_SHA256:
        raise DG25TerminalError("frozen architecture manifest drifted")
    if any((root / f"var/dg25/s{stage}").exists() for stage in range(5, 10)):
        raise DG25TerminalError("a prohibited downstream DG-25 effect stage exists")

    output.mkdir(parents=True)
    failure_pointer_path = output / "failure-index.json"
    _write_digest_artifact(
        failure_pointer_path,
        {
            "schema": "milai.dg25.s10-failure-index-pointer.v0.1",
            "source": failures["identity"],
            "line_count": failures["line_count"],
            "unique_failure_count": failures["unique_failure_count"],
            "official_s4b_failure": failures["official_s4b_failure"],
            "automatic_retries": 0,
        },
        "pointer_digest",
    )
    rollback_path = output / "rollback-report.json"
    _write_digest_artifact(
        rollback_path,
        {
            "schema": "milai.dg25.s10-rollback-report.v0.1",
            "status": "NO_PRODUCT_ROLLOUT_TO_ROLL_BACK",
            "candidate_default": False,
            "scored_policy_adopted": False,
            "product_schema_changed": False,
            "public_mcp_schema_changed": False,
            "architecture_v1_changed": False,
            "canonical_mutations": 0,
            "required_actions": [
                "Keep candidate OFF.",
                "Do not rerun the consumed S4B authorization or official run id.",
                "Do not adopt the diagnostic final-minimal-policy artifact.",
                "Keep S5-S9 NOT_ENTERED and formal holdout untouched.",
                "Address the measured residual only in a separately frozen successor.",
            ],
        },
        "report_digest",
    )
    deliverable_path = output / "deliverable-index.json"
    write_json_new(
        deliverable_path,
        _deliverable_index(
            root,
            output,
            failure_pointer=failure_pointer_path,
            rollback_report=rollback_path,
        ),
    )
    manifest_path = output / "source-artifact-manifest.json"
    manifest: dict[str, Any] = {
        "schema": "milai.dg25.s10-source-artifact-manifest.v0.1",
        "identities": [
            _identity(root, path)
            for path in _source_artifact_paths(
                root,
                output=output,
                official_failure=_mapping(
                    failures["official_s4b_failure"], "official failure identity"
                ),
            )
        ],
        "scorer_registry_content_reopened": False,
        "registry_identities_consumed_from_sealed_s4b_receipt": REGISTRY_IDENTITIES,
    }
    manifest["identity_count"] = len(manifest["identities"])
    _write_digest_artifact(manifest_path, manifest, "manifest_digest")
    for reference in _sequence(manifest["identities"], "terminal manifest identities"):
        _verify_identity(root, _mapping(reference, "terminal manifest identity"))

    dispositions = _mapping(s4b["dispositions"], "terminal dispositions")
    terminal_checks = {
        "authoritative_stage_identities_exact": True,
        "s4b_pre_score_gate_passed": True,
        "s4b_post_score_stop_preserved": True,
        "s4b_score_executed_once": True,
        "official_runner_failure_logged_once": True,
        "automatic_retries_zero": True,
        "scorer_registries_not_reopened_for_terminal": True,
        "downstream_s5_s9_not_entered": True,
        "diagnostic_policy_not_adopted": True,
        "reader_model_provider_controller_calls_zero": True,
        "formal_holdout_untouched": True,
        "candidate_default_false": True,
        "canonical_mutations_zero": True,
        "protected_user_diffs_exact": True,
        "architecture_v1_unchanged": True,
        "deliverable_denominator_49": True,
        "all_non_self_terminal_manifest_identities_recomputed": True,
    }
    receipt: dict[str, Any] = {
        "schema": "milai.dg25.s10-terminal-receipt.v0.1",
        "run_id": run_id,
        "status": "TERMINAL_DISPOSITION_SEALED",
        "overall_disposition": dispositions["overall"],
        "retrieval_disposition": dispositions["retrieval"],
        "temporal_disposition": dispositions["temporal"],
        "answer_disposition": dispositions["answer"],
        "efficiency_disposition": dispositions["efficiency"],
        "safety_disposition": dispositions["safety"],
        "quality_disposition": dispositions["quality"],
        "full_success": False,
        "terminal_seal_gate": {
            "passed": all(terminal_checks.values()),
            "checks": terminal_checks,
        },
        "stage_dispositions": {
            "S0_S4A": "SEALED_PREREQUISITES_PRESERVED",
            "S4B": "STOP_DG25_S4B_POST_SCORE_GATE",
            "S5": "NOT_ENTERED_S4B_STOP",
            "S6": "NOT_ENTERED_S4B_STOP",
            "S7": "NOT_ENTERED_S4B_STOP",
            "S8": "NOT_ENTERED_S4B_STOP",
            "S9": "NOT_ENTERED_S4B_STOP",
            "S10": "TERMINAL_DISPOSITION_SEALED",
        },
        "denominators": {
            "opened_development_cases": 10,
            "evidence_groups": 23,
            "proof_obligations": 37,
            "diagnostic_arms": 16,
            "reader_replicates_planned": 3,
            "reader_replicates_executed": 0,
        },
        "s4b_diagnostic_metrics": s4b["metrics"],
        "s4b_score": s4b["score_identity"],
        "s4b_post_score_gate": s4b["post_gate_identity"],
        "s4b_receipt": s4b["receipt_identity"],
        "diagnostic_final_minimal_policy": {
            "artifact": s4b["final_policy_identity"],
            "adopted": False,
            "publication_status": "NOT_PUBLISHED_S4B_STOP",
        },
        "stage_evidence": stage_identities,
        "failure_index": failures["identity"],
        "failure_count": failures["line_count"],
        "official_s4b_failure": failures["official_s4b_failure"],
        "deliverable_index": _identity(root, deliverable_path.relative_to(root)),
        "source_artifact_manifest": _identity(root, manifest_path.relative_to(root)),
        "failure_index_pointer": _identity(
            root, failure_pointer_path.relative_to(root)
        ),
        "runbook": _identity(root, RUNBOOK),
        "rollback_report": _identity(root, rollback_path.relative_to(root)),
        "goal": _identity(root, GOAL),
        "architecture_manifest": architecture_identity,
        "terminal_runner": _identity(root, Path("scripts/build_dg25_s10_terminal.py")),
        "terminal_tests": _identity(root, Path("tests/test_dg25_s10_terminal.py")),
        "protected_user_diff_sha256": protected_diffs,
        "safety_boundary": {
            "candidate_default": False,
            "formal_holdout_consumed": False,
            "reader_model_provider_controller_calls": 0,
            "canonical_mutations": 0,
            "automatic_retries": 0,
            "product_schema_changed": False,
            "public_mcp_schema_changed": False,
            "architecture_v1_changed": False,
            "scorer_registry_content_reopened_during_terminal": False,
        },
        "claim_boundary": (
            "On the frozen deidentified opened-development diagnostic only, the valid one-shot "
            "S4B score failed AcceptedBindingPrecision and WrongComplete stop rules. S5-S9 were "
            "therefore not entered, the diagnostic policy was not adopted, and no Reader, model, "
            "provider, controller, formal holdout, candidate enablement, schema change, canonical "
            "mutation, production-readiness, or generalization claim is authorized."
        ),
    }
    if receipt["terminal_seal_gate"]["passed"] is not True:
        raise DG25TerminalError("terminal seal gate failed")
    receipt["receipt_digest"] = canonical_sha256(receipt)
    write_json_new(output / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    argv = list(sys.argv)
    try:
        receipt = run(root=ROOT, run_id=str(args.run_id))
    except Exception as exc:
        recorded = datetime.now().astimezone().isoformat(timespec="seconds")
        append_failure(
            ROOT,
            failure_id=(
                "dg25-s10-terminal-"
                + datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
            ),
            recorded_at=recorded,
            command_argv=argv,
            cwd=str(ROOT),
            exit_code=1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}\n",
            first_failing_gate="DG25_S10_TERMINAL_SEAL",
            root_cause=f"{type(exc).__name__}: {exc}",
            general_fix=(
                "Preserve the failed terminal output, repair the evidence or terminal builder, "
                "and use a fresh run id without rerunning S4B."
            ),
            fresh_rerun_id="REQUIRES_FRESH_S10_RUN_ID",
        )
        raise
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "overall_disposition": receipt["overall_disposition"],
                "receipt": (OUTPUT_ROOT / str(args.run_id) / "receipt.json").as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
