"""DG-25 independent-review acceptance and immutable arm-freeze helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.dg25.artifacts import canonical_sha256, file_identity, sha256_file

REVIEW_PATH = Path(
    "var/dg25/reviews/dg25-ablation-independent-review-20260829-001/review.json"
)
REVIEW_SHA256 = "f20edc2860bc28363931e2b9373ed97ba8e3e77854301d9a277b6c40133455ac"
S1_RECEIPT_PATH = Path("var/dg25/s1/dg25-s1-contracts-20260829-002/receipt.json")
S1_RECEIPT_SHA256 = "e6cc9cee3751c88cf969e1db25cb9c4323adbd274dcb28ec7476b909866c9023"
S1_SOURCE_MANIFEST_PATH = Path(
    "var/dg25/s1/dg25-s1-contracts-20260829-002/source-manifest.json"
)
S1_SOURCE_MANIFEST_SHA256 = (
    "a0a27f22e3fec545a871dbb85719d0d4473e875ee9ca91b64ef3576865809a81"
)
S0_DENOMINATOR_PATH = Path(
    "var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/denominator-freeze.json"
)
S0_BOUNDARY_PATH = Path(
    "var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/"
    "source-config-index-snapshot-manifest.json"
)
DG24_PROBES_PATH = Path(
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/"
    "sealed-official-probe-traces.json"
)
DG24_AUDIT_CAPS_PATH = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/official-audit-cap-registry-v0.1.json"
)
DG24_CASE_INPUT_PATH = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/input-only-case-manifest-v0.1.json"
)
DG24_GOLD_REGISTRY_PATH = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "gold-equivalence-registry-v0.1.json"
)
DG24_PROOF_REGISTRY_PATH = Path(
    "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "proof-obligation-registry-v0.1.json"
)
DG24_SCORER_PATH = Path("scripts/run_dg24_s6_scoring.py")
DG24_SCORER_RECEIPT_PATH = Path(
    "var/dg24/s6/dg24-s6-scoring-20260829-003/receipt.json"
)

CASE_ORDER = (
    "gpt4_8279ba03",
    "9a707b82",
    "2a1811e2",
    "0bb5a684",
    "2e6d26dc",
    "4dfccbf7",
    "gpt4_88806d6e",
    "a89d7624",
    "a82c026e",
    "88432d0a",
)
CHANNEL_ORDER = (
    "FTS_RAW",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "SOURCE_OBSERVED_RANGE_SCAN",
    "TEMPORAL_EVENT",
)
REPLAY_AUDIT_CAPS = {
    "FTS_RAW": 64,
    "FTS_ENRICHED": 64,
    "EVIDENCE_DENSE": 30,
    "SOURCE_OBSERVED_RANGE_SCAN": 64,
    "TEMPORAL_EVENT": 64,
}
LIVE_ACTION_CAPS = {
    "FTS_RAW": 8,
    "FTS_ENRICHED": 8,
    "EVIDENCE_DENSE": 12,
    "SOURCE_OBSERVED_RANGE_SCAN": 8,
    "TEMPORAL_EVENT": 8,
}
REQUIRED_EDIT_IDS = {f"RE-{index:02d}" for index in range(1, 9)}


class DG25ReviewGateError(RuntimeError):
    """An independent-review or preregistration invariant failed."""


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG25ReviewGateError(f"JSON object required: {path}")
    return value


def load_and_validate_independent_review(root: Path) -> dict[str, Any]:
    path = root / REVIEW_PATH
    if sha256_file(path) != REVIEW_SHA256:
        raise DG25ReviewGateError("independent review identity mismatch")
    review = read_json_object(path)
    validate_independent_review_payload(review)
    return review


def validate_independent_review_payload(review: Mapping[str, Any]) -> None:
    exact = {
        "schema": "milai.dg25.ablation-independent-review.v0.1",
        "reviewer_role": "INDEPENDENT_SECONDARY_CODEX_REVIEWER",
        "verdict": "APPROVE_WITH_REQUIRED_EDITS",
        "s2_authorized": True,
        "holdout_authorized": False,
        "candidate_default": False,
        "reader_stage_authorized": False,
        "model_calls_authorized": 0,
        "provider_calls_authorized": 0,
        "controller_calls_authorized": 0,
        "automatic_retries": 0,
        "canonical_mutations_authorized": 0,
    }
    for key, expected in exact.items():
        if review.get(key) != expected:
            raise DG25ReviewGateError(f"independent review field mismatch: {key}")
    if review.get("model/provider/controller_calls_authorized") != 0:
        raise DG25ReviewGateError("independent review authorized a forbidden call")
    edits = review.get("required_edits")
    if not isinstance(edits, list):
        raise DG25ReviewGateError("independent review required_edits missing")
    edit_ids = {
        item.get("id")
        for item in edits
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    if edit_ids != REQUIRED_EDIT_IDS:
        raise DG25ReviewGateError("independent review edit set mismatch")
    inputs = review.get("reviewed_input_paths_and_sha256")
    if not isinstance(inputs, list):
        raise DG25ReviewGateError("independent review input manifest missing")
    by_path = {
        item.get("path"): item.get("sha256")
        for item in inputs
        if isinstance(item, Mapping)
    }
    if by_path.get(S1_RECEIPT_PATH.as_posix()) != S1_RECEIPT_SHA256:
        raise DG25ReviewGateError("review is not bound to S1-002 receipt")
    if by_path.get(S1_SOURCE_MANIFEST_PATH.as_posix()) != S1_SOURCE_MANIFEST_SHA256:
        raise DG25ReviewGateError("review is not bound to S1-002 source manifest")


def build_exact_query_freeze(root: Path) -> list[dict[str, Any]]:
    payload = read_json_object(root / DG24_PROBES_PATH)
    records = payload.get("records")
    if not isinstance(records, list):
        raise DG25ReviewGateError("DG-24 official probe records missing")
    frozen: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("trace"), Mapping):
            raise DG25ReviewGateError("DG-24 official probe record invalid")
        case_id = _required_string(record, "case_id")
        trace = record["trace"]
        assert isinstance(trace, Mapping)
        channel = _required_string(trace, "channel")
        requirement_id = _required_string(trace, "requirement_id")
        if case_id not in CASE_ORDER or channel not in CHANNEL_ORDER:
            raise DG25ReviewGateError("official probe case/channel outside freeze")
        identity = (case_id, requirement_id, channel)
        if identity in identities:
            raise DG25ReviewGateError("duplicate official channel query identity")
        identities.add(identity)
        cap = trace.get("requested_audit_cap")
        if cap != REPLAY_AUDIT_CAPS[channel]:
            raise DG25ReviewGateError("official channel audit cap mismatch")
        summaries = {
            occurrence.get("channel_query_semantic_summary")
            for occurrence in trace.get("returned_occurrences", [])
            if isinstance(occurrence, Mapping)
            and isinstance(occurrence.get("channel_query_semantic_summary"), str)
        }
        if len(summaries) > 1:
            raise DG25ReviewGateError("one query digest has multiple semantic summaries")
        frozen.append(
            {
                "case_id": case_id,
                "requirement_id": requirement_id,
                "channel": channel,
                "query_digest": _required_sha(trace, "query_digest"),
                "query_semantic_summary": next(iter(summaries), None),
                "requested_audit_cap": cap,
                "request_identity": _required_sha(trace, "request_identity"),
                "index_identity": _required_sha(trace, "index_identity"),
                "snapshot_identity": _required_sha(trace, "snapshot_identity"),
                "scope_digest": _required_sha(trace, "scope_digest"),
                "policy_digest": _required_sha(trace, "policy_digest"),
                "run_identity": _required_string(trace, "run_identity"),
                "disposition": _required_string(trace, "disposition"),
                "official_executor_identity": _required_string(
                    trace, "official_executor_identity"
                ),
            }
        )
    case_position = {case_id: index for index, case_id in enumerate(CASE_ORDER)}
    channel_position = {channel: index for index, channel in enumerate(CHANNEL_ORDER)}
    frozen.sort(
        key=lambda item: (
            case_position[item["case_id"]],
            item["requirement_id"],
            channel_position[item["channel"]],
        )
    )
    if len(frozen) != 75:
        raise DG25ReviewGateError("official channel query denominator must be 75")
    return frozen


def build_pre_treatment_arm_manifest(
    root: Path,
    review: Mapping[str, Any],
) -> dict[str, Any]:
    denominator = read_json_object(root / S0_DENOMINATOR_PATH)
    if tuple(denominator.get("case_order", ())) != CASE_ORDER:
        raise DG25ReviewGateError("S0 case order drifted")
    audit_caps = read_json_object(root / DG24_AUDIT_CAPS_PATH)
    observed_caps = {
        channel: value.get("m_audit")
        for channel, value in audit_caps.get("channels", {}).items()
        if isinstance(value, Mapping)
    }
    if observed_caps != REPLAY_AUDIT_CAPS:
        raise DG25ReviewGateError("DG-24 audit cap registry drifted")
    exact_queries = build_exact_query_freeze(root)
    material: dict[str, Any] = {
        "schema": "milai.dg25.pre-treatment-arm-manifest.v0.1",
        "run_id": "dg25-review-gate-20260829-001",
        "review": file_identity(root, root / REVIEW_PATH),
        "s1_binding": {
            "receipt": file_identity(root, root / S1_RECEIPT_PATH),
            "source_manifest": file_identity(root, root / S1_SOURCE_MANIFEST_PATH),
        },
        "denominators": {
            "case_order": list(CASE_ORDER),
            "case_count": 10,
            "evidence_group_count": 23,
            "evidence_group_ids_digest": denominator["evidence_group_ids_digest"],
            "proof_obligation_count": 37,
            "proof_obligation_ids_digest": denominator["proof_obligation_ids_digest"],
        },
        "frozen_inputs": {
            "s0_boundary_manifest": file_identity(root, root / S0_BOUNDARY_PATH),
            "input_only_cases": file_identity(root, root / DG24_CASE_INPUT_PATH),
            "official_channel_pools": file_identity(root, root / DG24_PROBES_PATH),
            "official_audit_caps": file_identity(root, root / DG24_AUDIT_CAPS_PATH),
        },
        "selection_and_budget": {
            "final_k": 8,
            "replay_audit_caps": dict(REPLAY_AUDIT_CAPS),
            "live_action_candidate_caps": dict(LIVE_ACTION_CAPS),
            "verified_dense_ceiling": 30,
            "max_actions_per_plan": 2,
            "max_additional_repository_calls_per_query": 2,
            "max_extra_state_passes_per_query": 1,
            "max_target_requirements": 3,
            "max_candidate_pool_per_query": 64,
            "max_hydrated_candidates_per_query": 120,
            "max_reader_evidence_items": 8,
            "range_scan_max_rows": 2_000,
            "cross_channel_fusion": "RANK_BASED_ONLY",
            "compare_raw_scores_across_channels": False,
            "preserve_baseline_action_cap": True,
        },
        "exact_channel_query_identities": exact_queries,
        "scorer_identities": {
            "gold_equivalence_registry": file_identity(root, root / DG24_GOLD_REGISTRY_PATH),
            "proof_obligation_registry": file_identity(root, root / DG24_PROOF_REGISTRY_PATH),
            "predecessor_scorer": file_identity(root, root / DG24_SCORER_PATH),
            "predecessor_scorer_receipt": file_identity(
                root, root / DG24_SCORER_RECEIPT_PATH
            ),
            "dg25_effect_scorer_status": "NOT_YET_SEALED_EFFECT_SCORING_BLOCKED",
        },
        "arm_order": {
            "S2": ["R0", "R0P"],
            "E1": [
                "R0",
                "R0P",
                "R1",
                "R2",
                "R3",
                "R4",
                "R5_NO_SYNONYM_NORMALIZATION",
                "R_FINAL_DROP_UNIFIED_PROOF_FIRST",
                "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
                "R_FINAL_DROP_ROLE_RESERVATION",
                "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
            ],
            "E2": ["T0", "T1", "T2", "T3", "T4"],
            "E3": ["C0_FRESH_CANDIDATE_OFF", "C1_FRESH_FINAL_MINIMAL_CANDIDATE_ON"],
            "E4": ["A0", "A1", "A2", "A3"],
        },
        "reviewed_blocks": review["approved_plan"]["blocks"],
        "cost_ledger_fields": [
            "logical_selected_actions",
            "physical_repository_calls",
            "replayed_repository_calls",
            "returned_rows",
            "range_rows_scanned",
            "candidates_returned",
            "candidates_hydrated",
            "candidates_bound",
            "candidates_shown_to_reader",
            "state_passes",
            "reader_calls",
            "latency_ms",
        ],
        "claim_boundary": review["approved_plan"]["claim_boundary"],
        "label_boundary": {
            "population": "OPENED_DEVELOPMENT_HISTORICALLY_LABEL_INFORMED",
            "same_run_product_before_score_required": True,
            "same_run_seal_is_unbiased_validation": False,
            "labels_loaded": False,
            "formal_holdout_consumed": False,
        },
        "authorization": {
            "S2_zero_model_label_free": True,
            "E1_E2_effect_scoring": False,
            "E3_opened_dev_treatment": False,
            "E4_reader_calls": False,
            "latency_repeats": False,
            "candidate_default": False,
            "model_provider_controller_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
        },
    }
    return {"manifest_digest": canonical_sha256(material), **material}


def build_stop_rule_registry(review: Mapping[str, Any]) -> dict[str, Any]:
    rules = review.get("stopping_rules")
    if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
        raise DG25ReviewGateError("review stopping rules missing")
    machine_rules = [
        {"id": "STOP_IDENTITY_DRIFT", "expected": 0, "observed_field": "identity_drift"},
        {"id": "STOP_LABEL_BEFORE_SEAL", "expected": 0, "observed_field": "label_before_seal"},
        {"id": "STOP_UNMATCHED_POOL_K", "expected": 0, "observed_field": "pool_k_mismatch"},
        {"id": "STOP_INVALID_PLAN", "expected": 0, "observed_field": "invalid_plan_count"},
        {"id": "STOP_BUDGET_OVERFLOW", "expected": 0, "observed_field": "budget_overflow"},
        {"id": "STOP_PRECISION", "expected": 1.0, "observed_field": "accepted_binding_precision"},
        {"id": "STOP_WRONG_COMPLETE", "expected": 0, "observed_field": "wrong_complete"},
        {"id": "STOP_BOUNDARY_DRIFT", "expected": 0, "observed_field": "boundary_drift"},
        {"id": "STOP_FORBIDDEN_CALL", "expected": 0, "observed_field": "forbidden_calls"},
        {"id": "STOP_POST_SCORE_ADAPTATION", "expected": 0, "observed_field": "post_score_adaptation"},
    ]
    return {
        "schema": "milai.dg25.stop-rule-registry.v0.1",
        "automatic_retries": 0,
        "review_rules": list(rules),
        "machine_rules": machine_rules,
        "downstream_dependencies": {
            "E4_requires_E3_C1_pass": True,
            "latency_requires_correctness_seal": True,
            "schema_change_disposition": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
            "reader_mismatch_disposition": "FALLBACK_OR_ABSTAIN_NO_RETRY",
        },
    }


def build_executor_feasibility(review: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "milai.dg25.executor-feasibility-review.v0.1",
        "status": "FEASIBLE_S2_ONLY",
        "review_verdict": review["verdict"],
        "compute": {
            "S2_gpu_hours": 0,
            "S2_model_provider_controller_calls": 0,
            "S2_physical_repository_calls_for_matched_replay": 0,
            "implementation_and_tests": "CPU_ONLY",
        },
        "code_change_scope": [
            "candidate-only internal plan compiler and validator",
            "official executor batch path with one final recomputation",
            "default-OFF internal feature flag",
            "R0-to-R0P equivalence and negative tests",
        ],
        "forbidden_change_scope": [
            "architecture/v1.0",
            "public MCP contracts",
            "PostgreSQL migrations",
            "canonical state",
            "Reader/provider/model/controller calls",
        ],
        "dependencies": [
            "RE-01/RE-07/RE-08 freeze",
            "S2 compiler/validator",
            "R0-to-R0P equivalence",
            "S2 source and receipt seal",
        ],
        "cuts": [],
        "later_not_authorized": [
            "E1/E2 effect scoring before DG25 scorer identity seal",
            "E3 opened-development treatment",
            "E4 Reader execution",
            "latency repeats",
        ],
    }


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise DG25ReviewGateError(f"required string missing: {key}")
    return item


def _required_sha(value: Mapping[str, Any], key: str) -> str:
    item = _required_string(value, key)
    if len(item) != 64 or any(char not in "0123456789abcdef" for char in item):
        raise DG25ReviewGateError(f"required SHA-256 invalid: {key}")
    return item


__all__ = [
    "REVIEW_PATH",
    "REVIEW_SHA256",
    "S1_RECEIPT_PATH",
    "S1_RECEIPT_SHA256",
    "S1_SOURCE_MANIFEST_PATH",
    "S1_SOURCE_MANIFEST_SHA256",
    "DG25ReviewGateError",
    "build_exact_query_freeze",
    "build_executor_feasibility",
    "build_pre_treatment_arm_manifest",
    "build_stop_rule_registry",
    "load_and_validate_independent_review",
    "validate_independent_review_payload",
]
