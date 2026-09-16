from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATE = "2026-08-22"
THREE_ARM_REPORT = (
    ROOT
    / "docs/reports/DG-10-benchmark-three-arm-dev-candidate.3-2026-08-22.json"
)
THREE_ARM_SHA256 = "6c7b2261e82bbbbc417f371983fbdea921e1f7f123f394c705cfd7091f5ee10e"
BFCL_REPORT = ROOT / "docs/reports/DG-10-bfcl-dev-aggregate-candidate.1-2026-08-21.json"
BFCL_SHA256 = "8bfce6d9bc957abe16404c419687050791375cbfb7951fd0e8f3119b8997cfc5"
LME_V2_REPORT = (
    ROOT
    / "docs/reports/DG-10-benchmark-lme-v2-dev-smoke-candidate.3-2026-08-21.json"
)
LME_V2_SHA256 = "7caa9609a01883f89b696ad40b631940aaf2937cbd5377726da0d9e33ac3f0d9"
DATASET_LOCK_REPORT = (
    ROOT / "docs/reports/DG-10-benchmark-dataset-lock-candidate.3-2026-08-21.json"
)
DATASET_LOCK_SHA256 = "889e99fa19e695db5b10d1ff72964aee5fbfc4426f4c67504ed4340742ffa62e"
FEASIBILITY_REPORT = (
    ROOT / "docs/reports/DG-10-benchmark-feasibility-candidate.3-2026-08-21.json"
)
FEASIBILITY_SHA256 = "c3e4796da2413acce778c338188e901c9300f918f39620ac89f535c8f391a79f"
BFCL_PLAN_REPORT = (
    ROOT
    / "docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-2026-08-21.json"
)
LME_DATASET = WORKSPACE_ROOT / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
LME_DATASET_SHA256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
TIER2_RUBRIC = ROOT / "docs/contracts/DG-10-tier2-blinded-audit-rubric.md"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-quality-calibration-assessment-candidate.1-{DATE}.json"
)
ARMS = ("NO_MEMORY", "NAIVE_RAG", "MILAI_MCP")
TIER2_SALT = "dg10-tier2-v1"


class QualityAssessmentError(RuntimeError):
    pass


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )


def _load_bound(path: Path, expected_sha256: str) -> dict[str, Any]:
    if _sha256_file(path) != expected_sha256:
        raise QualityAssessmentError(f"bound input drift: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualityAssessmentError(f"bound input is not an object: {path.name}")
    return value


def _arm_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arm in ARMS:
        selected = [record for record in records if record.get("arm") == arm]
        if len(selected) != 50:
            raise QualityAssessmentError("LongMemEval arm denominator drift")
        result[arm] = {
            "case_count": len(selected),
            "exact_match_mean": round(
                mean(int(item["answer_record"]["exact_match"]) for item in selected),
                6,
            ),
            "normalized_f1_mean": round(
                mean(
                    float(item["answer_record"]["normalized_f1"])
                    for item in selected
                ),
                6,
            ),
            "input_tokens": sum(int(item["usage"]["input_tokens"]) for item in selected),
            "output_tokens": sum(
                int(item["usage"]["output_tokens"]) for item in selected
            ),
        }
    return result


def _ability_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: defaultdict[str, defaultdict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in records:
        grouped[str(record["category"])][str(record["arm"])].append(record)
    result: dict[str, Any] = {}
    for category, arms in sorted(grouped.items()):
        arm_values: dict[str, Any] = {}
        for arm in ARMS:
            selected = arms[arm]
            arm_values[arm] = {
                "case_count": len(selected),
                "exact_match_mean": round(
                    mean(
                        int(item["answer_record"]["exact_match"])
                        for item in selected
                    ),
                    6,
                ),
                "normalized_f1_mean": round(
                    mean(
                        float(item["answer_record"]["normalized_f1"])
                        for item in selected
                    ),
                    6,
                ),
            }
        strongest = max(
            ("NO_MEMORY", "NAIVE_RAG"),
            key=lambda arm: (
                arm_values[arm]["normalized_f1_mean"],
                arm_values[arm]["exact_match_mean"],
            ),
        )
        result[category] = {
            "arms": arm_values,
            "strongest_fixed_baseline": strongest,
            "milai_minus_strongest_baseline": {
                "exact_match_mean": round(
                    arm_values["MILAI_MCP"]["exact_match_mean"]
                    - arm_values[strongest]["exact_match_mean"],
                    6,
                ),
                "normalized_f1_mean": round(
                    arm_values["MILAI_MCP"]["normalized_f1_mean"]
                    - arm_values[strongest]["normalized_f1_mean"],
                    6,
                ),
            },
        }
    return result


def _evidence_metrics(
    records: Sequence[Mapping[str, Any]], rows: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arm in ("NAIVE_RAG", "MILAI_MCP"):
        selected = [record for record in records if record["arm"] == arm]
        hits = 0
        for record in selected:
            row = rows[str(record["source_case_id"])]
            gold = row.get("answer_session_ids")
            retrieved = record["trace"]["retrieved_evidence_ids"]
            if (
                not isinstance(gold, list)
                or not gold
                or not isinstance(retrieved, list)
                or len(retrieved) != 1
            ):
                raise QualityAssessmentError("evidence Recall@1 input drift")
            hits += int(bool(set(gold) & set(retrieved)))
        result[arm] = {
            "case_count": len(selected),
            "hit_count": hits,
            "recall_at_1": round(hits / len(selected), 6),
            "precision_at_1": round(hits / len(selected), 6),
            "mrr_at_1": round(hits / len(selected), 6),
        }
    result["milai_minus_naive_rag_recall_at_1"] = round(
        result["MILAI_MCP"]["recall_at_1"]
        - result["NAIVE_RAG"]["recall_at_1"],
        6,
    )
    return result


def _tier2_manifest(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    categories: defaultdict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for record in records:
        case_id = str(record["case_id"])
        if case_id in seen:
            continue
        seen.add(case_id)
        categories[str(record["category"])].append(case_id)
    selected: list[str] = []
    counts: dict[str, int] = {}
    for category, case_ids in sorted(categories.items()):
        chosen = sorted(
            case_ids,
            key=lambda case_id: (
                _sha256_bytes(f"{TIER2_SALT}\0{case_id}".encode()),
                case_id,
            ),
        )[:2]
        if len(chosen) != 2:
            raise QualityAssessmentError("Tier-2 stratum has fewer than two cases")
        selected.extend(chosen)
        counts[category] = len(chosen)
    selected.sort()
    if len(selected) != 12:
        raise QualityAssessmentError("Tier-2 selected denominator drift")
    return {
        "status": "PRE_FROZEN_AUDIT_NOT_STARTED",
        "selection": "TWO_SHA256_LOWEST_CASE_IDS_PER_LONGMEMEVAL_ABILITY",
        "salt_version": TIER2_SALT,
        "case_count": len(selected),
        "case_ids": selected,
        "case_ids_sha256": _json_sha256(selected),
        "stratum_counts": counts,
        "rubric_path": TIER2_RUBRIC.relative_to(ROOT).as_posix(),
        "rubric_sha256": _sha256_file(TIER2_RUBRIC),
        "arm_identity_blinded": True,
        "human_annotations_present": False,
    }


def assess() -> dict[str, Any]:
    three_arm = _load_bound(THREE_ARM_REPORT, THREE_ARM_SHA256)
    bfcl = _load_bound(BFCL_REPORT, BFCL_SHA256)
    lme_v2 = _load_bound(LME_V2_REPORT, LME_V2_SHA256)
    dataset_lock = _load_bound(DATASET_LOCK_REPORT, DATASET_LOCK_SHA256)
    feasibility = _load_bound(FEASIBILITY_REPORT, FEASIBILITY_SHA256)
    bfcl_plan = json.loads(BFCL_PLAN_REPORT.read_text(encoding="utf-8"))
    if (
        three_arm.get("status")
        != "THREE_ARM_LONGMEMEVAL_DEV_CALIBRATION_COMPLETE"
        or three_arm.get("test_labels_or_outputs_opened") is not False
        or bfcl.get("status")
        != "BFCL_ADAPTED_LOCAL_NON_LIVE_216_DEV_CHARACTERIZATION_COMPLETE"
        or bfcl.get("test_execution") == "AUTHORIZED"
    ):
        raise QualityAssessmentError("calibration report boundary mismatch")
    records = three_arm.get("records")
    if not isinstance(records, list) or len(records) != 150:
        raise QualityAssessmentError("three-arm calibration denominator drift")
    if _sha256_file(LME_DATASET) != LME_DATASET_SHA256:
        raise QualityAssessmentError("LongMemEval dataset bytes drift")
    raw_rows = json.loads(LME_DATASET.read_text(encoding="utf-8"))
    rows = {
        str(row["question_id"]): row
        for row in raw_rows
        if isinstance(row, dict) and isinstance(row.get("question_id"), str)
    }
    arm_metrics = _arm_metrics(records)
    ability_metrics = _ability_metrics(records)
    evidence_metrics = _evidence_metrics(records, rows)
    strongest = max(
        ("NO_MEMORY", "NAIVE_RAG"),
        key=lambda arm: (
            arm_metrics[arm]["normalized_f1_mean"],
            arm_metrics[arm]["exact_match_mean"],
        ),
    )
    overall_delta = {
        "exact_match_mean": round(
            arm_metrics["MILAI_MCP"]["exact_match_mean"]
            - arm_metrics[strongest]["exact_match_mean"],
            6,
        ),
        "normalized_f1_mean": round(
            arm_metrics["MILAI_MCP"]["normalized_f1_mean"]
            - arm_metrics[strongest]["normalized_f1_mean"],
            6,
        ),
    }
    bfcl_aggregates = bfcl["aggregates"]
    observed = {
        "longmemeval_overall_f1_delta": overall_delta["normalized_f1_mean"],
        "longmemeval_overall_exact_match_delta": overall_delta["exact_match_mean"],
        "knowledge_update_f1_delta": ability_metrics["knowledge-update"][
            "milai_minus_strongest_baseline"
        ]["normalized_f1_mean"],
        "temporal_reasoning_f1_delta": ability_metrics["temporal-reasoning"][
            "milai_minus_strongest_baseline"
        ]["normalized_f1_mean"],
        "evidence_recall_at_1_delta": evidence_metrics[
            "milai_minus_naive_rag_recall_at_1"
        ],
        "bfcl_overall_accuracy": float(
            bfcl_aggregates["adapted_official_checker_accuracy"]
        ),
        "bfcl_multi_turn_accuracy": float(bfcl_aggregates["multi_turn"]["accuracy"]),
        "bfcl_no_call_accuracy": float(
            bfcl_aggregates["category_metrics"]["irrelevance"]["no_call_accuracy"]
        ),
        "hidden_or_extra_model_calls": int(three_arm["hidden_or_extra_model_calls"]),
        "max_memory_context_tokens": max(
            int(record["trace"]["memory_context_tokens_attribution"])
            for record in records
        ),
        "max_aggregate_input_tokens_per_arm_case": max(
            int(record["usage"]["input_tokens"]) for record in records
        ),
    }
    thresholds = {
        "longmemeval_overall_f1_delta_min": 0.0,
        "longmemeval_overall_exact_match_delta_min": 0.0,
        "knowledge_update_f1_delta_min": 0.0,
        "temporal_reasoning_f1_delta_min": 0.0,
        "evidence_recall_at_1_delta_min": 0.0,
        "bfcl_overall_accuracy_min": 0.8,
        "bfcl_multi_turn_accuracy_min": 0.5,
        "bfcl_no_call_accuracy_min": 0.8,
        "hidden_or_extra_model_calls_max": 0,
        "memory_context_tokens_max": 512,
        "aggregate_input_tokens_per_arm_case_max": 32768,
    }
    checks = {
        "longmemeval_overall_f1": observed["longmemeval_overall_f1_delta"]
        >= thresholds["longmemeval_overall_f1_delta_min"],
        "longmemeval_overall_exact_match": observed[
            "longmemeval_overall_exact_match_delta"
        ]
        >= thresholds["longmemeval_overall_exact_match_delta_min"],
        "knowledge_update": observed["knowledge_update_f1_delta"]
        >= thresholds["knowledge_update_f1_delta_min"],
        "temporal_reasoning": observed["temporal_reasoning_f1_delta"]
        >= thresholds["temporal_reasoning_f1_delta_min"],
        "evidence_recall": observed["evidence_recall_at_1_delta"]
        >= thresholds["evidence_recall_at_1_delta_min"],
        "bfcl_overall": observed["bfcl_overall_accuracy"]
        >= thresholds["bfcl_overall_accuracy_min"],
        "bfcl_multi_turn": observed["bfcl_multi_turn_accuracy"]
        >= thresholds["bfcl_multi_turn_accuracy_min"],
        "bfcl_no_call": observed["bfcl_no_call_accuracy"]
        >= thresholds["bfcl_no_call_accuracy_min"],
        "hidden_calls": observed["hidden_or_extra_model_calls"]
        <= thresholds["hidden_or_extra_model_calls_max"],
        "memory_context": observed["max_memory_context_tokens"]
        <= thresholds["memory_context_tokens_max"],
        "aggregate_input": observed["max_aggregate_input_tokens_per_arm_case"]
        <= thresholds["aggregate_input_tokens_per_arm_case_max"],
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    if not failed:
        raise QualityAssessmentError("expected dev NO-GO unexpectedly disappeared")
    return {
        "schema": "milai.dg10.quality-calibration-assessment.v1",
        "date": DATE,
        "candidate": "candidate.1",
        "status": "PRETEST_QUALITY_CONTRACT_FREEZE_INPUT_COMPLETE",
        "quality_outcome": "BELOW_TARGET",
        "test_authorization_decision": "DENY_DEV_BELOW_TARGET",
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": {
            "three_arm_longmemeval_dev_report_sha256": THREE_ARM_SHA256,
            "bfcl_dev_report_sha256": BFCL_SHA256,
            "lme_v2_dev_report_sha256": LME_V2_SHA256,
            "dataset_lock_report_sha256": DATASET_LOCK_SHA256,
            "feasibility_report_sha256": FEASIBILITY_SHA256,
            "bfcl_plan_report_sha256": _sha256_file(BFCL_PLAN_REPORT),
            "longmemeval_dataset_sha256": LME_DATASET_SHA256,
        },
        "longmemeval": {
            "strongest_fixed_baseline": strongest,
            "arms": arm_metrics,
            "milai_minus_strongest_baseline": overall_delta,
            "ability_metrics": ability_metrics,
            "evidence_metrics": evidence_metrics,
        },
        "longmemeval_v2": {
            "protocol": "ADAPTED_PROTOCOL",
            "three_arm_calibration_complete": False,
            "release_interpretation": "CHARACTERIZED_ONLY_NOT_TEST_AUTHORITY",
            "two_arm_aggregates": lme_v2["aggregates"],
        },
        "bfcl": {
            "eligible_case_count": bfcl_plan["split"]["eligible_case_count"],
            "dev_case_count": bfcl_plan["split"]["dev_case_count"],
            "test_case_count": bfcl_plan["split"]["test_case_count"],
            "quarantined_case_count": bfcl_plan["quarantine"]["case_count"],
            "aggregates": bfcl_aggregates,
        },
        "feasibility": {
            "longmemeval_v2": feasibility["datasets"]["longmemeval_v2"],
            "longmemeval": feasibility["datasets"]["longmemeval"],
            "bfcl_v4_local_non_live": feasibility["datasets"][
                "bfcl_v4_local_non_live"
            ],
            "dataset_lock_status": dataset_lock["status"],
        },
        "tier_2_manifest": _tier2_manifest(records),
        "proposed_frozen_thresholds": thresholds,
        "observed_values": observed,
        "threshold_checks": checks,
        "failed_thresholds": failed,
        "decision_rationale": [
            "Thresholds preserve non-regression against the strongest fixed memory baseline instead of lowering the bar after observing dev outputs.",
            "The BFCL 0.80 overall/no-call floor is below the observed supported single-turn and Java/JavaScript dev accuracies but still requires useful cross-category behavior.",
            "The BFCL multi-turn 0.50 floor requires majority task completion and is not met by the observed 0.0125 accuracy.",
            "A BELOW_TARGET dev decision closes test access; test labels/outputs remain unopened and cannot be used to rescue the candidate.",
        ],
        "gate_results": {
            "BMG-02": "NO_GO_DEV_MILAI_BELOW_STRONGEST_BASELINE_TEST_DENIED",
            "BMG-03": "MODEL_QUALITY_BELOW_TARGET_DEV_CHARACTERIZATION_COMPLETE",
            "BMG-05": "FREEZE_INPUT_COMPLETE_CONTRACT_UPDATE_REQUIRED",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assess DG-10 dev evidence before freezing the quality contract"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = assess()
    raw = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    from scripts import run_dg10_benchmark_dev_smoke as dev_smoke

    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": _sha256_bytes(raw),
                "status": report["status"],
                "quality_outcome": report["quality_outcome"],
                "failed_thresholds": report["failed_thresholds"],
                "test_access_authorized": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
