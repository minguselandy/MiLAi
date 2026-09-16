from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke

DATE = "2026-08-21"
CANDIDATE = "candidate.1"
PLAN = (
    ROOT
    / f"docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-{DATE}.json"
)
SINGLE_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-prompt-single-turn-dev-calibration-candidate.1-{DATE}.json"
)
MULTITURN_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-candidate.4-{DATE}.json"
)
LANGUAGE_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-language-dev-scoring-candidate.2-{DATE}.json"
)
LANGUAGE_GENERATION_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-language-dev-generation-candidate.1-{DATE}.json"
)
MULTITURN_GENERATION_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-generation-ledger-candidate.1-{DATE}.json"
)
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-bfcl-dev-aggregate-{CANDIDATE}-{DATE}.json"
)


class BfclAggregateError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BfclAggregateError(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise BfclAggregateError(f"JSON object required: {path}")
    return value


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise BfclAggregateError("multi-turn composite ledger must be mode 0600")
    try:
        rows = [
            json.loads(raw)
            for raw in path.read_text(encoding="utf-8").splitlines()
            if raw.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise BfclAggregateError("invalid multi-turn composite ledger") from exc
    if any(not isinstance(row, dict) for row in rows):
        raise BfclAggregateError("multi-turn ledger row must be an object")
    return rows


def build_report(composite_ledger_path: Path) -> dict[str, Any]:
    plan = _load_json(PLAN)
    single = _load_json(SINGLE_REPORT)
    multi = _load_json(MULTITURN_REPORT)
    language = _load_json(LANGUAGE_REPORT)
    multi_generation = _load_json(MULTITURN_GENERATION_REPORT)
    language_generation = _load_json(LANGUAGE_GENERATION_REPORT)
    if (
        plan.get("candidate") != "candidate.5"
        or single.get("status")
        != "BFCL_ADAPTED_PROMPT_SUPPORTED_SINGLE_TURN_DEV_CALIBRATION_COMPLETE_PARTIAL"
        or multi.get("status")
        != "BFCL_MULTITURN_DEV_SCORING_COMPLETE_EXPLICIT_C13_75_PLUS_C16_5"
        or language.get("status") != "BFCL_LANGUAGE_DEV_SCORING_V2_COMPLETE"
        or multi.get("repo_external_composite_scoring_ledger", {}).get("sha256")
        != dev_smoke._sha256_file(composite_ledger_path)
        or any(
            report.get("test_access_authorized") is not False
            for report in (plan, single, multi, language)
        )
    ):
        raise BfclAggregateError("BFCL dev report boundary mismatch")
    single_rows = single.get("records")
    multi_rows = _read_ledger(composite_ledger_path)
    language_rows = language.get("records")
    if not isinstance(single_rows, list) or not isinstance(language_rows, list):
        raise BfclAggregateError("BFCL dev row evidence absent")
    single_ids = [row["case_id"] for row in single_rows]
    multi_ids = [row["case_id"] for row in multi_rows]
    language_ids = [row["case_id"] for row in language_rows]
    all_ids = single_ids + multi_ids + language_ids
    expected_ids = plan.get("split", {}).get("dev_case_ids")
    if (
        len(single_ids) != 122
        or len(multi_ids) != 80
        or len(language_ids) != 14
        or len(all_ids) != len(set(all_ids)) != 216
        or not isinstance(expected_ids, list)
        or set(all_ids) != set(expected_ids)
        or any(row.get("evidence_complete") is not True for row in multi_rows)
    ):
        raise BfclAggregateError("BFCL 216-case denominator invariant failed")
    single_valid = sum(
        bool(row["answer_record"]["official_checker_valid"])
        for row in single_rows
    )
    multi_valid = sum(bool(row["final_valid"]) for row in multi_rows)
    language_valid = sum(
        bool(row["official_checker_valid"]) for row in language_rows
    )
    official_valid = single_valid + multi_valid + language_valid
    if (single_valid, multi_valid, language_valid, official_valid) != (
        106,
        1,
        12,
        119,
    ):
        raise BfclAggregateError("BFCL dev score counts drift")
    latest_model_requests = (
        int(single["local_vllm_requests"])
        + int(multi_generation["execution"]["native_model_requests"])
        + int(language_generation["local_vllm_requests"])
    )
    latest_tokenizer_requests = (
        int(single["local_tokenizer_requests"])
        + int(multi_generation["execution"]["tokenizer_requests"])
        + int(language_generation["local_tokenizer_requests"])
    )
    category_metrics = {
        **single["aggregates"]["per_category"],
        **multi["aggregates"]["by_category"],
        **language["aggregates"]["by_category"],
    }
    return {
        "schema": "milai.dg10.bfcl-dev-aggregate.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "BFCL_ADAPTED_LOCAL_NON_LIVE_216_DEV_CHARACTERIZATION_COMPLETE",
        "quality_outcome": "MODEL_QUALITY_BELOW_TARGET",
        "protocol_label": "ADAPTED_ENDPOINT_PROTOCOL_BFCL_PROMPT_MODE_NON_LEADERBOARD",
        "bfcl_dev_labels_opened": True,
        "bfcl_dev_case_count": 216,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "inputs": {
            "calibration_plan_sha256": dev_smoke._sha256_file(PLAN),
            "single_turn_report_sha256": dev_smoke._sha256_file(SINGLE_REPORT),
            "multi_turn_report_sha256": dev_smoke._sha256_file(MULTITURN_REPORT),
            "multi_turn_composite_ledger_sha256": dev_smoke._sha256_file(
                composite_ledger_path
            ),
            "language_report_sha256": dev_smoke._sha256_file(LANGUAGE_REPORT),
            "multi_turn_generation_report_sha256": dev_smoke._sha256_file(
                MULTITURN_GENERATION_REPORT
            ),
            "language_generation_report_sha256": dev_smoke._sha256_file(
                LANGUAGE_GENERATION_REPORT
            ),
            "builder_sha256": dev_smoke._sha256_file(Path(__file__).resolve()),
        },
        "coverage": {
            "eligible_case_count": 2186,
            "dev_case_count": 216,
            "dev_fraction": round(216 / 2186, 6),
            "dev_case_ids_sha256": plan["split"]["dev_case_ids_sha256"],
            "quarantined_case_count": 4,
            "test_case_count_closed": 1970,
            "single_turn_python_and_no_call": 122,
            "multi_turn": 80,
            "java_and_javascript": 14,
        },
        "aggregates": {
            "case_count": 216,
            "official_valid_count": official_valid,
            "adapted_official_checker_accuracy": round(official_valid / 216, 6),
            "single_turn_supported": {
                "case_count": 122,
                "valid_count": single_valid,
                "accuracy": round(single_valid / 122, 6),
            },
            "multi_turn": {
                "case_count": 80,
                "valid_count": multi_valid,
                "accuracy": round(multi_valid / 80, 6),
            },
            "java_javascript": {
                "case_count": 14,
                "valid_count": language_valid,
                "accuracy": round(language_valid / 14, 6),
            },
            "category_metrics": category_metrics,
        },
        "request_accounting_latest_complete_evidence": {
            "local_vllm_requests": latest_model_requests,
            "local_tokenizer_requests": latest_tokenizer_requests,
            "single_turn_model_requests": 122,
            "multi_turn_model_requests": 1649,
            "language_model_requests": 14,
            "retry_model_calls": 0,
            "hidden_or_extra_model_calls": 0,
            "scoring_model_requests": 0,
        },
        "gate_results": {
            "BMG-03": "MODEL_QUALITY_BELOW_TARGET_DEV_CHARACTERIZATION_COMPLETE",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "test_execution": "NOT_AUTHORIZED",
        },
        "known_limits": [
            "The aggregate mixes official checker functions with a frozen adapted prompt endpoint and is not an official leaderboard score.",
            "Multi-turn final validity preserves generation failure latches and requires both official checkers.",
            "The 216-case dev result does not authorize or include any of the 1,970 frozen test cases.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate complete 216-case BFCL dev")
    parser.add_argument("--composite-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.composite_ledger.resolve())
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "status": report["status"],
                "case_count": 216,
                "accuracy": report["aggregates"][
                    "adapted_official_checker_accuracy"
                ],
                "test_access_authorized": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
