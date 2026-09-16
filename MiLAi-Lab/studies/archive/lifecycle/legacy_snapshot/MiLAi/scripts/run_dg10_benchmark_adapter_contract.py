from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
DATE = "2026-08-21"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
ARMS = ("NO_MEMORY", "NAIVE_RAG", "MILAI_MCP")
PLANNED_MODEL_ROUNDS = {
    "NO_MEMORY": 1,
    "NAIVE_RAG": 1,
    "MILAI_MCP": 2,
}
PLANNED_MCP_CALLS = {
    "NO_MEMORY": 0,
    "NAIVE_RAG": 0,
    "MILAI_MCP": 1,
}
LATIN_SQUARE = (
    ("NO_MEMORY", "NAIVE_RAG", "MILAI_MCP"),
    ("NAIVE_RAG", "MILAI_MCP", "NO_MEMORY"),
    ("MILAI_MCP", "NO_MEMORY", "NAIVE_RAG"),
)
DEFAULT_LONGMEMEVAL_ROOT = WORKSPACE_ROOT / "benchmarks/LongMemEval"
DEFAULT_LONGMEMEVAL_V2_ROOT = WORKSPACE_ROOT / "benchmarks/LongMemEval-V2"
DEFAULT_DATASET_LOCK = (
    ROOT / f"docs/reports/DG-10-benchmark-dataset-lock-candidate.3-{DATE}.json"
)
DEFAULT_FEASIBILITY = (
    ROOT / f"docs/reports/DG-10-benchmark-feasibility-candidate.3-{DATE}.json"
)
DEFAULT_ADAPTER_OUTPUT = (
    ROOT / f"docs/reports/DG-10-benchmark-adapter-contract-candidate.4-{DATE}.json"
)
DEFAULT_CALIBRATION_OUTPUT = (
    ROOT / f"docs/reports/DG-10-benchmark-calibration-plan-candidate.4-{DATE}.json"
)


class AdapterContractError(RuntimeError):
    pass


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode())


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterContractError(f"invalid JSON file: {path}") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise AdapterContractError(
                        f"JSONL row is not an object: {path}:{line_number}"
                    )
                rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterContractError(f"invalid JSONL file: {path}") from exc
    return rows


def _require_report(path: Path, schema: str, status: str) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise AdapterContractError(f"report must be an object: {path}")
    if value.get("schema") != schema or value.get("status") != status:
        raise AdapterContractError(f"report boundary mismatch: {path}")
    if value.get("test_access_authorized") is not False:
        raise AdapterContractError("benchmark test access must remain unauthorized")
    if value.get("quality_thresholds_frozen") is not False:
        raise AdapterContractError("quality thresholds must remain unfrozen")
    return value


def _case_hash(case_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}\0{case_id}".encode()).hexdigest()


def _dev_count(total: int) -> int:
    if total <= 0:
        raise AdapterContractError("case count must be positive")
    return max(1, total // 10)


def _select_dev(case_ids: Sequence[str], salt: str) -> list[str]:
    selected = sorted(case_ids, key=lambda item: (_case_hash(item, salt), item))[
        : _dev_count(len(case_ids))
    ]
    return sorted(selected)


def _latin_square_order(case_id: str) -> tuple[str, str, str]:
    index = int(_case_hash(case_id, "dg10-latin-square-order")[:8], 16) % len(
        LATIN_SQUARE
    )
    return LATIN_SQUARE[index]


def _load_lme_cases(root: Path, allowed_ids_sha256: str) -> list[dict[str, Any]]:
    rows = _load_json(root / "data/longmemeval_s_cleaned.json")
    if not isinstance(rows, list):
        raise AdapterContractError("LongMemEval cleaned small must be a list")
    cases: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise AdapterContractError(f"LongMemEval row is not an object: {index}")
        question_id = row.get("question_id")
        question_type = row.get("question_type")
        if not isinstance(question_id, str) or not isinstance(question_type, str):
            raise AdapterContractError("LongMemEval case identity fields are invalid")
        cases.append(
            {
                "dataset": "LONGMEMEVAL_CLEANED_500",
                "case_id": f"longmemeval:{question_id}",
                "source_case_id": question_id,
                "category": question_type,
                "modality": "TEXT_ONLY",
            }
        )
    source_ids = sorted(case["source_case_id"] for case in cases)
    if _json_sha256(source_ids) != allowed_ids_sha256:
        raise AdapterContractError("LongMemEval case-id digest mismatch")
    return sorted(cases, key=lambda item: item["case_id"])


def _load_lme_v2_cases(root: Path, text_only_ids_sha256: str) -> list[dict[str, Any]]:
    rows = _read_jsonl(root / "data/longmemeval-v2/questions.jsonl")
    cases: list[dict[str, Any]] = []
    for row in rows:
        question_id = row.get("id")
        question_type = row.get("question_type")
        domain = row.get("domain")
        environment = row.get("environment")
        if not all(isinstance(value, str) and value for value in (question_id, question_type, domain, environment)):
            raise AdapterContractError("LongMemEval-V2 case identity fields are invalid")
        if row.get("image"):
            continue
        cases.append(
            {
                "dataset": "LONGMEMEVAL_V2_ADAPTED_TEXT_ONLY",
                "case_id": f"longmemeval_v2:{question_id}",
                "source_case_id": question_id,
                "category": str(question_type),
                "domain": str(domain),
                "environment": str(environment),
                "modality": "TEXT_ONLY_ADAPTED",
            }
        )
    source_ids = sorted(case["source_case_id"] for case in cases)
    if _json_sha256(source_ids) != text_only_ids_sha256:
        raise AdapterContractError("LongMemEval-V2 text-only case-id digest mismatch")
    return sorted(cases, key=lambda item: item["case_id"])


def _case_manifest(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: case[key]
            for key in sorted(case)
            if key in {"case_id", "category", "dataset", "domain", "environment", "modality", "source_case_id"}
        }
        for case in cases
    ]


def _arm_records(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    generation_sha = _json_sha256(_generation_contract())
    output_schema_sha = _json_sha256(_adapter_output_schema())
    records: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case["case_id"])
        order = _latin_square_order(case_id)
        for order_index, arm in enumerate(order):
            records.append(
                {
                    "case_id": case_id,
                    "dataset": case["dataset"],
                    "arm": arm,
                    "latin_square_order_index": order_index,
                    "model_id": MODEL_ID,
                    "generation_contract_sha256": generation_sha,
                    "adapter_output_schema_sha256": output_schema_sha,
                    "raw_prompt_in_report": False,
                    "raw_answer_in_report": False,
                    "planned_native_model_calls": PLANNED_MODEL_ROUNDS[arm],
                    "planned_mcp_calls": PLANNED_MCP_CALLS[arm],
                    "planned_model_round_roles": (
                        ["ANSWER"]
                        if arm != "MILAI_MCP"
                        else ["TOOL_DECISION", "ANSWER_AFTER_MCP_RESULT"]
                    ),
                    "hidden_or_extra_calls_max": 0,
                    "hidden_or_extra_calls_definition": (
                        "native model calls outside the frozen arm-specific planned roles"
                    ),
                    "route_contract": _route_contract(arm),
                }
            )
    return records


def _route_contract(arm: str) -> dict[str, Any]:
    if arm == "NO_MEMORY":
        return {
            "memory_context": "ABSENT",
            "retrieval": "NONE",
            "mcp": "NOT_CALLED",
            "tools": "NONE",
        }
    if arm == "NAIVE_RAG":
        return {
            "memory_context": "FROZEN_SIMPLE_TEXT_RETRIEVAL_RESULT",
            "retrieval": "LOCAL_LEXICAL_OR_OFFICIAL_SIMPLE_BASELINE_CANDIDATE",
            "mcp": "NOT_CALLED",
            "tools": "NONE",
        }
    if arm == "MILAI_MCP":
        return {
            "memory_context": "MCP_RESULT_DATA_ONLY",
            "retrieval": "OPENWORKER_TO_MCP_TO_RUNTIME_CANONICAL_GATE",
            "mcp": "REQUIRED",
            "tools": ["milai_recall"],
        }
    raise AdapterContractError(f"unknown arm: {arm}")


def _generation_contract() -> dict[str, Any]:
    return {
        "model": MODEL_ID,
        "temperature": 0,
        "seed": 20260821,
        "max_output_tokens": 256,
        "tool_choice": "none_except_MILAI_MCP_reader_lite",
        "same_vllm_identity_required": True,
        "same_prompt_template_required": True,
        "same_aggregate_per_case_token_ceiling_required": True,
        "equal_native_call_count_across_arms_required": False,
        "planned_native_model_calls_by_arm": dict(PLANNED_MODEL_ROUNDS),
        "planned_mcp_calls_by_arm": dict(PLANNED_MCP_CALLS),
        "hidden_or_extra_calls_max": 0,
        "hidden_or_extra_calls_definition": (
            "Any model invocation outside the arm-specific planned roles, including "
            "retry, fallback, repair, judge, or answer-influencing auxiliary calls."
        ),
    }


def _prompt_templates() -> dict[str, str]:
    return {
        "system_template": (
            "You answer benchmark questions using only the current question and the "
            "provided memory evidence for the selected arm. Preserve uncertainty and "
            "never turn unsupported or conflicting memory into a certain answer."
        ),
        "user_template": (
            "Dataset: {dataset}\\nCase: {case_id}\\nArm: {arm}\\nQuestion text is "
            "provided by the repo-external benchmark harness and is not materialized "
            "in the MiLAi report."
        ),
        "memory_template": (
            "NO_MEMORY: no memory block. NAIVE_RAG: bounded local retrieval block. "
            "MILAI_MCP: bounded data-only MCP recall result with trace fields."
        ),
    }


def _answer_parser_contract() -> dict[str, Any]:
    return {
        "name": "dg10-local-deterministic-answer-parser-v1",
        "raw_model_output_retained_in_repo": False,
        "rules": [
            "If a final answer is enclosed in \\boxed{...}, use the innermost boxed span.",
            "Otherwise use the final non-empty answer text emitted by the model.",
            "Normalize Unicode whitespace, lowercase where scorer requires it, strip surrounding punctuation where scorer requires it.",
            "Do not call an external LLM or Codex judge.",
        ],
    }


def _scorer_contract() -> dict[str, Any]:
    return {
        "tier": "TIER_1_DETERMINISTIC_RELEASE_INPUT_CANDIDATE",
        "longmemeval": {
            "primary": ["exact_match", "normalized_f1"],
            "by_ability": True,
            "external_judge": False,
        },
        "longmemeval_v2_adapted_text_only": {
            "primary": "local_eval_function_where_deterministic",
            "fallback": ["normalized_phrase_match", "normalized_f1"],
            "external_judge": False,
            "leaderboard_claim": False,
        },
        "safety": {
            "cross_tenant_returns_max": 0,
            "revoked_or_stale_returns_max": 0,
            "authority_escalations_max": 0,
            "live_open_issue_false_closures_max": 0,
            "unsupported_action_safe_answers_max": 0,
            "canonical_unavailable_false_certainty_max": 0,
        },
    }


def _budget_contract() -> dict[str, Any]:
    return {
        "memory_context_tokens": {
            "standard_max": 512,
            "high_max": 1024,
            "hard_ceiling": 1600,
        },
        "session_extra_input_tokens_per_100_turns_max": 30000,
        "retrieval_k_candidates": [1, 3, 5],
        "selected_retrieval_k": None,
        "selected_after_dev_calibration": True,
        "aggregate_per_case_model_token_ceiling": None,
        "aggregate_ceiling_selected_after_dev_calibration": True,
        "planned_model_rounds_by_arm": dict(PLANNED_MODEL_ROUNDS),
        "planned_mcp_calls_by_arm": dict(PLANNED_MCP_CALLS),
    }


def _adapter_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "run_id",
            "case_id",
            "source_case_id",
            "dataset",
            "category",
            "arm",
            "model_id",
            "planned_model_rounds",
            "planned_mcp_calls",
            "native_calls",
            "status",
            "usage",
            "latency_ms",
            "prompt_sha256",
            "trace",
            "answer_record",
        ],
        "additionalProperties": False,
        "properties": {
            "run_id": {"type": "string"},
            "case_id": {"type": "string"},
            "source_case_id": {"type": "string"},
            "dataset": {"type": "string"},
            "category": {"type": "string"},
            "arm": {"type": "string", "enum": list(ARMS)},
            "model_id": {"type": "string", "const": MODEL_ID},
            "planned_model_rounds": {"type": "integer", "minimum": 1, "maximum": 2},
            "planned_mcp_calls": {"type": "integer", "minimum": 0, "maximum": 1},
            "native_calls": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "native_request_id",
                        "model_id",
                        "planned_role",
                        "terminal",
                        "finish_reason",
                        "usage",
                        "latency_ms",
                        "native_receipt_sha256",
                    ],
                    "properties": {
                        "native_request_id": {"type": "string", "minLength": 8},
                        "model_id": {"type": "string", "const": MODEL_ID},
                        "planned_role": {
                            "type": "string",
                            "enum": ["TOOL_DECISION", "ANSWER", "ANSWER_AFTER_MCP_RESULT"],
                        },
                        "terminal": {"type": "boolean"},
                        "finish_reason": {"type": "string"},
                        "usage": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["input_tokens", "output_tokens"],
                            "properties": {
                                "input_tokens": {"type": "integer", "minimum": 0},
                                "output_tokens": {"type": "integer", "minimum": 0},
                            },
                        },
                        "latency_ms": {"type": "number", "minimum": 0},
                        "native_receipt_sha256": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
                    },
                },
            },
            "status": {"type": "string"},
            "usage": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "input_tokens",
                    "output_tokens",
                    "model_rounds",
                    "mcp_rounds",
                    "hidden_or_extra_model_calls",
                ],
                "properties": {
                    "input_tokens": {"type": "integer", "minimum": 0},
                    "output_tokens": {"type": "integer", "minimum": 0},
                    "model_rounds": {"type": "integer", "minimum": 0},
                    "mcp_rounds": {"type": "integer", "minimum": 0},
                    "hidden_or_extra_model_calls": {"type": "integer", "const": 0},
                },
            },
            "latency_ms": {"type": "number", "minimum": 0},
            "prompt_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "trace": {"type": "object"},
            "answer_record": {"type": "object"},
        },
    }


def _split_records(
    lme_cases: Sequence[Mapping[str, Any]],
    lme_v2_cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    lme_ids = [str(case["case_id"]) for case in lme_cases]
    lme_v2_ids = [str(case["case_id"]) for case in lme_v2_cases]
    lme_dev = _select_dev(lme_ids, "dg10-dev-longmemeval")
    lme_v2_dev = _select_dev(lme_v2_ids, "dg10-dev-longmemeval-v2")
    dev = sorted(lme_dev + lme_v2_dev)
    all_ids = sorted(lme_ids + lme_v2_ids)
    test = sorted(set(all_ids) - set(dev))
    return {
        "all_case_count": len(all_ids),
        "all_case_ids_sha256": _json_sha256(all_ids),
        "dev_case_count": len(dev),
        "dev_fraction": round(len(dev) / len(all_ids), 6),
        "dev_case_ids": dev,
        "dev_case_ids_sha256": _json_sha256(dev),
        "test_case_count": len(test),
        "test_case_ids_sha256": _json_sha256(test),
        "per_dataset": {
            "LONGMEMEVAL_CLEANED_500": {
                "total": len(lme_ids),
                "dev": len(lme_dev),
                "dev_case_ids_sha256": _json_sha256(lme_dev),
            },
            "LONGMEMEVAL_V2_ADAPTED_TEXT_ONLY": {
                "total": len(lme_v2_ids),
                "dev": len(lme_v2_dev),
                "dev_case_ids_sha256": _json_sha256(lme_v2_dev),
            },
        },
    }


def build_reports(
    dataset_lock_path: Path = DEFAULT_DATASET_LOCK,
    feasibility_path: Path = DEFAULT_FEASIBILITY,
    longmemeval_root: Path = DEFAULT_LONGMEMEVAL_ROOT,
    longmemeval_v2_root: Path = DEFAULT_LONGMEMEVAL_V2_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset_lock = _require_report(
        dataset_lock_path.resolve(),
        "milai.dg10.benchmark-dataset-lock.v1",
        "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED",
    )
    feasibility = _require_report(
        feasibility_path.resolve(),
        "milai.dg10.benchmark-feasibility.v1",
        "FEASIBILITY_CANDIDATE_REVIEW_REQUIRED",
    )
    lme_ids_sha = dataset_lock["datasets"]["longmemeval"]["files"][
        "data/longmemeval_s_cleaned.json"
    ]["case_ids_sha256"]
    lme_v2_text_sha = dataset_lock["datasets"]["longmemeval_v2"]["question_counts"][
        "text_only_case_ids_sha256"
    ]
    lme_cases = _load_lme_cases(longmemeval_root.resolve(), str(lme_ids_sha))
    lme_v2_cases = _load_lme_v2_cases(longmemeval_v2_root.resolve(), str(lme_v2_text_sha))
    cases = sorted([*lme_cases, *lme_v2_cases], key=lambda item: item["case_id"])
    case_manifest = _case_manifest(cases)
    arm_records = _arm_records(cases)
    split = _split_records(lme_cases, lme_v2_cases)
    prompt_templates = _prompt_templates()
    output_schema = _adapter_output_schema()
    adapter_report = {
        "schema": "milai.dg10.benchmark-adapter-contract.v1",
        "date": DATE,
        "candidate": "candidate.4",
        "status": "ADAPTER_CONTRACT_CANDIDATE_REVIEW_REQUIRED",
        "data_boundary": "PUBLIC_BENCHMARK_METADATA_ONLY_NO_RAW_PROMPT_OR_ANSWER",
        "provider_requests": 0,
        "provider_cost": 0,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "inputs": {
            "dataset_lock_report_sha256": _sha256_file(dataset_lock_path.resolve()),
            "feasibility_report_sha256": _sha256_file(feasibility_path.resolve()),
        },
        "arms": list(ARMS),
        "latin_square": [list(row) for row in LATIN_SQUARE],
        "case_manifest": {
            "case_count": len(case_manifest),
            "case_manifest_sha256": _json_sha256(case_manifest),
            "by_dataset": dict(sorted(Counter(case["dataset"] for case in cases).items())),
            "by_modality": dict(sorted(Counter(case["modality"] for case in cases).items())),
        },
        "arm_request_manifest": {
            "record_count": len(arm_records),
            "records_per_case": 3,
            "manifest_sha256": _json_sha256(arm_records),
        },
        "generation_contract": _generation_contract(),
        "generation_contract_sha256": _json_sha256(_generation_contract()),
        "prompt_templates_sha256": _json_sha256(prompt_templates),
        "answer_parser_contract_sha256": _json_sha256(_answer_parser_contract()),
        "scorer_contract_sha256": _json_sha256(_scorer_contract()),
        "budget_contract_sha256": _json_sha256(_budget_contract()),
        "adapter_output_schema": output_schema,
        "adapter_output_schema_sha256": _json_sha256(output_schema),
        "route_contracts": {arm: _route_contract(arm) for arm in ARMS},
        "planned_round_contract": {
            "model_rounds_by_arm": dict(PLANNED_MODEL_ROUNDS),
            "mcp_calls_by_arm": dict(PLANNED_MCP_CALLS),
            "case_level_denominator_symmetry": True,
            "native_call_count_symmetry": False,
            "hidden_or_extra_model_calls_max": 0,
            "source": "AI_DEV_AUDIT_REPLAYED_AUTHOR_CHANGE_NOT_FORMAL_ACCEPTANCE",
            "dev_audit_receipt": (
                "docs/reviews/DG-10-dev-semantic-audit-receipt-"
                "candidate.1-2026-08-21.json"
            ),
        },
        "benchmark_fixture_authority_contract": {
            "database_and_tenant": "FRESH_ISOLATED_BENCHMARK_ONLY",
            "scope": {"project_ids": ["milai"]},
            "reader_lite_authority": "ACTION_SAFE",
            "reader_lite_consistency": "CANONICAL_REQUIRED",
            "fixture_review_policy_must_be_frozen_before_three_arm_dev_run": True,
            "production_or_real_world_authority_claim": False,
            "integration_bytes_changed": False,
        },
        "gate_results": {
            "BMG-02": "NO_GO_NOT_RUN",
            "BMG-03": feasibility["gate_results"]["BMG-03"],
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "adapter_contract": "CANDIDATE_REVIEW_REQUIRED",
        },
        "known_limits": [
            "This report defines the three-arm adapter contract but does not execute model calls.",
            "No raw benchmark question, answer, haystack text, prompt, memory, model output, or scorer output is stored here.",
            "MILAI_MCP execution still requires the final benchmark runner against the frozen OpenWorker/MCP integration.",
            "MILAI_MCP has two visible planned model rounds (tool decision and answer after MCP result); calls outside planned roles remain forbidden.",
            "A common aggregate per-case token ceiling and benchmark-fixture ingestion policy remain to be selected and frozen by dev calibration.",
            "The final harness must capture each native call ID, role, usage, latency, terminal state and receipt; aggregate-only OpenCode tokens are insufficient.",
        ],
    }
    calibration_report = {
        "schema": "milai.dg10.benchmark-calibration-plan.v1",
        "date": DATE,
        "candidate": "candidate.4",
        "status": "CALIBRATION_PLAN_CANDIDATE_NOT_RUN",
        "data_boundary": "PUBLIC_BENCHMARK_METADATA_ONLY_NO_RAW_PROMPT_OR_ANSWER",
        "provider_requests": 0,
        "provider_cost": 0,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "inputs": {
            "adapter_contract_sha256": _json_sha256(adapter_report),
            "dataset_lock_report_sha256": _sha256_file(dataset_lock_path.resolve()),
            "feasibility_report_sha256": _sha256_file(feasibility_path.resolve()),
        },
        "dev_split": split,
        "dev_split_policy": {
            "max_fraction": 0.10,
            "selection": "deterministic_sha256_lowest_per_dataset",
            "salt_version": "dg10-dev-2026-08-21-v1",
        },
        "schedule": {
            "latin_square": [list(row) for row in LATIN_SQUARE],
            "all_case_arm_schedule_sha256": _json_sha256(
                [
                    {"case_id": case["case_id"], "order": list(_latin_square_order(str(case["case_id"])))}
                    for case in cases
                ]
            ),
            "dev_case_arm_schedule_sha256": _json_sha256(
                [
                    {"case_id": case_id, "order": list(_latin_square_order(case_id))}
                    for case_id in split["dev_case_ids"]
                ]
            ),
        },
        "calibration_inputs_to_freeze_after_run": {
            "prompt_templates_sha256": _json_sha256(prompt_templates),
            "answer_parser_contract": _answer_parser_contract(),
            "answer_parser_contract_sha256": _json_sha256(_answer_parser_contract()),
            "scorer_contract": _scorer_contract(),
            "scorer_contract_sha256": _json_sha256(_scorer_contract()),
            "budget_contract": _budget_contract(),
            "budget_contract_sha256": _json_sha256(_budget_contract()),
            "retrieval_k_candidates": [1, 3, 5],
            "selected_retrieval_k": None,
            "planned_model_rounds_by_arm": dict(PLANNED_MODEL_ROUNDS),
            "planned_mcp_calls_by_arm": dict(PLANNED_MCP_CALLS),
            "aggregate_per_case_model_token_ceiling": None,
            "benchmark_fixture_ingestion_policy_frozen": False,
        },
        "quality_acceptance_update_state": {
            "target_file": "docs/contracts/DG-10-quality-acceptance.yaml",
            "current_status": "CALIBRATION_REQUIRED_NOT_FROZEN",
            "may_update_after_dev_run": True,
            "may_open_test_before_update": False,
            "test_labels_or_outputs_opened_by_this_report": False,
        },
        "gate_results": {
            "BMG-02": "NO_GO_NOT_RUN",
            "BMG-05": "NO_GO_CALIBRATION_NOT_RUN_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "This is a calibration plan, not a calibration result.",
            "It does not compute or freeze quality thresholds.",
            "The full test split remains unopened and unexecuted by this report.",
            "The corrected 1/1/2 planned model-round contract must be exercised on dev before thresholds freeze.",
        ],
    }
    return adapter_report, calibration_report


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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
    parser = argparse.ArgumentParser(
        description="Generate DG-10 three-arm benchmark adapter and calibration-plan candidates"
    )
    parser.add_argument("--dataset-lock", type=Path, default=DEFAULT_DATASET_LOCK)
    parser.add_argument("--feasibility", type=Path, default=DEFAULT_FEASIBILITY)
    parser.add_argument("--longmemeval-root", type=Path, default=DEFAULT_LONGMEMEVAL_ROOT)
    parser.add_argument("--longmemeval-v2-root", type=Path, default=DEFAULT_LONGMEMEVAL_V2_ROOT)
    parser.add_argument("--adapter-output", type=Path, default=DEFAULT_ADAPTER_OUTPUT)
    parser.add_argument("--calibration-output", type=Path, default=DEFAULT_CALIBRATION_OUTPUT)
    args = parser.parse_args()
    adapter_report, calibration_report = build_reports(
        args.dataset_lock,
        args.feasibility,
        args.longmemeval_root,
        args.longmemeval_v2_root,
    )
    _write(args.adapter_output.resolve(), adapter_report)
    _write(args.calibration_output.resolve(), calibration_report)
    print(
        json.dumps(
            {
                "adapter_output": str(args.adapter_output.resolve()),
                "adapter_status": adapter_report["status"],
                "calibration_output": str(args.calibration_output.resolve()),
                "calibration_status": calibration_report["status"],
                "case_count": adapter_report["case_manifest"]["case_count"],
                "arm_record_count": adapter_report["arm_request_manifest"]["record_count"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
