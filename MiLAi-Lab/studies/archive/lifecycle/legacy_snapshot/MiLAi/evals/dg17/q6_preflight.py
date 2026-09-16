"""Artifact-only DG-17 Q6 matched-confirmation preflight.

This module validates the frozen denominator and predecessor receipts without
starting Runtime, retrieval, a Reader, or the SemanticQueryHint provider.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_ir_compat import infer_operator_family

from evals.dg14.provider import full_provider_contract_sha256
from evals.dg17.measurement import (
    DG16_CONTEXTS_PATH,
    DG16_CONTEXTS_SHA256,
    DG16_RECEIPT_PATH,
    DG16_RECEIPT_SHA256,
    load_answer_bearing_labels,
)
from evals.paper.provider import EXPECTED_PROMPT_CONTRACT_SHA256, MODEL_ID

ROOT = Path(__file__).resolve().parents[2]
GOAL = ROOT / "MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md"
DEFAULT_LOCAL_GATE_RECEIPT = (
    ROOT / "var/dg17/local-gate/dg17-local-gate-20260827-019/receipt.json"
)

BOUND_ARTIFACTS: tuple[tuple[str, Path, str, str], ...] = (
    (
        "goal",
        GOAL,
        "c316bd0ed89ab32cb4f53b45f28c7441c79a6548c4cfa7c56de9b21c2f70d4cb",
        "DOCUMENT",
    ),
    (
        "semantic_read_runbook",
        ROOT / "docs/runbooks/dg17-semantic-read.md",
        "51247f6994e534d756d39c3e2c24be22466e22934253a3433e1ccc5786eeac55",
        "DOCUMENT",
    ),
    (
        "evidence_atom_v01_compatibility_disposition",
        ROOT / "docs/dg17/q3a-compatibility-disposition.md",
        "816b69ef30681e10e8aa76faf15087c57dea8464f94cee18ef2b3532bf163238",
        "DOCUMENT",
    ),
    (
        "answer_bearing_annotation_manifest",
        ROOT / "docs/dg17/answer-bearing-labels-annotation-manifest.v0.1.json",
        "1526c5f7fcac478ca3bb50baf64a7aafed60a17c9ad39b11cf113a2f85beeb6b",
        "DOCUMENT",
    ),
    (
        "q0_receipt_lineage_disposition",
        ROOT / "docs/dg17/q0-receipt-lineage-disposition.v0.1.json",
        "f71acb4fdf93511c609b9a8b8ffb9876998fea02c2ca01746abdd4f111ef9e9e",
        "DOCUMENT",
    ),
    (
        "q0_multiseed_oracle",
        ROOT / "var/dg17/q0/dg17-q0-multiseed-20260827-001/receipt.json",
        "60cdcc64b8bad73f6a647d3f45560faa7c7b9cff8ace5514072d8bca7e7f1e80",
        "Q0_MULTI_SEED_ORACLE_CHARACTERIZED",
    ),
    (
        "q1_matched",
        ROOT / "var/dg17/q1/dg17-q1-p0-matched-20260827-002/receipt.json",
        "d9c9d304fef3c9d5becf71d875f5d48df4242813bd289dadd338f9f948ac94cb",
        "CHARACTERIZED",
    ),
    (
        "q3a_crosswalk",
        ROOT / "var/dg17/q3a/dg17-q3a-crosswalk-20260827-003/crosswalk.json",
        "e3fe3fbdd856a5239687516ec99b9c56922405d9b1d896ed11e71c626be6ba6a",
        "Q3A_CROSSWALK_COMPLETE",
    ),
    (
        "q1r_context_archive",
        ROOT / "var/dg17/q1r/dg17-q1r-contexts-20260827-004/contexts.json",
        "35007cb9c653dff5e792c2e495cf8627c8d89309e18f1958821bf32527a95c1e",
        "SUCCEEDED",
    ),
    (
        "q1r_context_producer",
        ROOT
        / "var/dg17/q1r/dg17-q1r-contexts-20260827-004/producer-receipt.json",
        "1d5cf8c014c915d18c218c648e921a3faa19c9fc13971a135bd6bcc6170ce472",
        "SUCCEEDED",
    ),
    (
        "q1r_generation_archive",
        ROOT
        / "var/dg17/q1r/dg17-q1r-matched-20260827-003/generations.json",
        "505c4ab7e7fe0a3d7ecce5c520adc9e8307a4493d64af6b5de2585b474b17c9d",
        "SUCCEEDED",
    ),
    (
        "q1r_matched",
        ROOT / "var/dg17/q1r/dg17-q1r-matched-20260827-003/receipt.json",
        "10a23068424379d0d42842223ce74b1ba98fe8e5a1537299a72e541f946ea2d1",
        "Q1R_CONTEXT_STABILITY_PASS",
    ),
    (
        "q3b_deterministic_fixtures",
        ROOT
        / "var/dg17/q3c/dg17-q3b-deterministic-fixtures-20260827-003/report.json",
        "931c38193d1b74fcfbbcf9149a4a02585336b5eecab0c03b9767314b3c72c4eb",
        "Q3C_INFRASTRUCTURE_READY_NO_MODEL_CALLS",
    ),
    (
        "q3c_live_shadow",
        ROOT / "var/dg17/q3c/dg17-q3c-shadow-20260827-004/report.json",
        "29227f554f941d340bbefcf330b4993ef362815df446fd052e059e5a26bc9cb5",
        "Q3C_SHADOW_CHARACTERIZED",
    ),
    (
        "q4_product_vertical",
        ROOT / "var/dg17/q4/dg17-q4q5-product-20260827-003/report.json",
        "e0baf2924f6dd95eebc5d16f17961186db8cf95a35b411d101aa1c15598ca524",
        "Q4_PRODUCT_VERTICAL_COMPLETE",
    ),
    (
        "q5_product_vertical",
        ROOT / "var/dg17/q5/dg17-q4q5-product-20260827-003/report.json",
        "6c11309e4f7d99c4fed094a3bb24436b4763f6cae2ecdbbd4630573861123195",
        "Q5_PRODUCT_VERTICAL_COMPLETE",
    ),
    (
        "reader_exact_match_stability",
        ROOT
        / "var/dg16/reader-stability/dg16-reader-stability-20260827-001/receipt.json",
        "9186a2629fc15b47076ce98f45a86551f8e2360b409b438bbee447f5c10dc56b",
        "CHARACTERIZED",
    ),
)

_EXPECTED_FAMILY = {
    "LOOKUP": "LOOKUP",
    "TEMPORAL_FILTER": "TEMPORAL_FILTER",
    "TEMPORAL_ORDER": "TEMPORAL_ORDER",
    "TEMPORAL_DISTANCE": "TEMPORAL_DISTANCE",
    "COUNT_DISTINCT": "COUNT",
    "DIVIDE_VALUES": "DIVIDE",
    "MULTI_EVIDENCE_JOIN": "MULTI_JOIN",
    "PREFERENCE_RESOLVE": "PREFERENCE_RESOLVE",
}


class Q6PreflightError(RuntimeError):
    """A frozen Q6 input or predecessor receipt drifted."""


def build_q6_preflight(
    *, local_gate_receipt: Path = DEFAULT_LOCAL_GATE_RECEIPT
) -> dict[str, Any]:
    artifacts = _load_bound_artifacts()
    artifacts["local_deterministic_gate"] = _load_observed_artifact(
        local_gate_receipt,
        expected_status="PASS",
    )
    _envelope, cases, labels = load_answer_bearing_labels()
    q1 = artifacts["q1_matched"]["value"]
    q0_multiseed = artifacts["q0_multiseed_oracle"]["value"]
    q3a = artifacts["q3a_crosswalk"]["value"]
    q1r_contexts = artifacts["q1r_context_archive"]["value"]
    q1r_producer = artifacts["q1r_context_producer"]["value"]
    q1r_generations = artifacts["q1r_generation_archive"]["value"]
    q1r = artifacts["q1r_matched"]["value"]
    q3b = artifacts["q3b_deterministic_fixtures"]["value"]
    q3c = artifacts["q3c_live_shadow"]["value"]
    q4 = artifacts["q4_product_vertical"]["value"]
    q5 = artifacts["q5_product_vertical"]["value"]
    stability = artifacts["reader_exact_match_stability"]["value"]

    compiler = MemoryQueryCompiler()
    case_matrix: list[dict[str, Any]] = []
    for case in cases:
        label = labels[case.case_id]
        ir = compiler.compile(
            case.question,
            reference_time=_reference_time(case.question_at),
        )
        family = infer_operator_family(ir)
        expected_family = _EXPECTED_FAMILY[str(label["gold_ir"]["operator"])]
        case_matrix.append(
            {
                "case_id": case.case_id,
                "query_class": label["gold_ir"]["query_class"],
                "gold_operator_family": expected_family,
                "deterministic_route": ir.mode,
                "deterministic_operator_family": family,
                "deterministic_operator_expected": family == expected_family,
                "deterministic_auxiliary_model_calls": (
                    ir.planner_trace.auxiliary_model_calls
                ),
                "token_budgets": [512, 2048],
                "matched_cells": 2,
                "execution_status": "READY_FOR_SEALED_Q1R_SCORING",
            }
        )

    current10_shadow_rows = [
        row
        for row in q3c["rows"]
        if str(row.get("case_id", "")).startswith("current10:")
    ]
    if len(current10_shadow_rows) != 10:
        raise Q6PreflightError("Q3C current-10 shadow denominator drifted")
    if q3a["denominators"]["case_count"] != 10:
        raise Q6PreflightError("Q3A measurement denominator drifted")
    if q4["gate"]["wrong_complete"] != 0 or q5["gate"]["wrong_complete"] != 0:
        raise Q6PreflightError("Q4/Q5 wrong-COMPLETE gate regressed")
    if not all(row["deterministic_operator_expected"] for row in case_matrix):
        raise Q6PreflightError("current-10 deterministic operator preflight failed")
    q3a_typed_contract_passed = q3a["typed_contract_gate"]["status"] == "PASS"
    q3b_declared_fixture_passed = (
        q3b["deterministic_correct"] == q3b["supported_denominator"]
        and q3b["unsafe_generic_lookup_promotions"] == 0
        and all(row["auxiliary_model_calls"] == 0 for row in q3b["rows"])
    )
    q1r_ready = (
        q1r["gate"]["status"] == "PASS"
        and q1r["gate"]["pair_count"] == 20
        and q1r["gate"]["causally_valid_count"] == 20
        and q1r["context_archive"]["sha256"]
        == artifacts["q1r_context_archive"]["sha256"]
        and q1r["generation_archive"]["sha256"]
        == artifacts["q1r_generation_archive"]["sha256"]
        and q1r_producer["context_archive"]["sha256"]
        == artifacts["q1r_context_archive"]["sha256"]
        and q1r_contexts["record_count"] == 40
        and q1r_generations["record_count"] == 40
    )
    if not q1r_ready:
        raise Q6PreflightError("Q1R same-snapshot predecessor gate regressed")

    stability_diagnosis = stability["diagnosis"]
    historical_boundary = stability["historical_strict_em_boundary"]
    q1_summaries = q1["summaries"]
    return {
        "schema": "milai.dg17.q6-matched-preflight.v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY / ARTIFACT_PREFLIGHT",
        "status": "Q6_PREFLIGHT_COMPLETE_EXECUTION_AUTHORIZED",
        "execution_authorized": True,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "execution": {
            "runtime_started": False,
            "retrieval_calls": 0,
            "reader_calls": 0,
            "semantic_hint_calls": 0,
            "semantic_repair_calls": 0,
            "automatic_retries": 0,
            "external_experiments": "AUTHORIZED_BY_USER / SEALED_SCORING_NOT_STARTED",
        },
        "frozen_contract": {
            "case_count": 10,
            "case_order": [case.case_id for case in cases],
            "token_budgets": [512, 2048],
            "cell_count_per_executed_arm": 20,
            "reader_model_id": MODEL_ID,
            "reader_prompt_contract_sha256": EXPECTED_PROMPT_CONTRACT_SHA256,
            "provider_contract_sha256": full_provider_contract_sha256(),
            "same_reader_prompt_generation_required": True,
            "same_case_order_and_answer_seed_required": True,
            "same_immutable_evidence_snapshot_per_pair_required": True,
            "stable_reader_aliases_required": True,
            "semantic_context_digest_required": True,
            "exact_reader_context_digest_required": True,
            "exact_serialized_prompt_digest_required": True,
            "historical_answer_reuse_allowed": False,
            "automatic_retries": 0,
            "baseline_arms": ["DG16-MILAI-MCP", "BM25-T"],
            "baseline_receipt": {
                "path": str(DG16_RECEIPT_PATH.relative_to(ROOT)),
                "sha256": DG16_RECEIPT_SHA256,
            },
            "baseline_contexts": {
                "path": str(DG16_CONTEXTS_PATH.relative_to(ROOT)),
                "sha256": DG16_CONTEXTS_SHA256,
            },
        },
        "artifact_bindings": {
            name: {key: value for key, value in artifact.items() if key != "value"}
            for name, artifact in artifacts.items()
        },
        "readiness": {
            "semantic_read_runbook_available": (
                artifacts["semantic_read_runbook"]["status"] == "DOCUMENT"
            ),
            "evidence_atom_v01_transition_disposition_available": (
                artifacts["evidence_atom_v01_compatibility_disposition"]["status"]
                == "DOCUMENT"
            ),
            "local_deterministic_gate_passed": (
                artifacts["local_deterministic_gate"]["status"] == "PASS"
            ),
            "answer_bearing_annotation_manifest_available": True,
            "answer_bearing_annotation_independent_review_complete": False,
            "q0_receipt_lineage_disposition_available": True,
            "q0_multiseed_oracle_receipt_available": True,
            "q0_authoritative_oracle_receipt_available": q0_multiseed[
                "authoritative_for_q0_measurement_gate"
            ],
            "q1r_stable_context_implementation_available": True,
            "q1r_same_snapshot_matched_receipt_available": True,
            "q1r_context_stability_gate_passed": True,
            "measurement_crosswalk_available": True,
            "q3a_typed_contract_gate_passed": (
                q3a_typed_contract_passed
            ),
            "q3c_shadow_infrastructure_available": True,
            "q3c_live_shadow_characterized": True,
            "q3_typed_requirement_identity_gate_passed": (
                q3a_typed_contract_passed and q3b_declared_fixture_passed
            ),
            "q3b_declared_fixture_gate_passed": q3b_declared_fixture_passed,
            "q4_temporal_cases_expected": q4["gate"]["operator_expected"],
            "q4_temporal_case_denominator": q4["gate"]["required_case_count"],
            "q4_wrong_complete": q4["gate"]["wrong_complete"],
            "q5_wrong_complete": q5["gate"]["wrong_complete"],
            "current10_deterministic_operator_expected": sum(
                row["deterministic_operator_expected"] for row in case_matrix
            ),
            "current10_deterministic_operator_denominator": len(case_matrix),
            "q6_live_matched_receipt_available": False,
        },
        "arms": {
            "DG16_CURRENT": "FROZEN_BASELINE_AVAILABLE",
            "BM25_T": "FROZEN_BASELINE_AVAILABLE",
            "DG17_DETERMINISTIC_ONLY": "SEALED_Q1R_CURRENT_ARM_READY_FOR_SCORING",
            "DG17_MINIMAL_SEMANTIC_QUERY_HINT_EXECUTED": (
                "NOT_AUTHORIZED_REQUIRES_UNBIASED_Q3C_MEDIATOR_GAIN"
            ),
            "DG17_MINIMAL_SEMANTIC_QUERY_HINT_SHADOW_COST_OVERLAY": (
                "COUNTERFACTUAL_ONLY_Q3C_CHARACTERIZED"
            ),
            "DG17_ONE_CALL_SEMANTIC_REPAIR": "PARKED_NOT_NEEDED",
        },
        "baseline_characterization": {
            "quality_causal_disposition": (
                "INCONCLUSIVE_READER_IDENTITY_AND_MATCHING_CONFOUNDED"
            ),
            "dg16_2048": q1_summaries["DG16_ANY_EVIDENCE_STOP"]["2048"],
            "q1_sufficiency_only_2048": q1_summaries["DG17_QUERY_SPECIFIC_STOP"][
                "2048"
            ],
        },
        "reader_exact_match_stability_boundary": {
            "scope": "HISTORICAL_INDEPENDENT_SINGLE_CASE_NOT_Q6_DENOMINATOR",
            "strict_em_boundary_observed": historical_boundary["observed"],
            "same_payload_reader_variability_signal": (
                stability_diagnosis["disposition"]
                == "LIVE_SAME_PAYLOAD_READER_VARIABILITY_SIGNAL"
            ),
            "retrieval_rework_indicated": stability_diagnosis[
                "retrieval_rework_indicated"
            ],
            "scorer_policy": (
                "KEEP_FROZEN_EM_AND_F1; REPORT_ANSWER_VARIANTS_SEPARATELY; "
                "DO_NOT_RESCORE_OR_MIX_DENOMINATORS"
            ),
        },
        "reporting_contract": {
            "per_case_stage_rows_required": True,
            "per_query_class_required": True,
            "aggregate_only_forbidden": True,
            "answer_session_coverage_required": True,
            "answer_bearing_span_recall_required": True,
            "requirement_binding_precision_required": True,
            "required_evidence_set_coverage_required": True,
            "operator_execution_accuracy_required": True,
            "reader_exact_match_and_normalized_f1_required": True,
            "semantic_assist_call_rate_and_tokens_required": True,
            "executed_semantic_assist_latency_and_coverage_delta_required": True,
            "shadow_cost_overlay_must_not_be_reported_as_quality_arm": True,
            "wrong_promoted_hint_invalid_schema_timeout_required": True,
            "quality_per_second_required": True,
            "same_snapshot_pair_receipt_required": True,
            "semantic_context_digest_required": True,
            "reader_context_digest_required": True,
            "exact_serialized_prompt_digest_required": True,
            "unexplained_prompt_diff_excluded_from_causal_claim": True,
            "triggered_stability_repeats": 3,
            "stability_repeats_cannot_replace_primary": True,
        },
        "case_matrix": case_matrix,
        "blocking_conditions": [
            "Q0_MULTI_SEED_ORACLE_PROVISIONAL_PENDING_LABEL_REVIEW",
            "ANSWER_BEARING_LABEL_INDEPENDENT_REVIEW_PENDING",
            "Q6_DG17_DETERMINISTIC_MATCHED_ARM_NOT_RUN",
        ],
        "release_claim_authorized": False,
    }


def _load_bound_artifacts() -> dict[str, dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    for name, path, expected_sha256, expected_status in BOUND_ARTIFACTS:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_sha256:
            raise Q6PreflightError(f"bound artifact drifted: {path}")
        if expected_status == "DOCUMENT":
            value: dict[str, Any] = {}
        else:
            decoded = json.loads(raw)
            if not isinstance(decoded, dict) or decoded.get("status") != expected_status:
                raise Q6PreflightError(f"bound artifact status drifted: {path}")
            value = decoded
        observed[name] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": digest,
            "status": expected_status,
            "value": value,
        }
    if hashlib.sha256(DG16_RECEIPT_PATH.read_bytes()).hexdigest() != DG16_RECEIPT_SHA256:
        raise Q6PreflightError("DG16 baseline receipt drifted")
    if hashlib.sha256(DG16_CONTEXTS_PATH.read_bytes()).hexdigest() != DG16_CONTEXTS_SHA256:
        raise Q6PreflightError("DG16 baseline contexts drifted")
    return observed


def _load_observed_artifact(
    path: Path, *, expected_status: str
) -> dict[str, Any]:
    path = path if path.is_absolute() else ROOT / path
    raw = path.read_bytes()
    decoded = json.loads(raw)
    if not isinstance(decoded, dict) or decoded.get("status") != expected_status:
        raise Q6PreflightError(f"observed artifact status drifted: {path}")
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "status": expected_status,
        "value": decoded,
    }


def _reference_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


__all__ = ["Q6PreflightError", "build_q6_preflight"]
